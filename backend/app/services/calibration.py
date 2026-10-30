"""Calibrate screen-time estimates against what earlier runs of the same kind of story produced."""
from statistics import median
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

# Seeded from one book (The Time Machine, 0.14); replaced by the median of recorded runs once there are any.
DEFAULT_SECONDS_PER_WORD = 0.14
LOW, HIGH = 0.35, 3.0  # estimates may run from 0.35x to 3x the expected screen time for their source words
MAX_HISTORY = 20


def expected_seconds_per_word(db: Session, series_id: UUID, story_profile: str) -> tuple[float, int]:
    """Median seconds of screen time per source word over earlier runs of other series with the same story profile."""
    values = [row[0] for row in db.execute(
        text("""SELECT value FROM stage_metrics WHERE stage = 'master_script' AND metric = 'seconds_per_word'
                AND detail ->> 'story_profile' = :p AND series_id <> :s ORDER BY created_at DESC LIMIT :n"""),
        {"p": story_profile, "s": str(series_id), "n": MAX_HISTORY})]
    return (float(median(values)), len(values)) if values else (DEFAULT_SECONDS_PER_WORD, 0)


def unit_source_words(units: list[dict], chunk_words: dict[str, int]) -> list[tuple[int, bool]]:
    """Per unit: the words of source text behind it, and whether the unit owns that text alone.
    A chunk shared by several units is split between them, so those word counts are only rough."""
    shared: dict[str, int] = {}
    chunk_ids = [{r.get("chunk_id") for r in unit.get("source_references") or []} for unit in units]
    for ids in chunk_ids:
        for chunk_id in ids:
            shared[chunk_id] = shared.get(chunk_id, 0) + 1
    return [(round(sum(chunk_words.get(c, 0) / shared[c] for c in ids)), all(shared[c] == 1 for c in ids) and bool(ids))
            for ids in chunk_ids]


def calibrate(units: list[dict], words: list[tuple[int, bool]], expected: float) -> list[dict]:
    """Pull absurd estimates back into range and return what changed.
    A unit that owns its source text is clamped on its own. When the estimates as a whole are out of range
    (or the units share chunks, so single words counts are rough), all units are scaled together so their
    relative lengths survive."""
    changed = []
    for number, (unit, (count, exclusive)) in enumerate(zip(units, words), start=1):
        if count <= 0 or not exclusive:
            continue
        old = unit["screen_seconds"]
        new = int(min(max(old, LOW * expected * count, 5), max(HIGH * expected * count, 5)))
        if new != old:
            unit["screen_seconds"] = new
            changed.append({"unit": number, "was": old, "now": new, "source_words": count, "scope": "unit"})

    total_words = sum(count for count, _ in words)
    total = sum(u["screen_seconds"] for u in units)
    if total_words and total:
        ratio = total / total_words
        bound = HIGH * expected if ratio > HIGH * expected else LOW * expected if ratio < LOW * expected else None
        if bound is not None:
            factor = bound / ratio
            for number, unit in enumerate(units, start=1):
                old = unit["screen_seconds"]
                unit["screen_seconds"] = max(5, int(round(old * factor)))
                changed.append({"unit": number, "was": old, "now": unit["screen_seconds"],
                                "source_words": words[number - 1][0], "scope": "all"})
    return changed
