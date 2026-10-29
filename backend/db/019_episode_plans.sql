-- Reviewable episode segmentation plans before final episodes are created.

BEGIN;

CREATE TABLE IF NOT EXISTS episode_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    season_id UUID NOT NULL REFERENCES seasons(id) ON DELETE CASCADE,
    master_script_id UUID REFERENCES master_scripts(id) ON DELETE SET NULL,
    episode_number INTEGER NOT NULL CHECK (episode_number > 0),
    title TEXT,
    synopsis TEXT,
    source_unit_ids UUID[] NOT NULL DEFAULT '{}',
    target_duration_seconds INTEGER CHECK (
        target_duration_seconds IS NULL OR target_duration_seconds > 0
    ),
    opening_hook TEXT,
    climax_notes TEXT,
    ending_notes TEXT,
    character_ids UUID[] NOT NULL DEFAULT '{}',
    continuity_object_ids UUID[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',
    generation_job_id UUID REFERENCES generation_jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (season_id, episode_number)
);

CREATE INDEX IF NOT EXISTS idx_episode_plans_season
    ON episode_plans(season_id, episode_number);

CREATE INDEX IF NOT EXISTS idx_episode_plans_job
    ON episode_plans(generation_job_id);

CREATE TRIGGER episode_plans_set_updated_at
BEFORE UPDATE ON episode_plans
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
