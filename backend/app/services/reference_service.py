"""Reference images: the approved pictures every later image and clip is made from.

A reference is a `generation_requests` row with kind style_anchor / character_image / place_image / object_image,
`review_status = 'approved'` and a `result_asset_id`. Its target is:
  style_anchor     none (one per series)
  character_image  target_type 'character_version' (a character's sheet) or 'costume'
  place_image      target_type 'entity_look' (a place's look sheet)
  object_image     target_type 'entity_look' (an object's look sheet)
`params.view` says which picture of the target it is (front, side, ...). Other views of a target depend on its first
view, so they are made only after the user has approved it, and they get its image as a reference.

Other stages ask for pictures with `get_style_anchor` and `get_approved_references`.
"""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.providers.media_base import ReferenceImage
from app.services import generation_service as generation
from app.services.asset_store import get_asset, get_storage
from app.services.consistency_judge import judge_images
from app.services.style_bible_service import get_approved, negative_block, style_block

REFERENCE_KINDS = ("style_anchor", "character_image", "place_image", "object_image")
# view -> (label, aspect ratio, instruction). The first view of a target is made first; the rest wait for its approval.
CHARACTER_VIEWS = {
    "front": ("Front", "3:4", "Full-body character reference, front view, standing straight, arms relaxed, neutral expression, plain light-grey background, even lighting."),
    "three_quarter": ("Three-quarter", "3:4", "Same character, full-body three-quarter view, neutral pose, plain light-grey background. Keep the face, build, clothing and colours exactly as in the attached reference."),
    "side": ("Side", "3:4", "Same character, full-body side profile view, neutral pose, plain light-grey background. Keep the face, build, clothing and colours exactly as in the attached reference."),
    "expression_sheet": ("Expressions", "16:9", "Same character: head-and-shoulders expression sheet in a grid of six expressions (neutral, happy, sad, angry, surprised, afraid), plain background. Match the attached reference exactly."),
}
COSTUME_VIEWS = {
    "costume_front": ("Costume", "3:4", "Same character, full-body front view, wearing the costume described below instead of the usual clothing. Keep the face and build exactly as in the attached reference. Plain light-grey background."),
}
PLACE_VIEWS = {
    "establishing": ("Establishing", "16:9", "Establishing view of this place: wide, clear, no people, showing its layout and atmosphere."),
    "alternate_angle": ("Other angle", "16:9", "The same place from a different angle, no people. Keep the architecture, materials and colours exactly as in the attached reference."),
}
OBJECT_VIEWS = {
    "hero": ("Hero", "1:1", "Single object reference, centred on a plain light-grey background, clear and well lit, shown at its usual size and condition."),
    "detail": ("Detail", "1:1", "Close-up of the same object showing its distinctive details. Keep the shape, materials and colours exactly as in the attached reference."),
}
VIEWS = {"character_version": CHARACTER_VIEWS, "costume": COSTUME_VIEWS, "place": PLACE_VIEWS, "object": OBJECT_VIEWS}
EXTRA_NEGATIVE = "text, captions, labels, watermark, extra limbs, deformed hands"
ANCHOR_VARIATIONS = (
    "a wide view of the story's main setting",
    "a quiet moment with a single figure seen from behind in the setting",
    "an object that matters to the story, in its setting",
    "the mood of the story's turning point",
)
BLOCKED_OR_OPEN = ("queued", "blocked", "running", "awaiting_input")


# --- what other stages read -------------------------------------------------------------------------------------

def _load(db: Session, asset_id, role: str) -> ReferenceImage | None:
    asset = get_asset(db, asset_id)
    if asset is None or asset["kind"] != "image":
        return None
    try:
        data = get_storage().read(asset["storage_key"])
    except Exception:  # noqa: BLE001 - a missing file means no reference, not a crash
        return None
    return ReferenceImage(data=data, mime_type=asset["mime_type"], role=role, asset_id=str(asset_id))


def get_style_anchor(db: Session, series_id: UUID) -> ReferenceImage | None:
    """The approved style anchor frame (role 'style'), or None."""
    asset_id = db.execute(
        text("""SELECT result_asset_id FROM generation_requests WHERE series_id = :s AND kind = 'style_anchor'
                AND review_status = 'approved' AND result_asset_id IS NOT NULL
                ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT 1"""), {"s": str(series_id)}).scalar()
    return _load(db, asset_id, "style") if asset_id else None


