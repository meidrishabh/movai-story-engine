from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class EmbeddingResult:
    vector: list[float]
    provider: str
    model: str
    version: str
    dimensions: int


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> EmbeddingResult:
        """Create one embedding vector for a text value."""

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        """Create embeddings for a batch of text values."""
