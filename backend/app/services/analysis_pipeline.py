"""Stages that run after entity extraction: timeline, continuity, master script, episode plan."""
import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_factory import get_llm_provider
from app.repositories.analysis_repository import list_source_chunks, update_analysis_progress
from app.services.continuity_service import build_continuity
from app.services.episode_plan_service import build_episode_plan
from app.services.llm_stage import LLMStageClient
from app.services.master_script_service import build_master_script
from app.services.story_analysis_service import detect_story_format
from app.services.timeline_service import build_timeline

log = logging.getLogger("analysis_pipeline")

# (stage name, progress when finished); extraction already brought the run to 85.
PROGRESS = {"timeline": 88, "continuity": 92, "master_script": 96, "episode_plan": 99}


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
    client = LLMStageClient(get_llm_provider())

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
    summary["master_script"] = build_master_script(db, client, run_id, series_id, source_id, snapshot, profile, story_format)
    done("master_script", summary["master_script"])
    summary["episode_plan"] = build_episode_plan(
        db, client, run_id, series_id, UUID(summary["master_script"]["master_script_id"]), profile, story_format)
    done("episode_plan", summary["episode_plan"])
    summary["llm_usage"] = client.state.usage
    return summary
