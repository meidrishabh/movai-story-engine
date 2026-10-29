from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.catalog import EpisodeCreate, EpisodeUpdate, ProjectCreate, ProjectUpdate, SeriesCreate, SeriesUpdate
from app.services.catalog_service import CatalogService


router = APIRouter(prefix="/api/v1", tags=["catalog"])
catalog_service = CatalogService()


def ensure_dev_user(db: Session):
    return db.execute(
        text(
            """
            INSERT INTO users (email, display_name, is_active)
            VALUES (:email, 'MovAI Development User', TRUE)
            ON CONFLICT (email) DO UPDATE
            SET is_active = TRUE, updated_at = now()
            RETURNING id
            """
        ),
        {"email": DEV_USER_EMAIL},
    ).scalar_one()


@router.get("/series")
def get_all_series(db: Session = Depends(get_db)):
    items = catalog_service.list_series(db)
    return {"count": len(items), "items": items}

    # Legacy SQL below is retained temporarily for deletion after migration.
    result = db.execute(
        text(
            """
            SELECT s.id, s.project_id, s.title, s.premise, s.genre,
                   s.language_code, s.visual_style, s.created_at, s.updated_at,
                   COUNT(DISTINCT se.id) AS season_count,
                   COUNT(DISTINCT e.id) AS episode_count
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN seasons se ON se.series_id = s.id
            LEFT JOIN episodes e ON e.series_id = s.id
            WHERE u.email = :email
            GROUP BY s.id, s.project_id, s.title, s.premise, s.genre,
                     s.language_code, s.visual_style, s.created_at, s.updated_at
            ORDER BY s.created_at DESC
            """
        ),
        {"email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.get("/series/{series_id}")
def get_series(series_id: UUID, db: Session = Depends(get_db)):
    series = catalog_service.get_series(db, series_id)
    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")
    return series

    # Legacy SQL below is retained temporarily for deletion after migration.
    series = db.execute(
        text(
            """
            SELECT s.id, s.project_id, s.title, s.premise, s.genre,
                   s.language_code, s.visual_style, s.continuity_notes,
                   s.created_at, s.updated_at
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).mappings().first()
    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")
    return dict(series)


@router.post("/series")
def create_root_series(payload: SeriesCreate, db: Session = Depends(get_db)):
    ensure_dev_user(db)
    project_id = db.execute(
        text(
            """SELECT p.id FROM projects p JOIN users u ON u.id = p.owner_id
               WHERE u.email = :email AND p.title = 'Default Studio' LIMIT 1"""
        ),
        {"email": DEV_USER_EMAIL},
    ).scalar()
    if project_id is None:
        project_id = db.execute(
            text(
                """INSERT INTO projects (owner_id, title, description)
                   SELECT id, 'Default Studio', 'Internal container for series.'
                   FROM users WHERE email = :email RETURNING id"""
            ),
            {"email": DEV_USER_EMAIL},
        ).scalar()
    if project_id is None:
        db.rollback()
        raise HTTPException(status_code=500, detail="Development user was not found")
    series = db.execute(
        text(
            """INSERT INTO series (project_id, title, premise, genre, language_code, visual_style)
               VALUES (:project_id, :title, :premise, :genre, :language_code, :visual_style)
               RETURNING id, project_id, title, premise, genre, language_code,
                         visual_style, created_at, updated_at"""
        ),
        {
            "project_id": str(project_id), "title": payload.title,
            "premise": payload.premise, "genre": payload.genre,
            "language_code": payload.language_code, "visual_style": payload.visual_style,
        },
    ).mappings().one()
    db.commit()
    return dict(series)


@router.get("/projects")
def get_all_projects(db: Session = Depends(get_db)):
    items = catalog_service.list_projects(db)
    return {"count": len(items), "items": items}

    # Legacy SQL below is retained temporarily for deletion after migration.
    result = db.execute(
        text(
            """
            SELECT p.id, p.title, p.description, p.settings,
                   p.created_at, p.updated_at,
                   COUNT(DISTINCT s.id) AS series_count
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN series s ON s.project_id = p.id
            WHERE u.email = :email
            GROUP BY p.id, p.title, p.description, p.settings,
                     p.created_at, p.updated_at
            ORDER BY p.created_at DESC
            """
        ),
        {"email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/projects")
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    try:
        return catalog_service.create_project(db, payload)
    except LookupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    # Legacy SQL below is retained temporarily for deletion after migration.
    owner_id = ensure_dev_user(db)
    project = db.execute(
        text(
            """
            INSERT INTO projects (owner_id, title, description)
            VALUES (:owner_id, :title, :description)
            RETURNING id, owner_id, title, description, settings,
                      created_at, updated_at
            """
        ),
        {"owner_id": owner_id, "title": payload.title, "description": payload.description},
    ).mappings().first()
    if project is None:
        db.rollback()
        raise HTTPException(status_code=500, detail="Development user was not found")
    db.commit()
    return dict(project)


@router.get("/projects/{project_id}")
def get_project(project_id: UUID, db: Session = Depends(get_db)):
    project = catalog_service.get_project(db, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project was not found")
    return project

    # Legacy SQL below is retained temporarily for deletion after migration.
    project = db.execute(
        text(
            """
            SELECT p.id, p.owner_id, p.title, p.description, p.settings,
                   p.created_at, p.updated_at, COUNT(DISTINCT s.id) AS series_count
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN series s ON s.project_id = p.id
            WHERE p.id = :project_id AND u.email = :email
            GROUP BY p.id, p.owner_id, p.title, p.description, p.settings,
                     p.created_at, p.updated_at
            """
        ),
        {"project_id": str(project_id), "email": DEV_USER_EMAIL},
    ).mappings().first()
    if project is None:
        raise HTTPException(status_code=404, detail="Project was not found")
    return dict(project)


@router.patch("/projects/{project_id}")
def update_project(project_id: UUID, payload: ProjectUpdate, db: Session = Depends(get_db)):
    project = catalog_service.update_project(db, project_id, payload)
    if project is None:
        raise HTTPException(status_code=404, detail="Project was not found")
    return project

    # Legacy SQL below is retained temporarily for deletion after migration.
    project = db.execute(
        text(
            """
            UPDATE projects p
            SET title = COALESCE(:title, p.title),
                description = COALESCE(:description, p.description)
            FROM users u
            WHERE p.id = :project_id AND u.id = p.owner_id AND u.email = :email
            RETURNING p.id, p.owner_id, p.title, p.description, p.settings,
                      p.created_at, p.updated_at
            """
        ),
        {
            "project_id": str(project_id), "email": DEV_USER_EMAIL,
            "title": payload.title, "description": payload.description,
        },
    ).mappings().first()
    if project is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Project was not found")
    db.commit()
    return dict(project)


@router.get("/projects/{project_id}/series")
def get_project_series(project_id: UUID, db: Session = Depends(get_db)):
    items = catalog_service.list_project_series(db, project_id)
    return {"count": len(items), "items": items}

    # Legacy SQL below is retained temporarily for deletion after migration.
    result = db.execute(
        text(
            """
            SELECT s.id, s.project_id, s.title, s.premise, s.genre,
                   s.language_code, s.visual_style, s.continuity_notes,
                   s.created_at, s.updated_at, COUNT(DISTINCT e.id) AS episode_count
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN episodes e ON e.series_id = s.id
            WHERE s.project_id = :project_id AND u.email = :email
            GROUP BY s.id, s.project_id, s.title, s.premise, s.genre,
                     s.language_code, s.visual_style, s.continuity_notes,
                     s.created_at, s.updated_at
            ORDER BY s.created_at
            """
        ),
        {"project_id": str(project_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/projects/{project_id}/series")
def create_series(project_id: UUID, payload: SeriesCreate, db: Session = Depends(get_db)):
    series = catalog_service.create_series(db, project_id, payload)
    if series is None:
        raise HTTPException(status_code=404, detail="Project was not found")
    return series

    # Legacy SQL below is retained temporarily for deletion after migration.
    series = db.execute(
        text(
            """
            INSERT INTO series (project_id, title, premise, genre, language_code, visual_style)
            SELECT p.id, :title, :premise, :genre, :language_code, :visual_style
            FROM projects p JOIN users u ON u.id = p.owner_id
            WHERE p.id = :project_id AND u.email = :email
            RETURNING id, project_id, title, premise, genre, language_code,
                      visual_style, created_at, updated_at
            """
        ),
        {
            "project_id": str(project_id), "email": DEV_USER_EMAIL,
            "title": payload.title, "premise": payload.premise,
            "genre": payload.genre, "language_code": payload.language_code,
            "visual_style": payload.visual_style,
        },
    ).mappings().first()
    if series is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Project was not found")
    db.commit()
    return dict(series)


@router.patch("/series/{series_id}")
def update_series(series_id: UUID, payload: SeriesUpdate, db: Session = Depends(get_db)):
    series = catalog_service.update_series(db, series_id, payload)
    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")
    return series

    # Legacy SQL below is retained temporarily for deletion after migration.
    series = db.execute(
        text(
            """
            UPDATE series s
            SET title = COALESCE(:title, s.title),
                premise = COALESCE(:premise, s.premise),
                genre = COALESCE(:genre, s.genre),
                language_code = COALESCE(:language_code, s.language_code),
                visual_style = COALESCE(:visual_style, s.visual_style)
            FROM projects p JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND p.id = s.project_id AND u.email = :email
            RETURNING s.id, s.project_id, s.title, s.premise, s.genre,
                      s.language_code, s.visual_style, s.continuity_notes,
                      s.created_at, s.updated_at
            """
        ),
        {
            "series_id": str(series_id), "email": DEV_USER_EMAIL,
            "title": payload.title, "premise": payload.premise,
            "genre": payload.genre, "language_code": payload.language_code,
            "visual_style": payload.visual_style,
        },
    ).mappings().first()
    if series is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")
    db.commit()
    return dict(series)


@router.get("/series/{series_id}/episodes")
def get_series_episodes(series_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT e.id, e.series_id, e.episode_number, e.title, e.synopsis,
                   e.script, e.target_duration_seconds, e.status,
                   e.created_at, e.updated_at
            FROM episodes e JOIN series s ON s.id = e.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            WHERE e.series_id = :series_id AND u.email = :email
            ORDER BY e.episode_number
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/series/{series_id}/episodes")
def create_episode(
    series_id: UUID,
    payload: EpisodeCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Episodes are created by approved episode segmentation, not manually.",
    )


@router.patch("/episodes/{episode_id}")
def update_episode(episode_id: UUID, payload: EpisodeUpdate, db: Session = Depends(get_db)):
    episode = db.execute(
        text(
            """
            UPDATE episodes e
            SET title = COALESCE(:title, e.title),
                synopsis = COALESCE(:synopsis, e.synopsis),
                script = COALESCE(:script, e.script),
                target_duration_seconds = COALESCE(
                    :target_duration_seconds, e.target_duration_seconds),
                status = COALESCE(:status, e.status)
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE e.id = :episode_id AND s.id = e.series_id AND u.email = :email
            RETURNING e.id, e.series_id, e.episode_number, e.title, e.synopsis,
                      e.script, e.target_duration_seconds, e.status,
                      e.created_at, e.updated_at
            """
        ),
        {
            "episode_id": str(episode_id), "email": DEV_USER_EMAIL,
            "title": payload.title, "synopsis": payload.synopsis,
            "script": payload.script,
            "target_duration_seconds": payload.target_duration_seconds,
            "status": payload.status,
        },
    ).mappings().first()
    if episode is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Episode was not found")
    db.commit()
    return dict(episode)
