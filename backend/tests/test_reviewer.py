"""Tests for the pre-publish reviewer (Phase 3).

Heuristic engine is exercised for real (deterministic); LLM calls are mocked.
API tests cover auth, tenant isolation, media-DNA score writing, and history.
"""

from __future__ import annotations

import io
import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("LLM_PROVIDER", "heuristic")
os.environ.setdefault("HINDSIGHT_ALLOW_LOCAL_FALLBACK", "1")
os.environ.setdefault("WHISPER_PROVIDER", "none")
os.environ.pop("LLM_API_KEY", None)

from app.config import get_settings
from app.database import session_scope
from app.main import app
from app.models import BrandProfile, ContentDNA, ContentReview, MediaAsset
from app.schemas import LLMReviewResult, ReviewerRequest, ReviewerSuggestion
from app.services import reviewer_service
from app.services.reviewer_service import ReviewContext


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("MEDIA_UPLOADS_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LLM_PROVIDER", "heuristic")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("HINDSIGHT_API_URL", raising=False)
    get_settings.cache_clear()
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def _login(client: TestClient, email: str = "r@x.com") -> dict:
    client.post("/api/auth/signup", json={"email": email, "password": "password123"})
    r = client.post("/api/auth/login", data={"username": email, "password": "password123"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


GOOD_DRAFT = (
    "How we cut reporting time by 60% with AI.\n\n"
    "Every Monday our team spent four hours pulling numbers into a slide deck. "
    "We automated the pipeline end to end. The result: 60% less time, zero missed deadlines. "
    "What would you automate first in your workflow?"
)
BAD_DRAFT = "This is a very really just actually quite simple update about our company. It is important to note we are very excited." 


class TestHeuristicEngine:
    def test_scores_in_range(self):
        ctx = ReviewContext(title="T", body=GOOD_DRAFT, platform="LinkedIn")
        hook, clarity, alignment = reviewer_service._heuristic_scores(ctx)
        assert 0 <= hook <= 100
        assert 0 <= clarity <= 100
        assert 0 <= alignment <= 100

    def test_good_draft_beats_weak_draft_on_hook(self):
        good = reviewer_service._heuristic_scores(ReviewContext(body=GOOD_DRAFT))
        weak = reviewer_service._heuristic_scores(ReviewContext(body=BAD_DRAFT))
        assert good[0] > weak[0]

    def test_weak_draft_suffers_on_clarity(self):
        good = reviewer_service._heuristic_scores(ReviewContext(body=GOOD_DRAFT))
        weak = reviewer_service._heuristic_scores(ReviewContext(body=BAD_DRAFT))
        assert good[1] > weak[1]

    def test_brand_profile_raises_alignment(self):
        brand = BrandProfile(
            user_id=1,
            brand_name="Acme",
            tone="practical, data-driven, friendly",
            target_audience="marketing leaders",
            description="AI automation for marketing teams",
        )
        with_brand = reviewer_service._heuristic_scores(
            ReviewContext(body="Our AI automation helps marketing leaders save time with data-driven reporting.", brand=brand)
        )
        without = reviewer_service._heuristic_scores(ReviewContext(body="Random text with no brand signal."))
        assert with_brand[2] >= without[2]

    def test_suggestions_cover_missing_cta_and_hook(self):
        suggestions = reviewer_service._heuristic_suggestions(ReviewContext(body="We shipped a new feature today."))
        categories = {s.category for s in suggestions}
        assert "hook" in categories
        assert "cta" in categories

    def test_every_suggestion_has_evidence(self):
        suggestions = reviewer_service._heuristic_suggestions(ReviewContext(body=BAD_DRAFT, brand=BrandProfile(user_id=1, tone="friendly")))
        assert all(s.evidence for s in suggestions)


class TestLLMReview:
    def test_llm_result_used_when_valid(self):
        fake = LLMReviewResult(
            hook_score=88, clarity_score=77, brand_alignment=66,
            summary="Strong hook.", suggestions=[
                ReviewerSuggestion(category="cta", severity="improve", suggestion="Add a CTA.", rationale="r", evidence="e")
            ],
        )
        mock_llm = MagicMock()
        mock_llm.available = True
        mock_llm.generate_json.return_value = (fake, "llm")
        with (
            patch.object(reviewer_service, "get_llm_service", return_value=mock_llm),
            patch.object(reviewer_service, "_recall_memories", return_value=[]),
            patch.object(reviewer_service, "_get_brand", return_value=None),
        ):
            res = reviewer_service.review_draft(
                None,  # db unused: brand/recall patched out
                ReviewerRequest(title="T", body=GOOD_DRAFT),
                user_id=1,
                persist=False,
            )
        assert res.engine == "llm"
        assert res.hook_score == 88
        assert res.degraded is False
        assert res.suggestions[0].category == "cta"

    def test_fallback_to_heuristic_when_llm_unavailable(self):
        mock_llm = MagicMock()
        mock_llm.available = False
        mock_llm.generate_json.return_value = (None, "fallback-unavailable")
        with (
            patch.object(reviewer_service, "get_llm_service", return_value=mock_llm),
            patch.object(reviewer_service, "_recall_memories", return_value=[]),
            patch.object(reviewer_service, "_get_brand", return_value=None),
        ):
            res = reviewer_service.review_draft(
                None, ReviewerRequest(body=GOOD_DRAFT), user_id=1, persist=False
            )
        assert res.engine == "heuristic"
        assert res.degraded is True
        assert res.suggestions


class TestReviewAPI:
    def test_requires_auth(self, client):
        assert client.post("/api/reviewer/review", json={"body": "hello"}).status_code == 401

    def test_review_draft_persists_history(self, client):
        h = _login(client)
        r = client.post(
            "/api/reviewer/review",
            headers=h,
            json={"title": "Draft", "body": GOOD_DRAFT, "platform": "LinkedIn", "topic": "AI"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["review_id"] is not None
        assert 0 <= body["overall_score"] <= 100
        assert body["engine"] in {"llm", "heuristic"}

        hist = client.get("/api/reviewer/reviews", headers=h).json()
        assert hist["total"] == 1
        assert hist["items"][0]["id"] == body["review_id"]

    def test_reviews_are_tenant_scoped(self, client):
        h_a = _login(client, "a@x.com")
        client.post("/api/reviewer/review", headers=h_a, json={"body": GOOD_DRAFT})
        h_b = _login(client, "b@x.com")
        assert client.get("/api/reviewer/reviews", headers=h_b).json()["total"] == 0


class TestMediaReview:
    def test_review_media_writes_dna_scores(self, client):
        h = _login(client)
        # create an asset + DNA directly (skip ffmpeg pipeline)
        with session_scope() as db:
            from app.models import User

            user = db.query(User).filter_by(email="m@x.com").first()
            client.post("/api/auth/signup", json={"email": "m@x.com", "password": "password123"})
            r = client.post("/api/auth/login", data={"username": "m@x.com", "password": "password123"})
            h = {"Authorization": f"Bearer {r.json()['access_token']}"}
            with session_scope() as db2:
                from app.models import User as U

                u = db2.query(U).filter_by(email="m@x.com").first()
                asset = MediaAsset(user_id=u.id, filename="v.mp4", stored_name="x.mp4",
                                   mime_type="video/mp4", file_size=1, media_type="video", status="ready")
                db2.add(asset)
                db2.flush()
                dna = ContentDNA(user_id=u.id, asset_id=asset.id,
                                 transcript="Welcome back to the show. Today we talk about AI automation for marketing teams.",
                                 scene_description="host at desk", visual_tags=["desk", "host"])
                db2.add(dna)
                db2.flush()
                aid = asset.id

        r = client.post(f"/api/reviewer/media/{aid}", headers=h)
        assert r.status_code == 200
        body = r.json()
        assert body["review_id"] is not None
        assert 0 <= body["hook_score"] <= 100

        with session_scope() as db:
            dna = db.query(ContentDNA).filter_by(asset_id=aid).first()
            assert dna.hook_score is not None
            assert dna.clarity_score is not None
            assert dna.brand_alignment is not None
            review = db.query(ContentReview).filter_by(asset_id=aid).first()
            assert review is not None
            assert review.source == "media"

    def test_review_missing_asset_404(self, client):
        h = _login(client)
        assert client.post("/api/reviewer/media/99999", headers=h).status_code == 404

    def test_review_other_tenant_asset_404(self, client):
        h_a = _login(client, "a@x.com")
        with session_scope() as db:
            from app.models import User

            u = db.query(User).filter_by(email="a@x.com").first()
            asset = MediaAsset(user_id=u.id, filename="a.mp4", stored_name="a.mp4",
                               mime_type="video/mp4", file_size=1, media_type="video", status="ready")
            db.add(asset)
            db.flush()
            db.add(ContentDNA(user_id=u.id, asset_id=asset.id, transcript="hello there friend"))
            db.flush()
            aid = asset.id
        h_b = _login(client, "b@x.com")
        assert client.post(f"/api/reviewer/media/{aid}", headers=h_b).status_code == 404
