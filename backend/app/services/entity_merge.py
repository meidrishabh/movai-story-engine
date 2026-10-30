"""Merges per-batch extraction results into one story-wide set of entities.

Entities carry stable ids (E1.. characters, L1.. locations, O1.. objects) that
are fed back to the model on later calls, so names do not drift. Two entities
that share a name stay separate when their disambiguation labels differ.
"""
import re
from typing import Any

from app.schemas.llm_analysis import EntityExtractionResult

KINDS = ("character", "location", "object")
LIST_NAME = {"character": "characters", "location": "locations", "object": "objects"}
PREFIX = {"character": "E", "location": "L", "object": "O"}
KIND_BY_PREFIX = {value: key for key, value in PREFIX.items()}

RECENT_DETAILED = 15
DETAIL_LIMIT = 40
COMPACT_LIMIT = {"character": 300, "location": 100, "object": 100}
RESOLUTION_LIMIT = 150
AUTO_MERGE_CONFIDENCE = 0.8
REVIEW_CONFIDENCE = 0.5


def _key(name: str | None) -> str:
    return re.sub(r"\W+", " ", (name or "").lower()).strip()


def _norm_text(text: str) -> str:
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("—", "-").replace("–", "-")
    return re.sub(r"\s+", " ", text.lower()).strip()


def _longer(current: str | None, new: str | None) -> str | None:
    return new if len(new or "") > len(current or "") else current


def _merge_refs(target: list[dict], new_refs: list[dict]):
    seen = {ref.get("chunk_id") for ref in target}
    for ref in new_refs:
        if ref.get("chunk_id") not in seen:
            seen.add(ref.get("chunk_id"))
            target.append(ref)


def _ref(chunk: dict) -> dict:
    return {
        "chunk_id": chunk["chunk_id"],
        "page_start": chunk.get("page_start"),
        "page_end": chunk.get("page_end"),
        "narrative_position": chunk.get("narrative_position"),
    }


