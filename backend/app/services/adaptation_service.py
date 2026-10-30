"""Adaptation options: full, concentrated (filler removed), trailer and teaser."""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest
from app.schemas.llm_stages import FillerResult, HighlightResult
from app.services.llm_stage import LLMStageClient

FILLER_WINDOW = 40  # units per model call
MAX_SAVED_SHARE = 0.6  # a removed beat may not take more than this share of its unit
BOUNDS = {"trailer": (60, 240), "teaser": (10, 59)}
DEFAULT_SECONDS = {"trailer": 120, "teaser": 45}


def latest_master_script(db: Session, series_id: UUID):
    return db.execute(
        text("""SELECT id, summary FROM master_scripts WHERE series_id = :s AND status <> 'superseded'
                ORDER BY version_number DESC LIMIT 1"""), {"s": str(series_id)}).mappings().first()


def load_units(db: Session, master_script_id) -> list[dict]:
    rows = db.execute(
        text("""SELECT id, sequence_number, title, synopsis, content, character_names, estimated_seconds
                FROM story_units WHERE master_script_id = :m ORDER BY sequence_number"""),
        {"m": str(master_script_id)}).mappings().all()
    return [{"id": r["id"], "number": r["sequence_number"], "title": r["title"], "synopsis": r["synopsis"] or "",
             "beats": (r["content"] or {}).get("beats", []), "characters": r["character_names"],
             "screen_seconds": r["estimated_seconds"] or 30} for r in rows]


def _upsert(db: Session, series_id: UUID, kind: str, **fields) -> None:
    columns = ["master_script_id", "target_seconds", "duration_seconds", "status", "content", "error_summary"]
    values = {c: fields.get(c) for c in columns}
    values["content"] = json.dumps(values["content"] or {})
    values["status"] = values["status"] or "not_generated"
    db.execute(
        text("""INSERT INTO adaptations (series_id, kind, master_script_id, target_seconds, duration_seconds,
                    status, content, error_summary)
                VALUES (:s, :kind, :master_script_id, :target_seconds, :duration_seconds, :status,
                        CAST(:content AS jsonb), :error_summary)
                ON CONFLICT (series_id, kind) DO UPDATE SET master_script_id = EXCLUDED.master_script_id,
                    target_seconds = EXCLUDED.target_seconds, duration_seconds = EXCLUDED.duration_seconds,
                    status = EXCLUDED.status, content = EXCLUDED.content, error_summary = EXCLUDED.error_summary,
                    updated_at = now()"""),
        {"s": str(series_id), "kind": kind, **values})


def run_context(db: Session, series_id: UUID) -> tuple[UUID, str, str]:
    """Latest finished analysis run of a series, its profile and the detected story format."""
    from app.repositories.analysis_repository import list_source_chunks
    from app.services.story_analysis_service import detect_story_format

    run = db.execute(
        text("""SELECT id, source_id, profile FROM analysis_runs WHERE series_id = :s AND status = 'succeeded'
                ORDER BY created_at DESC LIMIT 1"""), {"s": str(series_id)}).mappings().first()
    if run is None:
        raise PermanentJobError("The series has no finished analysis run")
    return run["id"], str(run["profile"]), detect_story_format(list_source_chunks(db, run["source_id"]))


def selected_main(db: Session, series_id: UUID) -> str:
    kind = db.execute(text("SELECT kind FROM adaptations WHERE series_id = :s AND selected AND kind IN ('full', 'concentrated')"),
                      {"s": str(series_id)}).scalar()
    return kind or "full"


def build_full(db: Session, series_id: UUID, master_script_id) -> dict:
    units = load_units(db, master_script_id)
    total = sum(u["screen_seconds"] for u in units)
    _upsert(db, series_id, "full", master_script_id=master_script_id, duration_seconds=total, status="ready",
            content={"units": len(units)})
    return {"duration_seconds": total, "units": len(units)}


