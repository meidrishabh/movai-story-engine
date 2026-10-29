from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ProjectUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None


class SeriesCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    premise: str | None = None
    genre: str | None = None
    language_code: str = "en"
    visual_style: str | None = None


class SeriesUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    premise: str | None = None
    genre: str | None = None
    language_code: str | None = Field(default=None, min_length=2, max_length=10)
    visual_style: str | None = None


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


class EpisodeCreate(BaseModel):
    episode_number: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    synopsis: str | None = None
    script: str | None = None
    target_duration_seconds: int = Field(gt=0, le=3600)


class EpisodeUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    synopsis: str | None = None
    script: str | None = None
    target_duration_seconds: int | None = Field(default=None, gt=0, le=3600)
    status: str | None = Field(default=None, max_length=50)
