"""Consistency judge: does a new image still look like the approved references of the same character, place or object?

Three modes, chosen by CONSISTENCY_JUDGE:
  llm_vision  an OpenAI-style chat model that accepts images (JUDGE_LLM_* settings, falling back to LLM_*). The real check.
  mock        compares average colour only. A placeholder so the flow can be tried without a vision model; the notes say so.
  none        skip the check.
A judge that cannot run (no references yet, the model rejects images, the network is down) never blocks generation: the
result carries no score and a note saying why.
"""
import base64
import io
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from app.core.settings import settings
from app.providers.media_base import ReferenceImage

MAX_REFERENCES = 3  # more than this adds cost without making the comparison better


@dataclass(frozen=True)
class JudgeResult:
    score: float | None  # 0 (different) to 1 (same); None when no comparison was made
    drift: bool
    notes: str
    judge: str


def judge_images(subject: str, image: ReferenceImage, references: list[ReferenceImage]) -> JudgeResult:
    mode = settings.consistency_judge.lower()
    if mode == "none":
        return JudgeResult(None, False, "The consistency check is turned off.", "none")
    if not references:
        return JudgeResult(None, False, "No approved reference to compare with yet.", mode)
    references = references[:MAX_REFERENCES]
    try:
        if mode == "mock":
            return _mock(image, references)
        if mode == "llm_vision":
            return _llm_vision(subject, image, references)
    except Exception as error:  # noqa: BLE001 - a judge failure must never fail the image
        return JudgeResult(None, False, f"The check could not run: {str(error)[:300]}", mode)
    return JudgeResult(None, False, f"Unknown CONSISTENCY_JUDGE '{settings.consistency_judge}'.", mode)


def _threshold(score: float) -> bool:
    return score < settings.consistency_threshold


def _mean_colour(data: bytes) -> tuple[float, float, float] | None:
    try:
        from PIL import Image  # optional: only the mock judge needs it
    except ImportError:
        return None
    with Image.open(io.BytesIO(data)) as picture:
        pixel = picture.convert("RGB").resize((1, 1)).getpixel((0, 0))
    return float(pixel[0]), float(pixel[1]), float(pixel[2])


def _mock(image: ReferenceImage, references: list[ReferenceImage]) -> JudgeResult:
    new = _mean_colour(image.data)
    colours = [c for c in (_mean_colour(r.data) for r in references) if c]
    if new is None or not colours:
        return JudgeResult(None, False, "MOCK judge: Pillow is not installed, so nothing was compared.", "mock")
    distance = min(sum(abs(a - b) for a, b in zip(new, c)) / (3 * 255) for c in colours)
    score = round(max(0.0, 1.0 - distance * 2), 3)
    return JudgeResult(score, _threshold(score), "MOCK judge: compared average colour only. Not a real consistency check.", "mock")


def _data_uri(image: ReferenceImage) -> str:
    return f"data:{image.mime_type};base64,{base64.b64encode(image.data).decode()}"


def _llm_vision(subject: str, image: ReferenceImage, references: list[ReferenceImage]) -> JudgeResult:
    base_url = settings.judge_llm_base_url or settings.llm_base_url
    model = settings.judge_llm_model or settings.llm_model
    api_key = settings.judge_llm_api_key or settings.llm_api_key
    if not (base_url and model and api_key):
        raise ValueError("llm_vision needs LLM_BASE_URL, LLM_MODEL and LLM_API_KEY (or the JUDGE_LLM_* ones) in backend/.env")
    content: list[dict] = [{"type": "text", "text": (
        f"You check visual consistency for an animated series. Subject: {subject}\n"
        f"The first {len(references)} image(s) are the approved reference(s). The last image is the new one. "
        "Does the new image show the same character, place or object, with the same face, build, clothing, colours and "
        "art style as the references? Ignore pose, framing and background. Reply with JSON only: "
        '{"score": <0 to 1, 1 = identical>, "notes": "<one or two sentences naming what differs>"}')}]
    for reference in references:
        content.append({"type": "image_url", "image_url": {"url": _data_uri(reference)}})
    content.append({"type": "image_url", "image_url": {"url": _data_uri(image)}})
    body = {"model": model, "temperature": 0, "max_tokens": 400, "messages": [{"role": "user", "content": content}]}
    http_request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    try:
        with urllib.request.urlopen(http_request, timeout=settings.llm_timeout_seconds) as response:
            reply = json.loads(response.read())
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"model returned HTTP {error.code}; it may not accept images") from error
    text = reply["choices"][0]["message"]["content"]
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("the model did not answer with JSON")
    data = json.loads(match.group(0))
    score = round(min(1.0, max(0.0, float(data["score"]))), 3)
    return JudgeResult(score, _threshold(score), str(data.get("notes") or "")[:500], "llm_vision")
