"""Gemini provider: factory, request shape, error mapping, fallback, vision.

Every test is fully mocked; no test makes a network call or consumes quota.
"""

from __future__ import annotations

import builtins
import json
import types as pytypes
from pathlib import Path

import pytest
from google.genai import types

from app.config import Settings
from app.schemas import LLMContentAnalysis, LLMImageAnalysis
from app.services import llm_service
from app.services.llm_service import (
    DisabledProvider,
    GeminiProvider,
    LLMService,
    OpenAICompatibleProvider,
)

GOOD_ANSWER = (
    '{"insights": [{"insight_type": "performance", '
    '"insight": "Carousels outperform text posts.", '
    '"confidence": 0.8, "evidence": "12% vs 4%"}], "memories": []}'
)
FALLBACK = {
    "insights": [
        {
            "insight_type": "performance",
            "insight": "Fallback insight.",
            "confidence": 0.5,
            "evidence": "heuristic",
        }
    ],
    "memories": [],
}


def _settings(**over):
    base = dict(
        gemini_api_key="test-gemini-key",
        llm_api_key="",
        llm_provider="gemini",
        llm_model="gemini-3.8-flash",
        llm_timeout=60.0,
        llm_temperature=0.3,
        llm_max_retries=1,
        llm_max_output_tokens=2048,
        llm_provider_key_present=True,
        gemini_configured=True,
        llm_configured=True,
        llm_base_url="https://api.openai.com/v1",
    )
    base.update(over)
    return pytypes.SimpleNamespace(**base)


class FakeResponse:
    def __init__(self, text: str) -> None:
        self.text = text


class FakeAPIError(Exception):
    """Mirrors ``google.genai.errors.APIError`` (which exposes ``.code``)."""

    def __init__(self, code: int) -> None:
        super().__init__(f"api error {code}")
        self.code = code


class FakeModels:
    def __init__(self, responses: list[FakeResponse] | None = None, error: Exception | None = None):
        self.responses = responses or []
        self.error = error
        self.calls: list[dict] = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


class FakeClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


def _provider(monkeypatch, *, responses=None, error=None, **settings_over):
    monkeypatch.setattr(llm_service, "get_settings", lambda: _settings(**settings_over))
    provider = GeminiProvider()
    provider._types = types
    models = FakeModels(responses=responses, error=error)
    provider._client = FakeClient(models)
    return provider, models


def _service(monkeypatch, provider, **settings_over) -> LLMService:
    monkeypatch.setattr(llm_service, "get_settings", lambda: _settings(**settings_over))
    svc = LLMService()
    svc._provider = provider
    return svc


# ---------------------------------------------------------------------------
# 1. Factory selection
# ---------------------------------------------------------------------------
def test_factory_selects_gemini_when_configured(monkeypatch):
    monkeypatch.setattr(llm_service, "get_settings", lambda: _settings())
    svc = LLMService()
    assert isinstance(svc.provider, GeminiProvider)
    assert svc.available is True


def test_factory_gemini_without_key_is_disabled(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "get_settings",
        lambda: _settings(
            gemini_api_key="", llm_provider_key_present=False, llm_configured=False
        ),
    )
    svc = LLMService()
    assert isinstance(svc.provider, DisabledProvider)
    assert svc.available is False


