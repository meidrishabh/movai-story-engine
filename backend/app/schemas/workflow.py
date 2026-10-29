from uuid import UUID

from pydantic import BaseModel, Field


class ApprovalCreate(BaseModel):
    entity_type: str = Field(pattern="^(character_version|storyboard_frame|scene|episode|render)$")
    entity_id: UUID
    decision: str = Field(pattern="^(approved|rejected)$")
    notes: str | None = None
