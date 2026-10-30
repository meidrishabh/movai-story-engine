-- How a place or an object looks, read from the story. Characters keep theirs in character_versions.
-- A user edit is saved as an approved version, which re-analysis never overwrites.
CREATE TABLE IF NOT EXISTS entity_looks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('location', 'object')),
    entity_id UUID NOT NULL,
    version_number INTEGER NOT NULL,
    description TEXT NOT NULL,
    form TEXT,
    atmosphere TEXT,
    distinctive_features TEXT,
    color_palette JSONB NOT NULL DEFAULT '[]'::jsonb,
    status approval_status NOT NULL DEFAULT 'draft',
    change_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_type, entity_id, version_number)
);
CREATE INDEX IF NOT EXISTS idx_entity_looks_series ON entity_looks (series_id, entity_type);
