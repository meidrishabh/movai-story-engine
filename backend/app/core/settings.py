from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    embedding_provider: str = "mock"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    # "mock" or "openai_compat" (any OpenAI-style /chat/completions endpoint)
    llm_provider: str = "mock"
    llm_base_url: str = ""
    llm_model: str = ""
    # Comma-separated models tried in order when the main model keeps failing.
    llm_fallback_models: str = ""
    llm_api_key: str = ""
    llm_json_mode: bool = True
    llm_max_tokens: int = 16384
    llm_timeout_seconds: int = 120
    llm_max_attempts: int = 3
    llm_min_interval_seconds: float = 0.0
    # Hard stop on new LLM calls in one analysis run (resumed batches are free).
    llm_max_calls_per_run: int = 150

    # Words of story text sent per extraction call.
    analysis_batch_words: int = 6000

    # Comma-separated browser origins allowed to call the API (the separate UI app).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
