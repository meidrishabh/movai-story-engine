"""Locating and running ffmpeg/ffprobe, plus the shared encoding profile."""
import glob
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.media.errors import FFmpegError, FFmpegNotFoundError

log = logging.getLogger("media")


@dataclass(frozen=True)
class Profile:
    """One output profile every clip is normalized to so any provider's clip stitches cleanly."""

    width: int = 1280
    height: int = 720
    fps: int = 24
    vcodec: str = "libx264"
    crf: int = 20
    preset: str = "medium"
    pix_fmt: str = "yuv420p"
    acodec: str = "aac"
    audio_rate: int = 48000
    audio_channels: int = 2
    audio_bitrate: str = "160k"

    def video_args(self) -> list[str]:
        return ["-c:v", self.vcodec, "-crf", str(self.crf), "-preset", self.preset,
                "-pix_fmt", self.pix_fmt, "-r", str(self.fps), "-movflags", "+faststart"]

    def audio_args(self) -> list[str]:
        return ["-c:a", self.acodec, "-b:a", self.audio_bitrate,
                "-ar", str(self.audio_rate), "-ac", str(self.audio_channels)]

    def key(self) -> str:
        return repr(self)


def _setting(name: str, default):
    """Read a media setting from app settings if importable (needs DATABASE_URL), else from the environment."""
    try:
        from app.core.settings import settings
        return getattr(settings, name, default)
    except Exception:  # noqa: BLE001 - settings need a database URL; media must work without one
        raw = os.environ.get(name.upper())
        if raw is None:
            return default
        return type(default)(raw) if default is not None else raw


def default_profile() -> Profile:
    return Profile(
        width=int(_setting("media_video_width", 1280)),
        height=int(_setting("media_video_height", 720)),
        fps=int(_setting("media_video_fps", 24)),
        crf=int(_setting("media_video_crf", 20)),
    )


def _winget_candidates(tool: str) -> list[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return []
    exe = f"{tool}.exe"
    found = glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "Gyan.FFmpeg*", "**", "bin", exe),
                      recursive=True)
    links = os.path.join(local, "Microsoft", "WinGet", "Links", exe)
    return sorted(found, reverse=True) + ([links] if os.path.exists(links) else [])


def find_tool(tool: str) -> str:
    """Resolve `ffmpeg` or `ffprobe`: FFMPEG_PATH setting, then PATH, then the winget install location."""
    configured = str(_setting("ffmpeg_path", "") or "")
    if configured:
        path = Path(configured)
        if path.is_dir():
            for name in (f"{tool}.exe", tool):
                if (path / name).exists():
                    return str(path / name)
        elif path.exists():
            sibling = path.parent / path.name.replace("ffmpeg", tool)
            if tool == "ffmpeg":
                return str(path)
            if sibling.exists():
                return str(sibling)
    on_path = shutil.which(tool)
    if on_path:
        return on_path
    for candidate in _winget_candidates(tool):
        if os.path.exists(candidate):
            return candidate
    raise FFmpegNotFoundError(f"{tool} not found: set FFMPEG_PATH, add it to PATH, or install ffmpeg")


def run(args: list[str], tool: str = "ffmpeg", cwd: str | None = None, timeout: int | None = None) -> str:
    """Run ffmpeg/ffprobe with `args`, log the command, raise FFmpegError on failure, return stdout."""
    command = [find_tool(tool)] + (["-hide_banner", "-loglevel", "error", "-y"] if tool == "ffmpeg" else []) + args
    seconds = timeout or int(_setting("ffmpeg_timeout_seconds", 600))
    log.info("%s", " ".join(f'"{part}"' if " " in part else part for part in command))
    try:
        done = subprocess.run(command, capture_output=True, text=True, cwd=cwd, timeout=seconds, encoding="utf-8",
                              errors="replace")
    except subprocess.TimeoutExpired as error:
        raise FFmpegError(f"{tool} timed out after {seconds}s", command) from error
    if done.returncode != 0:
        raise FFmpegError(f"{tool} failed ({done.returncode}): {done.stderr.strip()[-600:]}", command, done.stderr)
    return done.stdout
