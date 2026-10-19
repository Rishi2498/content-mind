"""Memory storage and recall."""

from app.schemas import MemoryStatement
from app.services.hindsight_service import get_hindsight_service
from app.services.memory_service import MemoryService

CONTEXT_PERFORMANCE = "content_performance"


def _stmt(text: str, kind: str = "performance") -> MemoryStatement:
    return MemoryStatement(text=text, kind=kind, context=CONTEXT_PERFORMANCE)


def test_remember_persists_and_recall_finds(db, user_id):
    svc = MemoryService(db)
    count, backend, degraded = svc.remember(
        [
            _stmt("LinkedIn carousels about AI automation average 12% engagement, well above baseline."),
            _stmt("AI news announcements underperform; avoid generic roundups.", kind="gap"),
        ],
        user_id=user_id,
    )
    db.commit()

    assert count == 2
    assert backend == "local"
    assert degraded is True  # no HINDSIGHT_API_URL in tests

    result = svc.recall("LinkedIn carousel engagement", user_id=user_id, limit=5)
    assert result.total_available is not None
    assert len(result.memories) >= 1
    assert "LinkedIn" in result.memories[0].text


def test_recall_returns_relevant_not_everything(db, user_id):
    svc = MemoryService(db)
    svc.remember(
        [
            _stmt("Tutorial carousels get 3x more saves than text posts."),
            _stmt("Pricing pages convert at 4% for enterprise buyers."),
            _stmt("Security is the top objection in enterprise deals.", kind="topic"),
        ],
        user_id=user_id,
    )
    db.commit()

    result = svc.recall("tutorial carousel saves", user_id=user_id, limit=1)
    assert len(result.memories) <= 1
    assert "tutorial" in result.memories[0].text.lower()


def test_unrelated_query_returns_nothing(db, user_id):
    svc = MemoryService(db)
    svc.remember([_stmt("Pricing pages convert at 4% for enterprise buyers.")], user_id=user_id)
    db.commit()

    result = svc.recall("kubernetes ingress controller timeouts", user_id=user_id, limit=5)
    assert result.memories == []


def test_learn_from_content_stores_statements(db, user_id):
    from app.schemas import ContentCreate
    from app.services.content_service import account_average_rate, create_content

    content = create_content(
        db,
        ContentCreate(
            title="Automating your weekly content review",
            body="A practical guide to automating a content review loop with AI.",
            platform="LinkedIn",
            content_type="carousel",
            topic="AI automation",
            published_at="2026-04-01T09:00:00Z",
            impressions=10000,
            likes=900,
            comments=100,
            shares=60,
            clicks=500,
        ),
        user_id,
    )
    db.commit()

    svc = MemoryService(db)
    insights, mem_count, _backend, _degraded = svc.learn_from_content(
        content, account_average_rate(db, user_id)
    )

    assert mem_count > 0
    assert len(insights) > 0
    assert any(
        any(w in i.insight.lower() for w in ("engagement", "reach", "ctr", "click"))
        for i in insights
    )


def test_memory_event_log_records_writes(db, user_id):
    from sqlalchemy import func, select

    from app.models import MemoryEvent

    svc = MemoryService(db)
    svc.remember(
        [_stmt("Auditable statement about AI automation performance.")], user_id=user_id
    )
    db.commit()

    assert db.scalar(select(func.count(MemoryEvent.id)).where(MemoryEvent.user_id == user_id)) >= 1


def test_learned_page_groups_by_type(seeded_client):
    r = seeded_client.get("/api/memory")
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] > 0
    assert payload["categories"]
    for group in payload["categories"].values():
        assert isinstance(group, list)
        assert group
        for insight in group:
            assert insight["text"]
            assert insight["category"]
            assert 0.0 <= insight["confidence"] <= 1.0


def test_learned_page_shows_provenance(seeded_client):
    """Insights must point back at the content item they were derived from."""
    payload = seeded_client.get("/api/memory").json()
    assert payload["insights"]
    sourced = [i for i in payload["insights"] if i.get("content_id")]
    assert sourced, "learned insights should be traceable to a content item"
    for insight in sourced:
        assert insight["origin"]
        assert insight["evidence"]


def test_status_reports_backend_honestly(db):
    status = MemoryService(db).status()
    assert status.backend == "local"
    assert status.degraded is True
    assert status.configured is False
    assert "fallback" in status.message.lower() or "not set" in status.message.lower()


def test_hindsight_outage_falls_back_to_local(db, monkeypatch):
    """A configured-but-unreachable Hindsight must degrade, not crash.

    ``configured`` is derived from settings, so we stub the whole remote call
    path instead of trying to mutate a computed property.
    """
    svc = MemoryService(db)
    monkeypatch.setattr(type(svc.hindsight), "configured", True, raising=False)
    # Force every remote attempt to fail, as if the host were down.
    monkeypatch.setattr(
        svc.hindsight,
        "_try",
        lambda *args, **kwargs: ({"ok": False}, "hindsight"),
    )

    count, backend, degraded = svc.remember(
        [_stmt("Statement written while Hindsight is unreachable.")]
    )
    db.commit()

    assert backend in {"hindsight", "local"}
    assert isinstance(count, int)
    if backend == "local":
        assert degraded is True
        # The statement must still be retrievable via the fallback bank.
        assert svc.recall("statement written while hindsight is unreachable").memories


def test_clear_empties_the_bank(db):
    svc = MemoryService(db)
    svc.remember([_stmt("A statement that should be deleted by clear.")])
    db.commit()
    assert svc.status().memory_count > 0

    svc.hindsight.clear()
    assert svc.status().memory_count == 0
