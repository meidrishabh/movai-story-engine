"""Shared plumbing for LLM stages: call budget, usage, stored replies, schema retry."""
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.errors import PermanentJobError
from app.core.settings import settings
from app.providers.llm_base import LLMAnalysisRequest, LLMProvider, LLMProviderError
from app.repositories.analysis_repository import load_batches, save_batch


JUDGE_TASKS = {"filler_judge"}


def provider_model(provider: LLMProvider) -> str:
    models = getattr(provider, "models", None)
    return models[0] if models else type(provider).__name__


@dataclass
class RunState:
    calls: int = 0
    usage: dict = field(default_factory=lambda: {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
    model: str | None = None
    provider: str | None = None
    prompt_version: str | None = None


class LLMStageClient:
    """One per analysis job, shared by every stage so the call budget is global."""

    def __init__(self, provider: LLMProvider, judge_provider: LLMProvider | None = None):
        self.provider = provider
        self.judge_provider = judge_provider  # a second provider for judge tasks; None means use the main one
        self.state = RunState()
        self._stored: dict[tuple[str, str], dict[str, dict]] = {}

    def analyze(self, request: LLMAnalysisRequest):
        state = self.state
        if state.calls >= settings.llm_max_calls_per_run:
            raise PermanentJobError(
                f"Stopped after {state.calls} LLM calls (LLM_MAX_CALLS_PER_RUN). "
                "Finished steps are saved; raise the limit and re-run to continue."
            )
        state.calls += 1
        provider = self.judge_provider if self.judge_provider and request.task in JUDGE_TASKS else self.provider
        response = provider.analyze(request)
        for key in state.usage:
            state.usage[key] += int(response.usage_metadata.get(key) or 0)
        if request.task == "entity_extraction":
            state.model, state.provider, state.prompt_version = response.model, response.provider, response.prompt_version
        elif state.model is None:
            state.model, state.provider = response.model, response.provider
        return response

    def stored(self, db: Session, run_id, stage: str) -> dict[str, dict]:
        cache_key = (str(run_id), stage)
        if cache_key not in self._stored:
            self._stored[cache_key] = load_batches(db, run_id, stage)
        return self._stored[cache_key]

    def forget(self, db: Session, run_id, stage: str, key_prefix: str) -> None:
        """Drop stored replies so an explicit regenerate calls the model again."""
        db.execute(
            text("DELETE FROM analysis_batches WHERE analysis_run_id = :r AND stage_name = :s AND batch_key LIKE :p"),
            {"r": str(run_id), "s": stage, "p": key_prefix + "%"})
        db.commit()
        self._stored.pop((str(run_id), stage), None)

    def run(self, db: Session, run_id, stage: str, key: str, request: LLMAnalysisRequest,
            model_cls: type[BaseModel], chunk_ids: list[str] | None = None) -> BaseModel:
        """Return the validated reply for this call, from storage when it already ran."""
        stored = self.stored(db, run_id, stage)
        if key in stored:
            return model_cls.model_validate(stored[key]["parsed"])
        last_error: Exception | None = None
        for _ in range(2):  # one retry if the reply does not match the schema
            response = self.analyze(request)
            try:
                parsed = model_cls.model_validate(response.payload)
                break
            except ValidationError as error:
                last_error = error
        else:
            raise LLMProviderError(f"Reply did not match the schema twice: {str(last_error)[:300]}")
        save_batch(db, run_id, stage, key, chunk_ids or [], response)
        db.commit()
        stored[key] = {"parsed": response.payload}
        return parsed