def _approved_rows(db: Session, kind: str, target_ids: list) -> list[dict]:
    """The newest approved image of each view of each target."""
    if not target_ids:
        return []
    rows = db.execute(
        text("""SELECT DISTINCT ON (target_id, params ->> 'view') id, target_id, result_asset_id, params ->> 'view' AS view
                FROM generation_requests
                WHERE kind = :k AND review_status = 'approved' AND result_asset_id IS NOT NULL
                  AND target_id = ANY(CAST(:t AS uuid[]))
                ORDER BY target_id, params ->> 'view', reviewed_at DESC NULLS LAST, created_at DESC"""),
        {"k": kind, "t": "{" + ",".join(str(t) for t in target_ids) + "}"}).mappings().all()
    return [dict(r) for r in rows]


def get_approved_references(db: Session, series_id: UUID, character_version_ids=(), place_id: UUID | None = None,
                            object_ids=(), *, costume_ids=(), max_per_target: int = 2) -> list[ReferenceImage]:
    """Approved reference images for the things in a shot, ready to attach to a keyframe request.

    `place_id` and `object_ids` may be the entity ids (locations / continuity_objects) or the entity_look ids; both
    are accepted. At most `max_per_target` views per target are returned, in the order front, three-quarter, side,
    expressions (places: establishing, other angle; objects: hero, detail). The style anchor is not included: ask
    for it with `get_style_anchor`.
    """
    look_targets = [i for i in ([place_id] if place_id else []) + list(object_ids)]
    if look_targets:
        ids = "{" + ",".join(str(i) for i in look_targets) + "}"
        look_ids = [r[0] for r in db.execute(
            text("""SELECT id FROM entity_looks WHERE series_id = :s
                    AND (id = ANY(CAST(:i AS uuid[])) OR entity_id = ANY(CAST(:i AS uuid[])))"""),
            {"s": str(series_id), "i": ids})]
    else:
        look_ids = []
    groups = [("character_image", list(character_version_ids), CHARACTER_VIEWS),
              ("character_image", list(costume_ids), COSTUME_VIEWS),
              ("place_image", look_ids, PLACE_VIEWS), ("object_image", look_ids, OBJECT_VIEWS)]
    out: list[ReferenceImage] = []
    seen: set[str] = set()
    for kind, targets, views in groups:
        order = list(views)
        by_target: dict[str, list[dict]] = {}
        for row in _approved_rows(db, kind, targets):
            if row["view"] in order:
                by_target.setdefault(str(row["target_id"]), []).append(row)
        for target_rows in by_target.values():
            for row in sorted(target_rows, key=lambda r: order.index(r["view"]))[:max_per_target]:
                if str(row["result_asset_id"]) in seen:
                    continue
                image = _load(db, row["result_asset_id"], "reference")
                if image:
                    seen.add(str(row["result_asset_id"]))
                    out.append(image)
    return out


# --- consistency check ------------------------------------------------------------------------------------------

def check_drift(db: Session, request_id: UUID) -> dict | None:
    """Compare a finished image with the approved images of the same target and record score and flag on the
    request. Never raises. Returns the recorded values, or None when the request has no image."""
    try:
        row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r"), {"r": str(request_id)}).mappings().first()
        if row is None or not row["result_asset_id"]:
            return None
        image = _load(db, row["result_asset_id"], "reference")
        if image is None:
            return None
        params = row["params"] or {}
        references: list[ReferenceImage] = []
        if row["target_id"]:
            rows = db.execute(
                text("""SELECT DISTINCT ON (params ->> 'view') result_asset_id FROM generation_requests
                        WHERE kind = :k AND target_id = :t AND id <> :r AND review_status = 'approved'
                          AND result_asset_id IS NOT NULL
                        ORDER BY params ->> 'view', reviewed_at DESC NULLS LAST"""),
                {"k": row["kind"], "t": str(row["target_id"]), "r": str(request_id)}).all()
            references = [i for i in (_load(db, r[0], "reference") for r in rows) if i]
            base_target = params.get("character_version_id")
            if base_target:  # a costume is judged against the character it dresses
                base = db.execute(
                    text("""SELECT result_asset_id FROM generation_requests WHERE kind = 'character_image'
                            AND target_id = :t AND review_status = 'approved' AND result_asset_id IS NOT NULL
                            ORDER BY reviewed_at DESC NULLS LAST LIMIT 1"""), {"t": str(base_target)}).scalar()
                loaded = _load(db, base, "reference") if base else None
                if loaded:
                    references.insert(0, loaded)
        subject = f"{params.get('subject', 'the subject')} ({str(params.get('view', '')).replace('_', ' ')})"
        result = judge_images(subject, image, references)
    except Exception as error:  # noqa: BLE001 - recorded, never raised
        return _record(db, request_id, None, False, f"The check failed: {str(error)[:300]}", "error")
    return _record(db, request_id, result.score, result.drift, result.notes, result.judge)


