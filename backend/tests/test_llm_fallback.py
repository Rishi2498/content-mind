"""LLM provider isolation and JSON validation fallback."""

from app.schemas import LLMContentAnalysis
from app.services.llm_service import get_llm_service

GOOD_ANSWER = (
    '{"insights": [{"insight_type": "performance", '
    '"insight": "Carousels outperform text posts on LinkedIn.", '
    '"confidence": 0.8, "evidence": "12% vs 4%"}], "memories": []}'
)

FALLBACK = {
    "insights": [
        {
            "insight_type": "performance",
            "insight": "Fallback insight: reporting automation works well.",
            "confidence": 0.5,
            "evidence": "heuristic",
        }
    ],
    "memories": [],
}


class _FakeProvider:
    """A provider that always answers, so the retry/fallback paths are testable."""

    name = "fake-openai-compatible"
    model = "fake-model"

    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def complete(self, system: str, user: str, temperature: float | None = None, **kwargs) -> str:
        self.calls += 1
        index = min(self.calls - 1, len(self._responses) - 1)
        return self._responses[index]


def _install(monkeypatch, responses: list[str]) -> _FakeProvider:
    provider = _FakeProvider(responses)
    monkeypatch.setattr(get_llm_service(), "_provider", provider)
    return provider


def _analyze(fallback=None):
    return get_llm_service().generate_json(
        LLMContentAnalysis,
        system="Analyse the content.",
        user="Analyse: automate your reporting pipeline",
        fallback=lambda: dict(fallback or FALLBACK),
    )


def test_no_api_key_means_unavailable_and_fallback():
    svc = get_llm_service()
    assert svc.available is False
    assert svc.describe()["available"] is False


def test_valid_llm_json_is_used(monkeypatch):
    provider = _install(monkeypatch, [GOOD_ANSWER])
    result, note = _analyze()

    assert note == "llm"
    assert result.insights[0].insight.startswith("Carousels outperform")
    assert provider.calls == 1


def test_unparseable_llm_output_falls_back(monkeypatch):
    _install(monkeypatch, ["this is not json at all {{{"])
    result, note = _analyze()

    assert result is not None
    assert note.startswith("fallback")
    assert result.insights[0].insight.startswith("Fallback insight")


def test_schema_invalid_llm_output_retries_then_falls_back(monkeypatch):
    provider = _install(monkeypatch, ['{"insights": "not-a-list", "memories": 7}'])
    result, note = _analyze()

    assert result is not None
    assert note.startswith("fallback")
    assert provider.calls > 1  # retries were attempted before giving up


def test_retry_recovers_from_a_bad_first_answer(monkeypatch):
    provider = _install(monkeypatch, ["garbage", GOOD_ANSWER])
    result, note = _analyze()

    assert result.insights[0].insight.startswith("Carousels outperform")
    assert note == "llm-retry"
    assert provider.calls == 2


def test_provider_error_is_treated_as_fallback(monkeypatch):
    class _Boom:
        name = "boom"
        model = "boom"

        def is_available(self) -> bool:
            return True

        def complete(self, *a, **kw):
            raise RuntimeError("upstream 503")

    monkeypatch.setattr(get_llm_service(), "_provider", _Boom())
    result, note = _analyze()

    assert result is not None
    assert note.startswith("fallback")
    assert "503" in (get_llm_service().last_error or "")


def test_fallback_is_used_when_no_provider(monkeypatch):
    """The default (no API key) path must still produce a usable object."""
    monkeypatch.setattr(get_llm_service(), "_provider", None)
    result, note = _analyze()

    assert result is not None
    assert note.startswith("fallback")
    assert result.insights


def test_generate_plan_endpoint_returns_valid_plan(seeded_client):
    r = seeded_client.post(
        "/api/plans/generate", json={"days": 3, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    )
    assert r.status_code == 200
    plan = r.json()["plan"]
    assert len(plan["items"]) == 3
    for item in plan["items"]:
        assert item["title"]
        assert item["platform"]
        assert item["date"]
