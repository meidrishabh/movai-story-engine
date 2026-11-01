"""Promo renders: the animatic, a draft and the final export of a teaser or trailer.

- animatic: each shot's keyframe held for its trim, title cards, music and narration; low-res working size.
- draft: each shot's clip (cut from its `start_offset`, trimmed to its `trim_seconds`), or its keyframe when it has no
  clip yet; low-res.
- final: only when every shot has an approved clip; full profile, then upscaled to the export height.

Title cards are made locally by `app.media.titlecards`. Narration and music are laid over the finished picture with
`app.media.mix_audio` (music is ducked under narration). Intermediate files are kept by content hash in the work folder,
so changing one item rebuilds only what depends on it.
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
from app.media.runner import default_profile
from app.media.stills import still_clip
from app.media.titlecards import title_card_clip
from app.services import promo_service
from app.services import render_service as episode_renders
from app.services import video_service as video
from app.services.asset_store import asset_summary, get_asset, save_asset
from app.services.style_bible_service import get_live

log = logging.getLogger("promo_render")

KINDS = ("animatic", "draft", "final")
MUSIC_GAIN = 0.45
NARRATION_GAIN = 1.0


def _present(row: dict, db: Session) -> dict:
    out = {k: (str(v) if k.endswith("_id") or k == "id" else v) for k, v in dict(row).items()}
    out["duration_seconds"] = float(row["duration_seconds"]) if row["duration_seconds"] is not None else None
    out["asset"] = asset_summary(get_asset(db, row["asset_id"])) if row["asset_id"] else None
    out["download_url"] = f"/api/v1/promo-renders/{row['id']}/download" if row["asset_id"] else None
    return out


def latest_renders(db: Session, promo_id: UUID) -> dict:
    rows = db.execute(text("""SELECT DISTINCT ON (kind) * FROM promo_renders WHERE promo_id = :p ORDER BY kind, created_at DESC"""),
                      {"p": str(promo_id)}).mappings().all()
    return {r["kind"]: _present(r, db) for r in rows}


def list_renders(db: Session, promo_id: UUID, limit: int = 30) -> list[dict]:
    rows = db.execute(text("SELECT * FROM promo_renders WHERE promo_id = :p ORDER BY created_at DESC LIMIT :l"),
                      {"p": str(promo_id), "l": limit}).mappings().all()
    return [_present(r, db) for r in rows]


def get_render(db: Session, render_id: UUID) -> dict | None:
    row = db.execute(text("SELECT * FROM promo_renders WHERE id = :r"), {"r": str(render_id)}).mappings().first()
    return _present(row, db) if row else None


# --- inputs ----------------------------------------------------------------------------------------------------------

def _shot_sources(db: Session, items: list[dict], kind: str) -> tuple[list[dict], dict]:
    """For each item: the keyframe and clip request the render will use, plus the problems found."""
    problems = {"missing_clip": [], "unapproved_clip": []}
    rows = []
    for item in items:
        row = {"item": item, "keyframe": None, "clip": None}
        if item["item_type"] == "shot" and item["shot_id"]:
            row["keyframe"] = promo_service._keyframe_of(db, item["shot_id"])  # noqa: SLF001 - same package
            usable = db.execute(
                text("""SELECT * FROM generation_requests WHERE kind = 'video_clip' AND target_id = :s AND status = 'succeeded'
                        AND result_asset_id IS NOT NULL AND review_status <> 'rejected' ORDER BY created_at"""),
                {"s": str(item["shot_id"])}).mappings().all()
            usable = [dict(r) for r in usable]
            clip = usable[-1] if usable else None
            if kind == "final":
                approved = [r for r in usable if r["review_status"] == "approved"]
                clip = approved[-1] if approved else None
                if clip is None:
                    problems["unapproved_clip" if usable else "missing_clip"].append(str(item["id"]))
            row["clip"] = clip
        rows.append(row)
    return rows, problems


def create_render(db: Session, promo_id: UUID, kind: str) -> dict:
    """Queue a render job. A final export is refused until every shot has an approved clip. The caller commits."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    promo = promo_service._promo(db, promo_id)  # noqa: SLF001
    items = promo_service._items(db, promo_id)  # noqa: SLF001
    if not items:
        raise ValueError("The promo has no items yet; plan it or add some first")
    rows, problems = _shot_sources(db, items, kind)
    shots = [r for r in rows if r["item"]["item_type"] == "shot"]
    if kind == "final" and (problems["missing_clip"] or problems["unapproved_clip"]):
        raise ValueError(f"A final export needs an approved clip for every shot: {len(problems['missing_clip'])} have no clip and "
                         f"{len(problems['unapproved_clip'])} have a clip that is not approved yet")
    if shots and not any(r["keyframe"] or r["clip"] for r in shots):
        raise ValueError("No shot has a keyframe or clip yet: use 'Generate missing' first")
    active = db.execute(text("SELECT id FROM promo_renders WHERE promo_id = :p AND kind = :k AND status IN ('queued', 'running')"),
                        {"p": str(promo_id), "k": kind}).scalar()
    if active:
        raise ValueError(f"A {kind} render is already in progress")
    row = db.execute(text("INSERT INTO promo_renders (series_id, promo_id, kind, status) VALUES (:s, :p, :k, 'queued') RETURNING *"),
                     {"s": str(promo["series_id"]), "p": str(promo_id), "k": kind}).mappings().one()
    db.execute(text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                       VALUES ('promo_render', 'queued', 'media', CAST(:m AS jsonb))"""),
               {"m": json.dumps({"promo_render_id": str(row["id"]), "series_id": str(promo["series_id"])})})
    return _present(row, db)


# --- the render ------------------------------------------------------------------------------------------------------

def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "promo"


def run_render(db: Session, render_id: UUID) -> dict:
    """Called by the job runner. Builds the render with ffmpeg and stores the result."""
    render = db.execute(text("SELECT * FROM promo_renders WHERE id = :r"), {"r": str(render_id)}).mappings().first()
    if render is None:
        raise PermanentJobError(f"Promo render {render_id} no longer exists")
    if render["status"] not in ("queued", "running"):
        return {"render_id": str(render_id), "skipped": render["status"]}
    db.execute(text("""UPDATE promo_renders SET status = 'running', error_summary = NULL, started_at = COALESCE(started_at, now())
                       WHERE id = :r"""), {"r": str(render_id)})
    db.commit()
    try:
        result = _build(db, dict(render))
    except (MediaError, ValueError, LookupError) as error:
        db.rollback()
        raise PermanentJobError(f"{type(error).__name__}: {error}") from error
    db.commit()
    return result


def mark_failed(db: Session, render_id: UUID, summary: str) -> None:
    db.execute(text("UPDATE promo_renders SET status = 'failed', error_summary = :s, completed_at = now() WHERE id = :r"),
               {"r": str(render_id), "s": summary[:1000]})


def _audio_asset(db: Session, kind: str, target_type: str, target_id) -> dict | None:
    row = db.execute(
        text("""SELECT result_asset_id FROM generation_requests WHERE kind = :k AND target_type = :tt AND target_id = :t
                AND status = 'succeeded' AND result_asset_id IS NOT NULL AND review_status <> 'rejected'
                ORDER BY created_at DESC LIMIT 1"""), {"k": kind, "tt": target_type, "t": str(target_id)}).first()
    return get_asset(db, row[0]) if row else None


def _build(db: Session, render: dict) -> dict:
    kind, promo_id = render["kind"], render["promo_id"]
    promo = promo_service._promo(db, promo_id)  # noqa: SLF001
    items = promo_service._items(db, promo_id)  # noqa: SLF001
    rows, problems = _shot_sources(db, items, kind)
    if kind == "final" and (problems["missing_clip"] or problems["unapproved_clip"]):
        raise ValueError("Every shot needs an approved clip before the final export")
    profile = default_profile() if kind == "final" else episode_renders.working_profile()
    work = video.work_root() / str(promo["series_id"]) / "promos" / str(promo_id) / f"{kind}-{profile.width}x{profile.height}"
    bible = get_live(db, promo["series_id"]) or {}
    assets = video.assets_by_id(db, [r["clip"]["result_asset_id"] for r in rows if r["clip"]]
                                + [r["keyframe"]["result_asset_id"] for r in rows if r["keyframe"]])
    entries, narrations, clock, stills, cards_without_text, auto_hold = [], [], 0.0, [], 0, []
    timeline: list[dict] = []  # each picture entry with where it starts on the finished timeline and how long it plays
    for row in rows:
        item = row["item"]
        key = str(item["id"])
        if item["item_type"] == "narration":
            if timeline:  # it plays over the picture item before it
                narrations.append({"item": item, "target": timeline[-1]})
            continue
        if item["item_type"] == "title_card":
            seconds = float(item["seconds"] or 2.0)
            token = file_hash_text(f"{item['text']}|{(item['style'] or {}).get('subtitle', '')}|{seconds}|{bible.get('palette', '')}")
            path = work / "cards" / f"{token}.mp4"
            if not path.exists():
                made = title_card_clip(item["text"], path, seconds, profile, palette=bible.get("palette"),
                                       subtitle=(item["style"] or {}).get("subtitle"))
                cards_without_text += 0 if made["text_drawn"] else 1
            entries.append({"shot_id": key, "scene_id": "promo", "clip": str(path), "trim_seconds": None,
                            "audio_tracks": [], "subtitles": []})
            length = seconds
        else:
            seconds = float(item["trim_seconds"] or 3.0)
            offset = float(item["start_offset"] or 0.0)
            clip = row["clip"] if kind != "animatic" else None
            if clip is not None:
                source = video.local_file(assets[str(clip["result_asset_id"])])
                info = ops.probe(source)
                hold = False
                if offset > 0.05:  # start part-way into the clip: keep what follows the offset
                    cut = work / "cuts" / f"{file_hash(source)[:16]}-{offset:g}.mp4"
                    if not cut.exists():
                        ops.trim(source, cut, max(info.duration - offset, 0.2), from_start=False, profile=profile)
                    source, info = cut, ops.probe(cut)
                if info.duration < seconds - settings.clip_duration_tolerance:
                    if kind == "final":
                        raise ClipTooShortError(str(source), info.duration, seconds)
                    hold = True
                    auto_hold.append(key)
                entries.append({"shot_id": key, "scene_id": "promo", "clip": str(source), "trim_seconds": seconds,
                                "audio_tracks": [], "subtitles": [], "hold_last_frame": hold})
            else:
                keyframe = row["keyframe"]
                image = video.local_file(assets[str(keyframe["result_asset_id"])]) if keyframe else None
                token = (file_hash(image)[:16] if image else "card")
                still = work / "stills" / f"{token}-{seconds:g}.mp4"
                if not still.exists():
                    still_clip(image, still, seconds, profile)
                entries.append({"shot_id": key, "scene_id": "promo", "clip": str(still), "trim_seconds": None,
                                "audio_tracks": [], "subtitles": []})
                stills.append(key)
            length = seconds
        timeline.append({"entry": entries[-1], "start": clock, "length": length})
        clock += length
    # Narration: a subtitle on the picture it plays over, its audio placed on the finished timeline.
    narration_tracks, shown = [], []
    for narration in narrations:
        target = narration["target"]
        spoken = float(narration["item"]["seconds"] or 2.0)
        target["entry"]["subtitles"].append({"start": 0.0, "end": round(min(spoken, target["length"]), 2),
                                             "text": narration["item"]["text"]})
        asset = _audio_asset(db, "voice_line", "promo_item", narration["item"]["id"])
        if asset is not None:
            narration_tracks.append({"path": str(video.local_file(asset)), "start_seconds": round(target["start"] + 0.2, 2),
                                     "gain": NARRATION_GAIN, "role": "dialogue"})
            shown.append(str(narration["item"]["id"]))
    name = _slug(promo["title"])
    result = assemble_episode(entries, work, profile=profile, subtitle_mode="soft" if kind == "final" else "burn",
                              episode_name=name)
    final_path = result.episode.path
    music = _audio_asset(db, "music", "promo", promo_id)
    tracks = list(narration_tracks)
    if music is not None:
        tracks.append({"path": str(video.local_file(music)), "start_seconds": 0.0, "gain": MUSIC_GAIN, "role": "music"})
    if tracks:
        digest = file_hash(final_path)[:12] + "-" + file_hash_text(json.dumps(tracks, sort_keys=True))[:10]
        mixed = work / "mixed" / f"{name}-{digest}.mp4"
        if not mixed.exists():
            ops.mix_audio(final_path, tracks, mixed, profile=profile)
        final_path = str(mixed)
    if kind == "final":
        target = Path(final_path).with_name(Path(final_path).stem + f"-{settings.final_export_height}p.mp4")
        if not target.exists():
            ops.upscale(final_path, target, target_height=settings.final_export_height, profile=profile)
        final_path = str(target)
    series_id = promo["series_id"]
    asset_id, _reused = episode_renders._store_file(  # noqa: SLF001
        db, final_path, series_id, reuse={}, key=None, filename=f"{name}-{kind}.mp4", kind=kind, provider="promo_render")
    info = ops.probe(final_path)
    details = {"profile": {"width": info.width, "height": info.height, "fps": profile.fps},
               "items": len(items), "stills": stills, "auto_hold": auto_hold, "narration_mixed": shown, "music": music is not None,
               "title_cards_without_text": cards_without_text,
               "rebuilt_shots": result.rebuilt_shots, "rebuilt_scenes": result.rebuilt_scenes}
    db.execute(text("""UPDATE promo_renders SET status = 'succeeded', asset_id = :a, duration_seconds = :d,
                       details = CAST(:details AS jsonb), completed_at = now() WHERE id = :r"""),
               {"a": asset_id, "d": round(info.duration, 2), "details": json.dumps(details, default=str), "r": str(render["id"])})
    return {"render_id": str(render["id"]), "kind": kind, "asset_id": asset_id, "duration": round(info.duration, 2),
            "target_seconds": float(promo["target_duration_seconds"])}


def file_hash_text(value: str) -> str:
    import hashlib
    return hashlib.sha1(value.encode("utf-8")).hexdigest()
