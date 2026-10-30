from dataclasses import dataclass
from typing import Any, Protocol


class LLMProviderError(RuntimeError):
    """A retryable provider failure (rate limit, overload, bad JSON, ...)."""


class LLMTruncatedError(LLMProviderError):
    """The reply hit the output limit, so its JSON is incomplete."""


@dataclass(frozen=True)
class LLMAnalysisRequest:
    task: str
    profile: str
    context_chunks: list[dict[str, Any]]
    known_entities: dict[str, Any]
    story_so_far: str = ""
    story_format: str = "novel"


@dataclass(frozen=True)
class LLMAnalysisResponse:
    provider: str
    model: str
    prompt_version: str
    payload: dict[str, Any]
    usage_metadata: dict[str, Any]
    raw: str = ""


class LLMProvider(Protocol):
    def analyze(self, request: LLMAnalysisRequest) -> LLMAnalysisResponse:
        """Return structured JSON-compatible analysis output."""


def chunk_reference(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": chunk["chunk_id"],
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "narrative_position": chunk.get("narrative_position"),
    }
