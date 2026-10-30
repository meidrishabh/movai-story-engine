"""Adaptation options: full, concentrated (filler removed), trailer and teaser."""
import json
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.providers.llm_base import LLMAnalysisRequest
from app.schemas.llm_stages import FillerResult, HighlightResult, JudgeResult
from app.services.llm_stage import LLMStageClient, provider_model
from app.services.metrics import log_decision, record_metric
from app.services.story_profiles import resolve_profile

FILLER_WINDOW = 40  # units per model call
MAX_SAVED_SHARE = 0.6  # a removed beat may not take more than this share of its unit
JUDGE_BATCH = 8  # candidates per judge call
CONTEXT_BEATS = 2  # beats shown before and after a candidate
MAIN_SHARE = 0.5  # people in more than this share of units are leads and do not count as reused later
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


def _current_cut(db: Session, series_id: UUID) -> dict | None:
    """The concentrated adaptation's content, when it is ready and was built from the latest master script."""
    script = latest_master_script(db, series_id)
    if script is None:
        return None
    return db.execute(
        text("""SELECT content FROM adaptations WHERE series_id = :s AND kind = 'concentrated' AND status = 'ready'
                AND master_script_id = :m"""), {"s": str(series_id), "m": str(script["id"])}).scalar()


def selected_main(db: Session, series_id: UUID) -> str:
    """Episodes are always planned from the cut (filler removed, every cut restorable); the whole story is the
    fallback until the cut exists or when it was built from an older master script."""
    return "concentrated" if _current_cut(db, series_id) is not None else "full"


def build_full(db: Session, series_id: UUID, master_script_id) -> dict:
    units = load_units(db, master_script_id)
    total = sum(u["screen_seconds"] for u in units)
    _upsert(db, series_id, "full", master_script_id=master_script_id, duration_seconds=total, status="ready",
            content={"units": len(units)})
    return {"duration_seconds": total, "units": len(units)}


def _terms(name: str) -> set[str]:
    """Full name plus the longer words of a multi-word name, lower-cased."""
    name = name.strip().lower()
    terms = {name}
    if len(name.split()) > 1:
        terms.update(w for w in re.split(r"\W+", name) if len(w) >= 5)
    return {t for t in terms if len(t) >= 3}


def _mentions(terms: set[str], text_: str) -> bool:
    return any(re.search(rf"\b{re.escape(t)}\b", text_) for t in terms)


def _reuse_index(db: Session, series_id: UUID, units: list[dict]) -> tuple[dict, list[dict]]:
    """People and objects that come back in later units, and the most mentioned characters."""
    unit_text = {u["number"]: " ".join([u["title"], u["synopsis"], *u["beats"]]).lower() for u in units}
    index: dict[str, tuple[set[str], set[int]]] = {}
    characters = []
    for table, is_character in (("characters", True), ("continuity_objects", False)):
        rows = db.execute(
            text(f"SELECT name, description FROM {table} WHERE series_id = :s AND merged_into_id IS NULL "
                 "AND review_status <> 'stale'"), {"s": str(series_id)}).all()
        for name, description in rows:
            terms = _terms(name)
            numbers = {n for n, t in unit_text.items() if _mentions(terms, t)}
            if is_character:
                characters.append({"name": name, "description": (description or "")[:100], "units": len(numbers)})
            if numbers and len(numbers) <= MAIN_SHARE * len(units):  # leads appear everywhere and prove nothing
                index[name] = (terms, numbers)
    characters.sort(key=lambda c: -c["units"])
    return index, [{k: c[k] for k in ("name", "description")} for c in characters[:15]]


def _reused_later(index: dict, unit_number: int, beat_text: str) -> list[str]:
    return [name for name, (terms, numbers) in index.items()
            if _mentions(terms, beat_text.lower()) and any(n > unit_number for n in numbers)]


def _brief(unit: dict | None) -> str | None:
    return None if unit is None else f"{unit['title']}: {unit['synopsis'][:160]}"


