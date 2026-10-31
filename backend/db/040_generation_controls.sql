-- One pause switch per series for everything the generation stages queue (images, keyframes, sound, clips).
-- Per-episode budgets stay in generation_budgets (038).
CREATE TABLE IF NOT EXISTS generation_controls (
    series_id UUID PRIMARY KEY REFERENCES series(id) ON DELETE CASCADE,
    paused BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
