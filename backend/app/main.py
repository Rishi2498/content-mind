"""ContentMind API — a memory-powered content strategy system.

Your content strategy remembers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.router import router
from .config import get_settings
from .database import init_db
from .services.scheduler import get_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
# Third-party HTTP chatter drowns out our own request logs.
for noisy in ("httpx", "httpcore", "urllib3"):
    logging.getLogger(noisy).setLevel(logging.WARNING)
logger = logging.getLogger("contentmind")

settings = get_settings()


def _log_production_readiness() -> None:
    """Log production readiness status."""
    from app.config_production import check_production_readiness, get_missing_production_config
    
    checks = check_production_readiness()
    missing = get_missing_production_config()
    
    if settings.environment == "production":
        if missing:
            logger.warning("Production configuration incomplete. Missing: %s", ", ".join(missing))
        else:
            logger.info("Production configuration validated successfully")
    else:
        logger.info("Running in %s mode. Production checks: %s", 
                   settings.environment, 
                   {k: v for k, v in checks.items()})


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("%s API starting (env=%s)", settings.app_name, settings.environment)
    _log_production_readiness()
    
    if not settings.hindsight_configured:
        logger.warning(
            "HINDSIGHT_API_URL is not set - memory will run on the local fallback backend."
        )
    if not settings.llm_configured:
        if settings.llm_provider == "gemini":
            logger.warning(
                "LLM_PROVIDER=gemini but GEMINI_API_KEY is not set - generation will "
                "use the deterministic engine."
            )
        else:
            logger.warning(
                "LLM provider is not configured - generation will use the deterministic engine."
            )
    if not settings.instagram_configured:
        logger.warning("Instagram integration not configured - Instagram features disabled.")
    else:
        instagram_hints = settings.instagram_config_warnings()
        for hint in instagram_hints:
            logger.warning("Instagram OAuth config: %s", hint)
        if instagram_hints:
            logger.warning(
                "Instagram OAuth reminder: register the exact redirect URI under Meta App "
                "Dashboard > Instagram > API setup with Instagram login > 3. Set up Instagram "
                "business login > Business login settings > OAuth redirect URIs (NOT the "
                "Facebook Login 'Valid OAuth Redirect URIs'), and set INSTAGRAM_APP_ID to the "
                "Instagram App ID, not the Meta App ID."
            )
    if settings.secret_key_is_default:
        logger.warning(
            "SECRET_KEY is empty or still the built-in development default - JWTs and "
            "Instagram OAuth state can be forged. Set a strong random SECRET_KEY."
        )

    # Recover media jobs stuck in processing from a previous crash/restart.
    try:
        from .database import session_scope
        from .services.media_service import recover_stale_jobs

        with session_scope() as db:
            recovered = recover_stale_jobs(db)
            if recovered:
                logger.warning("Marked %s stale media job(s) as failed on startup.", recovered)
    except Exception as exc:  # noqa: BLE001 - recovery must never block startup
        logger.warning("Media job recovery skipped: %s", exc)
    
    # Start background scheduler
    scheduler = get_scheduler()
    scheduler.start()
    logger.info("Background scheduler started")
    
    yield
    
    # Shutdown background scheduler
    scheduler.shutdown()
    from .services.hindsight_service import get_hindsight_service

    get_hindsight_service().close()
    logger.info("%s API stopped", settings.app_name)


app = FastAPI(
    title="ContentMind API",
    description=(
        "Memory-powered content strategy. Uses Hindsight by Vectorize as the long-term "
        "memory layer, a relational database for structured facts, and an LLM for reasoning."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins) or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix=settings.api_prefix)


@app.get("/", tags=["health"])
def root() -> dict:
    return {
        "name": settings.app_name,
        "tagline": settings.tagline,
        "docs": "/docs",
        "api": settings.api_prefix,
    }


@app.get("/health", tags=["health"])
def health_check() -> dict:
    """Health check endpoint for load balancers."""
    from .database import engine
    from sqlalchemy import text
    
    db_healthy = False
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_healthy = True
    except Exception:
        pass
    
    from .services.hindsight_service import get_hindsight_service
    hindsight = get_hindsight_service()
    
    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
        "memory": hindsight.status(),
        "environment": settings.environment,
    }


@app.get("/health/ready", tags=["health"])
def readiness_check() -> dict:
    """Readiness check - verifies all critical dependencies."""
    from .database import engine
    from sqlalchemy import text
    
    checks = {}
    
    # Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = "ready"
    except Exception:
        checks["database"] = "not ready"
    
    # Memory backend
    from .services.hindsight_service import get_hindsight_service
    hindsight = get_hindsight_service()
    checks["memory"] = "ready" if hindsight.status().get("available") else "degraded"
    
    all_ready = all(v == "ready" for v in checks.values())
    
    return {
        "ready": all_ready,
        "checks": checks,
    }


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An unexpected error occurred.",
            "error_type": type(exc).__name__,
            "path": request.url.path,
        },
    )
