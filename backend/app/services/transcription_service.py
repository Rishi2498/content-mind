"""Hybrid transcription: API whisper-1 first, local faster-whisper fallback.

Provider selection (``WHISPER_PROVIDER``):

- ``auto``  — use the OpenAI-compatible API when ``LLM_API_KEY`` is set;
  otherwise try the local faster-whisper model; otherwise degrade.
- ``api``   — force the API path; degrade if unavailable.
- ``local`` — force the local model; degrade if unavailable.
- ``none``  — skip transcription entirely (metadata-only mode).

Every path returns a :class:`TranscriptionResult` instead of raising, so the
caller can record the step as degraded and continue the pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings
from .llm_service import get_llm_service

logger = logging.getLogger("contentmind.transcription")


@dataclass
class TranscriptionResult:
    transcript: str = ""
    language: str = ""
    provider: str = "none"  # api | local | none
    degraded: bool = False
    note: str = ""


def _transcribe_api(audio_path: Path) -> TranscriptionResult:
    """Upload the audio to the provider's whisper endpoint."""
    import httpx

    settings = get_settings()
    llm = get_llm_service()
    if not llm.available:
        return TranscriptionResult(degraded=True, note="api-unavailable")

    base = settings.llm_base_url.rstrip("/")
    # OpenAI puts audio transcription under /audio/transcriptions
    url = f"{base}/audio/transcriptions"
    try:
        with audio_path.open("rb") as f, httpx.Client(timeout=settings.llm_timeout) as client:
            response = client.post(
                url,
                headers={"Authorization": f"Bearer {settings.llm_api_key}"},
                data={"model": settings.whisper_api_model, "response_format": "json"},
                files={"file": (audio_path.name, f, "audio/wav")},
            )
        if response.status_code >= 400:
            return TranscriptionResult(
                degraded=True, note=f"whisper-api-error-{response.status_code}"
            )
        data = response.json()
        text = (data.get("text") or "").strip()
        language = (data.get("language") or "").strip()
        if not text:
            return TranscriptionResult(degraded=True, language=language, note="whisper-api-empty")
        return TranscriptionResult(
            transcript=text, language=language, provider="api", note="whisper-api"
        )
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("Whisper API transcription failed: %s", exc)
        return TranscriptionResult(degraded=True, note="whisper-api-failed")


def _transcribe_local(audio_path: Path) -> TranscriptionResult:
    """Run the optional faster-whisper model in-process."""
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    except ImportError:
        return TranscriptionResult(degraded=True, note="faster-whisper-not-installed")

    settings = get_settings()
    try:
        model = WhisperModel(settings.whisper_local_model, device="cpu", compute_type="int8")
        segments, info = model.transcribe(str(audio_path), beam_size=1)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        language = (info.language or "").strip()
        if not text:
            return TranscriptionResult(degraded=True, language=language, note="local-whisper-empty")
        return TranscriptionResult(
            transcript=text, language=language, provider="local", note="local-whisper"
        )
    except Exception as exc:  # noqa: BLE001 - model loading can fail many ways
        logger.warning("Local whisper transcription failed: %s", exc)
        return TranscriptionResult(degraded=True, note="local-whisper-failed")


def transcribe(audio_path: Path | None) -> TranscriptionResult:
    """Transcribe ``audio_path`` following the configured provider policy."""
    if audio_path is None or not audio_path.is_file():
        return TranscriptionResult(degraded=True, note="no-audio")

    policy = (get_settings().whisper_provider or "auto").lower()
    if policy == "none":
        return TranscriptionResult(degraded=True, note="transcription-disabled")

    if policy in {"auto", "api"}:
        result = _transcribe_api(audio_path)
        if result.provider == "api":
            return result
        if policy == "api":
            return result  # forced API; report degraded

    if policy in {"auto", "local"}:
        result = _transcribe_local(audio_path)
        if result.provider == "local":
            return result
        return result  # local failed or missing

    return TranscriptionResult(degraded=True, note="unknown-whisper-provider")
