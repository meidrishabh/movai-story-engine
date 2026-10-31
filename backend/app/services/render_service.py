"""Episode renders: the animatic, a draft assembled from the clips, and the final export.

- animatic: each shot's keyframe held for the shot's length (and the sound plan's audio, if any), at the low-res
  working size. A cheap way to check pacing before paying for video.
- draft: the clips trimmed to their shots and stitched, low-res. A shot with no clip yet shows its keyframe, and a short
  clip holds its last frame, so a partly finished episode is still watchable.
- final: only when every shot has an approved clip; stitched at the full profile, then upscaled to the export height.

All three go through `app.media.assemble_episode`, which keeps intermediate files by content hash, so changing one shot
rebuilds only its scene and the episode file. Results are stored as assets; an unchanged episode reuses its asset.
"""
import json
import logging
import re
from pathlib import Path
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.core.settings import settings
from app.media import ops
from app.media.assemble import assemble_episode, file_hash
from app.media.errors import ClipTooShortError, MediaError
from app.media.runner import Profile, default_profile
from app.media.stills import still_clip
from app.services import video_service as video
from app.services.asset_store import asset_summary, get_asset, save_asset

log = logging.getLogger("render")

KINDS = ("animatic", "draft", "final")


def working_profile() -> Profile:
    return Profile(width=settings.render_working_width, height=settings.render_working_height,
                   fps=settings.render_working_fps, crf=settings.render_working_crf, preset="veryfast")


def _present(row: dict, db: Session) -> dict:
    out = {k: (str(v) if k.endswith("_id") or k == "id" else v) for k, v in dict(row).items()}
    out["duration_seconds"] = float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
    out["asset"] = asset_summary(get_asset(db, row["asset_id"])) if row["asset_id"] else None
    out["subtitle_asset"] = asset_summary(get_asset(db, row["subtitle_asset_id"])) if row["subtitle_asset_id"] else None
    out["download_url"] = f"/api/v1/episode-renders/{row['id']}/download" if row["asset_id"] else None
    return out


def latest_renders(db: Session, episode_id: UUID) -> dict:
    """The newest render of each kind (any status), keyed by kind."""
    rows = db.execute(
        text("""SELECT DISTINCT ON (kind) * FROM episode_renders WHERE episode_id = :e
                ORDER BY kind, created_at DESC"""), {"e": str(episode_id)}).mappings().all()
    return {row["kind"]: _present(row, db) for row in rows}


def list_renders(db: Session, episode_id: UUID, kind: str | None = None, limit: int = 30) -> list[dict]:
    clause, params = "episode_id = :e", {"e": str(episode_id), "limit": limit}
    if kind:
        clause += " AND kind = :k"
        params["k"] = kind
    rows = db.execute(text(f"SELECT * FROM episode_renders WHERE {clause} ORDER BY created_at DESC LIMIT :limit"),
                      params).mappings().all()
    return [_present(r, db) for r in rows]


def get_render(db: Session, render_id: UUID) -> dict | None:
    row = db.execute(text("SELECT * FROM episode_renders WHERE id = :r"), {"r": str(render_id)}).mappings().first()
    return _present(row, db) if row else None


# --- inputs --------------------------------------------------------------------------------------------------------

def _gather(db: Session, episode_id: UUID, kind: str) -> tuple[dict, list[dict], dict]:
    """The episode, its shots with the keyframe and clip each render will use, and the problems found."""
    episode = video.get_episode(db, episode_id)
    shots = video.shot_rows(db, episode_id)
    ids = [s["shot_id"] for s in shots]
    keyframes = video.requests_by_shot(db, episode["series_id"], "keyframe", ids)
    clips = video.requests_by_shot(db, episode["series_id"], "video_clip", ids)
    problems = {"missing_clip": [], "unapproved_clip": [], "short_clip": []}
    rows = []
    for shot in shots:
        key = str(shot["shot_id"])
        keyframe = video.pick_keyframe(keyframes.get(key, []), allow_unapproved=True)
        usable = [r for r in clips.get(key, []) if r["status"] == "succeeded" and r["result_asset_id"]
                  and r["review_status"] != "rejected"]
        clip = usable[-1] if usable else None
        if kind == "final":
            approved = [r for r in usable if r["review_status"] == "approved"]
            clip = approved[-1] if approved else None
            if clip is None:
                problems["unapproved_clip" if usable else "missing_clip"].append(key)
        rows.append({"shot": shot, "keyframe": keyframe, "clip": clip})
    return episode, rows, problems


