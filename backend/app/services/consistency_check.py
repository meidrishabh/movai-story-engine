"""Consistency check for a generated image against the approved references it was made from.

The check itself (a vision-model judge) belongs to the reference-image stage. This module is the hook: a judge is a
callable `judge(db, request_row) -> {"score": float | None, "flagged": bool, "notes": str}`. Register one with
`register_judge`, or merge a module the hook already looks for. With no judge the check is recorded as "skipped",
which never blocks the pipeline. The outcome is stored in `generation_requests.checks`.
"""
import importlib
import json
import logging
from collections.abc import Callable
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

log = logging.getLogger("consistency_check")

_judge: Callable | None = None
# (module, function) pairs the looks stage may provide; the first importable one is used.
_CANDIDATES = (("app.services.consistency_service", "judge_against_references"),
               ("app.services.reference_service", "judge_against_references"),
               ("app.services.reference_judge", "judge"))


def register_judge(judge: Callable | None) -> None:
    global _judge
    _judge = judge


def _find_judge() -> Callable | None:
    if _judge is not None:
        return _judge
    for module_name, function_name in _CANDIDATES:
        try:
            function = getattr(importlib.import_module(module_name), function_name, None)
        except ImportError:
            continue
        if callable(function):
            return function
    return None


def run_check(db: Session, request_id: UUID) -> dict:
    """Judge a finished image request against its references and store the verdict. Never raises: a broken judge is
    recorded as skipped so generation carries on. The caller commits."""
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).mappings().first()
    if row is None:
        raise LookupError("Request was not found")
    judge = _find_judge()
    if judge is None or not row["result_asset_id"] or not (row["reference_asset_ids"] or []):
        why = "No consistency judge is available yet" if judge is None else "Nothing to compare against"
        result = {"status": "skipped", "notes": why}
    else:
        try:
            verdict = judge(db, dict(row)) or {}
            result = {"status": "flagged" if verdict.get("flagged") else "passed", "score": verdict.get("score"),
                      "notes": verdict.get("notes", "")}
        except Exception as error:  # noqa: BLE001 - a judge failure must not fail the keyframe
            log.warning("Consistency judge failed for %s: %s", request_id, error)
            result = {"status": "skipped", "notes": f"The judge failed: {str(error)[:200]}"}
    db.execute(text("UPDATE generation_requests SET checks = CAST(:c AS jsonb) WHERE id = :r"),
               {"c": json.dumps(result), "r": str(request_id)})
    return result
