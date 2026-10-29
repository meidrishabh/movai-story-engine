import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.characters import CharacterCreate, CharacterVersionCreate


router = APIRouter(prefix="/api/v1", tags=["characters"])


@router.get("/series/{series_id}/characters")
def get_series_characters(series_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT c.id, c.series_id, c.name, c.role, c.personality, c.story_role,
                   c.created_at, c.updated_at, COUNT(cv.id) AS version_count
            FROM characters c JOIN series s ON s.id = c.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            LEFT JOIN character_versions cv ON cv.character_id = c.id
            WHERE c.series_id = :series_id AND u.email = :email
            GROUP BY c.id, c.series_id, c.name, c.role, c.personality,
                     c.story_role, c.created_at, c.updated_at
            ORDER BY c.created_at
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/series/{series_id}/characters")
def create_character(
    series_id: UUID,
    payload: CharacterCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Characters are created from approved story analysis, not manually.",
    )


@router.get("/series/{series_id}/continuity")
def get_series_continuity(series_id: UUID, db: Session = Depends(get_db)):
    ownership = db.execute(
        text(
            """
            SELECT s.id FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).scalar()
    if ownership is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    characters = db.execute(
        text(
            """
            SELECT c.id, c.name, c.role, c.personality, c.story_role, c.origin,
                   c.source_unit_ids, c.extraction_confidence, c.analysis_status,
                   COUNT(cv.id) AS version_count
            FROM characters c LEFT JOIN character_versions cv ON cv.character_id = c.id
            WHERE c.series_id = :series_id
            GROUP BY c.id, c.name, c.role, c.personality, c.story_role,
                     c.origin, c.source_unit_ids, c.extraction_confidence,
                     c.analysis_status
            ORDER BY c.name
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()
    objects = db.execute(
        text(
            """SELECT id, object_type, name, description, distinctive_features,
                      state_notes, source_unit_ids, approval_status
               FROM continuity_objects WHERE series_id = :series_id
               ORDER BY object_type, name"""
        ),
        {"series_id": str(series_id)},
    ).mappings().all()
    costumes = db.execute(
        text(
            """SELECT co.id, co.character_id, co.name, co.description,
                      co.color_palette, co.accessories, co.state_notes,
                      co.source_unit_ids, co.approval_status
               FROM costumes co JOIN characters c ON c.id = co.character_id
               WHERE c.series_id = :series_id ORDER BY c.name, co.name"""
        ),
        {"series_id": str(series_id)},
    ).mappings().all()
    return {
        "characters": [dict(row) for row in characters],
        "costumes": [dict(row) for row in costumes],
        "continuity_objects": [dict(row) for row in objects],
    }


@router.get("/characters/{character_id}/versions")
def get_character_versions(character_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT cv.id, cv.character_id, cv.version_number, cv.description,
                   cv.face_and_body_design, cv.clothing_and_accessories,
                   cv.distinctive_features, cv.color_palette, cv.voice_profile,
                   cv.status, cv.change_notes, cv.created_at
            FROM character_versions cv JOIN characters c ON c.id = cv.character_id
            JOIN series s ON s.id = c.series_id JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE cv.character_id = :character_id AND u.email = :email
            ORDER BY cv.version_number DESC
            """
        ),
        {"character_id": str(character_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/characters/{character_id}/versions")
def create_character_version(
    character_id: UUID,
    payload: CharacterVersionCreate,
    db: Session = Depends(get_db),
):
    next_version = db.execute(
        text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM character_versions WHERE character_id = :character_id"),
        {"character_id": str(character_id)},
    ).scalar_one()
    version = db.execute(
        text(
            """
            INSERT INTO character_versions (
                character_id, version_number, description, face_and_body_design,
                clothing_and_accessories, distinctive_features, color_palette,
                voice_profile, status, change_notes
            )
            SELECT c.id, :version_number, :description, :face_and_body_design,
                   :clothing_and_accessories, :distinctive_features,
                   CAST(:color_palette AS jsonb), CAST(:voice_profile AS jsonb),
                   CAST(:status AS approval_status), :change_notes
            FROM characters c JOIN series s ON s.id = c.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            WHERE c.id = :character_id AND u.email = :email
            RETURNING id, character_id, version_number, description,
                      face_and_body_design, clothing_and_accessories,
                      distinctive_features, color_palette, voice_profile, status,
                      change_notes, created_at
            """
        ),
        {
            "character_id": str(character_id), "email": DEV_USER_EMAIL,
            "version_number": next_version, "description": payload.description,
            "face_and_body_design": payload.face_and_body_design,
            "clothing_and_accessories": payload.clothing_and_accessories,
            "distinctive_features": payload.distinctive_features,
            "color_palette": json.dumps(payload.color_palette),
            "voice_profile": json.dumps(payload.voice_profile),
            "status": payload.status, "change_notes": payload.change_notes,
        },
    ).mappings().first()
    if version is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Character was not found")
    db.commit()
    return dict(version)
