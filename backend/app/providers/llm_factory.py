from app.core.settings import settings
from app.providers.llm_base import LLMProvider
from app.providers.llm_mock import MockLLMProvider
from app.providers.llm_openai_compat import OpenAICompatLLMProvider


def get_llm_provider() -> LLMProvider:
    name = settings.llm_provider.lower()
    if name == "mock":
        return MockLLMProvider()
    if name == "openai_compat":
        missing = [
            key
            for key, value in (
                ("LLM_BASE_URL", settings.llm_base_url),
                ("LLM_MODEL", settings.llm_model),
                ("LLM_API_KEY", settings.llm_api_key),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"LLM_PROVIDER=openai_compat requires {', '.join(missing)} in backend/.env")
        return OpenAICompatLLMProvider(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            json_mode=settings.llm_json_mode,
            max_tokens=settings.llm_max_tokens,
            timeout=settings.llm_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            min_interval=settings.llm_min_interval_seconds,
            fallback_models=[m.strip() for m in settings.llm_fallback_models.split(",") if m.strip()],
        )
    raise ValueError(f"Unknown LLM_PROVIDER '{settings.llm_provider}' (use 'mock' or 'openai_compat')")
