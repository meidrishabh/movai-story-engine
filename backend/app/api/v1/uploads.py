import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies import get_db
from app.core.config import DEV_USER_EMAIL
from app.schemas.story import StorySourceCreate
from app.services.document_ingestion import prepare_source_document
from app.services.document_parsers import parse_document


router = APIRouter(prefix="/api/v1", tags=["uploads"])


def _source_type(filename: str | None, requested: str) -> str:
    if requested and requested != "auto":
        return requested.lower()
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".pdf":
        return "novel_pdf"
    if suffix in {".md", ".markdown"}:
        return "markdown"
    raise ValueError("Only Markdown and PDF uploads are supported")


async def _read_and_parse(file: UploadFile, requested_type: str):
    content = await file.read()
    if not content:
        raise ValueError("Uploaded file is empty")
    source_type = _source_type(file.filename, requested_type)
    if len(content) > 25 * 1024 * 1024:
        raise ValueError("Uploaded file exceeds the 25 MB limit")
    if source_type in {"markdown", "md"}:
        raw_text = content.decode("utf-8-sig")
        parsed = parse_document(source_type="markdown", raw_text=raw_text)
    else:
        parsed = parse_document(source_type="novel_pdf", file_bytes=content)
    return source_type, parsed


def _insert_source(db: Session, scope_column: str, scope_id: UUID, payload: StorySourceCreate):
    if scope_column not in {"series_id", "season_id"}:
        raise ValueError("Invalid source scope")
    source = db.execute(
        text(
            f"""INSERT INTO story_sources ({scope_column}, title, source_type, original_filename, raw_text, metadata)
                SELECT {('s.id' if scope_column == 'series_id' else 'se.id')}, :title, :source_type,
                       :original_filename, :raw_text, CAST(:metadata AS jsonb)
                FROM {('series s JOIN projects p ON p.id = s.project_id' if scope_column == 'series_id' else 'seasons se JOIN series s ON s.id = se.series_id JOIN projects p ON p.id = s.project_id')}
                JOIN users u ON u.id = p.owner_id
                WHERE {('s.id' if scope_column == 'series_id' else 'se.id')} = :scope_id AND u.email = :email
                RETURNING id, series_id, season_id, title, source_type, original_filename, status, created_at, updated_at"""
        ),
        {"scope_id": str(scope_id), "email": DEV_USER_EMAIL, "title": payload.title,
         "source_type": payload.source_type, "original_filename": payload.original_filename,
         "raw_text": payload.raw_text, "metadata": json.dumps(payload.metadata)},
    ).mappings().first()
    return dict(source) if source else None


async def _create_upload(
    db: Session,
    scope_column: str,
    scope_id: UUID,
    title: str,
    requested_type: str,
    file: UploadFile,
):
    try:
        source_type, parsed = await _read_and_parse(file, requested_type)
    except (UnicodeDecodeError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    payload = StorySourceCreate(
        title=title or file.filename or "Uploaded story",
        source_type=source_type,
        original_filename=file.filename,
        raw_text=parsed.text,
        metadata={
            "input_format": "pdf_text" if source_type == "novel_pdf" else "markdown",
            "text_layer_detected": parsed.text_layer_detected,
            "ocr_used": parsed.ocr_used,
            "page_count": len(parsed.page_texts),
            "parser_name": parsed.parser_name,
            "parser_version": parsed.parser_version,
        },
    )
    source = _insert_source(db, scope_column, scope_id, payload)
    if source is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="Target was not found")
    try:
        document_id = prepare_source_document(db, source, payload, parsed_document=parsed)
    except (ValueError, RuntimeError) as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    result = dict(source)
    result["document_id"] = str(document_id)
    result["validation_status"] = "validated"
    return result


@router.post("/series/{series_id}/sources/upload")
async def upload_series_source(
    series_id: UUID,
    file: UploadFile = File(...),
    title: str = Form("Uploaded story"),
    source_type: str = Form("auto"),
    db: Session = Depends(get_db),
):
    return await _create_upload(db, "series_id", series_id, title, source_type, file)


@router.post("/seasons/{season_id}/sources/upload")
async def upload_season_source(
    season_id: UUID,
    file: UploadFile = File(...),
    title: str = Form("Uploaded story"),
    source_type: str = Form("auto"),
    db: Session = Depends(get_db),
):
    return await _create_upload(db, "season_id", season_id, title, source_type, file)
