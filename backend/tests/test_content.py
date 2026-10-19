"""Content CRUD validation."""

from app.schemas import ContentCreate
from app.services.content_service import create_content, all_contents, get_content


def test_create_content_persists(db, user_id):
    create_content(
        db,
        ContentCreate(
            title="Build a simple automation loop",
            body="Learn the building blocks.",
            platform="LinkedIn",
            content_type="carousel",
            topic="AI automation",
            published_at="2026-03-01T09:00:00Z",
            impressions=1000,
            likes=90,
            comments=10,
            shares=5,
            clicks=40,
        ),
        user_id,
    )
    db.commit()

    rows = all_contents(db, user_id)
    assert len(rows) == 1
    assert rows[0].engagement_rate > 0
    assert rows[0].ctr > 0


def test_title_too_short_rejected(client, auth_headers):
    r = client.post(
        "/api/content",
        headers=auth_headers,
        json={
            "title": "Hi",
            "body": "This body is long enough to pass the validation checks.",
            "platform": "LinkedIn",
            "content_type": "text post",
            "topic": "AI news",
        },
    )
    assert r.status_code == 422


def test_negative_metrics_rejected(client, auth_headers):
    r = client.post(
        "/api/content",
        headers=auth_headers,
        json={
            "title": "A longer title that is valid",
            "body": "Another sufficiently long body of text.",
            "platform": "Blog",
            "content_type": "article",
            "topic": "AI automation",
            "impressions": -5,
        },
    )
    assert r.status_code == 422


def test_get_content_404(client, auth_headers):
    r = client.get("/api/content/999999", headers=auth_headers)
    assert r.status_code == 404


def test_content_requires_auth(client):
    r = client.get("/api/content")
    assert r.status_code == 401
