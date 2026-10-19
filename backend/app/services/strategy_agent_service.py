"""Phase 5 — Content Strategy Agent.

Deterministic evidence aggregation and recommendation generation. The LLM is
never required: every number shown to the creator comes from their own stored
records (Phase 4 performance + insights, ContentDNA, ContentReview, plans,
memory). Generated explanations may use an LLM when configured, but the
selection of evidence, confidence labels and sample sizes is computed here,
from actual data only.

Rules enforced throughout:
* every query is scoped to user_id;
* each evidence source is gathered independently — one failing source (memory
  provider down, no performance data, etc.) never breaks generation and is
  reported in `evidence_sources` / `warnings`;
* empty performance data is never presented as evidence of what works;
* recommendations are either evidence-backed (`is_hypothesis=False`, carrying
  sample_size/observation_period) or explicit hypotheses (`is_hypothesis=True`)
  with a learning-oriented test method — never a guarantee of reach/views.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    BrandProfile,
    Content,
    ContentPlan,
    ContentReview,
    Experiment,
    MediaAsset,
    StrategyProfile,
    StrategyRecommendation,
)
from ..schemas import (
    ExperimentCreate,
    ExperimentUpdate,
    FeedbackRequest,
    LessonRead,
    LessonsResponse,
    MemoryStatement,
    RecommendationRead,
    StrategyGenerateRequest,
    StrategyGenerateResponse,
    StrategyProfileRead,
    StrategyProfileUpsert,
)
from .insight_service import build_insight_report
from .memory_service import MemoryService
from .performance_service import _latest_snapshots

logger = logging.getLogger("contentmind.strategy_agent")

GOAL_FORMAT_HINTS: dict[str, tuple[str, ...]] = {
    "education": ("tutorial", "how-to", "checklist", "explainer"),
    "awareness": ("short post", "carousel", "reel", "opinion post"),
    "community": ("question post", "poll", "discussion prompt", "case study"),
    "leads": ("case study", "lead magnet promo", "demo walkthrough", "webinar"),
    "conversion": ("customer story", "comparison post", "product walkthrough", "FAQ"),
}

MAX_RECOMMENDATIONS = 14


# ----------------------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------------------
def get_profile(db: Session, user_id: int) -> StrategyProfile | None:
    return db.scalar(
        select(StrategyProfile).where(StrategyProfile.user_id == user_id, StrategyProfile.is_active.is_(True))
    )


def upsert_profile(db: Session, user_id: int, payload: StrategyProfileUpsert) -> StrategyProfile:
    profile = get_profile(db, user_id)
    if profile is None:
        profile = StrategyProfile(user_id=user_id)
        db.add(profile)
    profile.niche = payload.niche.strip()
    profile.topics = [t.strip() for t in payload.topics if t.strip()]
    profile.target_audience = payload.target_audience.strip()
    profile.audience_needs = payload.audience_needs.strip()
    profile.goals = payload.goals
    profile.content_pillars = [p.strip() for p in payload.content_pillars if p.strip()]
    profile.avoid_topics = [t.strip() for t in payload.avoid_topics if t.strip()]
    profile.publishing_frequency = payload.publishing_frequency.strip()
    profile.constraints = payload.constraints.strip()
    db.commit()
    db.refresh(profile)
    return profile


def _profile_read(profile: StrategyProfile) -> StrategyProfileRead:
    return StrategyProfileRead.model_validate(profile)


# ----------------------------------------------------------------------------------
# Evidence aggregation (each source independent; failures degrade, never raise)
# ----------------------------------------------------------------------------------
class StrategyEvidence:
    """Tenant-scoped snapshot of everything the generator may cite."""

    def __init__(self) -> None:
        self.profile: StrategyProfile | None = None
        self.brand: BrandProfile | None = None
        self.contents: list[Content] = []
        self.recent_reviews: list[ContentReview] = []
        self.dna_topics: list[str] = []
        self.published_posts: int = 0
        self.posts_with_metrics: int = 0
        self.insight_report: Any = None  # InsightReportResponse | None
        self.validated_hints: list[dict] = []
        self.memories: list[Any] = []
        self.recent_plan_titles: list[str] = []
        self.feedback_preferences: list[str] = []
        self.sources: dict[str, bool] = {}  # source name -> available
        self.warnings: list[str] = []
        self.memory_degraded: bool = False

    @property
    def has_performance(self) -> bool:
        return self.posts_with_metrics > 0


def gather_evidence(db: Session, user_id: int) -> StrategyEvidence:
    ev = StrategyEvidence()

    # 1. Strategy profile + brand voice
    try:
        ev.profile = get_profile(db, user_id)
        ev.sources["strategy_profile"] = ev.profile is not None
        if ev.profile is not None:
            ev.feedback_preferences = list(ev.profile.feedback_preferences or [])
    except Exception:  # noqa: BLE001
        ev.sources["strategy_profile"] = False
        ev.warnings.append("Strategy profile unavailable; recommendations use portfolio data only.")

    try:
        ev.brand = db.scalar(
            select(BrandProfile).where(BrandProfile.user_id == user_id, BrandProfile.is_active.is_(True))
        )
        ev.sources["brand"] = ev.brand is not None
    except Exception:  # noqa: BLE001
        ev.sources["brand"] = False

    # 2. Content + plan history
    try:
        ev.contents = list(db.scalars(select(Content).where(Content.user_id == user_id).limit(500)))
        ev.sources["content"] = True
    except Exception:  # noqa: BLE001
        ev.sources["content"] = False
        ev.warnings.append("Content history unavailable.")

    try:
        plans = list(
            db.scalars(
                select(ContentPlan).where(ContentPlan.user_id == user_id).order_by(ContentPlan.id.desc()).limit(20)
            )
        )
        ev.recent_plan_titles = [p.title for p in plans]
        ev.sources["plans"] = True
    except Exception:  # noqa: BLE001
        ev.sources["plans"] = False

    # 3. Pre-publish reviews (latest 50) — evidence for quality patterns
    try:
        ev.recent_reviews = list(
            db.scalars(
                select(ContentReview)
                .where(ContentReview.user_id == user_id)
                .order_by(ContentReview.created_at.desc())
                .limit(50)
            )
        )
        ev.sources["reviews"] = True
    except Exception:  # noqa: BLE001
        ev.sources["reviews"] = False

    # 4. Content DNA topics (what media analysis found)
    try:
        assets = list(
            db.scalars(select(MediaAsset).where(MediaAsset.user_id == user_id).limit(100))
        )
        ev.dna_topics = [a.filename for a in assets if a.dna and a.dna.transcript]
        ev.sources["content_dna"] = bool(ev.dna_topics)
    except Exception:  # noqa: BLE001
        ev.sources["content_dna"] = False

    # 5. Phase 4 performance + insights (the strongest evidence class)
    try:
        pairs = _latest_snapshots(db, user_id, start=None, end=None)
        ev.published_posts = len({p.id for p, _ in pairs})
        ev.posts_with_metrics = sum(
            1 for _, s in pairs
            if any(v is not None for v in (s.views, s.impressions, s.likes, s.comments, s.shares))
        )
        ev.insight_report = build_insight_report(db, user_id)
        ev.validated_hints = [
            i.model_dump() for i in ev.insight_report.insights if i.status == "ok"
        ]
        ev.sources["performance"] = True
        if not ev.has_performance:
            ev.warnings.append(
                "No recorded post metrics yet — recommendations are learning-oriented "
                "hypotheses, not findings."
            )
    except Exception:  # noqa: BLE001
        ev.sources["performance"] = False
        ev.warnings.append("Performance data unavailable; treating all recommendations as hypotheses.")

    # 6. Memory (failure must never break generation)
    try:
        memory = MemoryService(db)
        recall = memory.get_relevant_memories(
            "content strategy lessons topics that worked audience preferences",
            user_id=user_id,
            aspects=["content strategy lessons", "topics that worked", "audience preferences"],
        )
        ev.memories = recall.memories
        ev.memory_degraded = recall.degraded
        ev.sources["memory"] = bool(ev.memories)
    except Exception:  # noqa: BLE001
        ev.sources["memory"] = False
        ev.memory_degraded = True
        ev.warnings.append("Memory provider unavailable; strategy uses relational data only.")

    return ev


# ----------------------------------------------------------------------------------
# Deterministic recommendation generation
# ----------------------------------------------------------------------------------
def _profile_topics(ev: StrategyEvidence) -> list[str]:
    if ev.profile is None:
        return []
    return list(dict.fromkeys([*(ev.profile.content_pillars or []), *(ev.profile.topics or [])]))


def _avoid_set(ev: StrategyEvidence) -> set[str]:
    return {t.strip().lower() for t in (ev.profile.avoid_topics or []) if t.strip()} if ev.profile else set()


def _platforms_for(ev: StrategyEvidence, request: StrategyGenerateRequest) -> list[str]:
    if request.platforms:
        return request.platforms
    if ev.brand and ev.brand.preferred_platforms:
        return list(ev.brand.preferred_platforms)[:4]
    platforms = {c.platform for c in ev.contents}
    return sorted(platforms)[:4] or ["LinkedIn"]


def _formats_for(ev: StrategyEvidence, goal: str) -> list[str]:
    hints = list(GOAL_FORMAT_HINTS.get(goal, GOAL_FORMAT_HINTS["education"]))
    if ev.brand and ev.brand.preferred_formats:
        merged = [f for f in ev.brand.preferred_formats if f] + hints
        return list(dict.fromkeys(merged))[:4]
    return hints


def _insight_for_topic(ev: StrategyEvidence, topic: str) -> dict | None:
    if ev.insight_report is None:
        return None
    for insight in ev.insight_report.insights:
        if insight.status != "ok":
            continue
        if topic.lower() in insight.finding.lower():
            return insight.model_dump()
    return None


def _hint_as_recommendation(hint: dict, ev: StrategyEvidence, seq: int, platform: str, goal: str) -> StrategyRecommendation:
    """A Phase-4 validated hint becomes an evidence-backed recommendation."""
    formats = _formats_for(ev, goal)
    return StrategyRecommendation(
        user_id=0,  # set by caller
        sequence_day=seq,
        pillar=hint.get("key", "").replace("_", " ").title(),
        topic=_first_topic_from_hint(hint) or (ev.profile.niche if ev.profile else "General"),
        format=formats[seq % len(formats)],
        platform=platform,
        working_title=hint.get("recommendation", "")[:200] or f"Double down on {_first_topic_from_hint(hint) or 'your top topic'}",
        hook="",
        audience=(ev.profile.target_audience[:280] if ev.profile and ev.profile.target_audience else ""),
        objective=goal,
        cta="",
        production_notes="",
        is_hypothesis=False,
        reason=hint.get("finding", ""),
        evidence=[
            f"{(e.get('title') or e.get('note') or 'post')} ({e.get('platform', '')})"
            for e in hint.get("evidence", [])
            if isinstance(e, dict)
        ][:5],
        sample_size=int(hint.get("posts_analyzed") or 0) or None,
        observation_period=hint.get("observation_period", ""),
        confidence=hint.get("confidence", "weak"),
        success_metric=hint.get("metric", "engagement_rate_per_view"),
        test_method=hint.get("recommendation", ""),
    )


def _first_topic_from_hint(hint: dict) -> str:
    for e in hint.get("evidence", []):
        note = e.get("note", "") if isinstance(e, dict) else getattr(e, "note", "")
        if "topic=" in note:
            return note.split("topic=", 1)[1].split(",")[0].strip()
    finding = hint.get("finding", "")
    if "'" in finding:
        return finding.split("'", 2)[1]
    return ""


def _hypothesis_recommendation(
    topic: str, ev: StrategyEvidence, seq: int, platform: str, goal: str
) -> StrategyRecommendation:
    """An explicit hypothesis — used when there is no supporting performance data."""
    formats = _formats_for(ev, goal)
    pillars = _profile_topics(ev)
    pillar = next((p for p in pillars if p.lower() in topic.lower()), pillars[seq % len(pillars)] if pillars else "General")
    confidence = "insufficient" if not ev.has_performance else "weak"
    sample = None
    observation = ""
    if ev.has_performance and ev.insight_report is not None:
        sample = ev.insight_report.posts_with_metrics
        observation = "directional only — your recorded metrics, mixed topics"

    reason_bits = [f"Proposed as a hypothesis: '{topic}' aligns with your stated interests."]
    if ev.profile and ev.profile.audience_needs:
        reason_bits.append(f"Audience need: {ev.profile.audience_needs[:160]}")
    reason_bits.append("You have little or no recorded performance on this exact topic, so treat it as an experiment.")

    return StrategyRecommendation(
        user_id=0,
        sequence_day=seq,
        pillar=pillar,
        topic=topic,
        format=formats[seq % len(formats)],
        platform=platform,
        working_title=f"{topic}: a practical first take",
        hook="",
        audience=(ev.profile.target_audience[:280] if ev.profile and ev.profile.target_audience else ""),
        objective=goal,
        cta="",
        production_notes="Record metrics after publishing so the next plan can cite this post as evidence.",
        is_hypothesis=True,
        reason=" ".join(reason_bits),
        evidence=[],
        sample_size=sample,
        observation_period=observation,
        confidence=confidence,
        success_metric="engagement_rate_per_view",
        test_method=(
            "Publish this variant, record day-7 views/engagement, and compare against your "
            "account median engagement-per-view. A single post cannot prove causality — "
            "repeat to strengthen the signal."
        ),
    )


def build_recommendations(
    db: Session, user_id: int, ev: StrategyEvidence, request: StrategyGenerateRequest
) -> list[StrategyRecommendation]:
    days = request.days or (30 if request.period == "month" else 7)
    posts_per_week = request.posts_per_week or 3
    total = min(MAX_RECOMMENDATIONS, max(1, round(days / 7 * posts_per_week)))
    platforms = _platforms_for(ev, request)
    goals = request.goals or (list(ev.profile.goals) if ev.profile and ev.profile.goals else ["education"])
    avoid = _avoid_set(ev)

    recs: list[StrategyRecommendation] = []
    seq = 0

    # 1) Evidence-backed: validated Phase-4 hints (only when performance exists)
    for hint in ev.validated_hints:
        if seq >= total:
            break
        topic = _first_topic_from_hint(hint)
        if topic and topic.lower() in avoid:
            continue
        platform = platforms[seq % len(platforms)]
        goal = goals[seq % len(goals)]
        recs.append(_hint_as_recommendation(hint, ev, seq, platform, goal))
        seq += 1

    # 2) Profile pillars / topics as hypotheses (skip ones already covered)
    covered = {r.topic.lower() for r in recs}
    for topic in _profile_topics(ev):
        if seq >= total:
            break
        if topic.lower() in avoid or topic.lower() in covered:
            continue
        platform = platforms[seq % len(platforms)]
        goal = goals[seq % len(goals)]
        recs.append(_hypothesis_recommendation(topic, ev, seq, platform, goal))
        covered.add(topic.lower())
        seq += 1

    # 3) Content-gap style fill from recent content topics (under-covered adjacent ideas)
    if seq < total and ev.contents:
        topic_counts: dict[str, int] = {}
        for c in ev.contents:
            key = (c.topic or "").strip()
            if key and key.lower() not in avoid:
                topic_counts[key] = topic_counts.get(key, 0) + 1
        rare = sorted(topic_counts.items(), key=lambda kv: kv[1])[: max(0, total - seq)]
        for topic, count in rare:
            if seq >= total:
                break
            if topic.lower() in covered:
                continue
            platform = platforms[seq % len(platforms)]
            goal = goals[seq % len(goals)]
            rec = _hypothesis_recommendation(topic, ev, seq, platform, goal)
            rec.reason = (
                f"You have covered '{topic}' {count} time(s) historically; this is a new angle "
                "on a familiar topic — still a hypothesis until metrics are recorded."
            )
            recs.append(rec)
            covered.add(topic.lower())
            seq += 1

    for r in recs:
        r.user_id = user_id
    return recs


# ----------------------------------------------------------------------------------
# Generation entry point (persists recommendations; optional LLM summary)
# ----------------------------------------------------------------------------------
def generate_strategy(
    db: Session, user_id: int, request: StrategyGenerateRequest
) -> StrategyGenerateResponse:
    ev = gather_evidence(db, user_id)
    recs = build_recommendations(db, user_id, ev, request)

    # Persist recommendations tied to a lightweight plan row for history.
    days = request.days or (30 if request.period == "month" else 7)
    start = request.start_date or datetime.now(timezone.utc)
    end = start + timedelta(days=days - 1)
    plan = ContentPlan(
        user_id=user_id,
        title=f"Strategy {request.period}: {start.date().isoformat()} → {end.date().isoformat()}",
        date_range=f"{start.date().isoformat()} → {end.date().isoformat()}",
        strategy_summary=_summary_text(ev, recs, request),
        request=request.model_dump_json(),
        memory_count=len(ev.memories),
        content_analyzed=len(ev.contents),
        gaps_considered=[],
        used_memory=bool(ev.memories),
        used_historical=bool(ev.contents),
        memory_backend="hindsight" if not ev.memory_degraded else "local",
        degraded=ev.memory_degraded,
        warnings=list(ev.warnings),
    )
    db.add(plan)
    db.flush()
    for r in recs:
        r.plan_id = plan.id
        db.add(r)
    db.commit()

    # Learning loop: remember accepted-profile preferences and top recs (small, curated).
    try:
        memory = MemoryService(db)
        statements: list[MemoryStatement] = []
        if ev.profile and ev.profile.niche:
            statements.append(
                MemoryStatement(
                    text=f"Creator niche: {ev.profile.niche}. Goals: {', '.join(ev.profile.goals) or 'unset'}.",
                    kind="strategy",
                    context="Creator strategy preferences",
                )
            )
        for rec in recs[:5]:
            statements.append(
                MemoryStatement(
                    text=(
                        f"Planned {rec.platform} {rec.format} about '{rec.topic}' "
                        f"({'hypothesis' if rec.is_hypothesis else 'evidence-backed, n=' + str(rec.sample_size)})."
                    ),
                    kind="strategy",
                    context="Content plan learning",
                )
            )
        if statements:
            memory.remember(statements, document_id=f"strategy-plan-{plan.id}", user_id=user_id)
    except Exception:  # noqa: BLE001 - memory failure degrades, never breaks
        ev.memory_degraded = True
        ev.warnings.append("Memory write failed; this plan will not be remembered.")

    db.refresh(plan)
    return StrategyGenerateResponse(
        plan_id=plan.id,
        period=request.period,
        summary=plan.strategy_summary,
        recommendations=[RecommendationRead.model_validate(r) for r in recs],
        evidence_sources=ev.sources,
        warnings=ev.warnings,
        memory_degraded=ev.memory_degraded,
    )


def _summary_text(ev: StrategyEvidence, recs: list[StrategyRecommendation], request: StrategyGenerateRequest) -> str:
    if not recs:
        return (
            "Not enough information to recommend anything yet. Set your strategy profile "
            "(topics, audience, goals) and/or register published posts with metrics."
        )
    evidence_count = sum(1 for r in recs if not r.is_hypothesis)
    hypothesis_count = len(recs) - evidence_count
    bits = [f"{len(recs)} recommendation(s) for the next {request.period}."]
    if evidence_count:
        bits.append(f"{evidence_count} backed by your recorded performance data.")
    if hypothesis_count:
        bits.append(
            f"{hypothesis_count} learning-oriented hypotheses (no sufficient performance "
            "data for those topics yet)."
        )
    if ev.warnings:
        bits.append("See warnings for data limitations.")
    return " ".join(bits)


# ----------------------------------------------------------------------------------
# Recommendation lifecycle (edit / accept / reject / defer / complete)
# ----------------------------------------------------------------------------------
def get_recommendation(db: Session, user_id: int, rec_id: int) -> StrategyRecommendation | None:
    return db.scalar(
        select(StrategyRecommendation).where(
            StrategyRecommendation.id == rec_id, StrategyRecommendation.user_id == user_id
        )
    )


def list_recommendations(
    db: Session, user_id: int, *, status: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[StrategyRecommendation], int]:
    base = select(StrategyRecommendation).where(StrategyRecommendation.user_id == user_id)
    if status:
        base = base.where(StrategyRecommendation.status == status)
    from sqlalchemy import func

    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = list(
        db.scalars(base.order_by(StrategyRecommendation.sequence_day, StrategyRecommendation.id).limit(limit).offset(offset))
    )
    return rows, total


def update_recommendation(
    db: Session, user_id: int, rec_id: int, payload: Any  # RecommendationUpdate
) -> StrategyRecommendation | None:
    rec = get_recommendation(db, user_id, rec_id)
    if rec is None:
        return None
    if payload.status is not None:
        rec.status = payload.status
    if payload.edited_title is not None:
        rec.edited_title = payload.edited_title.strip()
        if rec.status == "proposed":
            rec.status = "edited"
    if payload.edited_hook is not None:
        rec.edited_hook = payload.edited_hook.strip()
        if rec.status == "proposed":
            rec.status = "edited"
    if payload.edited_notes is not None:
        rec.edited_notes = payload.edited_notes.strip()
    if payload.feedback_note is not None:
        rec.feedback_note = payload.feedback_note.strip()
    db.commit()
    db.refresh(rec)
    return rec


def apply_feedback(
    db: Session, user_id: int, rec_id: int, payload: FeedbackRequest
) -> tuple[StrategyRecommendation | None, bool]:
    """Record feedback; optionally persist a preference to profile + memory.

    Returns (recommendation, memory_degraded). A single rejection is stored on
    the recommendation only — it is NOT promoted to a permanent preference
    unless the creator explicitly sets update_preferences=True.
    """
    rec = get_recommendation(db, user_id, rec_id)
    if rec is None:
        return None, False

    if payload.status:
        rec.status = payload.status
    if payload.note:
        rec.feedback_note = payload.note.strip()

    memory_degraded = False
    if payload.update_preferences and payload.note:
        profile = get_profile(db, user_id)
        if profile is not None:
            prefs = list(profile.feedback_preferences or [])
            statement = f"{rec.topic}: {payload.note.strip()}"[:300]
            if statement not in prefs:
                prefs.append(statement)
            profile.feedback_preferences = prefs[-20:]  # bounded
            db.commit()
        try:
            memory = MemoryService(db)
            memory.remember(
                [
                    MemoryStatement(
                        text=f"Creator preference about '{rec.topic}': {payload.note.strip()}",
                        kind="strategy",
                        context="Explicit creator preference",
                    )
                ],
                document_id=f"preference-{rec.id}",
                user_id=user_id,
            )
        except Exception:  # noqa: BLE001
            memory_degraded = True

    db.commit()
    db.refresh(rec)
    return rec, memory_degraded


# ----------------------------------------------------------------------------------
# Experiments
# ----------------------------------------------------------------------------------
def create_experiment(db: Session, user_id: int, payload: ExperimentCreate) -> Experiment:
    exp = Experiment(
        user_id=user_id,
        recommendation_id=payload.recommendation_id,
        title=payload.title.strip() or "Untitled experiment",
        hypothesis=payload.hypothesis.strip(),
        variation=payload.variation.strip(),
        intended_metric=payload.intended_metric.strip() or "engagement_rate_per_view",
        status="planned",
    )
    db.add(exp)
    db.commit()
    db.refresh(exp)
    return exp


def update_experiment(db: Session, user_id: int, exp_id: int, payload: ExperimentUpdate) -> Experiment | None:
    exp = db.scalar(select(Experiment).where(Experiment.id == exp_id, Experiment.user_id == user_id))
    if exp is None:
        return None
    if payload.status is not None:
        exp.status = payload.status
        if payload.status == "completed" and exp.completed_at is None:
            exp.completed_at = datetime.now(timezone.utc)
    if payload.actual_result is not None:
        exp.actual_result = payload.actual_result.strip()
    if payload.result_note is not None:
        exp.result_note = payload.result_note.strip()
    db.commit()
    db.refresh(exp)
    return exp


def list_experiments(db: Session, user_id: int, *, limit: int = 50) -> list[Experiment]:
    return list(
        db.scalars(
            select(Experiment).where(Experiment.user_id == user_id).order_by(Experiment.id.desc()).limit(limit)
        )
    )


# ----------------------------------------------------------------------------------
# Lessons (memory + completed experiments)
# ----------------------------------------------------------------------------------
def build_lessons(db: Session, user_id: int) -> LessonsResponse:
    lessons: list[LessonRead] = []
    memory_degraded = False

    # 1. Memory-sourced strategy lessons
    try:
        memory = MemoryService(db)
        recall = memory.recall("strategy lessons topics that worked experiments", user_id=user_id, limit=10)
        memory_degraded = recall.degraded
        for m in recall.memories:
            text = (m.text or "").strip()
            if not text or len(text) < 15:
                continue
            lessons.append(
                LessonRead(text=text, kind=m.kind or "strategy", confidence="weak", source="memory")
            )
    except Exception:  # noqa: BLE001
        memory_degraded = True

    # 2. Completed experiments as observed lessons (with evidence + non-causal framing)
    try:
        completed = list(
            db.scalars(
                select(Experiment)
                .where(Experiment.user_id == user_id, Experiment.status == "completed")
                .order_by(Experiment.id.desc())
                .limit(10)
            )
        )
        for exp in completed:
            if not exp.actual_result:
                continue
            lessons.append(
                LessonRead(
                    text=(
                        f"Experiment '{exp.title}' ({exp.intended_metric}): {exp.actual_result}. "
                        "This is a single observation, not proof of causality."
                    ),
                    kind="experiment",
                    confidence="weak",
                    evidence=[exp.hypothesis] if exp.hypothesis else [],
                    source="experiment",
                )
            )
    except Exception:  # noqa: BLE001
        pass

    message = (
        f"{len(lessons)} lesson(s) from memory and completed experiments."
        if lessons
        else "No lessons yet. Accept recommendations, run experiments, and record results."
    )
    return LessonsResponse(lessons=lessons[:15], message=message, memory_degraded=memory_degraded)
