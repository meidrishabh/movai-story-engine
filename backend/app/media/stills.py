"""A still image or a plain colour card turned into a silent clip: the animatic's building block."""
from pathlib import Path

from app.media.ops import _ensure_parent, _silence, _video_filter, probe
from app.media.runner import Profile, default_profile, run


def still_clip(image: str | Path | None, out: str | Path, seconds: float, profile: Profile | None = None) -> Path:
    """`image` shown for `seconds` as a clip in the common profile, with a silent audio track.

    With no image a dark card is used instead (a shot that has no keyframe yet), so the animatic still keeps its timing.
    """
    profile = profile or default_profile()
    out = _ensure_parent(out)
    args: list[str] = []
    if image is not None:
        args += ["-loop", "1", "-framerate", str(profile.fps), "-i", str(image)]
        video_filter = _video_filter(profile)
    else:
        args += ["-f", "lavfi", "-i", f"color=c=0x1c1f26:s={profile.width}x{profile.height}:r={profile.fps}"]
        video_filter = f"format={profile.pix_fmt}"
    args += _silence(profile) + ["-vf", video_filter, "-map", "0:v:0", "-map", "1:a:0", "-t", f"{max(seconds, 0.1):.3f}"]
    args += profile.video_args() + profile.audio_args() + ["-shortest", str(out)]
    run(args)
    probe(out)  # fail here, not later, if ffmpeg produced something unreadable
    return out
