import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.core.settings import settings
from app.providers.llm_base import LLMAnalysisRequest, LLMProvider, LLMProviderError, LLMTruncatedError
from app.providers.llm_factory import get_llm_provider
from app.repositories.analysis_repository import (
    list_source_chunks,
    load_batches,
    save_batch,
    update_analysis_progress,
)
from app.repositories.entity_repository import save_entities
from app.schemas.llm_analysis import EntityExtractionResult
from app.services.entity_merge import EntityAccumulator

log = logging.getLogger("story_analysis")

STAGE = "entity_extraction"
RESOLUTION_STAGE = "entity_resolution"
# Progress of the whole analysis run: extraction 20-60, resolution 70, saving 85.
EXTRACTION_START, EXTRACTION_END, RESOLUTION_DONE, PERSIST_DONE = 20, 60, 70, 85

TOKENS_PER_WORD = 1.4
PROMPT_OVERHEAD_TOKENS = 1500  # instructions + known entities, per call
OUTPUT_TOKENS_PER_CALL = 1500


def make_batches(chunks: list[dict], budget_words: int) -> list[list[dict]]:
    """Group consecutive chunks up to a word budget, preferring chapter boundaries."""
    batches: list[list[dict]] = []
    current: list[dict] = []
    words = 0
    for chunk in chunks:
        size = len(chunk["text"].split())
        new_chapter = bool(current) and chunk.get("chapter_title") != current[-1].get("chapter_title")
        if current and (words + size > budget_words or (new_chapter and words >= budget_words * 0.6)):
            batches.append(current)
            current, words = [], 0
        current.append(chunk)
        words += size
    if current:
        batches.append(current)
    return batches


def detect_story_format(chunks: list[dict]) -> str:
    sample = "\n".join(chunk["text"] for chunk in chunks[:12])
    sluglines = len(re.findall(r"(?m)^\s*(?:INT\.|EXT\.|INT\./EXT\.|I/E\.)", sample))
    cues = len(re.findall(r"(?m)^\s{0,40}[A-Z][A-Z .'-]{1,30}\s*$", sample))
    return "screenplay" if sluglines >= 2 or cues >= 8 else "novel"


def estimate_analysis(chunks: list[dict], batch_words: int | None = None) -> dict:
    batches = make_batches(chunks, batch_words or settings.analysis_batch_words)
    words = sum(len(chunk["text"].split()) for chunk in chunks)
    calls = len(batches) + 1  # + resolution pass
    return {
        "chunks": len(chunks),
        "words": words,
        "batches": len(batches),
        "llm_calls": calls,
        "estimated_prompt_tokens": int(words * TOKENS_PER_WORD + calls * PROMPT_OVERHEAD_TOKENS),
        "estimated_output_tokens": calls * OUTPUT_TOKENS_PER_CALL,
        "minimum_seconds": int(calls * settings.llm_min_interval_seconds),
        "max_calls_allowed": settings.llm_max_calls_per_run,
        "within_call_limit": calls <= settings.llm_max_calls_per_run,
    }


