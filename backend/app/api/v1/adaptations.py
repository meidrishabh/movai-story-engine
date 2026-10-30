"""Adaptation options (full, concentrated, trailer, teaser) and the user's selection."""
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.api.v1.entities import _series_owned
from app.core.errors import PermanentJobError
from app.services.episode_repair_service import affected_episodes
from app.services.adaptation_service import (
    BOUNDS, DEFAULT_SECONDS, apply_user_decision, build_full, latest_master_script, selected_main)

router = APIRouter(prefix="/api/v1", tags=["adaptations"])

KINDS = ("full", "concentrated", "trailer", "teaser")
LABELS = {"full": "Full adaptation", "concentrated": "Concentrated adaptation", "trailer": "Trailer", "teaser": "Teaser"}


class SelectionRequest(BaseModel):
    main: Literal["full", "concentrated"]
    trailer_seconds: int | None = Field(default=None, description="Set to include a trailer (60-240 seconds)")
    teaser_seconds: int | None = Field(default=None, description="Set to include a teaser (10-59 seconds)")


class BeatDecision(BaseModel):
    unit: int
    beat: int | None = Field(default=None, description="Beat number inside the unit; empty for a whole-unit removal")
    action: Literal["keep", "cut"]


class GenerateRequest(BaseModel):
    target_seconds: int | None = None


def _queue(db: Session, job_type: str, metadata: dict) -> dict:
    return dict(db.execute(
        text("""INSERT INTO generation_jobs (job_type, status, provider, request_metadata)
                VALUES (CAST(:t AS job_type), 'queued', 'llm', CAST(:m AS jsonb))
                RETURNING id, job_type, status, created_at"""),
        {"t": job_type, "m": json.dumps(metadata)}).mappings().one())


def _active(db: Session, job_type: str, key: str, value: str):
    return db.execute(
        text("""SELECT id FROM generation_jobs WHERE job_type = CAST(:t AS job_type) AND status IN ('queued', 'running')
                AND request_metadata ->> :k = :v"""), {"t": job_type, "k": key, "v": value}).scalar()


def _options(db: Session, series_id: UUID) -> list[dict]:
    script = latest_master_script(db, series_id)
    if script is not None:
        existing = db.execute(
            text("SELECT 1 FROM adaptations WHERE series_id = :s AND kind = 'full' AND master_script_id = :m"),
            {"s": str(series_id), "m": str(script["id"])}).scalar()
        if not existing:
            build_full(db, series_id, script["id"])
            db.commit()
    rows = {r["kind"]: r for r in db.execute(
        text("SELECT * FROM adaptations WHERE series_id = :s"), {"s": str(series_id)}).mappings()}
    items = []
    for kind in KINDS:
        row = rows.get(kind)
        ready = row is not None and row["status"] == "ready"
        stale = bool(ready and script is not None and str(row["master_script_id"]) != str(script["id"]))
        content = row["content"] if row else {}
        item = {
            "kind": kind, "label": LABELS[kind], "group": "main" if kind in ("full", "concentrated") else "extra",
            "status": row["status"] if row else "not_generated",
            "available": ready and not stale, "stale": stale,
            "selected": bool(row and row["selected"]),
            "duration_seconds": row["duration_seconds"] if row else None,
            "target_seconds": row["target_seconds"] if row else None,
            "error": row["error_summary"] if row else None,
        }
        if kind in BOUNDS:
            item.update(min_seconds=BOUNDS[kind][0], max_seconds=BOUNDS[kind][1], default_seconds=DEFAULT_SECONDS[kind])
            item["summary"] = {"title": content.get("title"), "logline": content.get("logline"),
                               "segments": len(content.get("segments", []))} if ready else None
        if kind == "concentrated":
            item["removed"] = content.get("removed", []) if ready else []
            item["disputed"] = content.get("disputed", []) if ready else []
            item["restored"] = content.get("restored", []) if ready else []
            item["saved_seconds"] = content.get("saved_seconds") if ready else None
        items.append(item)
    return items


