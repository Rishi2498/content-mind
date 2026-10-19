"""Content ingestion and library routes."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ...database import get_db
from ...models import Content
from ...schemas import (
    ContentCreate,
    ContentInsightRead,
    ContentListResponse,
    ContentRead,
    ContentUpdate,
    IngestRequest,
    IngestResponse,
)
from ...services import content_service
from ...services.memory_service import MemoryService
from ...auth import get_current_user
from ...models import User


logger = logging.getLogger("contentmind.routes.content")
router = APIRouter()


@router.get("", response_model=ContentListResponse)
def list_content(
    search: str | None = None,
    platform: str | None = None,
    topic: str | None = None,
    content_type: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ContentListResponse:
    return content_service.list_content(
        db,
        search=search,
        platform=platform,
        topic=topic,
        content_type=content_type,
        status=status_filter,
        limit=limit,
        offset=offset,
        user_id=current_user.id,
    )



@router.get("/{content_id}", response_model=ContentRead)
def get_content(
    content_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> ContentRead:
    content = content_service.get_content(db, content_id)
    if content is None or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    return ContentRead.model_validate(content)



@router.post("", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def create_content(
    payload: ContentCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> IngestResponse:
    """Add content, calculate metrics, extract insights, remember them."""
    content = content_service.create_content(db, payload, current_user.id)
    db.commit()

    warnings: list[str] = []
    insights: list[ContentInsightRead] = []
    memories_retained = 0
    backend = "none"
    degraded = False

    if payload.analyze:
        memory = MemoryService(db)
        avg = content_service.account_average_rate(db, current_user.id, exclude_id=content.id)
        try:
            new_insights, memories_retained, backend, degraded = memory.learn_from_content(content, avg)
            db.commit()
            insights = [ContentInsightRead.model_validate(i) for i in new_insights]
        except Exception as exc:  # noqa: BLE001 - ingestion must not fail on memory
            logger.warning("Analysis failed for content %s: %s", content.id, exc)
            db.rollback()
            warnings.append(f"Insight extraction failed: {exc}")

        try:
            retained, backend, degraded = memory.learn_portfolio(user_id=current_user.id)
            memories_retained += retained
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.info("Portfolio learning skipped: %s", exc)
            db.rollback()

    return IngestResponse(
        created=1,
        skipped=0,
        insights_created=len(insights),
        memories_retained=memories_retained,
        memory_backend=backend,
        degraded=degraded,
        warnings=warnings,
        insights=insights,
    )




@router.post("/bulk", response_model=IngestResponse, status_code=status.HTTP_201_CREATED)
def bulk_ingest(
    payload: IngestRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> IngestResponse:
    created_rows, skipped = content_service.bulk_create_content(
        db, payload.items, current_user.id, skip_duplicates=payload.skip_duplicates
    )
    db.commit()

    warnings: list[str] = []
    insights: list[ContentInsightRead] = []
    memories_retained = 0
    backend = "none"
    degraded = False

    if payload.analyze:
        memory = MemoryService(db)
        for content in created_rows:
            try:
                avg = content_service.account_average_rate(db, current_user.id, exclude_id=content.id)
                new_insights, retained, backend, degraded = memory.learn_from_content(content, avg)
                db.commit()
                memories_retained += retained
                insights.extend(ContentInsightRead.model_validate(i) for i in new_insights)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Bulk analysis failed for %s: %s", content.id, exc)
                db.rollback()
                warnings.append(f"Analysis failed for one item: {exc}")

    return IngestResponse(
        created=len(created_rows),
        skipped=skipped,
        insights_created=len(insights),
        memories_retained=memories_retained,
        memory_backend=backend,
        degraded=degraded,
        warnings=warnings,
        insights=insights[:100],
    )



@router.patch("/{content_id}", response_model=IngestResponse)
def update_content(
    content_id: int, 
    payload: ContentUpdate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> IngestResponse:
    """Update performance data �?" this is the OBSERVE RESULT step of the loop."""
    content = content_service.get_content(db, content_id)
    if content is None or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

    before_rate = content.engagement_rate
    content_service.update_content(db, content, payload)
    db.commit()

    warnings: list[str] = []
    insights: list[ContentInsightRead] = []
    memories_retained = 0
    backend = "none"
    degraded = False

    if payload.re_analyze:
        memory = MemoryService(db)
        try:
            avg = content_service.account_average_rate(db, current_user.id, exclude_id=content.id)
            new_insights, memories_retained, backend, degraded = memory.learn_from_content(content, avg)
            db.commit()
            insights = [ContentInsightRead.model_validate(i) for i in new_insights]

            delta_note = f" Updated from {before_rate:.4f} to {content.engagement_rate:.4f} engagement."
            for row in new_insights:
                if row.insight_type == "performance":
                    row.insight = row.insight.rstrip(".") + delta_note
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Re-analysis failed for %s: %s", content_id, exc)
            db.rollback()
            warnings.append(f"Re-analysis failed: {exc}")

        try:
            retained, backend, degraded = memory.learn_portfolio(user_id=current_user.id)
            memories_retained += retained
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.info("Portfolio learning skipped: %s", exc)
            db.rollback()


    return IngestResponse(
        created=1,
        skipped=0,
        insights_created=len(insights),
        memories_retained=memories_retained,
        memory_backend=backend,
        degraded=degraded,
        warnings=warnings,
        insights=insights,
    )



@router.post("/{content_id}/analyze", response_model=IngestResponse)
def analyze_content(
    content_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> IngestResponse:
    content = content_service.get_content(db, content_id)
    if content is None or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")

    try:
        avg = content_service.account_average_rate(db, current_user.id, exclude_id=content.id)
        insights, retained, backend, degraded = MemoryService(db).learn_from_content(content, avg)
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("Analyze failed: %s", exc)
        return IngestResponse(
            created=1,
            skipped=0,
            insights_created=0,
            memories_retained=0,
            memory_backend="local",
            degraded=True,
            warnings=[f"Analysis failed: {exc}"],
        )

    return IngestResponse(
        created=1,
        skipped=0,
        insights_created=len(insights),
        memories_retained=retained,
        memory_backend=backend,
        degraded=degraded,
        insights=[ContentInsightRead.model_validate(i) for i in insights],
    )



@router.get("/{content_id}/insights", response_model=list[ContentInsightRead])
def content_insights(
    content_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> list[ContentInsightRead]:
    content = content_service.get_content(db, content_id)
    if content is None or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    return content_service.insights_for(db, content_id)



@router.delete("/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_content(
    content_id: int, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> None:
    content = db.get(Content, content_id)
    if content is None or content.user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Content {content_id} not found")
    db.delete(content)
    db.commit()

