from dataclasses import dataclass
from io import BytesIO

from app.services.document_normalization import normalize_story_text


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    page_texts: list[str]
    parser_name: str
    parser_version: str
    text_layer_detected: bool
    ocr_used: bool


def parse_document(
    *,
    source_type: str,
    raw_text: str | None = None,
    file_bytes: bytes | None = None,
) -> ParsedDocument:
    normalized_type = (source_type or "pasted_text").lower()

    if normalized_type in {"pdf", "novel_pdf"}:
        if not file_bytes:
            if not raw_text or not raw_text.strip():
                raise ValueError("PDF input requires extracted text or file content")
            return ParsedDocument(
                text=normalize_story_text(raw_text),
                page_texts=[normalize_story_text(raw_text)],
                parser_name="pdf-text-layer",
                parser_version="v1",
                text_layer_detected=True,
                ocr_used=False,
            )
        return _parse_pdf(file_bytes)

    if not raw_text or not raw_text.strip():
        raise ValueError("Text input is empty")
    parser_name = "markdown-text" if normalized_type in {"markdown", "md"} else "plain-text"
    text = normalize_story_text(raw_text)
    return ParsedDocument(
        text=text,
        page_texts=[text],
        parser_name=parser_name,
        parser_version="v1",
        text_layer_detected=True,
        ocr_used=False,
    )


def _parse_pdf(file_bytes: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("PDF parsing requires the pypdf dependency") from exc

    reader = PdfReader(BytesIO(file_bytes))
    page_texts = [normalize_story_text(page.extract_text() or "") for page in reader.pages]
    non_empty_pages = [page for page in page_texts if page]
    if not non_empty_pages:
        raise ValueError("PDF has no extractable text layer; scanned PDFs and OCR are not supported")
    return ParsedDocument(
        text="\n\n".join(non_empty_pages),
        page_texts=page_texts,
        parser_name="pdf-text-layer",
        parser_version="pypdf",
        text_layer_detected=True,
        ocr_used=False,
    )
