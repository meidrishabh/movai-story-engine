"""Title cards: text on a plain colour, rendered locally with ffmpeg, so a teaser's opening and closing cards need no
image or video provider. Colours come from the series' style bible palette text (colour words it names), else a
dark card with off-white text."""
import re
import sys
import textwrap
from pathlib import Path

from app.media.errors import FFmpegError
from app.media.ops import _ensure_parent, _silence, probe
from app.media.runner import Profile, default_profile, run

# A small table of common colour words, enough to read a palette description like "deep mahogany, brass and velvet".
NAMED_COLOURS = {
    "black": "101216", "charcoal": "22262d", "grey": "6b7078", "gray": "6b7078", "silver": "b8bcc4", "white": "f2efe6",
    "ivory": "f3ecd8", "cream": "f1e7cf", "beige": "d8c7a3", "sepia": "704214", "brown": "5a3a22", "mahogany": "4a1f14",
    "umber": "635147", "bronze": "8c6a2f", "brass": "b5893a", "gold": "c9a227", "amber": "d98e04", "orange": "d9731a",
    "rust": "9c4a1a", "red": "a31f1f", "crimson": "8c1c2b", "maroon": "5b1a22", "burgundy": "5e1624", "pink": "d88aa3",
    "purple": "4b2a6b", "violet": "5f3b86", "indigo": "2b2f6b", "navy": "14213d", "blue": "1f4e8c", "teal": "1d6f73",
    "cyan": "2aa3b5", "green": "2f6b3a", "olive": "5f6b2f", "moss": "4a5d2a", "mossy": "4a5d2a", "mint": "9bd1b5",
    "yellow": "d8c13a", "pastel": "c9d4e6", "sunset": "d9732a", "velvet": "4a1c33", "slate": "3a4350", "steel": "5c6b7a",
}


def _luminance(hex_colour: str) -> float:
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * r + 0.587 * g + 0.114 * b


def colours_from_palette(palette: str | None) -> dict:
    """{"background", "text", "accent"} as hex without '#', picked from the colour words in the palette text.
    The background is the first dark colour named, the text colour the first light one, the accent the first mid-tone."""
    words = re.findall(r"[a-z]+", (palette or "").lower())
    named = [NAMED_COLOURS[w] for w in words if w in NAMED_COLOURS]
    dark = next((c for c in named if _luminance(c) < 70), None)
    light = next((c for c in named if _luminance(c) > 170), None)
    mid = next((c for c in named if 70 <= _luminance(c) <= 170), None)
    return {"background": dark or "14161b", "text": light or "f2efe6", "accent": mid or light or "c9a227"}


def _font_file() -> str | None:
    candidates = ["C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeuib.ttf",
                  "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
                  "/System/Library/Fonts/Supplemental/Arial Bold.ttf"]
    return next((c for c in candidates if Path(c).exists()), None)


def _escape_path(path: str) -> str:
    """A path inside an ffmpeg filter argument: forward slashes, the drive colon escaped."""
    return path.replace("\\", "/").replace(":", "\\:")


def title_card_clip(text: str, out: str | Path, seconds: float, profile: Profile | None = None, *,
                    palette: str | None = None, subtitle: str | None = None) -> dict:
    """Render `text` (and an optional smaller `subtitle` line) as a card of `seconds`, with a short fade in and out and a
    silent audio track. Returns {"path", "text_drawn": bool, "colours": {...}}. If ffmpeg cannot draw text on this
    machine (no usable font), a plain colour card is made instead and `text_drawn` is False."""
    profile = profile or default_profile()
    out = _ensure_parent(out)
    colours = colours_from_palette(palette)
    seconds = max(float(seconds), 0.5)
    fade = min(0.4, seconds / 4)
    size = max(18, int(profile.height / 11))
    wrap = max(12, int(profile.width / (size * 0.62)))
    lines = [piece for part in text.strip().splitlines() for piece in (textwrap.wrap(part, wrap) or [""])] or [" "]
    has_sub = bool(subtitle and subtitle.strip())
    line_height = int(size * 1.3)
    block = len(lines) * line_height
    total = block + (int(size * 0.9) if has_sub else 0)  # title lines plus the gap and the subtitle line
    top = max(int((profile.height - total) / 2), 0)
    font = _font_file()
    font_arg = f":fontfile='{_escape_path(font)}'" if font else ""
    scratch: list[Path] = []

    def draw(line: str, y: int, colour: str, pixels: int, index: int) -> str:
        path = out.with_suffix(f".{index}.txt")
        path.write_text(line, encoding="utf-8")
        scratch.append(path)
        return (f"drawtext=textfile='{_escape_path(str(path))}':fontcolor=0x{colour}:fontsize={pixels}:"
                f"x=(w-text_w)/2:y={y}{font_arg}")

    filters = [draw(line, top + i * line_height, colours["text"], size, i) for i, line in enumerate(lines) if line.strip()]
    if has_sub:
        filters.append(draw(subtitle.strip(), top + block + int(size * 0.3), colours["accent"], max(14, int(size * 0.5)), 99))
    filters += [f"fade=t=in:st=0:d={fade:.2f}", f"fade=t=out:st={max(seconds - fade, 0):.2f}:d={fade:.2f}",
                f"format={profile.pix_fmt}"]

    def render(video_filter: str) -> None:
        args = ["-f", "lavfi", "-i", f"color=c=0x{colours['background']}:s={profile.width}x{profile.height}:r={profile.fps}"]
        args += _silence(profile) + ["-vf", video_filter, "-map", "0:v:0", "-map", "1:a:0", "-t", f"{seconds:.3f}"]
        args += profile.video_args() + profile.audio_args() + ["-shortest", str(out)]
        run(args)

    drawn = True
    try:
        render(",".join(filters))
    except FFmpegError:
        drawn = False  # no usable font or no drawtext filter on this ffmpeg: keep the timing, lose the words
        render(f"fade=t=in:st=0:d={fade:.2f},fade=t=out:st={max(seconds - fade, 0):.2f}:d={fade:.2f},format={profile.pix_fmt}")
    finally:
        for leftover in scratch:
            leftover.unlink(missing_ok=True)
    probe(out)
    return {"path": str(out), "text_drawn": drawn, "colours": colours,
            "platform_font": font or ("default" if sys.platform != "win32" else None)}