def create_render(db: Session, episode_id: UUID, kind: str) -> dict:
    """Queue a render job. A final export is refused until every shot has an approved clip. The caller commits."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    episode, rows, problems = _gather(db, episode_id, kind)
    if not rows:
        raise ValueError("The episode has no shots yet")
    if kind == "final" and (problems["missing_clip"] or problems["unapproved_clip"]):
        raise ValueError(f"A final export needs an approved clip for every shot: {len(problems['missing_clip'])} shots "
                         f"have no clip and {len(problems['unapproved_clip'])} have a clip that is not approved yet")
    if kind == "animatic" and not any(r["keyframe"] for r in rows):
        raise ValueError("No shot has a keyframe yet, so there is nothing to show in an animatic")
    if kind == "draft" and not any(r["clip"] for r in rows):
        raise ValueError("No shot has a finished clip yet; make an animatic to check pacing instead")
    active = db.execute(text("""SELECT id FROM episode_renders WHERE episode_id = :e AND kind = :k
                                AND status IN ('queued', 'running')"""), {"e": str(episode_id), "k": kind}).scalar()
    if active:
        raise ValueError(f"A {kind} render is already in progress")
    row = db.execute(
        text("""INSERT INTO episode_renders (series_id, episode_id, kind, status) VALUES (:s, :e, :k, 'queued')
                RETURNING *"""), {"s": str(episode["series_id"]), "e": str(episode_id), "k": kind}).mappings().one()
    db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                VALUES ('episode_render', 'queued', 'media', CAST(:m AS jsonb))"""),
        {"m": json.dumps({"episode_render_id": str(row["id"]), "series_id": str(episode["series_id"])})})
    return _present(row, db)


# --- the render -----------------------------------------------------------------------------------------------------

def _audio_plan(db: Session, episode_id: UUID) -> dict[str, dict]:
    """Per shot: audio tracks and subtitles from sound_service's audio plan, in the shape assemble_episode takes."""
    from app.services.sound_service import build_audio_plan  # imported here: sound_service imports generation code
    try:
        plan = build_audio_plan(db, episode_id) or {}
    except Exception:  # noqa: BLE001 - a broken sound plan must not stop the picture
        log.warning("build_audio_plan failed for episode %s; rendering without audio", episode_id, exc_info=True)
        return {}
    resolved: dict[str, dict] = {}
    for shot_id, entry in plan.items():
        tracks = []
        for track in entry.get("audio_tracks") or []:
            track = dict(track)
            if not track.get("path") and track.get("asset_id"):
                asset = get_asset(db, track["asset_id"])
                if asset is None:
                    continue
                track["path"] = str(video.local_file(asset))
            if track.get("path"):
                tracks.append(track)
        resolved[str(shot_id)] = {"audio_tracks": tracks, "subtitles": entry.get("subtitles") or []}
    return resolved


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "episode"


def mark_failed(db: Session, render_id: UUID, summary: str) -> None:
    db.execute(text("""UPDATE episode_renders SET status = 'failed', error_summary = :s, completed_at = now()
                       WHERE id = :r"""), {"r": str(render_id), "s": summary[:1000]})


