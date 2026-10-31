"""Shared types for the image, video, voice and music providers."""
from dataclasses import dataclass, field
from typing import Any


class MediaProviderError(RuntimeError):
    """A retryable provider failure (rate limit, overload, timeout, ...). The job runner backs off and retries."""


class MediaPending(Exception):
    """The provider cannot return the result now; someone or something else will supply it later.

    The request goes to `awaiting_input` and finishes through `generation_service.attach_result`.
    """


@dataclass(frozen=True)
class ReferenceImage:
    """An image the provider should use: a character sheet, a style anchor, the keyframe a clip starts from."""
    data: bytes
    mime_type: str = "image/png"
    role: str = "reference"  # "reference", "style", "first_frame"
    asset_id: str | None = None


@dataclass(frozen=True)
class GeneratedMedia:
    data: bytes
    mime_type: str
    provider: str
    model: str
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None
    cost: float = 0.0  # in the provider's own currency units; recorded on the request, summed per episode later
    metadata: dict[str, Any] = field(default_factory=dict)


def size_for(aspect_ratio: str, long_side: int) -> tuple[int, int]:
    """Pixel size for an aspect ratio like '16:9', rounded to even numbers (video codecs need that)."""
    try:
        w, h = (float(part) for part in aspect_ratio.split(":"))
    except ValueError:
        w, h = 16.0, 9.0
    if w >= h:
        width, height = long_side, long_side * h / w
    else:
        width, height = long_side * w / h, long_side
    return int(width) // 2 * 2, int(height) // 2 * 2
