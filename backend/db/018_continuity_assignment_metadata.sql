-- Adds provenance and semantic metadata to continuity mappings.

BEGIN;

ALTER TABLE continuity_assignments
    ADD COLUMN IF NOT EXISTS assignment_type TEXT NOT NULL DEFAULT 'appears_in',
    ADD COLUMN IF NOT EXISTS confidence NUMERIC(5, 4),
    ADD COLUMN IF NOT EXISTS source_references JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_continuity_assignments_scene
    ON continuity_assignments(scene_id);

CREATE INDEX IF NOT EXISTS idx_continuity_assignments_type
    ON continuity_assignments(entity_type, assignment_type);

COMMIT;
