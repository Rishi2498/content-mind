"""API-level tests for media routes (Phase 2, Step 4).

Covers auth, tenant isolation, upload flow, job tracking, DNA exposure,
content creation from media, and startup recovery. AI calls are mocked;
ffmpeg is exercised for real when available.
"""

from __future__ import annotations

import io
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("HINDSIGHT_ALLOW_LOCAL_FALLBACK", "1")
os.environ.setdefault("WHISPER_PROVIDER", "none")
os.environ.pop("LLM_API_KEY", None)

from app.config import get_settings
from app.database import session_scope
from app.main import app
from app.models import MediaJob
from app.schemas import LLMImageAnalysis
from app.services import ffmpeg_service


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MEDIA_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("WHISPER_PROVIDER", "none")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _register_and_login(client: TestClient, email: str = "u@x.com") -> dict:
    client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    r = client.post("/api/auth/login", data={"username": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _image_upload(name: str = "pic.jpg", content: bytes = b"\xff\xd8\xff\xd9"):
    return {"file": (name, io.BytesIO(content), "image/jpeg")}


class TestAuthAndIsolation:
    def test_upload_requires_auth(self, client):
        r = client.post("/api/media/upload", files=_image_upload())
        assert r.status_code == 401

    def test_list_requires_auth(self, client):
        assert client.get("/api/media/assets").status_code == 401

    def test_other_tenant_cannot_see_asset(self, client):
        h_a = _register_and_login(client, "a@x.com")
        r = client.post("/api/media/upload", headers=h_a, files=_image_upload(), data={"analyze": "false"})
        aid = r.json()["asset"]["id"]
        h_b = _register_and_login(client, "b@x.com")
        assert client.get(f"/api/media/assets/{aid}", headers=h_b).status_code == 404
        assert client.get("/api/media/assets", headers=h_b).json()["total"] == 0
        assert client.delete(f"/api/media/assets/{aid}", headers=h_b).status_code == 404


class TestUploadFlow:
    def test_upload_image_no_analyze(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "false"})
        assert r.status_code == 201
        body = r.json()
        assert body["asset"]["media_type"] == "image"
        assert body["asset"]["status"] == "uploaded"
        assert body["job"]["status"] == "completed"

    def test_upload_enqueues_job_when_analyze(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "true"})
        assert r.status_code == 201
        assert r.json()["job"]["status"] == "pending"

    def test_list_and_detail(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "false"})
        aid = r.json()["asset"]["id"]
        listing = client.get("/api/media/assets", headers=h).json()
        assert listing["total"] == 1
        detail = client.get(f"/api/media/assets/{aid}", headers=h).json()
        assert detail["id"] == aid
        assert detail["has_dna"] is False
        assert len(detail["jobs"]) == 1

    def test_delete_removes_asset(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "false"})
        aid = r.json()["asset"]["id"]
        assert client.delete(f"/api/media/assets/{aid}", headers=h).status_code == 204
        assert client.get(f"/api/media/assets/{aid}", headers=h).status_code == 404

    def test_storage_path_never_exposed(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "false"})
        text = r.text
        assert "uploads" not in text
        assert "stored_name" not in text
        assert str(get_settings().media_uploads_dir) not in text


