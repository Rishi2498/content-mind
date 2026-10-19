"""FFmpeg/FFprobe wrappers with hard timeouts and path confinement.

Every subprocess runs with ``subprocess.run(..., timeout=...)`` so a hung or
malicious media file cannot wedge the pipeline. Output paths are confined to
the per-user directory. On any failure the service returns a structured
result instead of raising, so the caller can mark the step degraded and keep
the rest of the pipeline running.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..config import get_settings


class FFmpegError(Exception):
    """Raised only for programmer errors; runtime failures return StepResult."""


@dataclass
class StepResult:
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)


def ffmpeg_available() -> bool:
    settings = get_settings()
    return shutil.which(settings.ffmpeg_path) is not None


def ffprobe_available() -> bool:
    settings = get_settings()
    return shutil.which(settings.ffprobe_path) is not None


def _timeout() -> int:
    return get_settings().media_ffmpeg_timeout


def _run(cmd: list[str], timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout or _timeout(),
        check=False,
        shell=False,
    )


def probe(path: Path) -> StepResult:
    """Return duration/width/height/has_audio via ffprobe."""
    if not ffprobe_available():
        return StepResult(ok=False, detail="ffprobe not available")
    if not path.is_file():
        return StepResult(ok=False, detail="file not found")
    cmd = [
        get_settings().ffprobe_path,
        "-v", "error",
        "-print_format", "json",
        "-show_format",
        "-show_streams",
        str(path),
    ]
    try:
        proc = _run(cmd)
    except subprocess.TimeoutExpired:
        return StepResult(ok=False, detail="ffprobe timed out")
    except OSError as exc:
        return StepResult(ok=False, detail=f"ffprobe failed to start: {exc}")
    if proc.returncode != 0:
        return StepResult(ok=False, detail="ffprobe returned an error for this file")
    try:
        info = json.loads(proc.stdout.decode("utf-8", errors="replace") or "{}")
    except json.JSONDecodeError:
        return StepResult(ok=False, detail="ffprobe output was not valid JSON")

    duration = None
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = None

    width = height = None
    has_audio = False
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video" and width is None:
            width = stream.get("width")
            height = stream.get("height")
        if stream.get("codec_type") == "audio":
            has_audio = True

    return StepResult(
        ok=True,
        data={
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "has_audio": has_audio,
        },
    )


def extract_keyframes(path: Path, out_dir: Path, count: int) -> StepResult:
    """Extract ``count`` evenly spaced JPEG keyframes into ``out_dir``.

    Uses the thumbnail filter which samples N frames across the whole
    duration, then writes numbered JPEGs ``keyframe_00.jpg`` etc.
    """
    if not ffmpeg_available():
        return StepResult(ok=False, detail="ffmpeg not available")
    if not path.is_file():
        return StepResult(ok=False, detail="file not found")
    count = max(1, min(count, 12))
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "keyframe_%02d.jpg"
    cmd = [
        get_settings().ffmpeg_path,
        "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-vf", f"thumbnail={count}",
        "-frames:v", str(count),
        "-q:v", "3",
        str(pattern),
    ]
    try:
        proc = _run(cmd)
    except subprocess.TimeoutExpired:
        return StepResult(ok=False, detail="keyframe extraction timed out")
    except OSError as exc:
        return StepResult(ok=False, detail=f"ffmpeg failed to start: {exc}")
    if proc.returncode != 0:
        return StepResult(ok=False, detail="ffmpeg could not extract keyframes from this file")

    frames = sorted(out_dir.glob("keyframe_*.jpg"))
    if not frames:
        return StepResult(ok=False, detail="no keyframes were produced")
    return StepResult(ok=True, data={"frames": [str(f) for f in frames]})


def extract_audio(path: Path, out_path: Path) -> StepResult:
    """Extract mono 16 kHz WAV audio (compact for speech-to-text)."""
    if not ffmpeg_available():
        return StepResult(ok=False, detail="ffmpeg not available")
    if not path.is_file():
        return StepResult(ok=False, detail="file not found")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_settings().ffmpeg_path,
        "-hide_banner", "-loglevel", "error",
        "-i", str(path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-f", "wav",
        str(out_path),
    ]
    try:
        proc = _run(cmd)
    except subprocess.TimeoutExpired:
        return StepResult(ok=False, detail="audio extraction timed out")
    except OSError as exc:
        return StepResult(ok=False, detail=f"ffmpeg failed to start: {exc}")
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return StepResult(ok=False, detail="ffmpeg could not extract audio from this file")
    return StepResult(ok=True, data={"audio_path": str(out_path)})


def extract_audio_segment(path: Path, out_path: Path, start: float, duration: float) -> StepResult:
    """Extract a short mono WAV segment (used to sample audio from images)."""
    if not ffmpeg_available():
        return StepResult(ok=False, detail="ffmpeg not available")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        get_settings().ffmpeg_path,
        "-hide_banner", "-loglevel", "error",
        "-ss", f"{max(0.0, start):.3f}",
        "-t", f"{max(0.1, duration):.3f}",
        "-i", str(path),
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
        str(out_path),
    ]
    try:
        proc = _run(cmd)
    except (subprocess.TimeoutExpired, OSError):
        return StepResult(ok=False, detail="audio segment extraction failed")
    if proc.returncode != 0 or not out_path.is_file() or out_path.stat().st_size == 0:
        out_path.unlink(missing_ok=True)
        return StepResult(ok=False, detail="ffmpeg could not extract an audio segment")
    return StepResult(ok=True, data={"audio_path": str(out_path)})
