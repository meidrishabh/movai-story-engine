import json
from typing import Any
from uuid import UUID
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db
from app.providers.base import GenerationRequest
from app.providers.mock import MockStoryboardProvider


DEV_USER_EMAIL = "dev@movai.local"

app = FastAPI(
    title="MovAI API",
    version="0.1.0",
)

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def ensure_dev_user(db: Session):
    return db.execute(
        text(
            """
            INSERT INTO users (email, display_name, is_active)
            VALUES (:email, 'MovAI Development User', TRUE)
            ON CONFLICT (email) DO UPDATE
            SET is_active = TRUE,
                updated_at = now()
            RETURNING id
            """
        ),
        {"email": DEV_USER_EMAIL},
    ).scalar_one()


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class SeriesCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    premise: str | None = None
    genre: str | None = None
    language_code: str = "en"
    visual_style: str | None = None


class EpisodeCreate(BaseModel):
    episode_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    synopsis: str | None = None
    script: str | None = None
    target_duration_seconds: int = Field(gt=0, le=3600)


class CharacterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str | None = None
    personality: str | None = None
    story_role: str | None = None


class CharacterVersionCreate(BaseModel):
    description: str = Field(min_length=1)
    face_and_body_design: str | None = None
    clothing_and_accessories: str | None = None
    distinctive_features: str | None = None
    color_palette: list[str] = Field(default_factory=list)
    voice_profile: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="draft", pattern="^(draft|approved|rejected|superseded)$")
    change_notes: str | None = None


class SceneCreate(BaseModel):
    scene_number: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=200)
    description: str = Field(min_length=1)
    dialogue: list[dict[str, Any]] = Field(default_factory=list)
    continuity_state: dict[str, Any] = Field(default_factory=dict)
    environment_notes: str | None = None


class StoryboardFrameCreate(BaseModel):
    frame_number: int = Field(gt=0)
    version_number: int = Field(default=1, gt=0)
    prompt: str = Field(min_length=1)
    character_version_ids: list[UUID] = Field(default_factory=list)
    dependency_metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class SeriesUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    premise: str | None = None
    genre: str | None = None
    language_code: str | None = Field(default=None, min_length=2, max_length=10)
    visual_style: str | None = None


class SeriesSeasonPlanRequest(BaseModel):
    target_season_count: int = Field(gt=0, le=100)
    target_episode_duration_seconds: int = Field(gt=0, le=3600)


class SeasonCreate(BaseModel):
    season_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    synopsis: str | None = None


class SeasonUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    synopsis: str | None = None
    status: str | None = Field(default=None, max_length=50)


class SeasonPipelineUpdate(BaseModel):
    target_episode_count: int | None = Field(default=None, gt=0)
    target_episode_duration_seconds: int | None = Field(default=None, gt=0)
    climax_strategy: str | None = None


class StorySourceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    source_type: str = Field(default="pasted_text", max_length=50)
    original_filename: str | None = None
    raw_text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MasterScriptCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    summary: str | None = None
    full_script: str = Field(min_length=1)
    analysis_metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = Field(default="draft", pattern="^(draft|approved|rejected|superseded)$")


class AnalyzeSeasonRequest(BaseModel):
    source_id: UUID | None = None


class PlanEpisodesRequest(BaseModel):
    master_script_id: UUID | None = None


class ExtractedCostume(BaseModel):
    name: str
    description: str
    color_palette: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    state_notes: str | None = None
    source_unit_ids: list[UUID] = Field(default_factory=list)


class ExtractedCharacter(BaseModel):
    name: str
    role: str | None = None
    personality: str | None = None
    story_role: str | None = None
    source_unit_ids: list[UUID] = Field(default_factory=list)
    extraction_confidence: float | None = Field(default=None, ge=0, le=1)
    costumes: list[ExtractedCostume] = Field(default_factory=list)


class ExtractedContinuityObject(BaseModel):
    object_type: str
    name: str
    description: str
    distinctive_features: str | None = None
    state_notes: str | None = None
    source_unit_ids: list[UUID] = Field(default_factory=list)


class AnalysisResultCreate(BaseModel):
    master_script_id: UUID | None = None
    characters: list[ExtractedCharacter] = Field(default_factory=list)
    continuity_objects: list[ExtractedContinuityObject] = Field(default_factory=list)


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    synopsis: str | None = None
    script: str | None = None
    target_duration_seconds: int | None = Field(default=None, gt=0, le=3600)
    status: str | None = Field(default=None, max_length=50)


class ApprovalCreate(BaseModel):
    entity_type: str = Field(
        pattern="^(character_version|storyboard_frame|scene|episode|render)$"
    )
    entity_id: UUID
    decision: str = Field(pattern="^(approved|rejected)$")
    notes: str | None = None


app.mount(
    "/ui",
    StaticFiles(directory=FRONTEND_DIR, html=True),
    name="ui",
)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "movai-api",
    }


@app.get("/api/v1/series")
def get_all_series(db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.created_at,
            s.updated_at,
            COUNT(DISTINCT se.id) AS season_count,
            COUNT(DISTINCT e.id) AS episode_count
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN seasons se ON se.series_id = s.id
        LEFT JOIN episodes e ON e.series_id = s.id
        WHERE u.email = :email
        GROUP BY
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.created_at,
            s.updated_at
        ORDER BY s.created_at DESC
        """
    )

    result = db.execute(query, {"email": DEV_USER_EMAIL})
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@app.get("/api/v1/series/{series_id}")
def get_series(series_id: UUID, db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.continuity_notes,
            s.created_at,
            s.updated_at
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE s.id = :series_id
          AND u.email = :email
        """
    )

    series = db.execute(
        query,
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).mappings().first()

    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    return dict(series)


