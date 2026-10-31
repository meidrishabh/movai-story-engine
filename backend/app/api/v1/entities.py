from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.repositories.entity_repository import TABLES

router = APIRouter(prefix="/api/v1", tags=["entities"])

Kind = Literal["character", "location", "object"]
LIST_KEYS = {"character": "characters", "location": "locations", "object": "objects"}
EXTRA_SELECT = {"character": ", e.role, e.personality, e.story_role", "location": "", "object": ", e.object_type, e.distinctive_features"}


class EntityUpdate(BaseModel):
    name: str | None = None
    disambiguation: str | None = None
    description: str | None = None
    review_status: Literal["approved", "needs_review"] | None = None
    locked: bool | None = None


class MergeRequest(BaseModel):
    into_id: UUID


def _series_owned(db: Session, series_id: UUID):
    found = db.execute(
        text(
            """SELECT s.id FROM series s JOIN projects p ON p.id = s.project_id
               JOIN users u ON u.id = p.owner_id WHERE s.id = :series_id AND u.email = :email"""
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).scalar()
    if found is None:
        raise HTTPException(status_code=404, detail="Series was not found")


def _episode_series(db: Session, episode_id: UUID) -> UUID:
    series_id = db.execute(text("SELECT series_id FROM episodes WHERE id = :e"), {"e": str(episode_id)}).scalar()
    if series_id is None:
        raise HTTPException(status_code=404, detail="Episode was not found")
    _series_owned(db, series_id)
    return series_id


def _entity(db: Session, kind: str, entity_id: UUID) -> dict:
    row = db.execute(
        text(
            f"""SELECT e.id, e.series_id, e.name, e.merged_into_id FROM {TABLES[kind]} e
                JOIN series s ON s.id = e.series_id JOIN projects p ON p.id = s.project_id
                JOIN users u ON u.id = p.owner_id WHERE e.id = :id AND u.email = :email"""
        ),
        {"id": str(entity_id), "email": DEV_USER_EMAIL},
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail=f"{kind.capitalize()} was not found")
    return dict(row)


@router.get("/series/{series_id}/entities")
def list_entities(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    result = {}
    for kind, table in TABLES.items():
        rows = db.execute(
            text(
                f"""SELECT e.id, e.name, e.disambiguation, e.description, e.review_status, e.review_note,
                           e.locked, e.first_seen_position, e.merged_into_id {EXTRA_SELECT[kind]},
                    (SELECT COUNT(*) FROM entity_mentions m WHERE m.entity_type = :kind AND
                        (m.entity_id = e.id OR m.entity_id IN (SELECT c.id FROM {table} c WHERE c.merged_into_id = e.id)))
                        AS mention_count,
                    (SELECT COUNT(*) FROM entity_mentions m WHERE m.entity_type = :kind AND m.verified AND
                        (m.entity_id = e.id OR m.entity_id IN (SELECT c.id FROM {table} c WHERE c.merged_into_id = e.id)))
                        AS verified_mention_count,
                    COALESCE((SELECT array_agg(a.alias ORDER BY a.alias) FROM entity_aliases a
                              WHERE a.entity_type = :kind AND a.entity_id = e.id), '{{}}') AS aliases
                    FROM {table} e WHERE e.series_id = :series_id
                    ORDER BY e.first_seen_position NULLS LAST, e.name"""
            ),
            {"series_id": str(series_id), "kind": kind},
        ).mappings().all()
        result[LIST_KEYS[kind]] = [dict(row) for row in rows]
    return result


@router.patch("/entities/{kind}/{entity_id}")
def update_entity(kind: Kind, entity_id: UUID, payload: EntityUpdate, db: Session = Depends(get_db)):
    _entity(db, kind, entity_id)
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update")
    if "name" in changes and not (changes["name"] or "").strip():
        raise HTTPException(status_code=400, detail="Name cannot be empty")
    changes.setdefault("locked", True)  # a hand edit must survive re-analysis
    if changes.get("review_status") == "approved":
        changes["locked"] = True
    assignments = ", ".join(f"{column} = :{column}" for column in changes)
    try:
        row = db.execute(
            text(f"UPDATE {TABLES[kind]} SET {assignments}, updated_at = now() WHERE id = :id RETURNING id"),
            {**changes, "id": str(entity_id)},
        ).first()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Another entry already has that name and label")
    return {"id": str(row[0]), "updated": sorted(changes)}


@router.post("/entities/{kind}/{entity_id}/merge")
def merge_entity(kind: Kind, entity_id: UUID, payload: MergeRequest, db: Session = Depends(get_db)):
    source = _entity(db, kind, entity_id)
    target = _entity(db, kind, payload.into_id)
    if source["id"] == target["id"]:
        raise HTTPException(status_code=400, detail="Cannot merge an entry into itself")
    if source["series_id"] != target["series_id"]:
        raise HTTPException(status_code=400, detail="Entries belong to different series")
    if target["merged_into_id"] is not None:
        raise HTTPException(status_code=400, detail="The target entry was itself merged into another")
    table = TABLES[kind]
    # Entries already merged into the source now point at the target.
    db.execute(text(f"UPDATE {table} SET merged_into_id = :target WHERE merged_into_id = :source"),
               {"target": str(target["id"]), "source": str(source["id"])})
    db.execute(text(f"UPDATE {table} SET merged_into_id = :target, locked = TRUE WHERE id = :source"),
               {"target": str(target["id"]), "source": str(source["id"])})
    db.execute(text(f"UPDATE {table} SET review_status = 'approved', locked = TRUE, updated_at = now() WHERE id = :target"),
               {"target": str(target["id"])})
    # The merged entry's names become aliases of the target.
    db.execute(
        text(
            """INSERT INTO entity_aliases (series_id, entity_type, entity_id, alias)
               SELECT :series_id, :kind, :target, alias FROM entity_aliases
                 WHERE entity_type = :kind AND entity_id = :source
               ON CONFLICT (series_id, entity_type, entity_id, alias) DO NOTHING"""
        ),
        {"series_id": str(source["series_id"]), "kind": kind, "target": str(target["id"]), "source": str(source["id"])},
    )
    db.execute(
        text(
            """INSERT INTO entity_aliases (series_id, entity_type, entity_id, alias)
               VALUES (:series_id, :kind, :target, :alias)
               ON CONFLICT (series_id, entity_type, entity_id, alias) DO NOTHING"""
        ),
        {"series_id": str(source["series_id"]), "kind": kind, "target": str(target["id"]), "alias": source["name"]},
    )
    db.commit()
    return {"merged": str(source["id"]), "into": str(target["id"])}


@router.post("/entities/{kind}/{entity_id}/unmerge")
def unmerge_entity(kind: Kind, entity_id: UUID, db: Session = Depends(get_db)):
    source = _entity(db, kind, entity_id)
    if source["merged_into_id"] is None:
        raise HTTPException(status_code=400, detail="This entry is not merged")
    db.execute(text(f"UPDATE {TABLES[kind]} SET merged_into_id = NULL, updated_at = now() WHERE id = :id"),
               {"id": str(entity_id)})
    db.commit()
    return {"unmerged": str(entity_id)}
