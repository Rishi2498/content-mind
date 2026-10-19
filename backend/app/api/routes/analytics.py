"""Analytics and content gap routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import AnalyticsResponse, GapResponse
from ...services.analytics_service import build_analytics
from ...services.content_service import all_contents
from ...services.gap_service import detect_gaps
from ...auth import get_current_user
from ...models import User


router = APIRouter()


@router.get("", response_model=AnalyticsResponse)
def analytics(
    limit: int = Query(default=1000, ge=1, le=5000), 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> AnalyticsResponse:
    # Filter contents for this user
    from ...models import Content
    from sqlalchemy import select
    stmt = select(Content).where(Content.user_id == current_user.id)
    contents = list(db.scalars(stmt))
    return build_analytics(contents)



@router.get("/gaps", response_model=GapResponse)
def gaps(
    limit: int = Query(default=6, ge=1, le=25),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> GapResponse:
    from ...models import Content
    from sqlalchemy import select
    stmt = select(Content).where(Content.user_id == current_user.id)
    contents = list(db.scalars(stmt))
    return detect_gaps(build_analytics(contents), contents, limit=limit)



@router.get("/overview")
def overview(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> dict:
    """Compact summary for the dashboard hero cards."""
    from ...models import Content
    from sqlalchemy import select
    stmt = select(Content).where(Content.user_id == current_user.id)
    contents = list(db.scalars(stmt))
    a = build_analytics(contents)
    return {
        "content_published": a.content_count,
        "total_engagement": a.total_engagements,
        "total_impressions": a.total_impressions,
        "avg_engagement_rate": a.avg_engagement_rate,
        "top_topic": a.top_topic.model_dump() if a.top_topic else None,
        "top_platform": a.top_platform.model_dump() if a.top_platform else None,
        "top_content_type": a.top_content_type.model_dump() if a.top_content_type else None,
        "best_content": [c.model_dump() for c in a.best_content[:3]],
        "recent_content": [c.model_dump() for c in a.recent_content[:5]],
        "warnings": a.warnings,
    }