@app.get("/api/v1/series/{series_id}/pipeline")
def get_series_story_pipeline(series_id: UUID, db: Session = Depends(get_db)):
    series = db.execute(
        text(
            """
            SELECT s.id, s.title, s.premise, s.genre, s.language_code,
                   s.visual_style, s.estimated_duration_seconds,
                   s.target_season_count, s.target_episode_duration_seconds,
                   s.created_at, s.updated_at
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id
              AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).mappings().first()

    if series is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    source = db.execute(
        text(
            """
            SELECT id, series_id, title, source_type, original_filename,
                   status, created_at, updated_at
            FROM story_sources
            WHERE series_id = :series_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().first()

    master_script = db.execute(
        text(
            """
            SELECT id, series_id, version_number, title, summary,
                   status, created_at, updated_at
            FROM master_scripts
            WHERE series_id = :series_id
            ORDER BY version_number DESC
            LIMIT 1
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().first()

    series_story_status = "not_started"
    if source:
        series_story_status = str(source["status"])
    if master_script and str(master_script["status"]) in {"approved", "succeeded"}:
        series_story_status = "processed"
    elif master_script and series_story_status not in {"analysis_complete", "processed"}:
        series_story_status = "master_script_ready"

    return {
        "series": dict(series),
        "source": dict(source) if source else None,
        "master_script": dict(master_script) if master_script else None,
        "story_status": series_story_status,
    }


@app.post("/api/v1/series/{series_id}/sources")
def create_series_story_source(
    series_id: UUID,
    payload: StorySourceCreate,
    db: Session = Depends(get_db),
):
    source = db.execute(
        text(
            """
            INSERT INTO story_sources (
                series_id, season_id, title, source_type,
                original_filename, raw_text, metadata
            )
            SELECT
                s.id, NULL, :title, :source_type,
                :original_filename, :raw_text, CAST(:metadata AS jsonb)
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id
              AND u.email = :email
            RETURNING id, series_id, season_id, title, source_type,
                      original_filename, status, created_at, updated_at
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "source_type": payload.source_type,
            "original_filename": payload.original_filename,
            "raw_text": payload.raw_text,
            "metadata": json.dumps(payload.metadata),
        },
    ).mappings().first()

    if source is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    db.commit()
    return dict(source)


@app.post("/api/v1/series/{series_id}/master-script")
def create_series_master_script(
    series_id: UUID,
    payload: MasterScriptCreate,
    db: Session = Depends(get_db),
):
    next_version = db.execute(
        text(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM master_scripts WHERE series_id = :series_id"
        ),
        {"series_id": str(series_id)},
    ).scalar_one()

    master_script = db.execute(
        text(
            """
            INSERT INTO master_scripts (
                series_id, season_id, version_number, title, summary,
                full_script, analysis_metadata, status
            )
            SELECT
                s.id, NULL, :version_number, :title, :summary,
                :full_script, CAST(:analysis_metadata AS jsonb),
                CAST(:status AS approval_status)
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id
              AND u.email = :email
            RETURNING id, series_id, season_id, version_number, title, summary,
                      full_script, analysis_metadata, status, created_at, updated_at
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "version_number": next_version,
            "title": payload.title,
            "summary": payload.summary,
            "full_script": payload.full_script,
            "analysis_metadata": json.dumps(payload.analysis_metadata),
            "status": payload.status,
        },
    ).mappings().first()

    if master_script is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    db.commit()
    return dict(master_script)


@app.post("/api/v1/series/{series_id}/analyze")
def analyze_series_story(
    series_id: UUID,
    payload: AnalyzeSeasonRequest,
    db: Session = Depends(get_db),
):
    source_id = payload.source_id or db.execute(
        text(
            "SELECT id FROM story_sources WHERE series_id = :series_id ORDER BY created_at DESC LIMIT 1"
        ),
        {"series_id": str(series_id)},
    ).scalar()

    if source_id is None:
        raise HTTPException(status_code=400, detail="Upload a source story before analysis")

    series_exists = db.execute(
        text(
            """
            SELECT s.id
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).scalar()

    if series_exists is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    job = db.execute(
        text(
            """
            INSERT INTO generation_jobs (
                job_type, status, provider, provider_model, request_metadata, max_attempts
            )
            VALUES (
                'story_analysis', 'queued', 'mock', 'mock-story-analyzer-v1',
                CAST(:request_metadata AS jsonb), 1
            )
            RETURNING id, job_type, status, provider, provider_model, created_at
            """
        ),
        {
            "request_metadata": json.dumps(
                {"series_id": str(series_id), "source_id": str(source_id)}
            )
        },
    ).mappings().one()

    db.execute(
        text("UPDATE story_sources SET status = 'analysis_queued' WHERE id = :source_id"),
        {"source_id": str(source_id)},
    )
    db.commit()
    return dict(job)


@app.post("/api/v1/series/{series_id}/plan-seasons")
def plan_series_seasons(
    series_id: UUID,
    payload: SeriesSeasonPlanRequest,
    db: Session = Depends(get_db),
):
    readiness = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1 FROM story_sources
                WHERE series_id = :series_id
                  AND status IN ('analysis_complete', 'processed')
            )
            OR EXISTS (
                SELECT 1 FROM master_scripts
                WHERE series_id = :series_id
                  AND status IN ('approved', 'succeeded')
            )
            """
        ),
        {"series_id": str(series_id)},
    ).scalar()
    if not readiness:
        raise HTTPException(
            status_code=409,
            detail="Process the complete series story before planning seasons",
        )

    series = db.execute(
        text(
            """
            UPDATE series s
            SET target_season_count = :target_season_count,
                target_episode_duration_seconds = :target_episode_duration_seconds,
                updated_at = now()
            FROM projects p
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id
              AND p.id = s.project_id
              AND u.email = :email
            RETURNING s.id, s.title, s.estimated_duration_seconds,
                      s.target_season_count, s.target_episode_duration_seconds
            """
        ),
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "target_season_count": payload.target_season_count,
            "target_episode_duration_seconds": payload.target_episode_duration_seconds,
        },
    ).mappings().first()
    if series is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    existing_count = db.execute(
        text("SELECT COUNT(*) FROM seasons WHERE series_id = :series_id"),
        {"series_id": str(series_id)},
    ).scalar_one()
    if existing_count > payload.target_season_count:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="The requested season count is lower than the seasons already created",
        )

    for season_number in range(existing_count + 1, payload.target_season_count + 1):
        db.execute(
            text(
                """
                INSERT INTO seasons (series_id, season_number, title, synopsis, story_status)
                VALUES (:series_id, :season_number, :title, :synopsis, 'planned')
                """
            ),
            {
                "series_id": str(series_id),
                "season_number": season_number,
                "title": f"Season {season_number}",
                "synopsis": "Planned from the processed series story.",
            },
        )

    seasons = db.execute(
        text(
            """
            SELECT id, series_id, season_number, title, synopsis, story_status
            FROM seasons
            WHERE series_id = :series_id
            ORDER BY season_number
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()
    db.commit()
    return {"series": dict(series), "seasons": [dict(row) for row in seasons]}


@app.post("/api/v1/series")
def create_root_series(
    payload: SeriesCreate,
    db: Session = Depends(get_db),
):
    ensure_dev_user(db)
    project_query = text(
        """
        SELECT p.id
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE u.email = :email
          AND p.title = 'Default Studio'
        LIMIT 1
        """
    )
    project_id = db.execute(project_query, {"email": DEV_USER_EMAIL}).scalar()

    if project_id is None:
        project_id = db.execute(
            text(
                """
                INSERT INTO projects (owner_id, title, description)
                SELECT id, 'Default Studio', 'Internal container for series.'
                FROM users
                WHERE email = :email
                RETURNING id
                """
            ),
            {"email": DEV_USER_EMAIL},
        ).scalar()

    if project_id is None:
        db.rollback()
        raise HTTPException(status_code=500, detail="Development user was not found")

    series = db.execute(
        text(
            """
            INSERT INTO series (
                project_id, title, premise, genre, language_code, visual_style
            )
            VALUES (
                :project_id, :title, :premise, :genre, :language_code, :visual_style
            )
            RETURNING
                id, project_id, title, premise, genre, language_code,
                visual_style, created_at, updated_at
            """
        ),
        {
            "project_id": str(project_id),
            "title": payload.title,
            "premise": payload.premise,
            "genre": payload.genre,
            "language_code": payload.language_code,
            "visual_style": payload.visual_style,
        },
    ).mappings().one()

    db.commit()
    return dict(series)


@app.get("/api/v1/series/{series_id}/seasons")
def get_series_seasons(series_id: UUID, db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            se.id,
            se.series_id,
            se.season_number,
            se.title,
            se.synopsis,
            se.status,
            se.target_episode_count,
            se.target_episode_duration_seconds,
            se.climax_strategy,
            se.story_status,
            se.created_at,
            se.updated_at,
            COUNT(e.id) AS episode_count
        FROM seasons se
        JOIN series s ON s.id = se.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN episodes e ON e.season_id = se.id
        WHERE se.series_id = :series_id
          AND u.email = :email
        GROUP BY
            se.id, se.series_id, se.season_number, se.title,
            se.synopsis, se.status, se.target_episode_count,
            se.target_episode_duration_seconds, se.climax_strategy,
            se.story_status, se.created_at, se.updated_at
        ORDER BY se.season_number
        """
    )
    result = db.execute(
        query,
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@app.post("/api/v1/series/{series_id}/seasons")
def create_season(
    series_id: UUID,
    payload: SeasonCreate,
    db: Session = Depends(get_db),
):
    readiness = db.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM seasons se
                WHERE se.series_id = :series_id
                  AND se.story_status IN (
                      'analysis_complete', 'episode_planning_queued',
                      'episodes_generated', 'processed', 'complete', 'approved'
                  )
            ) AS can_create
            """
        ),
        {"series_id": str(series_id)},
    ).scalar()

    if not readiness:
        raise HTTPException(
            status_code=409,
            detail="Use season planning to create the first season, or finish the current season story before creating another season",
        )

    query = text(
        """
        INSERT INTO seasons (series_id, season_number, title, synopsis)
        SELECT s.id, :season_number, :title, :synopsis
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE s.id = :series_id
          AND u.email = :email
        RETURNING id, series_id, season_number, title, synopsis, status, created_at, updated_at
        """
    )
    season = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "season_number": payload.season_number,
            "title": payload.title,
            "synopsis": payload.synopsis,
        },
    ).mappings().first()

    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    db.commit()
    return dict(season)


