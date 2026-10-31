"""Single-purpose media operations on file paths: probe, normalize, trim, concat, mix, subtitles, upscale, frames."""
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

from app.media.errors import ClipTooShortError, InvalidMediaError
from app.media.runner import Profile, default_profile, run

DURATION_TOLERANCE = 0.06  # seconds a clip may fall short of the requested length before it counts as too short

Upscaler = Callable[[Path, Path, int], None]  # (src, dst, target_height) -> writes dst; hook for a model-based upscaler


@dataclass(frozen=True)
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    audio_codec: str | None
    has_audio: bool
    audio_sample_rate: int | None = None
    audio_channels: int | None = None


def _fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 0.0
    num, _, den = value.partition("/")
    try:
        return float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return 0.0


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    if not path.exists():
        raise InvalidMediaError(f"{path} does not exist")
    out = run(["-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)], tool="ffprobe")
    data = json.loads(out)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise InvalidMediaError(f"{path} has no video stream")
    duration = float(video.get("duration") or data.get("format", {}).get("duration") or 0)
    if audio is not None and not video.get("duration"):
        duration = float(data.get("format", {}).get("duration") or 0)
    return MediaInfo(
        path=str(path), duration=duration, width=int(video["width"]), height=int(video["height"]),
        fps=_fps(video.get("avg_frame_rate")) or _fps(video.get("r_frame_rate")),
        video_codec=video.get("codec_name", ""), audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        audio_sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        audio_channels=int(audio["channels"]) if audio and audio.get("channels") else None,
    )


def _ensure_parent(out: str | Path) -> Path:
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


def _video_filter(profile: Profile) -> str:
    w, h = profile.width, profile.height
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={profile.fps},format={profile.pix_fmt}")


def _silence(profile: Profile) -> list[str]:
    return ["-f", "lavfi", "-i", f"anullsrc=r={profile.audio_rate}:cl={'stereo' if profile.audio_channels == 2 else 'mono'}"]


def normalize(src: str | Path, out: str | Path, profile: Profile | None = None) -> MediaInfo:
    """Re-encode `src` to the common profile (size with letterbox, fps, codecs) with a consistent audio track.

    A clip without audio gets a silent track so every normalized clip can be concatenated or crossfaded.
    """
    profile = profile or default_profile()
    info = probe(src)
    out = _ensure_parent(out)
    layout = "stereo" if profile.audio_channels == 2 else "mono"
    args = ["-i", str(src)]
    if info.has_audio:
        args += ["-vf", _video_filter(profile), "-af", f"aresample={profile.audio_rate},aformat=channel_layouts={layout},apad",
                 "-map", "0:v:0", "-map", "0:a:0"]
    else:
        args += _silence(profile) + ["-vf", _video_filter(profile), "-map", "0:v:0", "-map", "1:a:0"]
    args += ["-t", f"{info.duration:.3f}"] + profile.video_args() + profile.audio_args() + [str(out)]
    run(args)
    return probe(out)


def trim(src: str | Path, out: str | Path, seconds: float, from_start: bool = True,
         hold_last_frame: bool = False, profile: Profile | None = None) -> MediaInfo:
    """Cut `src` to exactly `seconds`, re-encoded. A shorter clip raises ClipTooShortError unless hold_last_frame."""
    profile = profile or default_profile()
    info = probe(src)
    shortfall = seconds - info.duration
    if shortfall > DURATION_TOLERANCE and not hold_last_frame:
        raise ClipTooShortError(src, info.duration, seconds)
    out = _ensure_parent(out)
    start = 0.0 if from_start else max(0.0, info.duration - seconds)
    args = ["-ss", f"{start:.3f}", "-i", str(src)]
    vf = []
    if shortfall > DURATION_TOLERANCE:
        vf.append(f"tpad=stop_mode=clone:stop_duration={shortfall + 0.1:.3f}")
    layout = "stereo" if profile.audio_channels == 2 else "mono"
    if info.has_audio:
        args += ["-af", f"aresample={profile.audio_rate},aformat=channel_layouts={layout},apad", "-map", "0:v:0", "-map", "0:a:0"]
    else:
        args += _silence(profile) + ["-map", "0:v:0", "-map", "1:a:0"]
    if vf:
        args += ["-vf", ",".join(vf)]
    args += ["-t", f"{seconds:.3f}"] + profile.video_args() + profile.audio_args() + [str(out)]
    run(args)
    return probe(out)


def _signature(info: MediaInfo) -> tuple:
    return (info.width, info.height, round(info.fps, 2), info.video_codec, info.audio_codec, info.has_audio,
            info.audio_sample_rate, info.audio_channels)


def _concat_list_line(path: Path) -> str:
    return "file '" + str(path.resolve()).replace("\\", "/").replace("'", r"'\''") + "'"


def concat(clips: Sequence[str | Path], out: str | Path, crossfade: float = 0.0,
           profile: Profile | None = None) -> MediaInfo:
    """Join clips in order. Hard cuts when `crossfade` is 0; otherwise a video+audio crossfade between clips.

    Clips that don't already share one profile are normalized first, so mixed inputs are safe.
    """
    if not clips:
        raise InvalidMediaError("concat needs at least one clip")
    profile = profile or default_profile()
    out = _ensure_parent(out)
    infos = [probe(c) for c in clips]
    with tempfile.TemporaryDirectory(prefix="concat_", dir=out.parent) as tmp:
        tmpdir = Path(tmp)
        uniform = len({_signature(i) for i in infos}) == 1 and infos[0].has_audio
        paths = [Path(c) for c in clips]
        if len(clips) == 1:
            shutil.copyfile(paths[0], out)
            return probe(out)
        if not uniform or crossfade > 0:
            normalized = []
            for index, clip in enumerate(paths):
                target = tmpdir / f"n{index}.mp4"
                normalize(clip, target, profile)
                normalized.append(target)
            paths = normalized
            infos = [probe(p) for p in paths]
        if crossfade <= 0:
            listing = tmpdir / "list.txt"
            listing.write_text("\n".join(_concat_list_line(p) for p in paths), encoding="utf-8")
            run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)])
            return probe(out)
        for info in infos:
            if info.duration <= crossfade * 2:
                raise InvalidMediaError(f"{info.path} ({info.duration:.2f}s) is too short for a {crossfade}s crossfade")
        args: list[str] = []
        for p in paths:
            args += ["-i", str(p)]
        vf, af = [], []
        v_prev, a_prev = "[0:v]", "[0:a]"
        running = infos[0].duration
        for i in range(1, len(paths)):
            v_out, a_out = f"[v{i}]", f"[a{i}]"
            vf.append(f"{v_prev}[{i}:v]xfade=transition=fade:duration={crossfade}:offset={running - crossfade:.3f}{v_out}")
            af.append(f"{a_prev}[{i}:a]acrossfade=d={crossfade}{a_out}")
            v_prev, a_prev = v_out, a_out
            running += infos[i].duration - crossfade
        args += ["-filter_complex", ";".join(vf + af), "-map", v_prev, "-map", a_prev]
        args += profile.video_args() + profile.audio_args() + [str(out)]
        run(args)
    return probe(out)