def _record(db: Session, request_id, score, drift: bool, notes: str, judge: str) -> dict:
    db.execute(
        text("""UPDATE generation_requests SET drift_score = :score, drift_flag = :flag, drift_notes = :notes,
                       drift_judge = :judge, drift_checked_at = now() WHERE id = :r"""),
        {"score": score, "flag": drift, "notes": notes, "judge": judge, "r": str(request_id)})
    return {"score": score, "flag": drift, "notes": notes, "judge": judge}


# --- making the requests ----------------------------------------------------------------------------------------

def _bible(db: Session, series_id: UUID) -> dict:
    bible = get_approved(db, series_id)
    if bible is None:
        raise ValueError("Approve the style bible first: every reference image is made from it.")
    return bible


def _negative(bible: dict) -> str:
    return ", ".join(p for p in (negative_block(bible), EXTRA_NEGATIVE) if p)


def _latest(db: Session, kind: str, target_id, view: str) -> dict | None:
    """The newest request for a target's view that is not a rejected attempt."""
    row = db.execute(
        text("""SELECT * FROM generation_requests WHERE kind = :k AND target_id = :t AND params ->> 'view' = :v
                AND status <> 'rejected' ORDER BY created_at DESC LIMIT 1"""),
        {"k": kind, "t": str(target_id), "v": view}).mappings().first()
    return dict(row) if row else None


def _approved_asset(db: Session, kind: str, target_id, view: str):
    return db.execute(
        text("""SELECT result_asset_id FROM generation_requests WHERE kind = :k AND target_id = :t
                AND params ->> 'view' = :v AND review_status = 'approved' AND result_asset_id IS NOT NULL
                ORDER BY reviewed_at DESC NULLS LAST, created_at DESC LIMIT 1"""),
        {"k": kind, "t": str(target_id), "v": view}).scalar()


def _lines(*pairs: tuple[str, object]) -> str:
    out = []
    for label, value in pairs:
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value)
        if value and str(value).strip():
            out.append(f"{label}: {str(value).strip()}")
    return "\n".join(out)


def generate_style_anchors(db: Session, series_id: UUID, count: int = 4) -> list[dict]:
    """Candidate frames that show the series' look. The user picks one with `pick_style_anchor`."""
    bible = _bible(db, series_id)
    series = db.execute(text("SELECT title, premise, genre FROM series WHERE id = :s"), {"s": str(series_id)}).mappings().one()
    created = []
    for index in range(max(1, min(count, len(ANCHOR_VARIATIONS)))):
        prompt = (f"{style_block(bible)}\n\nStyle anchor frame for the series \"{series['title']}\". "
                  f"{(series['premise'] or '')[:400]}\n{_lines(('Genre', series['genre']))}\n"
                  f"Show {ANCHOR_VARIATIONS[index]}. It must set the look of the whole series. No text, no captions.")
        created.append(generation.create_request(
            db, series_id, "style_anchor", prompt, negative_prompt=_negative(bible),
            params={"aspect_ratio": "16:9", "seed": 1000 + index, "view": "anchor", "subject": "the style anchor frame"}))
    return created



def pick_style_anchor(db: Session, series_id: UUID, request_id: UUID) -> dict:
    """Make this candidate the series' style anchor. The earlier anchor and the other finished candidates are set aside."""
    row = db.execute(text("SELECT * FROM generation_requests WHERE id = :r AND series_id = :s AND kind = 'style_anchor'"),
                     {"r": str(request_id), "s": str(series_id)}).mappings().first()
    if row is None:
        raise LookupError("Style anchor was not found")
    result = generation.review_request(db, request_id, "approve", "Picked as the style anchor.")
    db.execute(
        text("""UPDATE generation_requests SET status = 'rejected', review_status = 'rejected', reviewed_at = now(),
                       review_note = 'Another frame was picked as the style anchor.'
                WHERE series_id = :s AND kind = 'style_anchor' AND id <> :r AND status = 'succeeded'"""),
        {"s": str(series_id), "r": str(request_id)})
    return result


