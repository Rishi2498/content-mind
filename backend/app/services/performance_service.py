"""Phase 4 — Performance intelligence.

Manual-first: creators register published posts and record dated metric
snapshots. Aggregations use each post's LATEST snapshot within the requested
window as its current state. Snapshots are append-only history.

Rate denominators (fixed per field, never interchanged):
* engagement_rate_per_view       = (likes + comments + shares) / views
* engagement_rate_per_impression = (likes + comments + shares) / impressions
* ctr_pct                        = platform-reported only (never derived,
                                   because platforms disagree on the denominator)
A post missing the denominator for a rate is excluded from that rate only.
NULL means unknown and is never coerced to 0.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Content, MetricSnapshot, PublishedPost
from ..schemas import (
    AttributeAggregate,
    InsightEvidence,
    MetricSnapshotInput,
    PerformanceAnalyticsResponse,
    PlatformAggregate,
    PostComparison,
    PublishedPostCreate,
    PublishedPostDetail,
    PublishedPostRead,
    PublishedPostUpdate,
    SnapshotTimeSeriesPoint,
)

logger = logging.getLogger("contentmind.performance")

# Minimum posts on a platform before cross-post comparisons are attempted.
MIN_COMPARISON_SAMPLE = 2
# Minimum posts for a "moderate" confidence insight; below = weak / directional.
MIN_MODERATE_SAMPLE = 5
MIN_STRONG_SAMPLE = 10


# ----------------------------------------------------------------------------------
# Validation helpers (user-submitted URL / external id are untrusted)
# ----------------------------------------------------------------------------------
def sanitize_url(raw: str) -> str:
    """Accept only http(s) URLs; anything else becomes empty string.

    The URL is stored for display only — the backend never fetches it.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except ValueError:
        return ""
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    # Cap length and drop control characters.
    return "".join(ch for ch in value if ch.isprintable())[:1000]


def sanitize_external_id(raw: str) -> str:
    return "".join(ch for ch in (raw or "") if ch.isprintable())[:200]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ----------------------------------------------------------------------------------
# Serializers
# ----------------------------------------------------------------------------------
def _snapshot_engagements(s: MetricSnapshot) -> int | None:
    """likes + comments + shares. None if all three are unknown."""
    parts = (s.likes, s.comments, s.shares)
    if all(p is None for p in parts):
        return None
    return sum(p or 0 for p in parts)


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or not denominator or denominator <= 0:
        return None
    return round(numerator / denominator, 5)


def post_to_read(post: PublishedPost) -> PublishedPostRead:
    latest = post.snapshots[-1] if post.snapshots else None
    data = PublishedPostRead.model_validate(post)
    data.snapshot_count = len(post.snapshots)
    data.latest_snapshot = latest
    return data


def post_to_detail(post: PublishedPost) -> PublishedPostDetail:
    data = PublishedPostDetail.model_validate(post)
    data.snapshot_count = len(post.snapshots)
    data.latest_snapshot = post.snapshots[-1] if post.snapshots else None
    data.snapshots = list(post.snapshots)
    return data


# ----------------------------------------------------------------------------------
# CRUD — every function takes an explicit user_id; queries always filter on it
# ----------------------------------------------------------------------------------
def register_post(db: Session, user_id: int, payload: PublishedPostCreate) -> PublishedPost:
    post = PublishedPost(
        user_id=user_id,
        content_id=payload.content_id,
        media_asset_id=payload.media_asset_id,
        platform=payload.platform.strip(),
        title=payload.title.strip(),
        external_id=sanitize_external_id(payload.external_id),
        url=sanitize_url(payload.url),
        published_at=_aware(payload.published_at) or datetime.now(timezone.utc),
    )
    db.add(post)
    db.flush()  # assign post.id for the snapshot FK

    if payload.initial_snapshot is not None:
        snap = build_snapshot(post, payload.initial_snapshot)
        db.add(snap)

    db.commit()
    db.refresh(post)
    return post


