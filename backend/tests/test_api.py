"""API contract tests: health, chat, demo, error handling."""


def test_health_returns_200(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "memory" in payload
    assert "llm" in payload
    assert "database" in payload


def test_chat_on_empty_db(client, auth_headers):
    before = client.post(
        "/api/chat",
        headers=auth_headers,
        json={"message": "What should I post next week?"},
    ).json()
    assert before["memory_count"] == 0
    assert before["confidence"] == "low"
    assert "add your past content" in before["answer"].lower()


def test_chat_requires_auth(client):
    r = client.post("/api/chat", json={"message": "What should I post next week?"})
    assert r.status_code == 401


def test_chat_with_memory(seeded_client):
    after = seeded_client.post("/api/chat", json={"message": "What should I post next week?"}).json()
    assert after["memory_count"] > 0
    assert after["confidence"] in {"medium", "high"}
    assert len(after["memories_used"]) > 0


def test_chat_suggestions(client):
    r = client.get("/api/chat/suggestions")
    assert r.status_code == 200
    assert len(r.json()["suggestions"]) > 0


def test_demo_compare(seeded_client):
    r = seeded_client.post("/api/demo/compare")
    assert r.status_code == 200
    payload = r.json()
    assert payload["without_memory"]["memories_used"] == []
    assert len(payload["with_memory"]["memories_used"]) > 0

def test_demo_publish_plan(seeded_client):
    r = seeded_client.post(
        "/api/demo/publish-plan", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["content_created"] > 0
    assert payload["insights_created"] > 0


def test_demo_reset_clears_everything(seeded_client):
    r = seeded_client.post("/api/demo/reset")
    assert r.status_code == 200
    assert seeded_client.get("/api/analytics").json()["content_count"] == 0


def test_recall_endpoint(seeded_client):
    r = seeded_client.get("/api/memory/recall", params={"query": "what works best", "limit": 5})
    assert r.status_code == 200


def test_strategy_context_endpoint(seeded_client):
    r = seeded_client.get("/api/memory/context")
    assert r.status_code == 200
    assert r.json()["summary"]["content_items"] == 72


def test_analytics_endpoint(seeded_client):
    r = seeded_client.get("/api/analytics")
    assert r.status_code == 200
    assert r.json()["content_count"] == 72


def test_secret_key_default_is_flagged():
    from dataclasses import replace

    from app.config import DEFAULT_SECRET_KEY, get_settings

    settings = get_settings()
    assert replace(settings, secret_key=DEFAULT_SECRET_KEY).secret_key_is_default is True
    assert replace(settings, secret_key="").secret_key_is_default is True
    assert replace(settings, secret_key="a" * 64).secret_key_is_default is False
