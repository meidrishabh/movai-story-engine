"""What the generation stages need from a person, and what they cost.

`generation_attention` feeds the pipeline page's "needs your attention" list. `overview` feeds the spend and pause
panel: episode budgets (kept by video_service in `generation_budgets`), spend so far and a pause switch for the whole
series. The series pause holds every queued request, whatever its kind; requests already running finish.
"""
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.services import generation_service as generation
from app.services import video_service

REFERENCE_KINDS = ("style_anchor", "character_image", "place_image", "object_image")


def _array(values) -> str:
    return "{" + ",".join(values) + "}"


def _item(key: str, count: int, singular: str, plural: str, to: str) -> dict | None:
    if not count:
        return None
    return {"key": key, "count": count, "label": f"{count} {singular if count == 1 else plural}", "to": to}


# ----- series pause ----------------------------------------------------------------------------------------------

def series_paused(db: Session, series_id) -> bool:
    return bool(db.execute(text("SELECT paused FROM generation_controls WHERE series_id = :s"),
                           {"s": str(series_id)}).scalar())


def set_series_pause(db: Session, series_id: UUID, paused: bool) -> dict:
    """Pause or resume everything queued for a series. Resuming queues the requests the pause held. The caller commits."""
    db.execute(text("""INSERT INTO generation_controls (series_id, paused) VALUES (:s, :p)
                       ON CONFLICT (series_id) DO UPDATE SET paused = :p, updated_at = now()"""),
               {"s": str(series_id), "p": paused})
    released: list[str] = []
    if not paused:
        rows = db.execute(
            text("""SELECT * FROM generation_requests WHERE series_id = :s AND status = 'blocked'
                    AND params ->> 'held_reason' IS NOT NULL ORDER BY created_at"""), {"s": str(series_id)}).mappings().all()
        for row in rows:
            if video_service.hold_reason(db, row) is not None or not generation._deps_ready(db, row):  # noqa: SLF001
                continue
            db.execute(text("UPDATE generation_requests SET status = 'queued', params = params - 'held_reason' WHERE id = :r"),
                       {"r": str(row["id"])})
            generation._queue_job(db, row["id"], row["series_id"])  # noqa: SLF001 - same package
            released.append(str(row["id"]))
    return {"paused": paused, "released": len(released)}


# ----- the attention list ----------------------------------------------------------------------------------------

def generation_attention(db: Session, series_id: UUID) -> list[dict]:
    """Things the generation stages finished or stopped on that want a person. Each is {key, count, label, to}, with
    `to` a route relative to the series page."""
    params = {"s": str(series_id)}

    def count(sql: str, **more) -> int:
        return db.execute(text(sql), {**params, **more}).scalar() or 0

    items: list[dict | None] = []

    if not count("SELECT count(*) FROM style_bibles WHERE series_id = :s AND status = 'approved'"):
        items.append({"key": "style_bible", "count": 1, "label": "The style bible is not approved yet", "to": "../style"})

    latest_refs = """SELECT DISTINCT ON (kind, COALESCE(target_id::text, id::text), COALESCE(params ->> 'view', ''))
                            status, review_status, drift_flag
                     FROM generation_requests WHERE series_id = :s AND kind = ANY(CAST(:k AS text[]))
                     ORDER BY kind, COALESCE(target_id::text, id::text), COALESCE(params ->> 'view', ''), created_at DESC"""
    refs = db.execute(text(f"""SELECT count(*) FILTER (WHERE status = 'failed') AS failed,
                                     count(*) FILTER (WHERE status = 'succeeded' AND review_status = 'pending' AND drift_flag) AS flagged,
                                     count(*) FILTER (WHERE status = 'succeeded' AND review_status = 'pending'
                                                      AND NOT COALESCE(drift_flag, false)) AS waiting
                              FROM ({latest_refs}) x"""), {**params, "k": _array(REFERENCE_KINDS)}).mappings().one()
    items += [
        _item("references_flagged", refs["flagged"], "reference image flagged as drifting from its references",
              "reference images flagged as drifting from their references", "../references"),
        _item("references_failed", refs["failed"], "reference image failed", "reference images failed", "../references"),
        _item("references_waiting", refs["waiting"], "reference image waiting for approval",
              "reference images waiting for approval", "../references"),
    ]

    keyframes = db.execute(text("""SELECT count(*) FILTER (WHERE status = 'failed') AS failed,
                                          count(*) FILTER (WHERE review_status = 'rejected') AS rejected,
                                          count(*) FILTER (WHERE checks ->> 'status' = 'flagged' AND review_status = 'pending') AS flagged
                                   FROM (SELECT DISTINCT ON (target_id) status, review_status, checks FROM generation_requests
                                         WHERE series_id = :s AND kind = 'keyframe' ORDER BY target_id, created_at DESC) x"""),
                           params).mappings().one()
    items += [
        _item("keyframes_failed", keyframes["failed"], "keyframe failed", "keyframes failed", "../keyframes"),
        _item("keyframes_rejected", keyframes["rejected"], "keyframe rejected and not redone", "keyframes rejected and not redone", "../keyframes"),
        _item("keyframes_flagged", keyframes["flagged"], "keyframe flagged by the consistency check",
              "keyframes flagged by the consistency check", "../keyframes"),
    ]

    items += [
        _item("sound_overflow", count("""SELECT count(*) FROM sound_shot_fits f JOIN episodes e ON e.id = f.episode_id
                                         WHERE e.series_id = :s AND f.status = 'overflow'"""),
              "shot where the speech is longer than the shot", "shots where the speech is longer than the shot", "../sound"),
        _item("voices_no_consent", count("""SELECT count(*) FROM voice_casts WHERE series_id = :s AND voice <> ''
                                            AND NOT consent_given"""),
              "voice without recorded consent", "voices without recorded consent", "../voices"),
        _item("sound_failed", count("""SELECT count(*) FROM (SELECT DISTINCT ON (target_id) status FROM generation_requests
                                       WHERE series_id = :s AND target_type = 'sound_cue'
                                       ORDER BY target_id, created_at DESC) x WHERE status = 'failed'"""),
              "sound request failed", "sound requests failed", "../sound"),
    ]

    clips = db.execute(text("""SELECT count(*) FILTER (WHERE r.status = 'failed') AS failed,
                                      count(*) FILTER (WHERE r.status = 'succeeded' AND a.duration_seconds IS NOT NULL
                                           AND a.duration_seconds < sh.duration_seconds - :tol
                                           AND NOT COALESCE((r.params ->> 'hold_last_frame')::boolean, false)) AS short
                               FROM (SELECT DISTINCT ON (target_id) * FROM generation_requests
                                     WHERE series_id = :s AND kind = 'video_clip' ORDER BY target_id, created_at DESC) r
                               JOIN shots sh ON sh.id = r.target_id LEFT JOIN assets a ON a.id = r.result_asset_id"""),
                       {**params, "tol": settings.clip_duration_tolerance}).mappings().one()
    items += [
        _item("clips_failed", clips["failed"], "video clip failed", "video clips failed", "../video"),
        _item("clips_short", clips["short"], "video clip shorter than its shot", "video clips shorter than their shots", "../video"),
    ]
    over_budget = paused = 0
    for episode in _episodes(db, series_id):
        budget = video_service.get_budget(db, episode["id"])
        over_budget += 1 if budget["over_cost"] else 0
        paused += 1 if budget["paused"] else 0
    items += [
        _item("budget_over", over_budget, "episode over its cost cap", "episodes over their cost cap", "../video"),
        _item("episodes_paused", paused, "episode paused", "episodes paused", "../video"),
    ]
    if series_paused(db, series_id):
        items.append({"key": "series_paused", "count": 1, "label": "Generation is paused for this series", "to": "../pipeline"})

    items.append(_item("renders_failed", count("""SELECT count(*) FROM (SELECT DISTINCT ON (episode_id, kind) status FROM episode_renders
                                                  WHERE series_id = :s ORDER BY episode_id, kind, created_at DESC) x
                                                  WHERE status = 'failed'"""),
                       "episode render failed", "episode renders failed", "../video"))
    return [i for i in items if i]


