"""Media pipeline orchestration.

Flow for a full analysis job:

    upload -> create asset+job -> probe -> extract keyframes -> extract audio
           -> transcribe -> vision-analyze keyframes -> synthesize DNA
           -> (optional) create Content record

Each step records its outcome in ``MediaJob.steps`` so a reviewer can see
exactly what succeeded, failed, or was skipped. Steps degrade gracefully:
a failed transcription does not kill vision analysis, and vice versa. On
startup, jobs stuck in ``processing`` are marked failed (BackgroundTasks
processes do not survive a server restart).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import session_scope
from ..models import Content, ContentDNA, MediaAsset, MediaJob, User
from ..schemas import (
    ContentCreate,
    ContentFromMediaRequest,
    MediaAssetDetail,
    MediaAssetRead,
    MediaJobRead,
    MediaUploadResponse,
)
from . import content_service, ffmpeg_service, media_storage
from .content_dna_service import build_dna, synthesis_summary
from .transcription_service import transcribe
from .vision_service import analyze_keyframes

logger = logging.getLogger("contentmind.media")

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def classify_media_type(filename: str, mime_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _VIDEO_EXTS or (mime_type or "").startswith("video/"):
        return "video"
    if ext in _AUDIO_EXTS or (mime_type or "").startswith("audio/"):
        return "audio"
    if ext in _IMAGE_EXTS or (mime_type or "").startswith("image/"):
        return "image"
    # default: treat unknown as video so ffmpeg gets a chance
    return "video"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------------
# Job helpers
# ----------------------------------------------------------------------------------
def _step(steps: dict, name: str, status: str, detail: str = "") -> None:
    steps[name] = {"status": status, "detail": detail[:300]}


def create_asset_and_job(
    db: Session,
    *,
    user_id: int,
    stored: media_storage.StoredFile,
    filename: str,
    media_type: str,
) -> tuple[MediaAsset, MediaJob]:
    asset = MediaAsset(
        user_id=user_id,
        filename=filename,
        stored_name=stored.stored_name,
        mime_type=stored.mime_type,
        file_size=stored.size,
        media_type=media_type,
        status="uploaded",
    )
    db.add(asset)
    db.flush()
    job = MediaJob(user_id=user_id, asset_id=asset.id, job_type="full", status="pending", steps={})
    db.add(job)
    db.commit()
    return asset, job


def enqueue_processing(background_tasks: BackgroundTasks, asset_id: int, user_id: int, job_id: int) -> None:
    background_tasks.add_task(process_asset, asset_id=asset_id, user_id=user_id, job_id=job_id)


def recover_stale_jobs(db: Session) -> int:
    """Mark jobs stuck in processing/pending as failed (called on startup)."""
    rows = list(
        db.scalars(
            select(MediaJob).where(MediaJob.status.in_(["processing", "pending"]))
        )
    )
    for job in rows:
        job.status = "failed"
        job.error = "interrupted by server restart"
        job.completed_at = _utcnow()
        steps = dict(job.steps or {})
        _step(steps, "recovery", "failed", "job interrupted by restart")
        job.steps = steps
        asset = db.get(MediaAsset, job.asset_id)
        if asset is not None and asset.status in {"processing", "uploaded"}:
            asset.status = "failed"
    if rows:
        db.commit()
    return len(rows)


# ----------------------------------------------------------------------------------
# Pipeline
# ----------------------------------------------------------------------------------
def process_asset(*, asset_id: int, user_id: int, job_id: int) -> None:
    """Run the full pipeline. Executed as a FastAPI BackgroundTask."""
    try:
        with session_scope() as db:
            _run_pipeline(db, asset_id=asset_id, user_id=user_id, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 - background task must never raise
        logger.exception("Media pipeline crashed for asset %s", asset_id)
        try:
            with session_scope() as db:
                job = db.get(MediaJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = "internal processing error"
                    job.completed_at = _utcnow()
                asset = db.get(MediaAsset, asset_id)
                if asset is not None:
                    asset.status = "failed"
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record pipeline crash for asset %s", asset_id)


def _run_pipeline(db: Session, *, asset_id: int, user_id: int, job_id: int) -> None:
    asset = db.get(MediaAsset, asset_id)
    job = db.get(MediaJob, job_id)
    if asset is None or job is None or asset.user_id != user_id:
        return

    job.status = "processing"
    asset.status = "processing"
    db.commit()

    steps: dict = {}
    user_dir = media_storage.get_uploads_root() / f"user_{user_id}"
    src = user_dir / media_storage.sanitize_filename(asset.stored_name)
    work_dir = user_dir / f"work_{asset.id}"
    keyframe_paths: list[Path] = []
    audio_path: Path | None = None
    degraded = False

    # --- Step 1: probe (metadata) --------------------------------------------
    probe = ffmpeg_service.probe(src)
    if probe.ok:
        asset.duration_seconds = probe.data.get("duration_seconds")
        asset.width = probe.data.get("width")
        asset.height = probe.data.get("height")
        has_audio = probe.data.get("has_audio", False)
        _step(steps, "ffmpeg_probe", "ok", f"duration={asset.duration_seconds}")
    else:
        has_audio = asset.media_type in {"video", "audio"}
        _step(steps, "ffmpeg_probe", "failed" if asset.media_type != "image" else "skipped", probe.detail)
        if asset.media_type != "image":
            degraded = True
    db.commit()

    # --- Step 2: keyframes ----------------------------------------------------
    if asset.media_type == "video":
        kf = ffmpeg_service.extract_keyframes(src, work_dir / "keyframes", get_settings().media_keyframe_count)
        if kf.ok:
            keyframe_paths = [Path(p) for p in kf.data["frames"]]
            _step(steps, "keyframes", "ok", f"{len(keyframe_paths)} frames")
        else:
            _step(steps, "keyframes", "failed", kf.detail)
            degraded = True
    elif asset.media_type == "image":
        # single keyframe = the image itself
        if src.is_file():
            keyframe_paths = [src]
            _step(steps, "keyframes", "ok", "image treated as single keyframe")
        else:
            _step(steps, "keyframes", "failed", "source file missing")
            degraded = True
    else:
        _step(steps, "keyframes", "skipped", "audio-only asset")

    # --- Step 3: audio extraction + transcription -----------------------------
    if asset.media_type == "audio" and src.is_file():
        audio_path = src
        _step(steps, "audio_extract", "ok", "source is already audio")
    elif asset.media_type == "video" and has_audio and src.is_file():
        af = ffmpeg_service.extract_audio(src, work_dir / "audio.wav")
        if af.ok:
            audio_path = Path(af.data["audio_path"])
            _step(steps, "audio_extract", "ok", "wav extracted")
        else:
            _step(steps, "audio_extract", "failed", af.detail)
            degraded = True
    elif asset.media_type == "image":
        _step(steps, "audio_extract", "skipped", "image asset")
    else:
        _step(steps, "audio_extract", "skipped", "no audio track")

    transcription = None
    if audio_path is not None:
        transcription = transcribe(audio_path)
        if transcription.provider != "none":
            _step(steps, "transcribe", "ok" if not transcription.degraded else "degraded", transcription.note)
            if transcription.degraded:
                degraded = True
        else:
            _step(steps, "transcribe", "failed", transcription.note)
            degraded = True
    else:
        _step(steps, "transcribe", "skipped", "no audio to transcribe")

    # --- Step 4: vision -------------------------------------------------------
    vision = None
    if keyframe_paths:
        vision = analyze_keyframes(keyframe_paths)
        if not vision.degraded:
            _step(steps, "vision", "ok", vision.note)
        elif vision.analyses:
            _step(steps, "vision", "degraded", vision.note)
            degraded = True
        else:
            _step(steps, "vision", "failed", vision.note)
            degraded = True
    else:
        _step(steps, "vision", "skipped", "no keyframes")

    # --- Step 5: DNA synthesis ------------------------------------------------
    from .transcription_service import TranscriptionResult
    from .vision_service import VisionResult

    try:
        dna = build_dna(
            db,
            user_id=user_id,
            asset_id=asset.id,
            transcript_result=transcription or TranscriptionResult(degraded=True, note="no-transcript"),
            vision_result=vision or VisionResult(degraded=True, note="no-vision"),
            keyframe_paths=keyframe_paths,
            audio_path=audio_path,
        )
        _step(steps, "dna", "ok", f"dna_id={dna.id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("DNA synthesis failed for asset %s: %s", asset.id, exc)
        _step(steps, "dna", "failed", "synthesis error")
        degraded = True

    # --- finalize -------------------------------------------------------------
    job.steps = steps
    job.status = "completed"
    job.completed_at = _utcnow()
    job.error = "" if not degraded else "some steps degraded"
    asset.status = "ready" if not degraded else "ready"

    # cleanup intermediate work dir (keep keyframes? remove for now)
    try:
        import shutil

        if work_dir.is_dir():
            shutil.rmtree(work_dir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass

    db.commit()


# ----------------------------------------------------------------------------------
# Content creation from DNA
# ----------------------------------------------------------------------------------
def create_content_from_media(
    db: Session,
    *,
    user_id: int,
    asset_id: int,
    payload: ContentFromMediaRequest,
) -> Content | None:
    """Create a Content record linked to a processed asset's DNA."""
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != user_id or asset.status != "ready":
        return None
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset_id))
    if dna is None:
        return None

    synth = synthesis_summary(dna)
    title = payload.title or synth.get("title_suggestion") or asset.filename
    body = payload.body or synth.get("summary") or dna.transcript or ""
    content = content_service.create_content(
        db,
        ContentCreate(
            title=title[:300],
            body=body,
            platform=payload.platform or "Media",
            content_type=payload.topic and "video" or "video",
            topic=payload.topic or synth.get("topic") or "General",
        ),
        user_id,
    )
    content.source = "media"
    asset.content_id = content.id
    dna.content_id = content.id
    db.flush()
    return content


