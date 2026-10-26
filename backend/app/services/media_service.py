"""Media pipeline orchestration.

Flow: upload -> asset+job -> probe -> keyframes -> audio -> transcribe ->
vision -> Content DNA. Each step records a user-facing message plus technical
detail so the UI can explain exactly what happened.

Important invariants:

* A failed vision/transcription step is never reported as success and never
  produces an empty "analysis". Metadata alone does not make an asset ready.
* A retry is a new job. It preserves successful signals already stored in
  ContentDNA, so a temporary provider outage cannot erase working analysis.
* Processing is idempotent from the UI's point of view: while an active job
  exists, retry returns that job instead of queueing duplicates.
"""

from __future__ import annotations

import logging
import shutil
import threading
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
    MediaAnalysisSummary,
    MediaAssetDetail,
    MediaAssetRead,
    MediaJobRead,
    MediaRetryResponse,
    MediaUploadResponse,
)
from . import content_service, ffmpeg_service, media_storage
from .content_dna_service import build_dna, dna_to_read, synthesis_summary
from .llm_service import get_llm_service
from .transcription_service import TranscriptionResult, transcribe
from .vision_service import VisionResult, analyze_keyframes

logger = logging.getLogger("contentmind.media")

_VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

_STEP_LABELS = {
    "ffmpeg_probe": "File details",
    "keyframes": "Keyframe extraction",
    "audio_extract": "Audio track",
    "transcribe": "Transcript",
    "vision": "Visual analysis",
    "dna": "Content insights",
    "analysis": "Analysis",
}
_SOURCE = "_source"
_ACTIVE_JOB_STATUSES = {"pending", "processing"}
_CREATE_LOCK = threading.Lock()


class RetryNotAllowed(Exception):
    """Raised when an asset cannot be retried (for example, file missing)."""


def classify_media_type(filename: str, mime_type: str) -> str:
    ext = Path(filename).suffix.lower()
    if ext in _VIDEO_EXTS or (mime_type or "").startswith("video/"):
        return "video"
    if ext in _AUDIO_EXTS or (mime_type or "").startswith("audio/"):
        return "audio"
    if ext in _IMAGE_EXTS or (mime_type or "").startswith("image/"):
        return "image"
    return "video"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------------
# Job helpers
# ----------------------------------------------------------------------------------
def _step(
    steps: dict,
    name: str,
    status: str,
    detail: str = "",
    message: str = "",
) -> None:
    steps[name] = {
        "status": status,
        "detail": (detail or "")[:300],
        "message": (message or "")[:240],
    }


def _step_label(name: str) -> str:
    return _STEP_LABELS.get(name, name.replace("_", " ").title())


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


def enqueue_processing(
    background_tasks: BackgroundTasks, asset_id: int, user_id: int, job_id: int
) -> None:
    background_tasks.add_task(process_asset, asset_id=asset_id, user_id=user_id, job_id=job_id)


def create_retry_job(db: Session, *, user_id: int, asset_id: int) -> MediaRetryResponse:
    """Queue a fresh analysis job, or return the already-active one.

    The lock makes the check-then-create operation safe within one process.
    A future multi-worker deployment should add a database-level partial unique
    index on active jobs; the current contract is still idempotent per worker.
    """
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != user_id:
        raise LookupError("asset-not-found")

    source = media_storage.stored_path(user_id, asset.stored_name)
    if not source.is_file():
        raise RetryNotAllowed(
            "The original file is missing from storage. Upload it again to analyze it."
        )

    with _CREATE_LOCK:
        active = db.scalar(
            select(MediaJob)
            .where(
                MediaJob.asset_id == asset_id,
                MediaJob.status.in_(sorted(_ACTIVE_JOB_STATUSES)),
            )
            .order_by(MediaJob.id.desc())
            .limit(1)
        )
        if active is not None:
            return MediaRetryResponse(
                asset=asset_to_read(db, asset),
                job=job_to_read(active),
                message="Analysis is already running for this file.",
                deduplicated=True,
            )

        job = MediaJob(
            user_id=user_id,
            asset_id=asset_id,
            job_type="full",
            status="pending",
            steps={},
        )
        db.add(job)
        asset.status = "processing"
        db.commit()
        db.refresh(job)
        db.refresh(asset)

    return MediaRetryResponse(
        asset=asset_to_read(db, asset),
        job=job_to_read(job),
        message="Analysis queued. You can keep using the app while it runs.",
        deduplicated=False,
    )