# ----- the spend and budget overview -----------------------------------------------------------------------------

def _episodes(db: Session, series_id: UUID) -> list[dict]:
    return [dict(r) for r in db.execute(
        text("SELECT id, episode_number, title FROM episodes WHERE series_id = :s ORDER BY episode_number"),
        {"s": str(series_id)}).mappings()]


def overview(db: Session, series_id: UUID) -> dict:
    """Spend, request counts and budget state for the series and each episode."""
    spent = {row["episode_id"]: row for row in db.execute(
        text("""WITH owned AS (
                    SELECT r.id, r.status, r.cost, e.id AS episode_id FROM generation_requests r
                      JOIN shots sh ON r.target_type = 'shot' AND sh.id = r.target_id
                      JOIN scenes sc ON sc.id = sh.scene_id JOIN episodes e ON e.id = sc.episode_id
                     WHERE r.series_id = :s
                    UNION ALL
                    SELECT r.id, r.status, r.cost, c.episode_id FROM generation_requests r
                      JOIN sound_cues c ON r.target_type = 'sound_cue' AND c.id = r.target_id
                     WHERE r.series_id = :s AND c.episode_id IS NOT NULL)
                SELECT episode_id, COALESCE(sum(cost), 0) AS spend, count(*) AS requests,
                       count(*) FILTER (WHERE status = 'failed') AS failed,
                       count(*) FILTER (WHERE status IN ('queued', 'running', 'blocked', 'awaiting_input')) AS open
                FROM owned GROUP BY episode_id"""), {"s": str(series_id)}).mappings()}
    episodes = []
    for episode in _episodes(db, series_id):
        budget = video_service.get_budget(db, episode["id"])
        row = spent.get(episode["id"])
        episodes.append({"episode_id": str(episode["id"]), "episode_number": episode["episode_number"], "title": episode["title"],
                         "spend": float(row["spend"]) if row else 0.0, "requests": row["requests"] if row else 0,
                         "failed": row["failed"] if row else 0, "open": row["open"] if row else 0, "budget": budget})
    totals = db.execute(
        text("""SELECT COALESCE(sum(cost), 0) AS spend, count(*) AS requests,
                       count(*) FILTER (WHERE status = 'blocked' AND params ->> 'held_reason' IS NOT NULL) AS held,
                       count(*) FILTER (WHERE status = 'awaiting_input') AS awaiting_input
                FROM generation_requests WHERE series_id = :s"""), {"s": str(series_id)}).mappings().one()
    by_kind = [{"kind": r["kind"], "requests": r["requests"], "spend": float(r["spend"])} for r in db.execute(
        text("""SELECT kind, count(*) AS requests, COALESCE(sum(cost), 0) AS spend FROM generation_requests
                WHERE series_id = :s GROUP BY kind ORDER BY kind"""), {"s": str(series_id)}).mappings()]
    return {"paused": series_paused(db, series_id), "spend": float(totals["spend"]), "requests": totals["requests"],
            "held": totals["held"], "awaiting_input": totals["awaiting_input"], "by_kind": by_kind, "episodes": episodes,
            "providers": {"image": settings.image_provider, "video": settings.video_provider,
                          "voice": settings.voice_provider, "music": settings.music_provider}}
