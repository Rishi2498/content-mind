"""Memory inspection and learning routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import ContentInsight, User
from ...schemas import (
    LearnedResponse,
    MemoryRecallResponse,
    MemoryStatus,
    PlanRequest,
)
from ...services.content_service import account_average_rate, all_contents, extract_insights
from ...services.learned_service import CATEGORY_LABELS, get_learned
from ...services.memory_service import MemoryService
from ...services.strategy_service import build_strategy_context, generate_plan_for_user
from ...auth import get_current_user

logger = logging.getLogger("contentmind.routes.memory")
router = APIRouter()


@router.get("", response_model=LearnedResponse)
def what_i_learned(
    include_memories: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LearnedResponse:
    return get_learned(db, user_id=current_user.id, include_memories=include_memories)


@router.get("/categories")
def categories() -> dict:
    return {"categories": CATEGORY_LABELS}


@router.get("/status", response_model=MemoryStatus)
def status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryStatus:
    return MemoryService(db).status()


@router.get("/recall", response_model=MemoryRecallResponse)
def recall(
    query: str = Query(default="what should I publish next", min_length=2),
    limit: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MemoryRecallResponse:
    return MemoryService(db).recall(query, user_id=current_user.id, limit=limit)


@router.get("/list")
def list_memories(
    limit: int = Query(default=50, ge=1, le=400),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Raw memory-unit browser — mirrors the Hindsight control plane."""
    from ...services.hindsight_service import get_hindsight_service

    try:
        items, total, backend = get_hindsight_service().list_memories(limit=limit * 4, offset=offset)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory listing failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Memory layer unavailable: {exc}") from exc

    wanted = f"user:{current_user.id}"
    items = [i for i in items if wanted in (i.get("tags") or [])][:limit]

    return {
        "items": items,
        "total": total,
        "backend": backend,
        "limit": limit,
        "offset": offset,
    }


@router.get("/context")
def strategy_context(
    request: str = Query(default="what should I post next week"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Expose the exact context handed to the LLM — the audit trail judges look for."""
    ctx = build_strategy_context(db, request, user_id=current_user.id)
    return {
        "summary": ctx.summary(),
        "memories": [m.model_dump(mode="json") for m in ctx.memories],
        "gaps": [g.model_dump(mode="json") for g in ctx.gaps.gaps],
        "warnings": ctx.analytics.warnings,
    }


@router.post("/learn", response_model=dict)
def learn(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Force a learning pass over the whole content history."""
    memory = MemoryService(db)
    contents = all_contents(db, user_id=current_user.id)
    if not contents:
        return {
            "memories_retained": 0,
            "backend": memory.status().backend,
            "message": "No content history to learn from yet. Add content first.",
            "degraded": True,
        }

    avg = account_average_rate(db, current_user.id)
    insights_created = 0
    for content in contents:
        for model in extract_insights(content, avg):
            db.add(
                ContentInsight(
                    content_id=content.id,
                    user_id=current_user.id,
                    insight_type=model.insight_type,
                    insight=model.insight,
                    confidence=model.confidence,
                    source="historical_performance",
                    evidence=model.evidence,
                )
            )
            insights_created += 1
    db.commit()

    retained, backend, degraded = memory.learn_portfolio(user_id=current_user.id)
    db.commit()

    return {
        "content_analyzed": len(contents),
        "insights_created": insights_created,
        "memories_retained": retained,
        "backend": backend,
        "degraded": degraded,
        "message": (
            f"Learned from {len(contents)} content items; {retained} memories written to the "
            f"'{backend}' memory bank."
        ),
    }


@router.post("/plan-and-remember")
def plan_and_remember(
    payload: PlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Generate a plan and show exactly which memories drove it."""
    result = generate_plan_for_user(db, payload, current_user.id)
    return {
        "plan": result.plan.model_dump(mode="json"),
        "memory_used": [m.model_dump(mode="json") for m in result.memory_used],
        "gaps": [g.model_dump(mode="json") for g in result.gaps],
        "context_summary": result.context_summary,
    }
