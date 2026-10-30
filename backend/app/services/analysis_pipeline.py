"""Stages that run after entity extraction: timeline, continuity, master script, episode plan."""
import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMProviderError
from app.providers.llm_factory import get_judge_provider, get_llm_provider
from app.repositories.analysis_repository import list_source_chunks, update_analysis_progress
from app.services.adaptation_service import build_full, detect_filler
from app.services.appearance_service import build_appearance
from app.services.continuity_service import build_continuity
from app.services.episode_plan_service import build_episode_plan
from app.services.llm_stage import LLMStageClient
from app.services.master_script_service import build_master_script
from app.services.metrics import record_metric
from app.services.story_analysis_service import detect_story_format
from app.services.timeline_service import build_timeline

log = logging.getLogger("analysis_pipeline")

# (stage name, progress when finished); extraction already brought the run to 85.
PROGRESS = {"timeline": 87, "continuity": 90, "appearance": 93, "master_script": 95, "adaptations": 97, "episode_plan": 99}


def run_structure_stages(db: Session, run_id: UUID, on_progress: Callable[[], None] | None = None) -> dict:
    run = db.execute(
        text("SELECT series_id, source_id, profile FROM analysis_runs WHERE id = :r"), {"r": str(run_id)}
    ).mappings().one()
    row = db.execute(
        text("""SELECT payload FROM analysis_outputs WHERE analysis_run_id = :r AND output_type = 'entity_extraction'
                ORDER BY version_number DESC LIMIT 1"""), {"r": str(run_id)}
    ).mappings().first()
    if row is None:
        raise PermanentJobError("Entity extraction output is missing; run extraction first")
    snapshot, series_id, source_id, profile = row["payload"], run["series_id"], run["source_id"], str(run["profile"])
    story_format = detect_story_format(list_source_chunks(db, source_id))
    client = LLMStageClient(get_llm_provider(), get_judge_provider())

    def done(stage: str, result: dict) -> None:
        update_analysis_progress(db, run_id, stage, PROGRESS[stage])
        db.commit()
        log.info("%s: %s", stage, result)
        if on_progress:
            on_progress()

    summary: dict = {}
    summary["timeline"] = build_timeline(db, client, run_id, series_id, snapshot, profile, story_format)
    done("timeline", summary["timeline"])
    summary["continuity"] = build_continuity(db, client, run_id, series_id, snapshot, profile, story_format)
    done("continuity", summary["continuity"])
    try:  # reference sheets are needed for visuals later, but the story pipeline works without them
        summary["appearance"] = build_appearance(db, client, run_id, series_id, profile, story_format)
    except (LLMProviderError, PermanentJobError) as error:
        db.rollback()
        summary["appearance"] = {"skipped": str(error)[:200]}
        log.warning("Appearance analysis skipped: %s", error)
    done("appearance", summary["appearance"])
    summary["master_script"] = build_master_script(db, client, run_id, series_id, source_id, snapshot, profile, story_format)
    done("master_script", summary["master_script"])
    script_id = UUID(summary["master_script"]["master_script_id"])
    summary["adaptations"] = {"full": build_full(db, series_id, script_id)}
    try:
        summary["adaptations"]["concentrated"] = detect_filler(db, client, run_id, series_id, script_id, profile, story_format)
    except (LLMProviderError, PermanentJobError) as error:  # the concentrated option is optional; the rest still works
        db.rollback()
        summary["adaptations"]["concentrated"] = {"skipped": str(error)[:200]}
        log.warning("Filler detection skipped: %s", error)
    done("adaptations", summary["adaptations"])
    summary["episode_plan"] = build_episode_plan(db, client, run_id, series_id, script_id, profile, story_format)
    done("episode_plan", summary["episode_plan"])
    record_run_metrics(db, series_id, run_id, source_id, script_id, summary)
    summary["llm_usage"] = client.state.usage
    return summary


def record_run_metrics(db: Session, series_id: UUID, run_id: UUID, source_id, script_id: UUID, summary: dict) -> None:
    """Objective checks across stages: does the script cover the source, does the plan cover the script."""
    chunks = {c["chunk_id"] for c in list_source_chunks(db, source_id)}
    referenced = {ref.get("chunk_id") for (refs,) in db.execute(
        text("SELECT source_reference FROM story_units WHERE master_script_id = :m"), {"m": str(script_id)}) for ref in refs or []}
    if chunks:
        record_metric(db, series_id, run_id, "master_script", "chunk_coverage", len(chunks & referenced) / len(chunks),
                      {"chunks": len(chunks), "referenced": len(chunks & referenced)})
    script_seconds = (summary.get("master_script") or {}).get("estimated_seconds")
    plan_seconds = (summary.get("episode_plan") or {}).get("total_seconds")
    if script_seconds and plan_seconds:
        record_metric(db, series_id, run_id, "episode_plan", "seconds_vs_script", plan_seconds / script_seconds,
                      {"plan": plan_seconds, "script": script_seconds})
    db.commit()
