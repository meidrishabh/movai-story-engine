from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.embedding_repository import EmbeddingRepository
from app.services.embedding_service import EmbeddingService


class ContextRetrievalService:
    def __init__(self, repository: EmbeddingRepository | None = None):
        self.repository = repository or EmbeddingRepository()

    def retrieve(
        self,
        db: Session,
        source_id: UUID,
        query: str,
        limit: int = 8,
        include_neighbors: bool = True,
    ) -> dict:
        query_embedding = EmbeddingService().embed(query)
        query_vector = vector_literal(query_embedding.vector)
        matches = self.repository.search_similar_chunks(
            db, source_id, query_vector, limit,
            embedding_model=query_embedding.model,
            embedding_version=query_embedding.version,
        )
        positions = [int(row["narrative_position"]) for row in matches]
        neighbors = (
            self.repository.get_neighbor_chunks(db, source_id, positions)
            if include_neighbors
            else []
        )
        matched_ids = {str(row["id"]) for row in matches}
        context = []
        seen = set()
        for row in sorted(neighbors, key=lambda item: item["narrative_position"]):
            key = str(row["id"])
            if key in seen:
                continue
            seen.add(key)
            context.append({
                "chunk_id": key,
                "narrative_position": row["narrative_position"],
                "chapter_title": row.get("chapter_title"),
                "page_start": row.get("page_start"),
                "page_end": row.get("page_end"),
                "text": row["content_text"],
                "is_direct_match": key in matched_ids,
            })
        return {
            "query": query,
            "direct_matches": len(matches),
            "context_chunks": context,
        }


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"
