"""Objective measurements and decision logs saved per run, for calibration and regression checks."""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


def record_metric(db: Session, series_id: UUID, run_id: UUID | None, stage: str, metric: str, value: float,
                  detail: dict | None = None) -> None:
    """One value per run, stage and metric; recording again replaces the earlier number."""
    db.execute(text("DELETE FROM stage_metrics WHERE analysis_run_id IS NOT DISTINCT FROM CAST(:r AS uuid) "
                    "AND stage = :stage AND metric = :metric"),
               {"r": str(run_id) if run_id else None, "stage": stage, "metric": metric})
    db.execute(
        text("""INSERT INTO stage_metrics (series_id, analysis_run_id, stage, metric, value, detail)
                VALUES (:s, CAST(:r AS uuid), :stage, :metric, :value, CAST(:detail AS jsonb))"""),
        {"s": str(series_id), "r": str(run_id) if run_id else None, "stage": stage, "metric": metric,
         "value": float(value), "detail": json.dumps(detail or {})})


def log_decision(db: Session, series_id: UUID, run_id: UUID | None, stage: str, item_ref: dict, decision: str,
                 actor: str, detail: dict) -> None:
    db.execute(
        text("""INSERT INTO feedback_events (series_id, analysis_run_id, stage, item_ref, decision, actor, detail)
                VALUES (:s, CAST(:r AS uuid), :stage, CAST(:ref AS jsonb), :decision, :actor, CAST(:detail AS jsonb))"""),
        {"s": str(series_id), "r": str(run_id) if run_id else None, "stage": stage, "ref": json.dumps(item_ref),
         "decision": decision, "actor": actor, "detail": json.dumps(detail)})
