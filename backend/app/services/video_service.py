"""Video clips per shot: planning, the clip board for an episode, review, and the episode budget with its pause switch.

A clip is an ordinary generation request (kind `video_clip`, target a shot) made image-to-video from the shot's
approved keyframe. The provider may return a clip longer or shorter than the shot needs, so the real length is
probed after saving; the render step trims a long clip, and a short one is flagged (never silently padded) unless the
user chose to hold its last frame.

The budget is per episode: a retry limit per shot, an optional cost cap, and a pause switch. `hold_reason` is called by
`generation_service.run_request`; a held request goes back to `blocked` and is released when the episode resumes.
"""
import json
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.media import ops
from app.media.errors import MediaError
from app.services import generation_service as generation
from app.services import style_bible_service
from app.services.asset_store import asset_summary, get_asset, get_storage, storage_root

log = logging.getLogger("video")

DEFAULT_SHOT_SECONDS = 5.0
DEFAULT_MAX_RETRIES = 3
LIVE_STATUSES = ("queued", "blocked", "running", "awaiting_input")


def _ids(values) -> str:
    return "{" + ",".join(str(v) for v in values) + "}"


def work_root() -> Path:
    """Scratch space for renders, next to the asset files."""
    return storage_root() / "_work"


def local_file(asset: dict) -> Path:
    """A path ffmpeg can read for the asset, copying out of storage when the backend has no local file."""
    storage = get_storage()
    path = storage.local_path(asset["storage_key"])
    if path is not None:
        return Path(path)
    cached = work_root() / "_inputs" / f"{asset['id']}{Path(asset['storage_key']).suffix}"
    if not cached.exists():
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(storage.read(asset["storage_key"]))
    return cached


def get_episode(db: Session, episode_id: UUID) -> dict:
    row = db.execute(
        text("""SELECT id, series_id, episode_number, title, target_duration_seconds FROM episodes WHERE id = :e"""),
        {"e": str(episode_id)}).mappings().first()
    if row is None:
        raise LookupError("Episode was not found")
    return dict(row)


def shot_rows(db: Session, episode_id: UUID) -> list[dict]:
    rows = db.execute(
        text("""SELECT sh.id AS shot_id, sh.scene_id, sc.scene_number, sc.title AS scene_title, sh.shot_number,
                       sh.description, sh.camera, sh.duration_seconds, sh.character_ids
                FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id
                WHERE sc.episode_id = :e ORDER BY sc.scene_number, sh.shot_number"""), {"e": str(episode_id)}).mappings().all()
    return [dict(r) for r in rows]


def shot_seconds(shot: dict) -> float:
    return float(shot["duration_seconds"] or DEFAULT_SHOT_SECONDS)


def requests_by_shot(db: Session, series_id: UUID, kind: str, shot_ids: list) -> dict[str, list[dict]]:
    """Requests of one kind for the given shots, oldest first, grouped by shot id."""
    if not shot_ids:
        return {}
    rows = db.execute(
        text("""SELECT * FROM generation_requests WHERE series_id = :s AND kind = :k AND target_type = 'shot'
                AND target_id = ANY(CAST(:ids AS uuid[])) ORDER BY created_at, id"""),
        {"s": str(series_id), "k": kind, "ids": _ids(shot_ids)}).mappings().all()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["target_id"]), []).append(dict(row))
    return grouped


def assets_by_id(db: Session, ids) -> dict[str, dict]:
    ids = [str(i) for i in ids if i]
    if not ids:
        return {}
    rows = db.execute(text("SELECT * FROM assets WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": _ids(ids)}).mappings().all()
    return {str(r["id"]): dict(r) for r in rows}


def pick_keyframe(rows: list[dict], *, allow_unapproved: bool = False) -> dict | None:
    """The newest approved keyframe request of a shot (or, when allowed, the newest finished one)."""
    finished = [r for r in reversed(rows) if r["status"] == "succeeded" and r["result_asset_id"]]
    for row in finished:
        if row["review_status"] == "approved":
            return row
    return finished[0] if (allow_unapproved and finished) else None


def current_clip(rows: list[dict]) -> dict | None:
    return rows[-1] if rows else None


# --- measuring clips -----------------------------------------------------------------------------------------------

