"""Continuity stage: per-event character/object states and contradictions."""
import json
from dataclasses import replace
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.llm_base import LLMAnalysisRequest
from app.repositories.analysis_repository import list_source_chunks
from app.schemas.llm_stages import ContinuityResult
from app.services.llm_stage import LLMStageClient

STAGE = "continuity"
CHECK_STAGE = "continuity_check"
WINDOW = 8  # events per model call, in chronological order; small so the model covers every event
SEVERITIES = {"info", "warning", "error", "critical"}
PASSAGE_WORDS = 2500  # source words shown with each window of events


def build_continuity(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID,
                    snapshot: dict, profile: str, story_format: str) -> dict:
    events = db.execute(
        text("""SELECT e.id, e.title, e.description, e.narrative_position, e.timeline_anchor_id, e.source_references
                FROM story_events e WHERE e.series_id = :s
                ORDER BY e.chronological_position NULLS LAST, e.narrative_position"""),
        {"s": str(series_id)},
    ).mappings().all()
    characters = {e["eid"]: e for e in snapshot["characters"] if e.get("db_id")}
    objects = {e["eid"]: e for e in snapshot["objects"] if e.get("db_id")}

    db.execute(text("DELETE FROM character_states WHERE story_event_id IN (SELECT id FROM story_events WHERE series_id = :s)"),
               {"s": str(series_id)})
    db.execute(text("DELETE FROM artifact_states WHERE story_event_id IN (SELECT id FROM story_events WHERE series_id = :s)"),
               {"s": str(series_id)})
    db.execute(text("DELETE FROM continuity_conflicts WHERE series_id = :s AND status = 'open'"), {"s": str(series_id)})
    if not events or not (characters or objects):
        db.commit()
        return {"character_states": 0, "object_states": 0, "conflicts": 0}

    by_vid = {f"V{e['narrative_position']}": e for e in events}
    people = [{"id": k, "name": v["name"], "description": (v.get("description") or "")[:160]} for k, v in characters.items()]
    things = [{"id": k, "name": v["name"], "description": (v.get("description") or "")[:160]} for k, v in objects.items()]
    last_character: dict[str, dict] = {}
    last_object: dict[str, dict] = {}
    counts = {"character_states": 0, "object_states": 0, "conflicts": 0}

    source_id = db.execute(text("SELECT source_id FROM analysis_runs WHERE id = :r"), {"r": str(run_id)}).scalar()
    chunk_text = {c["chunk_id"]: c["text"] for c in list_source_chunks(db, source_id)}

    for start in range(0, len(events), WINDOW):
        window = events[start:start + WINDOW]
        request = LLMAnalysisRequest(
            task="continuity", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={
                "events": [{"id": f"V{e['narrative_position']}", "title": e["title"],
                            "description": (e["description"] or "")[:400]} for e in window],
                "passages": _passages(window, chunk_text),
                "characters": people, "objects": things,
                "previous_states": {"characters": last_character, "objects": last_object},
            },
        )
        key = f"{start // WINDOW + 1:04d}"
        result: ContinuityResult = client.run(db, run_id, STAGE, key, request, ContinuityResult)
        # A separate call looks for contradictions: asking one call to extract states and hunt for conflicts
        # made the model report only the first thing it noticed.
        check_input = {**request.task_input,
                       "states": {"characters": [s.model_dump(exclude_none=True) for s in result.character_states],
                                  "objects": [s.model_dump(exclude_none=True) for s in result.object_states]}}
        check: ContinuityResult = client.run(
            db, run_id, CHECK_STAGE, key, replace(request, task="continuity_check", task_input=check_input), ContinuityResult)

        for state in result.character_states:
            event, entity = by_vid.get(state.event), characters.get(state.character)
            if not event or not entity:
                continue
            db.execute(
                text("""INSERT INTO character_states (character_id, story_event_id, timeline_anchor_id, age_or_stage,
                            location, costume, physical_condition, knowledge_state, relationship_state, state_changes)
                        VALUES (:c, :e, :a, :age, :loc, :costume, :phys, CAST(:know AS jsonb), CAST(:rel AS jsonb),
                                CAST(:chg AS jsonb))"""),
                {"c": entity["db_id"], "e": str(event["id"]), "a": _str(event["timeline_anchor_id"]),
                 "age": state.age_or_stage, "loc": state.location, "costume": state.costume,
                 "phys": state.physical_condition, "know": json.dumps(state.knowledge),
                 "rel": json.dumps(state.relationship_changes), "chg": json.dumps(state.changes)},
            )
            counts["character_states"] += 1
            last_character[state.character] = {k: v for k, v in {
                "location": state.location, "costume": state.costume, "condition": state.physical_condition,
                "stage": state.age_or_stage}.items() if v}

        for state in result.object_states:
            event, entity = by_vid.get(state.event), objects.get(state.object)
            if not event or not entity:
                continue
            owner = characters.get(state.owner or "")
            db.execute(
                text("""INSERT INTO artifact_states (continuity_object_id, story_event_id, timeline_anchor_id,
                            owner_character_id, location, condition, state_notes)
                        VALUES (:o, :e, :a, CAST(:owner AS uuid), :loc, :cond, :notes)"""),
                {"o": entity["db_id"], "e": str(event["id"]), "a": _str(event["timeline_anchor_id"]),
                 "owner": owner["db_id"] if owner else None, "loc": state.location, "cond": state.condition,
                 "notes": state.notes},
            )
            counts["object_states"] += 1
            last_object[state.object] = {k: v for k, v in {
                "owner": state.owner, "location": state.location, "condition": state.condition}.items() if v}

        for conflict in check.conflicts:
            entity = characters.get(conflict.entity or "") or objects.get(conflict.entity or "")
            kind = "character" if conflict.entity in characters else "object" if entity else None
            titles = ", ".join(by_vid[v]["title"] for v in conflict.events if v in by_vid)
            severity = (conflict.severity or "warning").lower()
            db.execute(
                text("""INSERT INTO continuity_conflicts (series_id, entity_type, entity_id, conflict_type, description,
                            severity, source_references)
                        VALUES (:s, :kind, CAST(:eid AS uuid), :type, :description, :severity, CAST(:refs AS jsonb))"""),
                {"s": str(series_id), "kind": kind, "eid": entity["db_id"] if entity else None,
                 "type": conflict.type or "state",
                 "description": conflict.description + (f" (events: {titles})" if titles else ""),
                 "severity": severity if severity in SEVERITIES else "warning", "refs": json.dumps([])},
            )
            counts["conflicts"] += 1
    db.commit()
    return counts


def _passages(window: list, chunk_text: dict[str, str]) -> list[dict]:
    """Source text behind a window's events, so details the event summaries leave out (where an object is,
    how old someone is) can be checked. Capped so the prompt stays small."""
    passages, words = [], 0
    for chunk_id in dict.fromkeys(ref.get("chunk_id") for e in window for ref in e["source_references"] or []):
        body = chunk_text.get(chunk_id)
        if not body:
            continue
        room = PASSAGE_WORDS - words
        if room <= 0:
            break
        snippet = " ".join(body.split()[:room])
        passages.append({"text": snippet})
        words += len(snippet.split())
    return passages


def _str(value):
    return str(value) if value else None
