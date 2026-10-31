"""Partial generation: choose which reference targets and which scenes to work on."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _episode_series, _series_owned
from app.services import reference_service, scope_service

router = APIRouter(prefix="/api/v1", tags=["scope"])


class ReferenceScopeUpdate(BaseModel):
    limited: bool = Field(description="false = every character, costume, place and object is in scope")
    characters: list[UUID] = []
    costumes: list[UUID] = []
    places: list[UUID] = []
    objects: list[UUID] = []


class SelectForScenes(BaseModel):
    episode_id: UUID
    scene_ids: list[UUID] | None = Field(default=None, description="Default: the episode's saved working scenes, else all")
    keep_existing: bool = Field(default=False, description="Add to the current selection instead of replacing it")


class WorkingScenes(BaseModel):
    scene_ids: list[UUID] = Field(default=[], description="Empty = every scene")
    first_scene: int | None = Field(default=None, description="Alternative: a scene-number range (inclusive)")
    last_scene: int | None = None


class PrepareScenes(BaseModel):
    scene_ids: list[UUID] | None = None
    first_scene: int | None = None
    last_scene: int | None = None
    limit_references: bool = Field(default=True, description="Limit the reference scope to what these scenes need")
    keep_existing_references: bool = True
    request_references: bool = Field(default=False, description="Also queue the reference images that are missing")


@router.get("/series/{series_id}/reference-scope")
def get_reference_scope(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    return scope_service.get_reference_scope(db, series_id)


@router.put("/series/{series_id}/reference-scope")
def put_reference_scope(series_id: UUID, payload: ReferenceScopeUpdate, db: Session = Depends(get_db)):
    """Choose the characters, costumes, places and objects to make reference images for. `limited: false` clears it."""
    _series_owned(db, series_id)
    result = scope_service.set_reference_scope(db, series_id, limited=payload.limited, characters=payload.characters,
                                               costumes=payload.costumes, places=payload.places, objects=payload.objects)
    db.commit()
    return result


@router.post("/series/{series_id}/reference-scope/select-for-scenes")
def select_for_scenes(series_id: UUID, payload: SelectForScenes, db: Session = Depends(get_db)):
    """Limit the reference scope to the characters, places and objects that appear in the chosen scenes."""
    _series_owned(db, series_id)
    if _episode_series(db, payload.episode_id) != series_id:
        raise HTTPException(status_code=404, detail="Episode is not in this series")
    scene_ids = scope_service.resolve_scenes(db, payload.episode_id, payload.scene_ids)
    needed = scope_service.needed_for_scenes(db, payload.episode_id, scene_ids)
    result = scope_service.select_needed_for_scenes(db, series_id, payload.episode_id, scene_ids,
                                                    keep_existing=payload.keep_existing)
    db.commit()
    return {"scope": result, "needed": needed}


@router.get("/episodes/{episode_id}/working-scenes")
def get_working_scenes(episode_id: UUID, db: Session = Depends(get_db)):
    _episode_series(db, episode_id)
    return scope_service.episode_scenes(db, episode_id)


@router.put("/episodes/{episode_id}/working-scenes")
def put_working_scenes(episode_id: UUID, payload: WorkingScenes, db: Session = Depends(get_db)):
    """Remember which scenes this episode's pages and generate buttons work on. Empty list = every scene."""
    _episode_series(db, episode_id)
    ids = [str(s) for s in payload.scene_ids]
    if not ids and (payload.first_scene is not None or payload.last_scene is not None):
        ids = scope_service.scenes_by_number(db, episode_id, payload.first_scene, payload.last_scene)
    try:
        scope_service.set_working_scenes(db, episode_id, ids)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return scope_service.episode_scenes(db, episode_id)


@router.get("/episodes/{episode_id}/needed-references")
def needed_references(episode_id: UUID, scene_ids: list[UUID] | None = Query(default=None), db: Session = Depends(get_db)):
    """The characters, places and objects that appear in the chosen scenes (default: the working scenes)."""
    _episode_series(db, episode_id)
    return scope_service.needed_for_scenes(db, episode_id, scope_service.resolve_scenes(db, episode_id, scene_ids))


@router.get("/episodes/{episode_id}/scope-checklist")
def scope_checklist(episode_id: UUID, scene_ids: list[UUID] | None = Query(default=None), db: Session = Depends(get_db)):
    """What each stage still lacks for the chosen scenes: references, keyframes, clips and sound."""
    series_id = _episode_series(db, episode_id)
    return scope_service.reference_checklist(db, series_id, episode_id, scene_ids)


@router.post("/episodes/{episode_id}/scope/prepare")
def prepare_scenes(episode_id: UUID, payload: PrepareScenes, db: Session = Depends(get_db)):
    """'Generate for selected scenes': save the scenes as the working scenes, limit the reference scope to what they
    need, optionally queue the missing reference images, and return the checklist of what is missing at each stage."""
    series_id = _episode_series(db, episode_id)
    ids = [str(s) for s in payload.scene_ids or []]
    if not ids and (payload.first_scene is not None or payload.last_scene is not None):
        ids = scope_service.scenes_by_number(db, episode_id, payload.first_scene, payload.last_scene)
    try:
        scope_service.set_working_scenes(db, episode_id, ids)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    chosen = scope_service.get_working_scenes(db, episode_id)
    needed = scope_service.needed_for_scenes(db, episode_id, chosen)
    if payload.limit_references:
        scope_service.select_needed_for_scenes(db, series_id, episode_id, chosen, keep_existing=payload.keep_existing_references)
    requested = None
    if payload.request_references:
        try:
            requested = reference_service.generate_all(db, series_id)
        except ValueError as error:  # no approved style bible or style anchor yet: the checklist says so
            requested = {"error": str(error)}
    db.commit()
    return {"working": scope_service.episode_scenes(db, episode_id), "needed": needed,
            "reference_scope": scope_service.get_reference_scope(db, series_id), "references_requested": requested,
            "checklist": scope_service.reference_checklist(db, series_id, episode_id, chosen)}
