-- Provider/model metadata for replaceable embedding implementations.

BEGIN;

ALTER TABLE story_embeddings
    ADD COLUMN IF NOT EXISTS embedding_provider TEXT,
    ADD COLUMN IF NOT EXISTS embedding_dimensions INTEGER,
    ADD COLUMN IF NOT EXISTS generation_status TEXT NOT NULL DEFAULT 'complete';

UPDATE story_embeddings
SET embedding_dimensions = 1536,
    embedding_provider = COALESCE(embedding_provider, 'mock')
WHERE embedding_dimensions IS NULL;

CREATE INDEX IF NOT EXISTS idx_story_embeddings_model
    ON story_embeddings(embedding_model, embedding_version);

COMMIT;
