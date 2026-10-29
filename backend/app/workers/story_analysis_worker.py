from uuid import UUID

from sqlalchemy import text

from app.services.story_analysis_service import StoryAnalysisService


def process_entity_extraction(db, analysis_run_id: UUID):
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
    )
