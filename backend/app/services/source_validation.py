from dataclasses import dataclass
import re


SUPPORTED_SOURCE_TYPES = {"pasted_text", "text", "markdown", "md", "pdf", "novel_pdf"}


@dataclass(frozen=True)
class ValidatedStorySource:
    source_type: str
    input_format: str
    parser_name: str
    parser_version: str
    text_layer_detected: bool
    ocr_used: bool


def validate_story_source(payload) -> ValidatedStorySource:
    source_type = (payload.source_type or "pasted_text").strip().lower()
    metadata = payload.metadata or {}
    if source_type not in SUPPORTED_SOURCE_TYPES:
        raise ValueError(f"Unsupported story source type: {source_type}")

    raw_text = payload.raw_text or ""
    if not raw_text.strip():
        raise ValueError("Story input is empty")
    if len(raw_text.encode("utf-8")) > 25 * 1024 * 1024:
        raise ValueError("Story input exceeds the 25 MB limit")

    ocr_used = bool(metadata.get("ocr_used", False))
    text_layer_detected = bool(metadata.get("text_layer_detected", True))
    if source_type in {"pdf", "novel_pdf"} and (ocr_used or not text_layer_detected):
        raise ValueError("Scanned PDFs and OCR-based extraction are not supported")

    if source_type in {"markdown", "md"} or (source_type in {"pasted_text", "text"} and _looks_like_markdown(raw_text)):
        input_format = "markdown"
        parser_name = "markdown-text"
    elif source_type in {"pdf", "novel_pdf"}:
        input_format = "pdf_text"
        parser_name = "pdf-text-layer"
    else:
        input_format = "plain_text"
        parser_name = "plain-text"

    return ValidatedStorySource(
        source_type=source_type,
        input_format=input_format,
        parser_name=parser_name,
        parser_version="v1",
        text_layer_detected=text_layer_detected,
        ocr_used=ocr_used,
    )


def _looks_like_markdown(raw_text: str) -> bool:
    markers = re.findall(r"(?m)^(?:#{1,6}\s+|[-*+]\s+|>\s+|```)|\[[^\]]+\]\([^)]+\)", raw_text)
    return len(markers) >= 2 or bool(re.search(r"(?m)^#{1,6}\s+", raw_text))
