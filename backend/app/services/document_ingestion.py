import hashlib
import json
import math
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.document_normalization import extract_paragraphs, nearest_heading, normalize_story_text, page_boundaries
from app.services.document_parsers import parse_document
from app.services.story_complexity import analyze_story_complexity
from app.services.source_validation import validate_story_source


def chunk_story_text(raw_text: str, target_words: int = 900, overlap_words: int = 100):
    words = re.findall(r"\S+", raw_text)
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = min(len(words), start + target_words)
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(start + 1, end - overlap_words)
    return chunks


def mock_embedding(text_value: str, dimensions: int = 1536):
    values = []
    seed = text_value.encode("utf-8")
    counter = 0
    while len(values) < dimensions:
        digest = hashlib.sha256(seed + counter.to_bytes(4, "big")).digest()
        for index in range(0, len(digest), 4):
            if len(values) >= dimensions:
                break
            integer = int.from_bytes(digest[index:index + 4], "big")
            values.append(round((integer / 4294967295.0) * 2.0 - 1.0, 7))
        counter += 1
    return values


def vector_literal(values: list[float]):
    return "[" + ",".join(str(value) for value in values) + "]"


def prepare_source_document(db: Session, source: dict, payload, parsed_document=None):
    validation = validate_story_source(payload)
    parsed = parsed_document or parse_document(source_type=validation.source_type, raw_text=payload.raw_text)
    raw_text = parsed.text
    input_format = validation.input_format
    file_name = payload.original_filename or payload.metadata.get("original_filename")
    document_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    chunks = chunk_story_text(raw_text)
    boundaries = page_boundaries(parsed.page_texts)

    document = db.execute(
        text(
            """
            INSERT INTO source_documents (
                story_source_id, file_name, file_type, file_size_bytes,
                document_hash, page_count, validation_status,
                extraction_status, parser_name, parser_version,
                text_layer_detected, ocr_used, validation_metadata
            )
            VALUES (
                :source_id, :file_name, :file_type, :file_size_bytes,
                :document_hash, :page_count, 'validated', 'complete',
                :parser_name, :parser_version, :text_layer_detected, :ocr_used,
                CAST(:metadata AS jsonb)
            )
            RETURNING id
            """
        ),
        {
            "source_id": str(source["id"]),
            "file_name": file_name,
            "file_type": input_format or "text",
            "file_size_bytes": len(raw_text.encode("utf-8")),
            "document_hash": document_hash,
            "page_count": len(parsed.page_texts),
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
            "text_layer_detected": parsed.text_layer_detected,
            "ocr_used": parsed.ocr_used,
            "metadata": json.dumps({"text_layer": parsed.text_layer_detected, "ocr_used": parsed.ocr_used}),
        },
    ).scalar_one()

    for page_number, page_text in enumerate(parsed.page_texts, start=1):
        page = db.execute(
            text(
                """
                INSERT INTO document_pages (
                    document_id, page_number, has_text, text_length,
                    extraction_status, extracted_text, layout_type
                )
                VALUES (:document_id, :page_number, :has_text, :text_length,
                        'complete', :text, 'text')
                RETURNING id
                """
            ),
            {
                "document_id": str(document),
                "page_number": page_number,
                "has_text": bool(page_text),
                "text_length": len(page_text),
                "text": page_text,
            },
        ).scalar_one()
        for sequence_number, paragraph in enumerate(extract_paragraphs(page_text), start=1):
            db.execute(
                text(
                    """
                    INSERT INTO document_elements (
                        page_id, element_type, sequence_number, text_content
                    )
                    VALUES (:page_id, 'paragraph', :sequence_number, :text_content)
                    """
                ),
                {"page_id": str(page), "sequence_number": sequence_number, "text_content": paragraph},
            )

    search_cursor = 0
    for narrative_position, chunk_text in enumerate(chunks, start=1):
        chunk_start = raw_text.find(chunk_text, search_cursor)
        if chunk_start < 0:
            chunk_start = search_cursor
        chunk_end = chunk_start + len(chunk_text)
        search_cursor = max(chunk_start + 1, chunk_end - 100)
        overlapping_pages = [
            page_number for page_number, page_start, page_end in boundaries
            if chunk_start < page_end and chunk_end > page_start
        ]
        page_start = min(overlapping_pages) if overlapping_pages else None
        page_end = max(overlapping_pages) if overlapping_pages else None
        chapter_title = nearest_heading(raw_text, chunk_start)
        chunk = db.execute(
            text(
                """
                INSERT INTO story_chunks (
                    story_source_id, document_id, narrative_position,
                    chapter_title, page_start, page_end,
                    content_text, token_count, metadata
                )
                VALUES (
                    :source_id, :document_id, :narrative_position,
                    :chapter_title, :page_start, :page_end,
                    :content_text, :token_count, CAST(:metadata AS jsonb)
                )
                RETURNING id
                """
            ),
            {
                "source_id": str(source["id"]),
                "document_id": str(document),
                "narrative_position": narrative_position,
                "chapter_title": chapter_title,
                "page_start": page_start,
                "page_end": page_end,
                "content_text": chunk_text,
                "token_count": math.ceil(len(chunk_text.split()) * 1.3),
                "metadata": json.dumps({"input_format": input_format, "ocr_used": validation.ocr_used, "page_start": page_start, "page_end": page_end}),
            },
        ).scalar_one()
    db.execute(
        text(
            """
            UPDATE story_sources
            SET input_format = :input_format,
                validation_status = 'validated',
                status = 'embedding_queued',
                metadata = metadata || CAST(:metadata AS jsonb),
                updated_at = now()
            WHERE id = :source_id
            """
        ),
        {
            "source_id": str(source["id"]),
            "input_format": input_format,
            "metadata": json.dumps({"document_id": str(document), "chunk_count": len(chunks), "embedding_status": "queued"}),
        },
    )
    db.execute(
        text("""INSERT INTO generation_jobs (
            job_type, status, provider, provider_model, request_metadata, max_attempts)
            VALUES ('embedding_generation', 'queued', 'mock', 'mock-embedding', CAST(:request_metadata AS jsonb), 3)"""),
        {"request_metadata": json.dumps({"source_id": str(source["id"]), "document_id": str(document), "chunk_count": len(chunks)})},
    )
    complexity = analyze_story_complexity(raw_text)
    db.execute(
        text(
            """UPDATE series s
               SET analysis_profile = :profile,
                   analysis_complexity = CAST(:complexity AS jsonb),
                   updated_at = now()
               FROM story_sources ss
               LEFT JOIN seasons se ON se.id = ss.season_id
               WHERE ss.id = :source_id
                 AND s.id = COALESCE(ss.series_id, se.series_id)"""
        ),
        {
            "source_id": str(source["id"]),
            "profile": complexity["profile"],
            "complexity": json.dumps(complexity),
        },
    )
    return document
