"""Phase 5 — Content Strategy Agent routes.

Profile CRUD, strategy generation from stored evidence, recommendation
lifecycle (edit/accept/reject/defer/complete), experiments, and lessons.
Every route is scoped to the authenticated user; generation never raises on
missing data — it degrades and reports warnings instead.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models import User
from ...schemas import (
    ExperimentCreate,
    ExperimentRead,
    ExperimentUpdate,
    FeedbackRequest,
    LessonsResponse,
    RecommendationListResponse,
    RecommendationRead,
    RecommendationUpdate,
    StrategyGenerateRequest,
    StrategyGenerateResponse,
    StrategyProfileRead,
    StrategyProfileUpsert,
)
from ...services import strategy_agent_service as agent

logger = logging.getLogger("contentmind.routes.strategy")
router = APIRouter()


# ----------------------------------------------------------------------------------
# Profile
# ----------------------------------------------------------------------------------
@router.get("/profile", response_model=StrategyProfileRead)
def get_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    """Return the current user's strategy profile (empty defaults when unset)."""
    profile = agent.get_profile(db, current_user.id)
    if profile is None:
        return StrategyProfileRead(
            id=0,
            niche="",
            topics=[],
            target_audience="",
            audience_needs="",
            goals=[],
            content_pillars=[],
            avoid_topics=[],
            publishing_frequency="",
            constraints="",
            feedback_preferences=[],
            is_active=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    return agent._profile_read(profile)


@router.put("/profile", response_model=StrategyProfileRead)
def upsert_profile(
    payload: StrategyProfileUpsert,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StrategyProfileRead:
    """Create or update the user's strategy profile (one active per user)."""
    profile = agent.upsert_profile(db, current_user.id, payload)
    return agent._profile_read(profile)


# ----------------------------------------------------------------------------------
# Generation
# ----------------------------------------------------------------------------------
@router.post("/generate", response_model=StrategyGenerateResponse)
def generate_strategy(
    payload: StrategyGenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> StrategyGenerateResponse:
    """Generate evidence-backed recommendations + a plan for the period.

    Deterministic: every number comes from stored records. Missing sources
    degrade to hypotheses with warnings; this endpoint never 500s on empty
    data.
    """
    return agent.generate_strategy(db, current_user.id, payload)


# ----------------------------------------------------------------------------------
# Recommendations
# ----------------------------------------------------------------------------------
@router.get("/recommendations", response_model=RecommendationListResponse)
def list_recommendations(
    status: str | None = Query(default=None, max_length=20),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationListResponse:
    rows, total = agent.list_recommendations(db, current_user.id, status=status, limit=limit, offset=offset)
    return RecommendationListResponse(
        items=[RecommendationRead.model_validate(r) for r in rows],
        total=total,
    )


@router.patch("/recommendations/{rec_id}", response_model=RecommendationRead)
def update_recommendation(
    rec_id: int,
    payload: RecommendationUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationRead:
    """Edit a recommendation's creator fields or transition its status."""
    rec = agent.update_recommendation(db, current_user.id, rec_id, payload)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    return RecommendationRead.model_validate(rec)


@router.post("/recommendations/{rec_id}/feedback", response_model=RecommendationRead)
def give_feedback(
    rec_id: int,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> RecommendationRead:
    """Accept/reject/defer/complete with a note; optionally persist preference."""
    rec, _memory_degraded = agent.apply_feedback(db, current_user.id, rec_id, payload)
    if rec is None:
        raise HTTPException(status_code=404, detail="Recommendation not found.")
    return RecommendationRead.model_validate(rec)


# ----------------------------------------------------------------------------------
# Experiments
# ----------------------------------------------------------------------------------
@router.get("/experiments", response_model=list[ExperimentRead])
def list_experiments(
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[ExperimentRead]:
    rows = agent.list_experiments(db, current_user.id, limit=limit)
    return [ExperimentRead.model_validate(r) for r in rows]


@router.post("/experiments", response_model=ExperimentRead, status_code=201)
def create_experiment(
    payload: ExperimentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExperimentRead:
    """Track a hypothesis-driven experiment (optionally tied to a recommendation)."""
    exp = agent.create_experiment(db, current_user.id, payload)
    return ExperimentRead.model_validate(exp)


@router.patch("/experiments/{exp_id}", response_model=ExperimentRead)
def update_experiment(
    exp_id: int,
    payload: ExperimentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ExperimentRead:
    """Update experiment status / record actual results (completes with timestamp)."""
    exp = agent.update_experiment(db, current_user.id, exp_id, payload)
    if exp is None:
        raise HTTPException(status_code=404, detail="Experiment not found.")
    return ExperimentRead.model_validate(exp)


# ----------------------------------------------------------------------------------
# Lessons
# ----------------------------------------------------------------------------------
@router.get("/lessons", response_model=LessonsResponse)
def lessons(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> LessonsResponse:
    """Lessons learned from memory + completed experiments (non-causal framing)."""
    return agent.build_lessons(db, current_user.id)
