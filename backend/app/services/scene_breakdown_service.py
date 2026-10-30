"""Scene breakdown: one approved episode -> scenes, dialogue and shots."""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.core.settings import settings
from app.providers.llm_base import LLMAnalysisRequest
from app.providers.llm_factory import get_llm_provider
from app.repositories.analysis_repository import list_source_chunks
from app.schemas.llm_stages import SceneBreakdownResult
from app.services.adaptation_service import removed_beats
from app.services.llm_stage import LLMStageClient
from app.services.story_analysis_service import detect_story_format

STAGE = "scene_breakdown"


def build_scene_breakdown(db: Session, episode_id: UUID, client: LLMStageClient | None = None) -> dict:
    episode = db.execute(
        text("""SELECT id, series_id, title, synopsis, target_duration_seconds, source_unit_ids
                FROM episodes WHERE id = :e"""), {"e": str(episode_id)}).mappings().first()
    if episode is None:
        raise PermanentJobError("Episode was not found")
    run = db.execute(
        text("""SELECT id, source_id, profile FROM analysis_runs WHERE series_id = :s AND status = 'succeeded'
                ORDER BY created_at DESC LIMIT 1"""), {"s": str(episode["series_id"])}).mappings().first()
    if run is None:
        raise PermanentJobError("The series has no finished analysis run")
    units = db.execute(
        text("""SELECT sequence_number, title, synopsis, content, character_names, location_names, source_reference,
                       estimated_seconds FROM story_units WHERE id = ANY(CAST(:ids AS uuid[])) ORDER BY sequence_number"""),
        {"ids": "{" + ",".join(str(u) for u in episode["source_unit_ids"]) + "}"}).mappings().all()
    if not units:
        raise PermanentJobError("Episode has no story units to break down")

    wanted = {ref.get("chunk_id") for unit in units for ref in unit["source_reference"] or []}
    chunks = [c for c in list_source_chunks(db, run["source_id"]) if c["chunk_id"] in wanted]
    words = 0
    kept = []
    for chunk in chunks:  # keep the prompt inside one batch worth of text
        words += len(chunk["text"].split())
        if words > settings.analysis_batch_words * 2 and kept:
            break
        kept.append(chunk)

    names = {k: [r[0] for r in db.execute(
        text(f"SELECT name FROM {t} WHERE series_id = :s AND merged_into_id IS NULL AND review_status <> 'stale'"),
        {"s": str(episode["series_id"])})] for k, t in (("characters", "characters"), ("locations", "locations"))}
    request = LLMAnalysisRequest(
        task="scene_breakdown", profile=str(run["profile"]), context_chunks=kept, known_entities={},
        story_format=detect_story_format(chunks or kept),
        task_input={
            "episode": {"title": episode["title"], "synopsis": episode["synopsis"],
                        "target_seconds": episode["target_duration_seconds"]},
            "units": [{"number": u["sequence_number"], "title": u["title"], "synopsis": u["synopsis"],
                       "beats": (u["content"] or {}).get("beats", []), "seconds": u["estimated_seconds"]} for u in units],
            "omit": [b["beat_text"] for b in removed_beats(db, episode["series_id"])
                     if b["unit"] in {u["sequence_number"] for u in units}],
            **names},
    )
    client = client or LLMStageClient(get_llm_provider())
    result: SceneBreakdownResult = client.run(db, run["id"], STAGE, f"episode:{episode_id}", request,
                                              SceneBreakdownResult, [c["chunk_id"] for c in kept])
    if not result.scenes:
        raise PermanentJobError("The model returned no scenes for this episode")

    character_ids = {n.lower(): str(i) for i, n in db.execute(
        text("SELECT id, name FROM characters WHERE series_id = :s AND merged_into_id IS NULL"),
        {"s": str(episode["series_id"])})}
    db.execute(text("DELETE FROM scenes WHERE episode_id = :e"), {"e": str(episode_id)})
    shot_total = 0
    for number, scene in enumerate(result.scenes, start=1):
        scene_id = db.execute(
            text("""INSERT INTO scenes (episode_id, scene_number, title, description, dialogue, continuity_state,
                        environment_notes)
                    VALUES (:e, :n, :title, :description, CAST(:dialogue AS jsonb), CAST(:state AS jsonb), :env)
                    RETURNING id"""),
            {"e": str(episode_id), "n": number, "title": scene.title, "description": scene.description,
             "dialogue": json.dumps([d.model_dump() for d in scene.dialogue]),
             "state": json.dumps({"location": scene.location, "time_of_day": scene.time_of_day,
                                  "characters": scene.characters}),
             "env": scene.environment_notes},
        ).scalar_one()
        for shot_number, shot in enumerate(scene.shots, start=1):
            ids = [character_ids[n.lower()] for n in shot.characters if n.lower() in character_ids]
            db.execute(
                text("""INSERT INTO shots (scene_id, shot_number, description, camera, duration_seconds, character_ids)
                        VALUES (:s, :n, :description, :camera, :seconds, CAST(:ids AS uuid[]))"""),
                {"s": str(scene_id), "n": shot_number, "description": shot.description, "camera": shot.camera,
                 "seconds": shot.duration_seconds, "ids": "{" + ",".join(ids) + "}"},
            )
            shot_total += 1
    db.commit()
    return {"scenes": len(result.scenes), "shots": shot_total}
