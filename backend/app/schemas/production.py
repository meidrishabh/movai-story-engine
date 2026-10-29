from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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
