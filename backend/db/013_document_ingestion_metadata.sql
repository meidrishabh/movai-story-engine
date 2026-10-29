-- Metadata needed by the document ingestion service.

BEGIN;

ALTER TABLE source_documents
    ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS parser_name TEXT,
    ADD COLUMN IF NOT EXISTS parser_version TEXT,
    ADD COLUMN IF NOT EXISTS text_layer_detected BOOLEAN,
    ADD COLUMN IF NOT EXISTS ocr_used BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
