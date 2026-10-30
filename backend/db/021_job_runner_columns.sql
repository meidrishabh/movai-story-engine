ALTER TABLE generation_jobs
    ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS run_after TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_generation_jobs_claim
    ON generation_jobs (created_at)
    WHERE status = 'queued';
