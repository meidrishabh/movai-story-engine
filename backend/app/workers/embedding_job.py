from uuid import UUID

from sqlalchemy import text

from app.services.embedding_persistence import EmbeddingPersistenceService


def process_embedding_job(db, job_id: UUID, batch_size: int = 100):
    job = db.execute(
        text("SELECT id, status, request_metadata FROM generation_jobs WHERE id = :job_id"),
        {"job_id": str(job_id)},
    ).mappings().first()
    if job is None:
        raise ValueError("Embedding job was not found")
    if job["status"] not in {"queued", "running"}:
        raise ValueError(f"Embedding job cannot run from status '{job['status']}'")

    source_id = UUID(str((job["request_metadata"] or {})["source_id"]))
    db.execute(
        text("UPDATE generation_jobs SET status = 'running', progress = 10, started_at = COALESCE(started_at, now()) WHERE id = :job_id"),
        {"job_id": str(job_id)},
    )
    db.commit()

    result = EmbeddingPersistenceService().process_source_batch(db, source_id, batch_size)
    if result["remaining"]:
        db.execute(
            text("UPDATE generation_jobs SET progress = LEAST(99, progress + 20) WHERE id = :job_id"),
            {"job_id": str(job_id)},
        )
        db.commit()
        return {"status": "running", **result}

    db.execute(
        text("UPDATE story_sources SET status = 'ready_for_analysis', updated_at = now() WHERE id = :source_id"),
        {"source_id": str(source_id)},
    )
    completed = db.execute(
        text("""UPDATE generation_jobs SET status = 'succeeded', progress = 100, completed_at = now()
            WHERE id = :job_id RETURNING id, status, progress, completed_at"""),
        {"job_id": str(job_id)},
    ).mappings().one()
    db.commit()
    return {"status": "succeeded", "processed": result["processed"], "job": dict(completed)}


def reembed_source(db, source_id: UUID):
    """Rebuild vectors for one source using the currently configured provider."""
    return EmbeddingPersistenceService().reembed_source(db, source_id)