def probe_asset(db: Session, asset: dict) -> dict | None:
    """The real length and size of a stored clip, remembered on the asset. None for a file that is not a video."""
    meta = asset.get("metadata") or {}
    if "probe" in meta:
        return meta["probe"]
    if asset["kind"] != "video" or asset["mime_type"] == "application/x-movai-placeholder":
        return None
    try:
        info = ops.probe(local_file(asset))
        result = {"duration": round(info.duration, 3), "width": info.width, "height": info.height, "fps": info.fps,
                  "has_audio": info.has_audio, "video_codec": info.video_codec}
    except (MediaError, OSError) as error:
        result = {"error": str(error)[:300]}
    db.execute(
        text("""UPDATE assets SET metadata = COALESCE(metadata, '{}'::jsonb) || CAST(:m AS jsonb),
                       duration_seconds = COALESCE(:d, duration_seconds), width = COALESCE(:w, width),
                       height = COALESCE(:h, height) WHERE id = :a"""),
        {"m": json.dumps({"probe": result}), "d": result.get("duration"), "w": result.get("width"),
         "h": result.get("height"), "a": str(asset["id"])})
    asset["metadata"] = {**meta, "probe": result}
    return result


def clip_state(needed: float, probe: dict | None, hold_last_frame: bool) -> dict:
    """How the clip compares with the shot: exact, trim (too long), short (flagged) or hold (short, last frame held)."""
    state = {"needed_seconds": round(needed, 2), "actual_seconds": None, "trim": "unknown"}
    if not probe or "duration" not in probe:
        state["trim"] = "unplayable" if probe else "unknown"
        return state
    actual = float(probe["duration"])
    state["actual_seconds"] = round(actual, 2)
    tolerance = settings.clip_duration_tolerance
    if actual < needed - tolerance:
        state["trim"] = "hold" if hold_last_frame else "short"
    elif actual > needed + tolerance:
        state["trim"] = "trim"
    else:
        state["trim"] = "exact"
    return state


def on_request_finished(db: Session, request_id) -> None:
    """Called by the job runner after a request finished: measure a new clip so the board and render know its length."""
    row = db.execute(text("SELECT kind, result_asset_id FROM generation_requests WHERE id = :r"),
                     {"r": str(request_id)}).mappings().first()
    if row and row["kind"] == "video_clip" and row["result_asset_id"]:
        asset = get_asset(db, row["result_asset_id"])
        if asset:
            probe_asset(db, asset)
            db.commit()


# --- budget, pause ------------------------------------------------------------------------------------------------

def cost_total(db: Session, episode_id: UUID) -> float:
    return float(db.execute(
        text("""SELECT COALESCE(SUM(r.cost), 0) FROM generation_requests r
                JOIN shots sh ON sh.id = r.target_id JOIN scenes sc ON sc.id = sh.scene_id
                WHERE r.kind = 'video_clip' AND sc.episode_id = :e"""), {"e": str(episode_id)}).scalar() or 0)


def get_budget(db: Session, episode_id: UUID) -> dict:
    row = db.execute(text("SELECT max_retries_per_shot, max_cost, paused FROM generation_budgets WHERE episode_id = :e"),
                     {"e": str(episode_id)}).mappings().first()
    budget = {"max_retries_per_shot": DEFAULT_MAX_RETRIES, "max_cost": None, "paused": False}
    if row:
        budget.update({"max_retries_per_shot": row["max_retries_per_shot"],
                       "max_cost": float(row["max_cost"]) if row["max_cost"] is not None else None,
                       "paused": row["paused"]})
    budget["cost_total"] = round(cost_total(db, episode_id), 4)
    budget["over_cost"] = budget["max_cost"] is not None and budget["cost_total"] >= budget["max_cost"]
    return budget


def set_budget(db: Session, episode_id: UUID, changes: dict) -> dict:
    """Change the retry limit, cost cap (None removes it) or pause switch. Un-pausing or raising the cap releases held
    requests. The caller commits."""
    episode = get_episode(db, episode_id)
    allowed = {"max_retries_per_shot", "max_cost", "paused"}
    changes = {k: v for k, v in changes.items() if k in allowed}
    db.execute(text("""INSERT INTO generation_budgets (episode_id, series_id) VALUES (:e, :s)
                       ON CONFLICT (episode_id) DO NOTHING"""), {"e": str(episode_id), "s": str(episode["series_id"])})
    if changes:
        assignments = ", ".join(f"{column} = :{column}" for column in changes)
        db.execute(text(f"UPDATE generation_budgets SET {assignments}, updated_at = now() WHERE episode_id = :e"),
                   {**changes, "e": str(episode_id)})
    released = release_held(db, episode_id)
    return {**get_budget(db, episode_id), "released": released}


