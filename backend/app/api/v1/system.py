from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL


router = APIRouter(tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "movai-api"}


@router.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": "connected"}


@router.get("/api/v1/demo/overview")
def demo_overview(db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT p.id AS project_id, p.title AS project_title,
                   s.id AS series_id, s.title AS series_title,
                   e.id AS episode_id, e.title AS episode_title,
                   e.target_duration_seconds, c.id AS character_id,
                   c.name AS character_name, cv.id AS character_version_id,
                   cv.version_number AS character_version, sc.id AS scene_id,
                   sc.title AS scene_title, sf.id AS storyboard_frame_id,
                   sf.status AS storyboard_status, gj.id AS job_id,
                   gj.status AS job_status, gj.provider, gj.provider_model
            FROM users u JOIN projects p ON p.owner_id = u.id
            JOIN series s ON s.project_id = p.id
            JOIN episodes e ON e.series_id = s.id
            LEFT JOIN characters c ON c.series_id = s.id
            LEFT JOIN character_versions cv ON cv.character_id = c.id
            LEFT JOIN scenes sc ON sc.episode_id = e.id
            LEFT JOIN storyboard_frames sf ON sf.scene_id = sc.id
            LEFT JOIN generation_jobs gj
              ON gj.request_metadata->>'storyboard_frame_id' = sf.id::text
            WHERE u.email = :email AND p.title = :project_title
              AND s.title = :series_title AND e.episode_number = 1
            ORDER BY sc.scene_number, sf.frame_number
            """
        ),
        {
            "email": DEV_USER_EMAIL,
            "project_title": "Demo Drama Project",
            "series_title": "The First Signal",
        },
    )
    items = [dict(row) for row in result.mappings().all()]
    if not items:
        raise HTTPException(status_code=404, detail="Demo data was not found")
    return {"count": len(items), "items": items}