def _previous_assets(db: Session, episode_id: UUID, kind: str) -> tuple[dict, dict]:
    """Scene and episode assets from earlier renders of this kind, by content key, so unchanged files are not stored twice."""
    scenes, episodes = {}, {}
    rows = db.execute(text("""SELECT asset_id, details FROM episode_renders WHERE episode_id = :e AND kind = :k
                              AND status = 'succeeded' ORDER BY created_at"""), {"e": str(episode_id), "k": kind}).mappings().all()
    for row in rows:
        details = row["details"] or {}
        if details.get("episode_key") and row["asset_id"]:
            episodes[details["episode_key"]] = row["asset_id"]
        for scene in details.get("scenes") or []:
            if scene.get("key") and scene.get("asset_id"):
                scenes[scene["key"]] = scene["asset_id"]
    return scenes, episodes


def _store_file(db: Session, path: str | Path, series_id, *, reuse: dict, key: str | None, filename: str, kind: str,
                provider: str = "render") -> tuple[str, bool]:
    """Save a built file as an asset unless an earlier render already stored the same one. Returns (asset id, reused)."""
    if key and key in reuse and get_asset(db, reuse[key]) is not None:
        return str(reuse[key]), True
    info = ops.probe(path)
    asset = save_asset(db, Path(path).read_bytes(), "video/mp4", series_id=series_id, provider=provider,
                       model="ffmpeg", width=info.width, height=info.height, duration_seconds=info.duration,
                       filename=filename, metadata={"render_kind": kind, "content_key": key})
    return str(asset["id"]), False


def run_render(db: Session, render_id: UUID) -> dict:
    """Called by the job runner. Builds the render with ffmpeg and stores the result."""
    render = db.execute(text("SELECT * FROM episode_renders WHERE id = :r"), {"r": str(render_id)}).mappings().first()
    if render is None:
        raise PermanentJobError(f"Render {render_id} no longer exists")
    if render["status"] not in ("queued", "running"):
        return {"render_id": str(render_id), "skipped": render["status"]}
    db.execute(text("""UPDATE episode_renders SET status = 'running', error_summary = NULL,
                       started_at = COALESCE(started_at, now()) WHERE id = :r"""), {"r": str(render_id)})
    db.commit()
    try:
        result = _build(db, render)
    except (MediaError, ValueError) as error:  # a bad clip or a missing tool will not fix itself on retry
        db.rollback()
        raise PermanentJobError(f"{type(error).__name__}: {error}") from error
    db.commit()
    return result