@app.patch("/api/v1/seasons/{season_id}")
def update_season(
    season_id: UUID,
    payload: SeasonUpdate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE seasons se
        SET
            title = COALESCE(:title, se.title),
            synopsis = COALESCE(:synopsis, se.synopsis),
            status = COALESCE(:status, se.status)
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE se.id = :season_id
          AND s.id = se.series_id
          AND u.email = :email
        RETURNING
            se.id, se.series_id, se.season_number, se.title,
            se.synopsis, se.status, se.created_at, se.updated_at
        """
    )
    season = db.execute(
        query,
        {
            "season_id": str(season_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "synopsis": payload.synopsis,
            "status": payload.status,
        },
    ).mappings().first()

    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")

    db.commit()
    return dict(season)


@app.patch("/api/v1/seasons/{season_id}/pipeline")
def update_season_pipeline(
    season_id: UUID,
    payload: SeasonPipelineUpdate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE seasons se
        SET
            target_episode_count = COALESCE(:target_episode_count, se.target_episode_count),
            target_episode_duration_seconds = COALESCE(
                :target_episode_duration_seconds,
                se.target_episode_duration_seconds
            ),
            climax_strategy = COALESCE(:climax_strategy, se.climax_strategy)
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE se.id = :season_id
          AND s.id = se.series_id
          AND u.email = :email
        RETURNING
            se.id, se.series_id, se.season_number, se.title, se.synopsis,
            se.target_episode_count, se.target_episode_duration_seconds,
            se.climax_strategy, se.story_status, se.created_at, se.updated_at
        """
    )
    season = db.execute(
        query,
        {
            "season_id": str(season_id),
            "email": DEV_USER_EMAIL,
            "target_episode_count": payload.target_episode_count,
            "target_episode_duration_seconds": payload.target_episode_duration_seconds,
            "climax_strategy": payload.climax_strategy,
        },
    ).mappings().first()

    if season is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")

    db.commit()
    return dict(season)