def detect_filler(db: Session, client: LLMStageClient, run_id: UUID, series_id: UUID, master_script_id,
                  profile: str, story_format: str) -> dict:
    """Find removable beats in two passes. Pass 1 proposes; a second reviewer with the story's context judges
    each one blind, and a code check looks for people and objects that return later. A beat is removed only when
    all agree; anything else stays in the story as a disputed marker the user can act on."""
    units = load_units(db, master_script_id)
    by_number = {u["number"]: u for u in units}
    script = latest_master_script(db, series_id)
    genre = db.execute(text("SELECT genre FROM series WHERE id = :s"), {"s": str(series_id)}).scalar()
    profile_key, story_profile = resolve_profile(genre)
    shown_profile = {k: story_profile[k] for k in ("label", "protect", "filler")}

    proposals: list[dict] = []
    for start in range(0, len(units), FILLER_WINDOW):
        window = units[start:start + FILLER_WINDOW]
        request = LLMAnalysisRequest(
            task="filler", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={"story_profile": shown_profile,
                        "units": [{"number": u["number"], "title": u["title"], "synopsis": u["synopsis"][:200],
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
            proposals.append({"unit": item.unit, "unit_title": unit["title"], "beat": item.beat,
                              "beat_text": None if whole else unit["beats"][item.beat - 1],
                              "reason": item.reason or "", "seconds": int(seconds)})

    index, characters = _reuse_index(db, series_id, units)
    candidates = []
    for number, item in enumerate(proposals, start=1):
        unit, beat = by_number[item["unit"]], item["beat"]
        subject = item["beat_text"] or " ".join([unit["title"], unit["synopsis"], *unit["beats"]])
        candidates.append({
            **item, "id": f"K{number}", "reused_later": _reused_later(index, item["unit"], subject),
            "before": [] if beat is None else unit["beats"][max(0, beat - 1 - CONTEXT_BEATS):beat - 1],
            "after": [] if beat is None else unit["beats"][beat:beat + CONTEXT_BEATS],
            "previous_unit": _brief(by_number.get(item["unit"] - 1)), "next_unit": _brief(by_number.get(item["unit"] + 1)),
        })

    verdicts: dict[str, object] = {}
    for start in range(0, len(candidates), JUDGE_BATCH):
        batch = candidates[start:start + JUDGE_BATCH]
        request = LLMAnalysisRequest(
            task="filler_judge", profile=profile, context_chunks=[], known_entities={}, story_format=story_format,
            task_input={"story_summary": (script["summary"] if script else "") or "", "story_profile": shown_profile,
                        "characters": characters,
                        "candidates": [{"id": c["id"], "unit": c["unit"], "unit_title": c["unit_title"],
                                        "beat": c["beat_text"] or "(the whole unit)", "before": c["before"],
                                        "after": c["after"], "previous_unit": c["previous_unit"],
                                        "next_unit": c["next_unit"], "reused_later": c["reused_later"]}
                                       for c in batch]})
        result: JudgeResult = client.run(db, run_id, "filler_judge", f"{master_script_id}:j{start // JUDGE_BATCH + 1:04d}",
                                         request, JudgeResult)
        verdicts.update({v.id: v for v in result.verdicts})

    removed: list[dict] = []
    disputed: list[dict] = []
    restored: list[dict] = []
    db.execute(text("DELETE FROM feedback_events WHERE analysis_run_id = :r AND stage = 'filler' AND actor = 'pipeline'"),
               {"r": str(run_id)})
    # What the user decided earlier wins over this run's verdict; beats are matched by their text because
    # beat numbers change when the master script is rebuilt.
    user_decisions = dict(db.execute(
        text("""SELECT DISTINCT ON (item_ref ->> 'beat_text') item_ref ->> 'beat_text', decision FROM feedback_events
                WHERE series_id = :s AND stage = 'filler' AND actor = 'user'
                ORDER BY item_ref ->> 'beat_text', created_at DESC"""), {"s": str(series_id)}).all())
    for candidate in candidates:
        verdict = verdicts.get(candidate["id"])
        judge_cut = verdict is not None and str(verdict.verdict).strip().lower() == "cut"
        item = {k: candidate[k] for k in ("unit", "unit_title", "beat", "beat_text", "reason", "seconds")}
        item.update(judge_reason=(verdict.reason if verdict else "") or "", reused_later=candidate["reused_later"])
        by_user = user_decisions.get(candidate["beat_text"]) if candidate["beat_text"] else None
        if by_user == "removed":
            removed.append({**item, "by": "user"})
            decision = "removed"
        elif by_user == "restored":
            restored.append({**item, "by": "user"})
            decision = "restored"
        elif judge_cut and not candidate["reused_later"]:
            removed.append(item)
            decision = "removed"
        else:
            item["why"] = "reused_later" if judge_cut else "judge_keep" if verdict else "judge_missing"
            disputed.append(item)
            decision = "disputed"
        log_decision(db, series_id, run_id, "filler", {"unit": item["unit"], "beat": item["beat"],
                                                        "beat_text": item["beat_text"]}, decision, "pipeline",
                     {"pass1_reason": item["reason"], "judge_verdict": verdict.verdict if verdict else None,
                      "judge_reason": item["judge_reason"], "reused_later": item["reused_later"],
                      "story_profile": profile_key, "proposal_model": provider_model(client.provider),
                      "judge_model": provider_model(client.judge_provider or client.provider)})

    # A beat the user cut stays cut even when this run's first pass no longer proposes it.
    handled = {c["beat_text"] for c in candidates if c["beat_text"]}
    for unit in units:
        for position, beat_text in enumerate(unit["beats"], start=1):
            if user_decisions.get(beat_text) == "removed" and beat_text not in handled:
                handled.add(beat_text)
                removed.append({"unit": unit["number"], "unit_title": unit["title"], "beat": position, "beat_text": beat_text,
                                "reason": "Cut by you.", "seconds": max(1, int(unit["screen_seconds"] / max(1, len(unit["beats"])))),
                                "judge_reason": "", "reused_later": [], "by": "user"})

    content = {"removed": removed, "disputed": disputed, "restored": restored, "story_profile": profile_key}
    total = _totals(content, units)
    _upsert(db, series_id, "concentrated", master_script_id=master_script_id, duration_seconds=total, status="ready",
            content=content)
    saved_total, full_total = content["saved_seconds"], content["full_seconds"]
    for name, value in (("candidates", len(candidates)), ("removed", len(removed)), ("disputed", len(disputed)),
                        ("agreement_rate", len(removed) / len(candidates) if candidates else 1.0),
                        ("saved_share", saved_total / full_total if full_total else 0.0)):
        record_metric(db, series_id, run_id, "filler", name, value, {"story_profile": profile_key})
    db.commit()
    return {"removed": len(removed), "disputed": len(disputed), "saved_seconds": saved_total,
            "duration_seconds": total}


def _totals(content: dict, units: list[dict]) -> int:
    """Fill in saved and full seconds from the removed beats and return the concentrated duration.
    A unit can lose at most its whole length, however many beats were flagged."""
    by_number = {u["number"]: u for u in units}
    saved: dict[int, int] = {}
    for item in content["removed"]:
        unit = by_number.get(item["unit"])
        if unit:
            saved[item["unit"]] = min(unit["screen_seconds"], saved.get(item["unit"], 0) + item["seconds"])
    content["saved_seconds"] = sum(saved.values())
    content["full_seconds"] = sum(u["screen_seconds"] for u in units)
    return content["full_seconds"] - content["saved_seconds"]


def apply_user_decision(db: Session, series_id: UUID, unit: int, beat: int | None, action: str) -> dict:
    """The user keeps a removed beat or cuts a disputed one. The decision is logged and survives regeneration."""
    row = db.execute(
        text("""SELECT master_script_id, content FROM adaptations WHERE series_id = :s AND kind = 'concentrated'
                AND status = 'ready' FOR UPDATE"""), {"s": str(series_id)}).mappings().first()
    if row is None:
        raise PermanentJobError("The concentrated adaptation has not been generated yet")
    content = row["content"]
    for key in ("removed", "disputed", "restored"):
        content.setdefault(key, [])
    source, target = (("removed", "restored") if action == "keep" else ("disputed", "removed"))
    found = next((i for i in content[source] if i["unit"] == unit and i.get("beat") == beat), None)
    if found is None and action == "cut":  # a beat the user earlier restored can be cut again
        source = "restored"
        found = next((i for i in content[source] if i["unit"] == unit and i.get("beat") == beat), None)
    if found is None:
        raise LookupError("That beat is not in the list it would move from")
    content[source].remove(found)
    content[target].append({**found, "by": "user"})
    total = _totals(content, load_units(db, row["master_script_id"]))
    _upsert(db, series_id, "concentrated", master_script_id=row["master_script_id"], duration_seconds=total,
            status="ready", content=content)
    log_decision(db, series_id, None, "filler", {"unit": unit, "beat": beat, "beat_text": found.get("beat_text")},
                 "restored" if action == "keep" else "removed", "user",
                 {"from": source, "pass1_reason": found.get("reason"), "judge_reason": found.get("judge_reason")})
    db.commit()
    return {"duration_seconds": total, **{k: content[k] for k in ("removed", "disputed", "restored", "saved_seconds")}}


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
    """Beats the scene breakdown must skip: the ones removed from the current cut."""
    content = _current_cut(db, series_id)
    return [] if content is None else [i for i in content.get("removed", []) if i.get("beat_text")]


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
