"""Strategy service: recall → reason → recommend.

Pipeline for every plan or answer:

    request
      → Hindsight recall (multiple aspect-focused queries)
      → relational analytics
      → content gap detection
      → brand voice
      → strategy context
      → LLM (validated JSON)
      → persisted plan with per-item memory citations

The deterministic engine underneath does the same work without an LLM, so the
product is demoable and testable without a provider key.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import BrandProfile, Content, ContentInsight, ContentPlan, ContentPlanItem
from ..schemas import (
    AnalyticsResponse,
    BrandProfileRead,
    ChatResponse,
    ContentGap,
    ContentPlanItemRead,
    ContentRead,
    GapResponse,
    GroupStat,
    LLMPlan,
    LLMPlanItem,
    LLMStrategyAnswer,
    MemoryRecord,
    PlanGenerateResponse,
    PlanListResponse,
    PlanRead,
    PlanRequest,
)
from .analytics_service import build_analytics
from .content_service import all_contents
from .gap_service import detect_gaps
from .llm_service import get_llm_service
from .memory_service import MemoryService

logger = logging.getLogger("contentmind.strategy")

PLATFORM_FORMAT_AFFINITY: dict[str, tuple[str, ...]] = {
    "LinkedIn": ("carousel", "document post", "text post", "poll"),
    "Blog": ("blog post", "tutorial", "comparison post", "thought leadership"),
    "YouTube": ("video", "tutorial", "webinar"),
    "X": ("thread", "text post", "poll"),
    "Instagram": ("carousel", "image post", "reel"),
    "Newsletter": ("newsletter", "roundup", "case study"),
    "YouTube Shorts": ("reel", "short video"),
}

PLATFORM_LABEL = {
    "LinkedIn": "LinkedIn",
    "Blog": "the blog",
    "YouTube": "YouTube",
    "X": "X",
    "Instagram": "Instagram",
    "Newsletter": "the newsletter",
}

GAP_TITLE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "AI ROI": (
        "How to Actually Calculate the ROI of an AI Project",
        "The 4 Numbers You Need Before You Can Claim AI ROI",
        "Why Most AI ROI Calculations Are Wrong",
    ),
    "AI implementation costs": (
        "What an AI Implementation Really Costs (Hidden Line Items)",
        "The True Cost of Shipping an AI Feature",
    ),
    "AI adoption mistakes": (
        "5 AI Adoption Mistakes That Kill Your Rollout",
        "Where AI Pilots Stall: 5 Mistakes to Avoid",
    ),
    "AI automation security": (
        "Securing AI Automation: A Practical Checklist",
        "Who Owns Risk When an Agent Acts on Its Own?",
    ),
    "AI automation change management": (
        "Rolling Out AI Without Burning Out Your Team",
        "Change Management for AI Automation: What Actually Works",
    ),
    "AI automation measurement": (
        "Which Metrics Should You Actually Track for AI Automation?",
        "Measuring AI Automation: From Tickets Saved to Revenue",
    ),
    "AI regulation update": (
        "What the New AI Rules Actually Require of Your Team",
        "AI Regulation in Plain English: A Practical Update",
    ),
    "AI model comparisons": (
        "We Tested 4 Models on the Same Task. Here Is the Winner.",
        "Choosing an AI Model: A Comparison That Saves You a Rewrite",
    ),
    "Prompt engineering at scale": (
        "Prompt Engineering That Survives Production Traffic",
        "From Clever Prompts to Reliable Prompts",
    ),
    "Prompt engineering for developers": (
        "Prompt Patterns Every Developer Should Know",
        "Structured Prompting for Real APIs",
    ),
    "MLOps for small teams": (
        "MLOps on a Two-Person Team: The 20% That Matters",
        "Deploying Models Without a Platform Team",
    ),
    "AI data privacy practices": (
        "What Your AI Stack Should Never Send to a Model",
        "Data Privacy for AI Workloads: A Working Policy",
    ),
    "Prompt injection defence": (
        "Defending Against Prompt Injection in Production",
        "Your Agent Is Adversarial Input Away From an Incident",
    ),
    "Customer onboarding playbooks": (
        "The Onboarding Playbook Behind Our Fastest Ramp",
        "How We Cut Time-to-First-Value in Half",
    ),
    "Beginner AI tutorials": (
        "Your First AI Workflow, Start to Finish",
        "A Beginner's Guide to Automating Your Team's Busywork",
    ),
    "AI automation for customer support": (
        "Automating Support Without Annoying Your Customers",
        "Where AI Should Stop in a Support Workflow",
    ),
}

GAP_DESCRIPTION_HINTS: dict[str, str] = {
    "AI ROI": "Give the reader a concrete formula and a worked example they can copy.",
    "AI implementation costs": "Break down one-time and recurring costs honestly.",
    "AI adoption mistakes": "Use concrete failure stories rather than generic advice.",
    "AI automation security": "End with a checklist the team can run this week.",
    "AI automation change management": "Include what the rollout calendar should look like.",
    "AI automation measurement": "Tie each metric to a business outcome, not a vanity number.",
    "AI regulation update": "State what changed, what it means, what to do Monday.",
    "AI model comparisons": "Publish the test harness so readers can reproduce it.",
    "Prompt engineering at scale": "Include the failure mode for each pattern.",
    "Prompt engineering for developers": "Show real request/response payloads.",
    "MLOps for small teams": "Be specific about the tooling you skipped.",
    "AI data privacy practices": "Offer a copy-paste policy template.",
    "Prompt injection defence": "Show the guardrail and the test that catches bypasses.",
    "Customer onboarding playbooks": "Include the actual sequence and timings.",
    "Beginner AI tutorials": "Ship something working in under 30 minutes.",
    "AI automation for customer support": "Name the exact hand-off points to a human.",
}

REINFORCE_TITLE_TEMPLATES: tuple[str, ...] = (
    "{topic}: The Version We Wish We'd Written First",
    "A Field Guide to {topic}",
    "What 12 Months of {topic} Taught Us",
    "{topic} — Lessons From the Trenches",
    "The Honest Guide to {topic}",
)

GAP_MEMORY_SUMMARY = (
    "Potential content gap: {topic} is {coverage_phrase} in this content history."
)
REINFORCE_MEMORY_SUMMARY = (
    "'{topic}' performs {ratio:.1f}x the account average but has only {count} published item(s)."
)
STALE_MEMORY_SUMMARY = (
    "'{topic}' is one of the strongest performing topics ({ratio:.1f}x average) and has not been "
    "published in {days} days."
)


# ----------------------------------------------------------------------------------
# Opportunities
# ----------------------------------------------------------------------------------
@dataclass
class TopicOpportunity:
    topic: str
    score: float
    kind: str  # gap | reinforce | revive
    reason: str
    evidence: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    formats: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    anchor: str | None = None


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


# ----------------------------------------------------------------------------------
# Strategy context
# ----------------------------------------------------------------------------------
@dataclass
class StrategyContext:
    request: str
    analytics: AnalyticsResponse
    contents: list[Content]
    gaps: GapResponse
    memories: list[MemoryRecord]
    brand: BrandProfileRead | None
    memory_backend: str
    degraded: bool
    insights: list[ContentInsight]
    # Phase 4: validated experiment hints from actual published-post metrics.
    # Empty when the creator has too little performance data — the planner
    # then falls back to its existing behaviour unchanged.
    performance_hints: list[dict] = field(default_factory=list)

    @property
    def has_history(self) -> bool:
        return bool(self.contents)

    @property
    def has_metrics(self) -> bool:
        return self.analytics.published_with_metrics > 0

    def summary(self) -> dict:
        return {
            "content_items": self.analytics.content_count,
            "items_with_metrics": self.analytics.published_with_metrics,
            "topics_covered": self.gaps.topics_covered,
            "memories_recalled": len(self.memories),
            "memory_backend": self.memory_backend,
            "gaps_detected": len(self.gaps.gaps),
            "avg_engagement_rate": round(self.analytics.avg_engagement_rate, 5),
            "top_platform": self.analytics.top_platform.key if self.analytics.top_platform else None,
            "top_topic": self.analytics.top_topic.key if self.analytics.top_topic else None,
            "brand": self.brand.brand_name if self.brand else None,
            "sufficient_data": self.analytics.content_count >= 10,
        }


def get_brand(db: Session, user_id: int) -> BrandProfileRead | None:
    row = db.scalar(select(BrandProfile).where(
        BrandProfile.user_id == user_id, 
        BrandProfile.is_active.is_(True)
    ).limit(1))
    return BrandProfileRead.model_validate(row) if row else None



def build_strategy_context(
    db: Session,
    request: str,
    user_id: int,
    *,
    recall_aspects: list[str] | None = None,
) -> StrategyContext:
    contents = all_contents(db, user_id=user_id)
    analytics = build_analytics(contents)
    # A generous gap list gives the planner enough distinct opportunities to fill
    # a full week without repeating a topic.
    gaps = detect_gaps(analytics, contents, limit=10)

    memory = MemoryService(db)
    recall = memory.get_relevant_memories(
        request or "what to publish next",
        user_id=user_id,
        aspects=recall_aspects
        or [
            "what to publish next",
            "historical performance patterns",
            "topics that worked",
            "content gaps not yet covered",
            "brand voice and tone",
            "audience engagement patterns",
        ],
    )

    insights = list(
        db.scalars(select(ContentInsight).where(ContentInsight.user_id == user_id).order_by(ContentInsight.confidence.desc(), ContentInsight.id.desc()).limit(120))
    )

    # Phase 4: pull validated experiment hints from actual published-post
    # metrics. Guarded so a failure here can never break plan generation.
    performance_hints: list[dict] = []
    try:
        from .insight_service import validated_experiment_hints

        performance_hints = validated_experiment_hints(db, user_id)
    except Exception:  # noqa: BLE001 - planner must degrade, not 500
        logger.warning("Performance insight hints unavailable for planner", exc_info=True)

    return StrategyContext(
        request=request,
        analytics=analytics,
        contents=contents,
        gaps=gaps,
        memories=recall.memories,
        brand=get_brand(db, user_id=user_id),
        memory_backend=recall.backend,
        degraded=recall.degraded,
        insights=insights,
        performance_hints=performance_hints,
    )



def render_context_for_llm(ctx: StrategyContext, request: PlanRequest | None = None) -> str:
    a = ctx.analytics
    lines: list[str] = []

    lines.append("=== MEMORY (long-term knowledge recalled from Hindsight) ===")
    if ctx.memories:
        for m in ctx.memories:
            lines.append(f"- [{m.kind}] {m.text}")
    else:
        lines.append("- (no memories available yet)")

    lines.append("\n=== STRUCTURED PERFORMANCE DATA (relational database) ===")
    lines.append(f"content_items: {a.content_count}")
    lines.append(f"items_with_metrics: {a.published_with_metrics}")
    lines.append(
        f"date_range: {a.date_range.get('start')} → {a.date_range.get('end')}"
    )
    lines.append(f"avg_engagement_rate: {_pct(a.avg_engagement_rate)}")
    lines.append(f"median_engagement_rate: {_pct(a.median_engagement_rate)}")
    lines.append(f"avg_ctr: {_pct(a.avg_ctr)}")
    lines.append(f"total_impressions: {a.total_impressions:,}")

    lines.append("\n-- performance by platform --")
    for s in a.by_platform[:6]:
        lines.append(f"  {s.key}: n={s.count} avg_er={_pct(s.avg_engagement_rate)} index={s.index_vs_average}x")
    lines.append("\n-- performance by topic --")
    for s in a.by_topic[:12]:
        lines.append(f"  {s.key}: n={s.count} avg_er={_pct(s.avg_engagement_rate)} index={s.index_vs_average}x")
    lines.append("\n-- performance by format --")
    for s in a.by_content_type[:8]:
        lines.append(f"  {s.key}: n={s.count} avg_er={_pct(s.avg_engagement_rate)} index={s.index_vs_average}x")
    lines.append("\n-- performance by audience --")
    for s in a.by_audience[:6]:
        lines.append(f"  {s.key}: n={s.count} avg_er={_pct(s.avg_engagement_rate)} index={s.index_vs_average}x")

    lines.append("\n-- topic coverage / recency --")
    for c in a.topic_coverage[:14]:
        lines.append(f"  {c.topic}: n={c.count} last_published_days_ago={c.days_since_published} index={c.performance_index}x")

    lines.append("\n=== CONTENT GAPS (detected from structured data) ===")
    if ctx.gaps.gaps:
        for g in ctx.gaps.gaps:
            lines.append(f"  [{g.priority}] {g.topic} (score={g.score}) — {g.reason}")
            for e in g.evidence:
                lines.append(f"      · {e}")
    else:
        lines.append("  (none detected)")

    if ctx.performance_hints:
        lines.append("\n=== VALIDATED PERFORMANCE EXPERIMENTS (from published-post metrics) ===")
        lines.append("Use these as evidence-backed experiments. They are associations in the")
        lines.append("creator's own data, not guarantees. If insufficient data, recommend a test.")
        for h in ctx.performance_hints:
            lines.append(
                f"  - {h.get('finding', '')} (n={h.get('posts_analyzed', 0)}, "
                f"confidence={h.get('confidence', 'weak')})"
            )
            if h.get("recommendation"):
                lines.append(f"    experiment: {h['recommendation']}")
            if h.get("limitation"):
                lines.append(f"    limitation: {h['limitation']}")

    lines.append("\n=== BRAND ===")
    if ctx.brand:
        lines.append(f"brand_name: {ctx.brand.brand_name}")
        lines.append(f"target_audience: {ctx.brand.target_audience or '(not set)'}")
        lines.append(f"tone: {ctx.brand.tone or '(not set)'}")
        lines.append(f"preferred_formats: {', '.join(ctx.brand.preferred_formats) or '(not set)'}")
        lines.append(f"preferred_platforms: {', '.join(ctx.brand.preferred_platforms) or '(not set)'}")
    else:
        lines.append("(no brand profile configured)")

    lines.append("\n=== RECENT CONTENT (avoid repeating) ===")
    recent = sorted(
        [c for c in ctx.contents if c.published_at],
        key=lambda c: c.published_at,
        reverse=True,
    )[:12]
    for c in recent:
        lines.append(f"  - {c.published_at.date()} | {c.platform} | {c.topic} | {c.title}")

    if request:
        lines.append("\n=== REQUEST ===")
        lines.append(f"days: {request.days}")
        lines.append(f"posts_per_day: {request.posts_per_day}")
        lines.append(f"platforms: {', '.join(request.platforms) or 'choose the strongest'}")
        lines.append(f"campaign: {request.campaign or '(none)'}")
        lines.append(f"notes: {request.notes or '(none)'}")

    if a.warnings:
        lines.append("\n=== DATA CAVEATS ===")
        for w in a.warnings:
            lines.append(f"  - {w}")

    return "\n".join(lines)


# ----------------------------------------------------------------------------------
# Opportunity building
# ----------------------------------------------------------------------------------
def build_opportunities(ctx: StrategyContext, limit: int = 18) -> list[TopicOpportunity]:
    opportunities: list[TopicOpportunity] = []
    seen: set[str] = set()
    a = ctx.analytics
    avg = a.avg_engagement_rate

    # 1) Gaps
    for gap in ctx.gaps.gaps:
        if gap.topic.lower() in seen:
            continue
        anchor = gap.adjacency[0] if gap.adjacency else None
        anchor_stat = next((s for s in a.by_topic if s.key == anchor), None)
        coverage_phrase = (
            "not covered at all"
            if gap.coverage_count == 0
            else f"covered by only {gap.coverage_count} item(s)"
        )
        bits = [f"'{gap.topic}' is {coverage_phrase} in your content history."]
        if anchor_stat and anchor_stat.count:
            bits.append(
                f"The adjacent topic '{anchor}' has historically run at "
                f"{anchor_stat.index_vs_average:.1f}x your average engagement across "
                f"{anchor_stat.count} item(s)."
            )
        if ctx.brand and ctx.brand.tone:
            bits.append(f"Write it in a {ctx.brand.tone.split(',')[0].strip()} voice.")
        opportunities.append(
            TopicOpportunity(
                topic=gap.topic,
                score=gap.score,
                kind="gap",
                reason=" ".join(bits),
                evidence=list(gap.evidence),
                memory_refs=[GAP_MEMORY_SUMMARY.format(topic=gap.topic, coverage_phrase=coverage_phrase)],
                formats=list(gap.suggested_formats),
                title=_gap_title(gap.topic, idx=len([o for o in opportunities if o.kind == "gap"])),
                description=GAP_DESCRIPTION_HINTS.get(gap.topic, "Ground it in a concrete example from your own experience."),
                anchor=anchor,
            )
        )
        seen.add(gap.topic.lower())

    # 2) Under-covered winners — the strongest form of memory-driven advice
    for stat in a.by_topic:
        if stat.key.lower() in seen:
            continue
        if stat.count > 2 or stat.index_vs_average < 1.2 or not stat.count:
            continue
        coverage = next((c for c in a.topic_coverage if c.topic == stat.key), None)
        bits = [
            f"'{stat.key}' is your {stat.index_vs_average:.1f}x-average topic but you have only "
            f"published {stat.count} item(s) about it."
        ]
        if coverage and coverage.days_since_published is not None:
            bits.append(f"It was last covered {coverage.days_since_published} days ago.")
        bits.append("Doubling down on your own proven topic usually beats chasing a new one.")
        opportunities.append(
            TopicOpportunity(
                topic=stat.key,
                score=min(0.95, 0.45 + 0.2 * stat.index_vs_average + 0.05 * stat.count),
                kind="reinforce",
                reason=" ".join(bits),
                evidence=[f"{stat.key}: n={stat.count} index={stat.index_vs_average}x avg_er={_pct(stat.avg_engagement_rate)}"],
                memory_refs=[
                    REINFORCE_MEMORY_SUMMARY.format(topic=stat.key, ratio=stat.index_vs_average, count=stat.count)
                ],
                title=_reinforce_title(stat.key, len([o for o in opportunities if o.kind == "reinforce"])),
                description="Lean on the specific example that made this topic work the first time.",
            )
        )
        seen.add(stat.key.lower())

    # 3) Stale winners — a proven topic that has gone quiet
    for cov in a.topic_coverage:
        if cov.topic.lower() in seen or cov.performance_index < 1.25 or not cov.count:
            continue
        if cov.days_since_published is None or cov.days_since_published < 30:
            continue
        opportunities.append(
            TopicOpportunity(
                topic=cov.topic,
                score=min(0.92, 0.5 + 0.18 * cov.performance_index),
                kind="revive",
                reason=(
                    f"'{cov.topic}' is one of your strongest topics at {cov.performance_index:.1f}x "
                    f"average engagement, and it has been {cov.days_since_published} days since you "
                    f"last published on it."
                ),
                evidence=[f"{cov.topic}: n={cov.count} index={cov.performance_index}x last={cov.days_since_published}d ago"],
                memory_refs=[
                    STALE_MEMORY_SUMMARY.format(
                        topic=cov.topic, ratio=cov.performance_index, days=cov.days_since_published
                    )
                ],
                title=_reinforce_title(cov.topic, len([o for o in opportunities if o.kind == "revive"])),
                description="Revisit the theme with whatever has changed since you last covered it.",
            )
        )
        seen.add(cov.topic.lower())

    opportunities.sort(key=lambda o: o.score, reverse=True)
    return opportunities[:limit]


def _gap_title(topic: str, idx: int) -> str:
    templates = GAP_TITLE_TEMPLATES.get(topic)
    if templates:
        return templates[idx % len(templates)]
    return f"{topic}: A Practical Guide for Teams Getting It Right"


def _reinforce_title(topic: str, idx: int) -> str:
    return REINFORCE_TITLE_TEMPLATES[idx % len(REINFORCE_TITLE_TEMPLATES)].format(topic=topic)


# ----------------------------------------------------------------------------------
# Deterministic planner
# ----------------------------------------------------------------------------------
def _platform_rotation(
    ctx: StrategyContext, requested: list[str], count: int
) -> list[str]:
    if requested:
        return [requested[i % len(requested)] for i in range(count)]
    ranked = [s.key for s in ctx.analytics.by_platform if s.count] or ["LinkedIn"]
    if ctx.brand and ctx.brand.preferred_platforms:
        preferred = [p for p in ctx.brand.preferred_platforms if p]
        ranked = preferred + [p for p in ranked if p not in preferred]
    strong = ranked[:2] if len(ranked) >= 2 else ranked
    return [strong[i % len(strong)] for i in range(count)]


def _format_for(platform: str, opportunities: list[TopicOpportunity], idx: int) -> str:
    affinity = PLATFORM_FORMAT_AFFINITY.get(platform, ("text post", "carousel", "blog post"))
    if opportunities:
        for offset in range(len(opportunities)):
            candidate = opportunities[(idx + offset) % len(opportunities)]
            for fmt in candidate.formats:
                if fmt in affinity:
                    return fmt
    return affinity[idx % len(affinity)]


def _next_business_day(value: datetime) -> datetime:
    while value.weekday() >= 5:  # skip Saturday and Sunday
        value += timedelta(days=1)
    return value


def _publish_dates(start: datetime, days: int, posts_per_day: int) -> list[datetime]:
    """One date per item, spread over the range, skipping weekends.

    Weekends are skipped rather than shifted, so a 7-day plan never collapses
    two slots onto the same Tuesday.
    """
    dates: list[datetime] = []
    cursor = _next_business_day(start)
    last = start + timedelta(days=max(0, days - 1))

    while len(dates) < days * posts_per_day and cursor <= last + timedelta(days=2):
        for _ in range(posts_per_day):
            if len(dates) >= days * posts_per_day:
                break
            dates.append(cursor)
        cursor = _next_business_day(cursor + timedelta(days=1))
    return dates


def build_plan_deterministically(
    ctx: StrategyContext, request: PlanRequest
) -> tuple[LLMPlan, list[TopicOpportunity]]:
    opportunities = build_opportunities(ctx)
    total = min(get_settings().max_plan_items, max(1, request.days * request.posts_per_day))
    start = _next_business_day(
        request.start_date or (datetime.now(timezone.utc) + timedelta(days=1))
    ).replace(hour=9, minute=0, second=0, microsecond=0)
    schedule = _publish_dates(start, request.days, request.posts_per_day)

    campaign = request.campaign.strip()
    items: list[LLMPlanItem] = []
    used_topics: set[str] = set()
    cursor = 0

    for i in range(total):
        # Walk the opportunity list in priority order, skipping topics already
        # placed. Only wrap around when every opportunity is exhausted, and say
        # so in the reason rather than silently repeating a topic.
        opp: TopicOpportunity | None = None
        is_second_angle = False
        for _ in range(len(opportunities)):
            if cursor >= len(opportunities):
                cursor = 0
                is_second_angle = True
            candidate = opportunities[cursor]
            cursor += 1
            if candidate.topic.lower() not in used_topics:
                opp = candidate
                break
        if opp is None:
            break

        if campaign and i < 2:
            opp = TopicOpportunity(
                topic=campaign,
                score=0.99,
                kind=opp.kind,
                reason=f"Requested campaign focus: '{campaign}'.",
                evidence=opp.evidence,
                memory_refs=opp.memory_refs,
                formats=list(opp.formats),
                title=f"{campaign}: {opp.title}" if not opp.title.startswith(campaign) else opp.title,
                description=opp.description,
            )
        elif is_second_angle:
            opp = TopicOpportunity(
                topic=opp.topic,
                score=opp.score,
                kind=opp.kind,
                reason=f"Every higher-priority topic is already in this plan, so this is a second angle on {opp.topic}. {opp.reason}",
                evidence=opp.evidence,
                memory_refs=opp.memory_refs,
                formats=list(opp.formats),
                title=_reinforce_title(opp.topic, i),
                description=opp.description,
            )
        used_topics.add(opp.topic.lower())

        platform = _platform_rotation(ctx, request.platforms, i + 1)[-1]
        fmt = _format_for(platform, opportunities, i)
        publish_at = schedule[i] if i < len(schedule) else start + timedelta(days=i)

        reason = opp.reason
        if not ctx.has_metrics:
            reason = (
                f"No performance data recorded yet, so this is a best-practice pick rather than a "
                f"learned one. {reason}"
            )

        memory_used = list(opp.memory_refs)
        matched = [
            m.text
            for m in ctx.memories
            if opp.topic.lower() in m.text.lower()
            or (opp.anchor and opp.anchor.lower() in m.text.lower())
        ]
        for text in matched[:2]:
            if text not in memory_used:
                memory_used.append(text)

        items.append(
            LLMPlanItem(
                date=publish_at.date().isoformat(),
                platform=platform,
                topic=opp.topic,
                format=fmt,
                title=opp.title,
                description=opp.description,
                reason=reason,
                memory_used=memory_used[:6],
            )
        )

    a = ctx.analytics
    if ctx.has_history and ctx.has_metrics:
        top_platform = a.top_platform.key if a.top_platform else "your strongest platform"
        top_topic = a.top_topic.key if a.top_topic else "your best topic"
        summary = (
            f"Built from {a.content_count} historical content items, {len(ctx.memories)} recalled "
            f"memories and {len(ctx.gaps.gaps)} detected content gaps. The plan leads with gaps "
            f"adjacent to your proven performers, then reinforces under-covered winners. "
            f"Historically {top_topic} and {top_platform} carry the account "
            f"({_pct(a.avg_engagement_rate)} average engagement)."
        )
        caveats = [
            "Gaps are candidates for testing, not guarantees of performance.",
            "Performance patterns shift; re-run the planner as new results land.",
        ]
    elif ctx.has_history:
        summary = (
            f"Built from {a.content_count} content items, but no performance metrics have been "
            f"recorded, so format and topic choices follow established practice rather than your "
            f"own data. Add impressions and engagement to make this plan memory-driven."
        )
        caveats = ["No performance metrics recorded — recommendations are generic." ]
    else:
        summary = (
            "No content history is available yet, so this plan is a best-practice starting point. "
            "Add your past content and ContentMind will replace these generic picks with "
            "personalised, memory-backed recommendations."
        )
        caveats = ["No historical content — this plan is not personalised."]

    plan = LLMPlan(
        title=request.title or f"{request.days}-day content plan (memory-driven)",
        strategy_summary=summary,
        items=items or [
            LLMPlanItem(
                date=start.date().isoformat(),
                platform=(request.platforms or ["LinkedIn"])[0],
                topic="Getting started with AI",
                format="text post",
                title="Start Here: What We Are Building and Why",
                description="A short introduction that sets the voice for everything after it.",
                reason="No content history exists yet, so this is a baseline piece to establish voice and measure a first engagement baseline.",
            )
        ],
        caveats=caveats,
    )
    return plan, opportunities


# ----------------------------------------------------------------------------------
# LLM prompts
# ----------------------------------------------------------------------------------
PLAN_SYSTEM = """You are ContentMind's strategy agent. You plan content for a marketing team.