def _build(db: Session, render: dict) -> dict:
    kind, episode_id = render["kind"], render["episode_id"]
    episode, rows, problems = _gather(db, episode_id, kind)
    if kind == "final" and (problems["missing_clip"] or problems["unapproved_clip"]):
        raise ValueError("Every shot needs an approved clip before the final export")
    profile = default_profile() if kind == "final" else working_profile()
    work = video.work_root() / str(episode["series_id"]) / str(episode_id) / f"{kind}-{profile.width}x{profile.height}"
    plan = _audio_plan(db, episode_id)
    assets = video.assets_by_id(db, [r["clip"]["result_asset_id"] for r in rows if r["clip"]]
                                + [r["keyframe"]["result_asset_id"] for r in rows if r["keyframe"]])
    shots, stills, auto_hold = [], [], []
    for row in rows:
        shot = row["shot"]
        key = str(shot["shot_id"])
        seconds = video.shot_seconds(shot)
        extras = plan.get(key, {})
        entry = {"shot_id": key, "scene_id": str(shot["scene_id"]), "audio_tracks": extras.get("audio_tracks", []),
                 "subtitles": extras.get("subtitles", [])}
        clip = row["clip"] if kind != "animatic" else None
        if clip is not None:
            asset = assets[str(clip["result_asset_id"])]
            entry["clip"] = str(video.local_file(asset))
            entry["trim_seconds"] = seconds
            hold = bool((clip["params"] or {}).get("hold_last_frame"))
            state = video.clip_state(seconds, video.probe_asset(db, asset), hold)
            if state["trim"] == "short" and kind == "final":
                raise ClipTooShortError(entry["clip"], state["actual_seconds"], seconds)
            if state["trim"] == "unplayable":
                raise ValueError(f"The clip for shot {shot['scene_number']}.{shot['shot_number']} is not a playable video")
            if state["trim"] == "short":  # a draft stays watchable: hold the last frame and say so
                hold = True
                auto_hold.append(key)
            entry["hold_last_frame"] = hold
        else:
            keyframe = row["keyframe"]
            image = None
            if keyframe is not None:
                image = video.local_file(assets[str(keyframe["result_asset_id"])])
            token = file_hash(image)[:16] if image else "card"
            still = work / "stills" / f"{token}-{seconds:g}.mp4"
            if not still.exists():
                still_clip(image, still, seconds, profile)
            entry["clip"] = str(still)
            entry["trim_seconds"] = None
            if kind != "animatic":
                stills.append(key)
        shots.append(entry)
    name = f"episode-{episode['episode_number']}"
    result = assemble_episode(shots, work, profile=profile, subtitle_mode="soft" if kind == "final" else "burn",
                              episode_name=name)
    series_id = episode["series_id"]
    prev_scenes, prev_episodes = _previous_assets(db, episode_id, kind)
    scene_numbers = {str(r["shot"]["scene_id"]): (r["shot"]["scene_number"], r["shot"]["scene_title"]) for r in rows}
    scenes_out = []
    for scene in result.scenes:
        number, title = scene_numbers.get(str(scene["scene_id"]), (None, None))
        asset_id, _reused = _store_file(db, scene["path"], series_id, reuse=prev_scenes, key=scene["key"],
                                        filename=f"{name}-scene-{number}.mp4", kind=kind)
        scenes_out.append({"scene_id": str(scene["scene_id"]), "scene_number": number, "title": title,
                           "key": scene["key"], "duration": round(scene["duration"], 2), "asset_id": asset_id,
                           "shot_ids": [str(s) for s in scene["shot_ids"]], "cached": scene["cached"]})
    final_path, episode_key = result.episode.path, result.episode.key
    if kind == "final":
        target = Path(final_path).with_name(Path(final_path).stem + f"-{settings.final_export_height}p.mp4")
        if not target.exists():
            ops.upscale(final_path, target, target_height=settings.final_export_height, profile=profile)
        final_path = str(target)
        episode_key = f"{episode_key}-{settings.final_export_height}"
    filename = f"{name}-{_slug(episode['title'])}" + ("-final" if kind == "final" else f"-{kind}") + ".mp4"
    asset_id, reused = _store_file(db, final_path, series_id, reuse=prev_episodes, key=episode_key, filename=filename,
                                   kind=kind)
    subtitle_asset_id = None
    if result.subtitle_srt:
        asset = save_asset(db, Path(result.subtitle_srt).read_bytes(), "application/x-subrip", series_id=series_id,
                           provider="render", model="ffmpeg", filename=f"{name}.srt")
        subtitle_asset_id = str(asset["id"])
    info = ops.probe(final_path)
    details = {"episode_key": episode_key, "profile": {"width": info.width, "height": info.height, "fps": profile.fps},
               "scenes": scenes_out, "shots": [{**s, "path": None} for s in result.shots],
               "rebuilt_shots": result.rebuilt_shots, "rebuilt_scenes": result.rebuilt_scenes, "unchanged": reused,
               "stills": stills, "auto_hold": auto_hold, "audio": bool(plan)}
    db.execute(text("""UPDATE episode_renders SET status = 'succeeded', asset_id = :a, subtitle_asset_id = :sub,
                       duration_seconds = :d, details = CAST(:details AS jsonb), completed_at = now() WHERE id = :r"""),
               {"a": asset_id, "sub": subtitle_asset_id, "d": round(info.duration, 2),
                "details": json.dumps(details, default=str), "r": str(render["id"])})
    return {"render_id": str(render["id"]), "kind": kind, "asset_id": asset_id, "duration": round(info.duration, 2),
            "rebuilt_shots": result.rebuilt_shots, "rebuilt_scenes": result.rebuilt_scenes, "unchanged": reused}