def _anchor_asset(db: Session, series_id: UUID):
    anchor = get_style_anchor(db, series_id)
    if anchor is None:
        raise ValueError("Pick a style anchor first: it is attached to every reference image.")
    return UUID(anchor.asset_id)


def _make_view(db: Session, series_id: UUID, bible: dict, anchor_id, *, kind: str, target_type: str, target_id,
               view: str, views: dict, body: str, subject: str, first_view: str, extra_params: dict | None = None,
               force: bool = False) -> tuple[dict | None, bool]:
    """Create the request for one view of one target unless one is already open. Returns (request row, created)."""
    existing = _latest(db, kind, target_id, view)
    if existing and not force:
        return existing, False
    label, aspect, instruction = views[view]
    refs = [anchor_id]
    prior = _approved_asset(db, kind, target_id, view)
    if prior:
        refs.append(prior)  # a regenerated picture keeps the look of the one it replaces
    params = {"aspect_ratio": aspect, "view": view, "subject": subject, **(extra_params or {})}
    depends: list[UUID] = []
    if view != first_view:
        first = _latest(db, kind, target_id, first_view)
        if first is None:
            raise ValueError(f"The {first_view} view must be requested first")
        depends = [first["id"]]
        params.update({"deps_need_approval": True, "use_dependency_results": True})
    prompt = f"{style_block(bible)}\n\n{instruction}\n{body}\nNo text, no captions."
    created = generation.create_request(
        db, series_id, kind, prompt, target_type=target_type, target_id=target_id,
        negative_prompt=_negative(bible), params=params, reference_asset_ids=refs, depends_on=depends)
    return created, True


def _character_sheets(db: Session, series_id: UUID, character_id=None) -> list[dict]:
    rows = db.execute(
        text("""SELECT DISTINCT ON (v.character_id) v.id AS version_id, v.character_id, c.name, c.role, v.version_number,
                       v.description, v.face_and_body_design, v.clothing_and_accessories, v.distinctive_features,
                       v.color_palette, v.status
                FROM character_versions v JOIN characters c ON c.id = v.character_id
                WHERE c.series_id = :s AND c.merged_into_id IS NULL AND v.status IN ('draft', 'approved')
                  AND (CAST(:c AS uuid) IS NULL OR c.id = CAST(:c AS uuid))
                ORDER BY v.character_id, (v.status = 'approved') DESC, v.version_number DESC"""),
        {"s": str(series_id), "c": str(character_id) if character_id else None}).mappings().all()
    sheets = [dict(r) for r in rows]
    for sheet in sheets:
        sheet["costumes"] = [dict(c) for c in db.execute(
            text("""SELECT id, name, description, color_palette, accessories, state_notes FROM costumes
                    WHERE character_id = :c AND approval_status IN ('draft', 'approved') ORDER BY created_at"""),
            {"c": str(sheet["character_id"])}).mappings()]
    return sheets


def _entity_looks(db: Session, series_id: UUID, entity_type: str) -> list[dict]:
    rows = db.execute(
        text("""SELECT DISTINCT ON (l.entity_id) l.id, l.entity_id, l.description, l.form, l.atmosphere,
                       l.distinctive_features, l.color_palette, l.status, COALESCE(loc.name, obj.name) AS name
                FROM entity_looks l
                LEFT JOIN locations loc ON l.entity_type = 'location' AND loc.id = l.entity_id
                LEFT JOIN continuity_objects obj ON l.entity_type = 'object' AND obj.id = l.entity_id
                WHERE l.series_id = :s AND l.entity_type = :t AND l.status IN ('draft', 'approved')
                  AND COALESCE(loc.merged_into_id, obj.merged_into_id) IS NULL
                ORDER BY l.entity_id, (l.status = 'approved') DESC, l.version_number DESC"""),
        {"s": str(series_id), "t": entity_type}).mappings().all()
    return [dict(r) for r in rows]


