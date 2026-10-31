-- Video clips per shot are ordinary generation_requests (kind 'video_clip', target shot). This adds the episode-level
-- controls (retry budget, cost cap, pause switch) and the assembled renders (animatic, draft, final export).

CREATE TABLE IF NOT EXISTS generation_budgets (
    episode_id UUID PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    max_retries_per_shot INTEGER NOT NULL DEFAULT 3 CHECK (max_retries_per_shot >= 0),
    max_cost NUMERIC(12, 4) CHECK (max_cost IS NULL OR max_cost >= 0),
    paused BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS episode_renders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    episode_id UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('animatic', 'draft', 'final')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    subtitle_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    duration_seconds NUMERIC(10, 2),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_episode_renders_episode ON episode_renders (episode_id, kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_generation_requests_target ON generation_requests (kind, target_id);
