"""Tests for Phase 5 — Content Strategy Agent.

Covers: strategy profile CRUD + validation, deterministic generation on empty
and populated data (hypothesis vs evidence distinction), recommendation
lifecycle edits, feedback with explicit preference persistence, experiment
tracking, lessons, memory degradation, tenant isolation, and auth. No
network calls; memory uses the local fallback bank.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models import Content, PublishedPost, StrategyRecommendation, User
from app.schemas import MetricSnapshotInput, PublishedPostCreate
from app.services import insight_service, performance_service, strategy_agent_service


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------
def _tester_user(db) -> User:
    """The user created by the auth_headers fixture (NOT the user_id fixture)."""
    user = db.query(User).filter(User.email == "tester@example.com").one()
    return user


def _put_profile(client: TestClient, **overrides) -> dict:
    payload = {
        "niche": "AI automation for small teams",
        "topics": ["AI automation", "no-code"],
        "target_audience": "Ops leads at 10-50 person companies",
        "audience_needs": "Cut manual reporting time",
        "goals": ["education", "awareness"],
        "content_pillars": ["Tutorials", "Case studies"],
        "avoid_topics": ["Crypto"],
        "publishing_frequency": "3/week",
        "constraints": "No competitor mentions",
    }
    payload.update(overrides)
    r = client.put("/api/strategy/profile", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _seed_posts_with_metrics(db, user_id: int, topic: str, n: int, *, likes: int, views: int) -> None:
    """Insert n published posts with one snapshot each, linked to Content rows."""
    for i in range(n):
        content = Content(
            user_id=user_id,
            title=f"{topic} post {i}",
            body=f"Body about {topic}",
            platform="LinkedIn",
            content_type="carousel",
            topic=topic,
            published_at=datetime(2026, 6, 1 + i, 9, 0, tzinfo=timezone.utc),
        )
        db.add(content)
        db.flush()
        post = performance_service.register_post(
            db,
            user_id,
            PublishedPostCreate(
                platform="LinkedIn",
                title=f"{topic} post {i}",
                published_at=datetime(2026, 6, 1 + i, 9, 0, tzinfo=timezone.utc),
                content_id=content.id,
            ),
        )
        performance_service.add_snapshot(
            db,
            user_id,
            post.id,
            MetricSnapshotInput(
                views=views,
                likes=likes,
                comments=2,
                shares=1,
            ),
        )
    db.commit()


# ----------------------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------------------
class TestProfile:
    def test_get_profile_empty_defaults(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.get("/api/strategy/profile")
        assert r.status_code == 200
        body = r.json()
        assert body["niche"] == ""
        assert body["goals"] == []
        assert body["feedback_preferences"] == []

    def test_put_creates_and_get_returns(self, client, auth_headers):
        client.headers.update(auth_headers)
        created = _put_profile(client)
        assert created["niche"] == "AI automation for small teams"
        assert created["goals"] == ["education", "awareness"]
        r = client.get("/api/strategy/profile")
        assert r.json()["topics"] == ["AI automation", "no-code"]

    def test_put_updates_in_place(self, client, auth_headers, db):
        client.headers.update(auth_headers)
        first = _put_profile(client)
        second = _put_profile(client, niche="Dev tools")
        assert second["id"] == first["id"]
        assert second["niche"] == "Dev tools"
        user = _tester_user(db)
        assert db.query(StrategyRecommendation).filter(StrategyRecommendation.user_id == user.id).count() == 0

    def test_invalid_goal_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.put("/api/strategy/profile", json={"goals": ["virality"]})
        assert r.status_code == 422

    def test_requires_auth(self, client):
        r = client.get("/api/strategy/profile")
        assert r.status_code == 401


# ----------------------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------------------
class TestGeneration:
    def test_empty_state_generates_hypotheses_not_findings(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post("/api/strategy/generate", json={"period": "week"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["plan_id"] is not None
        assert body["recommendations"] == []
        assert "Not enough information" in body["summary"]
        assert any("hypotheses" in w.lower() or "no recorded post metrics" in w.lower() for w in body["warnings"])

    def test_profile_topics_become_hypotheses(self, client, auth_headers, db):
        client.headers.update(auth_headers)
        _put_profile(client)
        r = client.post("/api/strategy/generate", json={"period": "week", "posts_per_week": 4})
        body = r.json()
        topics = {rec["topic"] for rec in body["recommendations"]}
        assert "AI automation" in topics or "Tutorials" in topics
        assert "Crypto" not in topics  # avoid_topics respected

    def test_evidence_backed_when_metrics_exist(self, client, auth_headers, db):
        client.headers.update(auth_headers)
        user = _tester_user(db)
        _seed_posts_with_metrics(db, user.id, "AI automation", n=6, likes=200, views=1000)
        _seed_posts_with_metrics(db, user.id, "no-code", n=6, likes=5, views=1000)
        r = client.post("/api/strategy/generate", json={"period": "month", "posts_per_week": 6})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["evidence_sources"].get("performance") is True
        evidence_recs = [rec for rec in body["recommendations"] if not rec["is_hypothesis"]]
        assert evidence_recs, "expected at least one evidence-backed recommendation"
        for rec in evidence_recs:
            assert rec["sample_size"] and rec["sample_size"] >= 2
            assert rec["observation_period"] or rec["reason"]

    def test_generation_persists_and_is_listable(self, client, auth_headers, db):
        client.headers.update(auth_headers)
        _put_profile(client)
        r = client.post("/api/strategy/generate", json={"period": "week"})
        plan_id = r.json()["plan_id"]
        recs = client.get("/api/strategy/recommendations").json()
        assert recs["total"] >= 1
        assert all(item["plan_id"] == plan_id for item in recs["items"])

    def test_memory_failure_degrades_but_does_not_break(self, client, auth_headers, monkeypatch):
        client.headers.update(auth_headers)
        _put_profile(client)

        def _boom(*args, **kwargs):
            raise RuntimeError("memory down")

        monkeypatch.setattr(strategy_agent_service.MemoryService, "get_relevant_memories", _boom)
        monkeypatch.setattr(strategy_agent_service.MemoryService, "remember", _boom)
        r = client.post("/api/strategy/generate", json={"period": "week"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["memory_degraded"] is True
        assert body["recommendations"]


# ----------------------------------------------------------------------------------
# Recommendations lifecycle
# ----------------------------------------------------------------------------------
class TestRecommendations:
    def _generate(self, client) -> dict:
        _put_profile(client)
        r = client.post("/api/strategy/generate", json={"period": "week"})
        assert r.status_code == 200
        return r.json()

    def test_edit_title_marks_edited(self, client, auth_headers):
        client.headers.update(auth_headers)
        self._generate(client)
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]
        r = client.patch(
            f"/api/strategy/recommendations/{rec_id}",
            json={"edited_title": "My own title"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["edited_title"] == "My own title"
        assert body["status"] == "edited"
        assert body["working_title"] != "My own title"  # generation-time field preserved

    def test_status_filter(self, client, auth_headers):
        client.headers.update(auth_headers)
        self._generate(client)
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]
        client.post(
            f"/api/strategy/recommendations/{rec_id}/feedback",
            json={"status": "rejected", "note": "off-brand"},
        )
        rejected = client.get("/api/strategy/recommendations", params={"status": "rejected"}).json()
        assert rejected["total"] == 1
        proposed = client.get("/api/strategy/recommendations", params={"status": "proposed"}).json()
        assert all(i["id"] != rec_id for i in proposed["items"])

    def test_foreign_recommendation_404(self, client, auth_headers, db):
        from app.auth import get_password_hash

        client.headers.update(auth_headers)
        self._generate(client)
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]

        other = User(email="other@example.com", hashed_password=get_password_hash("secret123"))
        db.add(other)
        db.commit()
        db.refresh(other)
        from app.auth import create_access_token

        token = create_access_token({"sub": str(other.id)})
        r = client.patch(
            f"/api/strategy/recommendations/{rec_id}",
            json={"status": "accepted"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404

    def test_requires_auth(self, client):
        assert client.get("/api/strategy/recommendations").status_code == 401


# ----------------------------------------------------------------------------------
# Feedback
# ----------------------------------------------------------------------------------
class TestFeedback:
    def test_feedback_updates_status_and_note(self, client, auth_headers):
        client.headers.update(auth_headers)
        _put_profile(client)
        client.post("/api/strategy/generate", json={"period": "week"})
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]
        r = client.post(
            f"/api/strategy/recommendations/{rec_id}/feedback",
            json={"status": "accepted", "note": "fits our voice"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "accepted"
        assert body["feedback_note"] == "fits our voice"

    def test_single_rejection_does_not_become_preference(self, client, auth_headers, db):
        client.headers.update(auth_headers)
        _put_profile(client)
        client.post("/api/strategy/generate", json={"period": "week"})
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]
        client.post(
            f"/api/strategy/recommendations/{rec_id}/feedback",
            json={"status": "rejected", "note": "not today", "update_preferences": False},
        )
        profile = client.get("/api/strategy/profile").json()
        assert profile["feedback_preferences"] == []

    def test_explicit_preference_is_persisted(self, client, auth_headers):
        client.headers.update(auth_headers)
        _put_profile(client)
        client.post("/api/strategy/generate", json={"period": "week"})
        rec_id = client.get("/api/strategy/recommendations").json()["items"][0]["id"]
        client.post(
            f"/api/strategy/recommendations/{rec_id}/feedback",
            json={"status": "rejected", "note": "never post on weekends", "update_preferences": True},
        )
        profile = client.get("/api/strategy/profile").json()
        assert any("never post on weekends" in p for p in profile["feedback_preferences"])

    def test_feedback_unknown_id_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post(
            "/api/strategy/recommendations/999999/feedback",
            json={"status": "accepted"},
        )
        assert r.status_code == 404


# ----------------------------------------------------------------------------------
# Experiments
# ----------------------------------------------------------------------------------
class TestExperiments:
    def test_create_complete_flow(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post(
            "/api/strategy/experiments",
            json={
                "title": "Hook style A/B",
                "hypothesis": "Question hooks outperform statement hooks",
                "variation": "Question vs statement first line",
                "intended_metric": "engagement_rate_per_view",
            },
        )
        assert r.status_code == 201, r.text
        exp = r.json()
        assert exp["status"] == "planned"

        done = client.patch(
            f"/api/strategy/experiments/{exp['id']}",
            json={"status": "completed", "actual_result": "Question +12% engagement (single post)"},
        )
        assert done.status_code == 200
        body = done.json()
        assert body["status"] == "completed"
        assert body["completed_at"] is not None

    def test_list_scoped_to_user(self, client, auth_headers, db):
        from app.auth import create_access_token, get_password_hash

        client.headers.update(auth_headers)
        other = User(email="other2@example.com", hashed_password=get_password_hash("secret123"))
        db.add(other)
        db.commit()
        db.refresh(other)
        token = create_access_token({"sub": str(other.id)})
        r = client.get("/api/strategy/experiments", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == []

    def test_foreign_experiment_404(self, client, auth_headers, db):
        from app.auth import create_access_token, get_password_hash

        client.headers.update(auth_headers)
        exp_id = client.post("/api/strategy/experiments", json={"title": "Mine"}).json()["id"]
        other = User(email="other3@example.com", hashed_password=get_password_hash("secret123"))
        db.add(other)
        db.commit()
        db.refresh(other)
        token = create_access_token({"sub": str(other.id)})
        r = client.patch(
            f"/api/strategy/experiments/{exp_id}",
            json={"status": "running"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404


# ----------------------------------------------------------------------------------
# Lessons
# ----------------------------------------------------------------------------------
class TestLessons:
    def test_empty_state(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.get("/api/strategy/lessons")
        assert r.status_code == 200
        body = r.json()
        assert body["lessons"] == []
        assert "No lessons yet" in body["message"]

    def test_completed_experiment_appears_with_non_causal_framing(self, client, auth_headers):
        client.headers.update(auth_headers)
        exp = client.post(
            "/api/strategy/experiments",
            json={"title": "Carousel vs video", "hypothesis": "Carousels win", "intended_metric": "views"},
        ).json()
        client.patch(
            f"/api/strategy/experiments/{exp['id']}",
            json={"status": "completed", "actual_result": "Video won by 20%"},
        )
        r = client.get("/api/strategy/lessons")
        lessons = r.json()["lessons"]
        assert any("Video won by 20%" in l["text"] for l in lessons)
        assert any("not proof of causality" in l["text"] for l in lessons)
        assert all(l["source"] in ("memory", "experiment") for l in lessons)

    def test_requires_auth(self, client):
        assert client.get("/api/strategy/lessons").status_code == 401


# ----------------------------------------------------------------------------------
# Service-level units
# ----------------------------------------------------------------------------------
class TestServiceUnits:
    def test_gather_evidence_marks_missing_sources(self, db, user_id):
        ev = strategy_agent_service.gather_evidence(db, user_id)
        assert ev.sources["strategy_profile"] is False
        assert ev.sources["performance"] is True  # empty performance is still "available"
        assert ev.has_performance is False
        assert any("hypotheses" in w for w in ev.warnings)

    def test_gather_evidence_tenant_scoped(self, db, user_id):
        from app.schemas import StrategyProfileUpsert

        strategy_agent_service.upsert_profile(
            db, user_id, StrategyProfileUpsert(niche="Only mine", goals=["education"])
        )
        ev = strategy_agent_service.gather_evidence(db, user_id + 999)
        assert ev.profile is None

    def test_recommendation_cap(self, db, user_id):
        from app.schemas import StrategyGenerateRequest, StrategyProfileUpsert

        strategy_agent_service.upsert_profile(
            db,
            user_id,
            StrategyProfileUpsert(
                niche="AI",
                topics=[f"t{i}" for i in range(20)],
                content_pillars=[f"p{i}" for i in range(15)],
                goals=["education"],
            ),
        )
        ev = strategy_agent_service.gather_evidence(db, user_id)
        recs = strategy_agent_service.build_recommendations(
            db, user_id, ev, StrategyGenerateRequest(period="month", posts_per_week=21)
        )
        assert len(recs) <= strategy_agent_service.MAX_RECOMMENDATIONS

    def test_confidence_labels_used(self, db, user_id):
        assert insight_service.confidence_label(11) == "strong"
        assert insight_service.confidence_label(6) == "moderate"
        assert insight_service.confidence_label(3) == "weak"
        assert insight_service.confidence_label(1) == "insufficient"
