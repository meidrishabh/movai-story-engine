from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


class EmbeddingRepository:
    def list_chunks(self, db: Session, source_id: UUID):
        rows = db.execute(
            text("""SELECT id, content_text, narrative_position
                FROM story_chunks WHERE story_source_id = :source_id
                ORDER BY narrative_position"""),
            {"source_id": str(source_id)},
        ).mappings().all()
        return [dict(row) for row in rows]

    def mark_other_models_obsolete(self, db: Session, source_id: UUID, model: str, version: str):
        db.execute(
            text("""UPDATE story_embeddings se SET generation_status = 'obsolete'
                FROM story_chunks sc WHERE sc.id = se.chunk_id
                  AND sc.story_source_id = :source_id
                  AND (se.embedding_model <> :model OR se.embedding_version <> :version)"""),
            {"source_id": str(source_id), "model": model, "version": version},
        )

    def list_pending_chunks(self, db: Session, source_id: UUID, limit: int = 100):
        rows = db.execute(
            text("""SELECT sc.id, sc.content_text, sc.narrative_position
                FROM story_chunks sc LEFT JOIN story_embeddings se ON se.chunk_id = sc.id
                WHERE sc.story_source_id = :source_id AND se.id IS NULL
                ORDER BY sc.narrative_position LIMIT :limit"""),
            {"source_id": str(source_id), "limit": limit},
        ).mappings().all()
        return [dict(row) for row in rows]

    def save_batch(self, db: Session, embeddings: list[dict]):
        for item in embeddings:
            db.execute(
                text("""INSERT INTO story_embeddings (
                    chunk_id, embedding, embedding_model, embedding_version,
                    embedding_provider, embedding_dimensions, generation_status, metadata)
                    VALUES (:chunk_id, CAST(:embedding AS vector), :embedding_model, :embedding_version,
                            :embedding_provider, :embedding_dimensions, 'complete', CAST(:metadata AS jsonb))
                    ON CONFLICT (chunk_id, embedding_model, embedding_version) DO UPDATE SET
                        embedding = EXCLUDED.embedding,
                        embedding_provider = EXCLUDED.embedding_provider,
                        embedding_dimensions = EXCLUDED.embedding_dimensions,
                        generation_status = 'complete',
                        metadata = EXCLUDED.metadata"""),
                item,
            )

    def search_similar_chunks(
        self,
        db: Session,
        source_id: UUID,
        query_vector: str,
        limit: int = 8,
        embedding_model: str | None = None,
        embedding_version: str | None = None,
    ) -> list[dict]:
        rows = db.execute(
            text(
                """
                SELECT sc.id, sc.story_source_id, sc.document_id,
                       sc.narrative_position, sc.chapter_title,
                       sc.page_start, sc.page_end, sc.content_text,
                       sc.token_count, sc.metadata,
                       se.embedding_model, se.embedding_version,
                       se.embedding_dimensions,
                       se.embedding <=> CAST(:query_vector AS vector) AS distance
                FROM story_chunks sc
                JOIN story_embeddings se ON se.chunk_id = sc.id
                WHERE sc.story_source_id = :source_id
                  AND se.generation_status = 'complete'
                  AND (CAST(:embedding_model AS text) IS NULL OR se.embedding_model = CAST(:embedding_model AS text))
                  AND (CAST(:embedding_version AS text) IS NULL OR se.embedding_version = CAST(:embedding_version AS text))
                ORDER BY se.embedding <=> CAST(:query_vector AS vector)
                LIMIT :limit
                """
            ),
            {"source_id": str(source_id), "query_vector": query_vector, "limit": limit,
             "embedding_model": embedding_model, "embedding_version": embedding_version},
        ).mappings().all()
        return [dict(row) for row in rows]

    def get_neighbor_chunks(
        self,
        db: Session,
        source_id: UUID,
        positions: list[int],
        radius: int = 1,
    ) -> list[dict]:
        if not positions:
            return []
        rows = db.execute(
            text(
                """
                SELECT id, story_source_id, document_id, narrative_position,
                       chapter_title, page_start, page_end, content_text,
                       token_count, metadata
                FROM story_chunks
                WHERE story_source_id = :source_id
                  AND narrative_position BETWEEN :minimum_position AND :maximum_position
                ORDER BY narrative_position
                """
            ),
            {
                "source_id": str(source_id),
                "minimum_position": min(positions) - radius,
                "maximum_position": max(positions) + radius,
            },
        ).mappings().all()
        return [dict(row) for row in rows]