def _episode_of_shot(db: Session, shot_id) -> str | None:
    value = db.execute(text("SELECT sc.episode_id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sh.id = :s"),
                       {"s": str(shot_id)}).scalar()
    return str(value) if value else None


def hold_reason(db: Session, row) -> str | None:
    """Why a queued request must not run now: 'series_paused' (any kind), or for a clip 'paused' / 'budget'; else None."""
    if db.execute(text("SELECT paused FROM generation_controls WHERE series_id = :s"), {"s": str(row["series_id"])}).scalar():
        return "series_paused"
    if row["kind"] != "video_clip":
        return None
    episode_id = (row["params"] or {}).get("episode_id") or (_episode_of_shot(db, row["target_id"]) if row["target_id"] else None)
    if not episode_id:
        return None
    budget = get_budget(db, UUID(str(episode_id)))
    if budget["paused"]:
        return "paused"
    if budget["over_cost"]:
        return "budget"
    return None


def release_held(db: Session, episode_id: UUID) -> list[str]:
    """Queue the clip requests that were held by the pause switch or the cost cap and may run now."""
    rows = db.execute(
        text("""SELECT r.* FROM generation_requests r
                JOIN shots sh ON sh.id = r.target_id JOIN scenes sc ON sc.id = sh.scene_id
                WHERE r.kind = 'video_clip' AND r.status = 'blocked' AND r.params ->> 'held_reason' IS NOT NULL
                  AND sc.episode_id = :e ORDER BY r.created_at"""), {"e": str(episode_id)}).mappings().all()
    released = []
    for row in rows:
        if hold_reason(db, row) is not None or not generation._deps_ready(db, row):  # noqa: SLF001 - same package
            continue
        db.execute(text("UPDATE generation_requests SET status = 'queued', params = params - 'held_reason' WHERE id = :r"),
                   {"r": str(row["id"])})
        generation._queue_job(db, row["id"], row["series_id"])  # noqa: SLF001
        released.append(str(row["id"]))
    return released


# --- prompts and planning -----------------------------------------------------------------------------------------

def build_prompts(db: Session, shot: dict, bible: dict | None) -> dict:
    """The motion prompt for a shot: prompt_builder's `build_video_prompt` on the shot's full context. Returns its dict
    ({"prompt", "negative_prompt", "sound_prompt", "duration_seconds", "aspect_ratio"})."""
    from app.services.prompt_builder import build_video_prompt, load_shot_context  # imported here: builder imports services
    context = load_shot_context(db, UUID(str(shot["shot_id"])))
    context["duration_seconds"] = shot_seconds(shot)
    return build_video_prompt(context, bible or {})


def working_size() -> tuple[int, int]:
    return settings.render_working_width, settings.render_working_height


