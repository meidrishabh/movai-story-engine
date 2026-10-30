"""Appearance stage: a visual reference sheet per main character, taken only from what the story says."""
import json
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest
from app.repositories.analysis_repository import list_source_chunks
from app.schemas.llm_stages import AppearanceResult
from app.services.llm_stage import LLMStageClient

STAGE = "appearance"
MAX_CHARACTERS = 15  # the most-mentioned characters; minor ones rarely need a reference sheet
PASSAGE_WORDS = 3000  # source words shown per character
DETAIL_FIELDS = ("age", "face_and_body", "clothing", "distinctive_features", "voice")


def build_appearance(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, profile: str,
                     story_format: str) -> dict:
    run = db.execute(text("SELECT source_id FROM analysis_runs WHERE id = :r"), {"r": str(run_id)}).mappings().one()
    chunks = list_source_chunks(db, run["source_id"])
    order = {c["chunk_id"]: c["narrative_position"] for c in chunks}
    chunk_text = {c["chunk_id"]: c["text"] for c in chunks}

    characters = db.execute(
        text("""SELECT id, name, description, role FROM characters
                WHERE series_id = :s AND merged_into_id IS NULL AND review_status <> 'stale'"""),
        {"s": str(series_id)}).mappings().all()
    counts = {"characters": 0, "written": 0, "no_details": 0, "kept_hand_edited": 0}
    candidates = []
    for character in characters:
        names, chunk_ids = _names_and_chunks(db, character["id"], character["name"])
        if chunk_ids:
            candidates.append((len(chunk_ids), character, names, chunk_ids))
    candidates.sort(key=lambda c: -c[0])

    for _, character, names, chunk_ids in candidates[:MAX_CHARACTERS]:
        if _has_approved_version(db, character["id"]):
            counts["kept_hand_edited"] += 1
            continue
        passages = _passages(sorted(chunk_ids, key=lambda c: order.get(c, 0)), chunk_text, names)
        if not passages:
            continue
        request = LLMAnalysisRequest(
            task="appearance", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={"character": {"name": character["name"], "aliases": names[1:],
                                      "description": (character["description"] or character["role"] or "")[:200]},
                        "passages": passages})
        result: AppearanceResult = client.run(db, run_id, STAGE, str(character["id"]), request, AppearanceResult)
        counts["characters"] += 1
        if _store(db, character, result):
            counts["written"] += 1
        else:
            counts["no_details"] += 1
    db.commit()
    return counts


def _names_and_chunks(db: Session, character_id, name: str) -> tuple[list[str], set[str]]:
    """The character's names (own, aliases, merged duplicates) and every chunk that mentions any of them."""
    ids = [str(character_id)] + [str(r[0]) for r in db.execute(
        text("SELECT id FROM characters WHERE merged_into_id = :c"), {"c": str(character_id)})]
    names = [name]
    for alias, in db.execute(text("SELECT alias FROM entity_aliases WHERE entity_type = 'character' AND entity_id = ANY(CAST(:ids AS uuid[]))"),
                             {"ids": "{" + ",".join(ids) + "}"}):
        names.append(alias)
    for merged, in db.execute(text("SELECT name FROM characters WHERE merged_into_id = :c"), {"c": str(character_id)}):
        names.append(merged)
    chunk_ids = {str(r[0]) for r in db.execute(
        text("SELECT chunk_id FROM entity_mentions WHERE entity_type = 'character' AND entity_id = ANY(CAST(:ids AS uuid[]))"),
        {"ids": "{" + ",".join(ids) + "}"})}
    return list(dict.fromkeys(n for n in names if n and n.strip())), chunk_ids


def _passages(chunk_ids: list[str], chunk_text: dict[str, str], names: list[str]) -> list[dict]:
    """Sentences that name the character plus the sentence after each (descriptions often continue with a pronoun)."""
    needles = {n.lower() for n in names} | {p.lower() for n in names for p in n.split() if len(p) >= 4}
    out, words = [], 0
    for chunk_id in chunk_ids:
        sentences = re.split(r"(?<=[.!?])\s+", chunk_text.get(chunk_id, ""))
        picked = []
        for index, sentence in enumerate(sentences):
            if any(needle in sentence.lower() for needle in needles):
                picked.extend(sentences[index:index + 2])
        snippet = " ".join(dict.fromkeys(picked))
        room = PASSAGE_WORDS - words
        if not snippet or room <= 0:
            continue
        snippet = " ".join(snippet.split()[:room])
        out.append({"text": snippet})
        words += len(snippet.split())
    return out


def _has_approved_version(db: Session, character_id) -> bool:
    return bool(db.execute(text("SELECT 1 FROM character_versions WHERE character_id = :c AND status = 'approved' LIMIT 1"),
                           {"c": str(character_id)}).scalar())


def _store(db: Session, character, result: AppearanceResult) -> bool:
    """Replace the character's earlier draft sheet. Returns False when the text gave no visual detail."""
    db.execute(text("DELETE FROM character_versions WHERE character_id = :c AND status = 'draft'"), {"c": str(character["id"])})
    db.execute(text("DELETE FROM costumes WHERE character_id = :c AND approval_status = 'draft'"), {"c": str(character["id"])})
    details = {f: getattr(result, f) for f in DETAIL_FIELDS if getattr(result, f)}
    if not details and not result.costumes:
        return False
    version = db.execute(text("SELECT COALESCE(MAX(version_number), 0) + 1 FROM character_versions WHERE character_id = :c"),
                         {"c": str(character["id"])}).scalar_one()
    notes = "Extracted from the story text."
    if result.evidence:
        notes += " Evidence: " + " | ".join(result.evidence)
    missing = [f.replace("_", " ") for f in DETAIL_FIELDS if f not in details]  # computed, the model's own list disagreed with its fields
    if missing:
        notes += " Not described: " + ", ".join(missing) + "."
    db.execute(
        text("""INSERT INTO character_versions (character_id, version_number, description, face_and_body_design,
                    clothing_and_accessories, distinctive_features, color_palette, voice_profile, status, change_notes)
                VALUES (:c, :v, :d, :face, :clothing, :features, CAST(:palette AS jsonb), CAST(:voice AS jsonb),
                        'draft', :notes)"""),
        {"c": str(character["id"]), "v": version,
         "d": result.description or "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in details.items()),
         "face": ", ".join(x for x in (result.age, result.face_and_body) if x) or None, "clothing": result.clothing,
         "features": result.distinctive_features, "palette": json.dumps(result.color_palette),
         "voice": json.dumps({"description": result.voice} if result.voice else {}), "notes": notes})
    for costume in result.costumes:
        db.execute(
            text("""INSERT INTO costumes (character_id, name, description, color_palette, accessories, state_notes,
                        source_unit_ids, approval_status)
                    VALUES (:c, :n, :d, CAST(:colors AS jsonb), CAST(:acc AS jsonb), :when, '{}', 'draft')"""),
            {"c": str(character["id"]), "n": costume.name, "d": costume.description or costume.name,
             "colors": json.dumps(costume.colors), "acc": json.dumps(costume.accessories), "when": costume.when})
    return True


def generate_for_series(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, profile: str,
                        story_format: str) -> dict:
    """Run the stage for a finished analysis. Stored replies are cleared when the job is queued, not here,
    so a retried job continues where it stopped."""
    if run_id is None:
        raise PermanentJobError("The series has no finished analysis run")
    return build_appearance(db, client, run_id, series_id, profile, story_format)
