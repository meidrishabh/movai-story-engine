"""Postgres-backed job runner.

Run with:  python -m app.workers.job_runner [--once]
"""
import argparse
import json
import logging
import time
from uuid import UUID

from sqlalchemy import text

from app.core.errors import PermanentJobError
from app.db import SessionLocal
from app.repositories.analysis_repository import mark_analysis_running
from app.providers.llm_factory import get_judge_provider, get_llm_provider
from app.services.adaptation_service import build_highlight, detect_filler, latest_master_script
from app.services.adaptation_service import run_context as adaptation_context
from app.services.analysis_pipeline import run_structure_stages
from app.services.episode_plan_service import build_episode_plan
from app.services.episode_repair_service import repair_episodes
from app.services.generation_service import mark_failed as mark_request_failed
from app.services.generation_service import run_request as run_generation_request
from app.services.render_service import mark_failed as mark_render_failed
from app.services.render_service import run_render
from app.services.llm_stage import LLMStageClient
from app.services.appearance_service import generate_for_series as generate_appearance
from app.services.scene_breakdown_service import build_scene_breakdown
from app.workers.embedding_job import process_embedding_job
from app.workers.story_analysis_worker import complete_story_analysis, process_entity_extraction

log = logging.getLogger("job_runner")

POLL_SECONDS = 2
BACKOFF_SECONDS = 30
STALE_AFTER_MINUTES = 30

# Only job types with a handler below are claimed; the rest stay queued.
CLAIM_SQL = """
UPDATE generation_jobs
SET status = 'running', attempt_count = attempt_count + 1,
    started_at = COALESCE(started_at, now()), heartbeat_at = now(),
    error_summary = NULL
WHERE id = (
    SELECT id FROM generation_jobs
    WHERE status = 'queued'
      AND (run_after IS NULL OR run_after <= now())
      AND (job_type = 'embedding_generation'
           OR (job_type = 'story_analysis'
               AND request_metadata ->> 'analysis_run_id' IS NOT NULL)
           OR (job_type = 'scene_breakdown'
               AND request_metadata ->> 'episode_id' IS NOT NULL)
           OR (job_type = 'episode_render'
               AND request_metadata ->> 'episode_render_id' IS NOT NULL)
           OR (job_type = 'generation_request'
               AND request_metadata ->> 'generation_request_id' IS NOT NULL)
           OR (job_type = 'adaptation_generation'
               AND request_metadata ->> 'series_id' IS NOT NULL)
           OR (job_type = 'episode_segmentation'
               AND request_metadata ->> 'plan_series_id' IS NOT NULL))
    ORDER BY created_at
    FOR UPDATE SKIP LOCKED
    LIMIT 1
)
RETURNING id, job_type, attempt_count, max_attempts, request_metadata
"""


def claim_next(db):
    job = db.execute(text(CLAIM_SQL)).mappings().first()
    db.commit()
    return job


def touch_heartbeat(db, job_id: UUID):
    db.execute(
        text("UPDATE generation_jobs SET heartbeat_at = now() WHERE id = :job_id"),
        {"job_id": str(job_id)},
    )
    db.commit()


def recover_stale(db):
    """Requeue jobs whose worker stopped heartbeating; fail those out of attempts."""
    params = {"minutes": STALE_AFTER_MINUTES}
    stale = "status = 'running' AND heartbeat_at < now() - make_interval(mins => :minutes)"
    db.execute(
        text(
            f"""UPDATE generation_jobs SET status = 'failed', completed_at = now(),
                    error_summary = 'Worker heartbeat expired'
                WHERE {stale} AND attempt_count >= max_attempts"""
        ),
        params,
    )
    requeued = db.execute(
        text(
            f"""UPDATE generation_jobs SET status = 'queued',
                    error_summary = 'Worker heartbeat expired; requeued'
                WHERE {stale} RETURNING id"""
        ),
        params,
    ).all()
    db.commit()
    for row in requeued:
        log.warning("Requeued stale job %s", row[0])


def run_embedding(db, job):
    while True:
        result = process_embedding_job(db, job["id"])
        if result["status"] == "succeeded":
            return
        touch_heartbeat(db, job["id"])


def run_story_analysis(db, job):
    metadata = job["request_metadata"]
    run_id = UUID(metadata["analysis_run_id"])
    mark_analysis_running(db, run_id)
    db.commit()
    beat = lambda: touch_heartbeat(db, job["id"])  # noqa: E731
    process_entity_extraction(db, run_id, on_progress=beat)
    structure = run_structure_stages(db, run_id, on_progress=beat)
    extraction = db.execute(
        text("""SELECT output_metadata -> 'usage' FROM analysis_run_stages
                WHERE analysis_run_id = :r AND stage_name = 'entity_extraction'"""), {"r": str(run_id)}).scalar() or {}
    usage = {key: int(extraction.get(key, 0)) + int(count) for key, count in structure["llm_usage"].items()}
    complete_story_analysis(db, job["id"], metadata, usage)


def _succeed(db, job, result: dict):
    db.execute(
        text("""UPDATE generation_jobs SET status = 'succeeded', progress = 100, completed_at = now(),
                  usage_metadata = CAST(:result AS jsonb) WHERE id = :job_id"""),
        {"job_id": str(job["id"]), "result": json.dumps(result)},
    )
    db.commit()


