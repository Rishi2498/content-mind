"""Safe storage for uploaded media files.

All files live under a single uploads root organized by user id. Writes are
path-confined (no traversal outside the root), size-limited, and streamed in
chunks so a huge upload never loads fully into memory.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from ..config import get_settings

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


class MediaStorageError(Exception):
    """Raised for storage-level failures (size, confinement, missing file)."""


@dataclass(frozen=True)
class StoredFile:
    path: Path
    stored_name: str
    size: int
    mime_type: str


def get_uploads_root() -> Path:
    root = Path(get_settings().media_uploads_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _user_dir(user_id: int) -> Path:
    d = get_uploads_root() / f"user_{user_id}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_filename(name: str) -> str:
    """Strip path components and normalize to a safe basename."""
    name = unicodedata.normalize("NFKC", name or "upload")
    name = Path(name.replace("\\", "/")).name  # drop any directory part
    name = _SAFE_NAME.sub("_", name).strip("._")
    return name[:200] or "upload"


def max_bytes_for(mime_type: str, media_type: str) -> int:
    settings = get_settings()
    if media_type == "image":
        return settings.media_max_image_mb * 1024 * 1024
    return settings.media_max_video_mb * 1024 * 1024


def _confine(base: Path, candidate: Path) -> Path:
    base_r = base.resolve()
    cand_r = candidate.resolve()
    if not cand_r.is_relative_to(base_r):
        raise MediaStorageError("path escapes storage root")
    return cand_r


async def save_upload(user_id: int, upload: UploadFile, media_type: str) -> StoredFile:
    """Stream ``upload`` into the user's directory, enforcing the size cap.

    The file is written with a unique stored name (timestamp + sanitized
    original) so same-name uploads never overwrite each other. Partial writes
    are cleaned up on failure.
    """
    settings = get_settings()
    limit = max_bytes_for(upload.content_type or "", media_type)
    user_dir = _user_dir(user_id)
    safe = sanitize_filename(upload.filename or "upload")
    stored = f"u{user_id}_{safe}"

    # avoid collisions
    target = _confine(user_dir, user_dir / stored)
    counter = 1
    while target.exists():
        stem, dot, ext = safe.rpartition(".")
        if not dot:
            stem, ext = safe, ""
        stored = f"u{user_id}_{stem}_{counter}{('.' + ext) if dot else ''}"
        target = _confine(user_dir, user_dir / stored)
        counter += 1

    size = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)  # 1 MiB chunks
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise MediaStorageError(
                        f"file exceeds limit of {limit // (1024 * 1024)} MB"
                    )
                out.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    return StoredFile(
        path=target, stored_name=stored, size=size, mime_type=upload.content_type or "application/octet-stream"
    )


def stored_path(user_id: int, stored_name: str) -> Path:
    """Return the confined path for a stored file (may or may not exist)."""
    user_dir = _user_dir(user_id)
    return _confine(user_dir, user_dir / sanitize_filename(stored_name))


def delete_stored(user_id: int, stored_name: str) -> bool:
    """Delete a stored file, confined to the user's directory."""
    user_dir = _user_dir(user_id)
    try:
        target = _confine(user_dir, user_dir / sanitize_filename(stored_name))
    except MediaStorageError:
        return False
    if target.is_file():
        target.unlink()
        return True
    return False


def cleanup_user_dir(user_id: int) -> None:
    """Remove the whole per-user upload directory (e.g. account deletion)."""
    d = get_uploads_root() / f"user_{user_id}"
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