def build_snapshot(post: PublishedPost, payload: MetricSnapshotInput) -> MetricSnapshot:
    recorded = _aware(payload.recorded_at) or datetime.now(timezone.utc)
    published = _aware(post.published_at)
    days = None
    if published is not None:
        days = max(0, (recorded.date() - published.date()).days)
    return MetricSnapshot(
        post_id=post.id,
        user_id=post.user_id,
        source=payload.source,
        recorded_at=recorded,
        days_since_published=days,
        views=payload.views,
        impressions=payload.impressions,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        saves=payload.saves,
        link_clicks=payload.link_clicks,
        watch_time_seconds=payload.watch_time_seconds,
        avg_watch_duration_seconds=payload.avg_watch_duration_seconds,
        audience_retention_pct=payload.audience_retention_pct,
        ctr_pct=payload.ctr_pct,
    )


def add_snapshot(db: Session, user_id: int, post_id: int, payload: MetricSnapshotInput) -> MetricSnapshot | None:
    """Append a new snapshot. History is never overwritten."""
    post = get_post(db, user_id, post_id)
    if post is None:
        return None
    snap = build_snapshot(post, payload)
    db.add(snap)
    db.commit()
    db.refresh(snap)
    return snap


def get_post(db: Session, user_id: int, post_id: int) -> PublishedPost | None:
    return db.scalar(
        select(PublishedPost).where(PublishedPost.id == post_id, PublishedPost.user_id == user_id)
    )


def list_posts(
    db: Session,
    user_id: int,
    *,
    platform: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[PublishedPost], int]:
    base = select(PublishedPost).where(PublishedPost.user_id == user_id)
    if platform:
        base = base.where(PublishedPost.platform == platform)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(
            base.order_by(PublishedPost.published_at.desc()).limit(limit).offset(offset)
        )
    )
    return rows, total


def update_post(db: Session, user_id: int, post_id: int, payload: PublishedPostUpdate) -> PublishedPost | None:
    post = get_post(db, user_id, post_id)
    if post is None:
        return None
    if payload.title is not None:
        post.title = payload.title.strip()
    if payload.url is not None:
        post.url = sanitize_url(payload.url)
    if payload.external_id is not None:
        post.external_id = sanitize_external_id(payload.external_id)
    if payload.status is not None:
        post.status = payload.status
    db.commit()
    db.refresh(post)
    return post


def delete_post(db: Session, user_id: int, post_id: int) -> bool:
    post = get_post(db, user_id, post_id)
    if post is None:
        return False
    db.delete(post)
    db.commit()
    return True


# ----------------------------------------------------------------------------------
# Aggregation
# ----------------------------------------------------------------------------------
def _latest_snapshots(
    db: Session, user_id: int, *, start: datetime | None, end: datetime | None
) -> list[tuple[PublishedPost, MetricSnapshot]]:
    """Each post's most recent snapshot (optionally window-filtered).

    A post with no snapshot inside the window is excluded from metric
    aggregates but still counted in post_count when its published_at is in range.
    """
    posts = list(db.scalars(select(PublishedPost).where(PublishedPost.user_id == user_id)))
    pairs: list[tuple[PublishedPost, MetricSnapshot]] = []
    for post in posts:
        snaps = post.snapshots
        if start:
            snaps = [s for s in snaps if _aware(s.recorded_at) and _aware(s.recorded_at) >= start]
        if end:
            snaps = [s for s in snaps if _aware(s.recorded_at) and _aware(s.recorded_at) <= end]
        if snaps:
            pairs.append((post, snaps[-1]))
    return pairs


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 5) if values else None


