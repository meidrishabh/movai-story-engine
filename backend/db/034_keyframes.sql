-- Keyframes: one image request per shot (kind 'keyframe', target_type 'shot', target_id = the shot).
-- `checks` holds the outcome of the consistency check against the approved references, e.g.
-- {"status": "passed" | "flagged" | "skipped", "score": 0.82, "notes": "...", "checked_at": "..."}.
ALTER TABLE generation_requests ADD COLUMN IF NOT EXISTS checks JSONB NOT NULL DEFAULT '{}'::jsonb;
CREATE INDEX IF NOT EXISTS idx_generation_requests_target ON generation_requests (kind, target_id, created_at DESC);
