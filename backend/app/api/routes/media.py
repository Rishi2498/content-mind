"""Media asset upload, processing status, and DNA routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models import MediaAsset, MediaJob, User
from ...schemas import (
    ContentFromMediaRequest,
    ContentRead,
    MediaAssetDetail,
    MediaAssetListResponse,
    MediaAssetRead,
    MediaJobListResponse,
    MediaJobRead,
    MediaRetryResponse,
    MediaUploadResponse,
)
from ...services import media_service, media_storage

logger = logging.getLogger("contentmind.routes.media")
router = APIRouter()


@router.post("/upload", response_model=MediaUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    analyze: bool = Form(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaUploadResponse:
    """Upload a video/image/audio file and enqueue processing."""
    try:
        return await media_service.handle_upload(
            db, user=current_user, upload=file, background_tasks=background_tasks, analyze=analyze
        )
    except media_service.media_storage.MediaStorageError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("/assets", response_model=MediaAssetListResponse)
def list_assets(
    media_type: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaAssetListResponse:
    """List the current user's media assets (newest first)."""
    stmt = select(MediaAsset).where(MediaAsset.user_id == current_user.id)
    count_stmt = select(func.count(MediaAsset.id)).where(MediaAsset.user_id == current_user.id)
    if media_type:
        stmt = stmt.where(MediaAsset.media_type == media_type)
        count_stmt = count_stmt.where(MediaAsset.media_type == media_type)
    if status_filter:
        stmt = stmt.where(MediaAsset.status == status_filter)
        count_stmt = count_stmt.where(MediaAsset.status == status_filter)
    total = db.scalar(count_stmt) or 0
    rows = list(db.scalars(stmt.order_by(MediaAsset.id.desc()).limit(limit).offset(offset)))
    items = [media_service.asset_to_read(db, a) for a in rows]
    return MediaAssetListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/assets/{asset_id}", response_model=MediaAssetDetail)
def get_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaAssetDetail:
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Media asset {asset_id} not found")
    return media_service.asset_to_detail(db, asset)


@router.post(
    "/assets/{asset_id}/retry",
    response_model=MediaRetryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def retry_analysis(
    asset_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaRetryResponse:
    """Re-run analysis without re-uploading. Idempotent while a job is active."""
    try:
        result = media_service.create_retry_job(
            db, user_id=current_user.id, asset_id=asset_id
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=f"Media asset {asset_id} not found") from exc
    except media_service.RetryNotAllowed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if not result.deduplicated:
        asset = db.get(MediaAsset, asset_id)
        assert asset is not None
        media_service.enqueue_processing(background_tasks, asset.id, current_user.id, result.job.id)
    return result


@router.get("/assets/{asset_id}/file")
def preview_asset_file(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> FileResponse:
    """Serve the owner's original upload for in-app preview.

    Only browser-safe media MIME types are rendered inline; anything else is
    downloaded as an attachment. The endpoint is JWT-protected and never
    reveals the on-disk path.
    """
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Media asset {asset_id} not found")
    try:
        path = media_storage.stored_path(current_user.id, asset.stored_name)
    except media_storage.MediaStorageError as exc:
        raise HTTPException(status_code=404, detail="Media file not found") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")

    mime = (asset.mime_type or "").split(";", 1)[0].strip().lower()
    safe_inline = mime.startswith(("image/", "video/", "audio/")) and mime not in {
        "image/svg+xml",
        "image/svg",
    }
    return FileResponse(
        path,
        media_type=mime if safe_inline else "application/octet-stream",
        filename=asset.filename,
        content_disposition_type="inline" if safe_inline else "attachment",
        headers={
            "Cache-Control": "private, max-age=60",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_asset(
    asset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Media asset {asset_id} not found")
    from ...services import media_storage

    media_storage.delete_stored(current_user.id, asset.stored_name)
    db.delete(asset)  # cascades to jobs + DNA
    db.commit()


@router.get("/jobs", response_model=MediaJobListResponse)
def list_jobs(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaJobListResponse:
    stmt = select(MediaJob).where(MediaJob.user_id == current_user.id)
    total = db.scalar(select(func.count(MediaJob.id)).where(MediaJob.user_id == current_user.id)) or 0
    rows = list(db.scalars(stmt.order_by(MediaJob.id.desc()).limit(limit).offset(offset)))
    return MediaJobListResponse(
        items=[media_service.job_to_read(j) for j in rows], total=total
    )


@router.get("/jobs/{job_id}", response_model=MediaJobRead)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MediaJobRead:
    job = db.get(MediaJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Media job {job_id} not found")
    return media_service.job_to_read(job)


@router.post("/assets/{asset_id}/content", response_model=ContentRead, status_code=status.HTTP_201_CREATED)
def create_content_from_asset(
    asset_id: int,
    payload: ContentFromMediaRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContentRead:
    """Create a Content record from a processed asset's DNA."""
    content = media_service.create_content_from_media(
        db, user_id=current_user.id, asset_id=asset_id, payload=payload
    )
    if content is None:
        raise HTTPException(
            status_code=409,
            detail="Asset is not ready or has no DNA yet. Wait for processing to finish.",
        )
    db.commit()
    return ContentRead.model_validate(content)
