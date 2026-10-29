import json

from app.repositories.embedding_repository import EmbeddingRepository
from app.services.embedding_service import EmbeddingService


class EmbeddingPersistenceService:
    def __init__(self, repository=None, embedding_service=None):
        self.repository = repository or EmbeddingRepository()
        self.embedding_service = embedding_service or EmbeddingService()

    def process_source_batch(self, db, source_id, batch_size: int = 100):
        chunks = self.repository.list_pending_chunks(db, source_id, batch_size)
        if not chunks:
            return {"processed": 0, "remaining": 0}
        results = self.embedding_service.embed_batch([chunk["content_text"] for chunk in chunks])
        rows = []
        for chunk, embedding in zip(chunks, results, strict=True):
            rows.append({
                "chunk_id": str(chunk["id"]),
                "embedding": "[" + ",".join(str(value) for value in embedding.vector) + "]",
                "embedding_model": embedding.model,
                "embedding_version": embedding.version,
                "embedding_provider": embedding.provider,
                "embedding_dimensions": embedding.dimensions,
                "metadata": json.dumps({"provider": embedding.provider, "dimensions": embedding.dimensions}),
            })
        self.repository.save_batch(db, rows)
        remaining = len(self.repository.list_pending_chunks(db, source_id, batch_size))
        return {"processed": len(rows), "remaining": remaining}

    def reembed_source(self, db, source_id):
        chunks = self.repository.list_chunks(db, source_id)
        if not chunks:
            return {"processed": 0, "model": self.embedding_service.embed("probe").model}
        results = self.embedding_service.embed_batch([chunk["content_text"] for chunk in chunks])
        rows = []
        for chunk, embedding in zip(chunks, results, strict=True):
            rows.append({
                "chunk_id": str(chunk["id"]),
                "embedding": "[" + ",".join(str(value) for value in embedding.vector) + "]",
                "embedding_model": embedding.model,
                "embedding_version": embedding.version,
                "embedding_provider": embedding.provider,
                "embedding_dimensions": embedding.dimensions,
                "metadata": json.dumps({"provider": embedding.provider, "dimensions": embedding.dimensions}),
            })
        self.repository.save_batch(db, rows)
        current = results[0]
        self.repository.mark_other_models_obsolete(db, source_id, current.model, current.version)
        db.commit()
        return {"processed": len(rows), "model": current.model, "dimensions": current.dimensions}
