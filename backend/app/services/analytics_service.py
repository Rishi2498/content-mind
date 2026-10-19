"""Performance analytics.

Deliberately small: the only job here is to produce the evidence the strategy
agent reasons over. No ML, no forecasting.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Content
from ..schemas import (
    AnalyticsResponse,
    ContentRead,
    GroupStat,
    TimeSeriesPoint,
    TopicCoverage,
)

ENGAGEMENT_COMPONENTS = ("likes", "comments", "shares")


# ----------------------------------------------------------------------------------
# Pure metric helpers (unit-tested directly)
# ----------------------------------------------------------------------------------
def engagement_count(likes: int, comments: int, shares: int) -> int:
    return int(likes or 0) + int(comments or 0) + int(shares or 0)


def engagement_rate(likes: int, comments: int, shares: int, impressions: int) -> float:
    """(likes + comments + shares) / impressions. Zero-safe."""
    if not impressions or impressions <= 0:
        return 0.0
    return engagement_count(likes, comments, shares) / impressions


def click_through_rate(clicks: int, impressions: int) -> float:
    if not impressions or impressions <= 0:
        return 0.0
    return int(clicks or 0) / impressions


def performance_index(value: float, baseline: float) -> float:
    """How a segment compares to the account average. 1.0 == average."""
    if baseline <= 0:
        return 1.0
    return round(value / baseline, 3)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ----------------------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------------------
def _build_groups(rows: list[Content], attribute: str, overall_avg: float) -> list[GroupStat]:
    buckets: dict[str, list[Content]] = defaultdict(list)
    for row in rows:
        key = (getattr(row, attribute) or "").strip() or "Unspecified"
        buckets[key].append(row)

    stats: list[GroupStat] = []
    for key, items in buckets.items():
        rates = [c.engagement_rate for c in items if c.impressions]
        ctrs = [c.ctr for c in items if c.impressions]
        avg_rate = statistics.fmean(rates) if rates else 0.0
        median_rate = statistics.median(rates) if rates else 0.0
        stats.append(
            GroupStat(
                key=key,
                label=key,
                count=len(items),
                impressions=sum(c.impressions for c in items),
                engagements=sum(c.engagement_count for c in items),
                avg_engagement_rate=round(avg_rate, 5),
                median_engagement_rate=round(median_rate, 5),
                avg_ctr=round(statistics.fmean(ctrs), 5) if ctrs else 0.0,
                index_vs_average=performance_index(avg_rate, overall_avg),
            )
        )
    stats.sort(key=lambda s: (s.avg_engagement_rate, s.count), reverse=True)
    return stats


def _coverage(rows: list[Content], overall_avg: float) -> list[TopicCoverage]:
    buckets: dict[str, list[Content]] = defaultdict(list)
    for row in rows:
        buckets[(row.topic or "").strip() or "Unspecified"].append(row)

    now = datetime.now(timezone.utc)
    coverage: list[TopicCoverage] = []
    for topic, items in buckets.items():
        dates = [d for d in (_as_aware(c.published_at) for c in items) if d]
        last = max(dates) if dates else None
        days_since = (now - last).days if last else None
        rates = [c.engagement_rate for c in items if c.impressions]
        avg_rate = statistics.fmean(rates) if rates else 0.0
        coverage.append(
            TopicCoverage(
                topic=topic,
                count=len(items),
                last_published_at=last,
                days_since_published=days_since,
                avg_engagement_rate=round(avg_rate, 5),
                performance_index=performance_index(avg_rate, overall_avg),
            )
        )
    coverage.sort(key=lambda c: c.count, reverse=True)
    return coverage


def _time_series(rows: list[Content], bucket_days: int = 14, limit: int = 12) -> list[TimeSeriesPoint]:
    buckets: dict[str, list[Content]] = defaultdict(list)
    for row in rows:
        published = _as_aware(row.published_at)
        if published is None:
            continue
        epoch_day = published.date()
        anchor = datetime(2024, 1, 1, tzinfo=timezone.utc).date()
        offset = (epoch_day - anchor).days // bucket_days
        buckets[f"B{offset:04d}"].append(row)

    ordered = sorted(buckets.items(), key=lambda kv: kv[0])[-limit:]
    points: list[TimeSeriesPoint] = []
    for bucket_id, items in ordered:
        offset = int(bucket_id[1:])
        start = datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=offset * bucket_days)
        impressions = sum(c.impressions for c in items)
        engagements = sum(c.engagement_count for c in items)
        points.append(
            TimeSeriesPoint(
                period=start.strftime("%d %b %Y"),
                content_count=len(items),
                impressions=impressions,
                engagements=engagements,
                engagement_rate=round(engagements / impressions, 5) if impressions else 0.0,
            )
        )
    return points


def get_analytics(db: Session, limit: int = 500) -> AnalyticsResponse:
    rows = list(db.scalars(select(Content).order_by(Content.published_at.desc()).limit(limit)))
    return build_analytics(rows)


def build_analytics(rows: list[Content]) -> AnalyticsResponse:
    warnings: list[str] = []
    with_metrics = [c for c in rows if c.impressions and c.impressions > 0]

    if not rows:
        return AnalyticsResponse(
            warnings=["No content recorded yet. Add historical content to unlock personalised planning."],
            content_count=0,
        )

    if not with_metrics:
        warnings.append(
            "No performance metrics recorded. Engagement analysis is unavailable; "
            "recommendations will rely on topics and brand voice only."
        )

    total_impressions = sum(c.impressions for c in rows)
    total_engagements = sum(c.engagement_count for c in rows)
    total_clicks = sum(c.clicks for c in rows)
    rates = [c.engagement_rate for c in with_metrics]
    ctrs = [c.ctr for c in with_metrics if c.impressions]
    overall_avg = statistics.fmean(rates) if rates else 0.0

    by_platform = _build_groups(rows, "platform", overall_avg)
    by_topic = _build_groups(rows, "topic", overall_avg)
    by_type = _build_groups(rows, "content_type", overall_avg)
    by_audience = _build_groups(rows, "audience", overall_avg)

    if len(rows) < 10:
        warnings.append(
            f"Only {len(rows)} content item(s) available. Insights are directional, not conclusive."
        )

    ranked = sorted(with_metrics, key=lambda c: c.engagement_rate, reverse=True) if with_metrics else []

    published_dates = [d for d in (_as_aware(c.published_at) for c in rows) if d]

    return AnalyticsResponse(
        content_count=len(rows),
        published_with_metrics=len(with_metrics),
        total_impressions=total_impressions,
        total_engagements=total_engagements,
        total_clicks=total_clicks,
        avg_engagement_rate=round(overall_avg, 5),
        median_engagement_rate=round(statistics.median(rates), 5) if rates else 0.0,
        avg_ctr=round(statistics.fmean(ctrs), 5) if ctrs else 0.0,
        top_topic=by_topic[0] if by_topic else None,
        top_platform=by_platform[0] if by_platform else None,
        top_content_type=by_type[0] if by_type else None,
        top_audience=by_audience[0] if by_audience else None,
        by_platform=by_platform,
        by_topic=by_topic,
        by_content_type=by_type,
        by_audience=by_audience,
        topic_coverage=_coverage(rows, overall_avg),
        over_time=_time_series(rows),
        best_content=[ContentRead.model_validate(c) for c in ranked[:5]],
        worst_content=[ContentRead.model_validate(c) for c in list(reversed(ranked[-5:])) if c.impressions],
        recent_content=[ContentRead.model_validate(c) for c in rows[:8]],
        coverage_ratio=round(len({c.topic for c in rows}) / max(1, len(rows)), 3),
        date_range={
            "start": min(published_dates) if published_dates else None,
            "end": max(published_dates) if published_dates else None,
        },
        warnings=warnings,
    )
