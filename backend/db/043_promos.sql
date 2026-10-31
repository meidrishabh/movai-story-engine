-- Teasers and trailers: a short cut built from shots the series already has, plus title cards, narration and music.
-- Shots in a promo reuse their existing keyframes and clips; missing ones are requested through generation_requests.

CREATE TABLE IF NOT EXISTS promos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('teaser', 'trailer')),
    title TEXT NOT NULL,
    target_duration_seconds NUMERIC(8, 2) NOT NULL CHECK (target_duration_seconds > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'planned')),
    notes TEXT,
    hook TEXT,
    music_mood TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promos_series ON promos (series_id, created_at DESC);

-- Ordered items. 'shot' points at an existing shot (trim_seconds of it, from start_offset); 'title_card' is rendered
-- locally with ffmpeg (text, seconds, style); 'narration' is a voice line laid over the item before it.
CREATE TABLE IF NOT EXISTS promo_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    promo_id UUID NOT NULL REFERENCES promos(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    item_type TEXT NOT NULL CHECK (item_type IN ('shot', 'title_card', 'narration')),
    shot_id UUID REFERENCES shots(id) ON DELETE SET NULL,
    trim_seconds NUMERIC(8, 2),
    start_offset NUMERIC(8, 2) NOT NULL DEFAULT 0,
    seconds NUMERIC(8, 2),
    text TEXT,
    style JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_promo_items_promo ON promo_items (promo_id, position);

CREATE TABLE IF NOT EXISTS promo_renders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    promo_id UUID NOT NULL REFERENCES promos(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('animatic', 'draft', 'final')),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed')),
    asset_id UUID REFERENCES assets(id) ON DELETE SET NULL,
    duration_seconds NUMERIC(10, 2),
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_promo_renders_promo ON promo_renders (promo_id, kind, created_at DESC);
