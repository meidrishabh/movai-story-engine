"""Partial generation scope: work on the characters, places and objects you need, and on a few scenes.

Two independent selections, both optional (nothing selected = everything):

* Reference scope (per series): which characters, costumes, places and objects get reference images. When the series
  is `limited`, only the listed targets are in scope. Out-of-scope targets are never requested, never waited for and
  never counted as missing; a shot that shows one just has no reference image for it (and a visible warning).
* Working scenes (per episode): the scenes keyframes, clips, sound and renders are made for. Every stage takes an
  explicit `scene_ids`; when it is not given, the saved working scenes are used.
"""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

ENTITY_KINDS = ("character", "costume", "place", "object")


def _arr(ids) -> str:
    return "{" + ",".join(str(i) for i in ids) + "}"


# --- scenes ---------------------------------------------------------------------------------------------------------

def get_working_scenes(db: Session, episode_id: UUID) -> list[str] | None:
    """The saved working scenes of an episode as id strings, or None when the whole episode is in play."""
    row = db.execute(text("SELECT scene_ids FROM episode_working_scenes WHERE episode_id = :e"),
                     {"e": str(episode_id)}).scalar()
    return [str(s) for s in row] if row else None


def set_working_scenes(db: Session, episode_id: UUID, scene_ids: list | None) -> list[str] | None:
    """Save the working scenes (None or an empty list = every scene). Scene ids of other episodes are rejected."""
    ids = [str(s) for s in (scene_ids or [])]
    if ids:
        valid = {str(r[0]) for r in db.execute(
            text("SELECT id FROM scenes WHERE episode_id = :e AND id = ANY(CAST(:i AS uuid[]))"),
            {"e": str(episode_id), "i": _arr(ids)})}
        unknown = [i for i in ids if i not in valid]
        if unknown:
            raise ValueError(f"These scenes are not in this episode: {', '.join(unknown)}")
    db.execute(
        text("""INSERT INTO episode_working_scenes (episode_id, scene_ids) VALUES (:e, CAST(:i AS uuid[]))
                ON CONFLICT (episode_id) DO UPDATE SET scene_ids = EXCLUDED.scene_ids, updated_at = now()"""),
        {"e": str(episode_id), "i": _arr(ids)})
    return ids or None


def resolve_scenes(db: Session, episode_id: UUID, explicit=None) -> list[str] | None:
    """`explicit` scene ids when given, else the saved working scenes, else None (every scene)."""
    if explicit:
        return [str(s) for s in explicit]
    return get_working_scenes(db, episode_id)


def scenes_by_number(db: Session, episode_id: UUID, first: int | None, last: int | None) -> list[str]:
    """Scene ids for a scene-number range (inclusive), for callers that think in 'scenes 3 to 5'."""
    rows = db.execute(
        text("""SELECT id FROM scenes WHERE episode_id = :e AND (CAST(:a AS int) IS NULL OR scene_number >= :a)
                AND (CAST(:b AS int) IS NULL OR scene_number <= :b) ORDER BY scene_number"""),
        {"e": str(episode_id), "a": first, "b": last}).all()
    return [str(r[0]) for r in rows]


def episode_scenes(db: Session, episode_id: UUID) -> dict:
    """What the scene picker shows: every scene with its shot count and whether it is selected."""
    selected = get_working_scenes(db, episode_id)
    rows = db.execute(
        text("""SELECT sc.id, sc.scene_number, sc.title, count(sh.id) AS shots, COALESCE(sum(sh.duration_seconds), 0) AS seconds
                FROM scenes sc LEFT JOIN shots sh ON sh.scene_id = sc.id WHERE sc.episode_id = :e
                GROUP BY sc.id ORDER BY sc.scene_number"""), {"e": str(episode_id)}).mappings().all()
    scenes = [{"id": str(r["id"]), "scene_number": r["scene_number"], "title": r["title"], "shots": r["shots"],
               "seconds": float(r["seconds"]), "selected": selected is None or str(r["id"]) in selected} for r in rows]
    return {"episode_id": str(episode_id), "all_scenes": selected is None, "scene_ids": selected or [str(s["id"]) for s in scenes],
            "selected_shots": sum(s["shots"] for s in scenes if s["selected"]), "scenes": scenes}


# --- reference targets ----------------------------------------------------------------------------------------------

def get_reference_scope(db: Session, series_id: UUID) -> dict:
    limited = bool(db.execute(text("SELECT limited FROM series_reference_scope WHERE series_id = :s"),
                              {"s": str(series_id)}).scalar())
    items = {k: [] for k in ENTITY_KINDS}
    for kind, entity_id in db.execute(text("SELECT entity_kind, entity_id FROM reference_scope_items WHERE series_id = :s"),
                                      {"s": str(series_id)}):
        items[kind].append(str(entity_id))
    return {"limited": limited, **{f"{k}s": v for k, v in items.items()}}


