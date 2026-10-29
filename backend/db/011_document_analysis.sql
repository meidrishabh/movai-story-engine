-- Document inspection, normalized chunks, embeddings, and analysis runs.

BEGIN;

ALTER TABLE story_sources
    ADD COLUMN IF NOT EXISTS input_format TEXT,
    ADD COLUMN IF NOT EXISTS language_code TEXT,
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE series
    ADD COLUMN IF NOT EXISTS analysis_profile TEXT,
    ADD COLUMN IF NOT EXISTS analysis_complexity JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    story_source_id UUID NOT NULL REFERENCES story_sources(id) ON DELETE CASCADE,
    file_name TEXT,
    file_type TEXT NOT NULL,
    file_size_bytes BIGINT,
    page_count INTEGER,
    document_hash TEXT,
    validation_status TEXT NOT NULL DEFAULT 'pending',
    validation_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_pages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    has_text BOOLEAN NOT NULL DEFAULT FALSE,
    text_length INTEGER NOT NULL DEFAULT 0,
    image_count INTEGER NOT NULL DEFAULT 0,
    layout_type TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pending',
    extracted_text TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (document_id, page_number)
);

CREATE TABLE IF NOT EXISTS document_elements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id UUID NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    element_type TEXT NOT NULL,
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    text_content TEXT,
    asset_id UUID,
    bounding_box JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (page_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS story_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    story_source_id UUID NOT NULL REFERENCES story_sources(id) ON DELETE CASCADE,
    document_id UUID REFERENCES source_documents(id) ON DELETE SET NULL,
    chapter_title TEXT,
    page_start INTEGER,
    page_end INTEGER,
    narrative_position INTEGER NOT NULL CHECK (narrative_position > 0),
    content_text TEXT NOT NULL,
    token_count INTEGER,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (story_source_id, narrative_position)
);

CREATE TABLE IF NOT EXISTS story_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES story_chunks(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL DEFAULT 'story_chunk',
    entity_id UUID,
    embedding vector NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_version TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (chunk_id, embedding_model, embedding_version)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    source_id UUID NOT NULL REFERENCES story_sources(id) ON DELETE CASCADE,
    profile TEXT NOT NULL DEFAULT 'standard',
    status TEXT NOT NULL DEFAULT 'queued',
    current_stage TEXT,
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    model_name TEXT,
    prompt_version TEXT,
    estimated_cost NUMERIC(12, 6),
    actual_cost NUMERIC(12, 6),
    result_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_documents_source_id ON source_documents(story_source_id);
CREATE INDEX IF NOT EXISTS idx_document_pages_document_id ON document_pages(document_id, page_number);
CREATE INDEX IF NOT EXISTS idx_document_elements_page_id ON document_elements(page_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_story_chunks_source_id ON story_chunks(story_source_id, narrative_position);
CREATE INDEX IF NOT EXISTS idx_story_embeddings_chunk_id ON story_embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_story_embeddings_entity ON story_embeddings(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_series_id ON analysis_runs(series_id, created_at DESC);

CREATE TRIGGER source_documents_set_updated_at
BEFORE UPDATE ON source_documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