def detect_filler(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, master_script_id,
                  profile: str, story_format: str) -> dict:
    """Mark removable beats; the concentrated adaptation is the master script minus these."""
    units = load_units(db, master_script_id)
    by_number = {u["number"]: u for u in units}
    removed: list[dict] = []
    for start in range(0, len(units), FILLER_WINDOW):
        window = units[start:start + FILLER_WINDOW]
        request = LLMAnalysisRequest(
            task="filler", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={"units": [{"number": u["number"], "title": u["title"], "synopsis": u["synopsis"][:200],
                                   "beats": [f"{i}. {b}" for i, b in enumerate(u["beats"], start=1)],
                                   "screen_seconds": u["screen_seconds"]} for u in window]})
        key = f"{master_script_id}:{start // FILLER_WINDOW + 1:04d}"
        result: FillerResult = client.run(db, run_id, "filler", key, request, FillerResult)
        for item in result.removals:
            unit = by_number.get(item.unit)
            if unit is None:
                continue
            whole = item.beat is None
            if not whole and not (1 <= item.beat <= len(unit["beats"])):
                continue
            seconds = float(item.seconds_saved or 0)
            seconds = unit["screen_seconds"] if whole else min(seconds, unit["screen_seconds"] * MAX_SAVED_SHARE)
            if seconds <= 0:
                continue
            removed.append({"unit": item.unit, "unit_title": unit["title"], "beat": item.beat,
                            "beat_text": None if whole else unit["beats"][item.beat - 1],
                            "reason": item.reason or "", "seconds": int(seconds)})

    # A unit can lose at most its whole length, however many beats were flagged.
    saved: dict[int, int] = {}
    for item in removed:
        saved[item["unit"]] = min(by_number[item["unit"]]["screen_seconds"], saved.get(item["unit"], 0) + item["seconds"])
    full_total = sum(u["screen_seconds"] for u in units)
    total = full_total - sum(saved.values())
    _upsert(db, series_id, "concentrated", master_script_id=master_script_id, duration_seconds=total, status="ready",
            content={"removed": removed, "saved_seconds": sum(saved.values()), "full_seconds": full_total})
    return {"removed": len(removed), "saved_seconds": sum(saved.values()), "duration_seconds": total}


def effective_units(db: Session, series_id: UUID, master_script_id, kind: str) -> list[dict]:
    """Units with their screen time adjusted for the chosen adaptation; removed units are dropped."""
    units = load_units(db, master_script_id)
    if kind != "concentrated":
        return units
    row = db.execute(text("SELECT content FROM adaptations WHERE series_id = :s AND kind = 'concentrated' AND status = 'ready'"),
                     {"s": str(series_id)}).mappings().first()
    if row is None:
        raise PermanentJobError("The concentrated adaptation has not been generated yet")
    saved: dict[int, int] = {}
    for item in row["content"].get("removed", []):
        saved[item["unit"]] = saved.get(item["unit"], 0) + item["seconds"]
    kept = []
    for unit in units:
        seconds = unit["screen_seconds"] - saved.get(unit["number"], 0)
        if seconds > 0:
            kept.append({**unit, "screen_seconds": seconds})
    return kept


def removed_beats(db: Session, series_id: UUID) -> list[dict]:
    """Beats the scene breakdown must skip when the concentrated adaptation is selected."""
    row = db.execute(text("""SELECT content FROM adaptations WHERE series_id = :s AND kind = 'concentrated'
                             AND selected AND status = 'ready'"""), {"s": str(series_id)}).mappings().first()
    return [] if row is None else [i for i in row["content"].get("removed", []) if i.get("beat_text")]


def build_highlight(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, kind: str,
                    target_seconds: int, profile: str, story_format: str) -> dict:
    low, high = BOUNDS[kind]
    if not low <= target_seconds <= high:
        raise PermanentJobError(f"A {kind} must be between {low} and {high} seconds")
    script = latest_master_script(db, series_id)
    if script is None:
        raise PermanentJobError("The series has no master script yet")
    units = load_units(db, script["id"])
    characters = [r[0] for r in db.execute(
        text("SELECT name FROM characters WHERE series_id = :s AND merged_into_id IS NULL AND review_status <> 'stale'"),
        {"s": str(series_id)})]
    request = LLMAnalysisRequest(
        task="highlight", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
        task_input={"kind": kind, "target_seconds": target_seconds, "characters": characters,
                    "story_summary": script["summary"] or "",
                    "units": [{k: u[k] for k in ("number", "title", "synopsis", "beats", "screen_seconds")} for u in units]})
    result: HighlightResult = client.run(db, run_id, "highlight", f"{kind}:{script['id']}:{target_seconds}", request,
                                         HighlightResult)
    if not result.segments:
        raise PermanentJobError(f"The model returned no segments for the {kind}")
    segments = [s.model_dump() for s in result.segments]
    total = int(sum(s["seconds"] or 0 for s in segments))
    if kind == "teaser" and total > high:  # a teaser must stay under a minute: trim from the end
        running, kept = 0, []
        for segment in segments:
            if running + (segment["seconds"] or 0) > high and kept:
                break
            kept.append(segment)
            running += segment["seconds"] or 0
        segments, total = kept, int(running)
    _upsert(db, series_id, kind, master_script_id=script["id"], target_seconds=target_seconds, duration_seconds=total,
            status="ready", content={"title": result.title, "logline": result.logline, "segments": segments})
    return {"kind": kind, "duration_seconds": total, "segments": len(segments)}
