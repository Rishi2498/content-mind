"""Analytics functions for ContentMind.

Re-exported from :mod:`~app.services.analytics_service` for convenience.
"""
from __future__ import annotations

from .services.analytics_service import click_through_rate as ctr
from .services.analytics_service import engagement_rate
from .services.analytics_service import performance_index

__all__ = ["engagement_rate", "ctr", "performance_index"]