"""Read the story structure and approve episode plans into episodes."""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned

router = APIRouter(prefix="/api/v1", tags=["story-structure"])


class PlanUpdate(BaseModel):
    title: str | None = None
    synopsis: str | None = None
    opening_hook: str | None = None
    climax_notes: str | None = None
    ending_notes: str | None = None
    review_note: str | None = None


class RejectRequest(BaseModel):
    review_note: str | None = None


def _owned_plan(db: Session, plan_id: UUID):
    plan = db.execute(
        text("""SELECT p.*, s.series_id FROM episode_plans p JOIN seasons s ON s.id = p.season_id WHERE p.id = :id"""),
        {"id": str(plan_id)}).mappings().first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Episode plan was not found")
    _series_owned(db, plan["series_id"])
    return plan


@router.get("/series/{series_id}/timeline")
def get_timeline(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    anchors = db.execute(
        text("""SELECT id, label, time_start, time_end, timeline_type, description, sort_order
                FROM timeline_anchors WHERE series_id = :s ORDER BY sort_order NULLS LAST"""),
        {"s": str(series_id)}).mappings().all()
    events = db.execute(
        text("""SELECT id, title, description, narrative_position, chronological_position, narrative_layer,
                       timeline_anchor_id FROM story_events WHERE series_id = :s
                ORDER BY chronological_position NULLS LAST, narrative_position"""),
        {"s": str(series_id)}).mappings().all()
    return {"anchors": [dict(a) for a in anchors], "events": [dict(e) for e in events]}


@router.get("/series/{series_id}/continuity")
def get_continuity(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    conflicts = db.execute(
        text("""SELECT id, entity_type, entity_id, conflict_type, description, severity, status
                FROM continuity_conflicts WHERE series_id = :s ORDER BY created_at"""),
        {"s": str(series_id)}).mappings().all()
    character_states = db.execute(
        text("""SELECT s.id, c.name AS character, e.title AS event, s.location, s.costume, s.physical_condition,
                       s.age_or_stage, s.knowledge_state, s.state_changes
                FROM character_states s JOIN characters c ON c.id = s.character_id
                JOIN story_events e ON e.id = s.story_event_id
                WHERE c.series_id = :s ORDER BY e.chronological_position NULLS LAST"""),
        {"s": str(series_id)}).mappings().all()
    object_states = db.execute(
        text("""SELECT s.id, o.name AS object, e.title AS event, s.location, s.condition, s.state_notes,
                       ch.name AS owner
                FROM artifact_states s JOIN continuity_objects o ON o.id = s.continuity_object_id
                JOIN story_events e ON e.id = s.story_event_id
                LEFT JOIN characters ch ON ch.id = s.owner_character_id
                WHERE o.series_id = :s ORDER BY e.chronological_position NULLS LAST"""),
        {"s": str(series_id)}).mappings().all()
    return {"conflicts": [dict(c) for c in conflicts], "character_states": [dict(c) for c in character_states],
            "object_states": [dict(o) for o in object_states]}


@router.get("/series/{series_id}/master-script")
def get_master_script(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    script = db.execute(
        text("""SELECT id, version_number, title, summary, status, analysis_metadata, created_at FROM master_scripts
                WHERE series_id = :s AND status <> 'superseded' ORDER BY version_number DESC LIMIT 1"""),
        {"s": str(series_id)}).mappings().first()
    if script is None:
        raise HTTPException(status_code=404, detail="No master script yet")
    units = db.execute(
        text("""SELECT id, sequence_number, title, synopsis, content, character_names, location_names, estimated_seconds
                FROM story_units WHERE master_script_id = :m ORDER BY sequence_number"""),
        {"m": str(script["id"])}).mappings().all()
    return {**dict(script), "units": [dict(u) for u in units]}


@router.get("/series/{series_id}/episode-plans")
def list_episode_plans(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    rows = db.execute(
        text("""SELECT p.id, p.season_id, s.season_number, s.title AS season_title, p.episode_number, p.title,
                       p.synopsis, p.target_duration_seconds, p.opening_hook, p.climax_notes, p.ending_notes,
                       p.status, p.review_note, cardinality(p.source_unit_ids) AS unit_count,
                       (SELECT array_agg(name ORDER BY name) FROM characters WHERE id = ANY(p.character_ids)) AS characters,
                       (SELECT e.id FROM episodes e WHERE e.season_id = p.season_id AND e.episode_number = p.episode_number) AS episode_id
                FROM episode_plans p JOIN seasons s ON s.id = p.season_id
                WHERE s.series_id = :s ORDER BY p.episode_number"""),
        {"s": str(series_id)}).mappings().all()
    return {"count": len(rows), "items": [dict(r) for r in rows]}


@router.patch("/episode-plans/{plan_id}")
def update_episode_plan(plan_id: UUID, payload: PlanUpdate, db: Session = Depends(get_db)):
    plan = _owned_plan(db, plan_id)
    if plan["status"] == "approved":
        raise HTTPException(status_code=409, detail="Approved plans are already episodes; edit the episode instead")
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=400, detail="Nothing to update")
    assignments = ", ".join(f"{column} = :{column}" for column in changes)
    db.execute(text(f"UPDATE episode_plans SET {assignments}, updated_at = now() WHERE id = :id"),
               {**changes, "id": str(plan_id)})
    db.commit()
    return {"id": str(plan_id), "updated": list(changes)}


def _approve(db: Session, plan) -> str:
    episode_id = db.execute(
        text("""INSERT INTO episodes (series_id, season_id, episode_number, title, synopsis, target_duration_seconds,
                    master_script_id, source_unit_ids, climax_notes, generation_source)
                VALUES (:series, :season, :n, :title, :synopsis, :seconds, :m, :units, :climax, 'episode_segmentation')
                ON CONFLICT (series_id, episode_number) DO UPDATE SET title = EXCLUDED.title,
                    synopsis = EXCLUDED.synopsis, target_duration_seconds = EXCLUDED.target_duration_seconds,
                    source_unit_ids = EXCLUDED.source_unit_ids, climax_notes = EXCLUDED.climax_notes, updated_at = now()
                RETURNING id"""),
        {"series": str(plan["series_id"]), "season": str(plan["season_id"]), "n": plan["episode_number"],
         "title": plan["title"], "synopsis": plan["synopsis"], "seconds": plan["target_duration_seconds"] or 600,
         "m": str(plan["master_script_id"]) if plan["master_script_id"] else None,
         "units": plan["source_unit_ids"], "climax": plan["climax_notes"]},
    ).scalar_one()
    db.execute(text("UPDATE episode_plans SET status = 'approved', updated_at = now() WHERE id = :id"),
               {"id": str(plan["id"])})
    return str(episode_id)


@router.post("/episode-plans/{plan_id}/approve")
def approve_episode_plan(plan_id: UUID, db: Session = Depends(get_db)):
    plan = _owned_plan(db, plan_id)
    episode_id = _approve(db, plan)
    db.commit()
    return {"id": str(plan_id), "status": "approved", "episode_id": episode_id}


@router.post("/series/{series_id}/episode-plans/approve-all")
def approve_all_plans(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    plans = db.execute(
        text("""SELECT p.*, s.series_id FROM episode_plans p JOIN seasons s ON s.id = p.season_id
                WHERE s.series_id = :s AND p.status = 'draft' ORDER BY p.episode_number"""),
        {"s": str(series_id)}).mappings().all()
    episode_ids = [_approve(db, plan) for plan in plans]
    db.commit()
    return {"approved": len(episode_ids), "episode_ids": episode_ids}


@router.post("/episode-plans/{plan_id}/reject")
def reject_episode_plan(plan_id: UUID, payload: RejectRequest, db: Session = Depends(get_db)):
    plan = _owned_plan(db, plan_id)
    if plan["status"] == "approved":
        raise HTTPException(status_code=409, detail="Approved plans cannot be rejected")
    db.execute(text("UPDATE episode_plans SET status = 'rejected', review_note = :note, updated_at = now() WHERE id = :id"),
               {"id": str(plan_id), "note": payload.review_note})
    db.commit()
    return {"id": str(plan_id), "status": "rejected"}


@router.post("/episodes/{episode_id}/breakdown", status_code=202)
def queue_scene_breakdown(episode_id: UUID, db: Session = Depends(get_db)):
    episode = db.execute(text("SELECT series_id FROM episodes WHERE id = :id"), {"id": str(episode_id)}).mappings().first()
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode was not found")
    _series_owned(db, episode["series_id"])
    active = db.execute(
        text("""SELECT id FROM generation_jobs WHERE job_type = 'scene_breakdown' AND status IN ('queued', 'running')
                AND request_metadata ->> 'episode_id' = :e"""), {"e": str(episode_id)}).scalar()
    if active:
        raise HTTPException(status_code=409, detail="A breakdown for this episode is already queued or running")
    job = db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                VALUES ('scene_breakdown', 'queued', 'llm', CAST(:meta AS jsonb))
                RETURNING id, job_type, status, created_at"""),
        {"meta": json.dumps({"episode_id": str(episode_id)})}).mappings().one()
    db.commit()
    return dict(job)


@router.get("/episodes/{episode_id}/breakdown")
def get_breakdown(episode_id: UUID, db: Session = Depends(get_db)):
    episode = db.execute(text("SELECT series_id, breakdown_stale, continuity_notes FROM episodes WHERE id = :id"),
                         {"id": str(episode_id)}).mappings().first()
    if episode is None:
        raise HTTPException(status_code=404, detail="Episode was not found")
    _series_owned(db, episode["series_id"])
    scenes = db.execute(
        text("""SELECT id, scene_number, title, description, dialogue, continuity_state, environment_notes
                FROM scenes WHERE episode_id = :e ORDER BY scene_number"""), {"e": str(episode_id)}).mappings().all()
    shots = db.execute(
        text("""SELECT sh.scene_id, sh.shot_number, sh.description, sh.camera, sh.duration_seconds
                FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sc.episode_id = :e
                ORDER BY sc.scene_number, sh.shot_number"""), {"e": str(episode_id)}).mappings().all()
    by_scene: dict[str, list] = {}
    for shot in shots:
        by_scene.setdefault(str(shot["scene_id"]), []).append(
            {k: (float(v) if k == "duration_seconds" and v is not None else v) for k, v in shot.items() if k != "scene_id"})
    return {"count": len(scenes), "stale": episode["breakdown_stale"], "continuity_notes": episode["continuity_notes"],
            "items": [{**dict(s), "shots": by_scene.get(str(s["id"]), [])} for s in scenes]}