def mix_audio(video: str | Path, tracks: Iterable[dict], out: str | Path, keep_original_audio: bool = True,
              duck_music: bool = True, profile: Profile | None = None) -> MediaInfo:
    """Layer audio tracks onto `video`.

    Each track is {path, start_seconds=0, gain=1.0, role="sfx"|"dialogue"|"music"}. With `duck_music`, music is
    compressed under dialogue. The video stream is copied; the mix is trimmed to the video length.
    """
    profile = profile or default_profile()
    tracks = list(tracks)
    info = probe(video)
    out = _ensure_parent(out)
    layout = "stereo" if profile.audio_channels == 2 else "mono"
    norm = f"aresample={profile.audio_rate},aformat=channel_layouts={layout}"
    args = ["-i", str(video), "-f", "lavfi", "-t", f"{info.duration:.3f}", "-i",
            f"anullsrc=r={profile.audio_rate}:cl={layout}"]
    filters = [f"[1:a]{norm}[base]"]
    groups: dict[str, list[str]] = {"dialogue": [], "music": [], "sfx": []}
    for index, track in enumerate(tracks):
        args += ["-i", str(track["path"])]
        role = track.get("role", "sfx")
        role = role if role in groups else "sfx"
        label = f"t{index}"
        ms = max(0, int(round(float(track.get("start_seconds", 0.0)) * 1000)))
        filters.append(f"[{index + 2}:a]{norm},adelay={ms}|{ms},volume={float(track.get('gain', 1.0))}[{label}]")
        groups[role].append(f"[{label}]")
    if keep_original_audio and info.has_audio:
        filters.append(f"[0:a]{norm}[orig]")
        groups["sfx"].append("[orig]")

    def mix(labels: list[str], name: str) -> str | None:
        if not labels:
            return None
        if len(labels) == 1:
            filters.append(f"{labels[0]}anull[{name}]")
        else:
            filters.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=longest:normalize=0[{name}]")
        return f"[{name}]"

    dialogue, music, sfx = mix(groups["dialogue"], "dia"), mix(groups["music"], "mus"), mix(groups["sfx"], "fx")
    final = ["[base]"]
    if dialogue and music and duck_music:
        filters.append(f"{dialogue}asplit=2[dia_main][dia_sc]")
        filters.append(f"{music}[dia_sc]sidechaincompress=threshold=0.04:ratio=8:attack=20:release=450[musd]")
        final += ["[dia_main]", "[musd]"]
    else:
        final += [x for x in (dialogue, music) if x]
    if sfx:
        final.append(sfx)
    filters.append(f"{''.join(final)}amix=inputs={len(final)}:duration=longest:normalize=0,alimiter=limit=0.95[mix]")
    args += ["-filter_complex", ";".join(filters), "-map", "0:v:0", "-map", "[mix]", "-c:v", "copy",
             "-c:a", profile.acodec, "-b:a", profile.audio_bitrate, "-t", f"{info.duration:.3f}",
             "-movflags", "+faststart", str(out)]
    run(args)
    return probe(out)


