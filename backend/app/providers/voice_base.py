from dataclasses import dataclass
from typing import Protocol

from app.providers.media_base import GeneratedMedia


@dataclass(frozen=True)
class VoiceRequest:
    text: str
    voice: str = ""  # a provider voice id, or a description of the voice ("older man, low, tired")
    language: str = "en"
    style: str = ""  # delivery: "whispered", "angry", "calm"
    speed: float = 1.0
    seed: int | None = None


class VoiceProvider(Protocol):
    def generate(self, request: VoiceRequest) -> GeneratedMedia:
        """Speech for one line. The result's duration_seconds is the real audio length."""
