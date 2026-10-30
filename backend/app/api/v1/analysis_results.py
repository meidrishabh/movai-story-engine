import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.analysis_results import AnalysisResultCreate


router = APIRouter(prefix="/api/v1", tags=["analysis"])


@router.post("/internal/seasons/{season_id}/analysis-result")
def commit_analysis_result(
    season_id: UUID,
    payload: AnalysisResultCreate,
    db: Session = Depends(get_db),
):
    series_id = db.execute(
        text(
            """SELECT s.id FROM seasons se JOIN series s ON s.id = se.series_id
               JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
               WHERE se.id = :season_id AND u.email = :email"""
        ),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    ).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Season was not found")

    character_count = costume_count = object_count = 0
    for extracted in payload.characters:
        source_ids = "{" + ",".join(str(item) for item in extracted.source_unit_ids) + "}"
        character_id = db.execute(
            text(
                """INSERT INTO characters (
                       series_id, name, role, personality, story_role, origin,
                       source_unit_ids, extraction_confidence, analysis_status)
                   VALUES (:series_id, :name, :role, :personality, :story_role,
                           'extracted', CAST(:source_unit_ids AS uuid[]),
                           :extraction_confidence, 'extracted')
                   ON CONFLICT (series_id, name, disambiguation) DO UPDATE SET
                       role = EXCLUDED.role, personality = EXCLUDED.personality,
                       story_role = EXCLUDED.story_role,
                       source_unit_ids = EXCLUDED.source_unit_ids,
                       extraction_confidence = EXCLUDED.extraction_confidence,
                       analysis_status = 'extracted', updated_at = now()
                   RETURNING id"""
            ),
            {
                "series_id": str(series_id), "name": extracted.name,
                "role": extracted.role, "personality": extracted.personality,
                "story_role": extracted.story_role, "source_unit_ids": source_ids,
                "extraction_confidence": extracted.extraction_confidence,
            },
        ).scalar_one()
        character_count += 1
        for costume in extracted.costumes:
            costume_ids = "{" + ",".join(str(item) for item in costume.source_unit_ids) + "}"
            db.execute(
                text(
                    """INSERT INTO costumes (
                           character_id, name, description, color_palette,
                           accessories, state_notes, source_unit_ids)
                       VALUES (:character_id, :name, :description,
                               CAST(:color_palette AS jsonb), CAST(:accessories AS jsonb),
                               :state_notes, CAST(:source_unit_ids AS uuid[]))"""
                ),
                {
                    "character_id": str(character_id), "name": costume.name,
                    "description": costume.description,
                    "color_palette": json.dumps(costume.color_palette),
                    "accessories": json.dumps(costume.accessories),
                    "state_notes": costume.state_notes, "source_unit_ids": costume_ids,
                },
            )
            costume_count += 1

    for extracted in payload.continuity_objects:
        source_ids = "{" + ",".join(str(item) for item in extracted.source_unit_ids) + "}"
        db.execute(
            text(
                """INSERT INTO continuity_objects (
                       series_id, object_type, name, description,
                       distinctive_features, state_notes, source_unit_ids)
                   VALUES (:series_id, :object_type, :name, :description,
                           :distinctive_features, :state_notes,
                           CAST(:source_unit_ids AS uuid[]))
                   ON CONFLICT (series_id, object_type, name, disambiguation) DO UPDATE SET
                       description = EXCLUDED.description,
                       distinctive_features = EXCLUDED.distinctive_features,
                       state_notes = EXCLUDED.state_notes,
                       source_unit_ids = EXCLUDED.source_unit_ids"""
            ),
            {
                "series_id": str(series_id), "object_type": extracted.object_type,
                "name": extracted.name, "description": extracted.description,
                "distinctive_features": extracted.distinctive_features,
                "state_notes": extracted.state_notes, "source_unit_ids": source_ids,
            },
        )
        object_count += 1

    db.execute(text("UPDATE seasons SET story_status = 'analysis_complete' WHERE id = :season_id"), {"season_id": str(season_id)})
    db.commit()
    return {
        "season_id": str(season_id),
        "characters_created_or_updated": character_count,
        "costumes_created": costume_count,
        "continuity_objects_created_or_updated": object_count,
    }
