-- Partial generation: the user works with only the characters/places/objects they need and only a few scenes.
-- Nothing here is required: a series with no scope row and an episode with no working-scenes row means "everything".

-- Which reference targets are in scope. `limited = false` (the default) means every character, costume, place and object.
CREATE TABLE IF NOT EXISTS series_reference_scope (
    series_id UUID PRIMARY KEY REFERENCES series(id) ON DELETE CASCADE,
    limited BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- entity_id is a characters.id, costumes.id, locations.id or continuity_objects.id, by entity_kind.
CREATE TABLE IF NOT EXISTS reference_scope_items (
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    entity_kind TEXT NOT NULL CHECK (entity_kind IN ('character', 'costume', 'place', 'object')),
    entity_id UUID NOT NULL,
    PRIMARY KEY (series_id, entity_kind, entity_id)
);

-- The scenes the user is working on in an episode. No row, or an empty list, means every scene.
CREATE TABLE IF NOT EXISTS episode_working_scenes (
    episode_id UUID PRIMARY KEY REFERENCES episodes(id) ON DELETE CASCADE,
    scene_ids UUID[] NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A render covers only these scenes when set (a partial episode).
ALTER TABLE episode_renders ADD COLUMN IF NOT EXISTS scene_ids UUID[];
