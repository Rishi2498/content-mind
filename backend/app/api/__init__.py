"""Thin HTTP layer. All business logic lives in ``app/services``."""

from .router import router

__all__ = ["router"]
