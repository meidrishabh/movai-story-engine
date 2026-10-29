from app.providers.embedding_base import EmbeddingResult


class LocalSentenceTransformerProvider:
    """Local embedding adapter. The model is loaded lazily on first use."""

    provider = "sentence-transformers"

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "Local embeddings require sentence-transformers and torch to be installed"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, text: str) -> EmbeddingResult:
        model = self._load()
        vector = model.encode(text, normalize_embeddings=True).tolist()
        return EmbeddingResult(
            vector=vector,
            provider=self.provider,
            model=self.model_name,
            version="v1",
            dimensions=len(vector),
        )

    def embed_batch(self, texts: list[str]) -> list[EmbeddingResult]:
        model = self._load()
        vectors = model.encode(texts, normalize_embeddings=True)
        return [
            EmbeddingResult(
                vector=vector.tolist(),
                provider=self.provider,
                model=self.model_name,
                version="v1",
                dimensions=len(vector),
            )
            for vector in vectors
        ]
