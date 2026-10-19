"""Tests for transcription and vision services (Phase 2, Step 3).

All AI calls are mocked — no network, no paid API usage, no local model
downloads. These tests verify provider selection, graceful degradation, and
the merge logic.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("HINDSIGHT_ALLOW_LOCAL_FALLBACK", "1")
os.environ.pop("LLM_API_KEY", None)

from app.config import get_settings
from app.schemas import LLMImageAnalysis
from app.services import transcription_service, vision_service
from app.services.transcription_service import TranscriptionResult


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("WHISPER_PROVIDER", "auto")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestTranscribeSelection:
    def test_no_audio_degrades(self):
        res = transcription_service.transcribe(None)
        assert res.degraded and res.note == "no-audio"

    def test_missing_file_degrades(self, tmp_path):
        res = transcription_service.transcribe(tmp_path / "nope.wav")
        assert res.degraded

    def test_policy_none_skips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHISPER_PROVIDER", "none")
        get_settings.cache_clear()
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"RIFF")
        res = transcription_service.transcribe(wav)
        assert res.degraded and res.note == "transcription-disabled"

    def test_auto_without_key_and_no_local_degrades(self, tmp_path):
        # No LLM_API_KEY -> API unavailable; faster-whisper not installed -> local unavailable
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"RIFF")
        res = transcription_service.transcribe(wav)
        assert res.degraded
        assert res.provider == "none"
        assert res.note in {"faster-whisper-not-installed", "whisper-api-unavailable", "local-whisper-failed"}

    def test_forced_api_without_key_degrades(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHISPER_PROVIDER", "api")
        get_settings.cache_clear()
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"RIFF")
        res = transcription_service.transcribe(wav)
        assert res.degraded and res.provider == "none"

    def test_api_success_mocked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHISPER_PROVIDER", "api")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        get_settings.cache_clear()
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"RIFF....")

        mock_llm = MagicMock()
        mock_llm.available = True
        with (
            patch.object(transcription_service, "get_llm_service", return_value=mock_llm),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = MagicMock(
                status_code=200, json=lambda: {"text": " hello world ", "language": "en"}
            )
            res = transcription_service.transcribe(wav)

        assert res.provider == "api"
        assert res.transcript == "hello world"
        assert res.language == "en"
        assert not res.degraded

    def test_api_error_falls_back_to_local(self, tmp_path, monkeypatch):
        monkeypatch.setenv("WHISPER_PROVIDER", "auto")
        monkeypatch.setenv("LLM_API_KEY", "test-key")
        get_settings.cache_clear()
        wav = tmp_path / "a.wav"
        wav.write_bytes(b"RIFF....")

        mock_llm = MagicMock()
        mock_llm.available = True
        with (
            patch.object(transcription_service, "get_llm_service", return_value=mock_llm),
            patch("httpx.Client") as mock_client_cls,
        ):
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = MagicMock(status_code=500, text="boom")
            with patch.object(
                transcription_service,
                "_transcribe_local",
                return_value=TranscriptionResult(
                    transcript="local text", language="en", provider="local", note="local-whisper"
                ),
            ):
                res = transcription_service.transcribe(wav)

        assert res.provider == "local"
        assert res.transcript == "local text"
        assert not res.degraded


class TestVision:
    def test_missing_keyframe_degrades(self, tmp_path):
        res = vision_service.analyze_keyframes([tmp_path / "no.jpg"])
        assert res.degraded

    def test_no_keyframes_degrades(self):
        res = vision_service.analyze_keyframes([])
        assert res.degraded and res.note == "no-keyframes"

    def test_unavailable_llm_degrades(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        get_settings.cache_clear()
        jpg = tmp_path / "kf.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")
        res = vision_service.analyze_keyframes([jpg])
        assert res.degraded
        assert res.note == "vision-llm-unavailable"

    def test_successful_analysis_mocked(self, tmp_path):
        jpg = tmp_path / "kf.jpg"
        jpg.write_bytes(b"\xff\xd8\xff")
        expected = LLMImageAnalysis(
            scene_description="a person at a whiteboard",
            ocr_text="Q3 Goals",
            visual_tags=["person", "whiteboard", "office"],
            dominant_colors=["white", "blue"],
            text_heavy=True,
        )
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.generate_json_with_images.return_value = (expected, "llm-vision")
        with patch.object(vision_service, "get_llm_service", return_value=mock_llm):
            res = vision_service.analyze_keyframes([jpg])
        assert not res.degraded
        assert len(res.analyses) == 1
        assert res.analyses[0].ocr_text == "Q3 Goals"

    def test_partial_failure_marks_degraded(self, tmp_path):
        good = tmp_path / "a.jpg"
        good.write_bytes(b"\xff\xd8\xff")
        missing = tmp_path / "missing.jpg"
        expected = LLMImageAnalysis(scene_description="ok", ocr_text="", visual_tags=["x"])
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.generate_json_with_images.return_value = (expected, "llm-vision")
        with patch.object(vision_service, "get_llm_service", return_value=mock_llm):
            res = vision_service.analyze_keyframes([good, missing])
        assert res.degraded
        assert res.failed_frames == 1
        assert len(res.analyses) == 1


class TestMergeAnalyses:
    def test_merge_empty(self):
        merged = vision_service.merge_analyses([])
        assert merged["scene_description"] == ""
        assert merged["visual_tags"] == []

    def test_merge_dedupes_tags_and_joins_text(self):
        a1 = LLMImageAnalysis(
            scene_description="desk", ocr_text="Line1", visual_tags=["desk", "lamp"], dominant_colors=["brown"]
        )
        a2 = LLMImageAnalysis(
            scene_description="closeup", ocr_text="Line2", visual_tags=["desk", "pen"], dominant_colors=["brown", "blue"]
        )
        merged = vision_service.merge_analyses([a1, a2])
        assert merged["scene_description"] == "desk / closeup"
        assert merged["ocr_text"] == "Line1\nLine2"
        assert merged["visual_tags"] == ["desk", "lamp", "pen"]
        assert merged["dominant_colors"] == ["brown", "blue"]