def build_performance_analytics(
    db: Session,
    user_id: int,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    platform: str | None = None,
) -> PerformanceAnalyticsResponse:
    warnings: list[str] = []
    all_posts = list(db.scalars(select(PublishedPost).where(PublishedPost.user_id == user_id)))
    if platform:
        all_posts = [p for p in all_posts if p.platform == platform]

    pairs = _latest_snapshots(db, user_id, start=start, end=end)
    if platform:
        pairs = [(p, s) for p, s in pairs if p.platform == platform]
    # If a window is set, keep only posts published inside it too (post_count meaning).
    if start or end:
        filtered = []
        for post in pairs:
            pub = _aware(post[0].published_at)
            if start and pub and pub < start:
                continue
            if end and pub and pub > end:
                continue
            filtered.append(post)
        pairs = filtered

    if not all_posts:
        return PerformanceAnalyticsResponse(
            post_count=0,
            posts_with_metrics=0,
            warnings=[
                "No published posts registered yet. Register a post and record its "
                "actual results to unlock performance analytics."
            ],
            date_range={"start": start, "end": end},
        )

    if not pairs:
        warnings.append(
            "Posts are registered but no metric snapshots fall inside this filter. "
            "Record metrics to see aggregates."
        )

    # --- global totals (None when no post reported the metric at all) ---
    views_vals = [s.views for _, s in pairs if s.views is not None]
    impr_vals = [s.impressions for _, s in pairs if s.impressions is not None]
    eng_vals = [e for _, s in pairs if (e := _snapshot_engagements(s)) is not None]
    er_view = [
        r for _, s in pairs
        if (r := _rate(_snapshot_engagements(s), s.views)) is not None
    ]
    er_impr = [
        r for _, s in pairs
        if (r := _rate(_snapshot_engagements(s), s.impressions)) is not None
    ]

    total_views = sum(views_vals) if views_vals else None
    total_impr = sum(impr_vals) if impr_vals else None
    total_eng = sum(eng_vals) if eng_vals else None

    # --- by platform ---
    platform_buckets: dict[str, list[MetricSnapshot]] = defaultdict(list)
    platform_post_count: dict[str, int] = defaultdict(int)
    for post in all_posts:
        platform_post_count[post.platform] += 1
    for post, snap in pairs:
        platform_buckets[post.platform].append(snap)

    by_platform: list[PlatformAggregate] = []
    for name in sorted(platform_post_count, key=lambda n: -platform_post_count[n]):
        snaps = platform_buckets.get(name, [])
        p_views = [s.views for s in snaps if s.views is not None]
        p_impr = [s.impressions for s in snaps if s.impressions is not None]
        p_er_view = [r for s in snaps if (r := _rate(_snapshot_engagements(s), s.views)) is not None]
        p_er_impr = [r for s in snaps if (r := _rate(_snapshot_engagements(s), s.impressions)) is not None]
        p_ctr = [s.ctr_pct for s in snaps if s.ctr_pct is not None]
        p_ret = [s.audience_retention_pct for s in snaps if s.audience_retention_pct is not None]
        by_platform.append(
            PlatformAggregate(
                platform=name,
                post_count=platform_post_count[name],
                posts_with_metrics=len(snaps),
                total_views=sum(p_views) if p_views else None,
                total_impressions=sum(p_impr) if p_impr else None,
                avg_engagement_rate_per_view=_mean(p_er_view),
                avg_engagement_rate_per_impression=_mean(p_er_impr),
                avg_ctr_pct=_mean([float(v) for v in p_ctr]) if p_ctr else None,
                avg_retention_pct=_mean([float(v) for v in p_ret]) if p_ret else None,
            )
        )

    # --- by topic / content type (via linked Content) ---
    def _attr_groups(attribute: str) -> list[AttributeAggregate]:
        buckets: dict[str, list[MetricSnapshot]] = defaultdict(list)
        for post, snap in pairs:
            key = "Unlinked"
            if post.content_id:
                content = db.get(Content, post.content_id)
                if content is not None:
                    key = (getattr(content, attribute, "") or "").strip() or "Unspecified"
            buckets[key].append(snap)
        aggregates: list[AttributeAggregate] = []
        for key, snaps in buckets.items():
            views = [float(s.views) for s in snaps if s.views is not None]
            rates = [r for s in snaps if (r := _rate(_snapshot_engagements(s), s.views)) is not None]
            aggregates.append(
                AttributeAggregate(
                    key=key,
                    post_count=len(snaps),
                    posts_with_views=len(views),
                    avg_views=_mean(views),
                    median_views=round(statistics.median(views), 2) if views else None,
                    avg_engagement_rate_per_view=_mean(rates),
                )
            )
        aggregates.sort(key=lambda a: (a.avg_views or 0), reverse=True)
        return aggregates

    by_topic = _attr_groups("topic")
    by_content_type = _attr_groups("content_type")

    # --- over time (daily buckets of snapshot recorded_at) ---
    time_buckets: dict[str, list[MetricSnapshot]] = defaultdict(list)
    for _, snap in pairs:
        time_buckets[_aware(snap.recorded_at).date().isoformat()].append(snap)  # type: ignore[union-attr]
    over_time: list[SnapshotTimeSeriesPoint] = []
    for day in sorted(time_buckets):
        snaps = time_buckets[day]
        t_views = [s.views for s in snaps if s.views is not None]
        t_impr = [s.impressions for s in snaps if s.impressions is not None]
        t_rates = [r for s in snaps if (r := _rate(_snapshot_engagements(s), s.views)) is not None]
        over_time.append(
            SnapshotTimeSeriesPoint(
                period=day,
                snapshot_count=len(snaps),
                total_views=sum(t_views) if t_views else None,
                total_impressions=sum(t_impr) if t_impr else None,
                avg_engagement_rate_per_view=_mean(t_rates),
            )
        )

    # --- top posts (same platform only; ranked by views when available) ---
    ranked = sorted(
        ((p, s) for p, s in pairs if s.views is not None),
        key=lambda ps: ps[1].views or 0,
        reverse=True,
    )[:5]
    top_posts = [_comparison(p, s) for p, s in ranked]

    with_any_metric = sum(
        1
        for _, s in pairs
        if any(
            v is not None
            for v in (s.views, s.impressions, s.likes, s.comments, s.shares)
        )
    )
    if with_any_metric == 0:
        warnings.append(
            "Snapshots exist but none report views, impressions or engagement. "
            "Rates cannot be computed."
        )
    if len(pairs) < MIN_MODERATE_SAMPLE:
        warnings.append(
            f"Only {len(pairs)} snapshot(s) in range. Aggregates are directional, not conclusive."
        )

    published_dates = [d for d in (_aware(p.published_at) for p, _ in pairs) if d]
    return PerformanceAnalyticsResponse(
        post_count=len(all_posts) if not (start or end) else len(pairs),
        posts_with_metrics=with_any_metric,
        date_range={
            "start": start or (min(published_dates) if published_dates else None),
            "end": end or (max(published_dates) if published_dates else None),
        },
        total_views=total_views,
        total_impressions=total_impr,
        total_engagements=total_eng,
        avg_views=_mean([float(v) for v in views_vals]),
        avg_engagement_rate_per_view=_mean(er_view),
        avg_engagement_rate_per_impression=_mean(er_impr),
        by_platform=by_platform,
        by_topic=by_topic,
        by_content_type=by_content_type,
        over_time=over_time,
        top_posts=top_posts,
        warnings=warnings,
    )


