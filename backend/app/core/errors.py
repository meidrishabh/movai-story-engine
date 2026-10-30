class PermanentJobError(RuntimeError):
    """A failure that retrying will not fix (bad API key, budget exceeded, ...)."""