# ----------------------------------------------------------------------------------
# Serialization helpers (never leak storage paths)
# ----------------------------------------------------------------------------------
def asset_to_read(db: Session, asset: MediaAsset) -> MediaAssetRead:
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
    job = db.scalars(
        select(MediaJob).where(MediaJob.asset_id == asset.id).order_by(MediaJob.id.desc())
    ).first()
    return MediaAssetRead(
        id=asset.id,
        filename=asset.filename,
        mime_type=asset.mime_type,
        file_size=asset.file_size,
        media_type=asset.media_type,
        status=asset.status,
        duration_seconds=asset.duration_seconds,
        width=asset.width,
        height=asset.height,
        content_id=asset.content_id,
        created_at=asset.created_at,
        has_dna=dna is not None,
        job_status=job.status if job else None,
    )


def asset_to_detail(db: Session, asset: MediaAsset) -> MediaAssetDetail:
    base = asset_to_read(db, asset)
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
    jobs = list(
        db.scalars(
            select(MediaJob).where(MediaJob.asset_id == asset.id).order_by(MediaJob.id.desc())
        )
    )
    from ..schemas import ContentDNARead

    dna_read = ContentDNARead.model_validate(dna) if dna else None
    return MediaAssetDetail(
        **base.model_dump(),
        dna=dna_read,
        jobs=[MediaJobRead.model_validate(j) for j in jobs],
    )


def job_to_read(job: MediaJob) -> MediaJobRead:
    return MediaJobRead(
        id=job.id,
        asset_id=job.asset_id,
        job_type=job.job_type,
        status=job.status,
        error=job.error,
        steps=job.steps or {},
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


async def handle_upload(
    db: Session,
    *,
    user: User,
    upload: UploadFile,
    background_tasks: BackgroundTasks,
    analyze: bool = True,
) -> MediaUploadResponse:
    """Validate, store, and (optionally) enqueue processing of an upload."""
    filename = upload.filename or "upload"
    media_type = classify_media_type(filename, upload.content_type or "")

    stored = await media_storage.save_upload(user.id, upload, media_type)
    asset, job = create_asset_and_job(
        db, user_id=user.id, stored=stored, filename=filename, media_type=media_type
    )

    warnings: list[str] = []
    if analyze:
        enqueue_processing(background_tasks, asset.id, user.id, job.id)
    else:
        job.status = "completed"
        _step(job.steps or {}, "skipped", "skipped", "processing not requested")
        db.commit()

    return MediaUploadResponse(
        asset=asset_to_read(db, asset),
        job=job_to_read(job),
        warnings=warnings,
    )