def recover_stale_jobs(db: Session) -> int:
    """Mark jobs stuck in processing/pending as interrupted (called on startup)."""
    rows = list(
        db.scalars(select(MediaJob).where(MediaJob.status.in_(["processing", "pending"])))
    )
    for job in rows:
        job.status = "failed"
        job.error = "Analysis was interrupted by a server restart. Retry when ready."
        job.completed_at = _utcnow()
        steps = dict(job.steps or {}) if isinstance(job.steps, dict) else {}
        _step(
            steps,
            "recovery",
            "failed",
            "job interrupted by restart",
            "Analysis was interrupted by a server restart.",
        )
        job.steps = steps
        asset = db.get(MediaAsset, job.asset_id)
        if asset is not None and asset.status in {"processing", "uploaded"}:
            dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
            asset.status = "partial" if _dna_has_signals(dna) else "failed"
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
    except Exception:  # noqa: BLE001 - background task must never raise
        logger.exception("Media pipeline crashed for asset %s", asset_id)
        try:
            with session_scope() as db:
                job = db.get(MediaJob, job_id)
                if job is not None:
                    job.status = "failed"
                    job.error = "Analysis hit an internal error. Retry when ready."
                    job.completed_at = _utcnow()
                    steps = dict(job.steps or {}) if isinstance(job.steps, dict) else {}
                    _step(
                        steps,
                        "pipeline",
                        "failed",
                        "unhandled pipeline exception",
                        "Analysis hit an internal error.",
                    )
                    job.steps = steps
                asset = db.get(MediaAsset, asset_id)
                if asset is not None:
                    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset_id))
                    asset.status = "partial" if _dna_has_signals(dna) else "failed"
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
    try:
        src = media_storage.stored_path(user_id, asset.stored_name)
    except media_storage.MediaStorageError:
        src = user_dir / "__missing__"
    work_dir = user_dir / f"work_{asset.id}"
    keyframe_paths: list[Path] = []
    audio_path: Path | None = None
    failed_steps: list[str] = []
    degraded_steps: list[str] = []

    if not src.is_file():
        _step(
            steps,
            _SOURCE,
            "failed",
            "stored source file missing",
            "The original file is missing from storage. Upload it again.",
        )
        failed_steps.append(_SOURCE)
        _finalize(
            db,
            asset=asset,
            job=job,
            steps=steps,
            dna=None,
            failed_steps=failed_steps,
            degraded_steps=degraded_steps,
            work_dir=work_dir,
        )
        return

    shutil.rmtree(work_dir, ignore_errors=True)

    # --- Step 1: probe (metadata) --------------------------------------------
    probe = ffmpeg_service.probe(src)
    if probe.ok:
        asset.duration_seconds = probe.data.get("duration_seconds")
        asset.width = probe.data.get("width")
        asset.height = probe.data.get("height")
        has_audio = probe.data.get("has_audio", False)
        _step(steps, "ffmpeg_probe", "completed", f"duration={asset.duration_seconds}")
    else:
        has_audio = asset.media_type in {"video", "audio"}
        if asset.media_type == "image":
            _step(
                steps,
                "ffmpeg_probe",
                "degraded",
                probe.detail,
                "File details couldn't be read, but visual analysis can still run.",
            )
            degraded_steps.append("ffmpeg_probe")
        else:
            _step(
                steps,
                "ffmpeg_probe",
                "failed",
                probe.detail,
                "File details couldn't be read, so audio and frame extraction may fail.",
            )
            failed_steps.append("ffmpeg_probe")
    db.commit()

    # --- Step 2: keyframes ----------------------------------------------------
    if asset.media_type == "video":
        kf = ffmpeg_service.extract_keyframes(
            src, work_dir / "keyframes", get_settings().media_keyframe_count
        )
        if kf.ok:
            keyframe_paths = [Path(p) for p in kf.data["frames"]]
            _step(steps, "keyframes", "completed", f"{len(keyframe_paths)} frames")
        else:
            _step(
                steps,
                "keyframes",
                "failed",
                kf.detail,
                "We couldn't extract frames from this video.",
            )
            failed_steps.append("keyframes")
    elif asset.media_type == "image":
        keyframe_paths = [src]
        _step(steps, "keyframes", "completed", "image treated as a single frame")
    else:
        _step(
            steps,
            "keyframes",
            "not_applicable",
            "audio-only asset",
            "Frame extraction isn't needed for audio files.",
        )

    # --- Step 3: audio extraction + transcription -----------------------------
    if asset.media_type == "audio":
        audio_path = src
        _step(steps, "audio_extract", "completed", "source is already audio")
    elif asset.media_type == "video" and has_audio:
        af = ffmpeg_service.extract_audio(src, work_dir / "audio.wav")
        if af.ok:
            audio_path = Path(af.data["audio_path"])
            _step(steps, "audio_extract", "completed", "wav extracted")
        else:
            _step(
                steps,
                "audio_extract",
                "failed",
                af.detail,
                "We couldn't extract the audio track from this video.",
            )
            failed_steps.append("audio_extract")
    elif asset.media_type == "image":
        _step(
            steps,
            "audio_extract",
            "not_applicable",
            "image asset",
            "Audio extraction isn't needed for images.",
        )
    else:
        _step(
            steps,
            "audio_extract",
            "not_applicable",
            "no audio track",
            "This video has no audio track.",
        )

    transcription = TranscriptionResult(degraded=True, note="not-attempted")
    if audio_path is not None:
        transcription = transcribe(audio_path)
        if not (transcription.transcript or "").strip():
            _step(
                steps,
                "transcribe",
                "failed",
                transcription.note,
                "Speech couldn't be transcribed. The rest of the analysis can still run.",
            )
            failed_steps.append("transcribe")
        elif transcription.degraded:
            _step(
                steps,
                "transcribe",
                "degraded",
                transcription.note,
                "Only part of the speech could be transcribed.",
            )
            degraded_steps.append("transcribe")
        else:
            _step(steps, "transcribe", "completed", transcription.note)
    elif asset.media_type == "image" or (
        asset.media_type == "video" and not has_audio
    ):
        _step(
            steps,
            "transcribe",
            "not_applicable",
            "no speech source",
            "Transcription isn't needed for this file.",
        )
    else:
        _step(
            steps,
            "transcribe",
            "failed",
            "audio unavailable",
            "The audio track wasn't available for transcription.",
        )
        failed_steps.append("transcribe")

    # --- Step 4: vision -------------------------------------------------------
    vision = VisionResult(degraded=True, note="not-attempted", attempted=False)
    if asset.media_type == "audio":
        _step(
            steps,
            "vision",
            "not_applicable",
            "audio-only asset",
            "Visual analysis isn't needed for audio files.",
        )
    elif keyframe_paths:
        vision = analyze_keyframes(keyframe_paths)
        if vision.ok:
            _step(steps, "vision", "completed", vision.note)
        elif vision.analyses:
            _step(
                steps,
                "vision",
                "degraded",
                vision.note,
                vision.user_message or "Some frames couldn't be analyzed.",
            )
            degraded_steps.append("vision")
        else:
            _step(
                steps,
                "vision",
                "failed",
                vision.note,
                vision.user_message or "Visual analysis couldn't be completed.",
            )
            failed_steps.append("vision")
    else:
        _step(
            steps,
            "vision",
            "failed",
            "no frames available",
            "There were no frames available for visual analysis.",
        )
        failed_steps.append("vision")

    # --- Step 5: DNA synthesis ------------------------------------------------
    dna: ContentDNA | None = None
    try:
        dna = build_dna(
            db,
            user_id=user_id,
            asset_id=asset.id,
            transcript_result=transcription,
            vision_result=vision,
            keyframe_paths=keyframe_paths,
            audio_path=audio_path,
            metadata={
                "media_type": asset.media_type,
                "filename": asset.filename,
                "duration_seconds": asset.duration_seconds,
                "has_audio": has_audio,
            },
            preserve_previous=True,
        )
        if dna is None:
            _step(
                steps,
                "dna",
                "skipped",
                "no usable analysis signals",
                "There wasn't enough usable analysis to build content insights.",
            )
        else:
            _step(steps, "dna", "completed", f"dna_id={dna.id}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("DNA synthesis failed for asset %s: %s", asset.id, exc)
        dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
        if _dna_has_signals(dna):
            _step(
                steps,
                "dna",
                "degraded",
                "synthesis error; kept previous insights",
                "Existing content insights were kept, but new synthesis failed.",
            )
            degraded_steps.append("dna")
        else:
            _step(
                steps,
                "dna",
                "failed",
                "synthesis error",
                "Content insights couldn't be generated from the available analysis.",
            )
            failed_steps.append("dna")

    _finalize(
        db,
        asset=asset,
        job=job,
        steps=steps,
        dna=dna,
        failed_steps=failed_steps,
        degraded_steps=degraded_steps,
        work_dir=work_dir,
    )


def _finalize(
    db: Session,
    *,
    asset: MediaAsset,
    job: MediaJob,
    steps: dict,
    dna: ContentDNA | None,
    failed_steps: list[str],
    degraded_steps: list[str],
    work_dir: Path,
) -> None:
    if dna is not None:
        if failed_steps or degraded_steps:
            asset.status = "partial"
        else:
            asset.status = "ready"
        job.status = "completed"
        job.error = (
            "Some analysis steps didn't complete; available insights were kept."
            if asset.status == "partial"
            else ""
        )
    else:
        asset.status = "failed"
        job.status = "failed"
        job.error = _failure_message(steps, failed_steps)

    job.steps = steps
    job.completed_at = _utcnow()

    shutil.rmtree(work_dir, ignore_errors=True)
    db.commit()


def _failure_message(steps: dict, failed_steps: list[str]) -> str:
    for name in failed_steps:
        value = steps.get(name)
        message = value.get("message") if isinstance(value, dict) else ""
        if message:
            return message
    return "We couldn't analyze this file. Retry when ready, or upload it again."


# ----------------------------------------------------------------------------------
# Content creation from DNA
# ----------------------------------------------------------------------------------
def _dna_has_signals(dna: ContentDNA | None) -> bool:
    if dna is None:
        return False
    return bool(
        (dna.transcript or "").strip()
        or (dna.scene_description or "").strip()
        or (dna.ocr_text or "").strip()
        or dna.visual_tags
    )


def create_content_from_media(
    db: Session,
    *,
    user_id: int,
    asset_id: int,
    payload: ContentFromMediaRequest,
) -> Content | None:
    """Create a Content record linked to a processed asset's DNA.

    Requires real analysis signals. Metadata-only uploads and failed analyses
    are rejected instead of receiving a generated placeholder article.
    """
    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != user_id or asset.status not in {"ready", "partial"}:
        return None
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset_id))
    if not _dna_has_signals(dna):
        return None
    assert dna is not None

    synth = synthesis_summary(dna)
    stem = Path(asset.filename).stem or asset.filename
    title = payload.title or synth.get("title_suggestion") or stem
    body = (
        payload.body
        or synth.get("summary")
        or dna.transcript
        or dna.ocr_text
        or dna.scene_description
        or ", ".join(dna.visual_tags or [])
        or ""
    )
    topic = payload.topic or synth.get("topic") or "Media upload"
    content = content_service.create_content(
        db,
        ContentCreate(
            title=title[:300],
            body=body,
            platform=payload.platform or "Media",
            content_type=asset.media_type if asset.media_type in {"video", "image", "audio"} else "article",
            topic=topic[:120],
            audience="",
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
def _latest_job(db: Session, asset_id: int) -> MediaJob | None:
    return db.scalars(
        select(MediaJob).where(MediaJob.asset_id == asset_id).order_by(MediaJob.id.desc())
    ).first()


def _analysis_summary(
    asset: MediaAsset, job: MediaJob | None, dna: ContentDNA | None
) -> MediaAnalysisSummary:
    steps: dict = _job_steps(job)
    completed = [
        _step_label(name)
        for name, value in steps.items()
        if name != _SOURCE
        and isinstance(value, dict)
        and value.get("status") == "completed"
    ]
    incomplete = [
        _step_label(name)
        for name, value in steps.items()
        if name != _SOURCE
        and isinstance(value, dict)
        and value.get("status") in {"failed", "degraded"}
    ]

    if job is not None and job.status in _ACTIVE_JOB_STATUSES:
        if asset.media_type == "image":
            message = "We're examining this image and building content insights."
        elif asset.media_type == "audio":
            message = "We're transcribing the audio and building content insights."
        else:
            message = "We're extracting visuals, speech when available, and content insights."
        return MediaAnalysisSummary(
            state="processing",
            label="Analyzing",
            message=message,
            completed=completed,
            incomplete=incomplete,
            retryable=False,
        )

    if asset.status in {"uploaded", "processing"}:
        return MediaAnalysisSummary(
            state=asset.status,
            label="Queued" if asset.status == "processing" else "Uploaded",
            message=(
                "Analysis is queued."
                if asset.status == "processing"
                else "This file is saved. Start analysis when you're ready."
            ),
            completed=completed,
            incomplete=incomplete,
            retryable=asset.status != "processing",
        )

    if not _dna_has_signals(dna):
        message = (job.error if job is not None else "") or (
            "We couldn't extract usable content from this file."
        )
        return MediaAnalysisSummary(
            state="failed",
            label="Analysis failed",
            message=message,
            completed=completed,
            incomplete=incomplete or ["Content insights"],
            retryable=True,
        )

    if asset.status == "partial" or incomplete:
        missing = ", ".join(incomplete) if incomplete else "some steps"
        return MediaAnalysisSummary(
            state="partial",
            label="Partially analyzed",
            message=f"Available insights are ready, but {missing} didn't fully complete.",
            completed=completed,
            incomplete=incomplete,
            retryable=True,
        )

    return MediaAnalysisSummary(
        state="complete",
        label="Analysis complete",
        message="All applicable analysis steps completed and content insights are ready.",
        completed=completed,
        incomplete=[],
        retryable=True,
    )


def asset_to_read(db: Session, asset: MediaAsset) -> MediaAssetRead:
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
    job = _latest_job(db, asset.id)
    try:
        preview_available = media_storage.stored_path(asset.user_id, asset.stored_name).is_file()
    except media_storage.MediaStorageError:
        preview_available = False
    has_insights = _dna_has_signals(dna)
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
        has_insights=has_insights,
        can_create_content=has_insights and asset.status in {"ready", "partial"},
        preview_available=preview_available,
        job_status=job.status if job else None,
        analysis=_analysis_summary(asset, job, dna),
    )


def asset_to_detail(db: Session, asset: MediaAsset) -> MediaAssetDetail:
    base = asset_to_read(db, asset)
    dna = db.scalar(select(ContentDNA).where(ContentDNA.asset_id == asset.id))
    jobs = list(
        db.scalars(
            select(MediaJob).where(MediaJob.asset_id == asset.id).order_by(MediaJob.id.desc())
        )
    )
    return MediaAssetDetail(
        **base.model_dump(),
        dna=dna_to_read(db, dna, asset=asset) if dna else None,
        jobs=[job_to_read(j) for j in jobs],
    )


def _job_steps(job: MediaJob | None) -> dict:
    if job is None or not isinstance(job.steps, dict):
        return {}
    return job.steps


def job_to_read(job: MediaJob) -> MediaJobRead:
    steps = _job_steps(job)
    retryable = job.status == "failed" or any(
        isinstance(value, dict) and value.get("status") in {"failed", "degraded"}
        for value in steps.values()
    )
    return MediaJobRead(
        id=job.id,
        asset_id=job.asset_id,
        job_type=job.job_type,
        status=job.status,
        error=job.error,
        steps=steps,
        created_at=job.created_at,
        completed_at=job.completed_at,
        retryable=retryable,
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
        if media_type in {"image", "video"} and not get_llm_service().available:
            warnings.append(
                "Visual analysis is not configured. The file is saved and can be analyzed "
                "after the AI provider is configured."
            )
        if media_type in {"video", "audio"} and not ffmpeg_service.ffmpeg_available():
            warnings.append(
                "FFmpeg is not installed. Video/audio metadata and transcription will be limited."
            )
        enqueue_processing(background_tasks, asset.id, user.id, job.id)
        asset.status = "processing"
        db.commit()
        db.refresh(asset)
    else:
        job.status = "completed"
        job.completed_at = _utcnow()
        skipped_steps = _job_steps(job)
        _step(
            skipped_steps,
            "analysis",
            "skipped",
            "processing not requested",
            "Analysis was not requested for this upload.",
        )
        job.steps = skipped_steps
        db.commit()
        db.refresh(asset)

    return MediaUploadResponse(
        asset=asset_to_read(db, asset),
        job=job_to_read(job),
        warnings=warnings,
    )
