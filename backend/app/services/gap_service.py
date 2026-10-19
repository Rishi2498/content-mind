"""Content gap detection.

Gaps are *candidates*, not predictions. Every gap ships with the evidence that
produced it and hedged language — the engine is a ranking aid, not an oracle.

Scoring blends four signals:

1. ``under_coverage``  – inverse topic frequency across the content history.
2. ``adjacency``       – sits next to a topic that historically performs well.
3. ``recency_gap``     – a proven performer that has not been revisited in a while.
4. ``format_readiness``– the brand's best-performing formats are available for it.
"""

from __future__ import annotations

import re
import statistics
from collections import defaultdict

from ..models import Content
from ..schemas import AnalyticsResponse, ContentGap, GapResponse

# Candidate subjects an AI/automation-leaning content team is likely to need.
# Anchors are *published topic labels*; a gap is only proposed next to a topic
# the account actually covers, otherwise "adjacency" is a fiction.
ADJACENT_TOPICS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "AI automation": (
        ("AI ROI", ("budget", "cost", "roi", "payback", "business case")),
        ("AI implementation costs", ("pricing", "hidden cost", "budget", "tco")),
        ("AI adoption mistakes", ("mistake", "pitfall", "lessons", "avoid")),
        ("AI automation security", ("security", "governance", "compliance", "risk")),
        ("AI automation change management", ("adoption", "rollout", "training", "team")),
        ("AI automation measurement", ("kpi", "metric", "measure", "reporting")),
        ("Beginner AI tutorials", ("beginner", "getting started", "101")),
    ),
    "AI security": (
        ("AI data privacy practices", ("privacy", "gdpr", "data protection")),
        ("Prompt injection defence", ("injection", "security", "attack", "red team")),
    ),
    "Prompt engineering": (
        ("Prompt engineering at scale", ("scale", "production", "evaluation", "testing")),
        ("Prompt engineering for developers", ("developer", "api", "code")),
    ),
    "Customer support AI": (
        ("AI support deflection metrics", ("deflection", "metric", "measurement")),
        ("Escalation workflows for AI support", ("escalation", "handoff", "workflow")),
    ),
    "AI news": (
        ("AI regulation update", ("regulation", "policy", "compliance")),
        ("AI model comparisons", ("compare", "vs", "benchmark", "evaluation")),
    ),
    "Customer stories": (
        ("Customer onboarding playbooks", ("onboarding", "activation", "retention")),
    ),
    "Data privacy": (
        ("Data retention for AI workloads", ("retention", "storage", "governance")),
    ),
}

FORMAT_AFFINITY: dict[str, tuple[str, ...]] = {
    "AI ROI": ("carousel", "thread", "text post", "blog post", "newsletter"),
    "AI implementation costs": ("blog post", "carousel", "thread"),
    "AI adoption mistakes": ("carousel", "list post", "text post", "video"),
    "AI automation security": ("blog post", "whitepaper", "thread"),
    "AI automation change management": ("blog post", "case study", "newsletter"),
    "AI automation measurement": ("carousel", "blog post", "newsletter"),
    "Prompt engineering at scale": ("blog post", "thread", "technical post"),
    "Prompt engineering for developers": ("technical post", "blog post", "code snippet"),
    "AI regulation update": ("newsletter", "blog post", "text post"),
    "AI model comparisons": ("carousel", "blog post", "comparison post"),
    "MLOps for small teams": ("blog post", "tutorial", "thread"),
    "AI data privacy practices": ("blog post", "whitepaper", "newsletter"),
    "Prompt injection defence": ("technical post", "blog post"),
    "Customer onboarding playbooks": ("case study", "blog post", "webinar"),
    "Beginner AI tutorials": ("tutorial", "video", "carousel"),
}


def _prioritise(score: float) -> str:
    if score >= 0.62:
        return "high"
    if score >= 0.38:
        return "medium"
    return "low"


def _hedge(count: int) -> str:
    if count == 0:
        return "uncovered"
    if count == 1:
        return "covered by only 1 related item so far"
    return f"covered by only {count} related items"


