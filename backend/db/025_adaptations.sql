-- Adaptation options per series: full, concentrated (filler removed), trailer, teaser.
CREATE TABLE IF NOT EXISTS adaptations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('full', 'concentrated', 'trailer', 'teaser')),
    master_script_id UUID REFERENCES master_scripts(id) ON DELETE SET NULL,
    target_seconds INTEGER CHECK (target_seconds IS NULL OR target_seconds > 0),
    duration_seconds INTEGER,
    status TEXT NOT NULL DEFAULT 'not_generated'
        CHECK (status IN ('not_generated', 'generating', 'ready', 'failed')),
    selected BOOLEAN NOT NULL DEFAULT FALSE,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, kind)
);

ALTER TABLE episode_plans ADD COLUMN IF NOT EXISTS adaptation_kind TEXT NOT NULL DEFAULT 'full';
