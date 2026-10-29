-- Adds a dedicated job type for asynchronous story-chunk embeddings.

BEGIN;

ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'embedding_generation';

COMMIT;
