"""Health and system status — also powers the UI status banner."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy import text

from ...config import get_settings
from ...database import get_db
from ...models import Content, ContentInsight
from ...schemas import HealthResponse, MemoryStatus
from ...services.llm_service import get_llm_service
from ...services.memory_service import MemoryService

router = APIRouter()

VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse)
def health(db: Session = Depends(get_db)) -> HealthResponse:
    settings = get_settings()

    try:
        db.execute(text("SELECT 1"))
        db_ok = True
        content_count = db.scalar(select(func.count(Content.id))) or 0
        insight_count = db.scalar(select(func.count(ContentInsight.id))) or 0
        db_error = None
    except Exception as exc:  # noqa: BLE001
        db_ok, content_count, insight_count = False, 0, 0
        db_error = str(exc)[:200]

    try:
        memory_status: MemoryStatus = MemoryService(db).status()
    except Exception as exc:  # noqa: BLE001
        memory_status = MemoryStatus(
            backend="unavailable", available=False, degraded=True, message=str(exc)[:200]
        )

    return HealthResponse(
        status="ok" if db_ok else "degraded",
        version=VERSION,
        memory=memory_status,
        llm=get_llm_service().describe(),
        config=settings.safe_dict(),
        database={
            "connected": db_ok,
            "error": db_error,
            "content_count": content_count,
            "insight_count": insight_count,
        },
    )


@router.get("/status")
def status(db: Session = Depends(get_db)) -> dict:
    """Lightweight variant used for polling by the frontend."""
    health_payload = health(db=db)
    return {
        "status": health_payload.status,
        "version": health_payload.version,
        "memory": health_payload.memory.model_dump(),
        "llm": health_payload.llm,
        "content_count": health_payload.database["content_count"],
    }
