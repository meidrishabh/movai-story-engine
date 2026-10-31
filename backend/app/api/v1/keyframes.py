"""Keyframes: one still image per shot. Review goes through the generic generation-request endpoints
(`POST /generation-requests/{id}/review` to approve or reject with a note, `/retry` for a failed one)."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _episode_series, _series_owned
from app.services import keyframe_service
from app.services.prompt_builder import build_video_prompt, load_shot_context
from app.services.style_bible_service import get_approved

router = APIRouter(prefix="/api/v1", tags=["keyframes"])


class GenerateKeyframes(BaseModel):
    shot_ids: list[UUID] | None = Field(default=None, description="Only these shots; default is every shot of the episode")
    regenerate: bool = Field(default=False, description="Make a fresh keyframe even where one exists")


def _shot_series(db: Session, shot_id: UUID) -> UUID:
    series_id = db.execute(
        text("""SELECT e.series_id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id JOIN episodes e ON e.id = sc.episode_id
                WHERE sh.id = :s"""), {"s": str(shot_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Shot was not found")
    _series_owned(db, series_id)
    return series_id


@router.get("/series/{series_id}/keyframes")
def keyframe_overview(series_id: UUID, db: Session = Depends(get_db)):
    """Per episode: how many shots have a keyframe, are waiting for review, approved, working or failed."""
    _series_owned(db, series_id)
    return keyframe_service.series_overview(db, series_id)


@router.get("/episodes/{episode_id}/keyframes")
def episode_keyframes(episode_id: UUID, db: Session = Depends(get_db)):
    """Scene > shot grid with each shot's current keyframe, exact prompt, references, checks and totals."""
    _episode_series(db, episode_id)
    return keyframe_service.episode_grid(db, episode_id)


@router.post("/episodes/{episode_id}/keyframes/generate")
def generate_keyframes(episode_id: UUID, payload: GenerateKeyframes | None = None, db: Session = Depends(get_db)):
    """Queue keyframes for the episode's shots in story order (each request is its own job for the job runner)."""
    _episode_series(db, episode_id)
    payload = payload or GenerateKeyframes()
    try:
        return keyframe_service.generate_for_episode(db, episode_id, shot_ids=payload.shot_ids, regenerate=payload.regenerate)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.post("/shots/{shot_id}/keyframe/regenerate", status_code=201)
def regenerate_keyframe(shot_id: UUID, db: Session = Depends(get_db)):
    """A fresh keyframe for one shot, rebuilt from the current style bible and references; the old one is retired."""
    _shot_series(db, shot_id)
    episode_id = db.execute(text("SELECT sc.episode_id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sh.id = :s"),
                            {"s": str(shot_id)}).scalar()
    try:
        return keyframe_service.generate_for_episode(db, episode_id, shot_ids=[shot_id], regenerate=True)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/shots/{shot_id}/video-prompt")
def shot_video_prompt(shot_id: UUID, db: Session = Depends(get_db)):
    """The short motion prompt for animating this shot's keyframe (what the video stage sends)."""
    series_id = _shot_series(db, shot_id)
    bible = get_approved(db, series_id)
    if bible is None:
        raise HTTPException(status_code=409, detail="Approve the style bible first")
    return build_video_prompt(load_shot_context(db, shot_id), bible)