def plan_clips(db: Session, episode_id: UUID, *, limit: int | None = None, scene_id: UUID | None = None,
               allow_text_to_video: bool = False, allow_unapproved_keyframes: bool = False,
               hold_last_frame: bool = False) -> dict:
    """One video request per shot that has no clip request yet, at the low-res working size. The caller commits."""
    episode = get_episode(db, episode_id)
    series_id = episode["series_id"]
    shots = [s for s in shot_rows(db, episode_id) if not scene_id or str(s["scene_id"]) == str(scene_id)]
    shot_ids = [s["shot_id"] for s in shots]
    keyframes = requests_by_shot(db, series_id, "keyframe", shot_ids)
    clips = requests_by_shot(db, series_id, "video_clip", shot_ids)
    bible = style_bible_service.get_approved(db, series_id)
    width, height = working_size()
    created, existing, failed, no_keyframe = [], [], [], []
    for shot in shots:
        key = str(shot["shot_id"])
        latest = current_clip(clips.get(key, []))
        if latest and latest["status"] in LIVE_STATUSES + ("succeeded",):
            existing.append(key)
            continue
        if latest and latest["status"] == "failed":
            failed.append(key)
            continue
        if limit is not None and len(created) >= limit:
            continue
        keyframe = pick_keyframe(keyframes.get(key, []), allow_unapproved=allow_unapproved_keyframes)
        if keyframe is None and not allow_text_to_video:
            no_keyframe.append(key)
            continue
        built = build_prompts(db, shot, bible)
        prompt, negative = built["prompt"], built["negative_prompt"]
        params = {"duration_seconds": shot_seconds(shot), "width": width, "height": height,
                  "aspect_ratio": built["aspect_ratio"], "sound_prompt": built["sound_prompt"] or None,
                  "fps": settings.render_working_fps, "episode_id": str(episode_id), "working_size": True,
                  "hold_last_frame": hold_last_frame}
        refs = []
        if keyframe is not None:
            params["first_frame_asset_id"] = str(keyframe["result_asset_id"])
            params["keyframe_request_id"] = str(keyframe["id"])
            refs = [keyframe["result_asset_id"]]
        request = generation.create_request(db, series_id, "video_clip", prompt, target_type="shot",
                                            target_id=shot["shot_id"], negative_prompt=negative, params=params,
                                            reference_asset_ids=refs)
        created.append(str(request["id"]))
    return {"created": len(created), "request_ids": created, "already_planned": len(existing),
            "failed": len(failed), "skipped_no_keyframe": len(no_keyframe), "no_keyframe_shot_ids": no_keyframe}


# --- review -------------------------------------------------------------------------------------------------------

def _clip_row(db: Session, request_id: UUID) -> dict:
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise LookupError("Request was not found")
    if row["kind"] != "video_clip":
        raise ValueError("This is not a video clip request")
    return dict(row)


def attempts_for_shot(db: Session, shot_id) -> int:
    return int(db.execute(text("SELECT count(*) FROM generation_requests WHERE kind = 'video_clip' AND target_id = :s"),
                          {"s": str(shot_id)}).scalar() or 0)


def review_clip(db: Session, request_id: UUID, decision: str, note: str | None = None) -> dict:
    """Approve a clip, or reject it with a note to regenerate it. Rejection stops at the episode's retry limit; approval
    is refused for a clip that is too short (unless its last frame is to be held) or is not a playable video."""
    row = _clip_row(db, request_id)
    episode_id = (row["params"] or {}).get("episode_id") or _episode_of_shot(db, row["target_id"])
    budget = get_budget(db, UUID(str(episode_id))) if episode_id else {"max_retries_per_shot": DEFAULT_MAX_RETRIES}
    if decision == "approve":
        if row["status"] != "succeeded" or not row["result_asset_id"]:
            raise ValueError("Only a finished clip can be approved")
        asset = get_asset(db, row["result_asset_id"])
        probe = probe_asset(db, asset) if asset else None
        shot = db.execute(text("SELECT duration_seconds FROM shots WHERE id = :s"), {"s": str(row["target_id"])}).mappings().first()
        needed = shot_seconds(shot) if shot else float((row["params"] or {}).get("duration_seconds") or DEFAULT_SHOT_SECONDS)
        state = clip_state(needed, probe, bool((row["params"] or {}).get("hold_last_frame")))
        if state["trim"] == "unplayable":
            raise ValueError("The clip is not a playable video file; regenerate it or upload a replacement")
        if state["trim"] == "short":
            raise ValueError(f"The clip is {state['actual_seconds']}s but the shot needs {state['needed_seconds']}s. "
                             "Regenerate it, or choose to hold its last frame.")
    elif decision == "reject":
        attempts = attempts_for_shot(db, row["target_id"])
        limit = budget["max_retries_per_shot"] + 1
        if attempts >= limit:
            raise ValueError(f"Retry budget used up: {attempts} attempts made for this shot (limit {limit}). "
                             "Raise the limit in the episode budget to try again.")
    result = generation.review_request(db, request_id, decision, note)
    if decision == "reject" and result.get("new_request"):
        _carry_options(db, row, result["new_request"]["id"])
    return result


