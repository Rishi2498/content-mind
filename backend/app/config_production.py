"""Production configuration for ContentMind.

This module provides production-ready settings that override development defaults.
All secrets must be provided via environment variables.
"""

from __future__ import annotations

from app.config import get_settings

settings = get_settings()

# Production-specific overrides
PRODUCTION_CHECKS = {
    "instagram_configured": settings.instagram_configured,
    "hindsight_configured": settings.hindsight_configured,
    "llm_configured": settings.llm_configured,
    "secret_key_changed": not settings.secret_key_is_default,
    "database_not_sqlite": not settings.database_url.startswith("sqlite"),
    "cors_restricted": len(settings.cors_origins) > 0 and not any(
        "localhost" in o or "127.0.0.1" in o for o in settings.cors_origins
    ),
}


def check_production_readiness() -> dict[str, bool]:
    """Return a dictionary of production readiness checks."""
    return PRODUCTION_CHECKS


def get_missing_production_config() -> list[str]:
    """Return a list of missing production configuration items."""
    missing = []
    checks = check_production_readiness()
    for key, value in checks.items():
        if not value:
            missing.append(key)
    return missing


def validate_production_config() -> None:
    """Validate production configuration and raise if not ready."""
    missing = get_missing_production_config()
    if missing:
        raise RuntimeError(
            f"Production configuration incomplete. Missing: {', '.join(missing)}"
        )