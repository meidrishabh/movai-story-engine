from dataclasses import dataclass

from app.services.embedding_service import EmbeddingService


@dataclass(frozen=True)
class EmbeddingBatchResult:
    processed: int
    failed: int
    model: str
    dimensions: int


def generate_embedding_batch(texts: list[str], service: EmbeddingService | None = None) -> tuple[list, EmbeddingBatchResult]:
    """Worker-ready batch boundary; persistence is handled by the caller/repository."""
    embedding_service = service or EmbeddingService()
    results = embedding_service.embed_batch(texts)
    metadata = EmbeddingBatchResult(
        processed=len(results),
        failed=0,
        model=results[0].model if results else "",
        dimensions=results[0].dimensions if results else 0,
    )
    return results, metadata