@app.get("/api/v1/seasons/{season_id}/pipeline")
def get_season_pipeline(season_id: UUID, db: Session = Depends(get_db)):
    season = db.execute(
        text(
            """
            SELECT
                se.id,
                se.series_id,
                se.season_number,
                se.title,
                se.synopsis,
                se.target_episode_count,
                se.target_episode_duration_seconds,
                se.climax_strategy,
                se.story_status
            FROM seasons se
            JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id
              AND u.email = :email
            """
        ),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    ).mappings().first()

    if season is None:
        raise HTTPException(status_code=404, detail="Season was not found")

    source = db.execute(
        text(
            """
            SELECT id, title, source_type, original_filename, status, created_at
            FROM story_sources
            WHERE season_id = :season_id
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"season_id": str(season_id)},
    ).mappings().first()

    master_script = db.execute(
        text(
            """
            SELECT id, version_number, title, summary, status, created_at, updated_at
            FROM master_scripts
            WHERE season_id = :season_id
            ORDER BY version_number DESC
            LIMIT 1
            """
        ),
        {"season_id": str(season_id)},
    ).mappings().first()

    return {
        "season": dict(season),
        "source": dict(source) if source else None,
        "master_script": dict(master_script) if master_script else None,
    }


@app.post("/api/v1/seasons/{season_id}/sources")
def create_story_source(
    season_id: UUID,
    payload: StorySourceCreate,
    db: Session = Depends(get_db),
):
    source = db.execute(
        text(
            """
            INSERT INTO story_sources (
                season_id, title, source_type, original_filename, raw_text, metadata
            )
            SELECT
                se.id, :title, :source_type, :original_filename, :raw_text,
                CAST(:metadata AS jsonb)
            FROM seasons se
            JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id
              AND u.email = :email
            RETURNING id, season_id, title, source_type, original_filename,
                      status, created_at, updated_at
            """
        ),
        {
            "season_id": str(season_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "source_type": payload.source_type,
            "original_filename": payload.original_filename,
            "raw_text": payload.raw_text,
            "metadata": json.dumps(payload.metadata),
        },
    ).mappings().first()

    if source is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")

    db.execute(
        text("UPDATE seasons SET story_status = 'source_ready' WHERE id = :season_id"),
        {"season_id": str(season_id)},
    )
    db.commit()
    return dict(source)


@app.get("/api/v1/seasons/{season_id}/sources")
def get_story_sources(season_id: UUID, db: Session = Depends(get_db)):
    result = db.execute(
        text(
            """
            SELECT id, season_id, title, source_type, original_filename,
                   status, created_at, updated_at
            FROM story_sources
            WHERE season_id = :season_id
            ORDER BY created_at DESC
            """
        ),
        {"season_id": str(season_id)},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@app.post("/api/v1/seasons/{season_id}/master-script")
def create_master_script(
    season_id: UUID,
    payload: MasterScriptCreate,
    db: Session = Depends(get_db),
):
    next_version = db.execute(
        text(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM master_scripts WHERE season_id = :season_id"
        ),
        {"season_id": str(season_id)},
    ).scalar_one()

    master_script = db.execute(
        text(
            """
            INSERT INTO master_scripts (
                season_id, version_number, title, summary, full_script,
                analysis_metadata, status
            )
            SELECT
                se.id, :version_number, :title, :summary, :full_script,
                CAST(:analysis_metadata AS jsonb), CAST(:status AS approval_status)
            FROM seasons se
            JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id
              AND u.email = :email
            RETURNING id, season_id, version_number, title, summary,
                      full_script, analysis_metadata, status, created_at, updated_at
            """
        ),
        {
            "season_id": str(season_id),
            "email": DEV_USER_EMAIL,
            "version_number": next_version,
            "title": payload.title,
            "summary": payload.summary,
            "full_script": payload.full_script,
            "analysis_metadata": json.dumps(payload.analysis_metadata),
            "status": payload.status,
        },
    ).mappings().first()

    if master_script is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")

    db.execute(
        text("UPDATE seasons SET story_status = 'master_script_ready' WHERE id = :season_id"),
        {"season_id": str(season_id)},
    )
    db.commit()
    return dict(master_script)


@app.get("/api/v1/seasons/{season_id}/master-script")
def get_master_script(season_id: UUID, db: Session = Depends(get_db)):
    script = db.execute(
        text(
            """
            SELECT id, season_id, version_number, title, summary, full_script,
                   analysis_metadata, status, created_at, updated_at
            FROM master_scripts
            WHERE season_id = :season_id
            ORDER BY version_number DESC
            LIMIT 1
            """
        ),
        {"season_id": str(season_id)},
    ).mappings().first()

    if script is None:
        raise HTTPException(status_code=404, detail="Master script was not found")

    return dict(script)


@app.post("/api/v1/seasons/{season_id}/analyze")
def analyze_season_story(
    season_id: UUID,
    payload: AnalyzeSeasonRequest,
    db: Session = Depends(get_db),
):
    source_id = payload.source_id
    if source_id is None:
        source_id = db.execute(
            text(
                "SELECT id FROM story_sources WHERE season_id = :season_id ORDER BY created_at DESC LIMIT 1"
            ),
            {"season_id": str(season_id)},
        ).scalar()

    if source_id is None:
        raise HTTPException(status_code=400, detail="Upload a source story before analysis")

    job = db.execute(
        text(
            """
            INSERT INTO generation_jobs (
                job_type, status, provider, provider_model, request_metadata, max_attempts
            )
            VALUES (
                'story_analysis', 'queued', 'mock', 'mock-story-analyzer-v1',
                CAST(:request_metadata AS jsonb), 1
            )
            RETURNING id, job_type, status, provider, provider_model, created_at
            """
        ),
        {
            "request_metadata": json.dumps(
                {"season_id": str(season_id), "source_id": str(source_id)}
            )
        },
    ).mappings().one()

    db.execute(
        text("UPDATE seasons SET story_status = 'analysis_queued' WHERE id = :season_id"),
        {"season_id": str(season_id)},
    )
    db.execute(
        text("UPDATE story_sources SET status = 'analysis_queued' WHERE id = :source_id"),
        {"source_id": str(source_id)},
    )
    db.commit()
    return dict(job)


@app.post("/api/v1/seasons/{season_id}/plan-episodes")
def plan_season_episodes(
    season_id: UUID,
    payload: PlanEpisodesRequest,
    db: Session = Depends(get_db),
):
    master_script_id = payload.master_script_id
    if master_script_id is None:
        master_script_id = db.execute(
            text(
                "SELECT id FROM master_scripts WHERE season_id = :season_id ORDER BY version_number DESC LIMIT 1"
            ),
            {"season_id": str(season_id)},
        ).scalar()

    if master_script_id is None:
        raise HTTPException(status_code=400, detail="Create a master script before planning episodes")

    preferences = db.execute(
        text(
            """
            SELECT target_episode_count, target_episode_duration_seconds, climax_strategy
            FROM seasons
            WHERE id = :season_id
            """
        ),
        {"season_id": str(season_id)},
    ).mappings().first()

    if preferences is None:
        raise HTTPException(status_code=404, detail="Season was not found")

    job = db.execute(
        text(
            """
            INSERT INTO generation_jobs (
                job_type, status, provider, provider_model, request_metadata, max_attempts
            )
            VALUES (
                'episode_segmentation', 'queued', 'mock', 'mock-episode-planner-v1',
                CAST(:request_metadata AS jsonb), 1
            )
            RETURNING id, job_type, status, provider, provider_model, created_at
            """
        ),
        {
            "request_metadata": json.dumps(
                {
                    "season_id": str(season_id),
                    "master_script_id": str(master_script_id),
                    "preferences": dict(preferences),
                },
                default=str,
            )
        },
    ).mappings().one()

    db.execute(
        text("UPDATE seasons SET story_status = 'episode_planning_queued' WHERE id = :season_id"),
        {"season_id": str(season_id)},
    )
    db.commit()
    return dict(job)


@app.get("/api/v1/seasons/{season_id}/episodes")
def get_season_episodes(season_id: UUID, db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            e.id, e.season_id, e.series_id, e.episode_number,
            e.title, e.synopsis, e.script, e.target_duration_seconds,
            e.status, e.created_at, e.updated_at
        FROM episodes e
        JOIN seasons se ON se.id = e.season_id
        JOIN series s ON s.id = se.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE e.season_id = :season_id
          AND u.email = :email
        ORDER BY e.episode_number
        """
    )
    result = db.execute(
        query,
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    )
    items = [dict(row) for row in result.mappings().all()]
    return {"count": len(items), "items": items}


@app.post("/api/v1/seasons/{season_id}/episodes")
def create_season_episode(
    season_id: UUID,
    payload: EpisodeCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Episodes are created by approved episode segmentation, not manually.",
    )
    query = text(
        """
        INSERT INTO episodes (
            series_id, season_id, episode_number, title, synopsis,
            script, target_duration_seconds
        )
        SELECT
            se.series_id, se.id, :episode_number, :title, :synopsis,
            :script, :target_duration_seconds
        FROM seasons se
        JOIN series s ON s.id = se.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE se.id = :season_id
          AND u.email = :email
        RETURNING
            id, season_id, series_id, episode_number, title, synopsis,
            script, target_duration_seconds, status, created_at, updated_at
        """
    )
    episode = db.execute(
        query,
        {
            "season_id": str(season_id),
            "email": DEV_USER_EMAIL,
            "episode_number": payload.episode_number,
            "title": payload.title,
            "synopsis": payload.synopsis,
            "script": payload.script,
            "target_duration_seconds": payload.target_duration_seconds,
        },
    ).mappings().first()

    if episode is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Season was not found")

    db.commit()
    return dict(episode)


@app.get("/health/db")
def database_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))

    return {
        "status": "ok",
        "database": "connected",
    }


@app.get("/api/v1/projects")
def get_all_projects(db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            p.id,
            p.title,
            p.description,
            p.settings,
            p.created_at,
            p.updated_at,
            COUNT(DISTINCT s.id) AS series_count
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN series s ON s.project_id = p.id
        WHERE u.email = :email
        GROUP BY
            p.id,
            p.title,
            p.description,
            p.settings,
            p.created_at,
            p.updated_at
        ORDER BY p.created_at DESC
        """
    )

    result = db.execute(query, {"email": DEV_USER_EMAIL})
    projects = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(projects),
        "items": projects,
    }


@app.post("/api/v1/projects")
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
):
    owner_id = ensure_dev_user(db)
    query = text(
        """
        INSERT INTO projects (owner_id, title, description)
        VALUES (:owner_id, :title, :description)
        RETURNING
            id,
            owner_id,
            title,
            description,
            settings,
            created_at,
            updated_at
        """
    )

    result = db.execute(
        query,
        {
            "owner_id": owner_id,
            "title": payload.title,
            "description": payload.description,
        },
    )

    project = result.mappings().first()

    if project is None:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Development user was not found",
        )

    db.commit()

    return dict(project)


@app.post("/api/v1/projects/{project_id}/series")
def create_series(
    project_id: UUID,
    payload: SeriesCreate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        INSERT INTO series (
            project_id,
            title,
            premise,
            genre,
            language_code,
            visual_style
        )
        SELECT
            p.id,
            :title,
            :premise,
            :genre,
            :language_code,
            :visual_style
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE p.id = :project_id
          AND u.email = :email
        RETURNING
            id,
            project_id,
            title,
            premise,
            genre,
            language_code,
            visual_style,
            created_at,
            updated_at
        """
    )

    result = db.execute(
        query,
        {
            "project_id": str(project_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "premise": payload.premise,
            "genre": payload.genre,
            "language_code": payload.language_code,
            "visual_style": payload.visual_style,
        },
    )

    series = result.mappings().first()

    if series is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Project was not found",
        )

    db.commit()

    return dict(series)


