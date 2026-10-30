import json
import re
import time
import urllib.error
import urllib.request
from typing import Any

from app.core.errors import PermanentJobError
from app.providers.llm_base import (
    LLMAnalysisRequest,
    LLMAnalysisResponse,
    LLMProviderError,
    LLMTruncatedError,
    chunk_reference,
)
from app.providers.llm_prompts import (
    ENTITY_PROMPT_VERSION,
    RESOLUTION_PROMPT_VERSION,
    build_entity_messages,
    STAGE_PROMPTS,
    build_resolution_messages,
    build_stage_messages,
    chunk_label,
)

# Re-exported for callers that import the error from here.
__all__ = ["OpenAICompatLLMProvider", "LLMProviderError", "LLMTruncatedError"]

ENTITY_LISTS = ("characters", "locations", "objects", "events", "relationships")
NAMED_LISTS = {"characters": "name", "locations": "name", "objects": "name", "events": "title"}


class OpenAICompatLLMProvider:
    """Calls any OpenAI-style /chat/completions endpoint (Gemini, OpenRouter, Ollama, ...)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        json_mode: bool = True,
        max_tokens: int = 16384,
        timeout: int = 120,
        max_attempts: int = 3,
        min_interval: float = 0.0,
        fallback_models: list[str] | None = None,
    ):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.models = [model, *(fallback_models or [])]
        self.api_key = api_key
        self.json_mode = json_mode
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_attempts = max_attempts
        self.min_interval = min_interval
        self._last_call = 0.0

    def analyze(self, request: LLMAnalysisRequest) -> LLMAnalysisResponse:
        if request.task == "entity_extraction":
            messages, version = build_entity_messages(request), ENTITY_PROMPT_VERSION
        elif request.task == "entity_resolution":
            messages, version = build_resolution_messages(request), RESOLUTION_PROMPT_VERSION
        elif request.task in STAGE_PROMPTS:
            messages, version = build_stage_messages(request), STAGE_PROMPTS[request.task][1]
        else:
            raise NotImplementedError(f"Task '{request.task}' is not supported yet")

        errors: list[str] = []
        for index, model in enumerate(self.models):
            try:
                content, usage = self._call_with_retries(model, messages)
            except PermanentJobError:
                if index == 0:
                    raise  # the main model is misconfigured: do not hide it
                errors.append(f"{model}: unavailable")
                continue
            except LLMTruncatedError:
                raise
            except LLMProviderError as error:
                errors.append(f"{model}: {error}")
                continue

            payload = parse_json_object(content)
            if request.task == "entity_extraction":
                payload = attach_references(clean_payload(payload), request.context_chunks)
            elif request.task == "master_script":
                payload = attach_unit_references(payload, request.context_chunks)
            return LLMAnalysisResponse(
                provider="openai_compat",
                model=model,
                prompt_version=version,
                payload=payload,
                usage_metadata=usage,
                raw=content,
            )
        raise LLMProviderError("All models failed: " + " | ".join(errors))

    def _call_with_retries(self, model: str, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        usage = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                content, call_usage = self._chat(model, messages)
                usage["calls"] += 1
                for key in ("prompt_tokens", "completion_tokens"):
                    usage[key] += int((call_usage or {}).get(key) or 0)
                parse_json_object(content)  # retry here if the reply is not valid JSON
                return content, usage
            except LLMTruncatedError:
                raise
            except LLMProviderError as error:
                last_error = error
                if attempt < self.max_attempts:
                    time.sleep(getattr(error, "retry_after", None) or 5 * 2 ** (attempt - 1))
        raise LLMProviderError(f"failed after {self.max_attempts} attempts: {last_error}")

    def _chat(self, model: str, messages: list[dict[str, str]]) -> tuple[str, dict[str, Any]]:
        wait = self.min_interval - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": self.max_tokens,
        }
        if self.json_mode:
            body["response_format"] = {"type": "json_object"}
        http_request = urllib.request.Request(
            self.url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                data = json.loads(response.read())
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:300]
            if not (error.code == 429 or error.code >= 500):
                # Bad key, bad model name, etc.: retrying will not help.
                raise PermanentJobError(f"LLM endpoint returned HTTP {error.code} for {model}: {detail}") from error
            failure = LLMProviderError(f"HTTP {error.code}: {detail}")
            retry_after = error.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                failure.retry_after = int(retry_after)
            raise failure from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise LLMProviderError(f"Network error: {error}") from error
        finally:
            self._last_call = time.monotonic()

        try:
            choice = data["choices"][0]
            content = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise LLMProviderError(f"Unexpected response shape: {str(data)[:300]}") from error
        if choice.get("finish_reason") == "length":
            raise LLMTruncatedError("Reply hit the output limit")
        return content, data.get("usage") or {}


def parse_json_object(content: str) -> dict[str, Any]:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise LLMProviderError("Response did not contain a JSON object")
    try:
        parsed = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as error:
        raise LLMProviderError(f"Response was not valid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise LLMProviderError("Response JSON was not an object")
    return parsed


def _confidence(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if 1 < value <= 100:
        value = value / 100
    return max(0.0, min(1.0, float(value)))


def clean_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop items a model got wrong so one bad entry does not fail the batch."""
    for list_name in ENTITY_LISTS:
        items = payload.get(list_name)
        if not isinstance(items, list):
            payload[list_name] = []
            continue
        kept = []
        for item in items:
            if not isinstance(item, dict):
                continue
            key = NAMED_LISTS.get(list_name)
            if key and not (isinstance(item.get(key), str) and item[key].strip()):
                continue
            if "confidence" in item:
                item["confidence"] = _confidence(item["confidence"])
            if isinstance(item.get("aliases"), list):
                item["aliases"] = [a for a in item["aliases"] if isinstance(a, str) and a.strip()]
            elif "aliases" in item:
                item["aliases"] = []
            if "id" in item and item["id"] is not None:
                item["id"] = str(item["id"])
            kept.append(item)
        payload[list_name] = kept
    if not isinstance(payload.get("analysis_notes"), list):
        payload["analysis_notes"] = []
    if not isinstance(payload.get("story_so_far"), str):
        payload["story_so_far"] = ""
    return payload


def attach_unit_references(payload: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Map the model's passage labels on master-script units to source_references."""
    by_label = {chunk_label(index): chunk_reference(chunk) for index, chunk in enumerate(chunks)}
    units = payload.get("units")
    payload["units"] = [u for u in units if isinstance(u, dict)] if isinstance(units, list) else []
    for unit in payload["units"]:
        refs = unit.pop("chunk_refs", None) or []
        unit["source_references"] = [by_label[r] for r in refs if isinstance(r, str) and r in by_label]
    return payload


def attach_references(payload: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Turn the model's passage labels (C1, C2, ...) into source_references."""
    by_label = {chunk_label(index): chunk_reference(chunk) for index, chunk in enumerate(chunks)}
    for list_name in ENTITY_LISTS:
        for item in payload[list_name]:
            refs = item.pop("chunk_refs", None) or []
            item["source_references"] = [
                by_label[ref] for ref in refs if isinstance(ref, str) and ref in by_label
            ]
    return payload
