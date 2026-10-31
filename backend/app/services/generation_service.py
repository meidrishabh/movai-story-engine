"""Generation requests: one row per image, clip, voice line or music cue to make.

Requests may depend on others (a video clip waits for its keyframe). A request with unfinished dependencies is
`blocked`; the rest are `queued` with a `generation_request` job for the job runner. The runner calls `run_request`,
which calls the configured provider and stores the result as an asset. The user's verdict goes through `review_request`.

Request `params` (all optional):
  aspect_ratio, width, height, seed          image and video
  first_frame_asset_id                       video: the keyframe the clip starts from (must be in reference_asset_ids)
  duration_seconds, fps, sound_prompt        video; duration_seconds also for music
  voice, language, style, speed, text        voice (text defaults to the prompt)
  music_kind                                 "music" | "sfx" | "ambience"
  deps_need_approval                         true: wait until the dependencies are approved, not just finished
"""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.image_base import ImageRequest
from app.providers.media_base import GeneratedMedia, MediaPending, ReferenceImage
from app.providers.media_factory import get_image_provider, get_music_provider, get_video_provider, get_voice_provider
from app.providers.music_base import MusicRequest
from app.providers.video_base import VideoRequest
from app.providers.voice_base import VoiceRequest
from app.services.asset_store import asset_summary, get_asset, get_storage, save_asset

KIND_MEDIA = {"style_anchor": "image", "character_image": "image", "place_image": "image", "object_image": "image",
              "keyframe": "image", "video_clip": "video", "voice_line": "voice", "music": "music", "sfx": "music"}
FINISHED = ("succeeded",)
OPEN_STATUSES = ("queued", "blocked", "running", "awaiting_input")


def _present(row, asset: dict | None) -> dict:
    out = dict(row)
    out["reference_asset_ids"] = [str(i) for i in out["reference_asset_ids"] or []]
    out["depends_on"] = [str(i) for i in out["depends_on"] or []]
    out["cost"] = float(out["cost"] or 0)
    out["result"] = asset_summary(asset)
    return out


