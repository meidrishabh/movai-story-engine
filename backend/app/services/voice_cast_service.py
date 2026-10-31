"""Voice casting: one voice per character plus a narrator, with consent recorded for each.

A cast row holds the voice (a provider voice id or a plain description), language, default delivery and speed. Lines
are generated from it by `sound_service`. A character with no cast row still speaks, in the voice description the
look sheet suggests (or the provider's default); the sound board warns about that so the user casts it on purpose.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import generation_service as generation
from app.services.asset_store import asset_url

NARRATOR = "narrator"
SAMPLE_TEXT = "This is how I sound. Does this voice fit the character?"
FIELDS = ("voice", "language", "style", "speed", "consent_given", "consent_note")


def _character(db: Session, series_id: UUID, character_id: UUID) -> dict:
    row = db.execute(text("SELECT id, name FROM characters WHERE id = :c AND series_id = :s AND merged_into_id IS NULL"),
                     {"c": str(character_id), "s": str(series_id)}).mappings().first()
    if row is None:
        raise LookupError("Character was not found in this series")
    return dict(row)


def get_cast(db: Session, series_id: UUID, character_id: UUID | None) -> dict | None:
    """The cast row for a character, or for the narrator when character_id is None."""
    if character_id is None:
        row = db.execute(text("SELECT * FROM voice_casts WHERE series_id = :s AND role = 'narrator'"),
                         {"s": str(series_id)}).mappings().first()
    else:
        row = db.execute(text("SELECT * FROM voice_casts WHERE series_id = :s AND character_id = :c"),
                         {"s": str(series_id), "c": str(character_id)}).mappings().first()
    return dict(row) if row else None


def suggested_voice(db: Session, character_id: UUID) -> str:
    """The voice description from the character's newest look sheet, if it has one."""
    return db.execute(
        text("""SELECT voice_profile ->> 'description' FROM character_versions WHERE character_id = :c
                AND voice_profile ->> 'description' IS NOT NULL ORDER BY version_number DESC LIMIT 1"""),
        {"c": str(character_id)}).scalar() or ""


def set_voice(db: Session, series_id: UUID, character_id: UUID | None, changes: dict) -> dict:
    """Create or update a cast row. Unknown keys are ignored. The caller commits."""
    if character_id is not None:
        _character(db, series_id, character_id)
    values = {k: changes[k] for k in FIELDS if k in changes}
    if "voice" in values:
        values["voice"] = (values["voice"] or "").strip()
    if "style" in values:
        values["style"] = (values["style"] or "").strip()
    if "language" in values:
        values["language"] = (values["language"] or "en").strip() or "en"
    if "consent_note" in values:
        values["consent_note"] = (values["consent_note"] or "").strip() or None
    existing = get_cast(db, series_id, character_id)
    if existing is None:
        columns = ["series_id", "character_id", "role", *values]
        params = {"series_id": str(series_id), "character_id": str(character_id) if character_id else None,
                  "role": "character" if character_id else NARRATOR, **values}
        row = db.execute(
            text(f"INSERT INTO voice_casts ({', '.join(columns)}) VALUES ({', '.join(':' + c for c in columns)}) RETURNING *"),
            params).mappings().one()
        return dict(row)
    if not values:
        return existing
    sets = ", ".join(f"{k} = :{k}" for k in values)
    row = db.execute(text(f"UPDATE voice_casts SET {sets}, updated_at = now() WHERE id = :id RETURNING *"),
                     {"id": str(existing["id"]), **values}).mappings().one()
    return dict(row)


def voice_params(cast: dict | None, suggestion: str = "", delivery: str | None = None) -> dict:
    """The `params` a voice request carries: who speaks, in which language and style, how fast."""
    cast = cast or {}
    style = "; ".join(part for part in ((cast.get("style") or "").strip(), (delivery or "").strip()) if part)
    return {"voice": (cast.get("voice") or "").strip() or suggestion, "language": cast.get("language") or "en",
            "style": style, "speed": float(cast.get("speed") or 1.0)}


