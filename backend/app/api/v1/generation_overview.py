"""Spend, budgets and the series-wide pause switch for the generation stages."""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.services import generation_overview as overview

router = APIRouter(prefix="/api/v1", tags=["generation"])


@router.get("/series/{series_id}/generation/overview")
def generation_overview(series_id: UUID, db: Session = Depends(get_db)):
    """Spend so far, request counts, providers in use and each episode's budget and pause state."""
    _series_owned(db, series_id)
    return overview.overview(db, series_id)


@router.post("/series/{series_id}/generation/pause")
def pause_generation(series_id: UUID, db: Session = Depends(get_db)):
    """Hold every queued generation request for the series. Requests already running finish."""
    _series_owned(db, series_id)
    result = overview.set_series_pause(db, series_id, True)
    db.commit()
    return result


@router.post("/series/{series_id}/generation/resume")
def resume_generation(series_id: UUID, db: Session = Depends(get_db)):
    """Lift the series pause and queue the requests it held."""
    _series_owned(db, series_id)
    result = overview.set_series_pause(db, series_id, False)
    db.commit()
    return result