def _comparison(post: PublishedPost, snap: MetricSnapshot) -> PostComparison:
    eng = _snapshot_engagements(snap)
    return PostComparison(
        post_id=post.id,
        title=post.title or "(untitled)",
        platform=post.platform,
        days_since_published=snap.days_since_published,
        views=snap.views,
        impressions=snap.impressions,
        engagement_count=eng,
        engagement_rate_per_view=_rate(eng, snap.views),
        engagement_rate_per_impression=_rate(eng, snap.impressions),
    )


def compare_posts(
    db: Session,
    user_id: int,
    platform: str,
    *,
    max_age_gap_days: int = 7,
) -> list[PostComparison]:
    """Compare posts on one platform with comparable observation windows."""
    pairs = _latest_snapshots(db, user_id, start=None, end=None)
    same = [(p, s) for p, s in pairs if p.platform == platform]
    if len(same) < MIN_COMPARISON_SAMPLE:
        return []
    ages = [s.days_since_published for _, s in same if s.days_since_published is not None]
    if ages:
        median_age = statistics.median(ages)
        same = [
            (p, s)
            for p, s in same
            if s.days_since_published is not None
            and abs(s.days_since_published - median_age) <= max_age_gap_days
        ]
    return [_comparison(p, s) for p, s in same]