@app.get("/api/v1/series/{series_id}/episodes")
def get_series_episodes(
    series_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            e.id,
            e.series_id,
            e.episode_number,
            e.title,
            e.synopsis,
            e.script,
            e.target_duration_seconds,
            e.status,
            e.created_at,
            e.updated_at
        FROM episodes e
        JOIN series s ON s.id = e.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE e.series_id = :series_id
          AND u.email = :email
        ORDER BY e.episode_number
        """
    )

    result = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
        },
    )

    episodes = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(episodes),
        "items": episodes,
    }


@app.post("/api/v1/series/{series_id}/episodes")
def create_episode(
    series_id: UUID,
    payload: EpisodeCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Episodes are created by approved episode segmentation, not manually.",
    )
    query = text(
        """
        INSERT INTO episodes (
            series_id,
            episode_number,
            title,
            synopsis,
            script,
            target_duration_seconds
        )
        SELECT
            s.id,
            :episode_number,
            :title,
            :synopsis,
            :script,
            :target_duration_seconds
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE s.id = :series_id
          AND u.email = :email
        RETURNING
            id,
            series_id,
            episode_number,
            title,
            synopsis,
            script,
            target_duration_seconds,
            status,
            created_at,
            updated_at
        """
    )

    result = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "episode_number": payload.episode_number,
            "title": payload.title,
            "synopsis": payload.synopsis,
            "script": payload.script,
            "target_duration_seconds": payload.target_duration_seconds,
        },
    )

    episode = result.mappings().first()

    if episode is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Series was not found",
        )

    db.commit()

    return dict(episode)


@app.get("/api/v1/series/{series_id}/characters")
def get_series_characters(
    series_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            c.id,
            c.series_id,
            c.name,
            c.role,
            c.personality,
            c.story_role,
            c.created_at,
            c.updated_at,
            COUNT(cv.id) AS version_count
        FROM characters c
        JOIN series s ON s.id = c.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN character_versions cv ON cv.character_id = c.id
        WHERE c.series_id = :series_id
          AND u.email = :email
        GROUP BY
            c.id,
            c.series_id,
            c.name,
            c.role,
            c.personality,
            c.story_role,
            c.created_at,
            c.updated_at
        ORDER BY c.created_at
        """
    )

    result = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
        },
    )

    characters = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(characters),
        "items": characters,
    }


@app.post("/api/v1/series/{series_id}/characters")
def create_character(
    series_id: UUID,
    payload: CharacterCreate,
    db: Session = Depends(get_db),
):
    raise HTTPException(
        status_code=405,
        detail="Characters are created from approved story analysis, not manually.",
    )


@app.get("/api/v1/series/{series_id}/continuity")
def get_series_continuity(
    series_id: UUID,
    db: Session = Depends(get_db),
):
    ownership = db.execute(
        text(
            """
            SELECT s.id
            FROM series s
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE s.id = :series_id
              AND u.email = :email
            """
        ),
        {"series_id": str(series_id), "email": DEV_USER_EMAIL},
    ).scalar()

    if ownership is None:
        raise HTTPException(status_code=404, detail="Series was not found")

    characters = db.execute(
        text(
            """
            SELECT
                c.id,
                c.name,
                c.role,
                c.personality,
                c.story_role,
                c.origin,
                c.source_unit_ids,
                c.extraction_confidence,
                c.analysis_status,
                COUNT(cv.id) AS version_count
            FROM characters c
            LEFT JOIN character_versions cv ON cv.character_id = c.id
            WHERE c.series_id = :series_id
            GROUP BY
                c.id, c.name, c.role, c.personality, c.story_role,
                c.origin, c.source_unit_ids, c.extraction_confidence,
                c.analysis_status
            ORDER BY c.name
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()

    objects = db.execute(
        text(
            """
            SELECT id, object_type, name, description,
                   distinctive_features, state_notes,
                   source_unit_ids, approval_status
            FROM continuity_objects
            WHERE series_id = :series_id
            ORDER BY object_type, name
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()

    costumes = db.execute(
        text(
            """
            SELECT co.id, co.character_id, co.name, co.description,
                   co.color_palette, co.accessories, co.state_notes,
                   co.source_unit_ids, co.approval_status
            FROM costumes co
            JOIN characters c ON c.id = co.character_id
            WHERE c.series_id = :series_id
            ORDER BY c.name, co.name
            """
        ),
        {"series_id": str(series_id)},
    ).mappings().all()

    return {
        "characters": [dict(row) for row in characters],
        "costumes": [dict(row) for row in costumes],
        "continuity_objects": [dict(row) for row in objects],
    }


@app.post("/api/v1/internal/seasons/{season_id}/analysis-result")
def commit_analysis_result(
    season_id: UUID,
    payload: AnalysisResultCreate,
    db: Session = Depends(get_db),
):
    series_id = db.execute(
        text(
            """
            SELECT s.id
            FROM seasons se
            JOIN series s ON s.id = se.series_id
            JOIN projects p ON p.id = s.project_id
            JOIN users u ON u.id = p.owner_id
            WHERE se.id = :season_id
              AND u.email = :email
            """
        ),
        {"season_id": str(season_id), "email": DEV_USER_EMAIL},
    ).scalar()

    if series_id is None:
        raise HTTPException(status_code=404, detail="Season was not found")

    character_count = 0
    costume_count = 0
    object_count = 0

    for extracted in payload.characters:
        source_ids = "{" + ",".join(str(item) for item in extracted.source_unit_ids) + "}"
        character = db.execute(
            text(
                """
                INSERT INTO characters (
                    series_id, name, role, personality, story_role,
                    origin, source_unit_ids, extraction_confidence, analysis_status
                )
                VALUES (
                    :series_id, :name, :role, :personality, :story_role,
                    'extracted', CAST(:source_unit_ids AS uuid[]),
                    :extraction_confidence, 'extracted'
                )
                ON CONFLICT (series_id, name) DO UPDATE
                SET
                    role = EXCLUDED.role,
                    personality = EXCLUDED.personality,
                    story_role = EXCLUDED.story_role,
                    source_unit_ids = EXCLUDED.source_unit_ids,
                    extraction_confidence = EXCLUDED.extraction_confidence,
                    analysis_status = 'extracted',
                    updated_at = now()
                RETURNING id
                """
            ),
            {
                "series_id": str(series_id),
                "name": extracted.name,
                "role": extracted.role,
                "personality": extracted.personality,
                "story_role": extracted.story_role,
                "source_unit_ids": source_ids,
                "extraction_confidence": extracted.extraction_confidence,
            },
        ).scalar_one()
        character_count += 1

        for costume in extracted.costumes:
            costume_source_ids = "{" + ",".join(str(item) for item in costume.source_unit_ids) + "}"
            db.execute(
                text(
                    """
                    INSERT INTO costumes (
                        character_id, name, description, color_palette,
                        accessories, state_notes, source_unit_ids
                    )
                    VALUES (
                        :character_id, :name, :description,
                        CAST(:color_palette AS jsonb),
                        CAST(:accessories AS jsonb), :state_notes,
                        CAST(:source_unit_ids AS uuid[])
                    )
                    """
                ),
                {
                    "character_id": str(character),
                    "name": costume.name,
                    "description": costume.description,
                    "color_palette": json.dumps(costume.color_palette),
                    "accessories": json.dumps(costume.accessories),
                    "state_notes": costume.state_notes,
                    "source_unit_ids": costume_source_ids,
                },
            )
            costume_count += 1

    for extracted in payload.continuity_objects:
        source_ids = "{" + ",".join(str(item) for item in extracted.source_unit_ids) + "}"
        db.execute(
            text(
                """
                INSERT INTO continuity_objects (
                    series_id, object_type, name, description,
                    distinctive_features, state_notes, source_unit_ids
                )
                VALUES (
                    :series_id, :object_type, :name, :description,
                    :distinctive_features, :state_notes,
                    CAST(:source_unit_ids AS uuid[])
                )
                ON CONFLICT (series_id, object_type, name) DO UPDATE
                SET
                    description = EXCLUDED.description,
                    distinctive_features = EXCLUDED.distinctive_features,
                    state_notes = EXCLUDED.state_notes,
                    source_unit_ids = EXCLUDED.source_unit_ids
                """
            ),
            {
                "series_id": str(series_id),
                "object_type": extracted.object_type,
                "name": extracted.name,
                "description": extracted.description,
                "distinctive_features": extracted.distinctive_features,
                "state_notes": extracted.state_notes,
                "source_unit_ids": source_ids,
            },
        )
        object_count += 1

    db.execute(
        text("UPDATE seasons SET story_status = 'analysis_complete' WHERE id = :season_id"),
        {"season_id": str(season_id)},
    )
    db.commit()

    return {
        "season_id": str(season_id),
        "characters_created_or_updated": character_count,
        "costumes_created": costume_count,
        "continuity_objects_created_or_updated": object_count,
    }
    query = text(
        """
        INSERT INTO characters (
            series_id,
            name,
            role,
            personality,
            story_role
        )
        SELECT
            s.id,
            :name,
            :role,
            :personality,
            :story_role
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE s.id = :series_id
          AND u.email = :email
        RETURNING
            id,
            series_id,
            name,
            role,
            personality,
            story_role,
            created_at,
            updated_at
        """
    )

    result = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "name": payload.name,
            "role": payload.role,
            "personality": payload.personality,
            "story_role": payload.story_role,
        },
    )

    character = result.mappings().first()

    if character is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Series was not found",
        )

    db.commit()

    return dict(character)


