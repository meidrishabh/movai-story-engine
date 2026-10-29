from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.catalog import EpisodeCreate, SeasonCreate, SeasonPipelineUpdate, SeasonUpdate
from app.services.season_service import SeasonService


router = APIRouter(prefix="/api/v1", tags=["seasons"])
season_service = SeasonService()


@router.get("/series/{series_id}/seasons")
def get_series_seasons(series_id: UUID, db: Session = Depends(get_db)):
    items = season_service.list_for_series(db, series_id)
    return {"count": len(items), "items": items}

    # Legacy SQL below is retained temporarily for deletion after migration.
    result = db.execute(
        text(
            """
            SELECT se.id, se.series_id, se.season_number, se.title, se.synopsis,
                   se.status, se.target_episode_count,
                   se.target_episode_duration_seconds, se.climax_strategy,
                   se.story_status, se.created_at, se.updated_at,
                   COUNT(e.id) AS episode_count
            FROM seasons se
            JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            LEFT JOIN episodes e ON e.season_id = se.id
            WHERE se.series_id = :series_id AND u.email = :email
            GROUP BY se.id, se.series_id, se.season_number, se.title, se.synopsis,
                     se.status, se.target_episode_count,
                     se.target_episode_duration_seconds, se.climax_strategy,
                     se.story_status, se.created_at, se.updated_at
            ORDER BY se.season_number
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/series/{series_id}/seasons")
def create_season(series_id: UUID, payload: SeasonCreate, db: Session = Depends(get_db)):
    try:
        season = season_service.create(db, series_id, payload)
    except PermissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if season is None:
        raise HTTPException(status_code=404, detail="Series was not found")
    return season

    # Legacy SQL below is retained temporarily for deletion after migration.
    readiness = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM seasons
                WHERE series_id = :series_id
                  AND story_status IN ('analysis_complete', 'episode_planning_queued',
                                       'episodes_generated', 'processed', 'complete', 'approved')
            )
            """
        ),
        {"series_id": str(series_id)},
    ).scalar()
    if not readiness:
        raise HTTPException(
            status_code=409,
            detail="Use season planning to create the first season, or finish the current season story before creating another season",
        )

    season = db.execute(
        text(
            """
            INSERT INTO seasons (series_id, season_number, title, synopsis)
            SELECT s.id, :season_number, :title, :synopsis
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            RETURNING id, series_id, season_number, title, synopsis, status,
                      created_at, updated_at
            """
        ),
        {
            "series_id": str(series_id), "email": DEV_USER_EMAIL,
            "season_number": payload.season_number, "title": payload.title,
            "synopsis": payload.synopsis,
        },
    ).mappings().first()
    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")
    db.commit()
    return dict(season)


@router.patch("/seasons/{season_id}")
def update_season(season_id: UUID, payload: SeasonUpdate, db: Session = Depends(get_db)):
    season = season_service.update(db, season_id, payload)
    if season is None:
        raise HTTPException(status_code=404, detail="Season was not found")
    return season

    # Legacy SQL below is retained temporarily for deletion after migration.
    season = db.execute(
        text(
            """
            UPDATE seasons se
            SET title = COALESCE(:title, se.title),
                synopsis = COALESCE(:synopsis, se.synopsis),
                status = COALESCE(:status, se.status)
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id AND s.id = se.series_id AND u.email = :email
            RETURNING se.id, se.series_id, se.season_number, se.title,
                      se.synopsis, se.status, se.created_at, se.updated_at
            """
        ),
        {
            "season_id": str(season_id), "email": DEV_USER_EMAIL,
            "title": payload.title, "synopsis": payload.synopsis,
            "status": payload.status,
        },
    ).mappings().first()
    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")
    db.commit()
    return dict(season)


@router.patch("/seasons/{season_id}/pipeline")
def update_season_pipeline(
    season_id: UUID,
    payload: SeasonPipelineUpdate,
    db: Session = Depends(get_db),
):
    season = season_service.update_pipeline(db, season_id, payload)
    if season is None:
        raise HTTPException(status_code=404, detail="Season was not found")
    return season

    # Legacy SQL below is retained temporarily for deletion after migration.
    season = db.execute(
        text(
            """
            UPDATE seasons se
            SET target_episode_count = COALESCE(:target_episode_count, se.target_episode_count),
                target_episode_duration_seconds = COALESCE(
                    :target_episode_duration_seconds, se.target_episode_duration_seconds),
                climax_strategy = COALESCE(:climax_strategy, se.climax_strategy)
            FROM series s JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id AND s.id = se.series_id AND u.email = :email
            RETURNING se.id, se.series_id, se.season_number, se.title, se.synopsis,
                      se.target_episode_count, se.target_episode_duration_seconds,
                      se.climax_strategy, se.story_status, se.created_at, se.updated_at
            """
        ),
        {
            "season_id": str(season_id), "email": DEV_USER_EMAIL,
            "target_episode_count": payload.target_episode_count,
            "target_episode_duration_seconds": payload.target_episode_duration_seconds,
            "climax_strategy": payload.climax_strategy,
        },
    ).mappings().first()
    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")
    db.commit()
    return dict(season)


@router.get("/seasons/{season_id}/pipeline")
def get_season_pipeline(season_id: UUID, db: Session = Depends(get_db)):
    pipeline = season_service.get_pipeline(db, season_id)
    if pipeline is None:
        raise HTTPException(status_code=404, detail="Season was not found")
    return pipeline

    # Legacy SQL below is retained temporarily for deletion after migration.
    season = db.execute(
        text(
            """
            SELECT se.id, se.series_id, se.season_number, se.title, se.synopsis,
                   se.target_episode_count, se.target_episode_duration_seconds,
                   se.climax_strategy, se.story_status
            FROM seasons se JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id AND u.email = :email
            """
        ),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    ).mappings().first()
    if season is None:
        raise HTTPException(status_code=404, detail="Season was not found")

    source = db.execute(
        text(
            """SELECT id, title, source_type, original_filename, status, created_at
               FROM story_sources WHERE season_id = :season_id
               ORDER BY created_at DESC LIMIT 1"""
        ),
        {"season_id": str(season_id)},
    ).mappings().first()
    master_script = db.execute(
        text(
            """SELECT id, version_number, title, summary, status, created_at, updated_at
               FROM master_scripts WHERE season_id = :season_id
               ORDER BY version_number DESC LIMIT 1"""
        ),
        {"season_id": str(season_id)},
    ).mappings().first()
    return {
        "season": dict(season),
        "source": dict(source) if source else None,
        "master_script": dict(master_script) if master_script else None,
    }


@router.get("/seasons/{season_id}/episodes")
def get_season_episodes(season_id: UUID, db: Session = Depends(get_db)):
    items = season_service.list_episodes(db, season_id)
    return {"count": len(items), "items": items}

    # Legacy SQL below is retained temporarily for deletion after migration.
    result = db.execute(
        text(
            """
            SELECT e.id, e.season_id, e.series_id, e.episode_number, e.title,
                   e.synopsis, e.script, e.target_duration_seconds, e.status,
                   e.created_at, e.updated_at
            FROM episodes e JOIN seasons se ON se.id = e.season_id
            JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE e.season_id = :season_id AND u.email = :email
            ORDER BY e.episode_number
            """
        ),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/seasons/{season_id}/episodes")
def create_season_episode(
    season_id: UUID,
    payload: EpisodeCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Episodes are created by approved episode segmentation, not manually.",
    )