def set_reference_scope(db: Session, series_id: UUID, *, limited: bool, characters=(), costumes=(), places=(),
                        objects=()) -> dict:
    """Replace the reference scope. With `limited` false the lists are remembered but ignored."""
    db.execute(
        text("""INSERT INTO series_reference_scope (series_id, limited) VALUES (:s, :l)
                ON CONFLICT (series_id) DO UPDATE SET limited = EXCLUDED.limited, updated_at = now()"""),
        {"s": str(series_id), "l": limited})
    db.execute(text("DELETE FROM reference_scope_items WHERE series_id = :s"), {"s": str(series_id)})
    for kind, ids in (("character", characters), ("costume", costumes), ("place", places), ("object", objects)):
        for entity_id in dict.fromkeys(str(i) for i in ids):
            db.execute(text("""INSERT INTO reference_scope_items (series_id, entity_kind, entity_id) VALUES (:s, :k, :e)
                               ON CONFLICT DO NOTHING"""), {"s": str(series_id), "k": kind, "e": entity_id})
    return get_reference_scope(db, series_id)


class ScopeFilter:
    """A loaded reference scope: `allows(kind, id)` answers for one target without a query each time."""

    def __init__(self, scope: dict):
        self.limited = scope["limited"]
        self._ids = {k: set(scope[f"{k}s"]) for k in ENTITY_KINDS}

    def allows(self, kind: str, entity_id) -> bool:
        return (not self.limited) or str(entity_id) in self._ids[kind]


def scope_filter(db: Session, series_id: UUID) -> ScopeFilter:
    return ScopeFilter(get_reference_scope(db, series_id))


def in_scope(db: Session, series_id: UUID, kind: str, entity_id) -> bool:
    return scope_filter(db, series_id).allows(kind, entity_id)


# --- what the chosen scenes need ------------------------------------------------------------------------------------

def needed_for_scenes(db: Session, episode_id: UUID, scene_ids: list | None = None) -> dict:
    """The characters, places and objects that appear in the shots of the chosen scenes (every scene when None), as
    ids plus names. Uses the same matching the keyframe prompts use, so what is listed is what the prompts reference."""
    from app.services.prompt_builder import load_shot_context  # imported here: the builder imports services

    ids = scene_ids if scene_ids else None
    clause = "AND sc.id = ANY(CAST(:ids AS uuid[]))" if ids else ""
    params = {"e": str(episode_id)}
    if ids:
        params["ids"] = _arr(ids)
    shot_ids = [r[0] for r in db.execute(
        text(f"""SELECT sh.id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sc.episode_id = :e {clause}
                 ORDER BY sc.scene_number, sh.shot_number"""), params)]
    found = {"characters": {}, "places": {}, "objects": {}}
    for shot_id in shot_ids:
        ctx = load_shot_context(db, shot_id)
        for character in ctx["characters"]:
            found["characters"][character["id"]] = character["name"]
        if ctx["place"]:
            found["places"][ctx["place"]["id"]] = ctx["place"]["name"]
        for obj in ctx["objects"]:
            found["objects"][obj["id"]] = obj["name"]
    return {"shots": len(shot_ids),
            **{kind: [{"id": i, "name": n} for i, n in entries.items()] for kind, entries in found.items()}}


def select_needed_for_scenes(db: Session, series_id: UUID, episode_id: UUID, scene_ids: list | None = None,
                             *, keep_existing: bool = False) -> dict:
    """Limit the reference scope to what the chosen scenes need (and, with `keep_existing`, what was already selected)."""
    needed = needed_for_scenes(db, episode_id, scene_ids)
    current = get_reference_scope(db, series_id) if keep_existing else {"characters": [], "costumes": [], "places": [], "objects": []}
    merge = lambda old, new: list(dict.fromkeys([*old, *[n["id"] for n in new]]))  # noqa: E731
    return set_reference_scope(
        db, series_id, limited=True, characters=merge(current["characters"], needed["characters"]),
        costumes=current["costumes"], places=merge(current["places"], needed["places"]),
        objects=merge(current["objects"], needed["objects"]))


