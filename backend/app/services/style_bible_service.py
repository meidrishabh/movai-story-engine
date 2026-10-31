"""The style bible: one look for the whole series, written from the story, edited and approved by the user.

Later stages build every image prompt from the approved bible with `style_block`, so the look never varies by shot.
Editing an approved bible sends it back to draft; generating a new one supersedes the old (the API asks first).
"""
import json
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest, LLMProviderError
from app.providers.llm_factory import get_llm_provider
from app.schemas.llm_stages import StyleBibleResult
from app.services.adaptation_service import latest_master_script, load_units
from app.services.llm_stage import LLMStageClient

FIELDS = ("theme_tone", "medium", "art_style", "palette", "lighting", "camera_language", "negative_style")
MAX_UNITS = 14
MAX_ENTITIES = 8


def get_live(db: Session, series_id: UUID) -> dict | None:
    """The current bible (draft or approved), or None."""
    row = db.execute(text("SELECT * FROM style_bibles WHERE series_id = :s AND status IN ('draft', 'approved')"),
                     {"s": str(series_id)}).mappings().first()
    return dict(row) if row else None


def get_approved(db: Session, series_id: UUID) -> dict | None:
    bible = get_live(db, series_id)
    return bible if bible and bible["status"] == "approved" else None


def style_block(bible: dict, *, short: bool = False) -> str:
    """The text every image prompt starts with. `short` is the few words a video prompt needs: the clip already has
    the look from its first frame, so repeating the whole block would only invite the model to restyle it."""
    if short:
        parts = [bible.get("medium"), bible.get("lighting")]
        return ", ".join(p.strip() for p in parts if p and p.strip())
    lines = []
    for label, key in (("Style", "medium"), ("Art style", "art_style"), ("Palette", "palette"), ("Lighting", "lighting"),
                       ("Camera", "camera_language"), ("Mood", "theme_tone")):
        if bible.get(key):
            lines.append(f"{label}: {bible[key].strip()}")
    return "\n".join(lines)


def negative_block(bible: dict) -> str:
    return (bible.get("negative_style") or "").strip()


def _entities(db: Session, table: str, series_id: UUID) -> list[dict]:
    rows = db.execute(
        text(f"""SELECT name, description FROM {table} WHERE series_id = :s AND merged_into_id IS NULL
                 AND review_status <> 'stale' ORDER BY created_at LIMIT :n"""), {"s": str(series_id), "n": MAX_ENTITIES}).mappings().all()
    return [{"name": r["name"], "description": (r["description"] or "")[:160]} for r in rows]


def _story_input(db: Session, series_id: UUID) -> tuple[dict, str, str]:
    series = db.execute(text("SELECT title, genre, premise, visual_style FROM series WHERE id = :s"),
                        {"s": str(series_id)}).mappings().one()
    script = latest_master_script(db, series_id)
    units = []
    if script is not None:
        units = [{"title": u["title"], "synopsis": u["synopsis"][:240]} for u in load_units(db, script["id"])[:MAX_UNITS]]
    profile, story_format = "general", "novel"
    try:
        from app.services.adaptation_service import run_context
        _, profile, story_format = run_context(db, series_id)
    except PermanentJobError:
        pass  # no finished analysis yet; the style can still be drafted from the series details
    data = {"series": {"title": series["title"], "genre": series["genre"], "premise": (series["premise"] or "")[:600],
                       "visual_style_hint": series["visual_style"] or ""},
            "summary": ((script["summary"] if script else "") or "")[:1500], "units": units,
            "characters": _entities(db, "characters", series_id), "places": _entities(db, "locations", series_id)}
    return data, profile, story_format


def _next_version(db: Session, series_id: UUID) -> int:
    return db.execute(text("SELECT COALESCE(MAX(version), 0) + 1 FROM style_bibles WHERE series_id = :s"),
                      {"s": str(series_id)}).scalar()


def generate_draft(db: Session, series_id: UUID) -> dict:
    """Write a style bible from the story with the LLM. A live bible is superseded. The caller commits."""
    data, profile, story_format = _story_input(db, series_id)
    request = LLMAnalysisRequest(task="style_bible", profile=profile, context_chunks=[], known_entities={},
                                 story_format=story_format, task_input=data)
    client = LLMStageClient(get_llm_provider())
    result = None
    for _ in range(2):  # one retry when the reply does not match the schema
        response = client.analyze(request)
        try:
            result = StyleBibleResult.model_validate(response.payload)
            break
        except ValidationError:
            continue
    if result is None:
        raise LLMProviderError("The style reply did not match the schema twice")
    db.execute(text("UPDATE style_bibles SET status = 'superseded', updated_at = now() WHERE series_id = :s AND status IN ('draft', 'approved')"),
               {"s": str(series_id)})
    overrides = [o.model_dump() for o in result.per_act_overrides if o.when or o.change]
    row = db.execute(
        text("""INSERT INTO style_bibles (series_id, version, status, theme_tone, medium, art_style, palette, lighting,
                    camera_language, negative_style, per_act_overrides)
                VALUES (:s, :v, 'draft', :theme_tone, :medium, :art_style, :palette, :lighting, :camera_language,
                        :negative_style, CAST(:overrides AS jsonb)) RETURNING *"""),
        {"s": str(series_id), "v": _next_version(db, series_id), "overrides": json.dumps(overrides),
         **{f: getattr(result, f) for f in FIELDS}}).mappings().one()
    return dict(row)


def update_live(db: Session, series_id: UUID, changes: dict) -> dict:
    """Edit the live bible. An approved one goes back to draft so the user approves the new look. The caller commits."""
    bible = get_live(db, series_id)
    if bible is None:
        raise LookupError("The series has no style bible yet")
    sets, params = [], {"id": str(bible["id"])}
    for field in FIELDS:
        if field in changes:
            sets.append(f"{field} = :{field}")
            params[field] = (changes[field] or "").strip() or None
    if "per_act_overrides" in changes:
        sets.append("per_act_overrides = CAST(:overrides AS jsonb)")
        params["overrides"] = json.dumps([o for o in changes["per_act_overrides"] if o.get("when") or o.get("change")])
    if not sets:
        return bible
    row = db.execute(
        text(f"""UPDATE style_bibles SET {', '.join(sets)}, status = 'draft', approved_at = NULL, updated_at = now()
                 WHERE id = :id RETURNING *"""), params).mappings().one()
    return dict(row)


def approve(db: Session, series_id: UUID) -> dict:
    bible = get_live(db, series_id)
    if bible is None:
        raise LookupError("The series has no style bible yet")
    if not (bible["medium"] and bible["art_style"]):
        raise ValueError("Fill in at least the medium and the art style before approving")
    row = db.execute(
        text("UPDATE style_bibles SET status = 'approved', approved_at = now(), updated_at = now() WHERE id = :id RETURNING *"),
        {"id": str(bible["id"])}).mappings().one()
    return dict(row)
