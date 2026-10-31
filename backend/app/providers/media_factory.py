"""Pick the image, video, voice and music provider from settings (IMAGE_PROVIDER=mock, ...).

A real provider (or the manual one) is added by putting a factory function in the matching registry below.
"""
from collections.abc import Callable

from app.core.settings import settings
from app.providers.image_base import ImageProvider
from app.providers.media_mock import MockImageProvider, MockMusicProvider, MockVideoProvider, MockVoiceProvider
from app.providers.music_base import MusicProvider
from app.providers.video_base import VideoProvider
from app.providers.voice_base import VoiceProvider

IMAGE_PROVIDERS: dict[str, Callable[[], ImageProvider]] = {"mock": MockImageProvider}
VIDEO_PROVIDERS: dict[str, Callable[[], VideoProvider]] = {"mock": MockVideoProvider}
VOICE_PROVIDERS: dict[str, Callable[[], VoiceProvider]] = {"mock": MockVoiceProvider}
MUSIC_PROVIDERS: dict[str, Callable[[], MusicProvider]] = {"mock": MockMusicProvider}


def _pick(registry: dict, name: str, setting: str):
    key = name.lower()
    if key not in registry:
        raise ValueError(f"Unknown {setting} '{name}' (available: {', '.join(sorted(registry))})")
    return registry[key]()


def get_image_provider() -> ImageProvider:
    return _pick(IMAGE_PROVIDERS, settings.image_provider, "IMAGE_PROVIDER")


def get_video_provider() -> VideoProvider:
    return _pick(VIDEO_PROVIDERS, settings.video_provider, "VIDEO_PROVIDER")


def get_voice_provider() -> VoiceProvider:
    return _pick(VOICE_PROVIDERS, settings.voice_provider, "VOICE_PROVIDER")


def get_music_provider() -> MusicProvider:
    return _pick(MUSIC_PROVIDERS, settings.music_provider, "MUSIC_PROVIDER")