def reference_checklist(db: Session, series_id: UUID, episode_id: UUID, scene_ids: list | None = None) -> dict:
    """For the chosen scenes: what each stage still lacks. A step is the series-level reference work first, then the
    scene-level work (keyframes, sound, clips, renders). Returns `{"scene_ids", "shots", "stages": [...]}`."""
    scene_ids = resolve_scenes(db, episode_id, scene_ids)
    needed = needed_for_scenes(db, episode_id, scene_ids)
    scope = scope_filter(db, series_id)
    shot_filter = "AND sc.id = ANY(CAST(:ids AS uuid[]))" if scene_ids else ""
    params = {"e": str(episode_id), **({"ids": _arr(scene_ids)} if scene_ids else {})}
    shots = [str(r[0]) for r in db.execute(
        text(f"SELECT sh.id FROM shots sh JOIN scenes sc ON sc.id = sh.scene_id WHERE sc.episode_id = :e {shot_filter}"), params)]
    stages: list[dict] = []

    def stage(key: str, label: str, missing: list[str], total: int, hint: str = ""):
        stages.append({"key": key, "label": label, "total": total, "done": total - len(missing), "missing": missing[:20],
                       "missing_count": len(missing), "complete": not missing, "hint": hint})

    bible = db.execute(text("SELECT 1 FROM style_bibles WHERE series_id = :s AND status = 'approved'"), {"s": str(series_id)}).scalar()
    stage("style_bible", "Style bible approved", [] if bible else ["not approved"], 1, "Style page")
    anchor = db.execute(
        text("""SELECT 1 FROM generation_requests WHERE series_id = :s AND kind = 'style_anchor' AND review_status = 'approved'
                AND result_asset_id IS NOT NULL LIMIT 1"""), {"s": str(series_id)}).scalar()
    stage("style_anchor", "Style anchor picked", [] if anchor else ["not picked"], 1, "Reference images page")

    def approved_names(kind: str, entities: list[dict], by: str) -> list[str]:
        missing = []
        for entity in entities:
            if by == "character":
                target_ids = [str(r[0]) for r in db.execute(text("SELECT id FROM character_versions WHERE character_id = :c"), {"c": entity["id"]})]
            else:
                target_ids = [str(r[0]) for r in db.execute(text("SELECT id FROM entity_looks WHERE entity_id = :e"), {"e": entity["id"]})]
            ok = target_ids and db.execute(
                text("""SELECT 1 FROM generation_requests WHERE kind = :k AND target_id = ANY(CAST(:t AS uuid[]))
                        AND review_status = 'approved' AND result_asset_id IS NOT NULL LIMIT 1"""),
                {"k": kind, "t": _arr(target_ids)}).scalar()
            if not ok:
                missing.append(entity["name"] + ("" if scope.allows(by, entity["id"]) else " (not in scope: will be left out)"))
        return missing

    stage("characters", "Character images approved", approved_names("character_image", needed["characters"], "character"),
          len(needed["characters"]), "Reference images page")
    stage("places", "Place images approved", approved_names("place_image", needed["places"], "place"),
          len(needed["places"]), "Reference images page")
    stage("objects", "Object images approved", approved_names("object_image", needed["objects"], "object"),
          len(needed["objects"]), "Reference images page")

    def shots_with(kind: str, approved: bool = True) -> int:
        if not shots:
            return 0
        extra = "AND review_status = 'approved'" if approved else ""
        return db.execute(
            text(f"""SELECT count(DISTINCT target_id) FROM generation_requests WHERE kind = :k AND target_id = ANY(CAST(:t AS uuid[]))
                     AND status = 'succeeded' AND result_asset_id IS NOT NULL AND review_status <> 'rejected' {extra}"""),
            {"k": kind, "t": _arr(shots)}).scalar() or 0

    stage("keyframes", "Keyframes approved", [f"{len(shots) - shots_with('keyframe')} shots"] if shots_with("keyframe") < len(shots) else [], len(shots), "Keyframes page")
    stage("clips", "Video clips approved", [f"{len(shots) - shots_with('video_clip')} shots"] if shots_with("video_clip") < len(shots) else [], len(shots), "Video page")
    cue_total = db.execute(
        text("""SELECT count(*) FROM sound_cues WHERE episode_id = :e AND role = 'scene'
                AND (CAST(:n AS int) = 0 OR scene_id = ANY(CAST(:ids AS uuid[])))"""),
        {"e": str(episode_id), "n": len(scene_ids or []), "ids": _arr(scene_ids or [])}).scalar() or 0
    stage("sound", "Sound cues made", [] if cue_total else ["no sound cues yet"], 1, "Sound page")
    return {"episode_id": str(episode_id), "scene_ids": scene_ids, "shots": len(shots),
            "ready_to_render": all(s["complete"] for s in stages if s["key"] in ("keyframes", "clips")),
            "stages": stages}


def in_scope_target_ids(db: Session, series_id: UUID) -> list[str] | None:
    """Ids of reference requests' targets (character versions, costumes, entity looks) that are in scope, or None when
    the series' reference scope is not limited. Used to keep progress counts and the attention list scope-aware."""
    scope = get_reference_scope(db, series_id)
    if not scope["limited"]:
        return None
    ids: list[str] = []
    if scope["characters"]:
        ids += [str(r[0]) for r in db.execute(
            text("SELECT id FROM character_versions WHERE character_id = ANY(CAST(:c AS uuid[]))"), {"c": _arr(scope["characters"])})]
    ids += scope["costumes"]
    looks = scope["places"] + scope["objects"]
    if looks:
        ids += [str(r[0]) for r in db.execute(
            text("SELECT id FROM entity_looks WHERE series_id = :s AND entity_id = ANY(CAST(:e AS uuid[]))"),
            {"s": str(series_id), "e": _arr(looks)})]
    return ids
