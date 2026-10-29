-- Tracks each stage of a story-analysis run independently.

BEGIN;

CREATE TABLE IF NOT EXISTS analysis_run_stages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    stage_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    input_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analysis_run_id, stage_name)
);

CREATE INDEX IF NOT EXISTS idx_analysis_run_stages_run
    ON analysis_run_stages(analysis_run_id, created_at);

CREATE TRIGGER analysis_run_stages_set_updated_at
BEFORE UPDATE ON analysis_run_stages
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
