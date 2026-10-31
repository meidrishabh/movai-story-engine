"""Media processing on file paths (ffmpeg): probe, normalize, trim, concat, mix, subtitles, upscale, assembly.

No database or web dependencies; callers pass paths and get paths back.
"""
from app.media.assemble import BuiltFile, EpisodeResult, assemble_episode
from app.media.errors import (ClipTooShortError, FFmpegError, FFmpegNotFoundError, InvalidMediaError, MediaError)
from app.media.ops import (MediaInfo, add_subtitles, concat, extract_frame, extract_last_frame, mix_audio, normalize,
                           probe, to_srt, trim, upscale)
from app.media.runner import Profile, default_profile, find_tool

__all__ = [
    "BuiltFile", "ClipTooShortError", "EpisodeResult", "FFmpegError", "FFmpegNotFoundError", "InvalidMediaError",
    "MediaError", "MediaInfo", "Profile", "add_subtitles", "assemble_episode", "concat", "default_profile",
    "extract_frame", "extract_last_frame", "find_tool", "mix_audio", "normalize", "probe", "to_srt", "trim", "upscale",
]
