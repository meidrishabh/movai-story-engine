"""Exceptions raised by the media package."""


class MediaError(Exception):
    """Base class for every media failure."""


class FFmpegNotFoundError(MediaError):
    """ffmpeg/ffprobe could not be located (set FFMPEG_PATH or install ffmpeg)."""


class FFmpegError(MediaError):
    """An ffmpeg/ffprobe run exited non-zero or timed out."""

    def __init__(self, message: str, command: list[str] | None = None, stderr: str = ""):
        super().__init__(message)
        self.command = command or []
        self.stderr = stderr


class ClipTooShortError(MediaError):
    """A clip is shorter than the length the shot needs; flag it instead of padding."""

    def __init__(self, path, actual: float, required: float):
        super().__init__(f"{path} is {actual:.2f}s but {required:.2f}s is needed")
        self.path = str(path)
        self.actual = actual
        self.required = required


class InvalidMediaError(MediaError):
    """The input is missing, unreadable, or has no video stream."""
