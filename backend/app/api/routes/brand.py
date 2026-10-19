"""Brand profile routes — the memory of how the company sounds."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import BrandProfile, User
from ...schemas import BrandProfileRead, BrandProfileUpsert
from ...services.memory_service import MemoryService
from ...services.strategy_service import get_brand, learn_brand_profile
from ...schemas import MemoryStatement
from ...auth import get_current_user


logger = logging.getLogger("contentmind.routes.brand")
router = APIRouter()


@router.get("", response_model=BrandProfileRead | None)
def read_brand(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> BrandProfileRead | None:
    return get_brand(db, user_id=current_user.id)



@router.put("", response_model=BrandProfileRead)
def upsert_brand(
    payload: BrandProfileUpsert, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> BrandProfileRead:
    existing = db.scalar(
        select(BrandProfile).where(
            BrandProfile.user_id == current_user.id, 
            BrandProfile.is_active.is_(True)
        ).limit(1)
    )
    if existing is None:
        existing = BrandProfile(
            brand_name=payload.brand_name, 
            user_id=current_user.id
        )
        db.add(existing)

    existing.brand_name = payload.brand_name
    existing.target_audience = payload.target_audience or existing.target_audience
    existing.tone = payload.tone or existing.tone
    existing.preferred_formats = payload.preferred_formats or existing.preferred_formats
    existing.preferred_platforms = payload.preferred_platforms or existing.preferred_platforms
    existing.description = payload.description or existing.description
    existing.is_active = True
    db.commit()

    if payload.learn_from_content:
        try:
            result = learn_brand_profile(db, payload.brand_name, user_id=current_user.id)
            db.commit()
            if result:
                return result
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("Brand learning failed: %s", exc)

    db.refresh(existing)
    return BrandProfileRead.model_validate(existing)



@router.post("/learn", response_model=BrandProfileRead | None)
def learn_brand(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> BrandProfileRead | None:
    current = get_brand(db, user_id=current_user.id)
    brand_name = current.brand_name if current else "Our Company"
    try:
        result = learn_brand_profile(db, brand_name, user_id=current_user.id)
        db.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Brand learning failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"Could not learn brand profile: {exc}") from exc



@router.post("/remember", response_model=dict)
def remember_brand_statement(
    text: str, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """Store an explicit brand rule as a durable memory."""
    statement = text.strip()
    if len(statement) < 5:
        raise HTTPException(status_code=422, detail="Brand memory must be at least 5 characters")

    memory = MemoryService(db)
    retained, backend, degraded = memory.remember(
        [MemoryStatement(text=statement, kind="brand", context="Brand voice and positioning")],
        document_id="brand-rules",
        user_id=current_user.id,
    )
    db.commit()
    return {
        "retained": retained,
        "backend": backend,
        "degraded": degraded,
        "message": f"Remembered: '{statement}'",
    }

