"""Prompts for keyframes (image) and shot clips (video), built from one shot and the series style bible.

Keyframe prompt: the full style block, then the scene, the shot, the camera as prose (image and video providers like
Muse have no camera controls), the look of the place, the look of each character in the shot, and an "Avoid" line.
The same avoid text is also returned as `negative_prompt` for providers that have such a field.

Video prompt: short. The clip starts from the approved keyframe, which already carries the look, so repeating the
whole style block would only invite the model to restyle it. It holds the motion, the duration and a few style words.

`load_shot_context` reads everything a prompt needs; `build_*` are pure functions of that dict and the bible.
"""
import re
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.style_bible_service import negative_block, style_block

MAX_OBJECTS = 2
NO_TEXT = "A single still image. No text, captions, subtitles or watermark."


@dataclass
class KeyframePrompt:
    prompt: str
    negative_prompt: str
    # What was attached, in order: [{"role": "style_anchor"|"character"|"place"|"object"|"continuity", "label": str,
    # "entity_id": str|None, "look_id": str|None}]. The caller fills the asset ids from approved reference requests.
    reference_slots: list[dict] = field(default_factory=list)


def _clean(value) -> str:
    return (value or "").strip() if isinstance(value, str) else ""


def _words(value: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", value.lower()) if len(w) > 3}


# ---------------------------------------------------------------- reading the shot

def _live_look(db: Session, table_sql: str, params: dict) -> dict | None:
    """The approved look, else the newest one that is not superseded."""
    row = db.execute(text(table_sql), params).mappings().first()
    return dict(row) if row else None


def _character_look(db: Session, character_id) -> dict | None:
    """Which costume or age version applies. Versions have no story position yet, so: the approved one, else the
    newest draft. (A later change can pick by the shot's story position without touching the prompt builder.)"""
    return _live_look(
        db, """SELECT id, version_number, description, face_and_body_design, clothing_and_accessories,
                      distinctive_features, color_palette, status
               FROM character_versions WHERE character_id = :c AND status IN ('approved', 'draft')
               ORDER BY (status = 'approved') DESC, version_number DESC LIMIT 1""", {"c": str(character_id)})


def _entity_look(db: Session, entity_type: str, entity_id) -> dict | None:
    return _live_look(
        db, """SELECT id, version_number, description, form, atmosphere, distinctive_features, color_palette, status
               FROM entity_looks WHERE entity_type = :t AND entity_id = :e AND status IN ('approved', 'draft')
               ORDER BY (status = 'approved') DESC, version_number DESC LIMIT 1""", {"t": entity_type, "e": str(entity_id)})


def _match_location(db: Session, series_id, name: str | None) -> dict | None:
    if not _clean(name):
        return None
    wanted = name.strip().lower()
    rows = db.execute(
        text("""SELECT id, name, description FROM locations WHERE series_id = :s AND merged_into_id IS NULL
                AND review_status <> 'stale'"""), {"s": str(series_id)}).mappings().all()
    for row in rows:  # exact name first, then one name containing the other ("The kitchen" / "Kitchen at night")
        if row["name"].strip().lower() == wanted:
            return dict(row)
    for row in rows:
        other = row["name"].strip().lower()
        if other and (other in wanted or wanted in other):
            return dict(row)
    return None


def load_shot_context(db: Session, shot_id: UUID) -> dict:
    """Everything the prompts need for one shot. Raises LookupError when the shot does not exist."""
    shot = db.execute(
        text("""SELECT sh.id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds, sh.character_ids,
                       sc.id AS scene_id, sc.scene_number, sc.title AS scene_title, sc.description AS scene_description,
                       sc.continuity_state, sc.environment_notes, e.id AS episode_id, e.episode_number,
                       e.title AS episode_title, e.synopsis AS episode_synopsis, e.series_id
                FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id JOIN episodes e ON e.id = sc.episode_id
                WHERE sh.id = :s"""), {"s": str(shot_id)}).mappings().first()
    if shot is None:
        raise LookupError("Shot was not found")
    ctx = dict(shot)
    state = ctx.pop("continuity_state") or {}
    ctx["location_name"] = state.get("location")
    ctx["time_of_day"] = state.get("time_of_day")
    series_id = ctx["series_id"]

    characters = []
    for character_id in ctx["character_ids"] or []:
        row = db.execute(text("SELECT id, name, description FROM characters WHERE id = :c"), {"c": str(character_id)}).mappings().first()
        if row is None:
            continue
        characters.append({"id": str(row["id"]), "name": row["name"], "summary": _clean(row["description"]),
                           "look": _character_look(db, row["id"])})
    ctx["characters"] = characters

    place = _match_location(db, series_id, ctx["location_name"])
    ctx["place"] = ({"id": str(place["id"]), "name": place["name"], "summary": _clean(place["description"]),
                     "look": _entity_look(db, "location", place["id"])} if place else None)

    haystack = f"{ctx['description']} {ctx['scene_description'] or ''}".lower()
    objects = []
    for row in db.execute(
            text("""SELECT id, name, description, distinctive_features FROM continuity_objects
                    WHERE series_id = :s AND merged_into_id IS NULL AND review_status <> 'stale'"""),
            {"s": str(series_id)}).mappings():
        if len(row["name"].strip()) > 2 and row["name"].strip().lower() in haystack:
            objects.append({"id": str(row["id"]), "name": row["name"], "summary": _clean(row["description"]),
                            "look": _entity_look(db, "object", row["id"])})
        if len(objects) >= MAX_OBJECTS:
            break
    ctx["objects"] = objects

    previous = db.execute(
        text("""SELECT id FROM shots WHERE scene_id = :sc AND shot_number < :n ORDER BY shot_number DESC LIMIT 1"""),
        {"sc": str(ctx["scene_id"]), "n": ctx["shot_number"]}).scalar()
    ctx["previous_shot_id"] = str(previous) if previous else None
    ctx["id"] = str(ctx["id"])
    return ctx


# ---------------------------------------------------------------- prompt text

def _palette(look: dict | None) -> str:
    colors = (look or {}).get("color_palette") or []
    return ", ".join(str(c) for c in colors[:6]) if isinstance(colors, list) else ""


def _sentence(label: str, value: str) -> str:
    value = value.strip().rstrip(".")
    return f"{label}: {value}." if value else ""


def _character_text(character: dict) -> str:
    look = character["look"] or {}
    parts = [_sentence("Face and body", _clean(look.get("face_and_body_design"))),
             _sentence("Clothing", _clean(look.get("clothing_and_accessories"))),
             _sentence("Distinctive", _clean(look.get("distinctive_features")))]
    detail = " ".join(p for p in parts if p) or _sentence("Look", _clean(look.get("description")) or character["summary"])
    palette = _palette(look)
    return f"{character['name']}. {detail}" + (f" Colours: {palette}." if palette else "")


def _entity_text(entity: dict) -> str:
    look = entity["look"] or {}
    parts = [_sentence("Look", _clean(look.get("description")) or entity["summary"]),
             _sentence("Form", _clean(look.get("form"))), _sentence("Atmosphere", _clean(look.get("atmosphere"))),
             _sentence("Features", _clean(look.get("distinctive_features")))]
    palette = _palette(look)
    return f"{entity['name']}. {' '.join(p for p in parts if p)}" + (f" Colours: {palette}." if palette else "")


MOVES = ("pan", "tilt", "zoom", "track", "dolly", "push", "pull", "crane", "orbit", "drift", "shake", "handheld", "follow", "sweep", "roll")


def _camera_line(camera: str) -> str:
    camera = camera.strip().rstrip(".")
    if any(word in camera.lower() for word in MOVES):
        return f"Camera and framing: {camera}. Compose the still as the opening frame of that camera move."
    return f"Camera and framing: {camera}."


def _style_exceptions(ctx: dict, bible: dict) -> list[str]:
    """Per-act overrides whose condition reads like this shot's setting (at least half of its words appear in the
    episode, scene or shot text). The condition is free text written by a person, so this is a deliberate heuristic."""
    text_pool = _words(" ".join(_clean(ctx.get(k)) for k in
                                ("episode_title", "episode_synopsis", "scene_title", "scene_description", "description")))
    found = []
    for override in bible.get("per_act_overrides") or []:
        when, change = _clean(override.get("when")), _clean(override.get("change"))
        needed = _words(when)
        if change and needed and len(needed & text_pool) * 2 >= len(needed):
            found.append(change)
    return found


def build_keyframe_prompt(ctx: dict, bible: dict, *, references_expected: bool = True) -> KeyframePrompt:
    """`references_expected`: reference images will be attached, so the prompt tells the model to match them. Left
    out when there are none, so the prompt never points at images that are not there."""
    lines = [style_block(bible)]
    place, scene_bits = ctx["place"], []
    where = (place["name"] if place else _clean(ctx["location_name"]))
    if where:
        scene_bits.append(f"Setting: {where}" + (f", {ctx['time_of_day']}" if _clean(ctx["time_of_day"]) else "") + ".")
    elif _clean(ctx["time_of_day"]):
        scene_bits.append(f"Time of day: {ctx['time_of_day']}.")
    if _clean(ctx["environment_notes"]):
        scene_bits.append(f"Environment: {ctx['environment_notes'].strip()}")
    lines += ["", *scene_bits]
    lines.append(f"Shot: {ctx['description'].strip()}")
    if _clean(ctx["camera"]):
        lines.append(_camera_line(ctx["camera"]))
    if place and (place["look"] or place["summary"]):
        lines.append(f"Place, {_entity_text(place)}")
    for character in ctx["characters"]:
        lines.append(f"Character, {_character_text(character)}")
    for obj in ctx["objects"]:
        lines.append(f"Object, {_entity_text(obj)}")
    for exception in _style_exceptions(ctx, bible):
        lines.append(f"Style exception for this shot: {exception}")
    if references_expected:
        lines.append("Match the attached reference images for the style, the characters, the place and the objects.")
    lines.append(NO_TEXT)
    negative = negative_block(bible)
    if negative:
        lines.append(f"Avoid: {negative}")

    slots = [{"role": "style_anchor", "label": "Style anchor", "entity_id": None, "look_id": None}]
    if place:
        slots.append({"role": "place", "label": f"Place: {place['name']}", "entity_id": place["id"],
                      "look_id": str(place["look"]["id"]) if place["look"] else None})
    for character in ctx["characters"]:
        slots.append({"role": "character", "label": character["name"], "entity_id": character["id"],
                      "look_id": str(character["look"]["id"]) if character["look"] else None})
    for obj in ctx["objects"]:
        slots.append({"role": "object", "label": f"Object: {obj['name']}", "entity_id": obj["id"],
                      "look_id": str(obj["look"]["id"]) if obj["look"] else None})
    return KeyframePrompt(prompt="\n".join(lines).strip(), negative_prompt=negative, reference_slots=slots)


def build_video_prompt(shot: dict, bible: dict) -> dict:
    """Short prompt for animating a shot's approved keyframe. `shot` is a `load_shot_context` dict (or any dict with
    `description`, `camera`, `duration_seconds`; optional `sound_mood`, `environment_notes`).

    Returns {"prompt", "negative_prompt", "sound_prompt", "duration_seconds", "aspect_ratio"} ready for a
    `video_clip` request: first frame = the keyframe, params = duration/aspect/sound_prompt."""
    seconds = float(shot.get("duration_seconds") or 5.0)
    camera = _clean(shot.get("camera"))
    lines = ["Animate the first frame."]
    lines.append(f"Camera: {camera}." if camera else "Camera: steady, slow and subtle.")
    lines.append(f"Action: {shot['description'].strip()}")
    short_style = style_block(bible, short=True)
    if short_style:
        lines.append(f"Look: {short_style}. Keep the look of the first frame.")
    lines.append(f"One continuous shot of {seconds:g} seconds, no cuts, 16:9. Nothing happens after the described action.")
    negative = negative_block(bible)
    if negative:
        lines.append(f"Avoid: {negative}, flicker, warping, morphing, new characters appearing")
    sound = _clean(shot.get("sound_mood"))
    if not sound and _clean(shot.get("environment_notes")):
        sound = f"ambient sound of the scene: {shot['environment_notes'].strip()[:160]}"
    if sound:
        lines.append(f"Sound: {sound}")
    return {"prompt": "\n".join(lines), "negative_prompt": ", ".join(p for p in (negative, "flicker, warping, morphing") if p),
            "sound_prompt": sound, "duration_seconds": seconds, "aspect_ratio": "16:9"}
