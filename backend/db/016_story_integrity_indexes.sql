-- Supporting indexes and integrity metadata for series-level story processing.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_story_sources_series_created
    ON story_sources(series_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_master_scripts_series_version
    ON master_scripts(series_id, version_number DESC);

CREATE INDEX IF NOT EXISTS idx_story_units_master_sequence
    ON story_units(master_script_id, sequence_number);

COMMIT;
