-- Stores the analysis result and the user's series-level season planning preferences.

BEGIN;

ALTER TABLE series
    ADD COLUMN IF NOT EXISTS estimated_duration_seconds INTEGER
        CHECK (estimated_duration_seconds IS NULL OR estimated_duration_seconds > 0),
    ADD COLUMN IF NOT EXISTS target_season_count INTEGER
        CHECK (target_season_count IS NULL OR target_season_count > 0),
    ADD COLUMN IF NOT EXISTS target_episode_duration_seconds INTEGER
        CHECK (target_episode_duration_seconds IS NULL OR target_episode_duration_seconds > 0);

COMMIT;
