"""Plan generation and persistence."""

from app.schemas import PlanRequest
from app.services.strategy_service import generate_plan_for_user


def test_plan_on_empty_db_does_not_crash(db, user_id):
    result = generate_plan_for_user(db, PlanRequest(days=7, posts_per_day=1), user_id)
    db.commit()

    assert result.plan.used_memory is False
    assert result.plan.used_historical is False
    assert len(result.plan.items) == 7


def test_plan_items_have_no_duplicate_topics(seeded_client):
    r = seeded_client.post(
        "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    )
    assert r.status_code == 200
    plan = r.json()["plan"]
    topics = [i["topic"] for i in plan["items"]]

    assert len(set(topics)) == len(topics), f"duplicate topics: {topics}"


def test_plan_items_have_reasons_and_memory_citations(seeded_client):
    plan = seeded_client.post(
        "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    ).json()["plan"]

    for item in plan["items"]:
        assert len(item["reason"]) > 20
        assert len(item["memory_used"]) > 0


def test_plan_date_range_matches_actual_items(seeded_client):
    plan = seeded_client.post(
        "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    ).json()["plan"]

    dates = [i["date"][:10] for i in plan["items"]]
    assert plan["date_range"].startswith(min(dates))
    assert plan["date_range"].endswith(max(dates))


def test_plan_uses_memory_after_learning(seeded_client):
    r = seeded_client.post(
        "/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]}
    )
    plan = r.json()
    assert plan["plan"]["used_memory"] is True
    assert plan["plan"]["used_historical"] is True


def test_plan_persists_and_can_be_listed(seeded_client):
    seeded_client.post("/api/plans/generate", json={"days": 7, "posts_per_day": 1, "platforms": ["LinkedIn"]})
    r = seeded_client.get("/api/plans")
    assert r.status_code == 200
    payload = r.json()
    assert len(payload) >= 1


def test_plan_out_of_range_rejected(client, auth_headers):
    r = client.post(
        "/api/plans/generate",
        headers=auth_headers,
        json={"days": 99, "posts_per_day": 1},
    )
    assert r.status_code == 422
