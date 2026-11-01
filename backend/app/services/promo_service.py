"""Teasers and trailers ("promos"): a short cut built from shots the series already has.

A promo is an ordered list of items:
  shot        an existing shot, `trim_seconds` of it starting `start_offset` seconds in; its keyframe and clip are the
              series' normal ones, so anything already made is reused and only missing ones are requested
  title_card  text on a colour card, rendered locally with ffmpeg (no provider)
  narration   one spoken line (a voice request) laid over the item before it
plus a music cue (`promos.music_mood`) laid under everything.

`plan_promo` asks the LLM to pick and order the items (stage `promo_plan`); the code then enforces what must hold
whatever the model says: only real shots, trims within the shot, a spoiler guard, a closing title card and a total
within 10 percent of the target length. The user can edit the list afterwards.
"""
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest, LLMProviderError
from app.providers.llm_factory import get_llm_provider
from app.schemas.llm_stages import PromoPlanResult
from app.services import generation_service as generation
from app.services import keyframe_service, video_service, voice_cast_service
from app.services.asset_store import asset_summary, get_asset
from app.services.llm_stage import LLMStageClient
from app.services.scope_service import get_working_scenes
from app.services.style_bible_service import get_live

KINDS = ("teaser", "trailer")
# kind -> (default seconds, minimum, maximum) and the latest story position a shot may come from (spoiler guard)
DEFAULTS = {"teaser": (20.0, 10.0, 30.0), "trailer": (60.0, 30.0, 120.0)}
SPOILER_LIMIT = {"teaser": 0.7, "trailer": 0.92}
MAX_CANDIDATES = 90
MIN_SHOT_SECONDS = 1.0
TOLERANCE = 0.10
OPEN = ("queued", "blocked", "running", "awaiting_input")
WORDS_PER_SECOND = 2.6


# --- reading ---------------------------------------------------------------------------------------------------------

def _promo(db: Session, promo_id: UUID) -> dict:
    row = db.execute(text("SELECT * FROM promos WHERE id = :p"), {"p": str(promo_id)}).mappings().first()
    if row is None:
        raise LookupError("Promo was not found")
    return dict(row)


def _items(db: Session, promo_id: UUID) -> list[dict]:
    return [dict(r) for r in db.execute(text("SELECT * FROM promo_items WHERE promo_id = :p ORDER BY position, created_at"),
                                        {"p": str(promo_id)}).mappings()]


def _latest(db: Session, kind: str, target_type: str, target_id) -> dict | None:
    row = db.execute(
        text("""SELECT * FROM generation_requests WHERE kind = :k AND target_type = :tt AND target_id = :t
                AND status <> 'rejected' ORDER BY created_at DESC LIMIT 1"""),
        {"k": kind, "tt": target_type, "t": str(target_id)}).mappings().first()
    return dict(row) if row else None


def _req_view(db: Session, row: dict | None) -> dict | None:
    if row is None:
        return None
    asset = get_asset(db, row["result_asset_id"]) if row["result_asset_id"] else None
    return {"request_id": str(row["id"]), "status": row["status"], "review_status": row["review_status"],
            "error_summary": row["error_summary"], "asset": asset_summary(asset)}


def shot_info(db: Session, shot_id) -> dict | None:
    row = db.execute(
        text("""SELECT sh.id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds, sc.id AS scene_id, sc.scene_number,
                       e.id AS episode_id, e.episode_number FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id
                JOIN episodes e ON e.id = sc.episode_id WHERE sh.id = :s"""), {"s": str(shot_id)}).mappings().first()
    return dict(row) if row else None


def _keyframe_of(db: Session, shot_id) -> dict | None:
    """The newest finished keyframe request of a shot that was not rejected (approved ones first)."""
    row = db.execute(
        text("""SELECT * FROM generation_requests WHERE kind = 'keyframe' AND target_id = :s AND status = 'succeeded'
                AND result_asset_id IS NOT NULL AND review_status <> 'rejected'
                ORDER BY (review_status = 'approved') DESC, created_at DESC LIMIT 1"""), {"s": str(shot_id)}).mappings().first()
    return dict(row) if row else None


