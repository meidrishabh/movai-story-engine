import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.repositories.analysis_repository import (
    create_analysis_run,
    get_latest_analysis_run,
    record_complexity_output,
)
from app.schemas.story import (
    AnalyzeSeasonRequest,
    MasterScriptCreate,
    SeriesSeasonPlanRequest,
    StorySourceCreate,
)
from app.services.document_ingestion import prepare_source_document


router = APIRouter(prefix="/api/v1", tags=["story"])


@router.get("/series/{series_id}/pipeline")
def get_series_story_pipeline(series_id: UUID, db: Session = Depends(get_db)):
    series = db.execute(
        text(
            """
            SELECT s.id, s.title, s.premise, s.genre, s.language_code,
                   s.visual_style, s.estimated_duration_seconds,
                   s.target_season_count, s.target_episode_duration_seconds,
                   s.created_at, s.updated_at
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).mappings().first()
    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    source = db.execute(
        text(
            """
            SELECT id, series_id, title, source_type, input_format,
                   original_filename, validation_status,
                   status, created_at, updated_at
            FROM story_sources
            WHERE series_id = :series_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().first()

    master_script = db.execute(
        text(
            """
            SELECT id, series_id, version_number, title, summary,
                   status, created_at, updated_at
            FROM master_scripts
            WHERE series_id = :series_id
            ORDER BY version_number DESC
            LIMIT 1
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().first()

    analysis_run = get_latest_analysis_run(db, series_id)
    story_status = str(source["status"]) if source else "not_started"
    if master_script and str(master_script["status"]) in {"approved", "succeeded"}:
        story_status = "processed"
    elif master_script and story_status not in {"analysis_complete", "processed"}:
        story_status = "master_script_ready"

    return {
        "series": dict(series),
        "source": dict(source) if source else None,
        "master_script": dict(master_script) if master_script else None,
        "analysis_run": dict(analysis_run) if analysis_run else None,
        "story_status": story_status,
    }


@router.post("/series/{series_id}/sources")
def create_series_story_source(
    series_id: UUID,
    payload: StorySourceCreate,
    db: Session = Depends(get_db),
):
    source = db.execute(
        text(
            """
            INSERT INTO story_sources (
                series_id, season_id, title, source_type,
                original_filename, raw_text, metadata
            )
            SELECT s.id, NULL, :title, :source_type,
                   :original_filename, :raw_text, CAST(:metadata AS jsonb)
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            RETURNING id, series_id, season_id, title, source_type,
                      original_filename, status, created_at, updated_at
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "source_type": payload.source_type,
            "original_filename": payload.original_filename,
            "raw_text": payload.raw_text,
            "metadata": json.dumps(payload.metadata),
        },
    ).mappings().first()
    if source is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    try:
        document_id = prepare_source_document(db, dict(source), payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    result = dict(source)
    result["document_id"] = str(document_id)
    result["validation_status"] = "validated"
    return result


@router.post("/series/{series_id}/master-script")
def create_series_master_script(
    series_id: UUID,
    payload: MasterScriptCreate,
    db: Session = Depends(get_db),
):
    next_version = db.execute(
        text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM master_scripts WHERE series_id = :series_id"),
        {"series_id": str(series_id)},
    ).scalar_one()
    script = db.execute(
        text(
            """
            INSERT INTO master_scripts (
                series_id, season_id, version_number, title, summary,
                full_script, analysis_metadata, status
            )
            SELECT s.id, NULL, :version_number, :title, :summary,
                   :full_script, CAST(:analysis_metadata AS jsonb),
                   CAST(:status AS approval_status)
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            RETURNING id, series_id, season_id, version_number, title,
                      summary, full_script, analysis_metadata, status,
                      created_at, updated_at
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "version_number": next_version,
            "title": payload.title,
            "summary": payload.summary,
            "full_script": payload.full_script,
            "analysis_metadata": json.dumps(payload.analysis_metadata),
            "status": payload.status,
        },
    ).mappings().first()
    if script is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")
    db.commit()
    return dict(script)


@router.post("/series/{series_id}/analyze")
def analyze_series_story(
    series_id: UUID,
    payload: AnalyzeSeasonRequest,
    db: Session = Depends(get_db),
):
    source_id = payload.source_id or db.execute(
        text("SELECT id FROM story_sources WHERE series_id = :series_id ORDER BY created_at DESC LIMIT 1"),
        {"series_id": str(series_id)},
    ).scalar()
    if source_id is None:
        raise HTTPException(status_code=400, detail="Upload a source story before analysis")

    series_exists = db.execute(
        text(
            """
            SELECT s.id FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).scalar()
    if series_exists is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    profile = db.execute(
        text("SELECT COALESCE(analysis_profile, 'standard') FROM series WHERE id = :series_id"),
        {"series_id": str(series_id)},
    ).scalar_one()
    analysis_run = create_analysis_run(db, series_id, source_id, profile)
    complexity = db.execute(
        text("SELECT COALESCE(analysis_complexity, '{}'::jsonb) FROM series WHERE id = :series_id"),
        {"series_id": str(series_id)},
    ).scalar_one()
    record_complexity_output(db, analysis_run["id"], complexity)
    job = db.execute(
        text(
            """
            INSERT INTO generation_jobs (
                job_type, status, provider, provider_model,
                request_metadata, max_attempts
            )
            VALUES (
                'story_analysis', 'queued', 'mock', 'mock-story-analyzer-v1',
                CAST(:request_metadata AS jsonb), 1
            )
            RETURNING id, job_type, status, provider, provider_model, created_at
            """
        ),
        {
            "request_metadata": json.dumps(
                {
                    "series_id": str(series_id),
                    "source_id": str(source_id),
                    "analysis_run_id": str(analysis_run["id"]),
                }
            )
        },
    ).mappings().one()
    db.execute(
        text("UPDATE story_sources SET status = 'analysis_queued' WHERE id = :source_id"),
        {"source_id": str(source_id)},
    )
    db.commit()
    result = dict(job)
    result["analysis_run_id"] = str(analysis_run["id"])
    return result


@router.post("/series/{series_id}/plan-seasons")
def plan_series_seasons(
    series_id: UUID,
    payload: SeriesSeasonPlanRequest,
    db: Session = Depends(get_db),
):
    readiness = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM story_sources
                WHERE series_id = :series_id
                  AND status IN ('analysis_complete', 'processed')
            ) OR EXISTS (
                SELECT 1 FROM master_scripts
                WHERE series_id = :series_id
                  AND status IN ('approved', 'succeeded')
            )
            """
        ),
        {"series_id": str(series_id)},
    ).scalar()
    if not readiness:
        raise HTTPException(status_code=409, detail="Process the complete series story before planning seasons")

    series = db.execute(
        text(
            """
            UPDATE series s
            SET target_season_count = :target_season_count,
                target_episode_duration_seconds = :target_episode_duration_seconds,
                updated_at = now()
            FROM projects p JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND p.id = s.project_id AND u.email = :email
            RETURNING s.id, s.title, s.estimated_duration_seconds,
                      s.target_season_count, s.target_episode_duration_seconds
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "target_season_count": payload.target_season_count,
            "target_episode_duration_seconds": payload.target_episode_duration_seconds,
        },
    ).mappings().first()
    if series is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    existing_count = db.execute(
        text("SELECT COUNT(*) FROM seasons WHERE series_id = :series_id"),
        {"series_id": str(series_id)},
    ).scalar_one()
    if existing_count > payload.target_season_count:
        db.rollback()
        raise HTTPException(status_code=409, detail="Requested season count is lower than existing seasons")

    for season_number in range(existing_count + 1, payload.target_season_count + 1):
        db.execute(
            text(
                """
                INSERT INTO seasons (series_id, season_number, title, synopsis, story_status)
                VALUES (:series_id, :season_number, :title,
                        'Planned from the processed series story.', 'planned')
                """
            ),
            {
                "series_id": str(series_id),
                "season_number": season_number,
                "title": f"Season {season_number}",
            },
        )

    seasons = db.execute(
        text(
            """
            SELECT id, series_id, season_number, title, synopsis, story_status
            FROM seasons WHERE series_id = :series_id ORDER BY season_number
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()
    db.commit()
    return {"series": dict(series), "seasons": [dict(row) for row in seasons]}
