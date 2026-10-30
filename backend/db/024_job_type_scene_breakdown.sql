-- ALTER TYPE ... ADD VALUE cannot run inside a transaction block on PostgreSQL 13,
-- so keep this statement in its own file and apply it with autocommit (psql -f does).
ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'scene_breakdown';
