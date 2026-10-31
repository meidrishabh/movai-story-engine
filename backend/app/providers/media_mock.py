"""Offline stand-ins for the media providers: valid placeholder files, no network, no cost.

They exist so the whole pipeline (requests, storage, review, stitching) runs without a paid service. The colour of an
image or the pitch of a tone comes from a hash of the prompt, so different prompts are easy to tell apart.
"""
import array
import hashlib
import io
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
import zlib
from pathlib import Path

from app.providers.image_base import ImageRequest
from app.providers.media_base import GeneratedMedia, MediaProviderError, size_for
from app.providers.music_base import MusicRequest
from app.providers.video_base import VideoRequest
from app.providers.voice_base import VoiceRequest

MOCK_IMAGE_LONG_SIDE = 640
MOCK_SAMPLE_RATE = 16000


def _digest(text: str) -> bytes:
    return hashlib.sha256(text.encode("utf-8")).digest()


def _png(width: int, height: int, top: tuple[int, int, int], bottom: tuple[int, int, int]) -> bytes:
    """A vertical gradient PNG built with the standard library only."""
    rows = bytearray()
    for y in range(height):
        t = y / max(1, height - 1)
        pixel = bytes(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        rows += b"\x00" + pixel * width

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(rows), 6)) + chunk(b"IEND", b"")


def _colours(prompt: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    d = _digest(prompt)
    return (d[0] // 2 + 40, d[1] // 2 + 40, d[2] // 2 + 40), (d[3] // 2 + 20, d[4] // 2 + 20, d[5] // 2 + 20)


class MockImageProvider:
    name = "mock"

    def generate(self, request: ImageRequest) -> GeneratedMedia:
        width, height = (request.width, request.height) if request.width and request.height else size_for(
            request.aspect_ratio, MOCK_IMAGE_LONG_SIDE)
        width, height = min(width, 1280), min(height, 1280)
        top, bottom = _colours(request.prompt)
        return GeneratedMedia(data=_png(width, height, top, bottom), mime_type="image/png", provider=self.name,
                              model="mock-image", width=width, height=height,
                              metadata={"references": len(request.references)})


def _wav(seconds: float, frequency: float, volume: float = 0.3) -> bytes:
    samples = int(seconds * MOCK_SAMPLE_RATE)
    fade = min(samples // 4, MOCK_SAMPLE_RATE // 10) or 1
    data = array.array("h")
    for i in range(samples):
        edge = min(1.0, i / fade, (samples - i) / fade)
        data.append(int(32767 * volume * edge * math.sin(2 * math.pi * frequency * i / MOCK_SAMPLE_RATE)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(MOCK_SAMPLE_RATE)
        out.writeframes(data.tobytes())
    return buffer.getvalue()


class MockVoiceProvider:
    name = "mock"

    def generate(self, request: VoiceRequest) -> GeneratedMedia:
        words = max(1, len(request.text.split()))
        seconds = round(max(0.8, words / 2.6 / max(0.25, request.speed)), 2)  # about 155 words a minute
        frequency = 140 + _digest(request.voice or "voice")[0]
        return GeneratedMedia(data=_wav(seconds, frequency), mime_type="audio/wav", provider=self.name, model="mock-voice",
                              duration_seconds=seconds)


class MockMusicProvider:
    name = "mock"

    def generate(self, request: MusicRequest) -> GeneratedMedia:
        seconds = round(max(0.5, min(request.duration_seconds, 120.0)), 2)
        frequency = 200 + _digest(request.prompt)[0] * 2
        return GeneratedMedia(data=_wav(seconds, frequency, 0.15), mime_type="audio/wav", provider=self.name,
                              model=f"mock-{request.kind}", duration_seconds=seconds)


def find_ffmpeg() -> str | None:
    """ffmpeg on PATH, or the winget install location (a fresh install is not on the PATH of running processes)."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for candidate in sorted(Path(local, "Microsoft", "WinGet", "Packages").glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe")):
            return str(candidate)
    return None


class MockVideoProvider:
    """A real MP4 (a colour card, or the first frame held) when ffmpeg is available, else a labelled placeholder file."""
    name = "mock"

    def generate(self, request: VideoRequest) -> GeneratedMedia:
        width, height = (request.width, request.height) if request.width and request.height else size_for(
            request.aspect_ratio, 640)
        seconds = max(1.0, float(request.duration_seconds))
        ffmpeg = find_ffmpeg()
        if ffmpeg is None:
            body = b"MOVAI MOCK VIDEO PLACEHOLDER (ffmpeg not found)\n" + request.prompt.encode("utf-8")
            return GeneratedMedia(data=body, mime_type="application/x-movai-placeholder", provider=self.name,
                                  model="mock-video-placeholder", width=width, height=height, duration_seconds=seconds,
                                  metadata={"placeholder": True})
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder, "clip.mp4")
            command = [ffmpeg, "-y", "-loglevel", "error"]
            if request.first_frame is not None:
                frame = Path(folder, "first.png")
                frame.write_bytes(request.first_frame.data)
                command += ["-loop", "1", "-framerate", str(request.fps), "-i", str(frame)]
                video_filter = f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
            else:
                top = _colours(request.prompt)[0]
                command += ["-f", "lavfi", "-i", f"color=c=0x{top[0]:02x}{top[1]:02x}{top[2]:02x}:s={width}x{height}:r={request.fps}"]
                video_filter = "null"
            command += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", f"{seconds:.2f}", "-vf", video_filter,
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
            try:
                done = subprocess.run(command, capture_output=True, timeout=180)
            except subprocess.TimeoutExpired as error:
                raise MediaProviderError("ffmpeg timed out making the mock clip") from error
            if done.returncode != 0 or not out.exists():
                raise MediaProviderError("ffmpeg failed making the mock clip: " + done.stderr.decode("utf-8", "replace")[:300])
            data = out.read_bytes()
        return GeneratedMedia(data=data, mime_type="video/mp4", provider=self.name, model="mock-video", width=width,
                              height=height, duration_seconds=seconds, metadata={"fps": request.fps})