class EntityAccumulator:
    def __init__(self):
        self.entities: dict[str, dict] = {}
        self.events: dict[tuple, dict] = {}
        self.relationships: dict[tuple, dict] = {}
        self.notes: list[str] = []
        self.story_so_far = ""
        self._counter = {kind: 0 for kind in KINDS}
        self._tick = 0
        self._full_index: dict[tuple[str, str], list[str]] = {}  # names and aliases
        self._name_index: dict[tuple[str, str], list[str]] = {}  # names only

    # ----- adding a batch -------------------------------------------------

    def add(self, batch: EntityExtractionResult, chunks: list[dict]):
        prepared = [{**chunk, "_norm": _norm_text(chunk["text"])} for chunk in chunks]
        data = batch.model_dump(mode="json")
        for kind in KINDS:
            for item in data[LIST_NAME[kind]]:
                self._add_entity(kind, item, prepared)
        for item in data["events"]:
            self._add_event(item, prepared)
        for item in data["relationships"]:
            self._add_relationship(item)
        for note in data["analysis_notes"]:
            if note not in self.notes:
                self.notes.append(note)
        if data.get("story_so_far"):
            self.story_so_far = data["story_so_far"]

    def _add_entity(self, kind: str, item: dict, chunks: list[dict]):
        disambiguation = (item.get("disambiguation") or "").strip()
        eid, note = self._match(kind, item, disambiguation)
        if eid is None:
            self._counter[kind] += 1
            eid = f"{PREFIX[kind]}{self._counter[kind]}"
            self.entities[eid] = {
                "eid": eid, "kind": kind, "name": item["name"].strip(), "disambiguation": disambiguation,
                "description": None, "aliases": [], "role": None, "personality": None, "story_role": None,
                "object_type": "artifact", "distinctive_features": None, "confidence": None,
                "first_seen_position": None, "source_references": [], "mentions": [],
                "review_status": "auto", "review_note": None, "touched": 0, "merged_from": [],
            }
        entity = self.entities[eid]
        self._tick += 1
        entity["touched"] = self._tick
        if note and not entity["review_note"]:
            entity["review_status"], entity["review_note"] = "needs_review", note
        if disambiguation and not entity["disambiguation"]:
            entity["disambiguation"] = disambiguation
        for name in [item["name"], *item.get("aliases", [])]:
            if _key(name) and _key(name) != _key(entity["name"]) and _key(name) not in {_key(a) for a in entity["aliases"]}:
                entity["aliases"].append(name.strip())
        for field in ("description", "role", "personality", "story_role", "distinctive_features"):
            entity[field] = _longer(entity[field], item.get(field))
        if item.get("object_type") and entity["object_type"] in (None, "", "artifact"):
            entity["object_type"] = item["object_type"]
        entity["confidence"] = max(entity["confidence"] or 0, item.get("confidence") or 0) or None
        self._record_evidence(entity, item, chunks)
        self._rebuild_index()

    def _match(self, kind: str, item: dict, disambiguation: str) -> tuple[str | None, str | None]:
        ref_id = (item.get("id") or "").strip()
        if ref_id in self.entities and self.entities[ref_id]["kind"] == kind:
            return ref_id, None

        candidates: list[str] = list(self._full_index.get((kind, _key(item["name"])), []))
        for alias in item.get("aliases", []):
            for eid in self._name_index.get((kind, _key(alias)), []):
                if eid not in candidates:
                    candidates.append(eid)

        def conflicts(eid: str) -> bool:
            existing = self.entities[eid]["disambiguation"]
            return bool(disambiguation and existing and _key(disambiguation) != _key(existing))

        compatible = [eid for eid in candidates if not conflicts(eid)]
        if not compatible:
            return None, None
        if disambiguation:
            exact = [e for e in compatible if _key(self.entities[e]["disambiguation"]) == _key(disambiguation)]
            if exact:
                return exact[0], None
        if len(compatible) == 1:
            return compatible[0], None
        best = max(compatible, key=lambda e: self.entities[e]["touched"])
        return best, f"Name matched {len(compatible)} existing entities; merged into the most recent one"

    def _record_evidence(self, entity: dict, item: dict, chunks: list[dict]):
        quote = (item.get("evidence") or "").strip()
        matched = [c for c in chunks if len(quote) >= 3 and _norm_text(quote) in c["_norm"]]
        refs = [_ref(c) for c in matched] or item.get("source_references", [])
        _merge_refs(entity["source_references"], refs)
        known = {(m["chunk_id"], m["quote"]) for m in entity["mentions"]}
        for ref in refs[:3]:
            if (ref["chunk_id"], quote or None) not in known:
                entity["mentions"].append({
                    "chunk_id": ref["chunk_id"], "quote": quote or None,
                    "verified": bool(matched), "confidence": item.get("confidence"),
                })
        positions = [r["narrative_position"] for r in refs if r.get("narrative_position") is not None]
        if positions:
            first = min(positions)
            if entity["first_seen_position"] is None or first < entity["first_seen_position"]:
                entity["first_seen_position"] = first

    def _add_event(self, item: dict, chunks: list[dict]):
        quote = (item.get("evidence") or "").strip()
        matched = [c for c in chunks if len(quote) >= 3 and _norm_text(quote) in c["_norm"]]
        refs = [_ref(c) for c in matched] or item.get("source_references", [])
        item["source_references"] = refs
        item["verified"] = bool(matched)
        positions = [r["narrative_position"] for r in refs if r.get("narrative_position") is not None]
        if item.get("narrative_position") is None and positions:
            item["narrative_position"] = min(positions)
        existing = self.events.setdefault((_key(item["title"]), item.get("narrative_position")), item)
        if existing is not item:
            existing["description"] = _longer(existing.get("description"), item.get("description")) or ""
            existing["verified"] = existing["verified"] or item["verified"]
            _merge_refs(existing["source_references"], refs)

    def _add_relationship(self, item: dict):
        source, target = self._name_of(item.get("source")), self._name_of(item.get("target"))
        relationship = (item.get("relationship") or "").strip()
        if not (source and target and relationship):
            return
        self.relationships.setdefault(
            (_key(source), _key(relationship), _key(target)),
            {"source": source, "target": target, "relationship": relationship, "confidence": item.get("confidence")},
        )

    def _name_of(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        value = value.strip()
        return self.entities[value]["name"] if value in self.entities else value

    # ----- feeding the model ---------------------------------------------

    def known_entities(self, chunks: list[dict]) -> dict:
        """Entities to show the model: full detail for those likely in this batch."""
        batch_text = " ".join(_norm_text(c["text"]) for c in chunks)
        result: dict[str, list] = {}
        for kind in KINDS:
            entities = sorted((e for e in self.entities.values() if e["kind"] == kind),
                              key=lambda e: e["touched"], reverse=True)[: COMPACT_LIMIT[kind]]
            recent = {e["eid"] for e in entities[:RECENT_DETAILED]}
            detailed = []
            for entity in entities:
                if entity["eid"] in recent or self._appears_in(entity, batch_text):
                    detailed.append(entity["eid"])
            detailed = set(detailed[:DETAIL_LIMIT])
            result[LIST_NAME[kind]] = [
                self._describe(e, detail=e["eid"] in detailed) for e in entities
            ]
        return result

    @staticmethod
    def _appears_in(entity: dict, batch_text: str) -> bool:
        for name in [entity["name"], *entity["aliases"]]:
            normalized = _norm_text(name)
            if len(normalized) >= 3 and re.search(r"\b" + re.escape(normalized) + r"\b", batch_text):
                return True
        return False

    def _describe(self, entity: dict, detail: bool) -> dict:
        described = {"id": entity["eid"], "name": entity["name"], "aliases": entity["aliases"][:6]}
        if detail:
            described["disambiguation"] = entity["disambiguation"]
            described["description"] = entity["description"] or ""
            described["relationships"] = self._relationships_of(entity)
        elif entity["disambiguation"]:
            described["disambiguation"] = entity["disambiguation"]
        return described

    def _relationships_of(self, entity: dict, limit: int = 4) -> list[str]:
        names = {_key(entity["name"]), *(_key(a) for a in entity["aliases"])}
        found = [
            f"{r['source']} {r['relationship']} {r['target']}"
            for r in self.relationships.values()
            if _key(r["source"]) in names or _key(r["target"]) in names
        ]
        return found[:limit]

    # ----- resolution pass -----------------------------------------------

    def resolution_input(self) -> dict:
        result = {}
        for kind in ("character", "location"):
            entities = sorted((e for e in self.entities.values() if e["kind"] == kind),
                              key=lambda e: len(e["mentions"]), reverse=True)[:RESOLUTION_LIMIT]
            result[LIST_NAME[kind]] = [
                {**self._describe(e, detail=True), "first_seen_position": e["first_seen_position"]}
                for e in entities
            ]
        return result

    def apply_resolution(self, groups: list[dict]) -> dict:
        merged = flagged = 0
        for group in groups:
            ids = [i for i in (group.get("ids") or []) if i in self.entities]
            if len(set(ids)) < 2 or len({self.entities[i]["kind"] for i in ids}) != 1:
                continue
            confidence = group.get("confidence") if isinstance(group.get("confidence"), (int, float)) else 0
            reason = str(group.get("reason") or "")[:200]
            labels = {_key(self.entities[i]["disambiguation"]) for i in ids if self.entities[i]["disambiguation"]}
            if len(labels) > 1:
                continue  # different disambiguation labels: told apart on purpose
            if group.get("same_entity") and confidence >= AUTO_MERGE_CONFIDENCE:
                keep = min(ids, key=lambda i: (self.entities[i]["first_seen_position"] is None,
                                               self.entities[i]["first_seen_position"] or 0))
                for drop in ids:
                    if drop != keep and drop in self.entities:
                        self.merge(keep, drop)
                merged += 1
            elif confidence >= REVIEW_CONFIDENCE:
                for i in ids:
                    others = ", ".join(self.entities[o]["name"] for o in ids if o != i)
                    self.entities[i]["review_status"] = "needs_review"
                    self.entities[i]["review_note"] = f"May be the same as {others}. {reason}".strip()
                flagged += 1
        return {"merged_groups": merged, "flagged_groups": flagged}

    def merge(self, keep_id: str, drop_id: str):
        keep, drop = self.entities[keep_id], self.entities.pop(drop_id)
        for name in [drop["name"], *drop["aliases"]]:
            if _key(name) != _key(keep["name"]) and _key(name) not in {_key(a) for a in keep["aliases"]}:
                keep["aliases"].append(name)
        for field in ("description", "role", "personality", "story_role", "distinctive_features"):
            keep[field] = _longer(keep[field], drop[field])
        keep["confidence"] = max(keep["confidence"] or 0, drop["confidence"] or 0) or None
        _merge_refs(keep["source_references"], drop["source_references"])
        keep["mentions"].extend(m for m in drop["mentions"] if m not in keep["mentions"])
        positions = [p for p in (keep["first_seen_position"], drop["first_seen_position"]) if p is not None]
        keep["first_seen_position"] = min(positions) if positions else None
        keep["merged_from"] = [*keep["merged_from"], drop_id, *drop["merged_from"]]
        for relationship in self.relationships.values():
            for side in ("source", "target"):
                if _key(relationship[side]) == _key(drop["name"]):
                    relationship[side] = keep["name"]
        self._rebuild_index()

    # ----- output ---------------------------------------------------------

    def finalize(self):
        for entity in self.entities.values():
            if entity["review_status"] == "auto" and not any(m["verified"] for m in entity["mentions"]):
                entity["review_status"] = "needs_review"
                entity["review_note"] = "No quote from the model matched the source text"

    def snapshot(self) -> dict:
        def ordered(kind: str):
            return sorted((e for e in self.entities.values() if e["kind"] == kind),
                          key=lambda e: int(e["eid"][1:]))
        events = sorted(
            self.events.values(),
            key=lambda e: (e.get("narrative_position") is None, e.get("narrative_position") or 0),
        )
        return {
            "characters": ordered("character"),
            "locations": ordered("location"),
            "objects": ordered("object"),
            "events": events,
            "relationships": list(self.relationships.values()),
            "analysis_notes": self.notes,
            "story_so_far": self.story_so_far,
        }

    def _rebuild_index(self):
        self._full_index, self._name_index = {}, {}
        for eid, entity in self.entities.items():
            kind = entity["kind"]
            self._name_index.setdefault((kind, _key(entity["name"])), []).append(eid)
            for name in [entity["name"], *entity["aliases"]]:
                bucket = self._full_index.setdefault((kind, _key(name)), [])
                if eid not in bucket:
                    bucket.append(eid)
