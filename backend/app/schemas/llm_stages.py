"""Output contracts for the LLM stages after entity extraction.

Models reply with loose JSON, so every text field is optional and numbers are
accepted where text is expected. Null values are dropped before validation.
"""
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Loose(BaseModel):
    model_config = ConfigDict(coerce_numbers_to_str=True, extra="ignore")


# ----- entity resolution -------------------------------------------------

class ResolutionResult(_Loose):
    groups: list[dict[str, Any]] = Field(default_factory=list)


# ----- timeline ------------------------------------------------------------

class TimelineAnchorOut(_Loose):
    label: str = Field(min_length=1)
    time_start: str | None = None
    time_end: str | None = None
    timeline_type: str | None = None
    description: str | None = ""
    after: str | None = None


class TimelineRelationOut(_Loose):
    to: str
    type: str | None = "before"


class TimelineEventOut(_Loose):
    id: str
    anchor: str | None = None
    narrative_layer: str | None = "main"
    relations: list[TimelineRelationOut] = Field(default_factory=list)


class TimelineResult(_Loose):
    anchors: list[TimelineAnchorOut] = Field(default_factory=list)
    events: list[TimelineEventOut] = Field(default_factory=list)


# ----- continuity ----------------------------------------------------------

class CharacterStateOut(_Loose):
    event: str
    character: str
    location: str | None = None
    costume: str | None = None
    physical_condition: str | None = None
    age_or_stage: str | None = None
    knowledge: list[str] = Field(default_factory=list)
    relationship_changes: list[str] = Field(default_factory=list)
    changes: list[str] = Field(default_factory=list)


class ObjectStateOut(_Loose):
    event: str
    object: str
    owner: str | None = None
    location: str | None = None
    condition: str | None = None
    notes: str | None = None


class ConflictOut(_Loose):
    type: str | None = "state"
    severity: str | None = "warning"
    description: str = Field(min_length=1)
    events: list[str] = Field(default_factory=list)
    entity: str | None = None


class ContinuityResult(_Loose):
    character_states: list[CharacterStateOut] = Field(default_factory=list)
    object_states: list[ObjectStateOut] = Field(default_factory=list)
    conflicts: list[ConflictOut] = Field(default_factory=list)


# ----- master script -------------------------------------------------------

class SourceRef(_Loose):
    chunk_id: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    narrative_position: int | None = None


class UnitOut(_Loose):
    title: str = Field(min_length=1)
    synopsis: str | None = ""
    beats: list[str] = Field(default_factory=list)
    characters: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    setting: str | None = None
    screen_seconds: float | None = None
    source_references: list[SourceRef] = Field(default_factory=list)


class MasterScriptResult(_Loose):
    units: list[UnitOut] = Field(default_factory=list)
    running_summary: str | None = ""


# ----- season and episode planning --------------------------------------

class PlanEpisodeOut(_Loose):
    title: str | None = None
    synopsis: str | None = ""
    unit_from: int
    unit_to: int
    opening_hook: str | None = None
    climax_notes: str | None = None
    ending_notes: str | None = None


class PlanSeasonOut(_Loose):
    title: str | None = None
    synopsis: str | None = ""
    episodes: list[PlanEpisodeOut] = Field(default_factory=list)


class EpisodePlanResult(_Loose):
    seasons: list[PlanSeasonOut] = Field(default_factory=list)


# ----- scene and shot breakdown --------------------------------------------

class DialogueOut(_Loose):
    character: str
    line: str
    delivery: str | None = None


class ShotOut(_Loose):
    description: str = Field(min_length=1)
    camera: str | None = None
    duration_seconds: float | None = None
    characters: list[str] = Field(default_factory=list)


class SceneOut(_Loose):
    title: str | None = None
    description: str = Field(min_length=1)
    location: str | None = None
    time_of_day: str | None = None
    environment_notes: str | None = None
    characters: list[str] = Field(default_factory=list)
    dialogue: list[DialogueOut] = Field(default_factory=list)
    shots: list[ShotOut] = Field(default_factory=list)


class SceneBreakdownResult(_Loose):
    scenes: list[SceneOut] = Field(default_factory=list)


# ----- adaptations: filler detection, trailer and teaser ---------------------

class FillerItem(_Loose):
    unit: int
    beat: int | None = None  # 1-based beat number inside the unit; empty = the whole unit
    reason: str | None = ""
    seconds_saved: float | None = None


class FillerResult(_Loose):
    removals: list[FillerItem] = Field(default_factory=list)


class RepairedEpisode(_Loose):
    number: int
    synopsis: str | None = None
    opening_note: str | None = None
    closing_note: str | None = None


class EpisodeRepairResult(_Loose):
    episodes: list[RepairedEpisode] = Field(default_factory=list)


class JudgeVerdict(_Loose):
    id: str
    verdict: str  # "cut" or "keep"
    reason: str | None = ""


class JudgeResult(_Loose):
    verdicts: list[JudgeVerdict] = Field(default_factory=list)


class HighlightSegment(_Loose):
    unit: int | None = None
    description: str = Field(min_length=1)
    voiceover: str | None = None
    seconds: float | None = None


class HighlightResult(_Loose):
    title: str | None = None
    logline: str | None = ""
    segments: list[HighlightSegment] = Field(default_factory=list)


# ----- character appearance ------------------------------------------------

class CostumeOut(_Loose):
    name: str = Field(min_length=1)
    description: str | None = ""
    colors: list[str] = Field(default_factory=list)
    accessories: list[str] = Field(default_factory=list)
    when: str | None = None


class AppearanceResult(_Loose):
    @field_validator("description", "age", "face_and_body", "clothing", "distinctive_features", "voice", mode="before")
    @classmethod
    def _join_lists(cls, value):
        # Models often list traits ["scar", "limp"] where a sentence is asked for.
        return ", ".join(str(v) for v in value if v) or None if isinstance(value, list) else value

    description: str | None = None
    age: str | None = None
    face_and_body: str | None = None
    clothing: str | None = None
    distinctive_features: str | None = None
    color_palette: list[str] = Field(default_factory=list)
    voice: str | None = None
    costumes: list[CostumeOut] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
