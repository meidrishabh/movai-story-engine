-- Versioned, reviewable outputs from story-analysis stages.

BEGIN;

CREATE TABLE IF NOT EXISTS analysis_outputs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    output_type TEXT NOT NULL,
    version_number INTEGER NOT NULL DEFAULT 1 CHECK (version_number > 0),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence NUMERIC(5, 4),
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analysis_run_id, output_type, version_number)
);

CREATE INDEX IF NOT EXISTS idx_analysis_outputs_run_type
    ON analysis_outputs(analysis_run_id, output_type, version_number DESC);

CREATE TRIGGER analysis_outputs_set_updated_at
BEFORE UPDATE ON analysis_outputs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
