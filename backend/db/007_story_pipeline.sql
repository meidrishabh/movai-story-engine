-- Story-first pipeline: source story -> master season script -> episodes.

BEGIN;

ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'story_analysis';
ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'episode_segmentation';

ALTER TABLE seasons
    ADD COLUMN IF NOT EXISTS target_episode_count INTEGER CHECK (target_episode_count IS NULL OR target_episode_count > 0),
    ADD COLUMN IF NOT EXISTS target_episode_duration_seconds INTEGER CHECK (target_episode_duration_seconds IS NULL OR target_episode_duration_seconds > 0),
    ADD COLUMN IF NOT EXISTS climax_strategy TEXT,
    ADD COLUMN IF NOT EXISTS story_status TEXT NOT NULL DEFAULT 'not_started';

CREATE TABLE IF NOT EXISTS story_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'pasted_text',
    original_filename TEXT,
    raw_text TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS master_scripts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    title TEXT NOT NULL,
    summary TEXT,
    full_script TEXT NOT NULL,
    analysis_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    status approval_status NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (season_id, version_number)
);

CREATE TABLE IF NOT EXISTS story_units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    master_script_id UUID NOT NULL REFERENCES master_scripts(id) ON DELETE CASCADE,
    unit_type TEXT NOT NULL CHECK (unit_type IN ('chapter', 'sequence', 'scene', 'dialogue', 'narration', 'event')),
    sequence_number INTEGER NOT NULL CHECK (sequence_number > 0),
    title TEXT,
    synopsis TEXT,
    content JSONB NOT NULL DEFAULT '{}'::jsonb,
    character_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    location_names JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_reference JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE episodes
    ADD COLUMN IF NOT EXISTS master_script_id UUID REFERENCES master_scripts(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS source_unit_ids UUID[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS climax_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_story_sources_season_id ON story_sources(season_id);
CREATE INDEX IF NOT EXISTS idx_master_scripts_season_id ON master_scripts(season_id);
CREATE INDEX IF NOT EXISTS idx_story_units_master_script_id ON story_units(master_script_id);
CREATE INDEX IF NOT EXISTS idx_episodes_master_script_id ON episodes(master_script_id);

CREATE TRIGGER story_sources_set_updated_at
BEFORE UPDATE ON story_sources
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER master_scripts_set_updated_at
BEFORE UPDATE ON master_scripts
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
