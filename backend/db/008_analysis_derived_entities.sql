-- Makes characters, episodes, costumes, and continuity objects analysis-driven.

BEGIN;

ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS origin TEXT NOT NULL DEFAULT 'extracted',
    ADD COLUMN IF NOT EXISTS source_unit_ids UUID[] NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS extraction_confidence NUMERIC(5, 4),
    ADD COLUMN IF NOT EXISTS analysis_status TEXT NOT NULL DEFAULT 'extracted';

ALTER TABLE episodes
    ADD COLUMN IF NOT EXISTS generation_job_id UUID REFERENCES generation_jobs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS generation_source TEXT NOT NULL DEFAULT 'episode_segmentation',
    ADD COLUMN IF NOT EXISTS generated_by_job BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS costumes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id UUID NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    color_palette JSONB NOT NULL DEFAULT '[]'::jsonb,
    accessories JSONB NOT NULL DEFAULT '[]'::jsonb,
    state_notes TEXT,
    source_unit_ids UUID[] NOT NULL DEFAULT '{}',
    approval_status approval_status NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS continuity_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    distinctive_features TEXT,
    state_notes TEXT,
    source_unit_ids UUID[] NOT NULL DEFAULT '{}',
    approval_status approval_status NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, object_type, name)
);

CREATE TABLE IF NOT EXISTS continuity_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type TEXT NOT NULL CHECK (entity_type IN ('character', 'costume', 'continuity_object')),
    entity_id UUID NOT NULL,
    episode_id UUID REFERENCES episodes(id) ON DELETE CASCADE,
    scene_id UUID REFERENCES scenes(id) ON DELETE CASCADE,
    story_unit_id UUID REFERENCES story_units(id) ON DELETE CASCADE,
    state TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_costumes_character_id ON costumes(character_id);
CREATE INDEX IF NOT EXISTS idx_continuity_objects_series_id ON continuity_objects(series_id);
CREATE INDEX IF NOT EXISTS idx_continuity_assignments_entity ON continuity_assignments(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_continuity_assignments_episode ON continuity_assignments(episode_id);
CREATE INDEX IF NOT EXISTS idx_episodes_generation_job_id ON episodes(generation_job_id);

CREATE TRIGGER costumes_set_updated_at
BEFORE UPDATE ON costumes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER continuity_objects_set_updated_at
BEFORE UPDATE ON continuity_objects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