def _carry_options(db: Session, old: dict, new_id) -> None:
    """A regenerated clip keeps the episode link and the hold-last-frame choice."""
    keep = {k: v for k, v in (old["params"] or {}).items() if k in ("episode_id", "hold_last_frame", "working_size")}
    if keep:
        db.execute(text("UPDATE generation_requests SET params = params || CAST(:p AS jsonb) WHERE id = :r"),
                   {"p": json.dumps(keep), "r": str(new_id)})


def set_clip_options(db: Session, request_id: UUID, hold_last_frame: bool) -> dict:
    row = _clip_row(db, request_id)
    db.execute(text("UPDATE generation_requests SET params = params || CAST(:p AS jsonb) WHERE id = :r"),
               {"p": json.dumps({"hold_last_frame": hold_last_frame}), "r": str(request_id)})
    return {"request_id": str(request_id), "hold_last_frame": hold_last_frame, "status": row["status"]}


# --- the clip board -----------------------------------------------------------------------------------------------

def _request_view(row: dict, asset: dict | None) -> dict:
    return {"request_id": str(row["id"]), "status": row["status"], "review_status": row["review_status"],
            "review_note": row["review_note"], "error_summary": row["error_summary"], "cost": float(row["cost"] or 0),
            "provider": row["provider"], "asset": asset_summary(asset)}


def board(db: Session, episode_id: UUID) -> dict:
    """Everything the clip board shows for an episode: per shot the keyframe and clip, the budget and the renders."""
    from app.services import render_service  # imported here: render_service imports this module

    episode = get_episode(db, episode_id)
    series_id = episode["series_id"]
    shots = shot_rows(db, episode_id)
    shot_ids = [s["shot_id"] for s in shots]
    keyframes = requests_by_shot(db, series_id, "keyframe", shot_ids)
    clips = requests_by_shot(db, series_id, "video_clip", shot_ids)
    wanted = []
    for key in clips:
        clip = current_clip(clips[key])
        wanted.append(clip["result_asset_id"] if clip else None)
    for key, rows in keyframes.items():
        picked = pick_keyframe(rows, allow_unapproved=True)
        wanted.append(picked["result_asset_id"] if picked else None)
    assets = assets_by_id(db, wanted)
    items, counts = [], {"approved": 0, "pending_review": 0, "failed": 0, "in_progress": 0, "no_clip": 0, "attention": 0}
    for shot in shots:
        key = str(shot["shot_id"])
        keyframe = pick_keyframe(keyframes.get(key, []), allow_unapproved=True)
        clip = current_clip(clips.get(key, []))
        item = {k: (str(v) if k.endswith("_id") and v is not None else v) for k, v in shot.items() if k != "character_ids"}
        item["duration_seconds"] = shot_seconds(shot)
        item["keyframe"] = ({"request_id": str(keyframe["id"]), "review_status": keyframe["review_status"],
                             "asset": asset_summary(assets.get(str(keyframe["result_asset_id"])))} if keyframe else None)
        if clip is None:
            item["clip"] = None
            counts["no_clip"] += 1
        else:
            asset = assets.get(str(clip["result_asset_id"])) if clip["result_asset_id"] else None
            probe = probe_asset(db, asset) if asset else None
            hold = bool((clip["params"] or {}).get("hold_last_frame"))
            view = _request_view(clip, asset)
            view.update(clip_state(shot_seconds(shot), probe, hold))
            view.update({"hold_last_frame": hold, "attempt": len(clips[key]), "attempts": len(clips[key]),
                         "held_reason": (clip["params"] or {}).get("held_reason"), "prompt": clip["prompt"]})
            item["clip"] = view
            if clip["status"] == "failed":
                counts["failed"] += 1
            elif clip["status"] != "succeeded":
                counts["in_progress"] += 1
            elif clip["review_status"] == "approved":
                counts["approved"] += 1
            else:
                counts["pending_review"] += 1
            if view["trim"] in ("short", "unplayable") or clip["status"] == "failed":
                counts["attention"] += 1
        items.append(item)
    db.commit()  # probing remembers each clip's real length
    return {"episode": {"id": str(episode["id"]), "series_id": str(series_id), "episode_number": episode["episode_number"],
                        "title": episode["title"]},
            "budget": get_budget(db, episode_id), "shots": items,
            "summary": {"shots": len(items), "with_keyframe": sum(1 for i in items if i["keyframe"]), **counts},
            "renders": render_service.latest_renders(db, episode_id)}
