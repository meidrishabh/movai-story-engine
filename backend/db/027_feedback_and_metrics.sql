-- Decisions made by the models, the code checks and users, kept so the pipeline can learn from them.
CREATE TABLE IF NOT EXISTS feedback_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE SET NULL,
    stage TEXT NOT NULL,
    item_ref JSONB NOT NULL DEFAULT '{}'::jsonb,
    decision TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'pipeline',
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_feedback_events_series_stage ON feedback_events (series_id, stage, created_at DESC);

-- Objective numbers measured on a run (coverage, planned vs actual seconds, agreement rates).
CREATE TABLE IF NOT EXISTS stage_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    metric TEXT NOT NULL,
    value DOUBLE PRECISION NOT NULL,
    detail JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_stage_metrics_series ON stage_metrics (series_id, stage, metric, created_at DESC);
