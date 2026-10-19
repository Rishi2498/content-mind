"""Background job scheduler for ContentMind.

Uses APScheduler for reliable, persistent job scheduling.
Supports both SQLite (development) and PostgreSQL (production) job stores.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings
from ..database import engine

logger = logging.getLogger("contentmind.scheduler")


class ContentMindScheduler:
    """Wrapper around APScheduler for ContentMind background jobs."""
    
    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.settings = get_settings()
        self._job_defaults = {
            "coalesce": True,  # Combine missed runs into one
            "max_instances": 1,  # Don't run multiple instances of same job
            "misfire_grace_time": 300,  # 5 minutes grace time for missed runs
        }
    
    def start(self) -> None:
        """Start the scheduler."""
        if self.scheduler is not None:
            logger.warning("Scheduler already started")
            return
        
        # Configure job store
        jobstores = {
            "default": SQLAlchemyJobStore(engine=engine)
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            job_defaults=self._job_defaults,
            timezone="UTC",
        )
        
        self.scheduler.start()
        logger.info("Background scheduler started")
    
    def shutdown(self) -> None:
        """Shutdown the scheduler."""
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=True)
            self.scheduler = None
            logger.info("Background scheduler stopped")
    
    def add_instagram_sync_job(
        self,
        connection_id: int,
        user_id: int,
        interval_seconds: Optional[int] = None,
    ) -> str:
        """Add or update an Instagram sync job for a connection."""
        if self.scheduler is None:
            raise RuntimeError("Scheduler not started")
        
        interval = interval_seconds or self.settings.instagram_sync_cooldown_seconds
        job_id = f"instagram_sync_{connection_id}"
        
        # Remove existing job if exists
        existing = self.scheduler.get_job(job_id)
        if existing:
            existing.remove()
        
        # Import here to avoid circular imports
        from .instagram_service import InstagramService
        from ..database import SessionLocal
        
        def sync_job():
            """Wrapper to run sync in a new DB session."""
            db = SessionLocal()
            try:
                svc = InstagramService(db, user_id)
                svc.run_full_sync(connection_id)
            except Exception as e:
                logger.exception("Scheduled Instagram sync failed for connection %s: %s", 
                               connection_id, e)
            finally:
                db.close()
        
        self.scheduler.add_job(
            sync_job,
            trigger=IntervalTrigger(seconds=interval),
            id=job_id,
            name=f"Instagram sync for connection {connection_id}",
            replace_existing=True,
        )
        
        logger.info("Added Instagram sync job for connection %s (interval: %ss)", 
                   connection_id, interval)
        return job_id
    
    def remove_instagram_sync_job(self, connection_id: int) -> bool:
        """Remove an Instagram sync job."""
        if self.scheduler is None:
            return False
        
        job_id = f"instagram_sync_{connection_id}"
        job = self.scheduler.get_job(job_id)
        if job:
            job.remove()
            logger.info("Removed Instagram sync job for connection %s", connection_id)
            return True
        return False
    
    def get_job_status(self, connection_id: int) -> Optional[dict]:
        """Get status of a scheduled job."""
        if self.scheduler is None:
            return None
        
        job_id = f"instagram_sync_{connection_id}"
        job = self.scheduler.get_job(job_id)
        if not job:
            return None
        
        return {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        }
    
    def list_jobs(self) -> list[dict]:
        """List all scheduled jobs."""
        if self.scheduler is None:
            return []
        
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs


# Global scheduler instance
_scheduler: Optional[ContentMindScheduler] = None


def get_scheduler() -> ContentMindScheduler:
    """Get the global scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = ContentMindScheduler()
    return _scheduler


@asynccontextmanager
async def lifespan_scheduler(app):
    """FastAPI lifespan context manager for the scheduler."""
    scheduler = get_scheduler()
    scheduler.start()
    try:
        yield
    finally:
        scheduler.shutdown()