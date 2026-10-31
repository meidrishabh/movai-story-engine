"""Generated and uploaded files: the bytes live in a storage backend, the `assets` table keeps what describes them.

`AssetStorage` is the seam for another backend (S3 and the like). Only the local-disk one exists today.
"""
import hashlib
import json
import mimetypes
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.settings import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]
EXTENSIONS = {
    "image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "video/mp4": ".mp4", "video/webm": ".webm",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3", "audio/mp4": ".m4a", "text/vtt": ".vtt",
    "application/x-subrip": ".srt", "application/x-movai-placeholder": ".placeholder",
}
KINDS = ("image", "video", "audio", "subtitle", "other")


class AssetStorage(Protocol):
    def put(self, key: str, data: bytes) -> None: ...
    def read(self, key: str) -> bytes: ...
    def local_path(self, key: str) -> Path | None:
        """A file on disk for the key (lets the API stream with range requests and ffmpeg read it), or None."""
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalAssetStorage:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root not in path.parents:  # keys come from our own database, but never trust a path
            raise ValueError("Asset key points outside the storage folder")
        return path

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # a half-written file is never visible under its real name

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def local_path(self, key: str) -> Path | None:
        path = self._path(key)
        return path if path.exists() else None

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


def get_storage() -> AssetStorage:
    root = Path(settings.storage_dir)
    return LocalAssetStorage(root if root.is_absolute() else BACKEND_ROOT / root)


def kind_for(mime_type: str) -> str:
    major = mime_type.split("/")[0]
    if major in ("image", "video", "audio"):
        return major
    return "subtitle" if mime_type in ("text/vtt", "application/x-subrip") else "other"


def extension_for(mime_type: str, filename: str | None = None) -> str:
    if mime_type in EXTENSIONS:
        return EXTENSIONS[mime_type]
    if filename and Path(filename).suffix:
        return Path(filename).suffix.lower()[:10]
    return mimetypes.guess_extension(mime_type) or ".bin"


def save_asset(db: Session, data: bytes, mime_type: str, *, series_id: UUID | str, kind: str | None = None,
               provider: str | None = None, model: str | None = None, source_request_id: UUID | str | None = None,
               width: int | None = None, height: int | None = None, duration_seconds: float | None = None,
               filename: str | None = None, metadata: dict | None = None) -> dict:
    """Write the bytes to storage and record them. The caller commits."""
    kind = kind or kind_for(mime_type)
    if kind not in KINDS:
        raise ValueError(f"Unknown asset kind '{kind}'")
    asset_id = uuid4()
    key = f"{series_id}/{kind}/{asset_id}{extension_for(mime_type, filename)}"
    storage = get_storage()
    storage.put(key, data)
    try:
        row = db.execute(
            text("""INSERT INTO assets (id, series_id, kind, storage_key, original_filename, mime_type, byte_size,
                                        checksum_sha256, provider, provider_model, width, height, duration_seconds,
                                        source_request_id, metadata)
                    VALUES (:id, :series, :kind, :key, :filename, :mime, :size, :sha, :provider, :model, :w, :h, :d,
                            :req, CAST(:meta AS jsonb))
                    RETURNING *"""),
            {"id": str(asset_id), "series": str(series_id), "kind": kind, "key": key, "filename": filename,
             "mime": mime_type, "size": len(data), "sha": hashlib.sha256(data).hexdigest(), "provider": provider,
             "model": model, "w": width, "h": height, "d": duration_seconds,
             "req": str(source_request_id) if source_request_id else None, "meta": json.dumps(metadata or {})},
        ).mappings().one()
    except Exception:
        storage.delete(key)  # no orphan file when the row could not be written
        raise
    return dict(row)


def get_asset(db: Session, asset_id: UUID | str) -> dict | None:
    row = db.execute(text("SELECT * FROM assets WHERE id = :a"), {"a": str(asset_id)}).mappings().first()
    return dict(row) if row else None


def read_asset(db: Session, asset_id: UUID | str) -> tuple[dict, bytes]:
    asset = get_asset(db, asset_id)
    if asset is None:
        raise LookupError(f"Asset {asset_id} was not found")
    return asset, get_storage().read(asset["storage_key"])


def delete_asset(db: Session, asset_id: UUID | str) -> bool:
    """Remove the row and its file. Requests that pointed at it keep working (their link is cleared). The caller commits."""
    asset = get_asset(db, asset_id)
    if asset is None:
        return False
    db.execute(text("DELETE FROM assets WHERE id = :a"), {"a": str(asset_id)})
    get_storage().delete(asset["storage_key"])
    return True


def asset_summary(asset: dict | None) -> dict | None:
    """What the API shows about an asset; `url` is the path that serves the file."""
    if asset is None:
        return None
    return {"id": str(asset["id"]), "kind": asset["kind"], "mime_type": asset["mime_type"], "byte_size": asset["byte_size"],
            "width": asset["width"], "height": asset["height"],
            "duration_seconds": float(asset["duration_seconds"]) if asset["duration_seconds"] is not None else None,
            "provider": asset["provider"], "url": f"/api/v1/assets/{asset['id']}/file",
            "created_at": asset["created_at"]}
