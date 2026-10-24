"""Demo orchestration: seed, reset, and the before/after memory comparison."""

from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import (
    BrandProfile,
    Content,
    ContentInsight,
    ContentPlan,
    ContentPlanItem,
    MemoryEvent,
    PlanResult,
)
from ..schemas import (
    ContentCreate,
    DemoResetResponse,
    DemoSeedRequest,
    DemoSeedResponse,
    PlanRequest,
)
from .content_service import all_contents, apply_metrics, create_content
from .memory_service import MemoryService
from .seed_service import default_brand_profile, generate_seed_payloads

logger = logging.getLogger("contentmind.demo")


def reset_demo(db: Session, user_id: int) -> DemoResetResponse:
    """Clear the relational database and the memory bank for one user."""
    insights = db.scalar(select(func.count(ContentInsight.id)).where(ContentInsight.user_id == user_id)) or 0
    plans = db.scalar(select(func.count(ContentPlan.id)).where(ContentPlan.user_id == user_id)) or 0
    content = db.scalar(select(func.count(Content.id)).where(Content.user_id == user_id)) or 0

    plan_ids = select(ContentPlan.id).where(ContentPlan.user_id == user_id)
    db.execute(delete(PlanResult).where(PlanResult.user_id == user_id))
    db.execute(delete(ContentPlanItem).where(ContentPlanItem.plan_id.in_(plan_ids)))
    db.execute(delete(ContentPlan).where(ContentPlan.user_id == user_id))
    db.execute(delete(ContentInsight).where(ContentInsight.user_id == user_id))
    db.execute(delete(MemoryEvent).where(MemoryEvent.user_id == user_id))
    db.execute(delete(Content).where(Content.user_id == user_id))
    db.execute(delete(BrandProfile).where(BrandProfile.user_id == user_id))
    db.commit()

    from .hindsight_service import get_hindsight_service

    hindsight = get_hindsight_service()
    bank_cleared = False
    degraded = False
    try:
        result = hindsight.clear()
        bank_cleared = bool(result.get("success", True))
        degraded = result.get("backend") != "hindsight"
    except Exception as exc:  # noqa: BLE001
        logger.warning("Hindsight clear failed during reset: %s", exc)
        degraded = True

    return DemoResetResponse(
        content_deleted=content,
        insights_deleted=insights,
        plans_deleted=plans,
        memory_backend="hindsight" if not degraded else "local",
        bank_cleared=bank_cleared,
        degraded=degraded,
        message=(
            "Database cleared and the Hindsight memory bank was emptied. "
            "Ask 'What should I post next week?' now to see the un-informed answer."
        ),
    )


def seed_demo(db: Session, request: DemoSeedRequest, user_id: int) -> DemoSeedResponse:
    """Populate structured history, derive insights, and remember it in Hindsight.

    The ``request.profile`` selects a creator niche (educational, fitness, food,
    technology) which alters the seeded topic distribution and synthetic
    performance patterns.  When ``profile`` is omitted the default (educational)
    weighting is used.
    """
    if request.reset_first:
        reset_demo(db, user_id)

    rows = generate_seed_payloads(request.records, seed=20260929, profile=request.profile)
    warnings: list[str] = []

    existing_titles = {
        t.lower() for t in db.scalars(select(Content.title).where(Content.user_id == user_id))
    }
    created = 0
    for row in rows:
        if row["title"].lower() in existing_titles:
            continue
        existing_titles.add(row["title"].lower())
        create_content(
            db,
            ContentCreate(**{k: v for k, v in row.items() if k != "source"}),
            user_id,
        )
        created += 1
    db.commit()

    # Brand profile: start from the curated default, then let the agent refine it.
    brand = db.scalar(
        select(BrandProfile).where(
            BrandProfile.user_id == user_id,
            BrandProfile.is_active.is_(True),
        ).limit(1)
    )
    if brand is None:
        brand = BrandProfile(user_id=user_id, **default_brand_profile(request.brand_name))
        db.add(brand)
    else:
        brand.brand_name = request.brand_name
    db.flush()

    # Per-item insights (structured, cheap)
    from .content_service import account_average_rate, extract_insights

    insights_created = 0
    contents = all_contents(db, user_id=user_id)
    avg = account_average_rate(db, user_id)
    for content in contents:
        if db.scalar(
            select(ContentInsight.id).where(
                ContentInsight.content_id == content.id, ContentInsight.insight_type == "performance"
            )
        ):
            continue
        for model in extract_insights(content, avg):
            db.add(
                ContentInsight(
                    content_id=content.id,
                    user_id=user_id,
                    insight_type=model.insight_type,
                    insight=model.insight,
                    confidence=model.confidence,
                    source="historical_performance",
                    evidence=model.evidence,
                )
            )
            insights_created += 1
    db.commit()

    memory = MemoryService(db)
    memories_retained = 0
    backend = "none"
    degraded = True

    if request.remember:
        try:
            backend = "hindsight" if memory.hindsight.configured else "local"
            # Portfolio-level synthesis first: the agent's high-level beliefs.
            retained, backend, degraded = memory.learn_portfolio(
                user_id=user_id, document_id="seed-portfolio"
            )
            memories_retained += retained

            # Then per-item memories, so recall can quote specifics.
            contents = all_contents(db, user_id=user_id)
            per_item: list = []
            for content in contents:
                from .memory_service import build_content_statements

                per_item.extend(
                    build_content_statements(content, account_average_rate(db, user_id), avg * 0.12)
                )
            retained, backend, degraded = memory.remember(
                per_item, document_id="seed-content-history", user_id=user_id
            )
            memories_retained += retained
        except Exception as exc:  # noqa: BLE001
            logger.warning("Seeding memory failed: %s", exc)
            warnings.append(f"Memory seeding degraded: {exc}")
    else:
        warnings.append("Content seeded but memory was not written (remember=false).")

    db.commit()

    # Let the agent learn the brand voice from the history it now has.
    try:
        from .strategy_service import learn_brand_profile

        learn_brand_profile(db, request.brand_name, user_id=user_id)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.info("Brand learning skipped: %s", exc)
        db.rollback()
        warnings.append(f"Brand profile learning skipped: {exc}")

    from .analytics_service import build_analytics

    analytics = build_analytics(all_contents(db, user_id=user_id))
    dates = [c.published_at for c in all_contents(db, user_id=user_id) if c.published_at]
    span = (
        f"{min(dates).date().isoformat()} → {max(dates).date().isoformat()}" if dates else ""
    )
    if not request.remember:
        degraded = True

    return DemoSeedResponse(
        content_created=created,
        insights_created=insights_created,
        memories_retained=memories_retained,
        memory_backend=backend,
        bank=memory.hindsight.bank,
        degraded=degraded,
        warnings=warnings,
        top_topics=[s.key for s in analytics.by_topic[:6]],
        date_span=span,
    )


def record_new_results(db: Session, contents: list[Content]) -> None:
    """Re-derive the account average after ingesting fresh performance data.

    Called on every ingestion so the *next* plan is compared against an updated
    baseline — this is what makes recommendations change over time.
    """
    if not contents:
        return
    user_id = contents[0].user_id
    memory = MemoryService(db)
    memory.learn_portfolio(user_id=user_id, document_id=f"portfolio-{datetime.now().date().isoformat()}")
    db.commit()
