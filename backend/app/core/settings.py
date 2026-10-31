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
    # Optional second provider for the filler judge; any blank value falls back to the LLM_* setting above.
    judge_llm_base_url: str = ""
    judge_llm_model: str = ""
    judge_llm_api_key: str = ""
    llm_json_mode: bool = True
    llm_max_tokens: int = 16384
    llm_timeout_seconds: int = 120
    llm_max_attempts: int = 3
    llm_min_interval_seconds: float = 0.0
    # Hard stop on new LLM calls in one analysis run (resumed batches are free).
    llm_max_calls_per_run: int = 150

    # Words of story text sent per extraction call.
    analysis_batch_words: int = 6000

    # Media processing. Blank FFMPEG_PATH = look on PATH, then the winget install location.
    # FFMPEG_PATH may be the ffmpeg executable or the folder holding ffmpeg and ffprobe.
    ffmpeg_path: str = ""
    ffmpeg_timeout_seconds: int = 600
    # Common profile every clip is normalized to before stitching.
    media_video_width: int = 1280
    media_video_height: int = 720
    media_video_fps: int = 24
    media_video_crf: int = 20
    # Low-res working profile for clip requests, the animatic and draft renders; the final export uses the profile
    # above and is then upscaled to final_export_height.
    render_working_width: int = 640
    render_working_height: int = 360
    render_working_fps: int = 24
    render_working_crf: int = 28
    final_export_height: int = 1080
    # A clip within this many seconds of the shot length counts as exact.
    clip_duration_tolerance: float = 0.15

    # Media generation. Each provider is looked up by name in app/providers/media_factory.py; "mock" writes placeholder files.
    image_provider: str = "mock"
    video_provider: str = "mock"
    voice_provider: str = "mock"
    music_provider: str = "mock"
    # Consistency judge for reference images: "mock" (colour comparison, placeholder only), "llm_vision" (an
    # OpenAI-style model that accepts images; uses JUDGE_LLM_* then LLM_*), or "none" (skip the check).
    consistency_judge: str = "mock"
    consistency_threshold: float = 0.7  # a score below this is flagged as drift
    # Where generated and uploaded files are kept; relative paths are resolved from the backend folder.
    storage_dir: str = "storage"

    # Comma-separated browser origins allowed to call the API (the separate UI app).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