def detect_gaps(
    analytics: AnalyticsResponse,
    contents: list[Content],
    limit: int = 6,
) -> GapResponse:
    rows = [c for c in contents if c.published_at is not None]
    if not rows:
        return GapResponse(
            gaps=[],
            method="not enough history to detect gaps",
            note="Add historical content and ContentMind will surface potential content gaps.",
        )

    topic_counts: dict[str, int] = defaultdict(int)
    topic_rates: dict[str, list[float]] = defaultdict(list)
    topic_last: dict[str, object] = {}
    for c in rows:
        topic = (c.topic or "").strip() or "General"
        topic_counts[topic] += 1
        if c.impressions:
            topic_rates[topic].append(c.engagement_rate)
        published = c.published_at
        if published is not None:
            current = topic_last.get(topic)
            if current is None or published > current:
                topic_last[topic] = published

    overall_avg = analytics.avg_engagement_rate or 0.0
    max_count = max(topic_counts.values()) if topic_counts else 1

    def topic_strength(topic: str) -> float:
        rates = topic_rates.get(topic) or []
        if not rates or not overall_avg:
            return 0.5
        return max(0.0, min(2.0, (statistics.fmean(rates) / overall_avg)))

    # Two guards against proposing something already published:
    #   1. exact/close match on a published topic label
    #   2. a title that mentions at least two of the candidate's keywords
    # Both must be precise — a fuzzy word match produced phantom gaps.
    def _normalise(label: str) -> str:
        return re.sub(r"[^a-z0-9 ]", " ", (label or "").lower()).split(" and ")[0].strip()

    published_topics = {_normalise(t) for t in topic_counts}
    title_token_sets: list[set[str]] = [
        {w for w in (c.title or "").lower().split() if len(w) > 3} for c in rows
    ]

    def _already_covered(candidate: str, keywords: tuple[str, ...]) -> bool:
        if _normalise(candidate) in published_topics:
            return True
        required = {k.lower() for k in keywords if len(k) > 4}
        if len(required) >= 2 and any(required.issubset(tokens) for tokens in title_token_sets):
            return True
        return False

    candidates: list[ContentGap] = []
    seen: set[str] = set()

    for anchor, entries in ADJACENT_TOPICS.items():
        anchor_count = topic_counts.get(anchor, 0)
        if not anchor_count:
            # No anchor coverage means no genuine adjacency to reason about.
            continue
        anchor_strength = topic_strength(anchor)
        anchor_recent = _days_since(topic_last.get(anchor))
        for candidate, keywords in entries:
            if candidate.lower() in seen:
                continue
            if _already_covered(candidate, keywords):
                continue

            coverage_count = topic_counts.get(candidate, 0)
            under_coverage = 1.0 - (coverage_count / max_count) if max_count else 1.0

            adjacency = 0.35 + 0.45 * anchor_strength
            recency = 0.0
            if anchor_recent is not None:
                if anchor_recent >= 45:
                    recency = 0.30
                elif anchor_recent >= 21:
                    recency = 0.18

            format_score = _format_readiness(candidate)
            score = round(
                min(1.0, 0.34 * under_coverage + 0.34 * adjacency + 0.18 * recency + 0.14 * format_score),
                4,
            )

            anchor_avg = statistics.fmean(topic_rates[anchor]) if topic_rates.get(anchor) else 0.0
            idx = (anchor_avg / overall_avg) if overall_avg else 0.0
            anchor_clause = (
                f"adjacent topic '{anchor}' has performed {idx:.1f}x the account average"
                if overall_avg
                else f"adjacent topic '{anchor}' is part of an established content pillar"
            )

            evidence: list[str] = [
                f"'{anchor}' has {anchor_count} published item(s) at "
                f"{anchor_avg * 100:.1f}% average engagement ({idx:.1f}x account average)"
            ]
            if anchor_recent is not None:
                evidence.append(f"last published on '{anchor}' was {anchor_recent} days ago")
            evidence.append(f"potential content gap: {candidate} is {_hedge(coverage_count)}")

            seen.add(candidate.lower())
            candidates.append(
                ContentGap(
                    topic=candidate,
                    reason=(
                        f"Potential content gap. '{candidate}' is {_hedge(coverage_count)}, while "
                        f"{anchor_clause}. Worth testing rather than assuming."
                    ),
                    priority=_prioritise(score),
                    score=score,
                    coverage_count=coverage_count,
                    evidence=evidence,
                    suggested_formats=list(FORMAT_AFFINITY.get(candidate, ("carousel", "text post", "blog post"))),
                    adjacency=[anchor],
                )
            )

    candidates.sort(key=lambda g: g.score, reverse=True)
    return GapResponse(
        gaps=candidates[:limit],
        topics_covered=len(topic_counts),
        content_analyzed=len(rows),
        method=(
            "Ranks uncovered subjects adjacent to historically strong topics using "
            "topic frequency, relative engagement, recency and format readiness."
        ),
        note="Gaps are candidates for testing, not predictions of performance.",
    )


def _days_since(value) -> int | None:
    if value is None:
        return None
    from datetime import datetime, timezone

    published = value
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - published).days


def _already_covered(candidate: str, existing_tokens: set[str], keywords: tuple[str, ...]) -> bool:
    """Heuristic guard: skip if a strong keyword already appears in the history."""
    candidate_words = [w for w in candidate.lower().split() if len(w) > 4]
    keyword_hits = sum(1 for kw in keywords if kw in existing_tokens)
    if candidate_words and sum(1 for w in candidate_words if w in existing_tokens) >= max(2, len(candidate_words) - 1):
        return True
    return keyword_hits >= 2


def _format_readiness(candidate: str) -> float:
    formats = FORMAT_AFFINITY.get(candidate)
    if not formats:
        return 0.5
    return 0.7