def _clip_of(db: Session, shot_id) -> dict | None:
    row = db.execute(
        text("""SELECT * FROM generation_requests WHERE kind = 'video_clip' AND target_id = :s AND status <> 'rejected'
                ORDER BY created_at DESC LIMIT 1"""), {"s": str(shot_id)}).mappings().first()
    return dict(row) if row else None


def _item_view(db: Session, item: dict) -> dict:
    view = {"id": str(item["id"]), "position": item["position"], "type": item["item_type"], "text": item["text"],
            "seconds": float(item["seconds"]) if item["seconds"] is not None else None,
            "trim_seconds": float(item["trim_seconds"]) if item["trim_seconds"] is not None else None,
            "start_offset": float(item["start_offset"] or 0), "style": item["style"] or {}, "reason": item["reason"],
            "shot_id": str(item["shot_id"]) if item["shot_id"] else None}
    if item["item_type"] == "shot":
        info = shot_info(db, item["shot_id"]) if item["shot_id"] else None
        view["shot"] = None if info is None else {
            "episode_number": info["episode_number"], "scene_number": info["scene_number"], "shot_number": info["shot_number"],
            "description": info["description"], "camera": info["camera"],
            "duration_seconds": float(info["duration_seconds"]) if info["duration_seconds"] is not None else None}
        view["keyframe"] = _req_view(db, _keyframe_of(db, item["shot_id"])) if item["shot_id"] else None
        view["clip"] = _req_view(db, _clip_of(db, item["shot_id"])) if item["shot_id"] else None
    elif item["item_type"] == "narration":
        view["voice"] = _req_view(db, _latest(db, "voice_line", "promo_item", item["id"]))
    return view


def promo_seconds(items: list[dict]) -> float:
    """Playing time: shots' trims plus title cards' seconds (narration plays over the picture)."""
    total = 0.0
    for item in items:
        if item["item_type"] == "shot":
            total += float(item["trim_seconds"] or 0)
        elif item["item_type"] == "title_card":
            total += float(item["seconds"] or 0)
    return round(total, 2)


def get_promo(db: Session, promo_id: UUID) -> dict:
    """The promo with its items, thumbnails' state, the music request and what is still missing."""
    promo = _promo(db, promo_id)
    items = _items(db, promo_id)
    views = [_item_view(db, i) for i in items]
    music = _req_view(db, _latest(db, "music", "promo", promo_id))
    shots = [v for v in views if v["type"] == "shot"]
    progress = {
        "shots": len(shots), "with_keyframe": sum(1 for v in shots if v["keyframe"]),
        "with_clip": sum(1 for v in shots if v["clip"] and v["clip"]["status"] == "succeeded"),
        "approved_clips": sum(1 for v in shots if v["clip"] and v["clip"]["status"] == "succeeded"
                              and v["clip"]["review_status"] == "approved"),
        "working": sum(1 for v in views for r in ((v.get("keyframe"), v.get("clip"), v.get("voice"))) if r and r["status"] in OPEN)
                   + (1 if music and music["status"] in OPEN else 0),
        "narration": sum(1 for v in views if v["type"] == "narration"),
        "narration_ready": sum(1 for v in views if v["type"] == "narration" and v.get("voice") and v["voice"]["status"] == "succeeded")}
    low, high = promo_range(float(promo["target_duration_seconds"]))
    seconds = promo_seconds(items)
    return {"id": str(promo["id"]), "series_id": str(promo["series_id"]), "kind": promo["kind"], "title": promo["title"],
            "target_duration_seconds": float(promo["target_duration_seconds"]), "status": promo["status"],
            "notes": promo["notes"], "hook": promo["hook"], "music_mood": promo["music_mood"], "created_at": promo["created_at"],
            "updated_at": promo["updated_at"], "items": views, "music": music, "seconds": seconds,
            "within_target": low <= seconds <= high, "progress": progress}


def list_promos(db: Session, series_id: UUID) -> list[dict]:
    rows = db.execute(text("SELECT id FROM promos WHERE series_id = :s ORDER BY created_at DESC"), {"s": str(series_id)}).all()
    return [get_promo(db, r[0]) for r in rows]


def promo_range(target: float) -> tuple[float, float]:
    return target * (1 - TOLERANCE), target * (1 + TOLERANCE)


# --- creating and editing --------------------------------------------------------------------------------------------

