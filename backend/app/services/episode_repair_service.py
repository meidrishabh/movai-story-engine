"""Repair the episodes around a changed filler cut: new length and synopsis, bridge notes, stale breakdowns."""
import hashlib
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.llm_base import LLMAnalysisRequest
from app.schemas.llm_stages import EpisodeRepairResult
from app.services.adaptation_service import effective_units, latest_master_script, load_units, removed_beats, selected_main
from app.services.llm_stage import LLMStageClient

TOLERANCE_SECONDS = 5  # plan lengths are sums of unit seconds; anything beyond this is a real change


def affected_episodes(db: Session, series_id: UUID) -> list[dict]:
    """Approved episodes whose length no longer matches the units they contain under the selected cut."""
    script = latest_master_script(db, series_id)
    if script is None or selected_main(db, series_id) != "concentrated":
        return []
    seconds = {str(u["id"]): u["screen_seconds"] for u in effective_units(db, series_id, script["id"], "concentrated")}
    rows = db.execute(
        text("""SELECT id, episode_number, title, synopsis, target_duration_seconds, source_unit_ids
                FROM episodes WHERE series_id = :s ORDER BY episode_number"""), {"s": str(series_id)}).mappings().all()
    episodes = []
    for row in rows:
        now = sum(seconds.get(str(i), 0) for i in row["source_unit_ids"] or [])
        episodes.append({**row, "seconds_now": now,
                         "changed": abs(now - (row["target_duration_seconds"] or 0)) > TOLERANCE_SECONDS})
    return episodes


def repair_episodes(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, profile: str,
                    story_format: str) -> dict:
    episodes = affected_episodes(db, series_id)
    changed = [e for e in episodes if e["changed"]]
    if not changed:
        return {"repaired": 0, "stale_breakdowns": 0}
    involved = {e["episode_number"] for c in changed for e in episodes if abs(e["episode_number"] - c["episode_number"]) <= 1}

    script = latest_master_script(db, series_id)
    units = {str(u["id"]): u for u in load_units(db, script["id"])}
    omitted = {b["beat_text"] for b in removed_beats(db, series_id)}
    payload = []
    for e in episodes:
        if e["episode_number"] not in involved:
            continue
        entry = {"number": e["episode_number"], "title": e["title"], "synopsis": e["synopsis"] or "", "changed": e["changed"]}
        if e["changed"]:
            entry["units"] = [{"title": units[str(i)]["title"],
                               "kept_beats": [b for b in units[str(i)]["beats"] if b not in omitted],
                               "omitted_beats": [b for b in units[str(i)]["beats"] if b in omitted]}
                              for i in e["source_unit_ids"] if str(i) in units]
        payload.append(entry)

    request = LLMAnalysisRequest(task="episode_repair", profile=profile, context_chunks=[], known_entities={},
                                 story_format=story_format, task_input={"episodes": payload})
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:12]  # same input, same stored reply
    result: EpisodeRepairResult = client.run(db, run_id, "episode_repair", f"repair:{digest}", request, EpisodeRepairResult)

    by_number = {r.number: r for r in result.episodes}
    stale = 0
    for e in episodes:
        if e["episode_number"] not in involved:
            continue
        reply = by_number.get(e["episode_number"])
        notes = {"opening": reply.opening_note if reply else None, "closing": reply.closing_note if reply else None}
        synopsis = reply.synopsis if reply and e["changed"] and reply.synopsis else e["synopsis"]
        has_scenes = db.execute(text("SELECT EXISTS (SELECT 1 FROM scenes WHERE episode_id = :e)"),
                                {"e": str(e["id"])}).scalar()
        db.execute(
            text("""UPDATE episodes SET synopsis = :syn, target_duration_seconds = :secs,
                        continuity_notes = CAST(:notes AS jsonb), breakdown_stale = breakdown_stale OR :stale,
                        updated_at = now() WHERE id = :id"""),
            {"id": str(e["id"]), "syn": synopsis, "notes": json.dumps(notes),
             "secs": e["seconds_now"] if e["changed"] else e["target_duration_seconds"],
             "stale": bool(e["changed"] and has_scenes)})
        stale += int(bool(e["changed"] and has_scenes))
    db.commit()
    return {"repaired": len(changed), "episodes_refreshed": len(involved), "stale_breakdowns": stale}