def _timestamp(seconds: float) -> str:
    millis = int(round(max(0.0, seconds) * 1000))
    h, rest = divmod(millis, 3_600_000)
    m, rest = divmod(rest, 60_000)
    s, ms = divmod(rest, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(segments: Iterable[dict]) -> str:
    """Segments are {start, end, text} in seconds; returns SRT text."""
    blocks = []
    ordered = sorted((s for s in segments if str(s.get("text", "")).strip()), key=lambda s: float(s["start"]))
    for number, seg in enumerate(ordered, start=1):
        blocks.append(f"{number}\n{_timestamp(float(seg['start']))} --> {_timestamp(float(seg['end']))}\n"
                      f"{str(seg['text']).strip()}\n")
    return "\n".join(blocks)


def add_subtitles(video: str | Path, subtitles: str | Path | Iterable[dict], out: str | Path, mode: str = "soft",
                  style: str = "FontName=Arial,FontSize=22,Outline=2,MarginV=36",
                  profile: Profile | None = None) -> MediaInfo:
    """Add subtitles from an SRT path or segment dicts. mode "soft" adds a selectable track; "burn" draws them in."""
    if mode not in ("soft", "burn"):
        raise ValueError("mode must be 'soft' or 'burn'")
    profile = profile or default_profile()
    out = _ensure_parent(out)
    with tempfile.TemporaryDirectory(prefix="subs_") as tmp:
        srt = Path(tmp) / "subs.srt"
        if isinstance(subtitles, (str, Path)):
            shutil.copyfile(subtitles, srt)
        else:
            srt.write_text(to_srt(subtitles), encoding="utf-8")
        video_abs = str(Path(video).resolve())
        out_abs = str(out.resolve())
        if mode == "soft":
            codec = "mov_text" if out.suffix.lower() in (".mp4", ".m4v", ".mov") else "srt"
            run(["-i", video_abs, "-i", "subs.srt", "-map", "0", "-map", "1:0", "-c", "copy", "-c:s", codec,
                 out_abs], cwd=tmp)
        else:
            run(["-i", video_abs, "-vf", f"subtitles=subs.srt:force_style='{style}'", "-map", "0:v:0", "-map", "0:a?"]
                + profile.video_args() + ["-c:a", "copy", out_abs], cwd=tmp)
    return probe(out)


def upscale(src: str | Path, out: str | Path, target_height: int = 1080, profile: Profile | None = None,
            upscaler: Upscaler | None = None) -> MediaInfo:
    """Scale to `target_height` (width follows the aspect). Pass `upscaler` to use a model instead of Lanczos."""
    profile = profile or default_profile()
    out = _ensure_parent(out)
    if upscaler is not None:
        upscaler(Path(src), out, target_height)
        return probe(out)
    run(["-i", str(src), "-vf", f"scale=-2:{target_height}:flags=lanczos,setsar=1", "-map", "0:v:0", "-map", "0:a?"]
        + profile.video_args() + ["-c:a", "copy", str(out)])
    return probe(out)


def extract_frame(video: str | Path, seconds: float, out_png: str | Path) -> Path:
    out = _ensure_parent(out_png)
    run(["-ss", f"{max(0.0, seconds):.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(out)])
    return out


def extract_last_frame(video: str | Path, out_png: str | Path) -> Path:
    """Last frame of the clip, the reference for visual continuity into the next shot."""
    out = _ensure_parent(out_png)
    run(["-sseof", "-1", "-i", str(video), "-update", "1", "-frames:v", "9999", "-q:v", "2", str(out)])
    return out