@pytest.mark.skipif(
    not ffmpeg_service.ffmpeg_available(), reason="ffmpeg not installed"
)
class TestFullPipeline:
    """Run the real pipeline on a tiny generated video with mocked AI."""

    @pytest.fixture()
    def tiny_video_bytes(self, tmp_path_factory):
        v = tmp_path_factory.mktemp("src") / "tiny.mp4"
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
        return v.read_bytes()

    def test_video_pipeline_creates_dna(self, client, tiny_video_bytes):
        h = _register_and_login(client)
        fake_vision = LLMImageAnalysis(
            scene_description="test pattern with color bars",
            ocr_text="",
            visual_tags=["test pattern", "color bars"],
        )
        with (
            patch("app.services.vision_service.get_llm_service") as mock_vlm,
        ):
            mock_llm = type("M", (), {})()
            mock_llm.available = True
            mock_vlm.return_value = mock_llm
            mock_llm.generate_json_with_images = lambda *a, **k: (fake_vision, "llm-vision")

            r = client.post(
                "/api/media/upload",
                headers=h,
                files={"file": ("tiny.mp4", io.BytesIO(tiny_video_bytes), "video/mp4")},
                data={"analyze": "true"},
            )
            assert r.status_code == 201
            aid = r.json()["asset"]["id"]
            # TestClient runs background tasks synchronously before returning
            detail = client.get(f"/api/media/assets/{aid}", headers=h).json()

        assert detail["status"] in {"ready", "processing"}
        # after sync background task completes:
        assert detail["status"] == "ready"
        assert detail["has_dna"] is True
        assert detail["duration_seconds"] is not None
        dna = detail["dna"]
        assert dna["scene_description"] == "test pattern with color bars"
        assert dna["visual_tags"] == ["test pattern", "color bars"]
        # reviewer scores must be NULL (not evaluated) until Phase 3
        assert dna["hook_score"] is None
        assert dna["clarity_score"] is None
        assert dna["brand_alignment"] is None

        # job recorded step-level outcomes
        jobs = detail["jobs"]
        assert jobs[0]["status"] == "completed"
        steps = jobs[0]["steps"]
        assert steps["ffmpeg_probe"]["status"] == "ok"
        assert steps["keyframes"]["status"] == "ok"
        assert steps["vision"]["status"] == "ok"
        # whisper provider=none -> transcribe skipped/degraded, not crash
        assert steps["transcribe"]["status"] in {"skipped", "failed", "degraded"}
        assert steps["dna"]["status"] == "ok"

    def test_create_content_from_dna(self, client, tiny_video_bytes):
        h = _register_and_login(client)
        fake_vision = LLMImageAnalysis(scene_description="scene", ocr_text="Hi", visual_tags=["tag"])
        with patch("app.services.vision_service.get_llm_service") as mock_vlm:
            mock_llm = type("M", (), {})()
            mock_llm.available = True
            mock_vlm.return_value = mock_llm
            mock_llm.generate_json_with_images = lambda *a, **k: (fake_vision, "llm-vision")

            r = client.post(
                "/api/media/upload",
                headers=h,
                files={"file": ("tiny.mp4", io.BytesIO(tiny_video_bytes), "video/mp4")},
                data={"analyze": "true"},
            )
            aid = r.json()["asset"]["id"]

        rc = client.post(
            f"/api/media/assets/{aid}/content",
            headers=h,
            json={"title": "My Video Post", "platform": "YouTube", "topic": "Testing"},
        )
        assert rc.status_code == 201
        content = rc.json()
        assert content["title"] == "My Video Post"
        # asset now linked
        detail = client.get(f"/api/media/assets/{aid}", headers=h).json()
        assert detail["content_id"] == content["id"]


class TestJobRecovery:
    def test_stale_jobs_marked_failed_on_startup(self, client):
        h = _register_and_login(client)
        r = client.post("/api/media/upload", headers=h, files=_image_upload(), data={"analyze": "false"})
        aid = r.json()["asset"]["id"]
        # simulate a crash: force job/asset into processing
        with session_scope() as db:
            job = db.query(MediaJob).first()
            job.status = "processing"
            asset = db.get(__import__("app.models", fromlist=["MediaAsset"]).MediaAsset, aid)
            asset.status = "processing"
        # re-enter lifespan (startup) via a new TestClient
        with TestClient(app) as c2:
            pass  # lifespan ran recover_stale_jobs
        with session_scope() as db:
            job = db.query(MediaJob).first()
            assert job.status == "failed"
            assert "restart" in job.error
            steps = job.steps or {}
            assert steps.get("recovery", {}).get("status") == "failed"
