import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.providers.base import GenerationRequest
from app.providers.mock import MockStoryboardProvider
from app.repositories.analysis_repository import mark_analysis_running, mark_analysis_succeeded
from app.schemas.workflow import ApprovalCreate
from app.workers.embedding_job import process_embedding_job
from app.workers.story_analysis_worker import complete_story_analysis, process_entity_extraction


router = APIRouter(prefix="/api/v1", tags=["workflow"])


@router.get("/jobs/{job_id}")
def get_job(job_id: UUID, db: Session = Depends(get_db)):
    job = db.execute(
        text(
            """
            SELECT id, job_type, status, progress, provider, provider_model,
                   request_metadata, attempt_count, max_attempts, error_summary,
                   estimated_cost, actual_cost, usage_metadata, output_asset_ids,
                   created_at, started_at, completed_at
            FROM generation_jobs WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    ).mappings().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job was not found")
    return dict(job)


@router.post("/jobs/{job_id}/run-mock")
def run_mock_job(job_id: UUID, db: Session = Depends(get_db)):
    job = db.execute(
        text(
            """SELECT id, job_type, status, provider, provider_model, request_metadata
               FROM generation_jobs WHERE id = :job_id"""
        ),
        {"job_id": str(job_id)},
    ).mappings().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job was not found")
    if job["provider"] != "mock":
        raise HTTPException(status_code=409, detail="Only mock-provider jobs can be run by this development endpoint")
    if job["status"] != "queued":
        raise HTTPException(status_code=409, detail=f"Job cannot be run from status '{job['status']}'")

    if str(job["job_type"]) == "embedding_generation":
        return process_embedding_job(db, job_id)

    db.execute(
        text("UPDATE generation_jobs SET status = 'running', progress = 10, started_at = now() WHERE id = :job_id"),
        {"job_id": str(job_id)},
    )
    db.commit()
    metadata = job["request_metadata"] or {}
    analysis_run_id = metadata.get("analysis_run_id")
    if analysis_run_id:
        mark_analysis_running(db, UUID(analysis_run_id))
        db.commit()

    if str(job["job_type"]) == "story_analysis" and analysis_run_id:
        output = process_entity_extraction(db, UUID(analysis_run_id))
        completed = complete_story_analysis(db, job_id, metadata)
        return {"job": completed, "analysis_output": output}

    provider_result = MockStoryboardProvider().generate(
        GenerationRequest(
            job_type=str(job["job_type"]),
            prompt=metadata.get("prompt", "Mock storyboard frame"),
            input_metadata=metadata,
        )
    )
    usage = {"provider": provider_result.provider, "model": provider_result.model, **provider_result.output_metadata}
    completed = db.execute(
        text(
            """
            UPDATE generation_jobs
            SET status = 'succeeded', progress = 100, provider_model = :provider_model,
                usage_metadata = CAST(:usage_metadata AS jsonb), completed_at = now()
            WHERE id = :job_id
            RETURNING id, job_type, status, progress, provider, provider_model,
                      usage_metadata, created_at, started_at, completed_at
            """
        ),
        {"job_id": str(job_id), "provider_model": provider_result.model, "usage_metadata": json.dumps(usage)},
    ).mappings().one()
    db.commit()

    source_id = metadata.get("source_id")
    if source_id:
        db.execute(text("UPDATE story_sources SET status = 'analysis_complete' WHERE id = :source_id"), {"source_id": source_id})
        db.execute(
            text(
                """UPDATE series s SET estimated_duration_seconds = GREATEST(
                       60, CEIL(COALESCE(length(ss.raw_text), 0) / 12.0)::INTEGER), updated_at = now()
                   FROM story_sources ss WHERE ss.id = :source_id AND ss.series_id = s.id"""
            ),
            {"source_id": source_id},
        )
    season_id = metadata.get("season_id")
    if season_id:
        db.execute(text("UPDATE seasons SET story_status = 'analysis_complete' WHERE id = :season_id"), {"season_id": season_id})
    if analysis_run_id:
        chunk_count = db.execute(
            text("SELECT COUNT(*) FROM story_chunks sc JOIN analysis_runs ar ON ar.source_id = sc.story_source_id WHERE ar.id = :run_id"),
            {"run_id": analysis_run_id},
        ).scalar_one()
        mark_analysis_succeeded(db, UUID(analysis_run_id), int(chunk_count))
    db.commit()
    return dict(completed)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: UUID, db: Session = Depends(get_db)):
    job = db.execute(
        text(
            """UPDATE generation_jobs SET status = 'cancelled', completed_at = now()
               WHERE id = :job_id AND status IN ('queued', 'running')
               RETURNING id, status, completed_at"""
        ),
        {"job_id": str(job_id)},
    ).mappings().first()
    if job is not None:
        db.commit()
        return dict(job)
    existing = db.execute(text("SELECT id, status FROM generation_jobs WHERE id = :job_id"), {"job_id": str(job_id)}).mappings().first()
    if existing is None:
        raise HTTPException(status_code=404, detail="Job was not found")
    raise HTTPException(status_code=409, detail=f"Job cannot be cancelled from status '{existing['status']}'")


@router.post("/approvals")
def create_approval(payload: ApprovalCreate, db: Session = Depends(get_db)):
    approval = db.execute(
        text(
            """INSERT INTO approvals (entity_type, entity_id, decision, notes)
               VALUES (:entity_type, :entity_id, CAST(:decision AS approval_decision), :notes)
               RETURNING id, entity_type, entity_id, decision, notes, created_at"""
        ),
        {"entity_type": payload.entity_type, "entity_id": str(payload.entity_id), "decision": payload.decision, "notes": payload.notes},
    ).mappings().one()
    if payload.entity_type in {"character_version", "storyboard_frame"}:
        table = "character_versions" if payload.entity_type == "character_version" else "storyboard_frames"
        db.execute(text(f"UPDATE {table} SET status = CAST(:status AS approval_status) WHERE id = :entity_id"), {"status": payload.decision, "entity_id": str(payload.entity_id)})
    elif payload.entity_type == "episode":
        db.execute(text("UPDATE episodes SET status = :status WHERE id = :entity_id"), {"status": payload.decision, "entity_id": str(payload.entity_id)})
    db.commit()
    return dict(approval)
