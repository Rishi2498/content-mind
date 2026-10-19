"""Relational models: structured facts only.

Hindsight stores semantic memory. This database stores measurable records.
The two are never mixed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Content(Base):
    __tablename__ = "content"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    body: Mapped[str] = mapped_column(Text, default="")
    platform: Mapped[str] = mapped_column(String(60), nullable=False, default="LinkedIn")
    content_type: Mapped[str] = mapped_column(String(60), nullable=False, default="article")
    topic: Mapped[str] = mapped_column(String(120), nullable=False, default="General")
    audience: Mapped[str] = mapped_column(String(120), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    impressions: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)

    engagement_rate: Mapped[float] = mapped_column(Float, default=0.0)
    ctr: Mapped[float] = mapped_column(Float, default=0.0)
    engagement_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(30), default="published")
    source: Mapped[str] = mapped_column(String(30), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    insights: Mapped[list["ContentInsight"]] = relationship(
        back_populates="content", cascade="all, delete-orphan", lazy="selectin"
    )

    __table_args__ = (
        Index("ix_content_published_at", "published_at"),
        Index("ix_content_topic", "topic"),
        Index("ix_content_platform", "platform"),
    )


class ContentInsight(Base):
    __tablename__ = "content_insight"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("content.id", ondelete="CASCADE"), nullable=True, index=True
    )

    insight_type: Mapped[str] = mapped_column(String(30), nullable=False)
    insight: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(30), default="historical_performance")
    evidence: Mapped[str] = mapped_column(Text, default="")
    memory_retained: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    content: Mapped["Content | None"] = relationship(back_populates="insights")

    __table_args__ = (Index("ix_insight_type", "insight_type"),)


class ContentPlan(Base):
    __tablename__ = "content_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)

    date_range: Mapped[str] = mapped_column(String(80), default="")
    strategy_summary: Mapped[str] = mapped_column(Text, default="")
    request: Mapped[str] = mapped_column(Text, default="")
    memory_count: Mapped[int] = mapped_column(Integer, default=0)
    content_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    gaps_considered: Mapped[list] = mapped_column(JSON, default=list)
    used_memory: Mapped[bool] = mapped_column(Boolean, default=False)
    used_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    memory_backend: Mapped[str] = mapped_column(String(40), default="none")
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    items: Mapped[list["ContentPlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin",
        order_by="ContentPlanItem.position",
    )


class ContentPlanItem(Base):
    __tablename__ = "content_plan_item"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("content_plan.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    platform: Mapped[str] = mapped_column(String(60), default="LinkedIn")
    topic: Mapped[str] = mapped_column(String(120), default="")
    format: Mapped[str] = mapped_column(String(60), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    memory_used: Mapped[list] = mapped_column(JSON, default=list)

    plan: Mapped["ContentPlan"] = relationship(back_populates="items")


class BrandProfile(Base):
    __tablename__ = "brand_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    brand_name: Mapped[str] = mapped_column(String(200), default="Our Company")

    target_audience: Mapped[str] = mapped_column(Text, default="")
    tone: Mapped[str] = mapped_column(Text, default="")
    preferred_formats: Mapped[list] = mapped_column(JSON, default=list)
    preferred_platforms: Mapped[list] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class MemoryEvent(Base):
    """Audit trail of every write to the long-term memory layer.

    Lets the UI show *when* the agent learned something, and lets tests assert
    that the remember/recall loop actually ran.
    """

    __tablename__ = "memory_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)  # remember | recall

    backend: Mapped[str] = mapped_column(String(40), default="hindsight")
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    count: Mapped[int] = mapped_column(Integer, default=0)
    related_content_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlanResult(Base):
    """Performance fed back after a plan was published.

    Closing the loop: a plan item is executed, results are recorded, and the
    agent learns from the delta.
    """

    __tablename__ = "plan_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("content_plan.id", ondelete="CASCADE"))

    plan_item_id: Mapped[int] = mapped_column(ForeignKey("content_plan_item.id", ondelete="CASCADE"))
    content_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted: Mapped[str] = mapped_column(Text, default="")
    outcome_note: Mapped[str] = mapped_column(Text, default="")
    learned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DailyMetric(Base):
    """Small pre-aggregated table for the analytics time series."""

    __tablename__ = "daily_metric"
    __table_args__ = (UniqueConstraint("user_id", "day", name="uq_daily_metric_user_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[datetime] = mapped_column(Date, nullable=False)

    content_count: Mapped[int] = mapped_column(Integer, default=0)
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    engagements: Mapped[int] = mapped_column(Integer, default=0)


class MediaAsset(Base):
    """One uploaded media file (video, image, or audio) owned by a user."""

    __tablename__ = "media_asset"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(300), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(300), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), default="application/octet-stream")
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # video | image | audio
    status: Mapped[str] = mapped_column(String(20), default="uploaded")  # uploaded|processing|ready|failed

    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)

    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("content.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    dna: Mapped["ContentDNA | None"] = relationship(
        back_populates="asset", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )
    jobs: Mapped[list["MediaJob"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", lazy="selectin"
    )


class MediaJob(Base):
    """Processing audit trail for a media asset with step-level results."""

    __tablename__ = "media_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_asset.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(20), default="full")  # full|transcribe|vision|metadata
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|processing|completed|failed
    error: Mapped[str] = mapped_column(Text, default="")
    # Per-step results: {"ffmpeg": {"status": "ok|failed|skipped", "detail": ...}, "whisper": {...}, ...}
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["MediaAsset"] = relationship(back_populates="jobs")


class ContentDNA(Base):
    """Structured representation of a media asset's content.

    Combines transcript, visual analysis of keyframes, and metadata into a
    single record. Reviewer scores are NULL until Phase 3 implements real
    scoring — NULL means "not evaluated", not zero.
    """

    __tablename__ = "content_dna"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("media_asset.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("content.id", ondelete="SET NULL"), nullable=True, index=True
    )

    transcript: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(20), default="")
    scene_description: Mapped[str] = mapped_column(Text, default="")
    ocr_text: Mapped[str] = mapped_column(Text, default="")
    visual_tags: Mapped[list] = mapped_column(JSON, default=list)
    keyframe_analyses: Mapped[list] = mapped_column(JSON, default=list)
    keyframes: Mapped[list] = mapped_column(JSON, default=list)
    audio_path: Mapped[str] = mapped_column(String(500), default="")

    # Phase 3 reviewer scores: NULL = not evaluated (explicitly not zero).
    hook_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    clarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    brand_alignment: Mapped[float | None] = mapped_column(Float, nullable=True)

    raw_analysis: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    asset: Mapped["MediaAsset"] = relationship(back_populates="dna")


class ContentReview(Base):
    """One pre-publish review of a draft (text) or a media asset's DNA.

    Scores are 0-100. Suggestions carry category, the advice itself, and the
    evidence (learned memory statements or brand rules) that justify it.
    Reviews are immutable history so the UI can show iteration progress.
    """

    __tablename__ = "content_review"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("content.id", ondelete="SET NULL"), nullable=True, index=True
    )
    asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_asset.id", ondelete="SET NULL"), nullable=True, index=True
    )

    source: Mapped[str] = mapped_column(String(20), default="draft")  # draft | media
    platform: Mapped[str] = mapped_column(String(60), default="")
    topic: Mapped[str] = mapped_column(String(120), default="")
    title: Mapped[str] = mapped_column(String(300), default="")
    draft_excerpt: Mapped[str] = mapped_column(Text, default="")

    hook_score: Mapped[float] = mapped_column(Float, default=0.0)
    clarity_score: Mapped[float] = mapped_column(Float, default=0.0)
    brand_alignment: Mapped[float] = mapped_column(Float, default=0.0)
    overall_score: Mapped[float] = mapped_column(Float, default=0.0)

    suggestions: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    engine: Mapped[str] = mapped_column(String(20), default="heuristic")  # llm | heuristic

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PublishedPost(Base):
    """A post the creator published on a platform, registered manually.

    Optionally linked to existing Content or MediaAsset records so analytics
    can join performance against ContentDNA and pre-publish reviews. The link
    is never required — a post may predate ContentMind.
    """

    __tablename__ = "published_post"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    content_id: Mapped[int | None] = mapped_column(
        ForeignKey("content.id", ondelete="SET NULL"), nullable=True, index=True
    )
    media_asset_id: Mapped[int | None] = mapped_column(
        ForeignKey("media_asset.id", ondelete="SET NULL"), nullable=True, index=True
    )

    platform: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(300), default="")
    external_id: Mapped[str] = mapped_column(String(200), default="")
    url: Mapped[str] = mapped_column(String(1000), default="")
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="published")  # published | archived

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    snapshots: Mapped[list["MetricSnapshot"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", lazy="selectin",
        order_by="MetricSnapshot.recorded_at",
    )

    __table_args__ = (
        Index("ix_published_post_platform", "platform"),
        Index("ix_published_post_published_at", "published_at"),
    )


class MetricSnapshot(Base):
    """One dated reading of a published post's performance metrics.

    Every metric is nullable: NULL means "unknown / not collected" and is
    never coerced to zero. A genuine zero is recorded as 0. Snapshots are
    append-only — later readings never overwrite history.
    """

    __tablename__ = "metric_snapshot"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(
        ForeignKey("published_post.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)

    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | platform
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Period since publication at the time of recording, when calculable.
    days_since_published: Mapped[int | None] = mapped_column(Integer, nullable=True)

    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    impressions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True)
    saves: Mapped[int | None] = mapped_column(Integer, nullable=True)
    link_clicks: Mapped[int | None] = mapped_column(Integer, nullable=True)

    watch_time_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_watch_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Percentage 0-100. NULL = platform does not provide it.
    audience_retention_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Click-through rate 0-100 as reported by the platform. NULL = not provided.
    ctr_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    post: Mapped["PublishedPost"] = relationship(back_populates="snapshots")


class InstagramConnection(Base):
    """Instagram (Instagram Professional) connection for an authenticated user.

    Access tokens are stored encrypted at rest if an encryption key is configured.
    The raw token is never returned by API schemas.
    """

    __tablename__ = "instagram_connection"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    instagram_account_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(80), default="")
    account_type: Mapped[str] = mapped_column(String(40), default="")  # e.g. "BUSINESS", "CREATOR"
    media_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    follows_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_picture_url: Mapped[str] = mapped_column(String(1000), default="")

    status: Mapped[str] = mapped_column(String(20), default="connected")  # connected, disconnected, error
    scopes: Mapped[list] = mapped_column(JSON, default=list)

    # Encrypted access token (base64-encoded encrypted blob)
    access_token_encrypted: Mapped[str] = mapped_column(Text, default="")
    token_type: Mapped[str] = mapped_column(String(20), default="bearer")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_status: Mapped[str] = mapped_column(String(40), default="never")
    last_sync_error: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    __table_args__ = (
        UniqueConstraint("user_id", "instagram_account_id", name="uq_instagram_user_account"),
    )


class InstagramSyncJob(Base):
    """Sync job metadata for observability."""

    __tablename__ = "instagram_sync_job"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(
        ForeignKey("instagram_connection.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(30), default="pending")  # pending, running, succeeded, partially_succeeded, failed
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posts_examined: Mapped[int] = mapped_column(Integer, default=0)
    posts_imported: Mapped[int] = mapped_column(Integer, default=0)
    snapshots_created: Mapped[int] = mapped_column(Integer, default=0)
    error_category: Mapped[str] = mapped_column(String(60), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StrategyProfile(Base):
    """Creator-specific strategic preferences (Phase 5).

    BrandProfile already stores brand voice, tone, preferred formats and
    platforms. This table stores only what BrandProfile does NOT have:
    niche/topics, goals, pillars, constraints, avoid-lists, frequency, and
    rolling feedback preferences. One active profile per user.
    """

    __tablename__ = "strategy_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    niche: Mapped[str] = mapped_column(String(300), default="")
    topics: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    target_audience: Mapped[str] = mapped_column(Text, default="")
    audience_needs: Mapped[str] = mapped_column(Text, default="")
    goals: Mapped[list] = mapped_column(JSON, default=list)  # education|awareness|community|leads|conversion
    content_pillars: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    avoid_topics: Mapped[list] = mapped_column(JSON, default=list)  # list[str]
    publishing_frequency: Mapped[str] = mapped_column(String(60), default="")  # e.g. "3/week"
    constraints: Mapped[str] = mapped_column(Text, default="")
    # Rolling preference learned from accept/reject feedback (explicit, not inferred).
    feedback_preferences: Mapped[list] = mapped_column(JSON, default=list)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class StrategyRecommendation(Base):
    """One recommendation produced by the strategy agent (Phase 5).

    Immutable generation-time fields (evidence, confidence, hypothesis flag)
    are never rewritten. Creator edits land in the `edited_*` columns and the
    `status` lifecycle (proposed -> accepted|edited|rejected|deferred ->
    completed) so regeneration never silently overwrites creator work.
    """

    __tablename__ = "strategy_recommendation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("content_plan.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Generation-time content (immutable after creation)
    sequence_day: Mapped[int] = mapped_column(Integer, default=0)  # relative day within the plan period
    pillar: Mapped[str] = mapped_column(String(120), default="")
    topic: Mapped[str] = mapped_column(String(120), default="")
    format: Mapped[str] = mapped_column(String(60), default="")
    platform: Mapped[str] = mapped_column(String(60), default="")
    working_title: Mapped[str] = mapped_column(String(300), default="")
    hook: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(String(300), default="")
    objective: Mapped[str] = mapped_column(String(120), default="")
    cta: Mapped[str] = mapped_column(String(300), default="")
    production_notes: Mapped[str] = mapped_column(Text, default="")

    # Evidence vs hypothesis (never rewritten)
    is_hypothesis: Mapped[bool] = mapped_column(Boolean, default=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[list] = mapped_column(JSON, default=list)  # list[str] references
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    observation_period: Mapped[str] = mapped_column(String(120), default="")
    confidence: Mapped[str] = mapped_column(String(20), default="insufficient")  # strong|moderate|weak|insufficient
    success_metric: Mapped[str] = mapped_column(String(300), default="")
    test_method: Mapped[str] = mapped_column(Text, default="")

    # Creator lifecycle + edits
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|accepted|edited|rejected|deferred|completed
    edited_title: Mapped[str] = mapped_column(String(300), default="")
    edited_hook: Mapped[str] = mapped_column(Text, default="")
    edited_notes: Mapped[str] = mapped_column(Text, default="")
    feedback_note: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Experiment(Base):
    """A tracked experiment derived from a recommendation (Phase 5).

    Records the hypothesis, the variation, the intended metric and the
    eventual actual result. A completed experiment is an observation — it is
    never described as proof of causality.
    """

    __tablename__ = "experiment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    recommendation_id: Mapped[int | None] = mapped_column(
        ForeignKey("strategy_recommendation.id", ondelete="SET NULL"), nullable=True, index=True
    )

    title: Mapped[str] = mapped_column(String(300), default="")
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    variation: Mapped[str] = mapped_column(Text, default="")  # what was changed vs the control
    intended_metric: Mapped[str] = mapped_column(String(120), default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")  # planned|running|completed
    actual_result: Mapped[str] = mapped_column(Text, default="")
    result_note: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
