-- Allows story ingestion and analysis before seasons are created.

BEGIN;

ALTER TABLE story_sources
    ADD COLUMN IF NOT EXISTS series_id UUID REFERENCES series(id) ON DELETE CASCADE;

ALTER TABLE master_scripts
    ADD COLUMN IF NOT EXISTS series_id UUID REFERENCES series(id) ON DELETE CASCADE;

UPDATE story_sources ss
SET series_id = se.series_id
FROM seasons se
WHERE ss.season_id = se.id
  AND ss.series_id IS NULL;

UPDATE master_scripts ms
SET series_id = se.series_id
FROM seasons se
WHERE ms.season_id = se.id
  AND ms.series_id IS NULL;

ALTER TABLE story_sources ALTER COLUMN season_id DROP NOT NULL;
ALTER TABLE master_scripts ALTER COLUMN season_id DROP NOT NULL;

ALTER TABLE continuity_assignments
    ADD COLUMN IF NOT EXISTS series_id UUID REFERENCES series(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS season_id UUID REFERENCES seasons(id) ON DELETE CASCADE;

UPDATE continuity_assignments ca
SET
    season_id = e.season_id,
    series_id = e.series_id
FROM episodes e
WHERE ca.episode_id = e.id
  AND (ca.season_id IS NULL OR ca.series_id IS NULL);

CREATE INDEX IF NOT EXISTS idx_story_sources_series_id ON story_sources(series_id);
CREATE INDEX IF NOT EXISTS idx_master_scripts_series_id ON master_scripts(series_id);
CREATE INDEX IF NOT EXISTS idx_continuity_assignments_series ON continuity_assignments(series_id, season_id);

COMMIT;
