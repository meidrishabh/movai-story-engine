from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SourceReference(BaseModel):
    chunk_id: UUID | None = None
    page_start: int | None = None
    page_end: int | None = None
    narrative_position: int | None = None


class _Extracted(BaseModel):
    """Fields shared by everything the model reports. Text fields accept null."""

    id: str | None = None
    disambiguation: str | None = ""
    description: str | None = ""
    evidence: str | None = None
    source_references: list[SourceReference] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractedLocation(_Extracted):
    name: str = Field(min_length=1)


class ExtractedObject(_Extracted):
    name: str = Field(min_length=1)
    object_type: str | None = "artifact"
    distinctive_features: str | None = None


class ExtractedEvent(BaseModel):
    title: str = Field(min_length=1)
    description: str | None = ""
    event_type: str | None = None
    narrative_position: int | None = None
    chronological_position: int | None = None
    timeline_label: str | None = None
    evidence: str | None = None
    source_references: list[SourceReference] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ExtractedEntityCharacter(_Extracted):
    name: str = Field(min_length=1)
    role: str | None = None
    personality: str | None = None
    story_role: str | None = None
    aliases: list[str] = Field(default_factory=list)


class EntityExtractionResult(BaseModel):
    characters: list[ExtractedEntityCharacter] = Field(default_factory=list)
    locations: list[ExtractedLocation] = Field(default_factory=list)
    objects: list[ExtractedObject] = Field(default_factory=list)
    events: list[ExtractedEvent] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    analysis_notes: list[str] = Field(default_factory=list)
    story_so_far: str | None = ""