def _queue_job(db: Session, request_id, series_id) -> None:
    active = db.execute(
        text("""SELECT 1 FROM generation_jobs WHERE job_type = 'generation_request' AND status IN ('queued', 'running')
                AND request_metadata ->> 'generation_request_id' = :r"""), {"r": str(request_id)}).scalar()
    if not active:
        db.execute(
            text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                    VALUES ('generation_request', 'queued', 'media',
                            CAST(:m AS jsonb))"""),
            {"m": json.dumps({"generation_request_id": str(request_id), "series_id": str(series_id)})})


def _deps_ready(db: Session, request) -> bool:
    deps = [str(d) for d in request["depends_on"] or []]
    if not deps:
        return True
    need_approval = bool((request["params"] or {}).get("deps_need_approval"))
    ready = db.execute(
        text("""SELECT count(*) FROM generation_requests WHERE id = ANY(CAST(:d AS uuid[])) AND status = 'succeeded'
                AND (NOT :approved OR review_status = 'approved')"""),
        {"d": "{" + ",".join(deps) + "}", "approved": need_approval}).scalar()
    return ready == len(set(deps))


def create_request(db: Session, series_id: UUID, kind: str, prompt: str, *, media_type: str | None = None,
                   target_type: str | None = None, target_id: UUID | None = None, negative_prompt: str | None = None,
                   params: dict | None = None, reference_asset_ids: list[UUID] | None = None,
                   depends_on: list[UUID] | None = None, previous_request_id: UUID | None = None) -> dict:
    """Create a request and queue it, or block it until its dependencies are done. The caller commits."""
    media_type = media_type or KIND_MEDIA.get(kind)
    if media_type is None:
        raise ValueError(f"Kind '{kind}' needs an explicit media_type")
    depends_on = list(dict.fromkeys(depends_on or []))
    if depends_on:
        found = db.execute(
            text("SELECT count(*) FROM generation_requests WHERE id = ANY(CAST(:d AS uuid[])) AND series_id = :s"),
            {"d": "{" + ",".join(str(d) for d in depends_on) + "}", "s": str(series_id)}).scalar()
        if found != len(depends_on):
            raise ValueError("A dependency is not a request of this series")
    row = db.execute(
        text("""INSERT INTO generation_requests (series_id, kind, media_type, target_type, target_id, prompt,
                    negative_prompt, params, reference_asset_ids, depends_on, previous_request_id, status)
                VALUES (:s, :kind, :media, :tt, :tid, :prompt, :neg, CAST(:params AS jsonb),
                        CAST(:refs AS uuid[]), CAST(:deps AS uuid[]), :prev, 'queued')
                RETURNING *"""),
        {"s": str(series_id), "kind": kind, "media": media_type, "tt": target_type,
         "tid": str(target_id) if target_id else None, "prompt": prompt, "neg": negative_prompt,
         "params": json.dumps(params or {}), "refs": "{" + ",".join(str(r) for r in reference_asset_ids or []) + "}",
         "deps": "{" + ",".join(str(d) for d in depends_on) + "}",
         "prev": str(previous_request_id) if previous_request_id else None}).mappings().one()
    if _deps_ready(db, row):
        _queue_job(db, row["id"], series_id)
    else:
        row = db.execute(text("UPDATE generation_requests SET status = 'blocked' WHERE id = :r RETURNING *"),
                         {"r": str(row["id"])}).mappings().one()
    return _present(row, None)


def release_dependents(db: Session, request_id) -> list[str]:
    """Queue every blocked request that was only waiting for this one (and others that have since finished)."""
    released = []
    for row in db.execute(
            text("SELECT * FROM generation_requests WHERE status = 'blocked' AND CAST(:r AS uuid) = ANY(depends_on)"),
            {"r": str(request_id)}).mappings().all():
        if _deps_ready(db, row):
            db.execute(text("UPDATE generation_requests SET status = 'queued' WHERE id = :r"), {"r": str(row["id"])})
            _queue_job(db, row["id"], row["series_id"])
            released.append(str(row["id"]))
    return released


def _references(db: Session, row) -> tuple[ReferenceImage | None, tuple[ReferenceImage, ...]]:
    """The request's images loaded for the provider: the first frame (video only) and the other references."""
    first_id = str((row["params"] or {}).get("first_frame_asset_id") or "")
    first, others = None, []
    storage = get_storage()
    for asset_id in row["reference_asset_ids"] or []:
        asset = get_asset(db, asset_id)
        if asset is None or asset["kind"] != "image":
            continue  # a deleted or non-image reference is skipped rather than failing the whole request
        image = ReferenceImage(data=storage.read(asset["storage_key"]), mime_type=asset["mime_type"],
                               role="first_frame" if str(asset_id) == first_id else "reference", asset_id=str(asset_id))
        if image.role == "first_frame":
            first = image
        else:
            others.append(image)
    return first, tuple(others)


def _provider(factory):
    try:
        return factory()
    except ValueError as error:  # an unknown or unconfigured provider will not fix itself on retry
        raise PermanentJobError(str(error)) from error


def _generate(db: Session, row) -> GeneratedMedia:
    params = row["params"] or {}
    first, references = _references(db, row)
    common = {"seed": params.get("seed")}
    media = row["media_type"]
    if media == "image":
        request = ImageRequest(prompt=row["prompt"], negative_prompt=row["negative_prompt"] or "", references=references,
                               aspect_ratio=params.get("aspect_ratio", "16:9"), width=params.get("width"),
                               height=params.get("height"), **common)
        return _provider(get_image_provider).generate(request)
    if media == "video":
        request = VideoRequest(prompt=row["prompt"], negative_prompt=row["negative_prompt"] or "", first_frame=first,
                               references=references, duration_seconds=float(params.get("duration_seconds") or 5.0),
                               aspect_ratio=params.get("aspect_ratio", "16:9"), width=params.get("width"),
                               height=params.get("height"), fps=int(params.get("fps") or 24),
                               sound_prompt=params.get("sound_prompt", ""), **common)
        return _provider(get_video_provider).generate(request)
    if media == "voice":
        request = VoiceRequest(text=params.get("text") or row["prompt"], voice=params.get("voice", ""),
                               language=params.get("language", "en"), style=params.get("style", ""),
                               speed=float(params.get("speed") or 1.0), **common)
        return _provider(get_voice_provider).generate(request)
    if media == "music":
        request = MusicRequest(prompt=row["prompt"], duration_seconds=float(params.get("duration_seconds") or 30.0),
                               kind=params.get("music_kind") or ("sfx" if row["kind"] == "sfx" else "music"), **common)
        return _provider(get_music_provider).generate(request)
    raise PermanentJobError(f"Unknown media type '{media}'")


def _finish(db: Session, row, data: bytes, mime_type: str, *, provider: str, model: str, cost: float = 0.0,
            width=None, height=None, duration_seconds=None, filename=None, metadata=None) -> dict:
    asset = save_asset(db, data, mime_type, series_id=row["series_id"], provider=provider, model=model,
                       source_request_id=row["id"], width=width, height=height, duration_seconds=duration_seconds,
                       filename=filename, metadata=metadata)
    updated = db.execute(
        text("""UPDATE generation_requests SET status = 'succeeded', result_asset_id = :a, provider = :p, cost = :c,
                       error_summary = NULL, completed_at = now() WHERE id = :r RETURNING *"""),
        {"a": str(asset["id"]), "p": provider, "c": cost, "r": str(row["id"])}).mappings().one()
    released = release_dependents(db, row["id"])
    return {"request_id": str(row["id"]), "asset_id": str(asset["id"]), "cost": cost, "released": released,
            "status": updated["status"]}


def run_request(db: Session, request_id: UUID) -> dict:
    """Called by the job runner. Makes the media with the configured provider and stores it."""
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise PermanentJobError(f"Generation request {request_id} no longer exists")
    if row["status"] not in ("queued", "running"):
        return {"request_id": str(request_id), "skipped": row["status"]}  # finished, rejected or filled in by hand
    db.execute(
        text("""UPDATE generation_requests SET status = 'running', attempt_count = attempt_count + 1,
                       started_at = COALESCE(started_at, now()), error_summary = NULL WHERE id = :r"""),
        {"r": str(request_id)})
    db.commit()
    try:
        media = _generate(db, row)
    except MediaPending:
        db.execute(text("UPDATE generation_requests SET status = 'awaiting_input' WHERE id = :r"), {"r": str(request_id)})
        db.commit()
        return {"request_id": str(request_id), "status": "awaiting_input"}
    result = _finish(db, row, media.data, media.mime_type, provider=media.provider, model=media.model, cost=media.cost,
                     width=media.width, height=media.height, duration_seconds=media.duration_seconds,
                     metadata=media.metadata)
    db.commit()
    return result


def mark_failed(db: Session, request_id: UUID, summary: str) -> None:
    db.execute(text("UPDATE generation_requests SET status = 'failed', error_summary = :s, completed_at = now() WHERE id = :r"),
               {"r": str(request_id), "s": summary[:1000]})


def attach_result(db: Session, request_id: UUID, data: bytes, mime_type: str, *, provider: str = "manual",
                  model: str = "uploaded", filename: str | None = None, width: int | None = None,
                  height: int | None = None, duration_seconds: float | None = None, cost: float = 0.0) -> dict:
    """Supply the result by hand (or from an outside system). Used by providers that raise MediaPending.
    Works on a request that is awaiting input, queued, blocked or failed. The caller commits."""
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r FOR UPDATE"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise LookupError("Request was not found")
    if row["status"] not in ("awaiting_input", "queued", "blocked", "failed"):
        raise ValueError(f"A {row['status']} request cannot take a result")
    result = _finish(db, row, data, mime_type, provider=provider, model=model, cost=cost, width=width, height=height,
                     duration_seconds=duration_seconds, filename=filename)
    return result


def review_request(db: Session, request_id: UUID, decision: str, note: str | None = None) -> dict:
    """The user's verdict on a finished request. Approving releases requests that waited for approval. Rejecting
    marks it rejected and queues a new attempt with the note added to the prompt; requests waiting on the rejected
    one now wait on the new attempt. The caller commits."""
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r FOR UPDATE"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise LookupError("Request was not found")
    if row["status"] != "succeeded":
        raise ValueError("Only a finished request can be reviewed")
    if decision == "approve":
        db.execute(text("""UPDATE generation_requests SET review_status = 'approved', review_note = :n, reviewed_at = now()
                           WHERE id = :r"""), {"r": str(request_id), "n": note})
        return {"request_id": str(request_id), "review_status": "approved", "released": release_dependents(db, request_id)}
    if decision != "reject":
        raise ValueError("decision must be 'approve' or 'reject'")
    db.execute(text("""UPDATE generation_requests SET status = 'rejected', review_status = 'rejected', review_note = :n,
                              reviewed_at = now() WHERE id = :r"""), {"r": str(request_id), "n": note})
    prompt = row["prompt"] + (f"\n\nRevision note: {note.strip()}" if note and note.strip() else "")
    params = dict(row["params"] or {})
    params.pop("seed", None)  # a new attempt should not repeat the same random draw
    params["attempt"] = int(params.get("attempt") or 1) + 1
    new = create_request(db, row["series_id"], row["kind"], prompt, media_type=row["media_type"],
                         target_type=row["target_type"], target_id=row["target_id"], negative_prompt=row["negative_prompt"],
                         params=params, reference_asset_ids=list(row["reference_asset_ids"] or []),
                         depends_on=list(row["depends_on"] or []), previous_request_id=row["id"])
    db.execute(text("""UPDATE generation_requests SET depends_on = array_replace(depends_on, CAST(:old AS uuid), CAST(:new AS uuid))
                       WHERE CAST(:old AS uuid) = ANY(depends_on) AND series_id = :s"""),
               {"old": str(request_id), "new": str(new["id"]), "s": str(row["series_id"])})
    return {"request_id": str(request_id), "review_status": "rejected", "new_request": new}


def retry_request(db: Session, request_id: UUID) -> dict:
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r FOR UPDATE"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise LookupError("Request was not found")
    if row["status"] != "failed":
        raise ValueError("Only a failed request can be retried")
    updated = db.execute(
        text("""UPDATE generation_requests SET status = 'queued', attempt_count = 0, error_summary = NULL, completed_at = NULL
                WHERE id = :r RETURNING *"""), {"r": str(request_id)}).mappings().one()
    _queue_job(db, request_id, row["series_id"])
    return _present(updated, None)


def get_request(db: Session, request_id: UUID) -> dict | None:
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).mappings().first()
    if row is None:
        return None
    return _present(row, get_asset(db, row["result_asset_id"]) if row["result_asset_id"] else None)


def list_requests(db: Session, series_id: UUID, *, kind: str | None = None, status: str | None = None,
                  target_id: UUID | None = None, review_status: str | None = None, limit: int = 200) -> list[dict]:
    clauses, params = ["series_id = :s"], {"s": str(series_id), "limit": limit}
    for column, value in (("kind", kind), ("status", status), ("review_status", review_status)):
        if value:
            clauses.append(f"{column} = :{column}")
            params[column] = value
    if target_id:
        clauses.append("target_id = :target")
        params["target"] = str(target_id)
    rows = db.execute(text(f"SELECT * FROM generation_requests WHERE {' AND '.join(clauses)} ORDER BY created_at DESC LIMIT :limit"),
                      params).mappings().all()
    ids = [str(r["result_asset_id"]) for r in rows if r["result_asset_id"]]
    assets = {}
    if ids:
        assets = {str(a["id"]): dict(a) for a in db.execute(
            text("SELECT * FROM assets WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": "{" + ",".join(ids) + "}"}).mappings()}
    return [_present(r, assets.get(str(r["result_asset_id"]))) for r in rows]