@app.get("/api/v1/characters/{character_id}/versions")
def get_character_versions(
    character_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            cv.id,
            cv.character_id,
            cv.version_number,
            cv.description,
            cv.face_and_body_design,
            cv.clothing_and_accessories,
            cv.distinctive_features,
            cv.color_palette,
            cv.voice_profile,
            cv.status,
            cv.change_notes,
            cv.created_at
        FROM character_versions cv
        JOIN characters c ON c.id = cv.character_id
        JOIN series s ON s.id = c.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE cv.character_id = :character_id
          AND u.email = :email
        ORDER BY cv.version_number DESC
        """
    )

    result = db.execute(
        query,
        {
            "character_id": str(character_id),
            "email": DEV_USER_EMAIL,
        },
    )

    versions = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(versions),
        "items": versions,
    }


@app.post("/api/v1/characters/{character_id}/versions")
def create_character_version(
    character_id: UUID,
    payload: CharacterVersionCreate,
    db: Session = Depends(get_db),
):
    version_query = text(
        """
        SELECT COALESCE(MAX(cv.version_number), 0) + 1 AS next_version
        FROM character_versions cv
        WHERE cv.character_id = :character_id
        """
    )

    next_version = db.execute(
        version_query,
        {"character_id": str(character_id)},
    ).scalar_one()

    insert_query = text(
        """
        INSERT INTO character_versions (
            character_id,
            version_number,
            description,
            face_and_body_design,
            clothing_and_accessories,
            distinctive_features,
            color_palette,
            voice_profile,
            status,
            change_notes
        )
        SELECT
            c.id,
            :version_number,
            :description,
            :face_and_body_design,
            :clothing_and_accessories,
            :distinctive_features,
            CAST(:color_palette AS jsonb),
            CAST(:voice_profile AS jsonb),
            CAST(:status AS approval_status),
            :change_notes
        FROM characters c
        JOIN series s ON s.id = c.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE c.id = :character_id
          AND u.email = :email
        RETURNING
            id,
            character_id,
            version_number,
            description,
            face_and_body_design,
            clothing_and_accessories,
            distinctive_features,
            color_palette,
            voice_profile,
            status,
            change_notes,
            created_at
        """
    )

    result = db.execute(
        insert_query,
        {
            "character_id": str(character_id),
            "email": DEV_USER_EMAIL,
            "version_number": next_version,
            "description": payload.description,
            "face_and_body_design": payload.face_and_body_design,
            "clothing_and_accessories": payload.clothing_and_accessories,
            "distinctive_features": payload.distinctive_features,
            "color_palette": json.dumps(payload.color_palette),
            "voice_profile": json.dumps(payload.voice_profile),
            "status": payload.status,
            "change_notes": payload.change_notes,
        },
    )

    version = result.mappings().first()

    if version is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Character was not found",
        )

    db.commit()

    return dict(version)


@app.get("/api/v1/episodes/{episode_id}/scenes")
def get_episode_scenes(
    episode_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            sc.id,
            sc.episode_id,
            sc.scene_number,
            sc.title,
            sc.description,
            sc.dialogue,
            sc.continuity_state,
            sc.environment_notes,
            sc.created_at,
            sc.updated_at,
            COUNT(sf.id) AS storyboard_frame_count
        FROM scenes sc
        JOIN episodes e ON e.id = sc.episode_id
        JOIN series s ON s.id = e.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN storyboard_frames sf ON sf.scene_id = sc.id
        WHERE sc.episode_id = :episode_id
          AND u.email = :email
        GROUP BY
            sc.id,
            sc.episode_id,
            sc.scene_number,
            sc.title,
            sc.description,
            sc.dialogue,
            sc.continuity_state,
            sc.environment_notes,
            sc.created_at,
            sc.updated_at
        ORDER BY sc.scene_number
        """
    )

    result = db.execute(
        query,
        {
            "episode_id": str(episode_id),
            "email": DEV_USER_EMAIL,
        },
    )

    scenes = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(scenes),
        "items": scenes,
    }


@app.post("/api/v1/episodes/{episode_id}/scenes")
def create_scene(
    episode_id: UUID,
    payload: SceneCreate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        INSERT INTO scenes (
            episode_id,
            scene_number,
            title,
            description,
            dialogue,
            continuity_state,
            environment_notes
        )
        SELECT
            e.id,
            :scene_number,
            :title,
            :description,
            CAST(:dialogue AS jsonb),
            CAST(:continuity_state AS jsonb),
            :environment_notes
        FROM episodes e
        JOIN series s ON s.id = e.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE e.id = :episode_id
          AND u.email = :email
        RETURNING
            id,
            episode_id,
            scene_number,
            title,
            description,
            dialogue,
            continuity_state,
            environment_notes,
            created_at,
            updated_at
        """
    )

    result = db.execute(
        query,
        {
            "episode_id": str(episode_id),
            "email": DEV_USER_EMAIL,
            "scene_number": payload.scene_number,
            "title": payload.title,
            "description": payload.description,
            "dialogue": json.dumps(payload.dialogue),
            "continuity_state": json.dumps(payload.continuity_state),
            "environment_notes": payload.environment_notes,
        },
    )

    scene = result.mappings().first()

    if scene is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Episode was not found",
        )

    db.commit()

    return dict(scene)


@app.get("/api/v1/scenes/{scene_id}/storyboards")
def get_scene_storyboards(
    scene_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            sf.id,
            sf.scene_id,
            sf.frame_number,
            sf.version_number,
            sf.prompt,
            sf.image_asset_id,
            sf.character_version_ids,
            sf.status,
            sf.dependency_metadata,
            sf.created_at,
            gj.id AS job_id,
            gj.status AS job_status,
            gj.provider,
            gj.provider_model
        FROM storyboard_frames sf
        JOIN scenes sc ON sc.id = sf.scene_id
        JOIN episodes e ON e.id = sc.episode_id
        JOIN series s ON s.id = e.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN generation_jobs gj
            ON gj.request_metadata->>'storyboard_frame_id' = sf.id::text
        WHERE sf.scene_id = :scene_id
          AND u.email = :email
        ORDER BY sf.frame_number, sf.version_number
        """
    )

    result = db.execute(
        query,
        {
            "scene_id": str(scene_id),
            "email": DEV_USER_EMAIL,
        },
    )

    frames = [dict(row) for row in result.mappings().all()]

    return {
        "count": len(frames),
        "items": frames,
    }


