-- When a user changes the filler cut, affected episodes get a refreshed synopsis, bridge notes for their
-- neighbours, and a stale flag on any existing scene breakdown.
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS breakdown_stale BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS continuity_notes JSONB NOT NULL DEFAULT '{}'::jsonb;
