"""API router aggregation."""

from __future__ import annotations

from fastapi import APIRouter

from .routes import (
    analytics,
    brand,
    chat,
    content,
    demo,
    health,
    instagram,
    media,
    memory,
    performance,
    plans,
    auth,
    reviewer,
    strategy,
)


router = APIRouter()
router.include_router(auth.router, tags=["auth"])
router.include_router(health.router, tags=["health"])
router.include_router(content.router, prefix="/content", tags=["content"])

router.include_router(analytics.router, prefix="/analytics", tags=["analytics"])
router.include_router(plans.router, prefix="/plans", tags=["plans"])
router.include_router(memory.router, prefix="/memory", tags=["memory"])
router.include_router(chat.router, prefix="/chat", tags=["chat"])
router.include_router(brand.router, prefix="/brand", tags=["brand"])
router.include_router(demo.router, prefix="/demo", tags=["demo"])
router.include_router(media.router, prefix="/media", tags=["media"])
router.include_router(reviewer.router, prefix="/reviewer", tags=["reviewer"])
router.include_router(performance.router, prefix="/performance", tags=["performance"])
router.include_router(strategy.router, prefix="/strategy", tags=["strategy"])
router.include_router(instagram.router, prefix="/instagram", tags=["instagram"])
