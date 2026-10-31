"""Keyframes: one still image per shot, the first frame its video clip is animated from.

A keyframe is a `generation_requests` row with kind 'keyframe', target_type 'shot' and target_id = the shot. The
newest request for a shot is its current keyframe; older ones are history (rejected, regenerated, failed).

Requests are created shot by shot in scene order, each committed on its own, so the job runner (which takes the
oldest queued job first) makes them in story order and a shot can use the finished keyframe of the shot before it.
References are approved images made by the reference stage. A keyframe whose character or place reference is still
waiting for approval is blocked on it (it needs the approval, not just the image); references are re-collected just
before it runs, so it always carries the approved ones.
"""
import json
import tempfile
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import consistency_check, generation_service, reference_adapter
from app.services.asset_store import asset_summary, get_asset, get_storage, save_asset
from app.services.prompt_builder import build_keyframe_prompt, load_shot_context
from app.services.style_bible_service import get_approved

MAX_REFERENCES = 8
OPEN = ("queued", "blocked", "running", "awaiting_input")


# ---------------------------------------------------------------- continuity

def _last_frame_asset(db: Session, series_id: UUID, clip_request) -> UUID | None:
    existing = db.execute(
        text("""SELECT id FROM assets WHERE source_request_id = :r AND provider = 'derived' AND kind = 'image'
                ORDER BY created_at DESC LIMIT 1"""), {"r": str(clip_request["id"])}).scalar()
    if existing:
        return existing
    asset = get_asset(db, clip_request["result_asset_id"])
    path = get_storage().local_path(asset["storage_key"]) if asset else None
    if path is None:
        return None
    try:
        from app.media import extract_last_frame
        with tempfile.TemporaryDirectory() as folder:
            png = extract_last_frame(path, Path(folder) / "last.png")
            saved = save_asset(db, png.read_bytes(), "image/png", series_id=series_id, provider="derived",
                               model="last_frame", source_request_id=clip_request["id"],
                               metadata={"derived": "last_frame"})
        return saved["id"]
    except Exception:  # noqa: BLE001 - continuity is a bonus; a missing ffmpeg or a bad clip must not stop the keyframe
        return None


def continuity_reference(db: Session, series_id: UUID, previous_shot_id: str | None) -> tuple[UUID, str] | None:
    """The picture that shows how the previous shot of the scene ended: the last frame of its video clip when one
    exists, otherwise its keyframe. None when neither has been made yet."""
    if not previous_shot_id:
        return None
    clip = db.execute(
        text("""SELECT id, result_asset_id FROM generation_requests
                WHERE kind = 'video_clip' AND target_id = :s AND status = 'succeeded' AND review_status <> 'rejected'
                  AND result_asset_id IS NOT NULL ORDER BY created_at DESC LIMIT 1"""), {"s": previous_shot_id}).mappings().first()
    if clip:
        frame = _last_frame_asset(db, series_id, clip)
        if frame:
            return frame, "Previous shot (last frame)"
    keyframe = db.execute(
        text("""SELECT result_asset_id FROM generation_requests
                WHERE kind = 'keyframe' AND target_id = :s AND status = 'succeeded' AND review_status <> 'rejected'
                  AND result_asset_id IS NOT NULL ORDER BY (review_status = 'approved') DESC, created_at DESC LIMIT 1"""),
        {"s": previous_shot_id}).scalar()
    return (keyframe, "Previous shot (keyframe)") if keyframe else None


def _references(db: Session, series_id: UUID, slots: list[dict], previous_shot_id: str | None) -> dict:
    # One slot is kept for the previous shot, so continuity is never the image that gets cut.
    found = reference_adapter.collect(db, series_id, slots, max_total=MAX_REFERENCES - 1)
    asset_ids, labels = list(found["asset_ids"]), dict(found["labels"])
    previous = continuity_reference(db, series_id, previous_shot_id)
    if previous and previous[0] not in asset_ids:
        asset_ids.append(previous[0])
        labels[str(previous[0])] = previous[1]
    found["asset_ids"], found["labels"] = asset_ids, {str(a): labels[str(a)] for a in asset_ids}
    return found


