from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.repositories.analysis_repository import get_analysis_run_for_owner


router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.get("/analysis-runs/{run_id}")
def get_analysis_run(run_id: UUID, db: Session = Depends(get_db)):
    run = get_analysis_run_for_owner(db, run_id, DEV_USER_EMAIL)
    if run is None:
        raise HTTPException(status_code=404, detail="Analysis run was not found")
    return dict(run)
