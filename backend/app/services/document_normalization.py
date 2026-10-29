import re


def normalize_story_text(raw_text: str) -> str:
    """Normalize transport noise while preserving narrative paragraphs and headings."""
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n").replace("\ufeff", "")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def extract_paragraphs(raw_text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", raw_text) if part.strip()]


def page_boundaries(page_texts: list[str]) -> list[tuple[int, int, int]]:
    """Return (page number, start offset, end offset) for normalized page text."""
    boundaries = []
    offset = 0
    for page_number, page_text in enumerate(page_texts, start=1):
        start = offset
        end = start + len(page_text)
        boundaries.append((page_number, start, end))
        offset = end + 2
    return boundaries


def nearest_heading(raw_text: str, position: int) -> str | None:
    prefix = raw_text[:position]
    headings = re.findall(r"(?mi)^(?:#{1,6}\s+|chapter\s+|prologue\s+|epilogue\s+)(.+)$", prefix)
    return headings[-1].strip() if headings else None
