"""Sound: voice casting, the per-episode sound board, timing fit, subtitles and the audio plan."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _episode_series, _series_owned
from app.services.scope_service import resolve_scenes
from app.services import sound_service as sound
from app.services import voice_cast_service as casting

router = APIRouter(prefix="/api/v1", tags=["sound"])


class VoiceUpdate(BaseModel):
    voice: str | None = None
    language: str | None = Field(default=None, max_length=16)
    style: str | None = None
    speed: float | None = Field(default=None, gt=0.25, le=3.0)
    consent_given: bool | None = None
    consent_note: str | None = None


class VoicePreview(BaseModel):
    text: str | None = Field(default=None, max_length=300)


class GenerateSound(BaseModel):
    redesign: bool = False
    scene_ids: list[UUID] | None = None  # default: the episode's saved working scenes, else every scene


class SoundReview(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


class ApplyFit(BaseModel):
    shot_ids: list[UUID] | None = None


def _character_id(value: str) -> UUID | None:
    """The path segment is a character id, or the word 'narrator'."""
    if value == casting.NARRATOR:
        return None
    try:
        return UUID(value)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="Use a character id or 'narrator'") from error


# ----- voice casting ---------------------------------------------------------------------------------------------

@router.get("/series/{series_id}/voice-casts")
def list_voice_casts(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    return casting.list_cast(db, series_id)


@router.put("/series/{series_id}/voice-casts/{character}")
def set_voice_cast(series_id: UUID, character: str, payload: VoiceUpdate, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        casting.set_voice(db, series_id, _character_id(character), payload.model_dump(exclude_unset=True))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()
    return casting.list_cast(db, series_id)


@router.post("/series/{series_id}/voice-casts/{character}/preview", status_code=202)
def preview_voice_cast(series_id: UUID, character: str, payload: VoicePreview | None = None, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        request = casting.preview_voice(db, series_id, _character_id(character), payload.text if payload else None)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()
    return request


# ----- the sound board -------------------------------------------------------------------------------------------

@router.post("/episodes/{episode_id}/sound/generate", status_code=202)
def generate_episode_sound(episode_id: UUID, payload: GenerateSound | None = None, db: Session = Depends(get_db)):
    """Queue the job that designs the cues and makes every sound. Needs the job runner."""
    _episode_series(db, episode_id)
    try:
        job = sound.queue_sound_job(db, episode_id, bool(payload and payload.redesign),
                                    payload.scene_ids if payload else None)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return job


@router.get("/episodes/{episode_id}/sound")
def get_sound_board(episode_id: UUID, db: Session = Depends(get_db)):
    _episode_series(db, episode_id)
    return sound.episode_board(db, episode_id)


@router.post("/sound-cues/{cue_id}/review")
def review_sound_cue(cue_id: UUID, payload: SoundReview, db: Session = Depends(get_db)):
    series_id = db.execute(text("SELECT series_id FROM sound_cues WHERE id = :c"), {"c": str(cue_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Cue was not found")
    _series_owned(db, series_id)
    try:
        result = sound.review_cue(db, cue_id, payload.decision, payload.note)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/episodes/{episode_id}/sound/approve-all")
def approve_all_sound(episode_id: UUID, db: Session = Depends(get_db)):
    _episode_series(db, episode_id)
    result = sound.approve_all(db, episode_id)
    db.commit()
    return result


@router.post("/episodes/{episode_id}/sound/apply-fit")
def apply_sound_fit(episode_id: UUID, payload: ApplyFit | None = None, db: Session = Depends(get_db)):
    """Lengthen shots whose speech does not fit, to the suggested length. Changes shot durations: user's call."""
    _episode_series(db, episode_id)
    result = sound.apply_fit(db, episode_id, payload.shot_ids if payload else None)
    db.commit()
    return result


# ----- subtitles and the plan ------------------------------------------------------------------------------------

@router.post("/episodes/{episode_id}/subtitles/build")
def build_episode_subtitles(episode_id: UUID, db: Session = Depends(get_db)):
    _episode_series(db, episode_id)
    result = sound.build_subtitles(db, episode_id)  # the saved working scenes, else every scene
    db.commit()
    return result


@router.get("/episodes/{episode_id}/subtitles")
def get_episode_subtitles(episode_id: UUID, db: Session = Depends(get_db)):
    _episode_series(db, episode_id)
    return {"files": sound.subtitle_files(db, episode_id), "srt": sound.episode_srt_text(db, episode_id)}


@router.get("/episodes/{episode_id}/audio-plan")
def get_audio_plan(episode_id: UUID, db: Session = Depends(get_db)):
    """What the video step mixes per shot. File paths are local, so only asset-free fields are echoed here."""
    _episode_series(db, episode_id)
    plan = sound.build_audio_plan(db, episode_id, resolve_scenes(db, episode_id))
    db.commit()
    return {shot_id: {"audio_tracks": [{k: v for k, v in t.items() if k != "path"} for t in item["audio_tracks"]],
                      "subtitles": item["subtitles"]} for shot_id, item in plan.items()}
