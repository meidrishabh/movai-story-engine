"""Finds the approved reference images a keyframe should carry.

This is a thin adapter over the generation_requests rows the reference-image stage produces: kind style_anchor,
character_image, place_image or object_image, with target_id on the character_version / entity_look, review_status
'approved' and result_asset_id set. It queries those rows directly. If `app.services.reference_service` is merged
later, the three functions below are the only place to point at it.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

ROLE_KIND = {"character": "character_image", "place": "place_image", "object": "object_image"}
PER_ENTITY = {"character": 2, "place": 1, "object": 1}  # e.g. front and three-quarter view of a character
PENDING_STATUSES = ("queued", "blocked", "running", "awaiting_input")


def style_anchor(db: Session, series_id: UUID) -> UUID | None:
    return db.execute(
        text("""SELECT result_asset_id FROM generation_requests
                WHERE series_id = :s AND kind = 'style_anchor' AND review_status = 'approved' AND result_asset_id IS NOT NULL
                ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT 1"""), {"s": str(series_id)}).scalar()


def _targets(slot: dict) -> list[str]:
    return [i for i in (slot.get("look_id"), slot.get("entity_id")) if i]


def approved_assets(db: Session, series_id: UUID, role: str, targets: list[str], limit: int) -> list[UUID]:
    if not targets:
        return []
    rows = db.execute(
        text("""SELECT result_asset_id FROM generation_requests
                WHERE series_id = :s AND kind = :k AND review_status = 'approved' AND result_asset_id IS NOT NULL
                  AND target_id = ANY(CAST(:t AS uuid[]))
                ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT :n"""),
        {"s": str(series_id), "k": ROLE_KIND[role], "t": "{" + ",".join(targets) + "}", "n": limit}).all()
    return [r[0] for r in rows]


def pending_request(db: Session, series_id: UUID, role: str, targets: list[str]) -> UUID | None:
    """A reference that is being made or waits for review, so a keyframe can wait for it to be approved."""
    if not targets:
        return None
    return db.execute(
        text("""SELECT id FROM generation_requests
                WHERE series_id = :s AND kind = :k AND target_id = ANY(CAST(:t AS uuid[]))
                  AND ((status = ANY(CAST(:open AS text[]))) OR (status = 'succeeded' AND review_status = 'pending'))
                ORDER BY created_at DESC LIMIT 1"""),
        {"s": str(series_id), "k": ROLE_KIND[role], "t": "{" + ",".join(targets) + "}",
         "open": "{" + ",".join(PENDING_STATUSES) + "}"}).scalar()


def collect(db: Session, series_id: UUID, slots: list[dict], max_total: int = 8) -> dict:
    """For a keyframe's reference slots: the approved images to attach (with labels), the pending reference requests
    to wait for, and warnings for entities that have no reference at all. When there are more images than `max_total`,
    every slot keeps its first image before any slot gets a second.

    -> {"asset_ids": [UUID], "labels": {asset_id: label}, "wait_for": [UUID], "warnings": [str]}"""
    per_slot: list[list[tuple[UUID, str]]] = []
    wait_for, warnings = [], []
    for slot in slots:
        role = slot["role"]
        if role == "style_anchor":
            anchor = style_anchor(db, series_id)
            per_slot.append([(anchor, slot["label"])] if anchor else [])
            if not anchor:
                warnings.append("No approved style anchor image yet")
            continue
        if role not in ROLE_KIND:
            continue
        targets = _targets(slot)
        found = approved_assets(db, series_id, role, targets, PER_ENTITY[role])
        per_slot.append([(a, slot["label"] if len(found) == 1 else f"{slot['label']} ({n})")
                         for n, a in enumerate(found, start=1)])
        if found:
            continue
        pending = pending_request(db, series_id, role, targets)
        if pending:
            wait_for.append(pending)
            warnings.append(f"{slot['label']}: reference image is not approved yet")
        else:
            warnings.append(f"{slot['label']}: no reference image")
    asset_ids, labels = [], {}
    for depth in range(max(PER_ENTITY.values())):
        for images in per_slot:
            if depth < len(images) and len(asset_ids) < max_total and images[depth][0] not in asset_ids:
                asset_ids.append(images[depth][0])
                labels[str(images[depth][0])] = images[depth][1]
    return {"asset_ids": asset_ids, "labels": labels, "wait_for": list(dict.fromkeys(wait_for)), "warnings": warnings}
