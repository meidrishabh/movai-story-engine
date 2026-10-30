-- Entities are identified by id, not name. The same name may appear more than
-- once in a series when told apart by a disambiguation label ("father", "son").

ALTER TABLE characters
    ADD COLUMN IF NOT EXISTS disambiguation TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS merged_into_id UUID REFERENCES characters(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'auto'
        CHECK (review_status IN ('auto', 'needs_review', 'approved', 'stale')),
    ADD COLUMN IF NOT EXISTS review_note TEXT,
    ADD COLUMN IF NOT EXISTS first_seen_position INTEGER,
    ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE SET NULL;

ALTER TABLE characters DROP CONSTRAINT IF EXISTS characters_series_id_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS characters_series_name_disambiguation_key
    ON characters (series_id, name, disambiguation);

ALTER TABLE continuity_objects
    ADD COLUMN IF NOT EXISTS disambiguation TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS merged_into_id UUID REFERENCES continuity_objects(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'auto'
        CHECK (review_status IN ('auto', 'needs_review', 'approved', 'stale')),
    ADD COLUMN IF NOT EXISTS review_note TEXT,
    ADD COLUMN IF NOT EXISTS first_seen_position INTEGER,
    ADD COLUMN IF NOT EXISTS locked BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE SET NULL;

ALTER TABLE continuity_objects DROP CONSTRAINT IF EXISTS continuity_objects_series_id_object_type_name_key;
CREATE UNIQUE INDEX IF NOT EXISTS continuity_objects_series_type_name_disambiguation_key
    ON continuity_objects (series_id, object_type, name, disambiguation);

CREATE TABLE IF NOT EXISTS locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    disambiguation TEXT NOT NULL DEFAULT '',
    description TEXT,
    merged_into_id UUID REFERENCES locations(id) ON DELETE SET NULL,
    review_status TEXT NOT NULL DEFAULT 'auto'
        CHECK (review_status IN ('auto', 'needs_review', 'approved', 'stale')),
    review_note TEXT,
    first_seen_position INTEGER,
    locked BOOLEAN NOT NULL DEFAULT FALSE,
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, name, disambiguation)
);

-- Where each entity appears, with a quote checked against the source text.
CREATE TABLE IF NOT EXISTS entity_mentions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('character', 'location', 'object', 'event')),
    entity_id UUID NOT NULL,
    chunk_id UUID REFERENCES story_chunks(id) ON DELETE CASCADE,
    quote TEXT,
    confidence REAL,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions (entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_series ON entity_mentions (series_id);

CREATE TABLE IF NOT EXISTS entity_relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    analysis_run_id UUID REFERENCES analysis_runs(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    target_name TEXT NOT NULL,
    source_character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    target_character_id UUID REFERENCES characters(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    confidence REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_entity_relationships_series ON entity_relationships (series_id);

-- One stored result per LLM call: lets a failed run resume, be re-merged
-- without new LLM calls, and be audited.
CREATE TABLE IF NOT EXISTS analysis_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    analysis_run_id UUID NOT NULL REFERENCES analysis_runs(id) ON DELETE CASCADE,
    stage_name TEXT NOT NULL DEFAULT 'entity_extraction',
    batch_key TEXT NOT NULL,
    chunk_ids UUID[] NOT NULL DEFAULT '{}',
    raw_response TEXT,
    parsed JSONB NOT NULL,
    usage JSONB NOT NULL DEFAULT '{}'::jsonb,
    model TEXT,
    prompt_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (analysis_run_id, stage_name, batch_key)
);

-- Only one queued or running analysis per series.
CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_active
    ON analysis_runs (series_id) WHERE status IN ('queued', 'running');
