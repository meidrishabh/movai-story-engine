-- Foundations for image / video / audio generation: the series style bible, stored assets and generation requests.

-- One look and feel per series. Every image prompt starts from the approved version, so the style never varies by shot.
CREATE TABLE IF NOT EXISTS style_bibles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'approved', 'superseded')),
    theme_tone TEXT,
    medium TEXT,
    art_style TEXT,
    palette TEXT,
    lighting TEXT,
    camera_language TEXT,
    negative_style TEXT,
    per_act_overrides JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    approved_at TIMESTAMPTZ,
    UNIQUE (series_id, version)
);
-- At most one live (draft or approved) bible per series; saving a new one supersedes the old.
CREATE UNIQUE INDEX IF NOT EXISTS uq_style_bibles_live ON style_bibles (series_id) WHERE status IN ('draft', 'approved');

-- `assets` already exists (empty, unused). Reuse it: storage_key is the storage path, byte_size the size.
ALTER TABLE assets ALTER COLUMN asset_type DROP NOT NULL;
ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS series_id UUID REFERENCES series(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('image', 'video', 'audio', 'subtitle', 'other')),
    ADD COLUMN IF NOT EXISTS duration_seconds NUMERIC(8, 2),
    ADD COLUMN IF NOT EXISTS width INTEGER,
    ADD COLUMN IF NOT EXISTS height INTEGER,
    ADD COLUMN IF NOT EXISTS source_request_id UUID;
CREATE INDEX IF NOT EXISTS idx_assets_series ON assets (series_id, kind);

-- One row per thing to generate. A request is blocked until every request in depends_on has succeeded.
-- review_* is the user's verdict on the result; rejecting with a note queues a new attempt (new row, same target).
CREATE TABLE IF NOT EXISTS generation_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('style_anchor', 'character_image', 'place_image', 'object_image', 'keyframe',
                                       'video_clip', 'voice_line', 'music', 'sfx', 'other')),
    media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video', 'voice', 'music')),
    target_type TEXT,
    target_id UUID,
    -- awaiting_input: a provider that needs a person or an outside system to supply the result (see attach_result).
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'blocked', 'running', 'awaiting_input', 'succeeded', 'failed', 'rejected')),
    prompt TEXT NOT NULL,
    negative_prompt TEXT,
    params JSONB NOT NULL DEFAULT '{}'::jsonb,
    reference_asset_ids UUID[] NOT NULL DEFAULT '{}',
    depends_on UUID[] NOT NULL DEFAULT '{}',
    result_asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    provider TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    previous_request_id UUID REFERENCES generation_requests(id) ON DELETE SET NULL,
    cost NUMERIC(12, 4) NOT NULL DEFAULT 0,
    error_summary TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending' CHECK (review_status IN ('pending', 'approved', 'rejected')),
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    reviewed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_generation_requests_series ON generation_requests (series_id, status);
CREATE INDEX IF NOT EXISTS idx_generation_requests_target ON generation_requests (target_type, target_id, kind);