@dataclass
class _RunState:
    calls: int = 0
    usage: dict = field(default_factory=lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    model: str | None = None
    provider: str | None = None
    prompt_version: str | None = None


class StoryAnalysisService:
    def __init__(self, provider: LLMProvider | None = None, batch_words: int | None = None):
        self.provider = provider or get_llm_provider()
        self.batch_words = max(200, batch_words or settings.analysis_batch_words)

    def extract_entities(
        self,
        db: Session,
        analysis_run_id: UUID,
        source_id: UUID,
        profile: str,
        on_progress: Callable[[], None] | None = None,
    ):
        chunks = list_source_chunks(db, source_id)
        if not chunks:
            raise PermanentJobError("Source has no chunks to analyze")
        series_id = db.execute(
            text("SELECT series_id FROM analysis_runs WHERE id = :run_id"), {"run_id": str(analysis_run_id)}
        ).scalar_one()

        story_format = detect_story_format(chunks)
        batches = make_batches(chunks, self.batch_words)
        accumulator = EntityAccumulator()
        stored = load_batches(db, analysis_run_id, STAGE)
        state = _RunState()

        for number, batch in enumerate(batches, start=1):
            self._run_batch(db, analysis_run_id, f"{number:04d}", batch, accumulator, stored, profile, story_format, state)
            progress = EXTRACTION_START + (EXTRACTION_END - EXTRACTION_START) * number // len(batches)
            update_analysis_progress(db, analysis_run_id, STAGE, progress)
            db.commit()
            if on_progress:
                on_progress()

        resolution = self._resolve(db, analysis_run_id, accumulator, state)
        update_analysis_progress(db, analysis_run_id, RESOLUTION_STAGE, RESOLUTION_DONE)
        db.commit()
        if on_progress:
            on_progress()

        accumulator.finalize()
        snapshot = accumulator.snapshot()
        saved = save_entities(db, series_id, analysis_run_id, snapshot)
        update_analysis_progress(db, analysis_run_id, "entity_persistence", PERSIST_DONE)

        source_references = [
            {"chunk_id": c["chunk_id"], "page_start": c.get("page_start"), "page_end": c.get("page_end"),
             "narrative_position": c.get("narrative_position")}
            for c in chunks
        ]
        stage_metadata = {
            "provider": state.provider, "model": state.model, "batches": len(batches), "chunks": len(chunks),
            "story_format": story_format, "new_llm_calls": state.calls, "usage": state.usage,
            "resolution": resolution, "saved": saved,
        }
        db.execute(
            text("""INSERT INTO analysis_run_stages (
                analysis_run_id, stage_name, status, progress, output_metadata, started_at, completed_at)
                VALUES (:run_id, :stage, 'succeeded', 100, CAST(:metadata AS jsonb), now(), now())
                ON CONFLICT (analysis_run_id, stage_name) DO UPDATE SET
                    status = EXCLUDED.status, progress = EXCLUDED.progress,
                    output_metadata = EXCLUDED.output_metadata, completed_at = EXCLUDED.completed_at"""),
            {"run_id": str(analysis_run_id), "stage": STAGE, "metadata": json.dumps(stage_metadata)},
        )
        output = db.execute(
            text("""INSERT INTO analysis_outputs (
                analysis_run_id, output_type, version_number, payload, source_references, status)
                VALUES (:run_id, :stage, 1, CAST(:payload AS jsonb), CAST(:references AS jsonb), 'succeeded')
                ON CONFLICT (analysis_run_id, output_type, version_number) DO UPDATE SET
                    payload = EXCLUDED.payload, source_references = EXCLUDED.source_references,
                    status = EXCLUDED.status, updated_at = now()
                RETURNING id, output_type, version_number, status, created_at"""),
            {"run_id": str(analysis_run_id), "stage": STAGE, "payload": json.dumps(snapshot, default=str),
             "references": json.dumps(source_references)},
        ).mappings().one()
        db.execute(
            text("""UPDATE analysis_runs SET current_stage = 'entity_persistence', progress = :progress,
                model_name = COALESCE(:model_name, model_name), prompt_version = COALESCE(:prompt_version, prompt_version)
                WHERE id = :run_id"""),
            {"run_id": str(analysis_run_id), "progress": PERSIST_DONE, "model_name": state.model,
             "prompt_version": state.prompt_version},
        )
        db.commit()
        return dict(output)

    # ----- one extraction call (resumable) --------------------------------

    def _run_batch(self, db, run_id, key, batch, accumulator, stored, profile, story_format, state):
        row = stored.get(key)
        if row:  # finished in an earlier attempt: replay instead of calling the model again
            accumulator.add(EntityExtractionResult.model_validate(row["parsed"]), batch)
            return
        if any(k.startswith(key + ".") for k in stored):
            self._run_halves(db, run_id, key, batch, accumulator, stored, profile, story_format, state)
            return

        request = LLMAnalysisRequest(
            task="entity_extraction", profile=profile, context_chunks=batch,
            known_entities=accumulator.known_entities(batch), story_so_far=accumulator.story_so_far,
            story_format=story_format,
        )
        try:
            response, parsed = self._call(request, state)
        except LLMTruncatedError:
            if len(batch) < 2:
                raise PermanentJobError("One passage alone produced a reply larger than the output limit")
            log.warning("Batch %s hit the output limit; splitting it", key)
            self._run_halves(db, run_id, key, batch, accumulator, stored, profile, story_format, state)
            return
        save_batch(db, run_id, STAGE, key, [c["chunk_id"] for c in batch], response)
        db.commit()
        accumulator.add(parsed, batch)

    def _run_halves(self, db, run_id, key, batch, accumulator, stored, profile, story_format, state):
        middle = len(batch) // 2
        for suffix, half in ((".1", batch[:middle]), (".2", batch[middle:])):
            self._run_batch(db, run_id, key + suffix, half, accumulator, stored, profile, story_format, state)

    def _call(self, request: LLMAnalysisRequest, state: _RunState):
        last_error: Exception | None = None
        for _ in range(2):  # one retry if the reply does not match the schema
            response = self._budgeted_analyze(request, state)
            try:
                return response, EntityExtractionResult.model_validate(response.payload)
            except ValidationError as error:
                last_error = error
        raise LLMProviderError(f"Reply did not match the schema twice: {str(last_error)[:300]}")

    def _budgeted_analyze(self, request: LLMAnalysisRequest, state: _RunState):
        if state.calls >= settings.llm_max_calls_per_run:
            raise PermanentJobError(
                f"Stopped after {state.calls} LLM calls (LLM_MAX_CALLS_PER_RUN). "
                "Finished batches are saved; raise the limit and re-run to continue."
            )
        state.calls += 1
        response = self.provider.analyze(request)
        for key in state.usage:
            state.usage[key] += int(response.usage_metadata.get(key) or 0)
        if request.task == "entity_extraction":
            state.model, state.provider, state.prompt_version = response.model, response.provider, response.prompt_version
        return response

    # ----- resolution pass -------------------------------------------------

    def _resolve(self, db, run_id, accumulator: EntityAccumulator, state: _RunState) -> dict:
        try:
            entry = load_batches(db, run_id, RESOLUTION_STAGE).get("0")
            if entry:
                groups = entry["parsed"].get("groups") or []
            else:
                inputs = accumulator.resolution_input()
                if len(inputs["characters"]) + len(inputs["locations"]) < 2:
                    return {"skipped": "fewer than two entities"}
                response = self._budgeted_analyze(
                    LLMAnalysisRequest(task="entity_resolution", profile="standard",
                                       context_chunks=[], known_entities=inputs),
                    state,
                )
                save_batch(db, run_id, RESOLUTION_STAGE, "0", [], response)
                db.commit()
                groups = response.payload.get("groups") or []
            return accumulator.apply_resolution([g for g in groups if isinstance(g, dict)])
        except (LLMProviderError, PermanentJobError) as error:
            # Resolution improves the result but is not required for it.
            note = f"Resolution pass skipped: {str(error)[:200]}"
            accumulator.notes.append(note)
            log.warning(note)
            return {"skipped": str(error)[:200]}