def before_run(db: Session, row) -> dict:
    """Called by the job runner just before a keyframe is made: re-collect the references so approvals and shots
    finished since the request was created are picked up. Returns the refreshed request row."""
    params = dict(row["params"] or {})
    slots = params.get("reference_slots")
    if not slots:
        return row
    found = _references(db, row["series_id"], slots, params.get("continuity_shot_id"))
    params["reference_labels"], params["warnings"] = found["labels"], found["warnings"]
    db.execute(
        text("""UPDATE generation_requests SET reference_asset_ids = CAST(:refs AS uuid[]), params = CAST(:params AS jsonb)
                WHERE id = :r"""),
        {"refs": "{" + ",".join(str(a) for a in found["asset_ids"]) + "}", "params": json.dumps(params),
         "r": str(row["id"])})
    db.commit()
    return db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(row["id"])}).mappings().one()


def after_generated(db: Session, request_id: UUID) -> None:
    """Called after a keyframe is made: run the consistency check against its references."""
    consistency_check.run_check(db, request_id)


# ---------------------------------------------------------------- creating requests

def _current(db: Session, shot_ids: list[str]) -> dict[str, dict]:
    if not shot_ids:
        return {}
    rows = db.execute(
        text("""SELECT DISTINCT ON (target_id) * FROM generation_requests
                WHERE kind = 'keyframe' AND target_id = ANY(CAST(:ids AS uuid[]))
                ORDER BY target_id, created_at DESC"""), {"ids": "{" + ",".join(shot_ids) + "}"}).mappings().all()
    return {str(r["target_id"]): dict(r) for r in rows}


def create_keyframe(db: Session, shot_id: UUID | str, bible: dict, *, previous_request_id=None) -> dict:
    """Build the prompt and references for one shot and queue (or block) its keyframe request. Caller commits."""
    ctx = load_shot_context(db, UUID(str(shot_id)))
    series_id = ctx["series_id"]
    built = build_keyframe_prompt(ctx, bible)  # first pass only to learn which references the shot calls for
    found = _references(db, series_id, built.reference_slots, ctx["previous_shot_id"])
    built = build_keyframe_prompt(ctx, bible, references_expected=bool(found["asset_ids"] or found["wait_for"]))
    params = {"aspect_ratio": "16:9", "reference_slots": built.reference_slots, "reference_labels": found["labels"],
              "warnings": found["warnings"], "continuity_shot_id": ctx["previous_shot_id"],
              "shot": {"scene_id": str(ctx["scene_id"]), "episode_id": str(ctx["episode_id"]),
                       "shot_number": ctx["shot_number"], "scene_number": ctx["scene_number"]}}
    if found["wait_for"]:
        params["deps_need_approval"] = True
    return generation_service.create_request(
        db, series_id, "keyframe", built.prompt, target_type="shot", target_id=UUID(ctx["id"]),
        negative_prompt=built.negative_prompt or None, params=params, reference_asset_ids=found["asset_ids"],
        depends_on=found["wait_for"], previous_request_id=previous_request_id)


def _retire(db: Session, old: dict, new_id, note: str) -> None:
    """Take an older request out of play when a fresh one replaces it, and point whatever waited on it at the new one."""
    db.execute(text("""UPDATE generation_requests SET status = 'rejected', review_status = 'rejected', review_note = :n,
                              reviewed_at = now() WHERE id = :r AND status <> 'failed'"""), {"r": str(old["id"]), "n": note})
    db.execute(text("""UPDATE generation_requests SET depends_on = array_replace(depends_on, CAST(:old AS uuid), CAST(:new AS uuid))
                       WHERE CAST(:old AS uuid) = ANY(depends_on)"""), {"old": str(old["id"]), "new": str(new_id)})


