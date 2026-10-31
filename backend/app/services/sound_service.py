"""Sound for an episode: dialogue, narration, effects, ambience, music and subtitles.

Flow (all behind provider interfaces, so mock and real providers behave the same):
  design_sound            copies the dialogue lines of every scene and asks the LLM for ambience, music, effects and
                          narration, giving one `sound_cues` row per sound
  generate_episode_sound  design + one generation request per cue (the job body)
  sync_episode            reads finished audio back: measures its length with ffprobe, lays the speech out on the
                          shots and records how well it fits (`sound_shot_fits`)
  build_audio_plan        per shot, the audio tracks and subtitle segments in the shape `app.media.assemble_episode`
                          takes, for the video step
  build_subtitles         SRT files per shot, scene and episode, stored as assets

Nothing here changes a shot's length by itself: a shot too short for its speech gets a suggestion that
`apply_fit` writes only when the user asks.
"""
import hashlib
import json
import math
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.media import probe, to_srt
from app.media.runner import run as run_ffmpeg
from app.providers.llm_base import LLMAnalysisRequest, LLMProviderError
from app.providers.llm_factory import get_llm_provider
from app.schemas.llm_stages import SoundDesignResult
from app.services import generation_service as generation
from app.services import style_bible_service, voice_cast_service
from app.services.asset_store import asset_summary, delete_asset, get_asset, get_storage, save_asset, storage_root
from app.services.llm_stage import LLMStageClient

LEAD = 0.3  # silence before the first line of a shot
GAP = 0.3  # between two lines
TAIL = 0.25  # room left after the last line of a shot
WORDS_PER_SECOND = 2.6
MAX_SCENES_PER_CALL = 8
DEFAULT_SHOT_SECONDS = 3.0
SPEECH = ("dialogue", "narration")
DESIGNED = ("narration", "sfx", "ambience", "music")
GAINS = {"dialogue": 1.0, "narration": 1.0, "sfx": 0.9, "ambience": 0.3, "music": 0.45}
THEME_SECONDS = 20.0


# ----- loading ---------------------------------------------------------------------------------------------------

def _episode(db: Session, episode_id: UUID) -> dict:
    row = db.execute(text("SELECT id, series_id, episode_number, title FROM episodes WHERE id = :e"),
                     {"e": str(episode_id)}).mappings().first()
    if row is None:
        raise PermanentJobError("Episode was not found")
    return dict(row)


def _seconds(value) -> float:
    return float(value) if value else DEFAULT_SHOT_SECONDS


def load_scenes(db: Session, episode_id: UUID) -> list[dict]:
    """Scenes in order, each with its shots (durations as floats) and its dialogue list."""
    scenes = [dict(r) for r in db.execute(
        text("""SELECT id, scene_number, title, description, dialogue, continuity_state, environment_notes
                FROM scenes WHERE episode_id = :e ORDER BY scene_number"""), {"e": str(episode_id)}).mappings()]
    by_scene = {str(s["id"]): s for s in scenes}
    for scene in scenes:
        scene["shots"], scene["dialogue"] = [], scene["dialogue"] or []
    for row in db.execute(
            text("""SELECT sh.id, sh.scene_id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds
                    FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sc.episode_id = :e
                    ORDER BY sc.scene_number, sh.shot_number"""), {"e": str(episode_id)}).mappings():
        shot = dict(row)
        shot["duration"] = _seconds(row["duration_seconds"])
        by_scene[str(row["scene_id"])]["shots"].append(shot)
    return scenes


def _scene_seconds(scene: dict) -> float:
    return sum(s["duration"] for s in scene["shots"]) or DEFAULT_SHOT_SECONDS


def _cues(db: Session, episode_id: UUID) -> list[dict]:
    return [dict(r) for r in db.execute(
        text("SELECT * FROM sound_cues WHERE episode_id = :e ORDER BY created_at, position"), {"e": str(episode_id)}).mappings()]


