"""Finds the approved reference images a keyframe should carry.

Approved references come from `app.services.reference_service` (one source of truth for which view of which target
counts as current). This module adds what only a keyframe needs: the slot-by-slot packing under the image cap, and
the pending references a keyframe should wait for.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services import reference_service

ROLE_KIND = {"character": "character_image", "place": "place_image", "object": "object_image"}
PER_ENTITY = {"character": 2, "place": 1, "object": 1}  # e.g. front and three-quarter view of a character
PENDING_STATUSES = ("queued", "blocked", "running", "awaiting_input")


def style_anchor(db: Session, series_id: UUID) -> UUID | None:
    asset_id = reference_service.style_anchor_asset_id(db, series_id)
    return UUID(str(asset_id)) if asset_id else None


def _targets(slot: dict) -> list[str]:
    return [i for i in (slot.get("look_id"), slot.get("entity_id")) if i]


def approved_assets(db: Session, series_id: UUID, role: str, targets: list[str], limit: int) -> list[UUID]:
    return [UUID(a) for a in reference_service.approved_asset_ids(db, series_id, role, targets, limit)]


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
