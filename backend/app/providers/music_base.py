from dataclasses import dataclass
from typing import Protocol

from app.providers.media_base import GeneratedMedia


@dataclass(frozen=True)
class MusicRequest:
    prompt: str  # mood, instruments, pace; or the effect for kind="sfx" ("heavy door slam, echo")
    duration_seconds: float = 30.0
    kind: str = "music"  # "music" (a cue or theme), "sfx" (a sound effect) or "ambience"
    seed: int | None = None


class MusicProvider(Protocol):
    def generate(self, request: MusicRequest) -> GeneratedMedia:
        """Music or a sound effect. Same error rules as ImageProvider."""
