import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

TABLES = {"character": "characters", "location": "locations", "object": "continuity_objects"}

# Fields that differ per table; everything else is shared.
_EXTRA_COLUMNS = {
    "character": ("role", "personality", "story_role"),
    "location": (),
    "object": ("distinctive_features",),
}


def _key(name: str) -> str:
    return re.sub(r"\W+", " ", name.lower()).strip()


def _upsert(db: Session, kind: str, series_id: UUID, run_id: UUID, entity: dict) -> UUID:
    table = TABLES[kind]
    extras = _EXTRA_COLUMNS[kind]
    columns = ["series_id", "name", "disambiguation", "description", "review_status", "review_note",
               "first_seen_position", "analysis_run_id", *extras]
    values = [":series_id", ":name", ":disambiguation", ":description", ":review_status", ":review_note",
              ":first_seen_position", ":analysis_run_id", *(f":{c}" for c in extras)]
    params = {
        "series_id": str(series_id), "name": entity["name"], "disambiguation": entity["disambiguation"],
        "description": entity["description"], "review_status": entity["review_status"],
        "review_note": entity["review_note"], "first_seen_position": entity["first_seen_position"],
        "analysis_run_id": str(run_id), **{c: entity.get(c) for c in extras},
    }
    if kind == "character":
        columns += ["origin", "analysis_status", "extraction_confidence"]
        values += ["'extracted'", "'extracted'", ":confidence"]
        params["confidence"] = entity["confidence"]
    if kind == "object":
        columns.append("object_type")
        values.append(":object_type")
        params["object_type"] = entity.get("object_type") or "artifact"

    conflict_key = "series_id, object_type, name, disambiguation" if kind == "object" else "series_id, name, disambiguation"
    updates = ["description = EXCLUDED.description", "first_seen_position = EXCLUDED.first_seen_position",
               "analysis_run_id = EXCLUDED.analysis_run_id", "updated_at = now()",
               *(f"{c} = EXCLUDED.{c}" for c in extras),
               f"review_status = CASE WHEN {table}.review_status = 'approved' THEN 'approved' ELSE EXCLUDED.review_status END",
               f"review_note = CASE WHEN {table}.review_status = 'approved' THEN {table}.review_note ELSE EXCLUDED.review_note END"]
    if kind == "character":
        updates.append("extraction_confidence = EXCLUDED.extraction_confidence")

    row = db.execute(
        text(
            f"""INSERT INTO {table} ({", ".join(columns)}) VALUES ({", ".join(values)})
                ON CONFLICT ({conflict_key}) DO UPDATE SET {", ".join(updates)}
                WHERE {table}.locked = FALSE
                RETURNING id, merged_into_id"""
        ),
        params,
    ).mappings().first()
    if row is None:  # the existing row is locked: keep it untouched
        lookup = "AND object_type = :object_type" if kind == "object" else ""
        row = db.execute(
            text(
                f"""SELECT id, merged_into_id FROM {table}
                    WHERE series_id = :series_id AND name = :name AND disambiguation = :disambiguation {lookup}"""
            ),
            params,
        ).mappings().one()
    return row["merged_into_id"] or row["id"]


def save_entities(db: Session, series_id: UUID, run_id: UUID, snapshot: dict) -> dict:
    ids: dict[str, UUID] = {}
    counts = {}
    for kind, list_name in (("character", "characters"), ("location", "locations"), ("object", "objects")):
        entities = snapshot[list_name]
        for entity in entities:
            ids[entity["eid"]] = _upsert(db, kind, series_id, run_id, entity)
            entity["db_id"] = str(ids[entity["eid"]])  # later stages map E/L/O ids to rows with this
            for alias in entity["aliases"]:
                db.execute(
                    text(
                        """INSERT INTO entity_aliases (series_id, entity_type, entity_id, alias)
                           VALUES (:series_id, :kind, :entity_id, :alias)
                           ON CONFLICT (series_id, entity_type, entity_id, alias) DO NOTHING"""
                    ),
                    {"series_id": str(series_id), "kind": kind, "entity_id": str(ids[entity["eid"]]), "alias": alias},
                )
        counts[list_name] = len(entities)
        # Rows from earlier runs that this run did not see are flagged, never deleted.
        db.execute(
            text(
                f"""UPDATE {TABLES[kind]} SET review_status = 'stale'
                    WHERE series_id = :series_id AND analysis_run_id IS NOT NULL
                      AND analysis_run_id <> :run_id AND locked = FALSE
                      AND merged_into_id IS NULL AND review_status IN ('auto', 'needs_review')"""
            ),
            {"series_id": str(series_id), "run_id": str(run_id)},
        )

    # Mentions and relationships are derived from the latest run, so they are replaced.
    db.execute(
        text("DELETE FROM entity_mentions WHERE series_id = :series_id AND analysis_run_id IS NOT NULL"),
        {"series_id": str(series_id)},
    )
    mention_count = 0
    for list_name, kind in (("characters", "character"), ("locations", "location"), ("objects", "object")):
        for entity in snapshot[list_name]:
            for mention in entity["mentions"]:
                if not mention.get("chunk_id"):
                    continue
                db.execute(
                    text(
                        """INSERT INTO entity_mentions (series_id, analysis_run_id, entity_type, entity_id,
                               chunk_id, quote, confidence, verified)
                           VALUES (:series_id, :run_id, :kind, :entity_id, CAST(:chunk_id AS uuid),
                                   :quote, :confidence, :verified)"""
                    ),
                    {"series_id": str(series_id), "run_id": str(run_id), "kind": kind,
                     "entity_id": str(ids[entity["eid"]]), "chunk_id": mention["chunk_id"],
                     "quote": mention.get("quote"), "confidence": mention.get("confidence"),
                     "verified": bool(mention.get("verified"))},
                )
                mention_count += 1

    by_name: dict[str, set[UUID]] = {}
    for entity in snapshot["characters"]:
        for name in [entity["name"], *entity["aliases"]]:
            by_name.setdefault(_key(name), set()).add(ids[entity["eid"]])

    def character_id(name: str):
        found = by_name.get(_key(name), set())
        return str(next(iter(found))) if len(found) == 1 else None

    db.execute(text("DELETE FROM entity_relationships WHERE series_id = :series_id"), {"series_id": str(series_id)})
    for relationship in snapshot["relationships"]:
        db.execute(
            text(
                """INSERT INTO entity_relationships (series_id, analysis_run_id, source_name, target_name,
                       source_character_id, target_character_id, relationship, confidence)
                   VALUES (:series_id, :run_id, :source, :target, CAST(:source_id AS uuid),
                           CAST(:target_id AS uuid), :relationship, :confidence)"""
            ),
            {"series_id": str(series_id), "run_id": str(run_id), "source": relationship["source"],
             "target": relationship["target"], "source_id": character_id(relationship["source"]),
             "target_id": character_id(relationship["target"]), "relationship": relationship["relationship"],
             "confidence": relationship.get("confidence")},
        )
    counts.update({"mentions": mention_count, "relationships": len(snapshot["relationships"])})
    return counts
