"""Teasers and trailers: create, plan with the LLM, edit the shot list, make what is missing, render and download."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.services import promo_render_service as renders
from app.services import promo_service as promos
from app.services.asset_store import get_asset, get_storage

router = APIRouter(prefix="/api/v1", tags=["promos"])


class PromoCreate(BaseModel):
    kind: Literal["teaser", "trailer"]
    title: str | None = None
    target_duration_seconds: float | None = Field(default=None, ge=3, le=600, description="Default 20 s (teaser) or 60 s (trailer)")
    notes: str | None = None
    plan: bool = Field(default=False, description="Also ask the LLM for the shot list right away")


class PromoUpdate(BaseModel):
    title: str | None = None
    target_duration_seconds: float | None = Field(default=None, ge=3, le=600)
    notes: str | None = None
    hook: str | None = None
    music_mood: str | None = None


class ItemCreate(BaseModel):
    type: Literal["shot", "title_card", "narration"]
    shot_id: UUID | None = None
    trim_seconds: float | None = Field(default=None, gt=0, le=60)
    start_offset: float = Field(default=0.0, ge=0)
    seconds: float | None = Field(default=None, gt=0, le=30)
    text: str | None = None
    subtitle: str | None = None
    position: int | None = Field(default=None, ge=1, description="1-based; default is the end")


class ItemUpdate(BaseModel):
    trim_seconds: float | None = Field(default=None, gt=0, le=60)
    start_offset: float | None = Field(default=None, ge=0)
    seconds: float | None = Field(default=None, gt=0, le=30)
    text: str | None = None
    subtitle: str | None = None


class Reorder(BaseModel):
    item_ids: list[UUID]


class RenderCreate(BaseModel):
    kind: Literal["animatic", "draft", "final"]


def _promo(db: Session, promo_id: UUID) -> dict:
    row = db.execute(text("SELECT id, series_id FROM promos WHERE id = :p"), {"p": str(promo_id)}).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Promo was not found")
    _series_owned(db, row["series_id"])
    return dict(row)


@router.get("/series/{series_id}/promos")
def list_promos(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    items = promos.list_promos(db, series_id)
    return {"count": len(items), "items": items}


@router.post("/series/{series_id}/promos", status_code=201)
def create_promo(series_id: UUID, payload: PromoCreate, db: Session = Depends(get_db)):
    """Create a teaser (about 20 s) or trailer (about 60 s). With `plan: true` the LLM proposes the shot list straight away."""
    _series_owned(db, series_id)
    try:
        promo = promos.create_promo(db, series_id, payload.kind, payload.title, payload.target_duration_seconds, payload.notes)
        if payload.plan:
            promo = promos.plan_promo(db, UUID(promo["id"]))
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return promo


@router.get("/promos/{promo_id}")
def get_promo(promo_id: UUID, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    promo = promos.get_promo(db, promo_id)
    promo["renders"] = renders.latest_renders(db, promo_id)
    return promo


@router.put("/promos/{promo_id}")
def update_promo(promo_id: UUID, payload: PromoUpdate, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        result = promos.update_promo(db, promo_id, {k: getattr(payload, k) for k in payload.model_fields_set})
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return result


@router.delete("/promos/{promo_id}", status_code=204)
def delete_promo(promo_id: UUID, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    promos.delete_promo(db, promo_id)
    db.commit()


@router.post("/promos/{promo_id}/plan")
def plan_promo(promo_id: UUID, db: Session = Depends(get_db)):
    """Ask the LLM to pick and order the shots, title cards, narration and music mood; replaces the current list."""
    _promo(db, promo_id)
    try:
        result = promos.plan_promo(db, promo_id)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/promos/{promo_id}/items", status_code=201)
def add_item(promo_id: UUID, payload: ItemCreate, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        result = promos.add_item(db, promo_id, payload.type, shot_id=payload.shot_id, trim_seconds=payload.trim_seconds,
                                 start_offset=payload.start_offset, seconds=payload.seconds, text_value=payload.text,
                                 subtitle=payload.subtitle, position=payload.position)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return result


@router.put("/promos/{promo_id}/items/{item_id}")
def update_item(promo_id: UUID, item_id: UUID, payload: ItemUpdate, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        result = promos.update_item(db, promo_id, item_id, {k: getattr(payload, k) for k in payload.model_fields_set})
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return result


@router.delete("/promos/{promo_id}/items/{item_id}", status_code=204)
def delete_item(promo_id: UUID, item_id: UUID, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        promos.delete_item(db, promo_id, item_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()


@router.post("/promos/{promo_id}/reorder")
def reorder_items(promo_id: UUID, payload: Reorder, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        result = promos.reorder_items(db, promo_id, payload.item_ids)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return result


@router.post("/promos/{promo_id}/generate-missing")
def generate_missing(promo_id: UUID, db: Session = Depends(get_db)):
    """Request the keyframes, clips, narration voice lines and music the promo lacks. Anything that already exists is reused.
    Call again after approving keyframes to request their clips."""
    _promo(db, promo_id)
    return promos.generate_missing(db, promo_id)


@router.post("/promos/{promo_id}/renders", status_code=202)
def create_render(promo_id: UUID, payload: RenderCreate, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    try:
        result = renders.create_render(db, promo_id, payload.kind)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.get("/promos/{promo_id}/renders")
def list_renders(promo_id: UUID, db: Session = Depends(get_db)):
    _promo(db, promo_id)
    items = renders.list_renders(db, promo_id)
    return {"count": len(items), "items": items}


def _render(db: Session, render_id: UUID) -> dict:
    render = renders.get_render(db, render_id)
    if render is None:
        raise HTTPException(status_code=404, detail="Render was not found")
    _series_owned(db, UUID(render["series_id"]))
    return render


@router.get("/promo-renders/{render_id}")
def get_render(render_id: UUID, db: Session = Depends(get_db)):
    return _render(db, render_id)


@router.get("/promo-renders/{render_id}/download")
def download_render(render_id: UUID, db: Session = Depends(get_db)):
    render = _render(db, render_id)
    asset = get_asset(db, render["asset_id"]) if render["asset_id"] else None
    if asset is None:
        raise HTTPException(status_code=404, detail="This render has no file yet")
    path = get_storage().local_path(asset["storage_key"])
    if path is None:
        raise HTTPException(status_code=404, detail="The file is missing from storage")
    return FileResponse(path, media_type=asset["mime_type"], filename=asset["original_filename"] or f"{render_id}.mp4")
