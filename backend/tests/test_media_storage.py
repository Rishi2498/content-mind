"""Tests for safe media storage and FFmpeg wrappers (Phase 2, Step 2)."""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import pytest
from fastapi import UploadFile

os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("HINDSIGHT_ALLOW_LOCAL_FALLBACK", "1")
os.environ.pop("LLM_API_KEY", None)

from app.config import get_settings
from app.services import ffmpeg_service, media_storage
from app.services.media_storage import MediaStorageError, sanitize_filename


def _save(user_id: int, upload: UploadFile, media_type: str) -> media_storage.StoredFile:
    return asyncio.run(media_storage.save_upload(user_id, upload, media_type))


@pytest.fixture(autouse=True)
def _uploads_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIA_UPLOADS_DIR", str(tmp_path / "uploads"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _upload(name: str, content: bytes, mime: str = "video/mp4") -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=name, headers={"content-type": mime})


class TestSanitizeFilename:
    def test_strips_path_components(self):
        assert sanitize_filename("../../etc/passwd") == "passwd"
        assert sanitize_filename("..\\..\\win.ini") == "win.ini"
        assert sanitize_filename("C:/evil/x.mp4") == "x.mp4"

    def test_replaces_unsafe_chars(self):
        assert sanitize_filename("my video (1).mp4") == "my_video_1_.mp4"

    def test_never_empty(self):
        assert sanitize_filename("") == "upload"
        assert sanitize_filename("...") == "upload"


class TestSaveUpload:
    def test_saves_file_and_reports_size(self):
        stored = _save(7, _upload("clip.mp4", b"x" * 1000), "video")
        assert stored.path.is_file()
        assert stored.size == 1000
        assert stored.path.parent.name == "user_7"

    def test_enforces_size_limit(self, monkeypatch):
        monkeypatch.setenv("MEDIA_MAX_VIDEO_MB", "1")
        get_settings.cache_clear()
        with pytest.raises(MediaStorageError, match="exceeds limit"):
            _save(1, _upload("big.mp4", b"x" * (2 * 1024 * 1024)), "video")

    def test_no_path_traversal_on_write(self):
        stored = _save(3, _upload("../../escape.mp4", b"data"), "video")
        assert stored.path.is_relative_to(Path(get_settings().media_uploads_dir).resolve())

    def test_unique_names_on_collision(self):
        s1 = _save(1, _upload("a.mp4", b"1"), "video")
        s2 = _save(1, _upload("a.mp4", b"2"), "video")
        assert s1.stored_name != s2.stored_name
        assert s1.path.is_file() and s2.path.is_file()


class TestDeleteStored:
    def test_deletes_own_file(self):
        stored = _save(1, _upload("a.mp4", b"1"), "video")
        assert media_storage.delete_stored(1, stored.stored_name) is True
        assert not stored.path.exists()

    def test_refuses_traversal(self):
        assert media_storage.delete_stored(1, "../../etc/passwd") is False


class TestFFmpeg:
    def test_availability_probe_does_not_raise(self):
        assert isinstance(ffmpeg_service.ffmpeg_available(), bool)
        assert isinstance(ffmpeg_service.ffprobe_available(), bool)

    def test_probe_missing_file(self):
        res = ffmpeg_service.probe(Path("/nonexistent/nope.mp4"))
        assert res.ok is False
        assert res.detail

    def test_extract_audio_missing_file(self, tmp_path):
        res = ffmpeg_service.extract_audio(Path("/nope.mp4"), tmp_path / "a.wav")
        assert res.ok is False

    def test_extract_keyframes_missing_file(self, tmp_path):
        res = ffmpeg_service.extract_keyframes(Path("/nope.mp4"), tmp_path, 3)
        assert res.ok is False


@pytest.mark.skipif(
    not (ffmpeg_service.ffmpeg_available() and ffmpeg_service.ffprobe_available()),
    reason="ffmpeg/ffprobe not installed",
)
class TestFFmpegReal:
    """End-to-end checks against the real ffmpeg binary when present."""

    @pytest.fixture(scope="class")
    def tiny_video(self, tmp_path_factory):
        v = tmp_path_factory.mktemp("vid") / "tiny.mp4"
        import subprocess

        subprocess.run(
            [
                get_settings().ffmpeg_path,
                "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i", "testsrc=duration=2:size=128x96:rate=10",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-y", str(v),
            ],
            capture_output=True,
            timeout=60,
        )
        assert v.is_file()
        return v

    def test_probe_reports_duration_and_streams(self, tiny_video):
        res = ffmpeg_service.probe(tiny_video)
        assert res.ok
        assert res.data["duration_seconds"] == pytest.approx(2.0, abs=0.5)
        assert res.data["has_audio"] is True
        assert res.data["width"] == 128

    def test_extract_keyframes(self, tiny_video, tmp_path):
        res = ffmpeg_service.extract_keyframes(tiny_video, tmp_path / "kf", 3)
        assert res.ok
        frames = res.data["frames"]
        assert 1 <= len(frames) <= 3
        assert all(Path(f).suffix == ".jpg" for f in frames)

    def test_extract_audio(self, tiny_video, tmp_path):
        res = ffmpeg_service.extract_audio(tiny_video, tmp_path / "a.wav")
        assert res.ok
        assert Path(res.data["audio_path"]).stat().st_size > 0
