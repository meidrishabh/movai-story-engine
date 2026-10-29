import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def create_analysis_run(
    db: Session,
    series_id: UUID,
    source_id: UUID,
    profile: str = "standard",
):
    return db.execute(
        text(
            """
            INSERT INTO analysis_runs (
                series_id, source_id, profile, status, current_stage,
                model_name, prompt_version
            )
            VALUES (
                :series_id, :source_id, :profile, 'queued', 'queued',
                'mock-story-analyzer', 'dev-v1'
            )
            RETURNING id, profile, status, current_stage, progress, created_at
            """
        ),
        {
            "series_id": str(series_id),
            "source_id": str(source_id),
            "profile": profile,
        },
    ).mappings().one()


def get_analysis_run_for_owner(db: Session, run_id: UUID, owner_email: str):
    return db.execute(
        text(
            """
            SELECT ar.id, ar.series_id, ar.source_id, ar.profile, ar.status,
                   ar.current_stage, ar.progress, ar.model_name,
                   ar.prompt_version, ar.estimated_cost, ar.actual_cost,
                   ar.result_metadata, ar.error_message, ar.started_at,
                   ar.completed_at, ar.created_at
            FROM analysis_runs ar
            JOIN series s ON s.id = ar.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE ar.id = :run_id AND u.email = :email
            """
        ),
        {"run_id": str(run_id), "email": owner_email},
    ).mappings().first()


def get_latest_analysis_run(db: Session, series_id: UUID):
    return db.execute(
        text(
            """
            SELECT id, source_id, profile, status, current_stage, progress,
                   model_name, prompt_version, result_metadata, error_message,
                   started_at, completed_at, created_at
            FROM analysis_runs
            WHERE series_id = :series_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().first()


def record_complexity_output(db: Session, run_id: UUID, complexity: dict):
    db.execute(
        text(
            """INSERT INTO analysis_run_stages (
                   analysis_run_id, stage_name, status, progress,
                   output_metadata, started_at, completed_at)
               VALUES (:run_id, 'complexity_analysis', 'succeeded', 100,
                       CAST(:output_metadata AS jsonb), now(), now())
               ON CONFLICT (analysis_run_id, stage_name) DO UPDATE SET
                   status = EXCLUDED.status, progress = EXCLUDED.progress,
                   output_metadata = EXCLUDED.output_metadata,
                   completed_at = EXCLUDED.completed_at"""
        ),
        {"run_id": str(run_id), "output_metadata": json.dumps(complexity)},
    )
    return db.execute(
        text(
            """INSERT INTO analysis_outputs (
                   analysis_run_id, output_type, version_number, payload,
                   source_references, status)
               VALUES (:run_id, 'complexity_report', 1,
                       CAST(:payload AS jsonb), '[]'::jsonb, 'succeeded')
               ON CONFLICT (analysis_run_id, output_type, version_number) DO UPDATE SET
                   payload = EXCLUDED.payload, status = EXCLUDED.status,
                   updated_at = now()
               RETURNING id, output_type, version_number, status, created_at"""
        ),
        {"run_id": str(run_id), "payload": json.dumps(complexity)},
    ).mappings().one()


def mark_analysis_running(db: Session, run_id: UUID):
    db.execute(
        text(
            """
            UPDATE analysis_runs
            SET status = 'running', current_stage = 'chunk_analysis',
                progress = 20, started_at = COALESCE(started_at, now())
            WHERE id = :run_id
            """
        ),
        {"run_id": str(run_id)},
    )


def mark_analysis_succeeded(
    db: Session,
    run_id: UUID,
    chunk_count: int,
):
    db.execute(
        text(
            """
            UPDATE analysis_runs
            SET status = 'succeeded', current_stage = 'review_required',
                progress = 100,
                result_metadata = CAST(:result_metadata AS jsonb),
                completed_at = now()
            WHERE id = :run_id
            """
        ),
        {
            "run_id": str(run_id),
            "result_metadata": json.dumps(
                {
                    "mode": "development_placeholder",
                    "chunk_count": chunk_count,
                    "ocr_used": False,
                    "message": "Connect the production analyzer and embedding provider for semantic results.",
                }
            ),
        },
    )
