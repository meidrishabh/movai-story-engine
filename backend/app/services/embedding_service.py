import os

from app.providers.embedding_base import EmbeddingProvider, EmbeddingResult
from app.providers.embedding_mock import MockEmbeddingProvider
from app.providers.embedding_mock import MockEmbeddingProvider


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider | None = None):
        self.provider = provider or self._configured_provider()

    @staticmethod
    def _configured_provider() -> EmbeddingProvider:
        provider_name = os.getenv("EMBEDDING_PROVIDER", "mock").lower()
        if provider_name == "local":
            from app.providers.embedding_local import LocalSentenceTransformerProvider

            model_name = os.getenv(
                "EMBEDDING_MODEL",
                "sentence-transformers/all-MiniLM-L6-v2",
            )
            return LocalSentenceTransformerProvider(model_name)
        return MockEmbeddingProvider()

    def embed(self, text: str) -> EmbeddingResult:
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        return self.provider.embed(text)

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        if any(not text.strip() for text in texts):
            raise ValueError("Cannot embed an empty text value")
        return self.provider.embed_batch(texts)
