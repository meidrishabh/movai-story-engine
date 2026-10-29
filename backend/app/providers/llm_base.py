from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMAnalysisRequest:
    task: str
    profile: str
    context_chunks: list[dict[str, Any]]
    known_entities: dict[str, Any]


@dataclass(frozen=True)
class LLMAnalysisResponse:
    provider: str
    model: str
    prompt_version: str
    payload: dict[str, Any]
    usage_metadata: dict[str, Any]


class LLMProvider(Protocol):
    def analyze(self, request: LLMAnalysisRequest) -> LLMAnalysisResponse:
        """Return structured JSON-compatible analysis output."""
