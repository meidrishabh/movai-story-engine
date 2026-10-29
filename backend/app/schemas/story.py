from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SeriesSeasonPlanRequest(BaseModel):
    target_season_count: int = Field(gt=0, le=100)
    target_episode_duration_seconds: int = Field(gt=0, le=3600)


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