@router.get("/series/{series_id}/adaptations")
def list_adaptations(series_id: UUID, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    return {"items": _options(db, series_id)}


@router.put("/series/{series_id}/adaptation-selection")
def select_adaptations(series_id: UUID, payload: SelectionRequest, db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    options = {o["kind"]: o for o in _options(db, series_id)}
    if not options["full"]["available"]:
        raise HTTPException(status_code=409, detail="The story has no finished master script yet")
    if not options[payload.main]["available"]:
        raise HTTPException(status_code=409, detail=f"The {payload.main} adaptation is not available yet")
    for kind, seconds in (("trailer", payload.trailer_seconds), ("teaser", payload.teaser_seconds)):
        if seconds is not None and not BOUNDS[kind][0] <= seconds <= BOUNDS[kind][1]:
            raise HTTPException(status_code=400, detail=f"A {kind} must be {BOUNDS[kind][0]}-{BOUNDS[kind][1]} seconds")

    wanted: dict[str, int | None] = {payload.main: None}
    if payload.trailer_seconds is not None:
        wanted["trailer"] = payload.trailer_seconds
    if payload.teaser_seconds is not None:
        wanted["teaser"] = payload.teaser_seconds
    for kind in KINDS:
        db.execute(
            text("""INSERT INTO adaptations (series_id, kind, selected) VALUES (:s, :k, :sel)
                    ON CONFLICT (series_id, kind) DO UPDATE SET selected = EXCLUDED.selected, updated_at = now()"""),
            {"s": str(series_id), "k": kind, "sel": kind in wanted})
    db.commit()
    items = _options(db, series_id)
    to_generate = [
        {"kind": kind, "target_seconds": seconds} for kind, seconds in wanted.items()
        if kind in BOUNDS and not any(i["kind"] == kind and i["available"] and i["target_seconds"] == seconds for i in items)
    ]
    return {"items": items, "to_generate": to_generate}


@router.post("/series/{series_id}/adaptations/{kind}/generate", status_code=202)
def generate_adaptation(series_id: UUID, kind: Literal["concentrated", "trailer", "teaser"], payload: GenerateRequest,
                        db: Session = Depends(get_db)):
    _series_owned(db, series_id)
    if _active(db, "adaptation_generation", "series_id", str(series_id)):
        raise HTTPException(status_code=409, detail="An adaptation is already being generated for this series")
    seconds = payload.target_seconds
    if kind in BOUNDS:
        seconds = seconds or DEFAULT_SECONDS[kind]
        if not BOUNDS[kind][0] <= seconds <= BOUNDS[kind][1]:
            raise HTTPException(status_code=400, detail=f"A {kind} must be {BOUNDS[kind][0]}-{BOUNDS[kind][1]} seconds")
    if latest_master_script(db, series_id) is None:
        raise HTTPException(status_code=409, detail="The story has no finished master script yet")
    db.execute(
        text("""INSERT INTO adaptations (series_id, kind, target_seconds, status) VALUES (:s, :k, :t, 'generating')
                ON CONFLICT (series_id, kind) DO UPDATE SET status = 'generating', error_summary = NULL,
                    target_seconds = COALESCE(EXCLUDED.target_seconds, adaptations.target_seconds), updated_at = now()"""),
        {"s": str(series_id), "k": kind, "t": seconds})
    job = _queue(db, "adaptation_generation", {"series_id": str(series_id), "kind": kind, "target_seconds": seconds})
    db.commit()
    return job


@router.put("/series/{series_id}/adaptations/concentrated/beats")
def decide_beat(series_id: UUID, payload: BeatDecision, db: Session = Depends(get_db)):
    """Keep a removed beat (action keep) or cut a disputed one (action cut). Episode plans and breakdowns built from
    the old cut are not changed here; `affected_episodes` lists the approved episodes that contain the unit."""
    _series_owned(db, series_id)
    try:
        result = apply_user_decision(db, series_id, payload.unit, payload.beat, payload.action)
    except LookupError as error:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(error)) from error
    except PermanentJobError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(error)) from error
    result["affected_episodes"] = [str(e["id"]) for e in affected_episodes(db, series_id) if e["changed"]]
    result["repair_job"] = None
    if result["affected_episodes"]:  # one queued repair reads the latest cut, so a second click needs no second job
        queued = db.execute(
            text("""SELECT id FROM generation_jobs WHERE job_type = 'adaptation_generation' AND status = 'queued'
                    AND request_metadata ->> 'series_id' = :s AND request_metadata ->> 'kind' = 'repair'"""),
            {"s": str(series_id)}).scalar()
        job = {"id": queued} if queued else _queue(db, "adaptation_generation", {"series_id": str(series_id), "kind": "repair"})
        db.commit()
        result["repair_job"] = str(job["id"])
    return result


@router.post("/series/{series_id}/episode-plans/generate", status_code=202)
def generate_episode_plans(series_id: UUID, db: Session = Depends(get_db)):
    """(Re)plan seasons and episodes for the selected main adaptation."""
    _series_owned(db, series_id)
    if _active(db, "episode_segmentation", "plan_series_id", str(series_id)):
        raise HTTPException(status_code=409, detail="Planning is already queued or running for this series")
    if latest_master_script(db, series_id) is None:
        raise HTTPException(status_code=409, detail="The story has no finished master script yet")
    kind = selected_main(db, series_id)
    approved_other = db.execute(
        text("""SELECT 1 FROM episode_plans p JOIN seasons s ON s.id = p.season_id
                WHERE s.series_id = :s AND p.status = 'approved' AND p.adaptation_kind <> :k LIMIT 1"""),
        {"s": str(series_id), "k": kind}).scalar()
    if approved_other:
        raise HTTPException(
            status_code=409,
            detail=f"Episodes are already approved for another adaptation; a {kind} plan would duplicate them")
    job = _queue(db, "episode_segmentation", {"plan_series_id": str(series_id), "adaptation_kind": kind})
    db.commit()
    return job
