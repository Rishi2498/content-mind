"""Pre-publish reviewer routes: review drafts, review media, browse history."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models import User
from ...schemas import (
    ContentReviewRead,
    ReviewerHistoryResponse,
    ReviewerRequest,
    ReviewerResponse,
)
from ...services import reviewer_service

logger = logging.getLogger("contentmind.routes.reviewer")
router = APIRouter()


@router.post("/review", response_model=ReviewerResponse)
def review_draft(
    payload: ReviewerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewerResponse:
    """Review a pre-publish text draft. Persists the review for iteration history."""
    try:
        response = reviewer_service.review_draft(db, payload, current_user.id)
        db.commit()
        return response
    except Exception as exc:  # noqa: BLE001 - review must degrade, not 500
        logger.exception("Draft review failed")
        db.rollback()
        raise HTTPException(status_code=503, detail="Review failed. Try again.") from exc


@router.post("/media/{asset_id}", response_model=ReviewerResponse)
def review_media(
    asset_id: int,
    platform: str = Query(default="", max_length=60),
    topic: str = Query(default="", max_length=120),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewerResponse:
    """Review a processed media asset via its ContentDNA.

    Writes the scores back onto the DNA (hook/clarity/brand_alignment).
    """
    response = reviewer_service.review_media_asset(
        db, user_id=current_user.id, asset_id=asset_id, platform=platform, topic=topic
    )
    if response is None:
        raise HTTPException(
            status_code=404,
            detail="Media asset not found or has no Content DNA yet.",
        )
    db.commit()
    return response


@router.get("/reviews", response_model=ReviewerHistoryResponse)
def list_reviews(
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ReviewerHistoryResponse:
    rows, total = reviewer_service.review_history(db, current_user.id, limit=limit, offset=offset)
    return ReviewerHistoryResponse(
        items=[ContentReviewRead.model_validate(r) for r in rows], total=total
    )
