import hashlib

from app.providers.embedding_base import EmbeddingResult


class MockEmbeddingProvider:
    """Deterministic provider used until a real embedding API is configured."""

    provider = "mock"
    model = "mock-embedding"
    version = "dev-v1"
    dimensions = 1536

    def embed(self, text: str) -> EmbeddingResult:
        values = []
        seed = text.encode("utf-8")
        counter = 0
        while len(values) < self.dimensions:
            digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
            for index in range(0, len(digest), 4):
                if len(values) >= self.dimensions:
                    break
                integer = int.from_bytes(digest[index:index + 4], "big")
                values.append(round((integer / 4294967295.0) * 2.0 - 1.0, 7))
            counter += 1
        return EmbeddingResult(values, self.provider, self.model, self.version, self.dimensions)

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        return [self.embed(text) for text in texts]
