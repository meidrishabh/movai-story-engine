from dataclasses import dataclass
from typing import Protocol

from app.providers.media_base import GeneratedMedia, ReferenceImage


@dataclass(frozen=True)
class VideoRequest:
    prompt: str  # the motion and camera description; the look comes from first_frame
    negative_prompt: str = ""
    first_frame: ReferenceImage | None = None  # image-to-video when set, text-to-video when None
    references: tuple[ReferenceImage, ...] = ()
    duration_seconds: float = 5.0  # what the shot needs; a provider may return a longer clip that is trimmed later
    aspect_ratio: str = "16:9"
    width: int | None = None
    height: int | None = None
    fps: int = 24
    sound_prompt: str = ""  # mood of the sound the clip should carry, when the provider makes sound
    seed: int | None = None


class VideoProvider(Protocol):
    def generate(self, request: VideoRequest) -> GeneratedMedia:
        """One clip. Same error rules as ImageProvider."""
