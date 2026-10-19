"""Phase 4 — Performance routes.

Manual-first workflow: register published posts, append dated metric
snapshots, view history, dashboard aggregates and evidence-based insights.
Every route is scoped to the authenticated user.
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...database import get_db
from ...models import User
from ...schemas import (
    InsightReportResponse,
    MetricSnapshotInput,
    MetricSnapshotRead,
    PerformanceAnalyticsResponse,
    PostComparison,
    PublishedPostCreate,
    PublishedPostDetail,
    PublishedPostListResponse,
    PublishedPostRead,
    PublishedPostUpdate,
)
from ...services import insight_service, performance_service

logger = logging.getLogger("contentmind.routes.performance")
router = APIRouter()


def _parse_optional_dt(value: str | None, name: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid {name}: use ISO-8601.") from exc


@router.post("/posts", response_model=PublishedPostRead, status_code=201)
def register_post(
    payload: PublishedPostCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishedPostRead:
    """Register a published post, optionally with an initial metric snapshot.

    Linked content_id / media_asset_id must belong to the same user or they
    are rejected. URL and external_id are stored sanitised and never fetched.
    """
    if payload.content_id is not None:
        from ...models import Content

        if db.get(Content, payload.content_id) is None or db.get(Content, payload.content_id).user_id != current_user.id:  # type: ignore[union-attr]
            raise HTTPException(status_code=404, detail="Linked content not found.")
    if payload.media_asset_id is not None:
        from ...models import MediaAsset

        asset = db.get(MediaAsset, payload.media_asset_id)
        if asset is None or asset.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Linked media asset not found.")

    post = performance_service.register_post(db, current_user.id, payload)
    return performance_service.post_to_read(post)


@router.get("/posts", response_model=PublishedPostListResponse)
def list_posts(
    platform: str | None = Query(default=None, max_length=60),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishedPostListResponse:
    rows, total = performance_service.list_posts(
        db, current_user.id, platform=platform, limit=limit, offset=offset
    )
    return PublishedPostListResponse(
        items=[performance_service.post_to_read(p) for p in rows], total=total
    )


@router.get("/posts/{post_id}", response_model=PublishedPostDetail)
def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishedPostDetail:
    post = performance_service.get_post(db, current_user.id, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Published post not found.")
    return performance_service.post_to_detail(post)


@router.patch("/posts/{post_id}", response_model=PublishedPostRead)
def update_post(
    post_id: int,
    payload: PublishedPostUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PublishedPostRead:
    post = performance_service.update_post(db, current_user.id, post_id, payload)
    if post is None:
        raise HTTPException(status_code=404, detail="Published post not found.")
    return performance_service.post_to_read(post)


@router.delete("/posts/{post_id}", status_code=204)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    if not performance_service.delete_post(db, current_user.id, post_id):
        raise HTTPException(status_code=404, detail="Published post not found.")


@router.post("/posts/{post_id}/snapshots", response_model=MetricSnapshotRead, status_code=201)
def add_snapshot(
    post_id: int,
    payload: MetricSnapshotInput,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> MetricSnapshotRead:
    """Append a new dated metric snapshot. History is never overwritten."""
    snap = performance_service.add_snapshot(db, current_user.id, post_id, payload)
    if snap is None:
        raise HTTPException(status_code=404, detail="Published post not found.")
    return MetricSnapshotRead.model_validate(snap)


@router.get("/analytics", response_model=PerformanceAnalyticsResponse)
def analytics(
    start: str | None = Query(default=None, description="ISO-8601 date/datetime lower bound on published_at"),
    end: str | None = Query(default=None, description="ISO-8601 date/datetime upper bound on published_at"),
    platform: str | None = Query(default=None, max_length=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> PerformanceAnalyticsResponse:
    """Dashboard aggregates over the user's published posts."""
    return performance_service.build_performance_analytics(
        db,
        current_user.id,
        start=_parse_optional_dt(start, "start"),
        end=_parse_optional_dt(end, "end"),
        platform=platform,
    )


@router.get("/compare/{platform}", response_model=list[PostComparison])
def compare(
    platform: str,
    max_age_gap_days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[PostComparison]:
    """Compare posts on one platform with comparable observation windows."""
    return performance_service.compare_posts(
        db, current_user.id, platform, max_age_gap_days=max_age_gap_days
    )


@router.get("/insights", response_model=InsightReportResponse)
def insights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InsightReportResponse:
    """Evidence-based insights from the user's own posts and metrics."""
    return insight_service.build_insight_report(db, current_user.id)