def _hash(*parts) -> str:
    return hashlib.sha1(json.dumps(parts, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def _estimate(line: str) -> float:
    return round(max(0.8, len(line.split()) / WORDS_PER_SECOND + 0.1), 2)


def _match_character(speaker: str, names: dict[str, str]) -> str | None:
    """Character id for a speaker name: exact, otherwise the one character whose name contains or is contained."""
    key = (speaker or "").strip().lower()
    if not key:
        return None
    if key in names:
        return names[key]
    close = {cid for name, cid in names.items() if name in key or key in name}
    return close.pop() if len(close) == 1 else None


# ----- design: which cues exist ----------------------------------------------------------------------------------

def _context(db: Session, series_id: UUID) -> tuple[str, str]:
    try:
        from app.services.adaptation_service import run_context
        _, profile, story_format = run_context(db, series_id)
        return profile, story_format
    except PermanentJobError:
        return "general", "novel"  # no finished analysis; the design can still be drafted from the scenes


def _run_design(db: Session, episode: dict, scenes: list[dict], client: LLMStageClient | None) -> dict[int, object]:
    series = db.execute(text("SELECT title, genre, premise FROM series WHERE id = :s"),
                        {"s": str(episode["series_id"])}).mappings().one()
    bible = style_bible_service.get_live(db, episode["series_id"])
    profile, story_format = _context(db, episode["series_id"])
    client = client or LLMStageClient(get_llm_provider())
    designed: dict[int, object] = {}
    for start in range(0, len(scenes), MAX_SCENES_PER_CALL):
        batch = scenes[start:start + MAX_SCENES_PER_CALL]
        data = {"series": {"title": series["title"], "genre": series["genre"], "tone": (bible or {}).get("theme_tone") or ""},
                "scenes": [{"scene": s["scene_number"], "title": s["title"], "description": (s["description"] or "")[:500],
                            "location": (s["continuity_state"] or {}).get("location"),
                            "time_of_day": (s["continuity_state"] or {}).get("time_of_day"),
                            "environment_notes": (s["environment_notes"] or "")[:300],
                            "shots": [{"number": sh["shot_number"], "description": sh["description"][:200],
                                       "seconds": sh["duration"]} for sh in s["shots"]],
                            "dialogue_lines": len(s["dialogue"])} for s in batch]}
        request = LLMAnalysisRequest(task="sound_design", profile=profile, context_chunks=[], known_entities={},
                                     story_format=story_format, task_input=data)
        result = None
        for _ in range(2):  # one retry when the reply does not match the schema
            try:
                result = SoundDesignResult.model_validate(client.analyze(request).payload)
                break
            except ValidationError:
                continue
        if result is None:
            raise LLMProviderError("The sound design reply did not match the schema twice")
        for entry in result.scenes:
            designed[entry.scene] = entry
    return designed


def _desired(db: Session, episode: dict, scenes: list[dict], designed: dict[int, object] | None) -> list[dict]:
    """Every cue the episode should have: dialogue always, the designed kinds when a design was just made."""
    names = {n.lower(): str(i) for i, n in db.execute(
        text("SELECT id, name FROM characters WHERE series_id = :s AND merged_into_id IS NULL"),
        {"s": str(episode["series_id"])})}
    out: list[dict] = []
    for scene in scenes:
        for index, line in enumerate(scene["dialogue"], start=1):
            if not (line.get("line") or "").strip():
                continue
            out.append({"scene": scene, "cue_type": "dialogue", "position": index, "speaker": line.get("character"),
                        "character_id": _match_character(line.get("character") or "", names), "text": line["line"].strip(),
                        "delivery": line.get("delivery"), "shot": None, "start": None, "hint": None})
    if designed is None:
        return out
    music = None
    for scene in scenes:
        entry = designed.get(scene["scene_number"])
        if entry is None:
            continue
        seconds = _scene_seconds(scene)
        shots = {s["shot_number"]: s for s in scene["shots"]}
        first = scene["shots"][0] if scene["shots"] else None
        if (entry.ambience or "").strip():
            out.append({"scene": scene, "cue_type": "ambience", "position": 1, "speaker": None, "character_id": None,
                        "text": entry.ambience.strip(), "delivery": None, "shot": first, "start": 0.0, "hint": round(seconds, 1)})
        mood = (entry.music.mood or "").strip() if entry.music else ""
        if entry.music is None:
            music = None
        elif entry.music.continues and music is not None:
            music["hint"] = round(music["hint"] + seconds, 1)
        elif mood:
            music = {"scene": scene, "cue_type": "music", "position": 1, "speaker": None, "character_id": None, "text": mood,
                     "delivery": None, "shot": first, "start": 0.0, "hint": round(seconds, 1)}
            out.append(music)
        for index, effect in enumerate(entry.sfx, start=1):
            shot = shots.get(effect.shot) or first
            if shot is None:
                continue
            at = min(max(effect.at_seconds or 0.0, 0.0), max(shot["duration"] - 0.3, 0.0))
            out.append({"scene": scene, "cue_type": "sfx", "position": index, "speaker": None, "character_id": None,
                        "text": effect.prompt.strip(), "delivery": None, "shot": shot, "start": round(at, 2),
                        "hint": round(min(3.0, max(0.5, shot["duration"] - at)), 1)})
        for index, narration in enumerate(entry.narration, start=1):
            shot = shots.get(narration.shot) or first
            if shot is None:
                continue
            out.append({"scene": scene, "cue_type": "narration", "position": index, "speaker": "Narrator",
                        "character_id": None, "text": narration.text.strip(), "delivery": None, "shot": shot,
                        "start": None, "hint": None})
    return out


def _reconcile(db: Session, episode: dict, desired: list[dict], replace: set[str]) -> dict:
    """Insert new cues, update changed ones (clearing their old audio), delete cues that are gone. A cue whose
    text did not change keeps its audio and its requests."""
    existing = {(str(c["scene_id"]), c["cue_type"], c["position"]): c for c in _cues(db, episode["id"]) if c["role"] == "scene"}
    seen, added, changed = set(), 0, 0
    for item in desired:
        key = (str(item["scene"]["id"]), item["cue_type"], item["position"])
        seen.add(key)
        digest = _hash(item["cue_type"], item["text"], item["delivery"], item["character_id"],
                       item["hint"] if item["cue_type"] in ("sfx", "ambience", "music") else None)
        shot_id = str(item["shot"]["id"]) if item["shot"] else None
        params = {"series": str(episode["series_id"]), "ep": str(episode["id"]), "scene": str(item["scene"]["id"]),
                  "shot": shot_id, "type": item["cue_type"], "pos": item["position"], "char": item["character_id"],
                  "speaker": item["speaker"], "text": item["text"], "delivery": item["delivery"], "start": item["start"],
                  "hint": item["hint"], "hash": digest}
        row = existing.get(key)
        if row is None:
            db.execute(
                text("""INSERT INTO sound_cues (series_id, episode_id, scene_id, shot_id, cue_type, position, character_id,
                            speaker, text, delivery, start_seconds, duration_hint, source_hash)
                        VALUES (:series, :ep, :scene, :shot, :type, :pos, :char, :speaker, :text, :delivery, :start,
                                :hint, :hash)"""), params)
            added += 1
        elif row["source_hash"] != digest:
            db.execute(
                text("""UPDATE sound_cues SET shot_id = COALESCE(:shot, shot_id), character_id = :char, speaker = :speaker,
                            text = :text, delivery = :delivery, start_seconds = COALESCE(:start, start_seconds),
                            duration_hint = :hint, source_hash = :hash, audio_asset_id = NULL, audio_duration = NULL,
                            updated_at = now() WHERE id = :id"""), {**params, "id": str(row["id"])})
            changed += 1
        elif item["cue_type"] in ("sfx", "narration") and shot_id:
            db.execute(text("""UPDATE sound_cues SET shot_id = :shot, start_seconds = COALESCE(:start, start_seconds)
                               WHERE id = :id"""), {"shot": shot_id, "start": item["start"], "id": str(row["id"])})
    removed = 0
    for key, row in existing.items():
        if key not in seen and row["cue_type"] in replace:
            db.execute(text("DELETE FROM sound_cues WHERE id = :id"), {"id": str(row["id"])})
            removed += 1
    return {"added": added, "changed": changed, "removed": removed}


def _ensure_theme(db: Session, series_id: UUID) -> dict:
    series = db.execute(text("SELECT title, genre FROM series WHERE id = :s"), {"s": str(series_id)}).mappings().one()
    bible = style_bible_service.get_live(db, series_id) or {}
    prompt = ", ".join(p for p in (f"main title theme for \"{series['title']}\"", series["genre"], bible.get("theme_tone"),
                                   "memorable melody, about 20 seconds") if p)
    digest = _hash("theme", prompt)
    row = db.execute(text("SELECT * FROM sound_cues WHERE series_id = :s AND role = 'theme'"), {"s": str(series_id)}).mappings().first()
    if row is None:
        db.execute(text("""INSERT INTO sound_cues (series_id, cue_type, role, text, duration_hint, source_hash)
                           VALUES (:s, 'music', 'theme', :t, :d, :h)"""),
                   {"s": str(series_id), "t": prompt, "d": THEME_SECONDS, "h": digest})
    elif row["source_hash"] != digest:
        db.execute(text("""UPDATE sound_cues SET text = :t, source_hash = :h, audio_asset_id = NULL, audio_duration = NULL,
                           updated_at = now() WHERE id = :id"""), {"t": prompt, "h": digest, "id": str(row["id"])})
    return dict(db.execute(text("SELECT * FROM sound_cues WHERE series_id = :s AND role = 'theme'"),
                           {"s": str(series_id)}).mappings().one())


def design_sound(db: Session, episode_id: UUID, client: LLMStageClient | None = None, redesign: bool = False) -> dict:
    """Make the cue list for an episode. Dialogue is always re-read from the breakdown; the designed kinds (ambience,
    music, effects, narration) are written by the LLM once and kept unless `redesign`. The caller commits."""
    episode = _episode(db, episode_id)
    scenes = load_scenes(db, episode_id)
    if not scenes or not any(s["shots"] for s in scenes):
        raise PermanentJobError("The episode has no scenes and shots yet; break it down first")
    designed_before = any(c["cue_type"] in DESIGNED for c in _cues(db, episode_id))
    designed = None if designed_before and not redesign else _run_design(db, episode, scenes, client)
    replace = {"dialogue"} | (set(DESIGNED) if designed is not None else set())
    counts = _reconcile(db, episode, _desired(db, episode, scenes, designed), replace)
    _ensure_theme(db, episode["series_id"])
    db.flush()
    relayout(db, episode_id)
    return {**counts, "redesigned": designed is not None}


# ----- layout and fit ----------------------------------------------------------------------------------------------

def _speech_seconds(cue: dict) -> float:
    return float(cue["audio_duration"]) if cue["audio_duration"] is not None else _estimate(cue["text"])


def _lay_out_scene(scene: dict, cues: list[dict]) -> tuple[dict[str, tuple[str, float]], dict[str, dict]]:
    """Place the scene's speech on its shots. Narration sits at the start of the shot it is anchored to; dialogue
    then fills shots in order, moving to the next shot when a line no longer fits. A line that cannot fit even an
    empty shot stays and the shot is marked as overflowing."""
    shots = scene["shots"]
    if not shots:
        return {}, {}
    narration = {}
    for cue in sorted((c for c in cues if c["cue_type"] == "narration"), key=lambda c: c["position"]):
        index = next((i for i, s in enumerate(shots) if str(s["id"]) == str(cue["shot_id"])), 0)
        narration.setdefault(index, []).append(cue)
    pending = sorted((c for c in cues if c["cue_type"] == "dialogue"), key=lambda c: c["position"])
    placed: dict[str, tuple[str, float]] = {}
    fits: dict[str, dict] = {}
    for index, shot in enumerate(shots):
        cursor, ends, total, measured, any_placed = LEAD, [], 0.0, True, False

        def place(cue: dict):
            nonlocal cursor, total, measured, any_placed
            length = _speech_seconds(cue)
            placed[str(cue["id"])] = (str(shot["id"]), round(cursor, 2))
            ends.append(cursor + length)
            total += length
            measured = measured and cue["audio_duration"] is not None
            cursor += length + GAP
            any_placed = True

        for cue in narration.get(index, []):
            place(cue)
        last = index == len(shots) - 1
        while pending:
            if cursor + _speech_seconds(pending[0]) + TAIL <= shot["duration"] or not any_placed or last:
                place(pending.pop(0))
            else:
                break
        needed = (max(ends) + TAIL) if ends else 0.0
        status = "empty" if not ends else ("ok" if needed <= shot["duration"] + 0.05 else "overflow")
        fits[str(shot["id"])] = {"audio_seconds": round(total, 2), "shot_seconds": shot["duration"], "status": status,
                                 "suggested": math.ceil(needed * 2) / 2 if status == "overflow" else None,
                                 "measured": measured and bool(ends)}
    return placed, fits


def relayout(db: Session, episode_id: UUID) -> dict:
    """Recompute where every speech cue sits and how well each shot holds its speech. The caller commits."""
    scenes = load_scenes(db, episode_id)
    cues = [c for c in _cues(db, episode_id) if c["cue_type"] in SPEECH]
    by_scene: dict[str, list[dict]] = {}
    for cue in cues:
        by_scene.setdefault(str(cue["scene_id"]), []).append(cue)
    overflow = 0
    for scene in scenes:
        placed, fits = _lay_out_scene(scene, by_scene.get(str(scene["id"]), []))
        for cue_id, (shot_id, start) in placed.items():
            db.execute(text("UPDATE sound_cues SET shot_id = :sh, start_seconds = :st WHERE id = :id"),
                       {"sh": shot_id, "st": start, "id": cue_id})
        for shot_id, fit in fits.items():
            overflow += fit["status"] == "overflow"
            db.execute(
                text("""INSERT INTO sound_shot_fits (shot_id, episode_id, audio_seconds, shot_seconds, suggested_seconds,
                            status, measured) VALUES (:sh, :ep, :a, :s, :g, :st, :m)
                        ON CONFLICT (shot_id) DO UPDATE SET audio_seconds = :a, shot_seconds = :s, suggested_seconds = :g,
                            status = :st, measured = :m, updated_at = now()"""),
                {"sh": shot_id, "ep": str(episode_id), "a": fit["audio_seconds"], "s": fit["shot_seconds"],
                 "g": fit["suggested"], "st": fit["status"], "m": fit["measured"]})
    return {"overflow_shots": overflow}


def apply_fit(db: Session, episode_id: UUID, shot_ids: list[UUID] | None = None) -> dict:
    """Lengthen the shots whose speech does not fit to the suggested length. Only called on the user's request.
    The caller commits."""
    rows = db.execute(
        text("""SELECT f.shot_id, f.suggested_seconds FROM sound_shot_fits f WHERE f.episode_id = :e
                AND f.status = 'overflow' AND f.suggested_seconds IS NOT NULL"""), {"e": str(episode_id)}).mappings().all()
    wanted = {str(s) for s in shot_ids} if shot_ids else None
    applied = []
    for row in rows:
        if wanted is not None and str(row["shot_id"]) not in wanted:
            continue
        db.execute(text("UPDATE shots SET duration_seconds = :d, updated_at = now() WHERE id = :id"),
                   {"d": row["suggested_seconds"], "id": str(row["shot_id"])})
        applied.append({"shot_id": str(row["shot_id"]), "seconds": float(row["suggested_seconds"])})
    relayout(db, episode_id)
    return {"applied": applied}


# ----- generation --------------------------------------------------------------------------------------------------

def _current_requests(db: Session, cue_ids: list, *, accepted_only: bool = False) -> dict[str, dict]:
    """The newest request of each cue made from its current text (a rejected attempt is replaced by a newer one).
    With accepted_only: the newest finished request the user has not rejected."""
    if not cue_ids:
        return {}
    extra = "AND r.status = 'succeeded' AND r.review_status <> 'rejected'" if accepted_only else ""
    rows = db.execute(
        text(f"""SELECT DISTINCT ON (c.id) c.id AS cue_id, r.id, r.status, r.review_status, r.review_note, r.error_summary,
                        r.result_asset_id, r.provider, r.attempt_count
                 FROM sound_cues c JOIN generation_requests r ON r.target_type = 'sound_cue' AND r.target_id = c.id
                      AND r.params ->> 'source_hash' = c.source_hash
                 WHERE c.id = ANY(CAST(:ids AS uuid[])) {extra} ORDER BY c.id, r.created_at DESC"""),
        {"ids": "{" + ",".join(str(i) for i in cue_ids) + "}"}).mappings().all()
    return {str(r["cue_id"]): dict(r) for r in rows}


def _request_for(cue: dict, cast: dict | None, suggestion: str) -> dict:
    kind_params = {"source_hash": cue["source_hash"], "cue_type": cue["cue_type"], "cue_id": str(cue["id"])}
    if cue["cue_type"] in SPEECH:
        params = voice_cast_service.voice_params(cast, suggestion, cue["delivery"])
        params.update(kind_params, text=cue["text"])
        return {"kind": "voice_line", "prompt": cue["text"], "params": params}
    seconds = float(cue["duration_hint"] or (THEME_SECONDS if cue["role"] == "theme" else 3.0))
    music_kind = {"sfx": "sfx", "ambience": "ambience"}.get(cue["cue_type"], "music")
    return {"kind": "sfx" if music_kind != "music" else "music", "prompt": cue["text"],
            "params": {**kind_params, "music_kind": music_kind, "duration_seconds": min(seconds, 120.0)}}


def request_cues(db: Session, series_id: UUID, cues: list[dict]) -> dict:
    """Create a generation request for each cue that has none for its current text. The caller commits."""
    current = _current_requests(db, [c["id"] for c in cues])
    casts, suggestions = {}, {}
    created = existing = 0
    for cue in cues:
        if str(cue["id"]) in current:
            existing += 1
            continue
        narrator = cue["cue_type"] == "narration"
        key = "narrator" if narrator else (str(cue["character_id"]) if cue["character_id"] else "unmatched")
        if cue["cue_type"] in SPEECH and key not in casts:
            if narrator:
                casts[key], suggestions[key] = voice_cast_service.get_cast(db, series_id, None), ""
            elif cue["character_id"]:
                casts[key] = voice_cast_service.get_cast(db, series_id, cue["character_id"])
                suggestions[key] = voice_cast_service.suggested_voice(db, cue["character_id"])
            else:  # a speaker that matches no character gets the provider's default voice
                casts[key], suggestions[key] = None, ""
        spec = _request_for(cue, casts.get(key), suggestions.get(key, ""))
        generation.create_request(db, series_id, spec["kind"], spec["prompt"], target_type="sound_cue", target_id=cue["id"],
                                  params=spec["params"])
        created += 1
    return {"created": created, "existing": existing}


def generate_episode_sound(db: Session, episode_id: UUID, client: LLMStageClient | None = None,
                           redesign: bool = False) -> dict:
    """The job body: design the cues, then queue a request for each. Idempotent. Commits."""
    episode = _episode(db, episode_id)
    design = design_sound(db, episode_id, client, redesign)
    db.commit()
    cues = _cues(db, episode_id)
    theme = db.execute(text("SELECT * FROM sound_cues WHERE series_id = :s AND role = 'theme'"),
                       {"s": str(episode["series_id"])}).mappings().first()
    result = request_cues(db, episode["series_id"], cues + ([dict(theme)] if theme else []))
    db.commit()
    return {"cues": len(cues), **design, **result}


def queue_sound_job(db: Session, episode_id: UUID, redesign: bool = False) -> dict:
    """Queue the bulk job. Raises ValueError when one is already queued or running. The caller commits."""
    active = db.execute(
        text("""SELECT id FROM generation_jobs WHERE job_type = 'sound_generation' AND status IN ('queued', 'running')
                AND request_metadata ->> 'sound_episode_id' = :e"""), {"e": str(episode_id)}).scalar()
    if active:
        raise ValueError("Sound for this episode is already being generated")
    row = db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                VALUES ('sound_generation', 'queued', 'media', CAST(:m AS jsonb)) RETURNING id, job_type, status, created_at"""),
        {"m": json.dumps({"sound_episode_id": str(episode_id), "redesign": bool(redesign)})}).mappings().one()
    return dict(row)


# ----- reading finished audio back ---------------------------------------------------------------------------------

def _measure(db: Session, asset: dict) -> float | None:
    path = get_storage().local_path(asset["storage_key"])
    if path is not None:
        try:
            return round(probe(path).duration, 2)
        except Exception:  # noqa: BLE001 - a file ffprobe cannot read falls back to what the provider reported
            pass
    return float(asset["duration_seconds"]) if asset["duration_seconds"] is not None else None


def sync_episode(db: Session, episode_id: UUID) -> dict:
    """Pick up audio that has finished (or been rejected) since the last look, measure it, then re-lay-out the
    speech. The caller commits."""
    cues = _cues(db, episode_id)
    theme = db.execute(text("""SELECT c.* FROM sound_cues c JOIN episodes e ON e.series_id = c.series_id
                               WHERE e.id = :e AND c.role = 'theme'"""), {"e": str(episode_id)}).mappings().first()
    if theme:
        cues.append(dict(theme))
    accepted = _current_requests(db, [c["id"] for c in cues], accepted_only=True)
    measured = 0
    for cue in cues:
        request = accepted.get(str(cue["id"]))
        asset_id = request["result_asset_id"] if request else None
        if asset_id is None:
            if cue["audio_asset_id"] is not None:
                db.execute(text("UPDATE sound_cues SET audio_asset_id = NULL, audio_duration = NULL WHERE id = :id"),
                           {"id": str(cue["id"])})
            continue
        if cue["audio_asset_id"] == asset_id and cue["audio_duration"] is not None:
            continue
        asset = get_asset(db, asset_id)
        if asset is None:
            continue
        db.execute(text("UPDATE sound_cues SET audio_asset_id = :a, audio_duration = :d, updated_at = now() WHERE id = :id"),
                   {"a": str(asset_id), "d": _measure(db, asset), "id": str(cue["id"])})
        measured += 1
    relayout(db, episode_id)
    return {"measured": measured}


def sync_request(db: Session, request_id: UUID) -> None:
    """Hook for the job runner: a generation request just finished, so refresh the episode its cue belongs to."""
    row = db.execute(
        text("""SELECT c.episode_id, c.series_id, c.role FROM generation_requests r JOIN sound_cues c ON c.id = r.target_id
                WHERE r.id = :r AND r.target_type = 'sound_cue'"""), {"r": str(request_id)}).mappings().first()
    if row is None:
        return
    if row["episode_id"]:
        sync_episode(db, row["episode_id"])
    else:  # the series theme: every episode of the series may use it
        for (episode_id,) in db.execute(text("SELECT id FROM episodes WHERE series_id = :s"), {"s": str(row["series_id"])}):
            sync_episode(db, episode_id)


def review_cue(db: Session, cue_id: UUID, decision: str, note: str | None = None) -> dict:
    """Approve or reject the finished audio of a cue. Rejecting queues a new attempt with the note added to the
    prompt. The caller commits."""
    cue = db.execute(text("SELECT * FROM sound_cues WHERE id = :id"), {"id": str(cue_id)}).mappings().first()
    if cue is None:
        raise LookupError("Cue was not found")
    current = _current_requests(db, [cue_id]).get(str(cue_id))
    if current is None or current["status"] != "succeeded":
        raise ValueError("This sound has not been generated yet")
    result = generation.review_request(db, current["id"], decision, note)
    if cue["episode_id"]:
        sync_episode(db, cue["episode_id"])
    return result


def approve_all(db: Session, episode_id: UUID) -> dict:
    """Approve every finished sound still waiting for a verdict. The caller commits."""
    cues = _cues(db, episode_id)
    current = _current_requests(db, [c["id"] for c in cues])
    count = 0
    for request in current.values():
        if request["status"] == "succeeded" and request["review_status"] == "pending":
            generation.review_request(db, request["id"], "approve", None)
            count += 1
    return {"approved": count}


# ----- the board ---------------------------------------------------------------------------------------------------

def _cue_view(cue: dict, request: dict | None, asset: dict | None) -> dict:
    status = "planned" if request is None else ("ready" if request["status"] == "succeeded" else request["status"])
    return {"id": str(cue["id"]), "cue_type": cue["cue_type"], "role": cue["role"], "position": cue["position"],
            "speaker": cue["speaker"], "character_id": str(cue["character_id"]) if cue["character_id"] else None,
            "text": cue["text"], "delivery": cue["delivery"], "shot_id": str(cue["shot_id"]) if cue["shot_id"] else None,
            "start_seconds": float(cue["start_seconds"]) if cue["start_seconds"] is not None else None,
            "duration_hint": float(cue["duration_hint"]) if cue["duration_hint"] is not None else None,
            "audio_duration": float(cue["audio_duration"]) if cue["audio_duration"] is not None else None,
            "status": status, "review_status": request["review_status"] if request else None,
            "review_note": request["review_note"] if request else None, "error": request["error_summary"] if request else None,
            "request_id": str(request["id"]) if request else None, "attempts": request["attempt_count"] if request else 0,
            "audio": asset_summary(asset)}


def episode_board(db: Session, episode_id: UUID) -> dict:
    """Everything the sound board shows. Reads finished audio first, so timings are current."""
    episode = _episode(db, episode_id)
    sync_episode(db, episode_id)
    db.commit()
    scenes = load_scenes(db, episode_id)
    cues = _cues(db, episode_id)
    theme = db.execute(text("SELECT * FROM sound_cues WHERE series_id = :s AND role = 'theme'"),
                       {"s": str(episode["series_id"])}).mappings().first()
    all_cues = cues + ([dict(theme)] if theme else [])
    current = _current_requests(db, [c["id"] for c in all_cues])
    asset_ids = [str(c["audio_asset_id"]) for c in all_cues if c["audio_asset_id"]]
    assets = {}
    if asset_ids:
        assets = {str(a["id"]): dict(a) for a in db.execute(
            text("SELECT * FROM assets WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": "{" + ",".join(asset_ids) + "}"}).mappings()}

    def view(cue: dict) -> dict:
        return _cue_view(cue, current.get(str(cue["id"])), assets.get(str(cue["audio_asset_id"])) if cue["audio_asset_id"] else None)

    fits = {str(r["shot_id"]): r for r in db.execute(
        text("SELECT * FROM sound_shot_fits WHERE episode_id = :e"), {"e": str(episode_id)}).mappings()}
    by_scene: dict[str, list[dict]] = {}
    for cue in cues:
        by_scene.setdefault(str(cue["scene_id"]), []).append(cue)
    out_scenes = []
    for scene in scenes:
        shots = []
        for shot in scene["shots"]:
            fit = fits.get(str(shot["id"]))
            shots.append({"id": str(shot["id"]), "shot_number": shot["shot_number"], "description": shot["description"],
                          "duration_seconds": shot["duration"],
                          "fit": None if fit is None else {
                              "status": fit["status"], "audio_seconds": float(fit["audio_seconds"]),
                              "suggested_seconds": float(fit["suggested_seconds"]) if fit["suggested_seconds"] is not None else None,
                              "measured": fit["measured"]}})
        order = {"narration": 0, "dialogue": 1, "sfx": 2, "ambience": 3, "music": 4}
        scene_cues = sorted(by_scene.get(str(scene["id"]), []), key=lambda c: (order[c["cue_type"]], c["position"]))
        out_scenes.append({"id": str(scene["id"]), "scene_number": scene["scene_number"], "title": scene["title"],
                           "shots": shots, "cues": [view(c) for c in scene_cues]})
    views = [view(c) for c in all_cues]
    counts: dict[str, int] = {}
    for v in views:
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    speakers = {c["character_id"] for c in cues if c["cue_type"] == "dialogue" and c["character_id"]}
    warnings = []
    for character_id in speakers:
        cast = voice_cast_service.get_cast(db, episode["series_id"], character_id)
        name = db.execute(text("SELECT name FROM characters WHERE id = :c"), {"c": str(character_id)}).scalar()
        if cast is None:
            warnings.append(f"{name} has no cast voice; lines use the look-sheet suggestion or the provider default.")
        elif not cast["consent_given"]:
            warnings.append(f"No voice consent is recorded for {name}.")
    if any(c["cue_type"] == "narration" for c in cues) and voice_cast_service.get_cast(db, episode["series_id"], None) is None:
        warnings.append("The narrator has no cast voice.")
    if any(c["cue_type"] == "dialogue" and not c["character_id"] for c in cues):
        warnings.append("Some dialogue speakers do not match a character; they use the default voice.")
    job = db.execute(
        text("""SELECT status, error_summary FROM generation_jobs WHERE job_type = 'sound_generation'
                AND request_metadata ->> 'sound_episode_id' = :e ORDER BY created_at DESC LIMIT 1"""),
        {"e": str(episode_id)}).mappings().first()
    subtitles = subtitle_files(db, episode_id)
    return {"episode": {"id": str(episode["id"]), "episode_number": episode["episode_number"], "title": episode["title"]},
            "job": dict(job) if job else None, "theme": view(dict(theme)) if theme else None, "scenes": out_scenes,
            "counts": counts, "overflow_shots": sum(1 for f in fits.values() if f["status"] == "overflow"),
            "warnings": warnings, "subtitles": subtitles}


# ----- the audio plan for the video step ---------------------------------------------------------------------------

def _plan_dir(episode_id: UUID) -> Path:
    folder = storage_root() / "sound_plan" / str(episode_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _slice(source: Path, start: float, length: float, folder: Path) -> Path:
    """A piece of a long audio file (ambience, music) for one shot, so each shot's mix starts at 0 and the whole
    scene still plays through. A file shorter than the span loops."""
    length_of_source = 0.0
    try:
        length_of_source = probe(source).duration
    except Exception:  # noqa: BLE001
        pass
    if length_of_source > 0:
        start = start % length_of_source
    out = folder / f"{source.stem}_{int(round(start * 1000))}_{int(round(length * 1000))}.wav"
    if not out.exists():
        run_ffmpeg(["-stream_loop", "-1", "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{length:.3f}",
                    "-ac", "2", "-ar", "48000", str(out)])
    return out


def build_audio_plan(db: Session, episode_id: UUID) -> dict[str, dict]:
    """`{shot_id: {"audio_tracks": [...], "subtitles": [...]}}`, the shape `app.media.assemble_episode` takes per shot.

    audio_tracks: {path, start_seconds, gain, role: dialogue|music|sfx, cue_id, cue_type}; start_seconds is relative to
    the shot. Ambience and music are cut into per-shot pieces so they run through a whole scene without restarting.
    subtitles: {start, end, text} in seconds relative to the shot, for dialogue and narration. Only audio the user has
    not rejected is included; subtitles are always included (with estimated timings until the audio is measured).
    """
    episode = _episode(db, episode_id)
    sync_episode(db, episode_id)
    db.commit()
    scenes = load_scenes(db, episode_id)
    cues = _cues(db, episode_id)
    theme = db.execute(text("SELECT * FROM sound_cues WHERE series_id = :s AND role = 'theme'"),
                       {"s": str(episode["series_id"])}).mappings().first()
    shots = [(scene, shot) for scene in scenes for shot in scene["shots"]]
    plan: dict[str, dict] = {str(shot["id"]): {"audio_tracks": [], "subtitles": []} for _, shot in shots}
    index_of = {str(shot["id"]): i for i, (_, shot) in enumerate(shots)}
    folder = _plan_dir(episode_id)
    storage = get_storage()

    def audio_path(cue: dict) -> Path | None:
        if not cue["audio_asset_id"]:
            return None
        asset = get_asset(db, cue["audio_asset_id"])
        return storage.local_path(asset["storage_key"]) if asset else None

    def track(shot_id: str, path: Path, start: float, cue: dict, role: str):
        plan[shot_id]["audio_tracks"].append({"path": str(path), "start_seconds": round(start, 2),
                                              "gain": GAINS[cue["cue_type"]], "role": role, "cue_id": str(cue["id"]),
                                              "cue_type": cue["cue_type"]})

    def spread(cue: dict, path: Path, first_index: int, seconds: float):
        """Lay a long file over consecutive shots from `first_index`, one piece per shot."""
        offset, i = 0.0, first_index
        while offset < seconds - 0.05 and i < len(shots):
            shot = shots[i][1]
            length = min(shot["duration"], seconds - offset)
            track(str(shot["id"]), _slice(path, offset, length, folder), 0.0, cue, "music" if cue["cue_type"] == "music" else "sfx")
            offset += shot["duration"]
            i += 1

    for cue in cues:
        if not cue["shot_id"] or str(cue["shot_id"]) not in plan:
            continue
        shot_id, path = str(cue["shot_id"]), audio_path(cue)
        shot = shots[index_of[shot_id]][1]
        start = float(cue["start_seconds"] or 0.0)
        if cue["cue_type"] in SPEECH:
            end = min(start + _speech_seconds(cue), shot["duration"])
            if end > start:
                plan[shot_id]["subtitles"].append({"start": round(start, 2), "end": round(end, 2), "text": cue["text"]})
            if path:
                track(shot_id, path, start, cue, "dialogue")
        elif path and cue["cue_type"] == "sfx":
            track(shot_id, path, start, cue, "sfx")
        elif path and cue["cue_type"] == "ambience":
            scene_start = next(i for i, (sc, _) in enumerate(shots) if sc["id"] == shots[index_of[shot_id]][0]["id"])
            spread_seconds = _scene_seconds(shots[index_of[shot_id]][0])
            offset, i = 0.0, scene_start
            while i < len(shots) and shots[i][0]["id"] == shots[scene_start][0]["id"] and offset < spread_seconds:
                piece = shots[i][1]
                track(str(piece["id"]), _slice(path, offset, piece["duration"], folder), 0.0, cue, "sfx")
                offset += piece["duration"]
                i += 1
        elif path and cue["cue_type"] == "music":
            spread(cue, path, index_of[shot_id], float(cue["duration_hint"] or shot["duration"]))
    if theme and audio_path(dict(theme)) and shots:
        first_scene = scenes[0]
        if not any(c["cue_type"] == "music" and c["scene_id"] == first_scene["id"] for c in cues):
            seconds = float(theme["audio_duration"] or theme["duration_hint"] or THEME_SECONDS)
            spread(dict(theme), audio_path(dict(theme)), 0, min(seconds, _scene_seconds(first_scene)))
    for item in plan.values():
        item["subtitles"].sort(key=lambda s: s["start"])
    return plan


# ----- subtitles ---------------------------------------------------------------------------------------------------

SRT_MIME = "application/x-subrip"


def subtitle_files(db: Session, episode_id: UUID) -> dict:
    """The subtitle assets built for the episode: one for the episode, the rest per scene and shot."""
    rows = db.execute(
        text("""SELECT * FROM assets WHERE kind = 'subtitle' AND metadata ->> 'episode_id' = :e ORDER BY created_at DESC"""),
        {"e": str(episode_id)}).mappings().all()
    episode = next((r for r in rows if r["metadata"].get("scope") == "episode"), None)
    return {"episode": asset_summary(dict(episode)) if episode else None,
            "scenes": sum(1 for r in rows if r["metadata"].get("scope") == "scene"),
            "shots": sum(1 for r in rows if r["metadata"].get("scope") == "shot")}


def build_subtitles(db: Session, episode_id: UUID) -> dict:
    """Write SRT files per shot, scene and episode from the audio plan and store them as assets, replacing the
    previous set. The caller commits."""
    episode = _episode(db, episode_id)
    plan = build_audio_plan(db, episode_id)
    scenes = load_scenes(db, episode_id)
    for row in db.execute(text("SELECT id FROM assets WHERE kind = 'subtitle' AND metadata ->> 'episode_id' = :e"),
                          {"e": str(episode_id)}).mappings().all():
        delete_asset(db, row["id"])

    def store(segments: list[dict], scope: str, **meta):
        return save_asset(db, to_srt(segments).encode("utf-8"), SRT_MIME, series_id=episode["series_id"], provider="sound",
                          filename=f"{scope}.srt", metadata={"scope": scope, "episode_id": str(episode_id), **meta})

    episode_segments, shot_files, scene_files = [], 0, 0
    clock = 0.0
    for scene in scenes:
        scene_segments, scene_clock = [], 0.0
        for shot in scene["shots"]:
            segments = plan[str(shot["id"])]["subtitles"]
            if segments:
                store(segments, "shot", shot_id=str(shot["id"]), scene_id=str(scene["id"]))
                shot_files += 1
            for seg in segments:
                scene_segments.append({**seg, "start": seg["start"] + scene_clock, "end": seg["end"] + scene_clock})
                episode_segments.append({**seg, "start": seg["start"] + clock, "end": seg["end"] + clock})
            scene_clock += shot["duration"]
            clock += shot["duration"]
        if scene_segments:
            store(scene_segments, "scene", scene_id=str(scene["id"]))
            scene_files += 1
    asset = store(episode_segments, "episode")
    return {"episode": asset_summary(asset), "scenes": scene_files, "shots": shot_files, "segments": len(episode_segments)}


def episode_srt_text(db: Session, episode_id: UUID) -> str | None:
    """The episode SRT as text, for the subtitle preview."""
    row = db.execute(
        text("""SELECT storage_key FROM assets WHERE kind = 'subtitle' AND metadata ->> 'episode_id' = :e
                AND metadata ->> 'scope' = 'episode' ORDER BY created_at DESC LIMIT 1"""), {"e": str(episode_id)}).mappings().first()
    if row is None:
        return None
    return get_storage().read(row["storage_key"]).decode("utf-8", errors="replace")
