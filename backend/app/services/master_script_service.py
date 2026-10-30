"""Master script stage: ordered story units with screen-time estimates."""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.providers.llm_base import LLMAnalysisRequest
from app.repositories.analysis_repository import list_source_chunks
from app.schemas.llm_stages import MasterScriptResult
from app.services.llm_stage import LLMStageClient
from app.services.story_analysis_service import make_batches

STAGE = "master_script"
MAX_UNIT_SECONDS = 600
READING_WORDS_PER_SECOND = 3  # fallback screen time when the model gives none


def build_master_script(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, source_id: UUID,
                        snapshot: dict, profile: str, story_format: str) -> dict:
    chunks = list_source_chunks(db, source_id)
    batches = make_batches(chunks, settings.analysis_batch_words)
    characters = [e["name"] for e in snapshot["characters"]]
    locations = [e["name"] for e in snapshot["locations"]]

    units: list[dict] = []
    summary = ""
    for number, batch in enumerate(batches, start=1):
        request = LLMAnalysisRequest(
            task="master_script", profile=profile, context_chunks=batch, known_entities={},
            story_format=story_format,
            task_input={"characters": characters, "locations": locations, "previous_summary": summary,
                        "unit_count_so_far": len(units)},
        )
        result: MasterScriptResult = client.run(db, run_id, STAGE, f"{number:04d}", request, MasterScriptResult,
                                                [c["chunk_id"] for c in batch])
        summary = result.running_summary or summary
        batch_words = sum(len(c["text"].split()) for c in batch)
        for unit in result.units:
            seconds = unit.screen_seconds or max(20, batch_words // max(1, len(result.units)) // READING_WORDS_PER_SECOND)
            units.append({**unit.model_dump(), "screen_seconds": int(min(max(seconds, 5), MAX_UNIT_SECONDS))})

    if not units:  # the model returned nothing usable: fall back to one unit per chapter group
        units = [{"title": c.get("chapter_title") or f"Passage {c['narrative_position']}", "synopsis": c["text"][:240],
                  "beats": [], "characters": [], "locations": [], "setting": None,
                  "screen_seconds": max(20, len(c["text"].split()) // READING_WORDS_PER_SECOND),
                  "source_references": []} for c in chunks]

    total = sum(u["screen_seconds"] for u in units)
    version = db.execute(text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM master_scripts WHERE series_id = :s"),
                         {"s": str(series_id)}).scalar_one()
    db.execute(text("UPDATE master_scripts SET status = 'superseded' WHERE series_id = :s AND status = 'draft'"),
               {"s": str(series_id)})
    outline = "\n\n".join(
        f"{i}. {u['title']}\n{u.get('synopsis') or ''}\n" + "\n".join(f"- {b}" for b in u["beats"])
        for i, u in enumerate(units, start=1))
    script_id = db.execute(
        text("""INSERT INTO master_scripts (series_id, version_number, title, summary, full_script, analysis_metadata, status)
                VALUES (:s, :v, :title, :summary, :script, CAST(:meta AS jsonb), 'draft') RETURNING id"""),
        {"s": str(series_id), "v": version, "title": f"Master script v{version}", "summary": summary,
         "script": outline, "meta": json.dumps({"analysis_run_id": str(run_id), "units": len(units),
                                                "estimated_seconds": total})},
    ).scalar_one()
    for number, unit in enumerate(units, start=1):
        db.execute(
            text("""INSERT INTO story_units (master_script_id, unit_type, sequence_number, title, synopsis, content,
                        character_names, location_names, source_reference, estimated_seconds)
                    VALUES (:m, 'scene', :n, :title, :synopsis, CAST(:content AS jsonb), CAST(:chars AS jsonb),
                            CAST(:locs AS jsonb), CAST(:refs AS jsonb), :seconds)"""),
            {"m": str(script_id), "n": number, "title": unit["title"], "synopsis": unit.get("synopsis") or "",
             "content": json.dumps({"beats": unit["beats"], "setting": unit.get("setting")}),
             "chars": json.dumps(unit["characters"]), "locs": json.dumps(unit["locations"]),
             "refs": json.dumps(unit["source_references"]), "seconds": unit["screen_seconds"]},
        )
    db.execute(text("UPDATE series SET estimated_duration_seconds = :t WHERE id = :s"),
               {"t": total, "s": str(series_id)})
    db.commit()
    return {"master_script_id": str(script_id), "version": version, "units": len(units), "estimated_seconds": total}
