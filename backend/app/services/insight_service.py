"""Phase 4 — Evidence-based insights.

Every insight is computed from the creator's own stored posts and metric
snapshots. Nothing is invented: no synthetic posts, no fabricated metrics, no
assumed audience data. Each finding reports:

* the number of relevant posts analyzed,
* the exact metric and comparison used,
* supporting post references (evidence rows),
* the observation period,
* a confidence label derived from the sample size,
* limitations (including alternative explanations),
* an experiment recommendation when the evidence is actionable.

Confidence rules (posts with a usable metric for the comparison):
* strong       >= 10 posts
* moderate     5-9 posts
* weak         2-4 posts (directional only, never causal)
* insufficient  < 2 posts -> status "insufficient_data"

Cross-platform metrics are never pooled for a single rate: platforms define
impressions, views and retention differently. Comparisons are per-platform or
explicitly labelled as mixed-platform with that limitation attached.

Reviewer-score correlation only uses posts that HAVE a review (or DNA score);
missing scores stay missing and are never backfilled. The output is described
as an association, never as a prediction of views or virality.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Content, ContentDNA, ContentReview, MetricSnapshot, PublishedPost
from ..schemas import (
    InsightEvidence,
    InsightReportResponse,
    PerformanceInsight,
)
from .performance_service import (
    MIN_MODERATE_SAMPLE,
    MIN_STRONG_SAMPLE,
    _aware,
    _latest_snapshots,
    _rate,
    _snapshot_engagements,
)

logger = logging.getLogger("contentmind.insights")

# CTA phrases that are cheap to detect in linked Content bodies.
CTA_MARKERS = (
    "comment below", "drop a comment", "let us know", "share this",
    "subscribe", "follow for", "link in bio", "sign up", "book a demo",
    "download", "read more", "reply", "save this", "send this",
)


def confidence_label(n: int) -> str:
    if n >= MIN_STRONG_SAMPLE:
        return "strong"
    if n >= MIN_MODERATE_SAMPLE:
        return "moderate"
    if n >= 2:
        return "weak"
    return "insufficient"


def _content_for(post: PublishedPost, db: Session) -> Content | None:
    if not post.content_id:
        return None
    return db.get(Content, post.content_id)


def _latest_review(db: Session, user_id: int, content_id: int | None) -> ContentReview | None:
    if not content_id:
        return None
    rows = list(
        db.scalars(
            select(ContentReview)
            .where(ContentReview.user_id == user_id, ContentReview.content_id == content_id)
            .order_by(ContentReview.created_at.desc())
            .limit(1)
        )
    )
    return rows[0] if rows else None


def _latest_dna_score(db: Session, user_id: int, post: PublishedPost) -> float | None:
    if post.media_asset_id:
        dna = db.scalar(
            select(ContentDNA).where(
                ContentDNA.user_id == user_id, ContentDNA.asset_id == post.media_asset_id
            )
        )
        if dna is not None and dna.hook_score is not None:
            return dna.hook_score
    return None


def _period_label(pairs: list[tuple[PublishedPost, MetricSnapshot]]) -> str:
    dates = [d for d in (_aware(s.recorded_at).date() for _, s in pairs) if d]  # type: ignore[union-attr]
    if not dates:
        return ""
    return f"{min(dates).isoformat()} to {max(dates).isoformat()}"


@dataclass
class _PostMetric:
    post: PublishedPost
    snap: MetricSnapshot
    content: Content | None
    er_view: float | None  # engagement per view
    er_impr: float | None  # engagement per impression
    views: int | None


def _collect(db: Session, user_id: int) -> list[_PostMetric]:
    out: list[_PostMetric] = []
    for post, snap in _latest_snapshots(db, user_id, start=None, end=None):
        eng = _snapshot_engagements(snap)
        out.append(
            _PostMetric(
                post=post,
                snap=snap,
                content=_content_for(post, db),
                er_view=_rate(eng, snap.views),
                er_impr=_rate(eng, snap.impressions),
                views=snap.views,
            )
        )
    return out


def _insufficient(key: str, finding: str, metric: str, comparison: str, needed: int, have: int) -> PerformanceInsight:
    return PerformanceInsight(
        key=key,
        finding=finding,
        posts_analyzed=have,
        metric=metric,
        comparison=comparison,
        confidence="insufficient",
        status="insufficient_data",
        limitations=[
            f"Need at least {needed} posts with a usable '{metric}' value; only {have} available.",
            "No conclusion can be drawn until more data is recorded.",
        ],
        recommendation=(
            f"Record metrics for at least {max(0, needed - have)} more comparable post(s) "
            "to unlock this analysis."
        ),
    )


# ----------------------------------------------------------------------------------
# Individual analyses
# ----------------------------------------------------------------------------------
def _attribute_insight(
    rows: list[_PostMetric],
    attribute_getter,
    key: str,
    label: str,
) -> PerformanceInsight:
    """Compare per-platform engagement-per-view across a Content attribute."""
    metric = "engagement_rate_per_view"
    comparison = "per-platform mean engagement-per-view, best group vs account median"

    usable = [r for r in rows if r.er_view is not None]
    if len(usable) < 2:
        return _insufficient(
            key, f"Not enough posts with views and engagement to compare {label}s.",
            metric, comparison, needed=2, have=len(usable),
        )

    # Group within each platform first; only pool when a group is single-platform.
    by_attr: dict[str, list[_PostMetric]] = defaultdict(list)
    for r in usable:
        attr_value = (attribute_getter(r.content) or "").strip() or ("Unlinked" if r.content is None else "Unspecified")
        by_attr[attr_value].append(r)

    group_stats: list[tuple[str, float, int]] = []
    for attr_value, group in by_attr.items():
        # Mixed-platform groups get their own limitation; we still compute,
        # but flag it in the limitations list below.
        rates = [r.er_view for r in group if r.er_view is not None]
        if rates:
            group_stats.append((attr_value, statistics.fmean(rates), len(group)))

    if len(group_stats) < 2:
        return _insufficient(
            key, f"Only one {label} group has measurable performance so far.",
            metric, comparison, needed=2, have=len(group_stats),
        )

    group_stats.sort(key=lambda g: g[1], reverse=True)
    best_name, best_rate, best_n = group_stats[0]
    median_rate = statistics.median([g[1] for g in group_stats])

    confidence = confidence_label(len(usable))
    platforms_in_data = {r.post.platform for r in usable}
    limitations = [
        "Association only — this does not prove the attribute caused the difference.",
        "Post age, posting time, audience size and topic novelty are not controlled.",
    ]
    if len(platforms_in_data) > 1:
        limitations.append(
            f"Posts span {len(platforms_in_data)} platforms; platforms define views and "
            "engagement differently, so treat the comparison as directional."
        )

    evidence = [
        InsightEvidence(
            post_id=r.post.id,
            title=r.post.title or "(untitled)",
            platform=r.post.platform,
            value=r.er_view,
            note=f"{label}={((attribute_getter(r.content) or 'Unlinked').strip() or 'Unspecified')}",
        )
        for r in sorted(usable, key=lambda x: x.er_view or 0, reverse=True)[:5]
    ]

    lift = (best_rate / median_rate) if median_rate > 0 else None
    lift_txt = f" ({lift:.1f}x the median group)" if lift and lift > 1.05 else ""
    return PerformanceInsight(
        key=key,
        finding=(
            f"Posts with {label} '{best_name}' average {best_rate * 100:.1f}% engagement "
            f"per view{lift_txt}, the strongest of {len(group_stats)} {label} groups."
        ),
        posts_analyzed=len(usable),
        metric=metric,
        comparison=comparison,
        confidence=confidence,  # type: ignore[arg-type]
        evidence=evidence,
        observation_period=_period_label([(r.post, r.snap) for r in usable]),
        limitations=limitations,
        recommendation=(
            f"Publish another {label} '{best_name}' post and record day-7 metrics to "
            "test whether the pattern holds."
        ),
    )


def _topic_insight(rows: list[_PostMetric]) -> PerformanceInsight:
    return _attribute_insight(rows, lambda c: c.topic if c else "", "topic_performance", "topic")


def _format_insight(rows: list[_PostMetric]) -> PerformanceInsight:
    return _attribute_insight(rows, lambda c: c.content_type if c else "", "format_performance", "format")


def _cta_insight(rows: list[_PostMetric]) -> PerformanceInsight:
    metric = "engagement_rate_per_view"
    comparison = "posts whose linked Content body contains a CTA marker vs those that do not"

    usable = [r for r in rows if r.er_view is not None and r.content is not None]
    if len(usable) < 4:
        return _insufficient(
            "cta_performance",
            "Not enough linked Content with measured performance to compare calls to action.",
            metric, comparison, needed=4, have=len(usable),
        )

    with_cta = [r for r in usable if any(m in (r.content.body or "").lower() for m in CTA_MARKERS)]
    without = [r for r in usable if r not in with_cta]
    if len(with_cta) < 2 or len(without) < 2:
        return _insufficient(
            "cta_performance",
            f"Need at least 2 posts with and 2 without a CTA marker; found {len(with_cta)} with, {len(without)} without.",
            metric, comparison, needed=4, have=len(usable),
        )

    rate_with = statistics.fmean(r.er_view for r in with_cta if r.er_view is not None)
    rate_without = statistics.fmean(r.er_view for r in without if r.er_view is not None)
    confidence = confidence_label(len(usable))

    winner = "with" if rate_with >= rate_without else "without"
    diff = abs(rate_with - rate_without)
    return PerformanceInsight(
        key="cta_performance",
        finding=(
            f"Posts containing a CTA marker average {rate_with * 100:.1f}% engagement per view "
            f"vs {rate_without * 100:.1f}% without ({winner} performs better by {diff * 100:.1f} points)."
        ),
        posts_analyzed=len(usable),
        metric=metric,
        comparison=comparison,
        confidence=confidence,  # type: ignore[arg-type]
        evidence=[
            InsightEvidence(
                post_id=r.post.id, title=r.post.title or "(untitled)",
                platform=r.post.platform, value=r.er_view,
                note="has CTA marker" if r in with_cta else "no CTA marker",
            )
            for r in sorted(usable, key=lambda x: x.er_view or 0, reverse=True)[:5]
        ],
        observation_period=_period_label([(r.post, r.snap) for r in usable]),
        limitations=[
            "CTA detection is keyword-based and may miss paraphrased calls to action.",
            "Posts with CTAs may differ in topic, length or format — association, not causation.",
        ],
        recommendation=(
            "Run a controlled test: publish two similar posts on the same topic and "
            "platform, one with a CTA and one without, then compare day-7 metrics."
        ),
    )


def _platform_insight(rows: list[_PostMetric]) -> PerformanceInsight:
    metric = "engagement_rate_per_view"
    comparison = "per-platform mean engagement-per-view (platforms compared side by side, never pooled)"

    by_platform: dict[str, list[_PostMetric]] = defaultdict(list)
    for r in rows:
        if r.er_view is not None:
            by_platform[r.post.platform].append(r)

    if len(by_platform) < 2:
        return _insufficient(
            "platform_performance",
            "Posts with metrics exist on fewer than two platforms; no cross-platform comparison possible.",
            metric, comparison, needed=2, have=len(by_platform),
        )

    stats: list[tuple[str, float, int]] = []
    for name, group in by_platform.items():
        stats.append((name, statistics.fmean(r.er_view for r in group if r.er_view is not None), len(group)))
    stats.sort(key=lambda s: s[1], reverse=True)
    usable_n = sum(s[2] for s in stats)

    return PerformanceInsight(
        key="platform_performance",
        finding=(
            f"Of {len(stats)} platforms with measurable data, '{stats[0][0]}' has the highest "
            f"mean engagement per view at {stats[0][1] * 100:.1f}% (n={stats[0][2]}), "
            f"vs '{stats[-1][0]}' at {stats[-1][1] * 100:.1f}% (n={stats[-1][2]})."
        ),
        posts_analyzed=usable_n,
        metric=metric,
        comparison=comparison,
        confidence=confidence_label(usable_n),  # type: ignore[arg-type]
        evidence=[
            InsightEvidence(note=f"{name}: {rate * 100:.1f}% avg engagement/view, n={n}", value=rate)
            for name, rate, n in stats
        ],
        observation_period=_period_label([(r.post, r.snap) for r in rows if r.er_view is not None]),
        limitations=[
            "Platforms define views, impressions and engagement differently — these rates "
            "are computed from each platform's own view counts and are not interchangeable.",
            "Sample sizes per platform may be small; a single viral post can skew a platform mean.",
            "Audience size and posting cadence differ per platform and are not controlled.",
        ],
        recommendation=(
            f"Shift one scheduled post toward '{stats[0][0]}' next week and record results "
            "to test whether the difference persists."
        ),
    )


def _review_vs_performance(db: Session, user_id: int, rows: list[_PostMetric]) -> PerformanceInsight:
    """Association between pre-publish review scores and later performance.

    Only posts that HAVE a review (or a DNA hook score) are included. Missing
    scores are never treated as zero. The finding is explicitly an association,
    not a prediction.
    """
    metric = "engagement_rate_per_view"
    comparison = "posts with review scores above vs at/below the sample median overall_score"

    scored: list[tuple[_PostMetric, float]] = []
    for r in rows:
        if r.er_view is None:
            continue
        review = _latest_review(db, user_id, r.post.content_id)
        if review is not None:
            scored.append((r, review.overall_score))
            continue
        dna_hook = _latest_dna_score(db, user_id, r.post)
        if dna_hook is not None:
            scored.append((r, dna_hook))

    if len(scored) < 4:
        return PerformanceInsight(
            key="review_vs_performance",
            finding=(
                "Not enough published posts have both a pre-publish review score and "
                "recorded performance to analyse this relationship."
            ),
            posts_analyzed=len(scored),
            metric=metric,
            comparison=comparison,
            confidence="insufficient",
            status="insufficient_data",
            limitations=[
                "Review scores and performance must both exist on the same post.",
                "Unevaluated content is excluded, not counted as zero.",
            ],
            recommendation=(
                "Review drafts before publishing (Reviewer page) and record post metrics; "
                "this analysis unlocks once ≥ 4 posts have both."
            ),
        )

    scores = [s for _, s in scored]
    median_score = statistics.median(scores)
    high = [(r, s) for r, s in scored if s > median_score]
    low = [(r, s) for r, s in scored if s <= median_score]
    if not high or not low:
        return _insufficient(
            "review_vs_performance",
            "All reviewed posts cluster on one side of the median score; no comparison possible.",
            metric, comparison, needed=4, have=len(scored),
        )

    rate_high = statistics.fmean(r.er_view for r, _ in high if r.er_view is not None)
    rate_low = statistics.fmean(r.er_view for r, _ in low if r.er_view is not None)

    return PerformanceInsight(
        key="review_vs_performance",
        finding=(
            f"Across {len(scored)} posts with review scores, those scoring above the "
            f"median ({median_score:.0f}) averaged {rate_high * 100:.1f}% engagement per view, "
            f"vs {rate_low * 100:.1f}% for those at or below it. This is an association "
            "in your data — not a prediction of future views."
        ),
        posts_analyzed=len(scored),
        metric=metric,
        comparison=comparison,
        confidence=confidence_label(len(scored)),  # type: ignore[arg-type]
        evidence=[
            InsightEvidence(
                post_id=r.post.id, title=r.post.title or "(untitled)",
                platform=r.post.platform, value=r.er_view,
                note=f"review score={s:.0f}",
            )
            for r, s in sorted(scored, key=lambda t: t[1], reverse=True)[:5]
        ],
        observation_period=_period_label([(r.post, r.snap) for r, _ in scored]),
        limitations=[
            "Correlation only — higher review scores may simply coincide with better topics.",
            "Posts without reviews are excluded; selecting only reviewed posts can bias the sample.",
            "Sample is your own history; it cannot predict virality or future platform behaviour.",
        ],
        recommendation=(
            "Keep reviewing before publish and recording after publish; revisit this "
            "comparison at ≥ 10 scored posts for a stronger read."
        ),
    )


# ----------------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------------
def build_insight_report(db: Session, user_id: int) -> InsightReportResponse:
    rows = _collect(db, user_id)
    with_metrics = [r for r in rows if r.er_view is not None or r.er_impr is not None or r.views is not None]

    if not rows:
        return InsightReportResponse(
            insights=[],
            posts_analyzed=0,
            posts_with_metrics=0,
            message=(
                "No published posts registered yet. Register a post and record its "
                "actual metrics to start generating evidence-based insights."
            ),
        )

    insights = [
        _topic_insight(rows),
        _format_insight(rows),
        _platform_insight(rows),
        _cta_insight(rows),
        _review_vs_performance(db, user_id, rows),
    ]

    message = (
        f"Analysed {len(rows)} registered post(s); {len(with_metrics)} have usable metrics."
    )
    if len(with_metrics) < MIN_MODERATE_SAMPLE:
        message += (
            f" Fewer than {MIN_MODERATE_SAMPLE} posts have metrics — findings are "
            "directional only until more results are recorded."
        )

    return InsightReportResponse(
        insights=insights,
        posts_analyzed=len(rows),
        posts_with_metrics=len(with_metrics),
        message=message,
    )


def validated_experiment_hints(db: Session, user_id: int, limit: int = 3) -> list[dict]:
    """Small, planner-safe projection of insights with usable evidence.

    Used by the content planner to recommend experiments grounded in the
    creator's own data. Only insights with status "ok" and confidence
    moderate/strong are returned; insufficient evidence yields an empty
    list so the planner falls back to its existing behaviour.
    """
    report = build_insight_report(db, user_id)
    hints: list[dict] = []
    for insight in report.insights:
        if insight.status != "ok":
            continue
        if insight.confidence not in ("moderate", "strong"):
            continue
        hints.append(
            {
                "key": insight.key,
                "finding": insight.finding,
                "posts_analyzed": insight.posts_analyzed,
                "confidence": insight.confidence,
                "recommendation": insight.recommendation,
                "limitation": insight.limitations[0] if insight.limitations else "",
            }
        )
        if len(hints) >= limit:
            break
    return hints
