from app.core.settings import settings
from app.providers.embedding_base import EmbeddingProvider, EmbeddingResult
from app.providers.embedding_mock import MockEmbeddingProvider


class EmbeddingService:
    def __init__(self, provider: EmbeddingProvider | None = None):
        self.provider = provider or self._configured_provider()

    @staticmethod
    def _configured_provider() -> EmbeddingProvider:
        if settings.embedding_provider.lower() == "local":
            from app.providers.embedding_local import LocalSentenceTransformerProvider

            return LocalSentenceTransformerProvider(settings.embedding_model)
        return MockEmbeddingProvider()

    def embed(self, text: str) -> EmbeddingResult:
        if not text.strip():
            raise ValueError("Cannot embed empty text")
        return self.provider.embed(text)

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        if any(not text.strip() for text in texts):
            raise ValueError("Cannot embed an empty text value")
        return self.provider.embed_batch(texts)
