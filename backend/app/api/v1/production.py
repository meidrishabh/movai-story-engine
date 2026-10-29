import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.production import SceneCreate, StoryboardFrameCreate


router = APIRouter(prefix="/api/v1", tags=["production"])


@router.get("/episodes/{episode_id}/scenes")
def get_episode_scenes(episode_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT sc.id, sc.episode_id, sc.scene_number, sc.title, sc.description,
                   sc.dialogue, sc.continuity_state, sc.environment_notes,
                   sc.created_at, sc.updated_at, COUNT(sf.id) AS storyboard_frame_count
            FROM scenes sc JOIN episodes e ON e.id = sc.episode_id
            JOIN series s ON s.id = e.series_id JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN storyboard_frames sf ON sf.scene_id = sc.id
            WHERE sc.episode_id = :episode_id AND u.email = :email
            GROUP BY sc.id, sc.episode_id, sc.scene_number, sc.title, sc.description,
                     sc.dialogue, sc.continuity_state, sc.environment_notes,
                     sc.created_at, sc.updated_at
            ORDER BY sc.scene_number
            """
        ),
        {"episode_id": str(episode_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/episodes/{episode_id}/scenes")
def create_scene(episode_id: UUID, payload: SceneCreate, db: Session = Depends(get_db)):
    scene = db.execute(
        text(
            """
            INSERT INTO scenes (
                episode_id, scene_number, title, description, dialogue,
                continuity_state, environment_notes
            )
            SELECT e.id, :scene_number, :title, :description,
                   CAST(:dialogue AS jsonb), CAST(:continuity_state AS jsonb),
                   :environment_notes
            FROM episodes e JOIN series s ON s.id = e.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            WHERE e.id = :episode_id AND u.email = :email
            RETURNING id, episode_id, scene_number, title, description, dialogue,
                      continuity_state, environment_notes, created_at, updated_at
            """
        ),
        {
            "episode_id": str(episode_id), "email": DEV_USER_EMAIL,
            "scene_number": payload.scene_number, "title": payload.title,
            "description": payload.description, "dialogue": json.dumps(payload.dialogue),
            "continuity_state": json.dumps(payload.continuity_state),
            "environment_notes": payload.environment_notes,
        },
    ).mappings().first()
    if scene is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Episode was not found")
    db.commit()
    return dict(scene)


@router.get("/scenes/{scene_id}/storyboards")
def get_scene_storyboards(scene_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT sf.id, sf.scene_id, sf.frame_number, sf.version_number, sf.prompt,
                   sf.image_asset_id, sf.character_version_ids, sf.status,
                   sf.dependency_metadata, sf.created_at, gj.id AS job_id,
                   gj.status AS job_status, gj.provider, gj.provider_model
            FROM storyboard_frames sf JOIN scenes sc ON sc.id = sf.scene_id
            JOIN episodes e ON e.id = sc.episode_id JOIN series s ON s.id = e.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            LEFT JOIN generation_jobs gj
              ON gj.request_metadata->>'storyboard_frame_id' = sf.id::text
            WHERE sf.scene_id = :scene_id AND u.email = :email
            ORDER BY sf.frame_number, sf.version_number
            """
        ),
        {"scene_id": str(scene_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/scenes/{scene_id}/storyboards")
def create_storyboard_frame(
    scene_id: UUID,
    payload: StoryboardFrameCreate,
    db: Session = Depends(get_db),
):
    ids = "{" + ",".join(str(item) for item in payload.character_version_ids) + "}"
    frame = db.execute(
        text(
            """
            INSERT INTO storyboard_frames (
                scene_id, frame_number, version_number, prompt,
                character_version_ids, status, dependency_metadata
            )
            SELECT sc.id, :frame_number, :version_number, :prompt,
                   CAST(:character_version_ids AS uuid[]), 'draft',
                   CAST(:dependency_metadata AS jsonb)
            FROM scenes sc JOIN episodes e ON e.id = sc.episode_id
            JOIN series s ON s.id = e.series_id JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE sc.id = :scene_id AND u.email = :email
            RETURNING id, scene_id, frame_number, version_number, prompt,
                      character_version_ids, status, dependency_metadata, created_at
            """
        ),
        {
            "scene_id": str(scene_id), "email": DEV_USER_EMAIL,
            "frame_number": payload.frame_number, "version_number": payload.version_number,
            "prompt": payload.prompt, "character_version_ids": ids,
            "dependency_metadata": json.dumps(payload.dependency_metadata),
        },
    ).mappings().first()
    if frame is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Scene was not found")

    job = db.execute(
        text(
            """
            INSERT INTO generation_jobs (
                job_type, status, provider, provider_model, request_metadata, max_attempts
            ) VALUES (
                'storyboard_generation', 'queued', 'mock', 'mock-storyboard-v1',
                CAST(:request_metadata AS jsonb), 1
            )
            RETURNING id, job_type, status, provider, provider_model, created_at
            """
        ),
        {"request_metadata": json.dumps({"storyboard_frame_id": str(frame["id"]), "scene_id": str(scene_id)})},
    ).mappings().one()
    db.commit()
    return {"frame": dict(frame), "job": dict(job)}
