from typing import Any

from pydantic import BaseModel, Field


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
