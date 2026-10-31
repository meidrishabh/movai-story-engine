"""The series style bible: one look for every image and clip."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMProviderError
from app.services import style_bible_service as styles

router = APIRouter(prefix="/api/v1", tags=["style"])


class Override(BaseModel):
    when: str | None = None
    change: str | None = None


class StyleUpdate(BaseModel):
    theme_tone: str | None = None
    medium: str | None = None
    art_style: str | None = None
    palette: str | None = None
    lighting: str | None = None
    camera_language: str | None = None
    negative_style: str | None = None
    per_act_overrides: list[Override] | None = None


class GenerateStyle(BaseModel):
    replace: bool = Field(default=False, description="Allow superseding an approved style bible")


def _shown(bible: dict | None) -> dict:
    return {"bible": bible, "approved": bool(bible and bible["status"] == "approved"),
            "style_block": styles.style_block(bible) if bible else None}


@router.get("/series/{series_id}/style-bible")
def get_style_bible(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    return _shown(styles.get_live(db, series_id))


@router.post("/series/{series_id}/style-bible/generate")
def generate_style_bible(series_id: UUID, payload: GenerateStyle | None = None, db: Session = Depends(get_db)):
    """Draft a style bible from the story (one LLM call). An approved bible is only replaced with `replace: true`."""
    _series_owned(db, series_id)
    if styles.get_approved(db, series_id) and not (payload and payload.replace):
        raise HTTPException(status_code=409, detail="The style is already approved; generating a new one replaces it")
    try:
        bible = styles.generate_draft(db, series_id)
    except PermanentJobError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LLMProviderError as error:
        db.rollback()
        raise HTTPException(status_code=502, detail=f"The model could not write the style: {error}") from error
    db.commit()
    return _shown(bible)


@router.put("/series/{series_id}/style-bible")
def update_style_bible(series_id: UUID, payload: StyleUpdate, db: Session = Depends(get_db)):
    """Edit the style. An approved style goes back to draft until it is approved again."""
    _series_owned(db, series_id)
    try:
        bible = styles.update_live(db, series_id, payload.model_dump(exclude_unset=True))
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    db.commit()
    return _shown(bible)


@router.post("/series/{series_id}/style-bible/approve")
def approve_style_bible(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    try:
        bible = styles.approve(db, series_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    db.commit()
    return _shown(bible)
