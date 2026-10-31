"""Generation requests and the files they produce."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.services import generation_service as generation
from app.services.asset_store import asset_summary, delete_asset, get_asset, get_storage, save_asset

router = APIRouter(prefix="/api/v1", tags=["generation"])

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
Kind = Literal["style_anchor", "character_image", "place_image", "object_image", "keyframe", "video_clip", "voice_line",
               "music", "sfx", "other"]


class RequestCreate(BaseModel):
    kind: Kind
    prompt: str = Field(min_length=1)
    media_type: Literal["image", "video", "voice", "music"] | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    negative_prompt: str | None = None
    params: dict = Field(default_factory=dict)
    reference_asset_ids: list[UUID] = Field(default_factory=list)
    depends_on: list[UUID] = Field(default_factory=list)


class Review(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None


def _request_series(db: Session, request_id: UUID) -> UUID:
    series_id = db.execute(text("SELECT series_id FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Request was not found")
    _series_owned(db, series_id)
    return series_id


def _asset_series(db: Session, asset_id: UUID) -> dict:
    asset = get_asset(db, asset_id)
    if asset is None or asset["series_id"] is None:
        raise HTTPException(status_code=404, detail="Asset was not found")
    _series_owned(db, asset["series_id"])
    return asset


@router.post("/series/{series_id}/generation-requests", status_code=201)
def create_generation_request(series_id: UUID, payload: RequestCreate, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        created = generation.create_request(
            db, series_id, payload.kind, payload.prompt, media_type=payload.media_type, target_type=payload.target_type,
            target_id=payload.target_id, negative_prompt=payload.negative_prompt, params=payload.params,
            reference_asset_ids=payload.reference_asset_ids, depends_on=payload.depends_on)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return created


@router.get("/series/{series_id}/generation-requests")
def list_generation_requests(series_id: UUID, kind: Kind | None = None, status: str | None = None,
                             review_status: Literal["pending", "approved", "rejected"] | None = None,
                             target_id: UUID | None = None, limit: int = 200, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    items = generation.list_requests(db, series_id, kind=kind, status=status, target_id=target_id,
                                     review_status=review_status, limit=min(max(limit, 1), 1000))
    return {"count": len(items), "items": items}


@router.get("/generation-requests/{request_id}")
def get_generation_request(request_id: UUID, db: Session = Depends(get_db)):
    _request_series(db, request_id)
    return generation.get_request(db, request_id)


@router.post("/generation-requests/{request_id}/review")
def review_generation_request(request_id: UUID, payload: Review, db: Session = Depends(get_db)):
    """Approve a finished result, or reject it with a note: a new attempt is queued with the note added to the prompt."""
    _request_series(db, request_id)
    try:
        result = generation.review_request(db, request_id, payload.decision, payload.note)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/generation-requests/{request_id}/retry")
def retry_generation_request(request_id: UUID, db: Session = Depends(get_db)):
    _request_series(db, request_id)
    try:
        result = generation.retry_request(db, request_id)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/generation-requests/{request_id}/result")
async def attach_generation_result(request_id: UUID, file: UploadFile = File(...), provider: str = Form("manual"),
                                   width: int | None = Form(None), height: int | None = Form(None),
                                   duration_seconds: float | None = Form(None), db: Session = Depends(get_db)):
    """Supply the result of a request by hand: for a provider that waits for a person, or to replace a failed one."""
    _request_series(db, request_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")
    try:
        result = generation.attach_result(db, request_id, data, file.content_type or "application/octet-stream",
                                          provider=provider, filename=file.filename, width=width, height=height,
                                          duration_seconds=duration_seconds)
    except ValueError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    db.commit()
    return result


@router.post("/series/{series_id}/assets", status_code=201)
async def upload_asset(series_id: UUID, file: UploadFile = File(...), width: int | None = Form(None),
                       height: int | None = Form(None), duration_seconds: float | None = Form(None),
                       db: Session = Depends(get_db)):
    """Store a file for the series (a reference image, a recorded voice, ...)."""
    _series_owned(db, series_id)
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File is too large")
    asset = save_asset(db, data, file.content_type or "application/octet-stream", series_id=series_id,
                       provider="upload", filename=file.filename, width=width, height=height,
                       duration_seconds=duration_seconds)
    db.commit()
    return asset_summary(asset)


@router.get("/assets/{asset_id}")
def get_asset_info(asset_id: UUID, db: Session = Depends(get_db)):
    return asset_summary(_asset_series(db, asset_id))


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: UUID, db: Session = Depends(get_db)):
    """The file itself. Served from disk so video and audio can seek."""
    asset = _asset_series(db, asset_id)
    storage = get_storage()
    headers = {"Cache-Control": "private, max-age=3600"}
    path = storage.local_path(asset["storage_key"])
    if path is not None:
        return FileResponse(path, media_type=asset["mime_type"], headers=headers)
    if not storage.exists(asset["storage_key"]):
        raise HTTPException(status_code=404, detail="The file is missing from storage")
    return Response(storage.read(asset["storage_key"]), media_type=asset["mime_type"], headers=headers)


@router.delete("/assets/{asset_id}", status_code=204)
def delete_asset_file(asset_id: UUID, db: Session = Depends(get_db)):
    _asset_series(db, asset_id)
    delete_asset(db, asset_id)
    db.commit()
    return Response(status_code=204)
