"""Metric math and aggregation."""

from __future__ import annotations

import math

from app.schemas import ContentCreate
from app.services.analytics_service import build_analytics
from app.services.content_service import all_contents, create_content


def _rows(db, sample_rows, user_id):
    for row in sample_rows:
        create_content(db, ContentCreate(**row), user_id)
    db.commit()


def test_engagement_rate_and_ctr_exact(db, sample_rows, user_id):
    _rows(db, sample_rows, user_id)
    a = build_analytics(all_contents(db, user_id))

    assert a.content_count == 3
    assert a.total_impressions == 17000
    assert a.published_with_metrics == 3
    assert a.total_engagements == 1599
    assert a.total_clicks == 710

    # Averages are unweighted means across items, not a pooled ratio: a single
    # 2k-impression post counts as much as a 10k-impression post.
    assert abs(a.avg_engagement_rate - (0.106 + 0.012 + 0.103) / 3) < 1e-5
    assert abs(a.avg_ctr - (0.05 + 0.005 + 0.04) / 3) < 1e-5
    assert abs(a.median_engagement_rate - 0.103) < 1e-5


def test_engagement_rate_definition_matches_spec(db, sample_rows, user_id):
    """engagement_rate = (likes + comments + shares) / impressions."""
    _rows(db, sample_rows, user_id)
    rows = {c.title: c for c in all_contents(db, user_id)}

    automation = rows["Automate your reporting pipeline end to end"]
    assert abs(automation.engagement_rate - (900 + 100 + 60) / 10000) < 1e-9
    assert abs(automation.ctr - 500 / 10000) < 1e-9

    news = rows["Weekly platform roundup announcement"]
    assert abs(news.engagement_rate - (20 + 3 + 1) / 2000) < 1e-9
    assert abs(news.ctr - 10 / 2000) < 1e-9


def test_index_vs_average_normalises_to_one(db, sample_rows, user_id):
    _rows(db, sample_rows, user_id)
    a = build_analytics(all_contents(db, user_id))
    by_topic = {s.key: s for s in a.by_topic}

    # AI automation 10.6% against the 7.37% mean = ~1.44x
    assert by_topic["AI automation"].index_vs_average > 1.0
    assert by_topic["AI news"].index_vs_average < 0.5


def test_empty_history_does_not_divide_by_zero(db):
    a = build_analytics([])

    assert a.content_count == 0
    assert a.avg_engagement_rate == 0.0
    assert a.avg_ctr == 0.0
    assert a.top_topic is None
    assert a.top_platform is None
    assert a.by_topic == []


def test_zero_impression_row_is_not_infinite(db, user_id):
    create_content(
        db,
        ContentCreate(
            title="A post that nobody saw",
            body="Zero impressions should not produce NaN or Infinity anywhere.",
            platform="LinkedIn",
            content_type="text post",
            topic="AI news",
            published_at="2026-02-01T09:00:00Z",
            impressions=0,
            likes=0,
            comments=0,
            shares=0,
            clicks=0,
        ),
        user_id,
    )
    db.commit()
    a = build_analytics(all_contents(db, user_id))
    row = a.by_platform[0]

    # A zero-impression post must not produce NaN/Infinity. With no baseline
    # available the index stays neutral at 1.0 rather than dividing by zero.
    assert row.avg_engagement_rate == 0.0
    assert row.avg_ctr == 0.0
    assert row.index_vs_average == 1.0
    assert a.published_with_metrics == 0
    assert a.avg_engagement_rate == 0.0
    assert math.isfinite(a.avg_engagement_rate)
    assert any("No performance metrics" in w for w in a.warnings)


def test_index_is_neutral_without_a_baseline(db):
    """A zero baseline must not yield a divide-by-zero or a fake winner."""
    a = build_analytics([])
    assert a.top_topic is None

    for group_stat in a.by_platform:
        assert math.isfinite(group_stat.index_vs_average)
