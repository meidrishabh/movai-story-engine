"""Video clips, the episode clip board, budget and pause, and episode renders (animatic, draft, final export)."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.services import render_service as renders
from app.services import video_service as video
from app.services.asset_store import get_asset, get_storage

router = APIRouter(prefix="/api/v1", tags=["video"])


class PlanClips(BaseModel):
    limit: int | None = Field(default=None, ge=1, description="Plan at most this many new clips (the first shots in order)")
    scene_id: UUID | None = None
    allow_text_to_video: bool = False
    allow_unapproved_keyframes: bool = False
    hold_last_frame: bool = False


class ClipReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class ClipOptions(BaseModel):
    hold_last_frame: bool


class BudgetUpdate(BaseModel):
    max_retries_per_shot: int | None = Field(default=None, ge=0, le=50)
    max_cost: float | None = Field(default=None, ge=0, description="null removes the cap")
    paused: bool | None = None


class RenderCreate(BaseModel):
    kind: Literal["animatic", "draft", "final"]


def _episode(db: Session, episode_id: UUID) -> dict:
    try:
        episode = video.get_episode(db, episode_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    _series_owned(db, episode["series_id"])
    return episode


def _clip_episode(db: Session, request_id: UUID) -> None:
    series_id = db.execute(text("SELECT series_id FROM generation_requests WHERE id = :r AND kind = 'video_clip'"),
                           {"r": str(request_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Clip request was not found")
    _series_owned(db, series_id)


@router.get("/episodes/{episode_id}/video")
def video_board(episode_id: UUID, db: Session = Depends(get_db)):
    """The clip board: per shot its keyframe and clip, the budget, and the latest animatic, draft and final render."""
    _episode(db, episode_id)
    return video.board(db, episode_id)


@router.post("/episodes/{episode_id}/video/plan", status_code=201)
def plan_video(episode_id: UUID, payload: PlanClips, db: Session = Depends(get_db)):
    """Create a low-res video request for each shot that has none, image-to-video from its approved keyframe."""
    _episode(db, episode_id)
    result = video.plan_clips(db, episode_id, limit=payload.limit, scene_id=payload.scene_id,
                              allow_text_to_video=payload.allow_text_to_video,
                              allow_unapproved_keyframes=payload.allow_unapproved_keyframes,
                              hold_last_frame=payload.hold_last_frame)
    db.commit()
    return result


@router.post("/video-clips/{request_id}/review")
def review_clip(request_id: UUID, payload: ClipReview, db: Session = Depends(get_db)):
    """Approve a clip, or reject it with a note to regenerate. 409 when the clip is too short, or the retries are used up."""
    _clip_episode(db, request_id)
    try:
        result = video.review_clip(db, request_id, payload.decision, payload.note)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/video-clips/{request_id}/options")
def clip_options(request_id: UUID, payload: ClipOptions, db: Session = Depends(get_db)):
    """Choose to hold the last frame of a clip that is shorter than its shot (instead of regenerating it)."""
    _clip_episode(db, request_id)
    result = video.set_clip_options(db, request_id, payload.hold_last_frame)
    db.commit()
    return result


@router.get("/episodes/{episode_id}/video/budget")
def get_budget(episode_id: UUID, db: Session = Depends(get_db)):
    _episode(db, episode_id)
    return video.get_budget(db, episode_id)


@router.put("/episodes/{episode_id}/video/budget")
def update_budget(episode_id: UUID, payload: BudgetUpdate, db: Session = Depends(get_db)):
    """Only the fields sent are changed; `max_cost: null` removes the cap. Un-pausing releases held requests."""
    _episode(db, episode_id)
    changes = {name: getattr(payload, name) for name in payload.model_fields_set}
    result = video.set_budget(db, episode_id, changes)
    db.commit()
    return result


@router.post("/episodes/{episode_id}/video/pause")
def pause_video(episode_id: UUID, db: Session = Depends(get_db)):
    _episode(db, episode_id)
    result = video.set_budget(db, episode_id, {"paused": True})
    db.commit()
    return result


@router.post("/episodes/{episode_id}/video/resume")
def resume_video(episode_id: UUID, db: Session = Depends(get_db)):
    _episode(db, episode_id)
    result = video.set_budget(db, episode_id, {"paused": False})
    db.commit()
    return result


@router.post("/episodes/{episode_id}/renders", status_code=202)
def create_render(episode_id: UUID, payload: RenderCreate, db: Session = Depends(get_db)):
    """Queue an animatic, a draft or the final export. The job runner builds it; poll the render for its status."""
    _episode(db, episode_id)
    try:
        result = renders.create_render(db, episode_id, payload.kind)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.get("/episodes/{episode_id}/renders")
def list_renders(episode_id: UUID, kind: Literal["animatic", "draft", "final"] | None = None, db: Session = Depends(get_db)):
    _episode(db, episode_id)
    items = renders.list_renders(db, episode_id, kind)
    return {"count": len(items), "items": items}


def _render(db: Session, render_id: UUID) -> dict:
    render = renders.get_render(db, render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="Render was not found")
    _series_owned(db, UUID(render["series_id"]))
    return render


@router.get("/episode-renders/{render_id}")
def get_render(render_id: UUID, db: Session = Depends(get_db)):
    return _render(db, render_id)


@router.get("/episode-renders/{render_id}/download")
def download_render(render_id: UUID, db: Session = Depends(get_db)):
    """The rendered file as a download (the plain asset URL plays it in the browser instead)."""
    render = _render(db, render_id)
    asset = get_asset(db, render["asset_id"]) if render["asset_id"] else None
    if asset is None:
        raise HTTPException(status_code=404, detail="This render has no file yet")
    path = get_storage().local_path(asset["storage_key"])
    if path is None:
        raise HTTPException(status_code=404, detail="The file is missing from storage")
    return FileResponse(path, media_type=asset["mime_type"], filename=asset["original_filename"] or f"{render_id}.mp4")