def _shots_of_episode(db: Session, episode_id: UUID) -> list[dict]:
    return [dict(r) for r in db.execute(
        text("""SELECT sh.id, sh.shot_number, sc.scene_number FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id
                WHERE sc.episode_id = :e ORDER BY sc.scene_number, sh.shot_number"""), {"e": str(episode_id)}).mappings()]


def generate_for_episode(db: Session, episode_id: UUID, *, shot_ids: list[UUID] | None = None,
                         regenerate: bool = False) -> dict:
    """Queue keyframes for an episode's shots in story order. Without `regenerate`, shots that already have a live
    keyframe (in progress, finished, or waiting for review) are left alone; failed ones are tried again. With it, the
    chosen shots (all by default) get a fresh keyframe and the old one is retired. COMMITS after each request so the
    queue order is the story order. Raises ValueError when the style bible is not approved."""
    series_id = db.execute(text("SELECT series_id FROM episodes WHERE id = :e"), {"e": str(episode_id)}).scalar()
    if series_id is None:
        raise LookupError("Episode was not found")
    bible = get_approved(db, series_id)
    if bible is None:
        raise ValueError("Approve the style bible first: every keyframe is built from it")
    shots = _shots_of_episode(db, episode_id)
    if not shots:
        raise ValueError("This episode has no shots yet; break it down first")
    wanted = {str(s) for s in shot_ids} if shot_ids else None
    current = _current(db, [str(s["id"]) for s in shots])
    created, skipped, warnings = [], 0, {}
    for shot in shots:
        sid = str(shot["id"])
        if wanted is not None and sid not in wanted:
            continue
        old = current.get(sid)
        live = old is not None and (old["status"] in OPEN or (old["status"] == "succeeded" and old["review_status"] != "rejected"))
        if live and not regenerate:
            skipped += 1
            continue
        request = create_keyframe(db, sid, bible, previous_request_id=old["id"] if old else None)
        if old is not None and live:
            _retire(db, old, request["id"], "Regenerated")
        db.commit()
        created.append(request["id"])
        if request["params"].get("warnings"):
            warnings[sid] = request["params"]["warnings"]
    return {"created": len(created), "skipped": skipped, "request_ids": [str(i) for i in created], "warnings": warnings}


# ---------------------------------------------------------------- reading for the UI

def _present_keyframe(db: Session, row: dict, attempts: int) -> dict:
    params = row["params"] or {}
    labels = params.get("reference_labels") or {}
    references = [{"asset_id": str(a), "label": labels.get(str(a), "Reference")} for a in row["reference_asset_ids"] or []]
    asset = get_asset(db, row["result_asset_id"]) if row["result_asset_id"] else None
    return {"id": str(row["id"]), "status": row["status"], "review_status": row["review_status"],
            "review_note": row["review_note"], "prompt": row["prompt"], "negative_prompt": row["negative_prompt"],
            "references": references, "warnings": params.get("warnings") or [], "checks": row["checks"] or {},
            "error_summary": row["error_summary"], "attempts": attempts, "provider": row["provider"],
            "created_at": row["created_at"], "result": asset_summary(asset)}


