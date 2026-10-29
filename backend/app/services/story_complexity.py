from collections import Counter
import re


TIME_MARKERS = re.compile(
    r"\b(yesterday|today|tomorrow|years? later|years? earlier|flashback|present day|in the future|in the past|before|after)\b",
    re.IGNORECASE,
)
WORLD_MARKERS = re.compile(
    r"\b(another world|alternate universe|parallel world|dimension|timeline|realm|planet|galaxy|future|past)\b",
    re.IGNORECASE,
)


def analyze_story_complexity(raw_text: str) -> dict:
    words = re.findall(r"\S+", raw_text)
    paragraphs = [part for part in re.split(r"\n\s*\n", raw_text) if part.strip()]
    headings = re.findall(r"^#{1,6}\s+.+$|^(?:chapter|prologue|epilogue)\b.*$", raw_text, re.IGNORECASE | re.MULTILINE)
    dialogue_lines = re.findall(r'(?m)^[A-Z][A-Z0-9 _-]{1,40}:\s+.+$', raw_text)
    time_matches = TIME_MARKERS.findall(raw_text)
    world_matches = WORLD_MARKERS.findall(raw_text)

    signals = 0
    if len(words) > 20000:
        signals += 1
    if len(headings) > 12:
        signals += 1
    if len(set(match.lower() for match in time_matches)) >= 3:
        signals += 1
    if len(world_matches) >= 5:
        signals += 1
    if len(dialogue_lines) > 100:
        signals += 1

    profile = "standard"
    if len(set(match.lower() for match in time_matches)) >= 3:
        profile = "temporal"
    elif len(world_matches) >= 5:
        profile = "multi_world"
    elif signals >= 3:
        profile = "complex"

    signal_names = [
        name for name, enabled in [
            ("long_story", len(words) > 20000),
            ("many_sections", len(headings) > 12),
            ("temporal_markers", len(set(match.lower() for match in time_matches)) >= 3),
            ("world_markers", len(world_matches) >= 5),
            ("dialogue_heavy", len(dialogue_lines) > 100),
        ] if enabled
    ]

    return {
        "profile": profile,
        "complexity": "high" if signals >= 3 else "medium" if signals >= 1 else "low",
        "word_count": len(words),
        "paragraph_count": len(paragraphs),
        "heading_count": len(headings),
        "dialogue_line_count": len(dialogue_lines),
        "timeline_marker_count": len(time_matches),
        "world_marker_count": len(world_matches),
        "signals": dict(Counter(signal_names)),
    }
