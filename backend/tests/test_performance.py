"""Tests for Phase 4 — performance intelligence.

Covers: model/input validation, manual post registration, append-only
snapshot history, aggregation rate denominators, missing-vs-zero semantics,
date filters, pagination, tenant isolation, auth, empty datasets, and
insufficient-sample insight behaviour. No network calls; no LLM required.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.models import Content, ContentReview, PublishedPost, User
from app.services import insight_service, performance_service


# ----------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------
def _register(
    client: TestClient,
    *,
    platform: str = "LinkedIn",
    title: str = "Launch post",
    published_at: str = "2026-06-01T09:00:00Z",
    url: str = "https://example.com/post/1",
    external_id: str = "ext-1",
    content_id: int | None = None,
    snapshot: dict | None = None,
) -> dict:
    payload: dict = {
        "platform": platform,
        "title": title,
        "published_at": published_at,
        "url": url,
        "external_id": external_id,
    }
    if content_id is not None:
        payload["content_id"] = content_id
    if snapshot is not None:
        payload["initial_snapshot"] = snapshot
    r = client.post("/api/performance/posts", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _snapshot(client: TestClient, post_id: int, **fields) -> dict:
    r = client.post(f"/api/performance/posts/{post_id}/snapshots", json=fields)
    assert r.status_code == 201, r.text
    return r.json()


# ----------------------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------------------
class TestValidation:
    def test_negative_views_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        r = client.post(
            f"/api/performance/posts/{post['id']}/snapshots", json={"views": -5}
        )
        assert r.status_code == 422

    def test_retention_above_100_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        r = client.post(
            f"/api/performance/posts/{post['id']}/snapshots",
            json={"audience_retention_pct": 150},
        )
        assert r.status_code == 422

    def test_ctr_above_100_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        r = client.post(
            f"/api/performance/posts/{post['id']}/snapshots", json={"ctr_pct": 101}
        )
        assert r.status_code == 422

    def test_missing_platform_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post(
            "/api/performance/posts",
            json={"published_at": "2026-06-01T09:00:00Z"},
        )
        assert r.status_code == 422

    def test_non_http_url_stored_empty(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client, url="javascript:alert(1)")
        assert post["url"] == ""

    def test_invalid_published_at_rejected(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post(
            "/api/performance/posts",
            json={"platform": "X", "published_at": "not-a-date"},
        )
        assert r.status_code == 422


# ----------------------------------------------------------------------------------
# Posts + snapshots
# ----------------------------------------------------------------------------------
class TestPostsAndSnapshots:
    def test_register_and_list(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, title="One")
        _register(client, title="Two", platform="YouTube")
        r = client.get("/api/performance/posts")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    def test_platform_filter(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, platform="LinkedIn")
        _register(client, platform="YouTube")
        r = client.get("/api/performance/posts", params={"platform": "YouTube"})
        assert r.json()["total"] == 1

    def test_pagination(self, client, auth_headers):
        client.headers.update(auth_headers)
        for i in range(5):
            _register(client, title=f"Post {i}")
        page1 = client.get("/api/performance/posts", params={"limit": 2, "offset": 0}).json()
        page2 = client.get("/api/performance/posts", params={"limit": 2, "offset": 2}).json()
        assert page1["total"] == 5
        assert len(page1["items"]) == 2
        assert len(page2["items"]) == 2
        assert page1["items"][0]["id"] != page2["items"][0]["id"]

    def test_multiple_snapshots_preserve_history(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        pid = post["id"]
        _snapshot(client, pid, views=100, likes=10, recorded_at="2026-06-02T10:00:00Z")
        _snapshot(client, pid, views=250, likes=30, recorded_at="2026-06-09T10:00:00Z")
        detail = client.get(f"/api/performance/posts/{pid}").json()
        assert detail["snapshot_count"] == 2
        views_seen = [s["views"] for s in detail["snapshots"]]
        assert views_seen == [100, 250]  # both preserved, chronological

    def test_latest_snapshot_is_most_recent(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        pid = post["id"]
        _snapshot(client, pid, views=100, recorded_at="2026-06-09T10:00:00Z")
        _snapshot(client, pid, views=50, recorded_at="2026-06-02T10:00:00Z")  # backdated
        detail = client.get(f"/api/performance/posts/{pid}").json()
        assert detail["latest_snapshot"]["views"] == 100

    def test_initial_snapshot_on_register(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client, snapshot={"views": 42, "likes": 7})
        assert post["snapshot_count"] == 1
        assert post["latest_snapshot"]["views"] == 42

    def test_days_since_published_computed(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client, published_at="2026-06-01T09:00:00Z")
        snap = _snapshot(client, post["id"], views=1, recorded_at="2026-06-08T09:00:00Z")
        assert snap["days_since_published"] == 7

    def test_update_and_delete(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        pid = post["id"]
        r = client.patch(f"/api/performance/posts/{pid}", json={"title": "Renamed"})
        assert r.status_code == 200
        assert r.json()["title"] == "Renamed"
        r = client.delete(f"/api/performance/posts/{pid}")
        assert r.status_code == 204
        assert client.get(f"/api/performance/posts/{pid}").status_code == 404

    def test_unknown_linked_content_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post(
            "/api/performance/posts",
            json={
                "platform": "LinkedIn",
                "published_at": "2026-06-01T09:00:00Z",
                "content_id": 99999,
            },
        )
        assert r.status_code == 404

    def test_snapshot_on_unknown_post_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        r = client.post("/api/performance/posts/99999/snapshots", json={"views": 1})
        assert r.status_code == 404


# ----------------------------------------------------------------------------------
# Missing vs zero
# ----------------------------------------------------------------------------------
class TestMissingVsZero:
    def test_zero_views_is_recorded_as_zero(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        snap = _snapshot(client, post["id"], views=0, likes=0)
        assert snap["views"] == 0
        assert snap["impressions"] is None  # unknown stays unknown

    def test_omitted_metric_is_null_not_zero(self, client, auth_headers):
        client.headers.update(auth_headers)
        post = _register(client)
        snap = _snapshot(client, post["id"], likes=5)
        assert snap["views"] is None
        assert snap["likes"] == 5

    def test_aggregate_excludes_unknown_views(self, client, auth_headers):
        client.headers.update(auth_headers)
        p1 = _register(client, title="A")
        p2 = _register(client, title="B")
        _snapshot(client, p1["id"], views=100, likes=10, comments=5, shares=5)
        _snapshot(client, p2["id"], likes=3)  # views unknown
        data = client.get("/api/performance/analytics").json()
        # total_views only counts the known one: 100 (not 100+0)
        assert data["total_views"] == 100
        # avg engagement per view only from posts with views: (10+5+5)/100 = 0.2
        assert data["avg_engagement_rate_per_view"] == pytest.approx(0.2)


# ----------------------------------------------------------------------------------
# Aggregation & denominators
# ----------------------------------------------------------------------------------
class TestAggregation:
    def test_engagement_rate_per_view_denominator(self, client, auth_headers):
        """engagement_rate_per_view = (likes+comments+shares)/views — never /impressions."""
        client.headers.update(auth_headers)
        post = _register(client)
        # 20 engagements / 100 views = 0.2 ; impressions deliberately different
        _snapshot(client, post["id"], views=100, impressions=10000, likes=10, comments=5, shares=5)
        data = client.get("/api/performance/analytics").json()
        assert data["avg_engagement_rate_per_view"] == pytest.approx(0.2)
        assert data["avg_engagement_rate_per_impression"] == pytest.approx(0.002)

    def test_platform_aggregates_separate_denominators(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, platform="LinkedIn", snapshot={"views": 200, "likes": 20, "comments": 10, "shares": 10})
        _register(client, platform="YouTube", snapshot={"views": 500, "likes": 50})
        data = client.get("/api/performance/analytics").json()
        platforms = {p["platform"]: p for p in data["by_platform"]}
        assert platforms["LinkedIn"]["avg_engagement_rate_per_view"] == pytest.approx(0.2)
        assert platforms["YouTube"]["avg_engagement_rate_per_view"] == pytest.approx(0.1)

    def test_ctr_pct_is_platform_reported_only(self, client, auth_headers):
        """ctr_pct must not be derived from link_clicks/views."""
        client.headers.update(auth_headers)
        post = _register(client)
        _snapshot(client, post["id"], views=100, link_clicks=50)  # no ctr_pct given
        data = client.get("/api/performance/analytics").json()
        assert data["by_platform"][0]["avg_ctr_pct"] is None

    def test_empty_dataset_returns_warning(self, client, auth_headers):
        client.headers.update(auth_headers)
        data = client.get("/api/performance/analytics").json()
        assert data["post_count"] == 0
        assert any("No published posts" in w for w in data["warnings"])

    def test_posts_without_snapshots_warn(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client)  # no snapshot
        data = client.get("/api/performance/analytics").json()
        assert data["post_count"] == 1
        assert data["posts_with_metrics"] == 0
        assert any("no metric snapshots" in w for w in data["warnings"])

    def test_date_filter_excludes_old_posts(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, title="Old", published_at="2026-01-01T09:00:00Z",
                  snapshot={"views": 10})
        _register(client, title="New", published_at="2026-06-01T09:00:00Z",
                  snapshot={"views": 20})
        data = client.get(
            "/api/performance/analytics",
            params={"start": "2026-05-01T00:00:00Z"},
        ).json()
        assert data["total_views"] == 20

    def test_top_posts_ranked_by_views(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, title="Small", snapshot={"views": 10})
        _register(client, title="Big", snapshot={"views": 1000})
        data = client.get("/api/performance/analytics").json()
        assert data["top_posts"][0]["title"] == "Big"

    def test_compare_same_platform_only(self, client, auth_headers):
        client.headers.update(auth_headers)
        _register(client, platform="LinkedIn", title="A",
                  snapshot={"views": 100, "likes": 10, "comments": 5, "shares": 5})
        _register(client, platform="LinkedIn", title="B", snapshot={"views": 300, "likes": 15})
        _register(client, platform="YouTube", title="C", snapshot={"views": 999})
        rows = client.get("/api/performance/compare/LinkedIn").json()
        assert len(rows) == 2
        assert all(r["platform"] == "LinkedIn" for r in rows)


# ----------------------------------------------------------------------------------
# Auth & tenant isolation
# ----------------------------------------------------------------------------------
class TestAuthAndIsolation:
    def test_requires_auth(self, client):
        assert client.get("/api/performance/posts").status_code == 401
        assert client.get("/api/performance/analytics").status_code == 401
        assert client.get("/api/performance/insights").status_code == 401
        assert client.post("/api/performance/posts", json={}).status_code == 401

    def test_posts_isolated_between_users(self, client):
        client.headers.update(_login(client, "alice@example.com"))
        _register(client)  # alice's post
        alice_posts = client.get("/api/performance/posts").json()
        assert alice_posts["total"] >= 1

        client.headers.clear()
        client.headers.update(_login(client, "bob@example.com"))
        bob_posts = client.get("/api/performance/posts").json()
        assert bob_posts["total"] == 0  # cannot see alice's

    def test_snapshot_404_for_foreign_post(self, client):
        client.headers.update(_login(client, "alice@example.com"))
        post = _register(client)
        client.headers.clear()
        client.headers.update(_login(client, "bob@example.com"))
        r = client.post(
            f"/api/performance/posts/{post['id']}/snapshots", json={"views": 1}
        )
        assert r.status_code == 404
        assert client.get(f"/api/performance/posts/{post['id']}").status_code == 404

    def test_analytics_isolated(self, client):
        client.headers.update(_login(client, "alice@example.com"))
        _register(client, snapshot={"views": 500})
        client.headers.clear()
        client.headers.update(_login(client, "bob@example.com"))
        data = client.get("/api/performance/analytics").json()
        assert data["post_count"] == 0

    def test_insights_isolated(self, client):
        client.headers.update(_login(client, "alice@example.com"))
        for i in range(6):
            _register(client, title=f"P{i}", snapshot={"views": 100, "likes": 10, "comments": 2})
        client.headers.clear()
        client.headers.update(_login(client, "bob@example.com"))
        report = client.get("/api/performance/insights").json()
        assert report["posts_analyzed"] == 0
        assert "No published posts" in report["message"]


def _login(client: TestClient, email: str) -> dict:
    client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    r = client.post("/api/auth/login", data={"username": email, "password": "password123"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ----------------------------------------------------------------------------------
# Insights
# ----------------------------------------------------------------------------------
class TestInsights:
    def test_empty_report(self, client, auth_headers):
        client.headers.update(auth_headers)
        report = client.get("/api/performance/insights").json()
        assert report["posts_analyzed"] == 0
        assert report["insights"] == []
        assert "No published posts" in report["message"]

    def test_insufficient_data_state(self, client, auth_headers):
        """1 post with metrics -> every comparative insight must be insufficient."""
        client.headers.update(auth_headers)
        post = _register(client)
        _snapshot(client, post["id"], views=100, likes=10)
        report = client.get("/api/performance/insights").json()
        assert report["posts_analyzed"] == 1
        ok = [i for i in report["insights"] if i["status"] == "ok"]
        assert ok == []  # nothing claimable from n=1
        insufficient = [i for i in report["insights"] if i["status"] == "insufficient_data"]
        assert insufficient  # explicit insufficient-evidence state present

    def test_topic_insight_with_sample(self, client, auth_headers, db):
        """6 posts across two topics with clear performance split."""
        client.headers.update(auth_headers)
        # auth_headers creates tester@example.com; Content rows must belong to that user.
        from app.models import User

        owner = db.query(User).filter(User.email == "tester@example.com").one()

        def make_content(topic: str) -> int:
            c = Content(user_id=owner.id, title=f"{topic} post deep dive", body="body text here",
                        platform="LinkedIn", topic=topic, content_type="text post")
            db.add(c)
            db.commit()
            db.refresh(c)
            return c.id

        strong_ids = [make_content("AI automation") for _ in range(3)]
        weak_ids = [make_content("Company news") for _ in range(3)]
        for cid in strong_ids:
            _register(client, content_id=cid, snapshot={"views": 100, "likes": 15, "comments": 3, "shares": 2})
        for cid in weak_ids:
            _register(client, content_id=cid, snapshot={"views": 100, "likes": 1, "comments": 0, "shares": 0})

        report = client.get("/api/performance/insights").json()
        topic = next(i for i in report["insights"] if i["key"] == "topic_performance")
        assert topic["status"] == "ok"
        assert topic["posts_analyzed"] == 6
        assert topic["confidence"] in ("moderate", "strong")
        assert "AI automation" in topic["finding"]
        assert topic["evidence"]  # supporting post references
        assert topic["limitations"]  # limitations disclosed

    def test_review_vs_performance_insufficient_without_reviews(self, client, auth_headers):
        client.headers.update(auth_headers)
        for i in range(6):
            post = _register(client, title=f"P{i}")
            _snapshot(client, post["id"], views=100, likes=10)
        report = client.get("/api/performance/insights").json()
        rvp = next(i for i in report["insights"] if i["key"] == "review_vs_performance")
        assert rvp["status"] == "insufficient_data"
        assert rvp["confidence"] == "insufficient"

    def test_review_vs_performance_uses_actual_reviews(self, client, auth_headers, db):
        """Posts with ContentReview scores produce an association insight."""
        client.headers.update(auth_headers)
        from app.models import User

        owner = db.query(User).filter(User.email == "tester@example.com").one()
        for i, score in enumerate([80, 85, 30, 25]):
            c = Content(user_id=owner.id, title=f"Reviewed draft {i}", body="b", platform="LinkedIn",
                        topic="T", content_type="text post")
            db.add(c)
            db.commit()
            db.refresh(c)
            db.add(ContentReview(user_id=owner.id, content_id=c.id, source="draft",
                                 platform="LinkedIn", topic="T", title=f"Reviewed draft {i}",
                                 draft_excerpt="x",
                                 hook_score=score, clarity_score=score,
                                 brand_alignment=score, overall_score=float(score)))
            db.commit()
            post = _register(client, title=f"C{i}", content_id=c.id)
            # Higher-scored posts get more engagement.
            likes = 20 if score > 50 else 1
            _snapshot(client, post["id"], views=100, likes=likes, comments=2, shares=1)

        report = client.get("/api/performance/insights").json()
        rvp = next(i for i in report["insights"] if i["key"] == "review_vs_performance")
        assert rvp["status"] == "ok"
        assert rvp["posts_analyzed"] == 4
        assert "not a prediction" in rvp["finding"] or any(
            "not a prediction" in lim or "Correlation only" in lim for lim in rvp["limitations"]
        )
        # Must not invent scores: evidence rows cite actual review scores.
        assert any("review score=" in (e["note"] or "") for e in rvp["evidence"])


# ----------------------------------------------------------------------------------
# Service-level unit checks (direct, no HTTP)
# ----------------------------------------------------------------------------------
class TestServiceUnits:
    def test_sanitize_url_allows_https_only(self):
        assert performance_service.sanitize_url("https://x.com/a") == "https://x.com/a"
        assert performance_service.sanitize_url("ftp://x.com") == ""
        assert performance_service.sanitize_url("") == ""
        assert performance_service.sanitize_url("https://") == ""

    def test_confidence_label_boundaries(self):
        assert insight_service.confidence_label(0) == "insufficient"
        assert insight_service.confidence_label(1) == "insufficient"
        assert insight_service.confidence_label(2) == "weak"
        assert insight_service.confidence_label(4) == "weak"
        assert insight_service.confidence_label(5) == "moderate"
        assert insight_service.confidence_label(9) == "moderate"
        assert insight_service.confidence_label(10) == "strong"

    def test_validated_experiment_hints_requires_usable_evidence(self, db, user_id):
        # No posts -> no hints.
        assert insight_service.validated_experiment_hints(db, user_id) == []
