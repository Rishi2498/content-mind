"""Content planning routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import PlanGenerateResponse, PlanListResponse, PlanRead, PlanRequest
from ...services import strategy_service
from ...auth import get_current_user
from ...models import User


logger = logging.getLogger("contentmind.routes.plans")
router = APIRouter()


@router.post("/generate", response_model=PlanGenerateResponse)
def generate_plan(
    payload: PlanRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> PlanGenerateResponse:
    try:
        # We need to pass user_id to strategy_service.generate_plan
        return strategy_service.generate_plan_for_user(db, payload, current_user.id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.exception("Plan generation failed")
        raise HTTPException(status_code=500, detail=f"Plan generation failed: {exc}") from exc



@router.post("", response_model=PlanGenerateResponse, status_code=201)
def create_plan(
    payload: PlanRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> PlanGenerateResponse:
    return generate_plan(payload, db, current_user)



@router.get("", response_model=PlanListResponse)
def list_plans(
    limit: int = Query(default=20, ge=1, le=100), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> PlanListResponse:
    return strategy_service.list_plans(db, user_id=current_user.id, limit=limit)



@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(
    plan_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> PlanRead:
    plan = strategy_service.get_plan(db, plan_id)
    if plan is None or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    return strategy_service.plan_to_read(plan)



@router.delete("/{plan_id}", status_code=204)
def delete_plan(
    plan_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> None:
    plan = strategy_service.get_plan(db, plan_id)
    if plan is None or plan.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Plan {plan_id} not found")
    db.delete(plan)
    db.commit()