# ---------------------------------------------------------------------------
# 2. Request arguments and configured model
# ---------------------------------------------------------------------------
def test_request_uses_model_tokens_and_schema(monkeypatch):
    provider, models = _provider(
        monkeypatch, responses=[FakeResponse('{"ok": true}')]
    )
    out = provider.complete("system", "user", response_schema=LLMImageAnalysis)

    assert out == '{"ok": true}'
    call = models.calls[0]
    assert call["model"] == "gemini-3.8-flash"
    assert call["contents"] == "user"
    config = call["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema is LLMImageAnalysis
    assert config.max_output_tokens == 2048
    assert config.system_instruction == "system"


# ---------------------------------------------------------------------------
# 3. JSON parsing + Pydantic validation through the existing service
# ---------------------------------------------------------------------------
def test_generate_json_validates_model_output(monkeypatch):
    provider, _ = _provider(monkeypatch, responses=[FakeResponse(GOOD_ANSWER)])
    svc = _service(monkeypatch, provider)

    result, note = svc.generate_json(LLMContentAnalysis, system="s", user="u")

    assert note == "llm"
    assert result is not None
    assert result.insights[0].insight.startswith("Carousels outperform")


# ---------------------------------------------------------------------------
# 4. Missing key / missing SDK
# ---------------------------------------------------------------------------
def test_missing_sdk_marks_unavailable(monkeypatch):
    monkeypatch.setattr(llm_service, "get_settings", lambda: _settings())
    provider = GeminiProvider()
    provider._genai = None
    provider._types = None

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "google" or name.startswith("google."):
            raise ImportError("simulated missing SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    assert provider.is_available() is False
    with pytest.raises(RuntimeError, match="not installed"):
        provider._ensure_client()


def test_missing_key_is_unavailable(monkeypatch):
    monkeypatch.setattr(llm_service, "get_settings", lambda: _settings(gemini_api_key=""))
    provider = GeminiProvider()
    assert provider.is_available() is False


# ---------------------------------------------------------------------------
# 5. 429 / quota and 5xx mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code,needle",
    [(429, "rate limit"), (500, "server error"), (503, "server error")],
)
def test_quota_and_server_errors_are_mapped(monkeypatch, code, needle):
    provider, _ = _provider(monkeypatch, error=FakeAPIError(code))
    with pytest.raises(RuntimeError) as excinfo:
        provider.complete("s", "u")

    message = str(excinfo.value)
    assert needle in message
    assert "test-gemini-key" not in message


# ---------------------------------------------------------------------------
# 6. Timeout and malformed response
# ---------------------------------------------------------------------------
def test_timeout_is_mapped(monkeypatch):
    provider, _ = _provider(monkeypatch, error=TimeoutError("slow"))
    with pytest.raises(RuntimeError, match="timed out"):
        provider.complete("s", "u")


def test_empty_response_is_an_error(monkeypatch):
    provider, _ = _provider(monkeypatch, responses=[FakeResponse("   ")])
    with pytest.raises(RuntimeError, match="empty response"):
        provider.complete("s", "u")


# ---------------------------------------------------------------------------
# 7. Bounded corrective retry and fallback
# ---------------------------------------------------------------------------
def test_corrective_retry_recovers(monkeypatch):
    provider, models = _provider(
        monkeypatch,
        responses=[FakeResponse("garbage"), FakeResponse(GOOD_ANSWER)],
    )
    svc = _service(monkeypatch, provider)

    result, note = svc.generate_json(LLMContentAnalysis, system="s", user="u")

    assert note == "llm-retry"
    assert len(models.calls) == 2
    assert "previous answer was rejected" in models.calls[1]["contents"]
    assert result is not None
    assert result.insights[0].insight.startswith("Carousels outperform")


def test_malformed_output_retries_then_falls_back(monkeypatch):
    provider, models = _provider(
        monkeypatch,
        responses=[FakeResponse("not json"), FakeResponse("still not json")],
    )
    svc = _service(monkeypatch, provider)

    result, note = svc.generate_json(
        LLMContentAnalysis, system="s", user="u", fallback=lambda: dict(FALLBACK)
    )

    assert note.startswith("fallback")
    assert len(models.calls) == 2  # initial + one bounded corrective retry
    assert result is not None
    assert result.insights[0].insight == "Fallback insight."


def test_quota_error_triggers_deterministic_fallback(monkeypatch):
    provider, models = _provider(monkeypatch, error=FakeAPIError(429))
    svc = _service(monkeypatch, provider)

    result, note = svc.generate_json(
        LLMContentAnalysis, system="s", user="u", fallback=lambda: dict(FALLBACK)
    )

    assert note.startswith("fallback")
    assert "429" in (svc.last_error or "")
    assert len(models.calls) == 2
    assert result is not None
    assert result.insights[0].insight == "Fallback insight."


# ---------------------------------------------------------------------------
# 8. Image input conversion
# ---------------------------------------------------------------------------
def test_vision_sends_inline_image_parts(monkeypatch, tmp_path: Path):
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    provider, models = _provider(
        monkeypatch, responses=[FakeResponse('{"scene_description": "a desk"}')]
    )

    out = provider.complete_vision("s", "u", [image], response_schema=LLMImageAnalysis)

    assert out == '{"scene_description": "a desk"}'
    parts = models.calls[0]["contents"]
    assert parts[0].text == "u"
    assert parts[1].inline_data.mime_type == "image/png"
    assert parts[1].inline_data.data == image.read_bytes()
    assert models.calls[0]["config"].response_schema is LLMImageAnalysis


# ---------------------------------------------------------------------------
# 9. Provider-aware status + secret-safe diagnostics
# ---------------------------------------------------------------------------
def test_settings_are_provider_aware_and_secret_safe(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-gemini")
    monkeypatch.setenv("LLM_API_KEY", "")

    settings = Settings()

    assert settings.llm_provider_key_present is True
    assert settings.llm_configured is True
    blob = json.dumps(settings.safe_dict())
    assert "super-secret-gemini" not in blob
    assert settings.safe_dict()["llm"]["gemini_key_present"] is True


def test_openai_provider_still_uses_llm_api_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "super-secret-openai")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    settings = Settings()

    assert settings.llm_provider_key_present is True
    assert settings.llm_configured is True
    assert "super-secret-openai" not in json.dumps(settings.safe_dict())


def test_describe_exposes_only_booleans(monkeypatch):
    provider, _ = _provider(monkeypatch, responses=[FakeResponse("{}")])
    svc = _service(monkeypatch, provider)

    described = svc.describe()

    assert described["api_key_present"] is True
    assert described["gemini_key_present"] is True
    assert "test-gemini-key" not in json.dumps(described)


# ---------------------------------------------------------------------------
# 10. Regression: OpenAI-compatible + heuristic providers
# ---------------------------------------------------------------------------
def test_openai_provider_accepts_response_schema_kwarg(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "get_settings",
        lambda: _settings(
            llm_provider="openai",
            llm_api_key="openai-key",
            gemini_api_key="",
            llm_provider_key_present=True,
            llm_configured=True,
        ),
    )
    provider = OpenAICompatibleProvider()
    captured: dict = {}

    class FakeHttpResponse:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "{}"}}]}

    def fake_post(url, json=None, headers=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return FakeHttpResponse()

    provider._client = pytypes.SimpleNamespace(post=fake_post, close=lambda: None)

    out = provider.complete("s", "u", response_schema=LLMImageAnalysis)

    assert out == "{}"
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"].startswith("Bearer ")


def test_heuristic_provider_still_works_without_keys(monkeypatch):
    monkeypatch.setattr(
        llm_service,
        "get_settings",
        lambda: _settings(
            llm_provider="heuristic",
            gemini_api_key="",
            llm_api_key="",
            llm_provider_key_present=False,
            llm_configured=False,
        ),
    )
    svc = LLMService()
    assert isinstance(svc.provider, DisabledProvider)
    assert svc.available is False