def list_cast(db: Session, series_id: UUID) -> dict:
    """Every character with how much they speak and who voices them, plus the narrator."""
    lines = {r[0]: r[1] for r in db.execute(
        text("""SELECT lower(d ->> 'character'), count(*) FROM scenes sc JOIN episodes e ON e.id = sc.episode_id
                CROSS JOIN LATERAL jsonb_array_elements(sc.dialogue) d WHERE e.series_id = :s GROUP BY 1"""),
        {"s": str(series_id)})}
    casts = {str(r["character_id"]): dict(r) for r in db.execute(
        text("SELECT * FROM voice_casts WHERE series_id = :s AND character_id IS NOT NULL"), {"s": str(series_id)}).mappings()}
    narrator = get_cast(db, series_id, None)
    characters = db.execute(
        text("""SELECT id, name, role FROM characters WHERE series_id = :s AND merged_into_id IS NULL
                AND review_status <> 'stale' ORDER BY name"""), {"s": str(series_id)}).mappings().all()
    previews = {str(r["target_id"]): r for r in db.execute(
        text("""SELECT DISTINCT ON (r.target_id) r.target_id, r.id, r.status, r.result_asset_id, r.error_summary
                FROM generation_requests r WHERE r.series_id = :s AND r.target_type = 'voice_cast'
                ORDER BY r.target_id, r.created_at DESC"""), {"s": str(series_id)}).mappings()}
    assets = {}
    ids = [str(p["result_asset_id"]) for p in previews.values() if p["result_asset_id"]]
    if ids:
        assets = {str(a["id"]): a for a in db.execute(
            text("SELECT * FROM assets WHERE id = ANY(CAST(:ids AS uuid[]))"), {"ids": "{" + ",".join(ids) + "}"}).mappings()}

    def present(cast: dict | None) -> dict | None:
        if cast is None:
            return None
        preview = previews.get(str(cast["id"]))
        asset = assets.get(str(preview["result_asset_id"])) if preview and preview["result_asset_id"] else None
        return {"voice": cast["voice"], "language": cast["language"], "style": cast["style"], "speed": float(cast["speed"]),
                "consent_given": cast["consent_given"], "consent_note": cast["consent_note"],
                "preview": None if preview is None else {
                    "request_id": str(preview["id"]), "status": preview["status"], "error": preview["error_summary"],
                    "url": asset_url(asset["id"]) if asset else None}}

    items = []
    for c in characters:
        items.append({"character_id": str(c["id"]), "name": c["name"], "role": c["role"], "lines": int(lines.get(c["name"].lower(), 0)),
                      "suggested_voice": suggested_voice(db, c["id"]), "cast": present(casts.get(str(c["id"])))})
    items.sort(key=lambda i: (-i["lines"], i["name"].lower()))
    return {"narrator": {"cast": present(narrator)}, "characters": items,
            "uncast_speaking": sum(1 for i in items if i["lines"] and i["cast"] is None),
            "without_consent": sum(1 for i in items if i["cast"] and not i["cast"]["consent_given"])}


def preview_voice(db: Session, series_id: UUID, character_id: UUID | None, sample: str | None = None) -> dict:
    """Queue a short sample of the cast voice. A cast row is created (with defaults) if there is none yet.
    The caller commits."""
    cast = get_cast(db, series_id, character_id)
    if cast is None:
        cast = set_voice(db, series_id, character_id, {})
    suggestion = suggested_voice(db, character_id) if character_id else ""
    params = voice_params(cast, suggestion)
    params["text"] = (sample or "").strip() or SAMPLE_TEXT
    params["preview"] = True
    return generation.create_request(db, series_id, "voice_line", params["text"], target_type="voice_cast",
                                     target_id=cast["id"], params=params)
