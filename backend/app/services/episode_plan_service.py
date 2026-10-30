"""Season and episode planning: split the master script into reviewable episode plans."""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest
from app.schemas.llm_stages import EpisodePlanResult
from app.services.llm_stage import LLMStageClient

STAGE = "episode_plan"
DEFAULT_EPISODE_SECONDS = 600


def _fallback_ranges(units: list[dict], target: int) -> list[tuple[int, int]]:
    ranges, start, seconds = [], units[0]["number"], 0
    for unit in units:
        seconds += unit["screen_seconds"]
        if seconds >= target:
            ranges.append((start, unit["number"]))
            start, seconds = unit["number"] + 1, 0
    if start <= units[-1]["number"]:
        ranges.append((start, units[-1]["number"]))
    return ranges


def repair_ranges(episodes: list[tuple[int, int]], first: int, last: int) -> list[tuple[int, int]] | None:
    """Make the model's ranges contiguous and complete; None when they cannot be trusted."""
    cleaned = sorted((a, b) for a, b in episodes if first <= a <= b <= last)
    if not cleaned:
        return None
    repaired, expected = [], first
    for a, b in cleaned:
        a = max(a, expected)
        if b < a:  # entirely overlapped by the previous episode
            continue
        repaired.append((a, b))
        expected = b + 1
    if not repaired:
        return None
    repaired[0] = (first, repaired[0][1])
    for index in range(1, len(repaired)):  # close gaps by extending the earlier episode
        repaired[index - 1] = (repaired[index - 1][0], repaired[index][0] - 1)
    repaired[-1] = (repaired[-1][0], last)
    return repaired


def build_episode_plan(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID,
                       master_script_id: UUID, profile: str, story_format: str) -> dict:
    rows = db.execute(
        text("""SELECT id, sequence_number, title, synopsis, character_names, estimated_seconds
                FROM story_units WHERE master_script_id = :m ORDER BY sequence_number"""),
        {"m": str(master_script_id)},
    ).mappings().all()
    if not rows:
        raise PermanentJobError("The master script has no units to plan from")
    units = [{"number": r["sequence_number"], "title": r["title"], "synopsis": (r["synopsis"] or "")[:200],
              "characters": r["character_names"], "screen_seconds": r["estimated_seconds"] or 30} for r in rows]
    unit_ids = {r["sequence_number"]: r["id"] for r in rows}
    total = sum(u["screen_seconds"] for u in units)
    target = db.execute(text("SELECT target_episode_duration_seconds FROM series WHERE id = :s"),
                        {"s": str(series_id)}).scalar_one() or DEFAULT_EPISODE_SECONDS

    request = LLMAnalysisRequest(
        task="episode_plan", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
        task_input={"units": units, "target_episode_seconds": target, "total_seconds": total,
                    "story_format": story_format},
    )
    key = str(master_script_id)
    result: EpisodePlanResult = client.run(db, run_id, STAGE, key, request, EpisodePlanResult)

    # Flatten the model's seasons and make sure the ranges cover every unit exactly once.
    flat = [(season_index, episode) for season_index, season in enumerate(result.seasons)
            for episode in season.episodes]
    first, last = units[0]["number"], units[-1]["number"]
    repaired = repair_ranges([(e.unit_from, e.unit_to) for _, e in flat], first, last)
    used_fallback = repaired is None
    if used_fallback:
        repaired = _fallback_ranges(units, target)
        flat = [(0, None)] * len(repaired)
    elif len(repaired) != len(flat):  # ranges were dropped as overlapped: re-pair by start unit
        by_start = {e.unit_from: (s, e) for s, e in flat}
        flat = [by_start.get(a, (flat[0][0], None)) for a, _ in repaired]

    # Replace plans that were never approved; approved ones became episodes and stay.
    db.execute(
        text("""DELETE FROM episode_plans WHERE status IN ('draft', 'rejected')
                AND season_id IN (SELECT id FROM seasons WHERE series_id = :s)"""), {"s": str(series_id)})
    next_number = db.execute(text("SELECT COALESCE(MAX(episode_number), 0) + 1 FROM episodes WHERE series_id = :s"),
                             {"s": str(series_id)}).scalar_one()
    season_ids: dict[int, UUID] = {}
    base_season = db.execute(text("SELECT COALESCE(MAX(season_number), 0) FROM seasons WHERE series_id = :s"),
                             {"s": str(series_id)}).scalar_one()
    plans = 0
    for (season_index, episode), (start, end) in zip(flat, repaired):
        if season_index not in season_ids:
            season = result.seasons[season_index] if result.seasons and not used_fallback else None
            number = db.execute(
                text("""SELECT season_number FROM seasons WHERE series_id = :s AND status = 'draft'
                        AND NOT EXISTS (SELECT 1 FROM episodes WHERE season_id = seasons.id)
                        ORDER BY season_number LIMIT 1"""), {"s": str(series_id)}).scalar()
            if number is None:
                base_season += 1
                number = base_season
            season_ids[season_index] = db.execute(
                text("""INSERT INTO seasons (series_id, season_number, title, synopsis)
                        VALUES (:s, :n, :title, :synopsis)
                        ON CONFLICT (series_id, season_number) DO UPDATE SET title = EXCLUDED.title,
                            synopsis = EXCLUDED.synopsis, updated_at = now() RETURNING id"""),
                {"s": str(series_id), "n": number, "title": (season.title if season else None) or f"Season {number}",
                 "synopsis": season.synopsis if season else None},
            ).scalar_one()
        covered = [u for u in units if start <= u["number"] <= end]
        names = list(dict.fromkeys(n for u in covered for n in u["characters"]))
        db.execute(
            text("""INSERT INTO episode_plans (season_id, master_script_id, episode_number, title, synopsis,
                        source_unit_ids, target_duration_seconds, opening_hook, climax_notes, ending_notes, character_ids)
                    VALUES (:season, :m, :n, :title, :synopsis, CAST(:units AS uuid[]), :seconds, :hook, :climax, :ending,
                            COALESCE((SELECT array_agg(id) FROM characters WHERE series_id = :s AND name = ANY(:names)
                                      AND merged_into_id IS NULL), '{}'))"""),
            {"season": str(season_ids[season_index]), "m": str(master_script_id), "n": next_number + plans,
             "title": (episode.title if episode else None) or f"Episode {next_number + plans}",
             "synopsis": episode.synopsis if episode else None,
             "units": "{" + ",".join(str(unit_ids[u["number"]]) for u in covered) + "}",
             "seconds": max(1, sum(u["screen_seconds"] for u in covered)),
             "hook": episode.opening_hook if episode else None, "climax": episode.climax_notes if episode else None,
             "ending": episode.ending_notes if episode else None, "s": str(series_id), "names": names},
        )
        plans += 1
    db.commit()
    return {"plans": plans, "seasons": len(season_ids), "total_seconds": total, "target_episode_seconds": target,
            "used_fallback": used_fallback}
