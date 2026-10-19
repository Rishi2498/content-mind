"""Shared pytest fixtures.

Every test runs against a throwaway SQLite file so the developer's real
`contentmind.db` and any in-memory Hindsight state are never touched.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest


# Force the deterministic provider *before* app config is imported, so tests
# never make a network call even if a developer has real credentials in .env.
os.environ["LLM_PROVIDER"] = "heuristic"
os.environ["HINDSIGHT_ALLOW_LOCAL_FALLBACK"] = "true"

# A temp DATABASE_URL must be set before any app module reads settings.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="contentmind-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP_DIR / 'test.db').as_posix()}"
os.environ.pop("HINDSIGHT_API_URL", None)
os.environ.pop("HINDSIGHT_API_KEY", None)
os.environ.pop("LLM_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.services.hindsight_service import get_hindsight_service  # noqa: E402
from app.services.llm_service import get_llm_service  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Truncate every table before and after each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def clean_memory() -> Iterator[None]:
    """Reset the in-process fallback memory bank between tests."""
    get_hindsight_service().clear()
    yield
    get_hindsight_service().clear()


@pytest.fixture
def db() -> Iterator:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user_id(db) -> int:
    """A persisted user row for direct-service (non-HTTP) tests."""
    from app.auth import get_password_hash
    from app.models import User

    user = User(email="direct@example.com", hashed_password=get_password_hash("secret123"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user.id


@pytest.fixture
def auth_headers(client: TestClient) -> dict[str, str]:
    """Create a test user and return Authorization headers with their token."""
    email = "tester@example.com"
    password = "secret123"
    signup = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert signup.status_code in (200, 201), signup.text
    login = client.post("/api/auth/login", data={"username": email, "password": password})
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def _override_get_db() -> Iterator:
    """Per-request session that is always closed.

    A plain ``lambda: SessionLocal()`` leaks a session (and an open SQLite
    transaction) for every request, which deadlocks ``drop_all`` at teardown.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[get_db] = _override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def seeded_client(client: TestClient, auth_headers: dict[str, str]) -> TestClient:
    """A client with the 72-item demo corpus already loaded."""
    client.headers.update(auth_headers)
    client.post("/api/demo/reset")
    response = client.post("/api/demo/seed", json={})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def sample_rows() -> list[dict]:
    """Three content rows with hand-computable metrics.

    engagement_rate = (likes + comments + shares) / impressions
      A: (900 + 100 + 60)  / 10000 = 10.60%
      B: ( 20 +   3 +  1)  /  2000 =  1.20%
      C: (450 +  40 + 25)  /  5000 = 10.30%
    ctr = clicks / impressions
      A: 500/10000 = 5.00%
      B:  10/ 2000 = 0.50%
      C: 200/ 5000 = 4.00%
    """
    return [
        {
            "title": "Automate your reporting pipeline end to end",
            "body": "A walkthrough of the automation setup we use internally.",
            "platform": "LinkedIn",
            "content_type": "carousel",
            "topic": "AI automation",
            "published_at": "2026-01-05T09:00:00Z",
            "impressions": 10000,
            "likes": 900,
            "comments": 100,
            "shares": 60,
            "clicks": 500,
        },
        {
            "title": "Weekly platform roundup announcement",
            "body": "Short update on what shipped this week.",
            "platform": "Twitter",
            "content_type": "text post",
            "topic": "AI news",
            "published_at": "2026-01-12T09:00:00Z",
            "impressions": 2000,
            "likes": 20,
            "comments": 3,
            "shares": 1,
            "clicks": 10,
        },
        {
            "title": "Case study: how Northwind cut review time in half",
            "body": "A customer story with real numbers and lessons learned.",
            "platform": "Blog",
            "content_type": "case study",
            "topic": "Customer stories",
            "published_at": "2026-01-20T09:00:00Z",
            "impressions": 5000,
            "likes": 450,
            "comments": 40,
            "shares": 25,
            "clicks": 200,
        },
    ]


@pytest.fixture
def llm_service():
    return get_llm_service()