def run_adaptation(db, job):
    meta = job["request_metadata"]
    series_id, kind = UUID(meta["series_id"]), meta["kind"]
    run_id, profile, story_format = adaptation_context(db, series_id)
    client = LLMStageClient(get_llm_provider(), get_judge_provider())
    try:
        if kind == "appearance":  # regenerate the character reference sheets
            result = generate_appearance(db, client, run_id, series_id, profile, story_format)
        elif kind == "repair":  # a user changed the filler cut; refresh the episodes around it
            result = repair_episodes(db, client, run_id, series_id, profile, story_format)
        elif kind == "concentrated":
            script = latest_master_script(db, series_id)
            client.forget(db, run_id, "filler", f"{script['id']}:")
            client.forget(db, run_id, "filler_judge", f"{script['id']}:")
            result = detect_filler(db, client, run_id, series_id, script["id"], profile, story_format)
        else:
            client.forget(db, run_id, "highlight", f"{kind}:")
            result = build_highlight(db, client, run_id, series_id, kind, int(meta["target_seconds"]), profile, story_format)
    except Exception as error:
        db.rollback()
        db.execute(text("UPDATE adaptations SET status = 'failed', error_summary = :e, updated_at = now() "
                        "WHERE series_id = :s AND kind = :k"), {"e": str(error)[:500], "s": str(series_id), "k": kind})
        db.commit()
        raise
    _succeed(db, job, {**result, **client.state.usage})


def run_episode_planning(db, job):
    meta = job["request_metadata"]
    series_id = UUID(meta["plan_series_id"])
    run_id, profile, story_format = adaptation_context(db, series_id)
    script = latest_master_script(db, series_id)
    client = LLMStageClient(get_llm_provider())
    result = build_episode_plan(db, client, run_id, series_id, script["id"], profile, story_format,
                                meta.get("adaptation_kind") or "full")
    _succeed(db, job, result)


def run_scene_breakdown(db, job):
    result = build_scene_breakdown(db, UUID(job["request_metadata"]["episode_id"]))
    db.execute(
        text("""UPDATE generation_jobs SET status = 'succeeded', progress = 100, completed_at = now(),
                  usage_metadata = CAST(:result AS jsonb) WHERE id = :job_id"""),
        {"job_id": str(job["id"]), "result": json.dumps(result)},
    )
    db.commit()


def run_generation(db, job):
    request_id = UUID(job["request_metadata"]["generation_request_id"])
    try:
        result = run_generation_request(db, request_id)
    except Exception as error:  # noqa: BLE001 - record the failure on the request, then let the runner retry or give up
        db.rollback()
        if isinstance(error, PermanentJobError) or job["attempt_count"] >= job["max_attempts"]:
            mark_request_failed(db, request_id, f"{type(error).__name__}: {error}")
            db.commit()
        raise
    _succeed(db, job, result)


def run_episode_render(db, job):
    render_id = UUID(job["request_metadata"]["episode_render_id"])
    try:
        result = run_render(db, render_id)
    except Exception as error:  # noqa: BLE001 - record the failure on the render, then let the runner retry or give up
        db.rollback()
        if isinstance(error, PermanentJobError) or job["attempt_count"] >= job["max_attempts"]:
            mark_render_failed(db, render_id, f"{type(error).__name__}: {error}")
            db.commit()
        raise
    _succeed(db, job, result)


HANDLERS = {
    "episode_render": run_episode_render,
    "generation_request": run_generation,
    "adaptation_generation": run_adaptation,
    "episode_segmentation": run_episode_planning,
    "scene_breakdown": run_scene_breakdown,
    "embedding_generation": run_embedding,
    "story_analysis": run_story_analysis,
}


def fail_or_retry(db, job, error: Exception):
    db.rollback()
    summary = f"{type(error).__name__}: {error}"[:1000]
    if isinstance(error, PermanentJobError) or job["attempt_count"] >= job["max_attempts"]:
        db.execute(
            text(
                """UPDATE generation_jobs SET status = 'failed', completed_at = now(),
                       error_summary = :summary WHERE id = :job_id"""
            ),
            {"job_id": str(job["id"]), "summary": summary},
        )
        run_id = (job["request_metadata"] or {}).get("analysis_run_id")
        if run_id:
            db.execute(
                text(
                    """UPDATE analysis_runs SET status = 'failed', error_message = :summary,
                           completed_at = now() WHERE id = :run_id"""
                ),
                {"run_id": run_id, "summary": summary},
            )
        log.error("Job %s failed permanently: %s", job["id"], summary)
    else:
        db.execute(
            text(
                """UPDATE generation_jobs SET status = 'queued', error_summary = :summary,
                       run_after = now() + make_interval(secs => :delay)
                   WHERE id = :job_id"""
            ),
            {
                "job_id": str(job["id"]),
                "summary": summary,
                "delay": BACKOFF_SECONDS * job["attempt_count"],
            },
        )
        log.warning("Job %s failed (attempt %s), will retry: %s", job["id"], job["attempt_count"], summary)
    db.commit()


def run_job(db, job):
    log.info("Running %s job %s (attempt %s)", job["job_type"], job["id"], job["attempt_count"])
    try:
        HANDLERS[str(job["job_type"])](db, job)
    except Exception as error:  # noqa: BLE001 - any failure goes through retry handling
        fail_or_retry(db, job, error)


def run(once: bool = False):
    while True:
        with SessionLocal() as db:
            recover_stale(db)
            job = claim_next(db)
            if job is None:
                if once:
                    return
                time.sleep(POLL_SECONDS)
                continue
            run_job(db, job)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MovAI job runner")
    parser.add_argument("--once", action="store_true", help="exit when the queue is empty")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run(once=args.once)
