"""Reference images: style anchors, character / costume / place / object pictures, and the consistency check."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.services import consistency_check
from app.services import generation_service as generation
from app.services import reference_service as references

router = APIRouter(prefix="/api/v1", tags=["references"])


class AnchorRequest(BaseModel):
    count: int = Field(default=4, ge=1, le=4)


class TargetRequest(BaseModel):
    target_type: Literal["character_version", "costume", "entity_look"]
    target_id: UUID
    views: list[str] | None = None
    force: bool = False  # true: make a fresh attempt even when the view already has one


def _conflict(db: Session, error: Exception, status: int = 409) -> HTTPException:
    db.rollback()
    return HTTPException(status_code=status, detail=str(error))


@router.get("/series/{series_id}/references")
def reference_overview(series_id: UUID, db: Session = Depends(get_db)):
    """The gallery: style anchors, then every character (with costumes), place and object and each of its views."""
    _series_owned(db, series_id)
    return references.get_overview(db, series_id)


@router.get("/series/{series_id}/references/flagged")
def flagged_references(series_id: UUID, db: Session = Depends(get_db)):
    """Finished images the consistency check marked as drifting, waiting for the user's verdict."""
    _series_owned(db, series_id)
    items = references.list_flagged(db, series_id)
    return {"count": len(items), "items": items}


@router.post("/series/{series_id}/references/style-anchors/generate", status_code=201)
def generate_style_anchors(series_id: UUID, payload: AnchorRequest | None = None, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        created = references.generate_style_anchors(db, series_id, (payload or AnchorRequest()).count)
    except ValueError as error:
        raise _conflict(db, error) from error
    db.commit()
    return {"count": len(created), "items": created}


@router.post("/series/{series_id}/references/style-anchors/{request_id}/pick")
def pick_style_anchor(series_id: UUID, request_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        result = references.pick_style_anchor(db, series_id, request_id)
    except LookupError as error:
        raise _conflict(db, error, 404) from error
    except ValueError as error:
        raise _conflict(db, error) from error
    db.commit()
    return result


@router.post("/series/{series_id}/references/generate", status_code=201)
def generate_reference(series_id: UUID, payload: TargetRequest, db: Session = Depends(get_db)):
    """Request the pictures of one character, costume, place or object (`force` makes a fresh attempt)."""
    _series_owned(db, series_id)
    try:
        made = references.generate_target(db, series_id, payload.target_type, payload.target_id,
                                          views=payload.views, force=payload.force)
    except LookupError as error:
        raise _conflict(db, error, 404) from error
    except ValueError as error:
        raise _conflict(db, error) from error
    db.commit()
    return {"count": len(made), "items": made}


@router.post("/series/{series_id}/references/generate-all", status_code=201)
def generate_all_references(series_id: UUID, db: Session = Depends(get_db)):
    """Request every missing picture for the whole series. Needs an approved style bible and style anchor."""
    _series_owned(db, series_id)
    try:
        counts = references.generate_all(db, series_id)
    except ValueError as error:
        raise _conflict(db, error) from error
    db.commit()
    return counts


@router.post("/generation-requests/{request_id}/consistency-check")
def run_consistency_check(request_id: UUID, db: Session = Depends(get_db)):
    """Run the consistency check again, for example after approving more references."""
    series_id = db.execute(text("SELECT series_id FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Request was not found")
    _series_owned(db, series_id)
    if db.execute(text("SELECT kind FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).scalar() == "keyframe":
        result = consistency_check.run_check(db, request_id)  # keyframes keep their verdict in `checks`
        db.commit()
        return {**result, "request": generation.get_request(db, request_id)}
    result = references.check_drift(db, request_id)
    if result is None:
        raise HTTPException(status_code=409, detail="The request has no image to check")
    db.commit()
    return {**result, "request": generation.get_request(db, request_id)}