def _character_body(sheet: dict) -> str:
    return _lines(("Character", sheet["name"]), ("Role", sheet.get("role")), ("Description", sheet["description"]),
                  ("Face and body", sheet["face_and_body_design"]), ("Clothing", sheet["clothing_and_accessories"]),
                  ("Distinctive features", sheet["distinctive_features"]), ("Colours", sheet["color_palette"]))


def _look_body(label: str, look: dict) -> str:
    return _lines((label, look["name"]), ("Description", look["description"]), ("Form", look["form"]),
                  ("Atmosphere", look["atmosphere"]), ("Distinctive features", look["distinctive_features"]),
                  ("Colours", look["color_palette"]))


def generate_target(db: Session, series_id: UUID, target_type: str, target_id: UUID, *, views: list[str] | None = None,
                    force: bool = False) -> list[dict]:
    """Request the pictures of one target. Without `force`, views that already have an open or finished request
    are left alone. With it, a fresh attempt is made (the approved picture of that view is attached as a reference).
    Returns the requests created. The caller commits."""
    bible = _bible(db, series_id)
    anchor_id = _anchor_asset(db, series_id)
    made: list[dict] = []

    def run(kind, tt, tid, view_set, body, subject, extra=None):
        order = list(view_set)
        wanted = [v for v in (views or order) if v in view_set]
        if not wanted:
            raise ValueError(f"Unknown view for {tt}")
        first_view = order[0]
        if first_view not in wanted and _latest(db, kind, tid, first_view) is None:
            wanted.insert(0, first_view)
        for view in sorted(wanted, key=order.index):
            row, created = _make_view(db, series_id, bible, anchor_id, kind=kind, target_type=tt, target_id=tid,
                                      view=view, views=view_set, body=body, subject=subject, first_view=first_view,
                                      extra_params=extra, force=force and view in (views or order))
            if created:
                made.append(row)

    if target_type == "character_version":
        sheet = next((s for s in _character_sheets(db, series_id) if s["version_id"] == target_id), None)
        if sheet is None:
            raise LookupError("Character sheet was not found")
        run("character_image", "character_version", target_id, CHARACTER_VIEWS, _character_body(sheet), sheet["name"])
    elif target_type == "costume":
        for sheet in _character_sheets(db, series_id):
            costume = next((c for c in sheet["costumes"] if c["id"] == target_id), None)
            if costume:
                break
        else:
            raise LookupError("Costume was not found")
        front = _latest(db, "character_image", sheet["version_id"], "front")
        if front is None:  # the costume is drawn from the character's front view, so that must exist first
            made +=[r for r, c in [_make_view(db, series_id, bible, anchor_id, kind="character_image",
                                               target_type="character_version", target_id=sheet["version_id"],
                                               view="front", views=CHARACTER_VIEWS, body=_character_body(sheet),
                                               subject=sheet["name"], first_view="front")] if c]
            front = _latest(db, "character_image", sheet["version_id"], "front")
        body = _character_body(sheet) + "\n" + _lines(("Costume", costume["name"]), ("Costume description", costume["description"]),
                                                      ("Accessories", costume["accessories"]), ("Costume colours", costume["color_palette"]),
                                                      ("Worn when", costume["state_notes"]))
        existing = _latest(db, "character_image", target_id, "costume_front")
        if existing is None or force:
            label, aspect, instruction = COSTUME_VIEWS["costume_front"]
            refs = [anchor_id]
            prior = _approved_asset(db, "character_image", target_id, "costume_front")
            if prior:
                refs.append(prior)
            made.append(generation.create_request(
                db, series_id, "character_image", f"{style_block(bible)}\n\n{instruction}\n{body}\nNo text, no captions.",
                target_type="costume", target_id=target_id, negative_prompt=_negative(bible), reference_asset_ids=refs,
                depends_on=[front["id"]],
                params={"aspect_ratio": aspect, "view": "costume_front", "subject": f"{sheet['name']} in {costume['name']}",
                        "character_version_id": str(sheet["version_id"]), "deps_need_approval": True,
                        "use_dependency_results": True}))
    elif target_type == "entity_look":
        entity_type = db.execute(text("SELECT entity_type FROM entity_looks WHERE id = :i AND series_id = :s"),
                                 {"i": str(target_id), "s": str(series_id)}).scalar()
        if entity_type is None:
            raise LookupError("Look sheet was not found")
        look = next((x for x in _entity_looks(db, series_id, entity_type) if x["id"] == target_id), None)
        if look is None:
            raise LookupError("That look sheet is not the current one for its place or object")
        if entity_type == "location":
            run("place_image", "entity_look", target_id, PLACE_VIEWS, _look_body("Place", look), look["name"])
        else:
            run("object_image", "entity_look", target_id, OBJECT_VIEWS, _look_body("Object", look), look["name"])
    else:
        raise ValueError("target_type must be character_version, costume or entity_look")
    return made


