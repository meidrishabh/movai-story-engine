from dataclasses import dataclass
from typing import Protocol

from app.providers.media_base import GeneratedMedia, ReferenceImage


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    negative_prompt: str = ""
    references: tuple[ReferenceImage, ...] = ()
    aspect_ratio: str = "16:9"
    width: int | None = None  # a provider picks its own size when these are None
    height: int | None = None
    seed: int | None = None


class ImageProvider(Protocol):
    def generate(self, request: ImageRequest) -> GeneratedMedia:
        """One image. Raise MediaProviderError for a retryable failure, PermanentJobError for one retrying will not fix."""