You are given:
  1. MEMORY — durable strategic knowledge recalled from Hindsight (the team's own history).
  2. STRUCTURED PERFORMANCE DATA — measured metrics from the database.
  3. CONTENT GAPS — under-covered subjects adjacent to proven topics.
  4. BRAND — voice, audience, preferred platforms and formats.
  5. RECENT CONTENT — so you do not repeat yourself.

Hard requirements:
- EVERY item must have a `reason` that cites specific evidence: a number, a memory, or a gap.
  Never write a bare recommendation like "post about AI".
- NEVER claim certainty about future performance. Use "likely to", "worth testing", "because
  similar content has historically...".
- Respect the brand voice. Do not invent facts that are not in the evidence.
- Do not repeat a topic already used elsewhere in this plan unless the reason explicitly justifies it.
- `memory_used` must contain short verbatim quotes or paraphrases of the memories that drove the item.
  If no memory applies, leave it empty rather than inventing one.
- Return only JSON matching the schema.
"""


def _plan_user_prompt(ctx: StrategyContext, request: PlanRequest) -> str:
    total = min(get_settings().max_plan_items, request.days * request.posts_per_day)
    return f"""Plan exactly {total} content items across {request.days} day(s), starting
{request.start_date.date().isoformat() if request.start_date else 'tomorrow'},
{request.posts_per_day} per day.

{render_context_for_llm(ctx, request)}

Return JSON: {{"title": str, "strategy_summary": str, "items": [{{"date": "YYYY-MM-DD",
"platform": str, "topic": str, "format": str, "title": str, "description": str, "reason": str,
"memory_used": [str]}}], "caveats": [str]}}
Use only platforms available in the evidence. Spread items across the days in the range.
"""


# ----------------------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------------------
def persist_plan(db: Session, draft: LLMPlan, ctx: StrategyContext, request: PlanRequest, user_id: int) -> ContentPlan:
    start = request.start_date or (datetime.now(timezone.utc) + timedelta(days=1))
    item_dates: list[datetime] = []
    for item in draft.items:
        try:
            parsed = datetime.fromisoformat(item.date)
        except (ValueError, TypeError):
            parsed = start
        item_dates.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc))

    if item_dates:
        first, last = min(item_dates), max(item_dates)
        date_range = f"{first.date().isoformat()} �+' {last.date().isoformat()}"
    else:
        end = start + timedelta(days=request.days - 1)
        date_range = f"{start.date().isoformat()} �+' {end.date().isoformat()}"

    plan = ContentPlan(
        user_id=user_id,
        title=draft.title,
        date_range=date_range,
        strategy_summary=draft.strategy_summary,
        request=request.model_dump_json(),
        memory_count=len(ctx.memories),
        content_analyzed=ctx.analytics.content_count,
        gaps_considered=[g.model_dump() for g in ctx.gaps.gaps],
        used_memory=bool(ctx.memories),
        used_historical=ctx.has_history,
        memory_backend=ctx.memory_backend,
        degraded=ctx.degraded,
        warnings=list(draft.caveats) + list(ctx.analytics.warnings),
    )
    db.add(plan)
    db.flush()

    for position, item in enumerate(draft.items):
        published = item_dates[position] if position < len(item_dates) else start
        db.add(
            ContentPlanItem(
                plan_id=plan.id,
                position=position,
                date=published,
                platform=item.platform,
                topic=item.topic,
                format=item.format,
                title=item.title,
                description=item.description,
                reason=item.reason,
                memory_used=list(item.memory_used),
            )
        )
    db.flush()
    return plan



def plan_to_read(plan: ContentPlan) -> PlanRead:
    return PlanRead.model_validate(plan)


# ----------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------
def generate_plan_for_user(db: Session, request: PlanRequest, user_id: int) -> PlanGenerateResponse:
    ctx = build_strategy_context(db, f"{request.days}-day plan: {request.campaign or 'full content calendar'}", user_id=user_id)

    llm = get_llm_service()
    fallback_plan, opportunities = build_plan_deterministically(ctx, request)

    result, note = llm.generate_json(
        LLMPlan,
        system=PLAN_SYSTEM,
        user=_plan_user_prompt(ctx, request),
        fallback=lambda: fallback_plan.model_dump(),
        temperature=0.4,
    )

    draft = result if result and result.items else fallback_plan
    if result and len(result.items) > len(fallback_plan.items):
        draft = result

    normalised = _normalise_items(draft, fallback_plan, request)
    # Phase 4: surface validated experiment hints as plan caveats so the
    # persisted plan explains *why* a direction is recommended. Additive and
    # capped so existing plans keep their shape.
    hint_caveats = [
        f"Experiment (from your published metrics, n={h.get('posts_analyzed', 0)}, "
        f"{h.get('confidence', 'weak')} confidence): {h.get('recommendation') or h.get('finding', '')}"
        for h in ctx.performance_hints[:2]
    ]
    draft = LLMPlan(
        title=draft.title,
        strategy_summary=draft.strategy_summary,
        items=normalised,
        caveats=list(dict.fromkeys(list(draft.caveats) + hint_caveats + list(fallback_plan.caveats)))[:8],
    )

    plan_row = persist_plan(db, draft, ctx, request, user_id=user_id)
    db.commit()

    memory = MemoryService(db)
    memory.remember(
        [
            _statement_from(f"strategy:{plan_row.id}:summary", draft.strategy_summary, "strategy", "Content strategy learning"),
            *[
                _statement_from(
                    f"strategy:{plan_row.id}:item:{i}",
                    f"Recommended {item.platform} {item.format} about {item.topic}: '{item.title}'. {item.reason}",
                    "strategy",
                    "Content strategy learning",
                )
                for i, item in enumerate(draft.items[:12])
            ],
        ],
        document_id=f"plan-{plan_row.id}",
        user_id=user_id,
    )
    db.commit()

    return PlanGenerateResponse(
        plan=plan_to_read(plan_row),
        memory_used=ctx.memories,
        gaps=ctx.gaps.gaps,
        context_summary={
            **ctx.summary(),
            "llm_note": note,
            "llm_available": llm.available,
            "opportunities": [
                {"topic": o.topic, "kind": o.kind, "score": o.score} for o in opportunities[:8]
            ],
        },
        explanation=draft.strategy_summary,
    )



def _statement_from(key: str, text: str, kind: str, context: str):
    from ..schemas import MemoryStatement

    return MemoryStatement(text=text, kind=kind, context=context)


def _normalise_items(draft: LLMPlan, fallback: LLMPlan, request: PlanRequest) -> list[LLMPlanItem]:
    """Guarantee a usable plan: enough items, valid dates, no empty reasons."""
    expected = min(get_settings().max_plan_items, max(1, request.days * request.posts_per_day))
    items = list(draft.items)

    for idx, item in enumerate(items):
        if not item.reason or len(item.reason.strip()) < 10:
            item.reason = fallback.items[idx % len(fallback.items)].reason
        if not item.title or len(item.title.strip()) < 3:
            item.title = fallback.items[idx % len(fallback.items)].title
        try:
            datetime.fromisoformat(item.date)
        except (ValueError, TypeError):
            base = request.start_date or (datetime.now(timezone.utc) + timedelta(days=1))
            item.date = (base + timedelta(days=idx // max(1, request.posts_per_day))).date().isoformat()

    if len(items) < expected:
        filler = fallback.items[len(items) :] or fallback.items
        for offset in range(expected - len(items)):
            items.append(filler[offset % len(filler)])
    return items[:expected]


def list_plans(db: Session, user_id: int, limit: int = 20) -> PlanListResponse:
    plans = list(
        db.scalars(
            select(ContentPlan)
            .where(ContentPlan.user_id == user_id)
            .order_by(ContentPlan.created_at.desc())
            .limit(limit)
        )
    )
    return PlanListResponse(items=[plan_to_read(p) for p in plans], total=len(plans))


def get_plan(db: Session, plan_id: int) -> ContentPlan | None:
    return db.get(ContentPlan, plan_id)


# ----------------------------------------------------------------------------------
# Chat / Q&A
# ----------------------------------------------------------------------------------
CHAT_SYSTEM = """You are ContentMind's strategy assistant for a marketing team.

Answer only from the evidence provided. Structure of the answer:
1. Lead with the direct answer.
2. Support it with specific numbers and quoted memories.
3. Close with the single most useful next action.

Rules:
- If the memory or data is thin, say so explicitly and explain what is missing.
- Use hedged language about future performance. Never guarantee results.
- Reference the audience, topics, formats or platforms by name.
- If asked "why did you recommend this", quote the memory and the metric behind it.
- Return only JSON.
"""

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "next": ("post next", "what should i post", "next week", "what to publish", "plan", "schedule", "calendar"),
    "topics": ("topic", "topics worked", "best topic", "subject"),
    "overused": ("overused", "over use", "fatigue", "too much", "repeated", "tired of"),
    "gaps": ("gap", "gaps", "missing", "not covered", "undercovered", "uncovered"),
    "audience": ("audience", "responded", "response", "engage", "engagement"),
    "brand": ("brand voice", "voice", "tone", "how do we sound", "style"),
    "why": ("why did you", "why this", "why recommend", "reason"),
    "learned": ("what did you learn", "learned", "what have you learned", "learn from"),
    "platforms": ("platform", "channel", "linkedin", "blog", "youtube", "instagram", "newsletter"),
    "performance": ("best performing", "worst performing", "performance", "what worked", "what didn't"),
}


def detect_intent(message: str) -> str:
    lowered = (message or "").lower()
    best, best_hits = "general", 0
    for intent, keywords in INTENT_KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in lowered)
        if hits > best_hits:
            best, best_hits = intent, hits
    return best


def answer_question(db: Session, message: str, user_id: int, history: list | None = None) -> ChatResponse:
    intent = detect_intent(message)
    ctx = build_strategy_context(db, message, user_id=user_id)

    llm = get_llm_service()


    def fallback() -> dict:
        response = _deterministic_answer(ctx, message, intent)
        return {
            "answer": response.answer,
            "memories_used": [m.text for m in response.memories_used],
            "confidence": response.confidence,
            "follow_ups": response.follow_ups,
        }

    result, note = llm.generate_json(
        LLMStrategyAnswer,
        system=CHAT_SYSTEM,
        user=f"""QUESTION: {message}

{render_context_for_llm(ctx)}

Return JSON: {{"answer": str, "memories_used": [str], "confidence":
"low"|"medium"|"high", "follow_ups": [str]}}
Quote memories verbatim in memories_used. Do not invent memories that are not listed above.
""",
        fallback=fallback,
        temperature=0.3,
    )

    if result is None:
        answer = _deterministic_answer(ctx, message, intent)
        return _chat_response(answer, ctx, degraded=True, notes=[note])

    answer = ChatResponse(
        answer=result.answer,
        memories_used=_match_memories(result.memories_used, ctx.memories),
        confidence=result.confidence if ctx.has_metrics else "low",
        follow_ups=result.follow_ups,
        content_analyzed=ctx.analytics.content_count,
        memory_count=len(ctx.memories),
        degraded=ctx.degraded or not llm.available,
    )
    return answer


def _chat_response(answer: ChatResponse, ctx: StrategyContext, degraded: bool, notes: list[str]) -> ChatResponse:
    answer.content_analyzed = ctx.analytics.content_count
    answer.memory_count = len(ctx.memories)
    answer.degraded = degraded or ctx.degraded
    if notes and "fallback" in notes[-1]:
        answer.notes.append(
            "No LLM provider is configured, so this answer came from ContentMind's deterministic "
            "strategy engine using the same recalled memory and metrics."
        )
    return answer


def _match_memories(quoted: list[str], available: list[MemoryRecord]) -> list[MemoryRecord]:
    matched: list[MemoryRecord] = []
    seen: set[str] = set()
    for quote in quoted or []:
        for mem in available:
            if mem.id in seen:
                continue
            if quote.strip().lower() in mem.text.lower() or mem.text.lower() in quote.strip().lower():
                seen.add(mem.id)
                matched.append(mem)
                break
    return matched


def _deterministic_answer(ctx: StrategyContext, message: str, intent: str) -> ChatResponse:
    a = ctx.analytics
    warnings: list[str] = []

    if not ctx.has_history:
        return ChatResponse(
            answer=(
                "I don't have any content history for this account yet, so anything I say would be "
                "generic rather than tailored to you.\n\n"
                "**What to do next:** add your past content with its performance numbers "
                "(impressions, likes, comments, shares, clicks). After that I can tell you which "
                "topics and formats actually work for *your* audience, where your gaps are, and "
                "what to publish next — and I will keep learning as new results land."
            ),
            confidence="low",
            follow_ups=[
                "Add my last 20 posts",
                "What data do you need from me?",
                "Show me an example of a personalised plan",
            ],
            degraded=ctx.degraded,
        )

    if not ctx.has_metrics:
        warnings.append(
            "No impressions/engagement recorded, so performance questions can only be answered "
            "from topic coverage and brand memory."
        )

    memories = ctx.memories
    mem_lines = "\n".join(f"- {m.text}" for m in memories[:6]) or "- (none recalled)"

    if intent in {"next", "why"}:
        top_platform = a.top_platform.key if a.top_platform else "your strongest platform"
        top_topic = a.top_topic.key if a.top_topic else "your best topic"
        gap_lines = (
            "\n".join(f"- **{g.topic}** ({g.priority}) — {g.reason}" for g in ctx.gaps.gaps[:4])
            or "- No clear gaps detected from the current history."
        )
        answer = (
            f"Based on **{a.content_count} historical content items** and **{len(memories)} recalled "
            f"memories**, here is where I'd focus.\n\n"
            f"**What the data says:** your average engagement rate is {_pct(a.avg_engagement_rate)}. "
            f"`{top_topic}` and {PLATFORM_LABEL.get(top_platform, top_platform)} are your strongest "
            f"performers right now.\n\n"
            f"**Largest potential gaps:**\n{gap_lines}\n\n"
            f"**Memories driving this:**\n{mem_lines}\n\n"
            f"**Next action:** run *Plan My Content* for the coming week — it will fill the calendar "
            f"using the gaps above and cite the memory behind each slot."
        )
        return ChatResponse(
            answer=answer,
            memories_used=memories[:6],
            confidence="high" if a.published_with_metrics >= 10 else "low",
            follow_ups=["Plan my content for next week", "Why is topic X a gap?", "Show my top formats"],
            notes=warnings,
        )

    if intent == "topics":
        lines = "\n".join(
            f"- **{s.key}** — {s.count} item(s), {_pct(s.avg_engagement_rate)} avg engagement "
            f"({s.index_vs_average:.1f}x average)"
            for s in a.by_topic[:8]
        )
        return ChatResponse(
            answer=f"**Topics ranked by engagement:**\n{lines or '- No topics recorded yet.'}\n\n"
            f"Account average is {_pct(a.avg_engagement_rate)}. Anything above 1.0x is outperforming.",
            memories_used=[m for m in memories if m.kind in {"topic", "performance"}][:6],
            confidence="high" if a.published_with_metrics >= 10 else "medium",
            notes=warnings,
        )

    if intent == "overused":
        lines = "\n".join(
            f"- **{s.key}** — {s.count} item(s) of {a.content_count} total"
            for s in a.by_topic[:4]
            if s.count >= 3
        )
        return ChatResponse(
            answer=(
                f"**Most-covered topics (fatigue risk):**\n{lines or '- No topic dominates yet.'}\n\n"
                f"Across {a.content_count} items you have covered {len({c.topic for c in ctx.contents})} "
                f"distinct topics. Rotating into an uncovered subject is usually the cheapest fix."
            ),
            memories_used=[m for m in memories if "fatigue" in m.text.lower() or "most covered" in m.text.lower()][:4],
            confidence="medium",
            notes=warnings,
        )

    if intent == "gaps":
        lines = "\n".join(
            f"- **{g.topic}** ({g.priority}, score {g.score}) — {g.reason}" for g in ctx.gaps.gaps[:6]
        )
        return ChatResponse(
            answer=(
                f"**Potential content gaps** (candidates, not guarantees):\n"
                f"{lines or '- None detected. Add more content history to sharpen detection.'}\n\n"
                f"Scored on topic frequency, relative engagement of adjacent topics, recency and "
                f"format readiness."
            ),
            memories_used=[m for m in memories if m.kind == "gap" or "gap" in m.text.lower()][:4],
            confidence="medium",
            notes=warnings,
        )

    if intent == "audience":
        lines = "\n".join(
            f"- **{s.key}** — {_pct(s.avg_engagement_rate)} avg engagement across {s.count} item(s) "
            f"({s.index_vs_average:.1f}x average)"
            for s in a.by_audience[:6]
        )
        top = a.top_audience
        lead = (
            f"Your most responsive audience is **{top.key}** at {top.index_vs_average:.1f}x average "
            f"engagement."
            if top and top.index_vs_average > 1
            else "No audience segment is clearly outperforming yet."
        )
        return ChatResponse(
            answer=f"{lead}\n\n**By audience:**\n{lines or '- No audience data recorded yet.'}\n\n"
            f"**Memories:**\n{mem_lines}",
            memories_used=[m for m in memories if m.kind == "audience"][:6] or memories[:4],
            confidence="high" if a.published_with_metrics >= 10 else "low",
            notes=warnings,
        )

    if intent == "brand":
        brand = ctx.brand
        brand_mem = [m for m in memories if m.kind == "brand"]
        return ChatResponse(
            answer=(
                f"**Your brand voice**\n\n"
                f"- Tone: {brand.tone if brand and brand.tone else 'not explicitly configured — inferred from history'}\n"
                f"- Audience: {brand.target_audience if brand and brand.target_audience else 'not configured'}\n"
                f"- Preferred formats: {', '.join(brand.preferred_formats) if brand and brand.preferred_formats else 'not configured'}\n"
                f"- Preferred platforms: {', '.join(brand.preferred_platforms) if brand and brand.preferred_platforms else 'not configured'}\n\n"
                f"**What I've remembered about your voice:**\n"
                f"{chr(10).join('- ' + m.text for m in brand_mem) or '- No explicit brand memories yet.'}"
            ),
            memories_used=brand_mem or memories[:4],
            confidence="high" if brand_mem else "low",
            notes=warnings,
        )

    if intent == "learned":
        lines = "\n".join(f"- {m.text}" for m in memories[:10]) or "- Nothing learned yet."
        return ChatResponse(
            answer=(
                f"**What I've learned from your content** ({len(memories)} memories recalled, "
                f"{a.content_count} items analysed):\n{lines}\n\n"
                f"Each of these came from measuring a published item, comparing it to your "
                f"account average of {_pct(a.avg_engagement_rate)}, and keeping the comparison."
            ),
            memories_used=memories[:10],
            confidence="high",
            notes=warnings,
        )

    if intent == "platforms":
        lines = "\n".join(
            f"- **{s.key}** — {s.index_vs_average:.1f}x average engagement, {s.count} item(s)"
            for s in a.by_platform[:6]
        )
        return ChatResponse(
            answer=f"**Platform performance:**\n{lines or '- No platform data yet.'}",
            memories_used=[m for m in memories if "platform" in m.text.lower()][:6] or memories[:4],
            confidence="medium",
            notes=warnings,
        )

    if intent == "performance":
        best = "\n".join(
            f"- **{c.title}** — {_pct(c.engagement_rate)} across {c.impressions:,} impressions"
            for c in a.best_content[:5]
        )
        worst = "\n".join(
            f"- **{c.title}** — {_pct(c.engagement_rate)} across {c.impressions:,} impressions"
            for c in a.worst_content[:5]
        )
        return ChatResponse(
            answer=(
                f"**Best performing:**\n{best or '- No metrics yet.'}\n\n"
                f"**Weakest performing:**\n{worst or '- No metrics yet.'}\n\n"
                f"Account average engagement rate: {_pct(a.avg_engagement_rate)}."
            ),
            memories_used=[m for m in memories if m.kind == "performance"][:6] or memories[:4],
            confidence="high" if a.published_with_metrics >= 10 else "low",
            notes=warnings,
        )

    top_topic = a.top_topic
    top_platform = a.top_platform
    summary_bits = []
    if top_topic:
        summary_bits.append(f"**Top topic:** {top_topic.key} ({top_topic.index_vs_average:.1f}x average)")
    if top_platform:
        summary_bits.append(
            f"**Top platform:** {top_platform.key} ({top_platform.index_vs_average:.1f}x average)"
        )
    if ctx.gaps.gaps:
        summary_bits.append(f"**Largest gap:** {ctx.gaps.gaps[0].topic}")
    return ChatResponse(
        answer=(
            f"Here's where you stand, based on **{a.content_count} content items** and "
            f"**{len(memories)} memories**.\n\n"
            + "\n".join(f"- {b}" for b in summary_bits)
            + f"\n\n**Memories I recalled:**\n{mem_lines}\n\n"
            f"Ask me about specific topics, gaps, audiences or why I recommend something."
        ),
        memories_used=memories[:6],
        confidence="high" if a.published_with_metrics >= 10 else "medium",
        notes=warnings,
    )


# ----------------------------------------------------------------------------------
# Brand
# ----------------------------------------------------------------------------------
BRAND_SYSTEM = """You infer a brand profile from a company's published content and remembered
performance. Be conservative: state only what the evidence supports, and keep each field short."""


def learn_brand_profile(db: Session, brand_name: str, user_id: int) -> BrandProfileRead | None:
    ctx = build_strategy_context(db, "brand voice, tone, formats and platforms", user_id=user_id)
    if not ctx.has_history:
        return None


    from ..schemas import LLMBrandRead

    def fallback() -> dict:
        a = ctx.analytics
        return {
            "target_audience": (a.top_audience.key if a.top_audience and a.top_audience.count else "not enough audience data yet"),
            "tone": _infer_tone(ctx),
            "preferred_formats": [s.key for s in a.by_content_type[:3] if s.index_vs_average >= 1.0],
            "preferred_platforms": [s.key for s in a.by_platform[:3] if s.index_vs_average >= 1.0],
            "memories": [],
        }

    result, _note = get_llm_service().generate_json(
        LLMBrandRead,
        system=BRAND_SYSTEM,
        user=f"""Brand name: {brand_name}

{render_context_for_llm(ctx)}

Return JSON: {{"target_audience": str, "tone": str, "preferred_formats": [str],
"preferred_platforms": [str], "memories": [{{"text": str, "kind": "brand", "context": "Brand voice and positioning"}}]}}
""",
        fallback=fallback,
        temperature=0.2,
    )
    if result is None:
        return None

    existing = db.scalar(select(BrandProfile).where(
        BrandProfile.user_id == user_id, 
        BrandProfile.is_active.is_(True)
    ).limit(1))
    if existing is None:
        existing = BrandProfile(brand_name=brand_name, user_id=user_id)
        db.add(existing)

    existing.brand_name = brand_name or existing.brand_name
    if result.target_audience:
        existing.target_audience = result.target_audience
    if result.tone:
        existing.tone = result.tone
    if result.preferred_formats:
        existing.preferred_formats = result.preferred_formats
    if result.preferred_platforms:
        existing.preferred_platforms = result.preferred_platforms
    existing.is_active = True
    db.flush()

    if result.memories:
        MemoryService(db).remember(result.memories, document_id=f"brand-{existing.id}", user_id=user_id)
    return BrandProfileRead.model_validate(existing)


def _infer_tone(ctx: StrategyContext) -> str:
    winners = [s.key.lower() for s in ctx.analytics.by_content_type[:3] if s.index_vs_average >= 1.1]
    if any("tutorial" in w or "how-to" in w or "guide" in w for w in winners):
        return "educational, practical and implementation-focused"
    if any("case" in w or "customer" in w for w in winners):
        return "evidence-led and outcome-focused"
    if any("thought" in w for w in winners):
        return "considered and authoritative"
    return "concise and professional"