def generate_all(db: Session, series_id: UUID) -> dict:
    """Request every missing picture for every character, costume, place and object. Safe to repeat: targets that
    already have a request are skipped. Needs an approved style bible and style anchor. The caller commits."""
    _bible(db, series_id)
    _anchor_asset(db, series_id)
    counts = {"characters": 0, "costumes": 0, "places": 0, "objects": 0, "requests_created": 0}
    for sheet in _character_sheets(db, series_id):
        made = generate_target(db, series_id, "character_version", sheet["version_id"])
        counts["characters"] += 1 if made else 0
        counts["requests_created"] += len(made)
        for costume in sheet["costumes"]:
            made = generate_target(db, series_id, "costume", costume["id"])
            counts["costumes"] += 1 if made else 0
            counts["requests_created"] += len(made)
    for key, entity_type in (("places", "location"), ("objects", "object")):
        for look in _entity_looks(db, series_id, entity_type):
            made = generate_target(db, series_id, "entity_look", look["id"])
            counts[key] += 1 if made else 0
            counts["requests_created"] += len(made)
    return counts


# --- what the gallery shows -------------------------------------------------------------------------------------

def _views_of(requests: dict, target_id, views: dict) -> list[dict]:
    out = []
    for view, (label, _aspect, _instruction) in views.items():
        entries = requests.get((str(target_id), view), [])
        out.append({"view": view, "label": label, "request": entries[0] if entries else None, "attempts": len(entries)})
    return out


def get_overview(db: Session, series_id: UUID) -> dict:
    """Everything the reference gallery needs in one call."""
    requests: dict[tuple[str, str], list[dict]] = {}
    anchors: list[dict] = []
    for kind in REFERENCE_KINDS:
        for item in generation.list_requests(db, series_id, kind=kind, limit=1000):  # newest first
            if kind == "style_anchor":
                anchors.append(item)
            elif item["target_id"]:
                requests.setdefault((str(item["target_id"]), (item["params"] or {}).get("view", "")), []).append(item)
    bible = get_approved(db, series_id)
    characters = []
    for sheet in _character_sheets(db, series_id):
        characters.append({
            "target_type": "character_version", "target_id": str(sheet["version_id"]), "character_id": str(sheet["character_id"]),
            "name": sheet["name"], "role": sheet["role"], "version_number": sheet["version_number"],
            "description": sheet["description"], "views": _views_of(requests, sheet["version_id"], CHARACTER_VIEWS),
            "costumes": [{"target_type": "costume", "target_id": str(c["id"]), "name": c["name"], "description": c["description"],
                          "views": _views_of(requests, c["id"], COSTUME_VIEWS)} for c in sheet["costumes"]]})

    def looks(entity_type: str, views: dict) -> list[dict]:
        return [{"target_type": "entity_look", "target_id": str(x["id"]), "entity_id": str(x["entity_id"]), "name": x["name"],
                 "description": x["description"], "views": _views_of(requests, x["id"], views)}
                for x in _entity_looks(db, series_id, entity_type)]

    anchor = get_style_anchor(db, series_id)
    return {
        "style_bible_approved": bible is not None,
        "style_anchor_asset_id": anchor.asset_id if anchor else None,
        "style_anchors": anchors, "characters": characters,
        "places": looks("location", PLACE_VIEWS), "objects": looks("object", OBJECT_VIEWS),
        "flagged_count": len(list_flagged(db, series_id)),
    }


def list_flagged(db: Session, series_id: UUID) -> list[dict]:
    """Finished, not yet reviewed images the consistency check marked as drifting from their references."""
    items = generation.list_requests(db, series_id, review_status="pending", limit=1000)
    return [i for i in items if i["kind"] in REFERENCE_KINDS and i["status"] == "succeeded" and i.get("drift_flag")]
