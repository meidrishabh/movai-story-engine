from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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