def create_promo(db: Session, series_id: UUID, kind: str, title: str | None = None, target_seconds: float | None = None,
                 notes: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError("kind must be teaser or trailer")
    default, low, high = DEFAULTS[kind]
    target = float(target_seconds or default)
    if not 3 <= target <= 600:
        raise ValueError("The target length must be between 3 and 600 seconds")
    series = db.execute(text("SELECT title FROM series WHERE id = :s"), {"s": str(series_id)}).mappings().first()
    if series is None:
        raise LookupError("Series was not found")
    row = db.execute(
        text("""INSERT INTO promos (series_id, kind, title, target_duration_seconds, notes) VALUES (:s, :k, :t, :d, :n)
                RETURNING id"""),
        {"s": str(series_id), "k": kind, "t": (title or f"{series['title']} {kind}").strip(), "d": target, "n": notes}).one()
    return get_promo(db, row[0])


def update_promo(db: Session, promo_id: UUID, changes: dict) -> dict:
    allowed = {"title", "target_duration_seconds", "notes", "hook", "music_mood"}
    sets, params = [], {"p": str(promo_id)}
    for key, value in changes.items():
        if key not in allowed:
            continue
        if key == "target_duration_seconds" and (value is None or not 3 <= float(value) <= 600):
            raise ValueError("The target length must be between 3 and 600 seconds")
        sets.append(f"{key} = :{key}")
        params[key] = value
    if sets:
        _promo(db, promo_id)
        db.execute(text(f"UPDATE promos SET {', '.join(sets)}, updated_at = now() WHERE id = :p"), params)
    return get_promo(db, promo_id)


def delete_promo(db: Session, promo_id: UUID) -> None:
    _promo(db, promo_id)
    db.execute(text("DELETE FROM promos WHERE id = :p"), {"p": str(promo_id)})


def _renumber(db: Session, promo_id: UUID) -> None:
    for position, item in enumerate(_items(db, promo_id), start=1):
        if item["position"] != position:
            db.execute(text("UPDATE promo_items SET position = :n WHERE id = :i"), {"n": position, "i": str(item["id"])})


def add_item(db: Session, promo_id: UUID, item_type: str, *, shot_id: UUID | None = None, trim_seconds: float | None = None,
             start_offset: float = 0.0, seconds: float | None = None, text_value: str | None = None,
             subtitle: str | None = None, position: int | None = None, reason: str | None = None) -> dict:
    promo = _promo(db, promo_id)
    if item_type == "shot":
        info = shot_info(db, shot_id) if shot_id else None
        if info is None:
            raise ValueError("A shot item needs an existing shot")
        full = float(info["duration_seconds"] or video_service.DEFAULT_SHOT_SECONDS)
        trim = min(float(trim_seconds or min(3.0, full)), full)
        offset = min(max(float(start_offset or 0), 0.0), max(full - trim, 0.0))
        values = {"shot": str(shot_id), "trim": round(trim, 2), "off": round(offset, 2), "sec": None, "text": None, "style": {}}
    elif item_type == "title_card":
        if not (text_value or "").strip():
            raise ValueError("A title card needs text")
        values = {"shot": None, "trim": None, "off": 0, "sec": round(float(seconds or 2.0), 2), "text": text_value.strip(),
                  "style": {"subtitle": subtitle.strip()} if subtitle and subtitle.strip() else {}}
    elif item_type == "narration":
        if not (text_value or "").strip():
            raise ValueError("A narration line needs text")
        spoken = max(1.0, len(text_value.split()) / WORDS_PER_SECOND + 0.3)
        values = {"shot": None, "trim": None, "off": 0, "sec": round(spoken, 2), "text": text_value.strip(), "style": {}}
    else:
        raise ValueError("item type must be shot, title_card or narration")
    count = len(_items(db, promo_id))
    at = count + 1 if position is None else min(max(int(position), 1), count + 1)
    db.execute(text("UPDATE promo_items SET position = position + 1 WHERE promo_id = :p AND position >= :at"),
               {"p": str(promo_id), "at": at})
    row = db.execute(
        text("""INSERT INTO promo_items (promo_id, position, item_type, shot_id, trim_seconds, start_offset, seconds, text, style, reason)
                VALUES (:p, :at, :type, :shot, :trim, :off, :sec, :text, CAST(:style AS jsonb), :reason) RETURNING *"""),
        {"p": str(promo_id), "at": at, "type": item_type, "shot": values["shot"], "trim": values["trim"], "off": values["off"],
         "sec": values["sec"], "text": values["text"], "style": json.dumps(values["style"]), "reason": reason}).mappings().one()
    db.execute(text("UPDATE promos SET updated_at = now() WHERE id = :p"), {"p": str(promo["id"])})
    return _item_view(db, dict(row))


def update_item(db: Session, promo_id: UUID, item_id: UUID, changes: dict) -> dict:
    item = next((i for i in _items(db, promo_id) if i["id"] == item_id), None)
    if item is None:
        raise LookupError("Item was not found in this promo")
    sets, params = [], {"i": str(item_id)}
    if item["item_type"] == "shot":
        info = shot_info(db, item["shot_id"])
        full = float(info["duration_seconds"] or video_service.DEFAULT_SHOT_SECONDS) if info else 10.0
        trim = min(float(changes.get("trim_seconds", item["trim_seconds"]) or 0) or 3.0, full)
        offset = min(max(float(changes.get("start_offset", item["start_offset"]) or 0), 0.0), max(full - trim, 0.0))
        sets += ["trim_seconds = :trim", "start_offset = :off"]
        params.update(trim=round(trim, 2), off=round(offset, 2))
    else:
        if "text" in changes:
            if not (changes["text"] or "").strip():
                raise ValueError("The text cannot be empty")
            sets.append("text = :text")
            params["text"] = changes["text"].strip()
        if item["item_type"] == "title_card" and "seconds" in changes and changes["seconds"]:
            sets.append("seconds = :sec")
            params["sec"] = round(min(max(float(changes["seconds"]), 0.5), 10.0), 2)
        if item["item_type"] == "title_card" and "subtitle" in changes:
            style = dict(item["style"] or {})
            style["subtitle"] = (changes["subtitle"] or "").strip()
            sets.append("style = CAST(:style AS jsonb)")
            params["style"] = json.dumps(style)
        if item["item_type"] == "narration" and "text" in changes:
            sets.append("seconds = :sec")
            params["sec"] = round(max(1.0, len(params["text"].split()) / WORDS_PER_SECOND + 0.3), 2)
    if sets:
        db.execute(text(f"UPDATE promo_items SET {', '.join(sets)} WHERE id = :i"), params)
        db.execute(text("UPDATE promos SET updated_at = now() WHERE id = :p"), {"p": str(promo_id)})
    refreshed = db.execute(text("SELECT * FROM promo_items WHERE id = :i"), {"i": str(item_id)}).mappings().one()
    return _item_view(db, dict(refreshed))


def delete_item(db: Session, promo_id: UUID, item_id: UUID) -> None:
    if not any(i["id"] == item_id for i in _items(db, promo_id)):
        raise LookupError("Item was not found in this promo")
    db.execute(text("DELETE FROM promo_items WHERE id = :i"), {"i": str(item_id)})
    _renumber(db, promo_id)
    db.execute(text("UPDATE promos SET updated_at = now() WHERE id = :p"), {"p": str(promo_id)})


def reorder_items(db: Session, promo_id: UUID, ordered_ids: list[UUID]) -> dict:
    current = [i["id"] for i in _items(db, promo_id)]
    if sorted(map(str, ordered_ids)) != sorted(map(str, current)):
        raise ValueError("The list must contain every item of the promo exactly once")
    for position, item_id in enumerate(ordered_ids, start=1):
        db.execute(text("UPDATE promo_items SET position = :n WHERE id = :i"), {"n": position, "i": str(item_id)})
    db.execute(text("UPDATE promos SET updated_at = now() WHERE id = :p"), {"p": str(promo_id)})
    return get_promo(db, promo_id)


# --- planning --------------------------------------------------------------------------------------------------------

def _candidates(db: Session, series_id: UUID) -> list[dict]:
    """Every shot of the series in story order, with where it falls in the story and whether its picture exists."""
    rows = db.execute(
        text("""SELECT sh.id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds, sc.id AS scene_id, sc.scene_number,
                       e.id AS episode_id, e.episode_number
                FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id JOIN episodes e ON e.id = sc.episode_id
                WHERE e.series_id = :s ORDER BY e.episode_number, sc.scene_number, sh.shot_number"""), {"s": str(series_id)}).mappings().all()
    if not rows:
        return []
    ready = {str(r[0]) for r in db.execute(
        text("""SELECT DISTINCT target_id FROM generation_requests WHERE series_id = :s AND kind IN ('keyframe', 'video_clip')
                AND status = 'succeeded' AND result_asset_id IS NOT NULL AND review_status <> 'rejected'"""), {"s": str(series_id)})}
    working = {}
    for episode_id in {r["episode_id"] for r in rows}:
        working[str(episode_id)] = get_working_scenes(db, episode_id)
    total = len(rows)
    out = []
    for index, row in enumerate(rows):
        chosen = working.get(str(row["episode_id"]))
        out.append({"shot_id": str(row["id"]), "episode": row["episode_number"], "scene": row["scene_number"],
                    "shot": row["shot_number"], "description": (row["description"] or "")[:140],
                    "camera": row["camera"] or "", "seconds": float(row["duration_seconds"] or video_service.DEFAULT_SHOT_SECONDS),
                    "position": round(index / max(total - 1, 1), 3), "ready": str(row["id"]) in ready,
                    "working": chosen is not None and str(row["scene_id"]) in chosen})
    return out


def _limit_candidates(candidates: list[dict], kind: str) -> list[dict]:
    """The shots the model may choose from: none past the spoiler limit, and at most MAX_CANDIDATES (shots that are
    ready or in the working scenes first, then an even spread)."""
    allowed = [c for c in candidates if c["position"] < SPOILER_LIMIT[kind]]
    if len(allowed) <= MAX_CANDIDATES:
        return allowed
    keep = [c for c in allowed if c["ready"] or c["working"]][:MAX_CANDIDATES // 2]
    taken = {c["shot_id"] for c in keep}
    rest = [c for c in allowed if c["shot_id"] not in taken]
    step = max(len(rest) // (MAX_CANDIDATES - len(keep)), 1)
    keep += rest[::step][:MAX_CANDIDATES - len(keep)]
    return sorted(keep, key=lambda c: c["position"])


def normalise_plan(result: PromoPlanResult, candidates: dict[int, dict], *, kind: str, target: float,
                   closing_title: str) -> tuple[list[dict], list[str]]:
    """Turn the model's items into valid ones and make the total fit the target. Returns (items, notes about what changed).
    Item dicts: {type, shot_id, trim, offset, seconds, text, subtitle, reason}."""
    notes: list[str] = []
    items: list[dict] = []
    for raw in result.items:
        kind_of = (raw.type or "shot").strip().lower()
        if kind_of == "shot":
            cand = candidates.get(raw.ref) if raw.ref is not None else None
            if cand is None:
                notes.append(f"Dropped a shot the model referred to as {raw.ref}: it is not one of the candidates.")
                continue
            if cand["position"] >= SPOILER_LIMIT[kind]:
                notes.append("Dropped a shot from the end of the story (spoiler guard).")
                continue
            trim = min(max(float(raw.seconds or 3.0), MIN_SHOT_SECONDS), cand["seconds"])
            offset = min(max(float(raw.start_offset or 0.0), 0.0), max(cand["seconds"] - trim, 0.0))
            items.append({"type": "shot", "shot_id": cand["shot_id"], "trim": trim, "offset": offset, "max": cand["seconds"],
                          "reason": raw.reason})
        elif kind_of == "title_card" and (raw.text or "").strip():
            items.append({"type": "title_card", "text": raw.text.strip(), "subtitle": (raw.subtitle or "").strip(),
                          "seconds": min(max(float(raw.seconds or 2.0), 1.0), 5.0)})
        elif kind_of == "narration" and (raw.text or "").strip():
            items.append({"type": "narration", "text": raw.text.strip()})
    # A promo always ends on a title card.
    visual = [i for i in items if i["type"] != "narration"]
    if not visual or visual[-1]["type"] != "title_card":
        items.append({"type": "title_card", "text": closing_title, "subtitle": "Coming soon", "seconds": 2.5})
        notes.append("Added a closing title card.")
    # Narration with nothing to play over goes (it must follow a picture item).
    items = [i for n, i in enumerate(items) if not (i["type"] == "narration" and n == 0)]
    low, high = promo_range(target)

    def total() -> float:
        return sum(i["trim"] if i["type"] == "shot" else i["seconds"] for i in items if i["type"] != "narration")

    # Too long: shorten shots proportionally (not below the minimum), then drop the weakest middle shots.
    if total() > high:
        cards = sum(i["seconds"] for i in items if i["type"] == "title_card")
        shots = [i for i in items if i["type"] == "shot"]
        if shots:
            factor = max((target - cards) / max(sum(i["trim"] for i in shots), 0.01), 0.0)
            for i in shots:
                i["trim"] = max(MIN_SHOT_SECONDS, round(i["trim"] * min(factor, 1.0), 2))
                i["offset"] = min(i["offset"], max(i["max"] - i["trim"], 0.0))
            notes.append("Shortened shots to fit the target length.")
        while total() > high:
            middle = [n for n, i in enumerate(items) if i["type"] == "shot"][1:-1] or [n for n, i in enumerate(items) if i["type"] == "shot"][1:]
            if not middle:
                break
            items.pop(middle[len(middle) // 2])
            notes.append("Dropped a shot to fit the target length.")
    # Too short: lengthen shots up to their own length, round robin.
    if total() < low:
        shots = [i for i in items if i["type"] == "shot"]
        for _ in range(40):
            if total() >= low or not shots:
                break
            grew = False
            for i in shots:
                room = i["max"] - i["trim"]
                if room > 0.05 and total() < low:
                    step = min(room, 0.5)
                    i["trim"] = round(i["trim"] + step, 2)
                    grew = True
            if not grew:
                break
        if total() < low:
            notes.append(f"The plan is {total():.0f}s, shorter than the {target:.0f}s target: add more shots to reach it.")
        else:
            notes.append("Lengthened shots to reach the target length.")
    # Narration seconds are its spoken length.
    for i in items:
        if i["type"] == "narration":
            i["seconds"] = round(max(1.0, len(i["text"].split()) / WORDS_PER_SECOND + 0.3), 2)
    return items, notes


def plan_promo(db: Session, promo_id: UUID, client: LLMStageClient | None = None) -> dict:
    """Ask the LLM for the shot list and replace the promo's items with its (checked) plan. The caller commits."""
    promo = _promo(db, promo_id)
    series_id = promo["series_id"]
    series = db.execute(text("SELECT title, genre, premise FROM series WHERE id = :s"), {"s": str(series_id)}).mappings().one()
    candidates = _limit_candidates(_candidates(db, series_id), promo["kind"])
    if not candidates:
        raise ValueError("This series has no shots yet; break an episode down first")
    numbered = {n: c for n, c in enumerate(candidates, start=1)}
    bible = get_live(db, series_id) or {}
    profile, story_format = "general", "novel"
    try:
        from app.services.adaptation_service import run_context
        _, profile, story_format = run_context(db, series_id)
    except PermanentJobError:
        pass
    data = {"promo": {"kind": promo["kind"], "target_seconds": float(promo["target_duration_seconds"]), "title": promo["title"]},
            "series": {"title": series["title"], "genre": series["genre"], "premise": (series["premise"] or "")[:500],
                       "tone": bible.get("theme_tone") or ""},
            "candidates": [{"ref": n, "episode": c["episode"], "scene": c["scene"], "shot": c["shot"],
                            "description": c["description"], "camera": c["camera"], "seconds": c["seconds"],
                            "position": c["position"], "ready": c["ready"], "working": c["working"]}
                           for n, c in numbered.items()]}
    request = LLMAnalysisRequest(task="promo_plan", profile=profile, context_chunks=[], known_entities={},
                                 story_format=story_format, task_input=data)
    client = client or LLMStageClient(get_llm_provider())
    result = None
    for _ in range(2):  # one retry when the reply does not match the schema
        try:
            result = PromoPlanResult.model_validate(client.analyze(request).payload)
            break
        except ValidationError:
            continue
    if result is None:
        raise LLMProviderError("The promo plan reply did not match the schema twice")
    items, notes = normalise_plan(result, numbered, kind=promo["kind"], target=float(promo["target_duration_seconds"]),
                                  closing_title=series["title"])
    db.execute(text("DELETE FROM promo_items WHERE promo_id = :p"), {"p": str(promo_id)})
    for position, item in enumerate(items, start=1):
        style = {"subtitle": item["subtitle"]} if item.get("subtitle") else {}
        db.execute(
            text("""INSERT INTO promo_items (promo_id, position, item_type, shot_id, trim_seconds, start_offset, seconds, text, style, reason)
                    VALUES (:p, :pos, :type, :shot, :trim, :off, :sec, :text, CAST(:style AS jsonb), :reason)"""),
            {"p": str(promo_id), "pos": position, "type": item["type"], "shot": item.get("shot_id"), "trim": item.get("trim"),
             "off": item.get("offset", 0), "sec": item.get("seconds"), "text": item.get("text"), "style": json.dumps(style),
             "reason": item.get("reason")})
    note = " ".join([(result.notes or "").strip(), *notes]).strip()
    db.execute(text("""UPDATE promos SET status = 'planned', hook = :h, music_mood = :m, notes = :n, updated_at = now() WHERE id = :p"""),
               {"h": result.hook, "m": result.music_mood, "n": note or None, "p": str(promo_id)})
    return get_promo(db, promo_id)


# --- making what the promo needs -------------------------------------------------------------------------------------

def generate_missing(db: Session, promo_id: UUID) -> dict:
    """Request what the promo lacks, through the normal generation flow (so a manual provider works too): a keyframe for
    each shot without one, a clip for each shot whose keyframe is approved and has none, a voice line for each
    narration item and the music. Shots that already have a keyframe or clip are reused as they are. Call it again after
    approving keyframes to request their clips. The caller commits keyframe batches itself."""
    promo = _promo(db, promo_id)
    series_id = promo["series_id"]
    items = _items(db, promo_id)
    by_episode: dict[str, list[str]] = {}
    for item in items:
        if item["item_type"] == "shot" and item["shot_id"]:
            info = shot_info(db, item["shot_id"])
            if info:
                by_episode.setdefault(str(info["episode_id"]), []).append(str(item["shot_id"]))
    summary = {"keyframes_requested": 0, "clips_requested": 0, "clips_waiting_on_keyframe": 0, "voice_lines_requested": 0,
               "music_requested": 0, "reused_keyframes": 0, "reused_clips": 0, "problems": []}
    for episode_id, shot_ids in by_episode.items():
        try:
            made = keyframe_service.generate_for_episode(db, UUID(episode_id), shot_ids=[UUID(s) for s in shot_ids])
            summary["keyframes_requested"] += made["created"]
            summary["reused_keyframes"] += made["skipped"]
        except ValueError as error:
            summary["problems"].append(str(error))
            continue
        planned = video_service.plan_clips(db, UUID(episode_id), shot_ids=shot_ids)
        summary["clips_requested"] += planned["created"]
        summary["reused_clips"] += planned["already_planned"]
        summary["clips_waiting_on_keyframe"] += planned["skipped_no_keyframe"]
    cast = voice_cast_service.get_cast(db, series_id, None)
    for item in items:
        if item["item_type"] != "narration":
            continue
        existing = _latest(db, "voice_line", "promo_item", item["id"])
        if existing and (existing["params"] or {}).get("text") == item["text"]:
            continue
        params = voice_cast_service.voice_params(cast, "", None)
        params.update({"text": item["text"], "promo_id": str(promo_id)})
        generation.create_request(db, series_id, "voice_line", item["text"], target_type="promo_item", target_id=item["id"],
                                  params=params)
        summary["voice_lines_requested"] += 1
    mood = (promo["music_mood"] or "").strip()
    if mood:
        existing = _latest(db, "music", "promo", promo_id)
        if not (existing and existing["prompt"] == mood):
            generation.create_request(
                db, series_id, "music", mood, target_type="promo", target_id=promo_id,
                params={"music_kind": "music", "duration_seconds": min(float(promo["target_duration_seconds"]) + 2, 120.0),
                        "promo_id": str(promo_id)})
            summary["music_requested"] += 1
    db.commit()
    return summary
