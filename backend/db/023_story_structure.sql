-- Support for timeline, master script, episode plans and scene/shot breakdown.

ALTER TABLE timeline_anchors
    ADD COLUMN IF NOT EXISTS sort_order INTEGER;

ALTER TABLE story_units
    ADD COLUMN IF NOT EXISTS estimated_seconds INTEGER;

ALTER TABLE episode_plans
    ADD COLUMN IF NOT EXISTS review_note TEXT;

CREATE TABLE IF NOT EXISTS shots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scene_id UUID NOT NULL REFERENCES scenes(id) ON DELETE CASCADE,
    shot_number INTEGER NOT NULL CHECK (shot_number > 0),
    description TEXT NOT NULL,
    camera TEXT,
    duration_seconds NUMERIC(6, 1),
    character_ids UUID[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (scene_id, shot_number)
);
