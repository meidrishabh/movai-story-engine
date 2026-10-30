"""Timeline stage: turn extracted events into story_events placed on timeline anchors."""
import json
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.llm_base import LLMAnalysisRequest
from app.schemas.llm_stages import TimelineResult
from app.services.llm_stage import LLMStageClient

STAGE = "timeline"
WINDOW = 120  # events per model call
LAYERS = {"main": "objective", "objective": "objective", "flashback": "flashback",
          "flash_forward": "flash_forward", "dream": "dream", "vision": "vision", "alternate": "alternate"}
RELATIONS = {"before", "after", "simultaneous"}


def _norm(label: str) -> str:
    return re.sub(r"\W+", " ", label.lower()).strip()


def build_timeline(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID,
                   snapshot: dict, profile: str, story_format: str) -> dict:
    events = snapshot.get("events") or []
    if not events:
        return {"events": 0, "anchors": 0}

    # Derived data from earlier runs is replaced (states cascade with their events).
    db.execute(text("DELETE FROM story_events WHERE series_id = :s"), {"s": str(series_id)})
    db.execute(text("DELETE FROM timeline_anchors WHERE series_id = :s"), {"s": str(series_id)})

    items = []  # {"vid", "row_id", "title", "description", "position"}
    for number, event in enumerate(events, start=1):
        row_id = db.execute(
            text("""INSERT INTO story_events (series_id, title, description, event_type, narrative_position,
                        confidence, source_references)
                    VALUES (:s, :title, :description, :event_type, :position, :confidence, CAST(:refs AS jsonb))
                    RETURNING id"""),
            {"s": str(series_id), "title": event["title"], "description": event.get("description") or event["title"],
             "event_type": event.get("event_type"), "position": number, "confidence": event.get("confidence"),
             "refs": json.dumps(event.get("source_references") or [])},
        ).scalar_one()
        items.append({"vid": f"V{number}", "row_id": row_id, "title": event["title"],
                      "description": (event.get("description") or "")[:300], "hint": event.get("timeline_label")})

    anchors: list[dict] = []  # ordered; {"label", "id", "data"}
    by_label: dict[str, dict] = {}
    placement: dict[str, tuple[dict, str]] = {}  # vid -> (anchor, layer)
    relations: list[tuple[str, str, str]] = []
    summary = snapshot.get("story_so_far") or ""

    for start in range(0, len(items), WINDOW):
        window = items[start:start + WINDOW]
        request = LLMAnalysisRequest(
            task="timeline", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={
                "story_so_far": summary,
                "anchors": [{"label": a["label"], "time_start": a["data"].get("time_start")} for a in anchors],
                "events": [{"id": i["vid"], "title": i["title"], "description": i["description"],
                            "timeline_hint": i["hint"]} for i in window],
            },
        )
        result: TimelineResult = client.run(db, run_id, STAGE, f"{start // WINDOW + 1:04d}", request, TimelineResult)

        # New anchors keep the order the model listed them in, placed after the one they follow.
        for anchor in result.anchors:
            key = _norm(anchor.label)
            if not key or key in by_label:
                continue
            record = {"label": anchor.label.strip(), "data": anchor.model_dump()}
            after = by_label.get(_norm(anchor.after or ""))
            if after is not None and after in anchors:
                anchors.insert(anchors.index(after) + 1, record)
            else:
                anchors.append(record)
            by_label[key] = record

        for event in result.events:
            anchor = by_label.get(_norm(event.anchor or ""))
            if anchor is None:
                continue
            placement[event.id] = (anchor, LAYERS.get((event.narrative_layer or "main").lower(), "objective"))
            for relation in event.relations:
                kind = (relation.type or "before").lower()
                if kind in RELATIONS:
                    relations.append((event.id, relation.to, kind))

    # Events the model skipped inherit the previous event's placement (or the first anchor).
    if not anchors:
        anchors.append({"label": "Story", "data": {}})
    previous = (anchors[0], "objective")
    for item in items:
        previous = placement.setdefault(item["vid"], previous)

    for order, anchor in enumerate(anchors, start=1):
        data = anchor["data"]
        anchor["id"] = db.execute(
            text("""INSERT INTO timeline_anchors (series_id, label, time_start, time_end, timeline_type,
                        description, sort_order)
                    VALUES (:s, :label, :start, :end, :type, :description, :order)
                    ON CONFLICT (series_id, label, timeline_type, world_id) DO UPDATE SET sort_order = EXCLUDED.sort_order
                    RETURNING id"""),
            {"s": str(series_id), "label": anchor["label"], "start": data.get("time_start"),
             "end": data.get("time_end"), "type": data.get("timeline_type") or "primary",
             "description": data.get("description") or None, "order": order},
        ).scalar_one()
        anchor["rank"] = order

    # chronological_position = anchor rank * 1000 + telling order inside the anchor
    inside: dict[int, int] = {}
    for item in items:
        anchor, layer = placement[item["vid"]]
        inside[anchor["rank"]] = inside.get(anchor["rank"], 0) + 1
        db.execute(
            text("""UPDATE story_events SET timeline_anchor_id = :anchor, narrative_layer = :layer,
                        chronological_position = :chrono WHERE id = :id"""),
            {"anchor": str(anchor["id"]), "layer": layer, "chrono": anchor["rank"] * 1000 + inside[anchor["rank"]],
             "id": str(item["row_id"])},
        )
        item["anchor_id"] = anchor["id"]

    ids = {item["vid"]: item["row_id"] for item in items}
    saved_relations = 0
    for source, target, kind in dict.fromkeys(relations):
        if source in ids and target in ids and source != target:
            db.execute(
                text("""INSERT INTO timeline_relations (from_event_id, to_event_id, relation_type)
                        VALUES (:a, :b, :kind) ON CONFLICT DO NOTHING"""),
                {"a": str(ids[source]), "b": str(ids[target]), "kind": kind},
            )
            saved_relations += 1
    db.commit()
    return {"events": len(items), "anchors": len(anchors), "relations": saved_relations,
            "non_main_events": sum(1 for _, layer in placement.values() if layer != "objective")}