@app.post("/api/v1/scenes/{scene_id}/storyboards")
def create_storyboard_frame(
    scene_id: UUID,
    payload: StoryboardFrameCreate,
    db: Session = Depends(get_db),
):
    frame_query = text(
        """
        INSERT INTO storyboard_frames (
            scene_id,
            frame_number,
            version_number,
            prompt,
            character_version_ids,
            status,
            dependency_metadata
        )
        SELECT
            sc.id,
            :frame_number,
            :version_number,
            :prompt,
            CAST(:character_version_ids AS uuid[]),
            'draft',
            CAST(:dependency_metadata AS jsonb)
        FROM scenes sc
        JOIN episodes e ON e.id = sc.episode_id
        JOIN series s ON s.id = e.series_id
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE sc.id = :scene_id
          AND u.email = :email
        RETURNING
            id,
            scene_id,
            frame_number,
            version_number,
            prompt,
            character_version_ids,
            status,
            dependency_metadata,
            created_at
        """
    )

    character_ids = "{" + ",".join(str(item) for item in payload.character_version_ids) + "}"

    frame_result = db.execute(
        frame_query,
        {
            "scene_id": str(scene_id),
            "email": DEV_USER_EMAIL,
            "frame_number": payload.frame_number,
            "version_number": payload.version_number,
            "prompt": payload.prompt,
            "character_version_ids": character_ids,
            "dependency_metadata": json.dumps(payload.dependency_metadata),
        },
    )

    frame = frame_result.mappings().first()

    if frame is None:
        db.rollback()
        raise HTTPException(
            status_code=404,
            detail="Scene was not found",
        )

    job_query = text(
        """
        INSERT INTO generation_jobs (
            job_type,
            status,
            provider,
            provider_model,
            request_metadata,
            max_attempts
        )
        VALUES (
            'storyboard_generation',
            'queued',
            'mock',
            'mock-storyboard-v1',
            CAST(:request_metadata AS jsonb),
            1
        )
        RETURNING
            id,
            job_type,
            status,
            provider,
            provider_model,
            created_at
        """
    )

    job_result = db.execute(
        job_query,
        {
            "request_metadata": json.dumps(
                {
                    "storyboard_frame_id": str(frame["id"]),
                    "scene_id": str(scene_id),
                }
            )
        },
    )

    job = job_result.mappings().one()
    db.commit()

    return {
        "frame": dict(frame),
        "job": dict(job),
    }


