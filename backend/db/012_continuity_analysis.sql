-- Timeline, causal relations, character/artifact states, and review conflicts.

BEGIN;

CREATE TABLE IF NOT EXISTS timeline_anchors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    time_start TEXT,
    time_end TEXT,
    timeline_type TEXT NOT NULL DEFAULT 'primary',
    world_id TEXT NOT NULL DEFAULT 'primary',
    description TEXT,
    confidence NUMERIC(5, 4),
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (series_id, label, timeline_type, world_id)
);

CREATE TABLE IF NOT EXISTS story_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    master_script_id UUID REFERENCES master_scripts(id) ON DELETE SET NULL,
    story_unit_id UUID REFERENCES story_units(id) ON DELETE SET NULL,
    timeline_anchor_id UUID REFERENCES timeline_anchors(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    event_type TEXT,
    narrative_position INTEGER,
    chronological_position INTEGER,
    world_id TEXT NOT NULL DEFAULT 'primary',
    narrative_layer TEXT NOT NULL DEFAULT 'objective',
    confidence NUMERIC(5, 4),
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS timeline_relations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_event_id UUID NOT NULL REFERENCES story_events(id) ON DELETE CASCADE,
    to_event_id UUID NOT NULL REFERENCES story_events(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL,
    confidence NUMERIC(5, 4),
    notes TEXT,
    UNIQUE (from_event_id, to_event_id, relation_type)
);

CREATE TABLE IF NOT EXISTS character_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    character_id UUID NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
    story_event_id UUID REFERENCES story_events(id) ON DELETE CASCADE,
    timeline_anchor_id UUID REFERENCES timeline_anchors(id) ON DELETE SET NULL,
    world_id TEXT NOT NULL DEFAULT 'primary',
    age_or_stage TEXT,
    location TEXT,
    costume TEXT,
    physical_condition TEXT,
    knowledge_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    relationship_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    state_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5, 4),
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS artifact_states (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    continuity_object_id UUID NOT NULL REFERENCES continuity_objects(id) ON DELETE CASCADE,
    story_event_id UUID REFERENCES story_events(id) ON DELETE CASCADE,
    timeline_anchor_id UUID REFERENCES timeline_anchors(id) ON DELETE SET NULL,
    world_id TEXT NOT NULL DEFAULT 'primary',
    owner_character_id UUID REFERENCES characters(id) ON DELETE SET NULL,
    location TEXT,
    condition TEXT,
    state_notes TEXT,
    state_changes JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(5, 4),
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE TABLE IF NOT EXISTS world_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL,
    exceptions TEXT,
    confidence NUMERIC(5, 4),
    status TEXT NOT NULL DEFAULT 'inferred',
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (series_id, name)
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    alias TEXT NOT NULL,
    confidence NUMERIC(5, 4),
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    UNIQUE (series_id, entity_type, entity_id, alias)
);

CREATE TABLE IF NOT EXISTS continuity_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    entity_type TEXT,
    entity_id UUID,
    conflict_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    status TEXT NOT NULL DEFAULT 'open',
    source_references JSONB NOT NULL DEFAULT '[]'::jsonb,
    resolution_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_timeline_anchors_series ON timeline_anchors(series_id);
CREATE INDEX IF NOT EXISTS idx_story_events_series ON story_events(series_id, narrative_position);
CREATE INDEX IF NOT EXISTS idx_story_events_timeline ON story_events(timeline_anchor_id, chronological_position);
CREATE INDEX IF NOT EXISTS idx_timeline_relations_from ON timeline_relations(from_event_id);
CREATE INDEX IF NOT EXISTS idx_timeline_relations_to ON timeline_relations(to_event_id);
CREATE INDEX IF NOT EXISTS idx_character_states_character ON character_states(character_id, story_event_id);
CREATE INDEX IF NOT EXISTS idx_artifact_states_object ON artifact_states(continuity_object_id, story_event_id);
CREATE INDEX IF NOT EXISTS idx_world_rules_series ON world_rules(series_id);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup ON entity_aliases(series_id, entity_type, alias);
CREATE INDEX IF NOT EXISTS idx_continuity_conflicts_series ON continuity_conflicts(series_id, status);

COMMIT;
