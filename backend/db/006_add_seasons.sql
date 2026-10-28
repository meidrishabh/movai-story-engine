-- Adds the user-facing Series -> Seasons -> Episodes hierarchy.

BEGIN;

CREATE TABLE IF NOT EXISTS seasons (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    series_id UUID NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL CHECK (season_number > 0),
    title TEXT,
    synopsis TEXT,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (series_id, season_number)
);

ALTER TABLE episodes
    ADD COLUMN IF NOT EXISTS season_id UUID REFERENCES seasons(id) ON DELETE CASCADE;

INSERT INTO seasons (series_id, season_number, title, synopsis)
SELECT s.id, 1, 'Season 1', 'Initial season'
FROM series s
WHERE NOT EXISTS (
    SELECT 1
    FROM seasons se
    WHERE se.series_id = s.id
      AND se.season_number = 1
);

UPDATE episodes e
SET season_id = se.id
FROM seasons se
WHERE e.series_id = se.series_id
  AND se.season_number = 1
  AND e.season_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_seasons_series_id ON seasons(series_id);
CREATE INDEX IF NOT EXISTS idx_episodes_season_id ON episodes(season_id);

CREATE TRIGGER seasons_set_updated_at
BEFORE UPDATE ON seasons
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