@app.get("/api/v1/projects/{project_id}")
def get_project(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            p.id,
            p.owner_id,
            p.title,
            p.description,
            p.settings,
            p.created_at,
            p.updated_at,
            COUNT(DISTINCT s.id) AS series_count
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN series s ON s.project_id = p.id
        WHERE p.id = :project_id
          AND u.email = :email
        GROUP BY
            p.id,
            p.owner_id,
            p.title,
            p.description,
            p.settings,
            p.created_at,
            p.updated_at
        """
    )

    project = db.execute(
        query,
        {
            "project_id": str(project_id),
            "email": DEV_USER_EMAIL,
        },
    ).mappings().first()

    if project is None:
        raise HTTPException(status_code=404, detail="Project was not found")

    return dict(project)


@app.patch("/api/v1/projects/{project_id}")
def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE projects p
        SET
            title = COALESCE(:title, p.title),
            description = COALESCE(:description, p.description)
        FROM users u
        WHERE p.id = :project_id
          AND u.id = p.owner_id
          AND u.email = :email
        RETURNING
            p.id,
            p.owner_id,
            p.title,
            p.description,
            p.settings,
            p.created_at,
            p.updated_at
        """
    )

    project = db.execute(
        query,
        {
            "project_id": str(project_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "description": payload.description,
        },
    ).mappings().first()

    if project is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Project was not found")

    db.commit()
    return dict(project)


@app.get("/api/v1/projects/{project_id}/series")
def get_project_series(
    project_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.continuity_notes,
            s.created_at,
            s.updated_at,
            COUNT(DISTINCT e.id) AS episode_count
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        LEFT JOIN episodes e ON e.series_id = s.id
        WHERE s.project_id = :project_id
          AND u.email = :email
        GROUP BY
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.continuity_notes,
            s.created_at,
            s.updated_at
        ORDER BY s.created_at
        """
    )

    result = db.execute(
        query,
        {
            "project_id": str(project_id),
            "email": DEV_USER_EMAIL,
        },
    )

    series = [dict(row) for row in result.mappings().all()]
    return {"count": len(series), "items": series}


@app.patch("/api/v1/series/{series_id}")
def update_series(
    series_id: UUID,
    payload: SeriesUpdate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE series s
        SET
            title = COALESCE(:title, s.title),
            premise = COALESCE(:premise, s.premise),
            genre = COALESCE(:genre, s.genre),
            language_code = COALESCE(:language_code, s.language_code),
            visual_style = COALESCE(:visual_style, s.visual_style)
        FROM projects p
        JOIN users u ON u.id = p.owner_id
        WHERE s.id = :series_id
          AND p.id = s.project_id
          AND u.email = :email
        RETURNING
            s.id,
            s.project_id,
            s.title,
            s.premise,
            s.genre,
            s.language_code,
            s.visual_style,
            s.continuity_notes,
            s.created_at,
            s.updated_at
        """
    )

    series = db.execute(
        query,
        {
            "series_id": str(series_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "premise": payload.premise,
            "genre": payload.genre,
            "language_code": payload.language_code,
            "visual_style": payload.visual_style,
        },
    ).mappings().first()

    if series is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Series was not found")

    db.commit()
    return dict(series)


@app.patch("/api/v1/episodes/{episode_id}")
def update_episode(
    episode_id: UUID,
    payload: EpisodeUpdate,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE episodes e
        SET
            title = COALESCE(:title, e.title),
            synopsis = COALESCE(:synopsis, e.synopsis),
            script = COALESCE(:script, e.script),
            target_duration_seconds = COALESCE(
                :target_duration_seconds,
                e.target_duration_seconds
            ),
            status = COALESCE(:status, e.status)
        FROM series s
        JOIN projects p ON p.id = s.project_id
        JOIN users u ON u.id = p.owner_id
        WHERE e.id = :episode_id
          AND s.id = e.series_id
          AND u.email = :email
        RETURNING
            e.id,
            e.series_id,
            e.episode_number,
            e.title,
            e.synopsis,
            e.script,
            e.target_duration_seconds,
            e.status,
            e.created_at,
            e.updated_at
        """
    )

    episode = db.execute(
        query,
        {
            "episode_id": str(episode_id),
            "email": DEV_USER_EMAIL,
            "title": payload.title,
            "synopsis": payload.synopsis,
            "script": payload.script,
            "target_duration_seconds": payload.target_duration_seconds,
            "status": payload.status,
        },
    ).mappings().first()

    if episode is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Episode was not found")

    db.commit()
    return dict(episode)


@app.get("/api/v1/jobs/{job_id}")
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        SELECT
            id,
            job_type,
            status,
            progress,
            provider,
            provider_model,
            request_metadata,
            attempt_count,
            max_attempts,
            error_summary,
            estimated_cost,
            actual_cost,
            usage_metadata,
            output_asset_ids,
            created_at,
            started_at,
            completed_at
        FROM generation_jobs
        WHERE id = :job_id
        """
    )

    job = db.execute(query, {"job_id": str(job_id)}).mappings().first()

    if job is None:
        raise HTTPException(status_code=404, detail="Job was not found")

    return dict(job)


@app.post("/api/v1/jobs/{job_id}/run-mock")
def run_mock_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    job_query = text(
        """
        SELECT
            id,
            job_type,
            status,
            provider,
            provider_model,
            request_metadata
        FROM generation_jobs
        WHERE id = :job_id
        """
    )

    job = db.execute(
        job_query,
        {"job_id": str(job_id)},
    ).mappings().first()

    if job is None:
        raise HTTPException(status_code=404, detail="Job was not found")

    if job["provider"] != "mock":
        raise HTTPException(
            status_code=409,
            detail="Only mock-provider jobs can be run by this development endpoint",
        )

    if job["status"] != "queued":
        raise HTTPException(
            status_code=409,
            detail=f"Job cannot be run from status '{job['status']}'",
        )

    db.execute(
        text(
            """
            UPDATE generation_jobs
            SET status = 'running', progress = 10, started_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )
    db.commit()

    request_metadata = job["request_metadata"] or {}
    provider = MockStoryboardProvider()
    provider_result = provider.generate(
        GenerationRequest(
            job_type=str(job["job_type"]),
            prompt=request_metadata.get("prompt", "Mock storyboard frame"),
            input_metadata=request_metadata,
        )
    )

    output_metadata = {
        "provider": provider_result.provider,
        "model": provider_result.model,
        **provider_result.output_metadata,
    }

    completed = db.execute(
        text(
            """
            UPDATE generation_jobs
            SET
                status = 'succeeded',
                progress = 100,
                provider_model = :provider_model,
                usage_metadata = CAST(:usage_metadata AS jsonb),
                completed_at = now()
            WHERE id = :job_id
            RETURNING
                id,
                job_type,
                status,
                progress,
                provider,
                provider_model,
                usage_metadata,
                created_at,
                started_at,
                completed_at
            """
        ),
        {
            "job_id": str(job_id),
            "provider_model": provider_result.model,
            "usage_metadata": json.dumps(output_metadata),
        },
    ).mappings().one()

    db.commit()

    source_id = request_metadata.get("source_id")
    if source_id:
        db.execute(
            text(
                "UPDATE story_sources SET status = 'analysis_complete' "
                "WHERE id = :source_id"
            ),
            {"source_id": source_id},
        )
        db.execute(
            text(
                """
                UPDATE series s
                SET estimated_duration_seconds = GREATEST(
                        60,
                        CEIL(COALESCE(length(ss.raw_text), 0) / 12.0)::INTEGER
                    ),
                    updated_at = now()
                FROM story_sources ss
                WHERE ss.id = :source_id
                  AND ss.series_id = s.id
                """
            ),
            {"source_id": source_id},
        )

    season_id = request_metadata.get("season_id")
    if season_id:
        db.execute(
            text(
                "UPDATE seasons SET story_status = 'analysis_complete' "
                "WHERE id = :season_id"
            ),
            {"season_id": season_id},
        )

    db.commit()

    return dict(completed)


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_job(
    job_id: UUID,
    db: Session = Depends(get_db),
):
    query = text(
        """
        UPDATE generation_jobs
        SET
            status = 'cancelled',
            completed_at = now()
        WHERE id = :job_id
          AND status IN ('queued', 'running')
        RETURNING id, status, completed_at
        """
    )

    job = db.execute(query, {"job_id": str(job_id)}).mappings().first()

    if job is not None:
        db.commit()
        return dict(job)

    existing = db.execute(
        text("SELECT id, status FROM generation_jobs WHERE id = :job_id"),
        {"job_id": str(job_id)},
    ).mappings().first()

    if existing is None:
        raise HTTPException(status_code=404, detail="Job was not found")

    raise HTTPException(
        status_code=409,
        detail=f"Job cannot be cancelled from status '{existing['status']}'",
    )


@app.post("/api/v1/approvals")
def create_approval(
    payload: ApprovalCreate,
    db: Session = Depends(get_db),
):
    approval_query = text(
        """
        INSERT INTO approvals (
            entity_type,
            entity_id,
            decision,
            notes
        )
        VALUES (
            :entity_type,
            :entity_id,
            CAST(:decision AS approval_decision),
            :notes
        )
        RETURNING id, entity_type, entity_id, decision, notes, created_at
        """
    )

    approval = db.execute(
        approval_query,
        {
            "entity_type": payload.entity_type,
            "entity_id": str(payload.entity_id),
            "decision": payload.decision,
            "notes": payload.notes,
        },
    ).mappings().one()

    if payload.entity_type in {"character_version", "storyboard_frame"}:
        table = (
            "character_versions"
            if payload.entity_type == "character_version"
            else "storyboard_frames"
        )
        db.execute(
            text(
                f"UPDATE {table} SET status = CAST(:status AS approval_status) "
                "WHERE id = :entity_id"
            ),
            {
                "status": payload.decision,
                "entity_id": str(payload.entity_id),
            },
        )
    elif payload.entity_type == "episode":
        db.execute(
            text("UPDATE episodes SET status = :status WHERE id = :entity_id"),
            {
                "status": payload.decision,
                "entity_id": str(payload.entity_id),
            },
        )

    db.commit()
    return dict(approval)


@app.get("/api/v1/demo/overview")
def demo_overview(db: Session = Depends(get_db)):
    query = text(
        """
        SELECT
            p.id AS project_id,
            p.title AS project_title,
            s.id AS series_id,
            s.title AS series_title,
            e.id AS episode_id,
            e.title AS episode_title,
            e.target_duration_seconds,
            c.id AS character_id,
            c.name AS character_name,
            cv.id AS character_version_id,
            cv.version_number AS character_version,
            sc.id AS scene_id,
            sc.title AS scene_title,
            sf.id AS storyboard_frame_id,
            sf.status AS storyboard_status,
            gj.id AS job_id,
            gj.status AS job_status,
            gj.provider,
            gj.provider_model
        FROM users u
        JOIN projects p ON p.owner_id = u.id
        JOIN series s ON s.project_id = p.id
        JOIN episodes e ON e.series_id = s.id
        LEFT JOIN characters c ON c.series_id = s.id
        LEFT JOIN character_versions cv ON cv.character_id = c.id
        LEFT JOIN scenes sc ON sc.episode_id = e.id
        LEFT JOIN storyboard_frames sf ON sf.scene_id = sc.id
        LEFT JOIN generation_jobs gj
            ON gj.request_metadata->>'storyboard_frame_id' = sf.id::text
        WHERE u.email = :email
          AND p.title = :project_title
          AND s.title = :series_title
          AND e.episode_number = 1
        ORDER BY sc.scene_number, sf.frame_number
        """
    )

    result = db.execute(
        query,
        {
            "email": DEV_USER_EMAIL,
            "project_title": "Demo Drama Project",
            "series_title": "The First Signal",
        },
    )

    rows = [dict(row) for row in result.mappings().all()]

    if not rows:
        raise HTTPException(
            status_code=404,
            detail="Demo data was not found",
        )

    return {
        "count": len(rows),
        "items": rows,
    }
