from uuid import UUID

from sqlalchemy import text

from app.repositories.analysis_repository import mark_analysis_succeeded
from app.services.story_analysis_service import StoryAnalysisService


def process_entity_extraction(db, analysis_run_id: UUID, on_progress=None):
    run = db.execute(
        text("SELECT id, source_id, profile FROM analysis_runs WHERE id = :run_id"),
        {"run_id": str(analysis_run_id)},
    ).mappings().first()
    if run is None:
        raise ValueError("Analysis run was not found")
    return StoryAnalysisService().extract_entities(
        db,
        analysis_run_id,
        UUID(str(run["source_id"])),
        str(run["profile"]),
        on_progress=on_progress,
    )


def complete_story_analysis(db, job_id: UUID, metadata: dict):
    """Close out a series-level story_analysis job and its analysis run."""
    run_id = UUID(metadata["analysis_run_id"])
    chunk_count = db.execute(
        text(
            """SELECT COUNT(*) FROM story_chunks sc
               JOIN analysis_runs ar ON ar.source_id = sc.story_source_id
               WHERE ar.id = :run_id"""
        ),
        {"run_id": str(run_id)},
    ).scalar_one()
    mark_analysis_succeeded(db, run_id, int(chunk_count))

    source_id = metadata.get("source_id")
    if source_id:
        db.execute(
            text("UPDATE story_sources SET status = 'analysis_complete' WHERE id = :source_id"),
            {"source_id": source_id},
        )
        # The master script stage sets the real estimate; this only fills it when that stage never ran (mock runs).
        db.execute(
            text(
                """UPDATE series s SET estimated_duration_seconds = GREATEST(
                       60, CEIL(COALESCE(length(ss.raw_text), 0) / 12.0)::INTEGER), updated_at = now()
                   FROM story_sources ss WHERE ss.id = :source_id AND ss.series_id = s.id
                     AND s.estimated_duration_seconds IS NULL"""
            ),
            {"source_id": source_id},
        )

    completed = db.execute(
        text(
            """UPDATE generation_jobs SET status = 'succeeded', progress = 100,
                   completed_at = now()
               WHERE id = :job_id
               RETURNING id, job_type, status, progress, provider, provider_model,
                         created_at, started_at, completed_at"""
        ),
        {"job_id": str(job_id)},
    ).mappings().one()
    db.commit()
    return dict(completed)
