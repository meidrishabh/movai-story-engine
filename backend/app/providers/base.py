from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class GenerationRequest:
    job_type: str
    prompt: str
    input_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    provider: str
    model: str
    output_metadata: dict[str, Any] = field(default_factory=dict)
    output_bytes: bytes | None = None


class StoryboardProvider(Protocol):
    def generate(self, request: GenerationRequest) -> ProviderResult:
        """Generate a storyboard result without exposing provider-specific details."""
