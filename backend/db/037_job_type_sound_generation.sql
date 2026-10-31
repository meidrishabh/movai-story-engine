-- ALTER TYPE ... ADD VALUE keeps its own file so the new value is committed before anything uses it.
ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'sound_generation';
