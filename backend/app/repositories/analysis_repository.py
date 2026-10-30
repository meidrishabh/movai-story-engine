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


def list_source_chunks(db: Session, source_id: UUID) -> list[dict]:
    rows = db.execute(
        text(
            """SELECT id, narrative_position, chapter_title, page_start, page_end, content_text
               FROM story_chunks WHERE story_source_id = :source_id
               ORDER BY narrative_position"""
        ),
        {"source_id": str(source_id)},
    ).mappings().all()
    return [
        {
            "chunk_id": str(row["id"]),
            "narrative_position": row["narrative_position"],
            "chapter_title": row["chapter_title"],
            "page_start": row["page_start"],
            "page_end": row["page_end"],
            "text": row["content_text"],
        }
        for row in rows
    ]


def load_batches(db: Session, run_id: UUID, stage_name: str) -> dict[str, dict]:
    rows = db.execute(
        text(
            """SELECT batch_key, parsed, usage, model, prompt_version
               FROM analysis_batches WHERE analysis_run_id = :run_id AND stage_name = :stage"""
        ),
        {"run_id": str(run_id), "stage": stage_name},
    ).mappings().all()
    return {row["batch_key"]: dict(row) for row in rows}


def save_batch(db: Session, run_id: UUID, stage_name: str, batch_key: str, chunk_ids: list[str],
               response, ) -> None:
    db.execute(
        text(
            """INSERT INTO analysis_batches (analysis_run_id, stage_name, batch_key, chunk_ids,
                   raw_response, parsed, usage, model, prompt_version)
               VALUES (:run_id, :stage, :key, CAST(:chunk_ids AS uuid[]), :raw,
                       CAST(:parsed AS jsonb), CAST(:usage AS jsonb), :model, :prompt_version)
               ON CONFLICT (analysis_run_id, stage_name, batch_key) DO NOTHING"""
        ),
        {
            "run_id": str(run_id), "stage": stage_name, "key": batch_key,
            "chunk_ids": "{" + ",".join(chunk_ids) + "}", "raw": response.raw,
            "parsed": json.dumps(response.payload), "usage": json.dumps(response.usage_metadata),
            "model": response.model, "prompt_version": response.prompt_version,
        },
    )


def update_analysis_progress(db: Session, run_id: UUID, stage: str, progress: int):
    db.execute(
        text("UPDATE analysis_runs SET current_stage = :stage, progress = :progress WHERE id = :run_id"),
        {"run_id": str(run_id), "stage": stage, "progress": progress},
    )


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