def episode_grid(db: Session, episode_id: UUID) -> dict:
    episode = db.execute(text("SELECT id, series_id, episode_number, title FROM episodes WHERE id = :e"),
                         {"e": str(episode_id)}).mappings().first()
    if episode is None:
        raise LookupError("Episode was not found")
    rows = db.execute(
        text("""SELECT sc.id AS scene_id, sc.scene_number, sc.title AS scene_title, sc.continuity_state,
                       sh.id AS shot_id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds, sh.character_ids
                FROM scenes sc JOIN shots sh ON sh.scene_id = sc.id WHERE sc.episode_id = :e
                ORDER BY sc.scene_number, sh.shot_number"""), {"e": str(episode_id)}).mappings().all()
    shot_ids = [str(r["shot_id"]) for r in rows]
    current = _current(db, shot_ids)
    attempts = {}
    if shot_ids:
        attempts = {str(r[0]): r[1] for r in db.execute(
            text("""SELECT target_id, count(*) FROM generation_requests WHERE kind = 'keyframe'
                    AND target_id = ANY(CAST(:ids AS uuid[])) GROUP BY target_id"""), {"ids": "{" + ",".join(shot_ids) + "}"})}
    names = {str(r[0]): r[1] for r in db.execute(text("SELECT id, name FROM characters WHERE series_id = :s"),
                                                  {"s": str(episode["series_id"])})}
    scenes: dict[str, dict] = {}
    totals = {"shots": 0, "not_generated": 0, "working": 0, "needs_review": 0, "approved": 0, "failed": 0, "flagged": 0}
    for r in rows:
        scene = scenes.setdefault(str(r["scene_id"]), {
            "id": str(r["scene_id"]), "scene_number": r["scene_number"], "title": r["scene_title"],
            "location": (r["continuity_state"] or {}).get("location"),
            "time_of_day": (r["continuity_state"] or {}).get("time_of_day"), "shots": []})
        sid = str(r["shot_id"])
        keyframe = current.get(sid)
        totals["shots"] += 1
        if keyframe is None:
            totals["not_generated"] += 1
        elif keyframe["status"] in OPEN:
            totals["working"] += 1
        elif keyframe["status"] == "failed":
            totals["failed"] += 1
        elif keyframe["status"] == "succeeded":
            totals["approved" if keyframe["review_status"] == "approved" else "needs_review"] += 1
            if (keyframe["checks"] or {}).get("status") == "flagged":
                totals["flagged"] += 1
        scene["shots"].append({
            "id": sid, "shot_number": r["shot_number"], "description": r["description"], "camera": r["camera"],
            "duration_seconds": float(r["duration_seconds"]) if r["duration_seconds"] is not None else None,
            "characters": [names[str(c)] for c in r["character_ids"] or [] if str(c) in names],
            "keyframe": _present_keyframe(db, keyframe, attempts.get(sid, 1)) if keyframe else None})
    approved = get_approved(db, episode["series_id"]) is not None
    return {"episode": {"id": str(episode["id"]), "episode_number": episode["episode_number"], "title": episode["title"]},
            "style_approved": approved, "totals": totals, "scenes": list(scenes.values())}


def series_overview(db: Session, series_id: UUID) -> dict:
    rows = db.execute(
        text("""WITH latest AS (
                    SELECT DISTINCT ON (target_id) target_id, status, review_status FROM generation_requests
                    WHERE series_id = :s AND kind = 'keyframe' ORDER BY target_id, created_at DESC)
                SELECT e.id, e.episode_number, e.title, count(sh.id) AS shots, count(l.target_id) AS generated,
                       count(*) FILTER (WHERE l.status = 'succeeded' AND l.review_status = 'approved') AS approved,
                       count(*) FILTER (WHERE l.status = 'succeeded' AND l.review_status = 'pending') AS needs_review,
                       count(*) FILTER (WHERE l.status IN ('queued', 'blocked', 'running', 'awaiting_input')) AS working,
                       count(*) FILTER (WHERE l.status = 'failed') AS failed
                FROM episodes e JOIN scenes sc ON sc.episode_id = e.id JOIN shots sh ON sh.scene_id = sc.id
                LEFT JOIN latest l ON l.target_id = sh.id
                WHERE e.series_id = :s GROUP BY e.id ORDER BY e.episode_number"""), {"s": str(series_id)}).mappings().all()
    return {"style_approved": get_approved(db, series_id) is not None, "count": len(rows),
            "items": [{**dict(r), "id": str(r["id"])} for r in rows]}
