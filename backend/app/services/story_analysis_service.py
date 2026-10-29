import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.llm_base import LLMAnalysisRequest, LLMProvider
from app.providers.llm_mock import MockLLMProvider
from app.schemas.llm_analysis import EntityExtractionResult
from app.services.context_retrieval import ContextRetrievalService


class StoryAnalysisService:
    def __init__(self, provider: LLMProvider | None = None, retrieval=None):
        self.provider = provider or MockLLMProvider()
        self.retrieval = retrieval or ContextRetrievalService()

    def extract_entities(self, db: Session, analysis_run_id: UUID, source_id: UUID, profile: str):
        context = self.retrieval.retrieve(
            db,
            source_id,
            "Extract all important characters, locations, artifacts, events, and relationships in this story.",
            limit=12,
            include_neighbors=True,
        )
        response = self.provider.analyze(
            LLMAnalysisRequest(
                task="entity_extraction",
                profile=profile,
                context_chunks=context["context_chunks"],
                known_entities={},
            )
        )
        validated = EntityExtractionResult.model_validate(response.payload)
        payload = validated.model_dump(mode="json")
        source_references = [
            {
                "chunk_id": chunk["chunk_id"],
                "page_start": chunk.get("page_start"),
                "page_end": chunk.get("page_end"),
                "narrative_position": chunk.get("narrative_position"),
            }
            for chunk in context["context_chunks"]
        ]
        db.execute(
            text("""INSERT INTO analysis_run_stages (
                analysis_run_id, stage_name, status, progress, output_metadata, started_at, completed_at)
                VALUES (:run_id, 'entity_extraction', 'succeeded', 100, CAST(:metadata AS jsonb), now(), now())
                ON CONFLICT (analysis_run_id, stage_name) DO UPDATE SET
                    status = EXCLUDED.status, progress = EXCLUDED.progress,
                    output_metadata = EXCLUDED.output_metadata, completed_at = EXCLUDED.completed_at"""),
            {"run_id": str(analysis_run_id), "metadata": json.dumps({"provider": response.provider, "model": response.model})},
        )
        output = db.execute(
            text("""INSERT INTO analysis_outputs (
                analysis_run_id, output_type, version_number, payload, source_references, status)
                VALUES (:run_id, 'entity_extraction', 1, CAST(:payload AS jsonb), CAST(:references AS jsonb), 'succeeded')
                ON CONFLICT (analysis_run_id, output_type, version_number) DO UPDATE SET
                    payload = EXCLUDED.payload, source_references = EXCLUDED.source_references,
                    status = EXCLUDED.status, updated_at = now()
                RETURNING id, output_type, version_number, status, created_at"""),
            {"run_id": str(analysis_run_id), "payload": json.dumps(payload), "references": json.dumps(source_references)},
        ).mappings().one()
        db.execute(
            text("""UPDATE analysis_runs SET current_stage = 'entity_extraction', progress = 60,
                model_name = :model_name, prompt_version = :prompt_version WHERE id = :run_id"""),
            {"run_id": str(analysis_run_id), "model_name": response.model, "prompt_version": response.prompt_version},
        )
        db.commit()
        return dict(output)
