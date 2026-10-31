-- Consistency check on reference images: a judge compares a new image with the approved references of the same
-- target and records how closely it matches. A low score sets drift_flag so the gallery can surface the image.
ALTER TABLE generation_requests
    ADD COLUMN IF NOT EXISTS drift_score NUMERIC(4, 3),
    ADD COLUMN IF NOT EXISTS drift_flag BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS drift_notes TEXT,
    ADD COLUMN IF NOT EXISTS drift_judge TEXT,
    ADD COLUMN IF NOT EXISTS drift_checked_at TIMESTAMPTZ;

-- The gallery lists the images of one target and picks the newest approved one per view.
CREATE INDEX IF NOT EXISTS idx_generation_requests_review ON generation_requests (series_id, kind, review_status);
CREATE INDEX IF NOT EXISTS idx_generation_requests_drift ON generation_requests (series_id) WHERE drift_flag;
