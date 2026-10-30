from app.core.settings import settings
from app.providers.llm_base import LLMProvider
from app.providers.llm_mock import MockLLMProvider
from app.providers.llm_openai_compat import OpenAICompatLLMProvider


def _openai_compat(base_url: str, model: str, api_key: str, env_prefix: str = "LLM") -> OpenAICompatLLMProvider:
    missing = [key for key, value in ((f"{env_prefix}_BASE_URL", base_url), (f"{env_prefix}_MODEL", model),
                                      (f"{env_prefix}_API_KEY", api_key)) if not value]
    if missing:
        raise ValueError(f"LLM_PROVIDER=openai_compat requires {', '.join(missing)} in backend/.env")
    return OpenAICompatLLMProvider(
        base_url=base_url,
        model=model,
        api_key=api_key,
        json_mode=settings.llm_json_mode,
        max_tokens=settings.llm_max_tokens,
        timeout=settings.llm_timeout_seconds,
        max_attempts=settings.llm_max_attempts,
        min_interval=settings.llm_min_interval_seconds,
        fallback_models=[m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()],
    )


def get_llm_provider() -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "mock":
        return MockLLMProvider()
    if name == "openai_compat":
        return _openai_compat(settings.llm_base_url, settings.llm_model, settings.llm_api_key)
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}' (use 'mock' or 'openai_compat')")


def get_judge_provider() -> LLMProvider | None:
    """A separate provider for the filler judge, or None to use the main one."""
    if settings.llm_provider.lower() != "openai_compat":
        return None
    if not (settings.judge_llm_base_url or settings.judge_llm_model or settings.judge_llm_api_key):
        return None
    return _openai_compat(settings.judge_llm_base_url or settings.llm_base_url,
                          settings.judge_llm_model or settings.llm_model,
                          settings.judge_llm_api_key or settings.llm_api_key, env_prefix="JUDGE_LLM")
