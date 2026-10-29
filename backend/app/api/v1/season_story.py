import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.story import AnalyzeSeasonRequest, MasterScriptCreate, PlanEpisodesRequest, StorySourceCreate
from app.services.document_ingestion import prepare_source_document


router = APIRouter(prefix="/api/v1", tags=["season-story"])


@router.post("/seasons/{season_id}/sources")
def create_story_source(season_id: UUID, payload: StorySourceCreate, db: Session = Depends(get_db)):
    source = db.execute(
        text("""INSERT INTO story_sources (season_id, title, source_type, original_filename, raw_text, metadata)
            SELECT se.id, :title, :source_type, :original_filename, :raw_text, CAST(:metadata AS jsonb)
            FROM seasons se JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id WHERE se.id = :season_id AND u.email = :email
            RETURNING id, season_id, title, source_type, original_filename, status, created_at, updated_at"""),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL, "title": payload.title,
         "source_type": payload.source_type, "original_filename": payload.original_filename,
         "raw_text": payload.raw_text, "metadata": json.dumps(payload.metadata)},
    ).mappings().first()
    if source is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")
    try:
        document_id = prepare_source_document(db, dict(source), payload)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.execute(text("UPDATE seasons SET story_status = 'source_ready' WHERE id = :season_id"), {"season_id": str(season_id)})
    db.commit()
    result = dict(source)
    result["document_id"] = str(document_id)
    result["validation_status"] = "validated"
    return result


@router.get("/seasons/{season_id}/sources")
def get_story_sources(season_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text("""SELECT id, season_id, title, source_type, original_filename, status, created_at, updated_at
            FROM story_sources WHERE season_id = :season_id ORDER BY created_at DESC"""),
        {"season_id": str(season_id)},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@router.post("/seasons/{season_id}/master-script")
def create_master_script(season_id: UUID, payload: MasterScriptCreate, db: Session = Depends(get_db)):
    version = db.execute(text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM master_scripts WHERE season_id = :season_id"), {"season_id": str(season_id)}).scalar_one()
    script = db.execute(
        text("""INSERT INTO master_scripts (season_id, version_number, title, summary, full_script, analysis_metadata, status)
            SELECT se.id, :version_number, :title, :summary, :full_script, CAST(:analysis_metadata AS jsonb), CAST(:status AS approval_status)
            FROM seasons se JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id AND u.email = :email
            RETURNING id, season_id, version_number, title, summary, full_script, analysis_metadata, status, created_at, updated_at"""),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL, "version_number": version,
         "title": payload.title, "summary": payload.summary, "full_script": payload.full_script,
         "analysis_metadata": json.dumps(payload.analysis_metadata), "status": payload.status},
    ).mappings().first()
    if script is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")
    db.execute(text("UPDATE seasons SET story_status = 'master_script_ready' WHERE id = :season_id"), {"season_id": str(season_id)})
    db.commit()
    return dict(script)


@router.get("/seasons/{season_id}/master-script")
def get_master_script(season_id: UUID, db: Session = Depends(get_db)):
    script = db.execute(
        text("""SELECT id, season_id, version_number, title, summary, full_script, analysis_metadata, status, created_at, updated_at
            FROM master_scripts WHERE season_id = :season_id ORDER BY version_number DESC LIMIT 1"""),
        {"season_id": str(season_id)},
    ).mappings().first()
    if script is None:
        raise HTTPException(status_code=404, detail="Master script was not found")
    return dict(script)


@router.post("/seasons/{season_id}/analyze")
def analyze_season_story(season_id: UUID, payload: AnalyzeSeasonRequest, db: Session = Depends(get_db)):
    source_id = payload.source_id or db.execute(text("SELECT id FROM story_sources WHERE season_id = :season_id ORDER BY created_at DESC LIMIT 1"), {"season_id": str(season_id)}).scalar()
    if source_id is None:
        raise HTTPException(status_code=400, detail="Upload a source story before analysis")
    job = db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, provider_model, request_metadata, max_attempts)
            VALUES ('story_analysis', 'queued', 'mock', 'mock-story-analyzer-v1', CAST(:request_metadata AS jsonb), 1)
            RETURNING id, job_type, status, provider, provider_model, created_at"""),
        {"request_metadata": json.dumps({"season_id": str(season_id), "source_id": str(source_id)})},
    ).mappings().one()
    db.execute(text("UPDATE seasons SET story_status = 'analysis_queued' WHERE id = :season_id"), {"season_id": str(season_id)})
    db.execute(text("UPDATE story_sources SET status = 'analysis_queued' WHERE id = :source_id"), {"source_id": str(source_id)})
    db.commit()
    return dict(job)


@router.post("/seasons/{season_id}/plan-episodes")
def plan_season_episodes(season_id: UUID, payload: PlanEpisodesRequest, db: Session = Depends(get_db)):
    master_script_id = payload.master_script_id or db.execute(text("SELECT id FROM master_scripts WHERE season_id = :season_id ORDER BY version_number DESC LIMIT 1"), {"season_id": str(season_id)}).scalar()
    if master_script_id is None:
        raise HTTPException(status_code=400, detail="Create a master script before planning episodes")
    preferences = db.execute(text("SELECT target_episode_count, target_episode_duration_seconds, climax_strategy FROM seasons WHERE id = :season_id"), {"season_id": str(season_id)}).mappings().first()
    if preferences is None:
        raise HTTPException(status_code=404, detail="Season was not found")
    job = db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, provider_model, request_metadata, max_attempts)
            VALUES ('episode_segmentation', 'queued', 'mock', 'mock-episode-planner-v1', CAST(:request_metadata AS jsonb), 1)
            RETURNING id, job_type, status, provider, provider_model, created_at"""),
        {"request_metadata": json.dumps({"season_id": str(season_id), "master_script_id": str(master_script_id), "preferences": dict(preferences)}, default=str)},
    ).mappings().one()
    db.execute(text("UPDATE seasons SET story_status = 'episode_planning_queued' WHERE id = :season_id"), {"season_id": str(season_id)})
    db.commit()
    return dict(job)
