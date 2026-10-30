"""Character reference sheets: how each character looks, taken from the story and editable by the user."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.adaptations import _active, _queue
from app.api.v1.entities import _series_owned

router = APIRouter(prefix="/api/v1", tags=["appearance"])


class AppearanceUpdate(BaseModel):
    description: str = Field(min_length=1)
    face_and_body_design: str | None = None
    clothing_and_accessories: str | None = None
    distinctive_features: str | None = None
    color_palette: list[str] = Field(default_factory=list)
    voice: str | None = None


def _series_of_character(db: Session, character_id: UUID) -> UUID:
    series_id = db.execute(text("SELECT series_id FROM characters WHERE id = :c"), {"c": str(character_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Character was not found")
    _series_owned(db, series_id)
    return series_id


@router.get("/series/{series_id}/appearance")
def list_appearance(series_id: UUID, db: Session = Depends(get_db)):
    """The newest usable reference sheet and costumes for every character that has one."""
    _series_owned(db, series_id)
    sheets = db.execute(
        text("""SELECT DISTINCT ON (v.character_id) v.character_id, v.version_number, v.description,
                       v.face_and_body_design, v.clothing_and_accessories, v.distinctive_features, v.color_palette,
                       v.voice_profile ->> 'description' AS voice, v.status, v.change_notes
                FROM character_versions v JOIN characters c ON c.id = v.character_id
                WHERE c.series_id = :s AND v.status IN ('draft', 'approved')
                ORDER BY v.character_id, (v.status = 'approved') DESC, v.version_number DESC"""),
        {"s": str(series_id)}).mappings().all()
    costumes = db.execute(
        text("""SELECT co.id, co.character_id, co.name, co.description, co.color_palette, co.accessories,
                       co.state_notes AS "when", co.approval_status AS status
                FROM costumes co JOIN characters c ON c.id = co.character_id
                WHERE c.series_id = :s AND co.approval_status IN ('draft', 'approved') ORDER BY co.created_at"""),
        {"s": str(series_id)}).mappings().all()
    by_character: dict[str, list] = {}
    for costume in costumes:
        by_character.setdefault(str(costume["character_id"]), []).append(dict(costume))
    return {"items": [{**dict(sheet), "costumes": by_character.get(str(sheet["character_id"]), [])} for sheet in sheets]}


@router.put("/characters/{character_id}/appearance")
def save_appearance(character_id: UUID, payload: AppearanceUpdate, db: Session = Depends(get_db)):
    """Save the user's version of the sheet. It is approved, so re-analysis never overwrites it."""
    _series_of_character(db, character_id)
    version = db.execute(text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM character_versions WHERE character_id = :c"),
                         {"c": str(character_id)}).scalar_one()
    db.execute(text("UPDATE character_versions SET status = 'superseded' WHERE character_id = :c AND status IN ('draft', 'approved')"),
               {"c": str(character_id)})
    db.execute(
        text("""INSERT INTO character_versions (character_id, version_number, description, face_and_body_design,
                    clothing_and_accessories, distinctive_features, color_palette, voice_profile, status, change_notes)
                VALUES (:c, :v, :d, :face, :clothing, :features, CAST(:palette AS jsonb), CAST(:voice AS jsonb),
                        'approved', 'Edited by the user.')"""),
        {"c": str(character_id), "v": version, "d": payload.description, "face": payload.face_and_body_design,
         "clothing": payload.clothing_and_accessories, "features": payload.distinctive_features,
         "palette": json.dumps(payload.color_palette),
         "voice": json.dumps({"description": payload.voice} if payload.voice else {})})
    db.commit()
    return {"character_id": str(character_id), "version_number": version, "status": "approved"}


@router.post("/series/{series_id}/appearance/generate", status_code=202)
def generate_appearance(series_id: UUID, db: Session = Depends(get_db)):
    """Re-read the story for how characters look. Sheets the user approved are kept."""
    _series_owned(db, series_id)
    if _active(db, "adaptation_generation", "series_id", str(series_id)):
        raise HTTPException(status_code=409, detail="A generation job is already queued or running for this series")
    db.execute(  # drop stored replies so the model is asked again; a retry of the job then reuses what it already did
        text("""DELETE FROM analysis_batches WHERE stage_name = 'appearance'
                AND analysis_run_id IN (SELECT id FROM analysis_runs WHERE series_id = :s)"""), {"s": str(series_id)})
    job = _queue(db, "adaptation_generation", {"series_id": str(series_id), "kind": "appearance"})
    db.commit()
    return job
