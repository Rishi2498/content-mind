"""Pydantic schemas.

Two families live here:

* ``*Request`` / ``*Response`` — the public HTTP contract.
* ``LLM*`` — strict JSON contracts handed to the LLM. Every LLM response is
  validated against one of these; a failure triggers exactly one corrective
  retry, then a safe deterministic fallback.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

InsightType = Literal["performance", "topic", "audience", "format", "tone", "strategy"]
MemoryKind = Literal[
    "content", "performance", "audience", "topic", "gap", "brand", "strategy", "format"
]


# --------------------------------------------------------------------------------------
# Shared building blocks
# --------------------------------------------------------------------------------------
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ContentMetricsMixin(BaseModel):
    engagement_count: int = 0
    engagement_rate: float = 0.0
    ctr: float = 0.0


# --------------------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------------------
class UserCreate(BaseModel):
    email: str = Field(..., pattern=r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")
    password: str = Field(..., min_length=8)

class UserRead(ORMModel):
    id: int
    email: str
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class TokenData(BaseModel):
    user_id: str | None = None

# --------------------------------------------------------------------------------------
# Content
# --------------------------------------------------------------------------------------
class ContentBase(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    body: str = ""
    platform: str = Field(default="LinkedIn", min_length=1, max_length=60)
    content_type: str = Field(default="article", min_length=1, max_length=60)
    topic: str = Field(default="General", min_length=1, max_length=120)
    audience: str = Field(default="", max_length=120)
    published_at: datetime | None = None
    impressions: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    shares: int = Field(default=0, ge=0)
    clicks: int = Field(default=0, ge=0)
    status: str = "published"

    @field_validator("title", "platform", "content_type", "topic")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class ContentCreate(ContentBase):
    analyze: bool = True


class ContentUpdate(BaseModel):
    impressions: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    clicks: int | None = Field(default=None, ge=0)
    published_at: datetime | None = None
    body: str | None = None
    audience: str | None = None
    re_analyze: bool = False


class ContentRead(ContentBase, ContentMetricsMixin, ORMModel):
    id: int
    source: str
    created_at: datetime
    updated_at: datetime
    insights: list["ContentInsightRead"] = Field(default_factory=list)


class ContentInsightRead(ORMModel):
    id: int
    content_id: int | None
    insight_type: str
    insight: str
    confidence: float
    source: str
    evidence: str
    memory_retained: bool
    created_at: datetime


class ContentListResponse(BaseModel):
    items: list[ContentRead]
    total: int
    limit: int
    offset: int


# --------------------------------------------------------------------------------------
# Memory
# --------------------------------------------------------------------------------------
class MemoryStatement(BaseModel):
    """A single sentence worth remembering long-term."""

    text: str = Field(min_length=5, max_length=600)
    kind: MemoryKind = "strategy"
    context: str = "ContentMind content performance history"


class MemoryRecord(BaseModel):
    id: str
    text: str
    type: str = "world"
    kind: str = "strategy"
    context: str | None = None
    entities: list[str] = Field(default_factory=list)
    score: float = 0.0
    document_id: str | None = None
    occurred_at: datetime | None = None
    backend: str = "hindsight"


class MemoryRecallResponse(BaseModel):
    query: str
    memories: list[MemoryRecord]
    backend: str
    degraded: bool = False
    total_available: int | None = None


class MemoryStatus(BaseModel):
    backend: str = "hindsight"
    available: bool = False
    degraded: bool = False
    configured: bool = False
    bank: str = ""
    memory_count: int = 0
    observation_count: int = 0
    document_count: int = 0
    last_error: str | None = None
    message: str = ""


# --------------------------------------------------------------------------------------
# Insights / "What I've Learned"
# --------------------------------------------------------------------------------------
class LearnedInsight(BaseModel):
    id: str
    text: str
    category: str  # audience | topics | formats | platforms | brand_voice | gaps | performance
    origin: str  # historical_performance | user_preference | content_history | hindsight_memory
    confidence: float = 0.5
    evidence: str = ""
    content_id: int | None = None
    created_at: datetime | None = None


class LearnedResponse(BaseModel):
    total: int = 0
    memory_count: int = 0
    content_analyzed: int = 0
    insights: list[LearnedInsight] = Field(default_factory=list)
    categories: dict[str, list[LearnedInsight]] = Field(default_factory=dict)
    degraded: bool = False
    message: str = ""


# --------------------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------------------
class GroupStat(BaseModel):
    key: str
    label: str
    count: int = 0
    impressions: int = 0
    engagements: int = 0
    avg_engagement_rate: float = 0.0
    median_engagement_rate: float = 0.0
    avg_ctr: float = 0.0
    index_vs_average: float = 1.0  # 1.0 == exactly the account average


class TopicCoverage(BaseModel):
    topic: str
    count: int
    last_published_at: datetime | None = None
    days_since_published: int | None = None
    avg_engagement_rate: float = 0.0
    performance_index: float = 1.0


class TimeSeriesPoint(BaseModel):
    period: str
    content_count: int = 0
    impressions: int = 0
    engagements: int = 0
    engagement_rate: float = 0.0


class ContentGap(BaseModel):
    topic: str
    reason: str
    priority: Literal["high", "medium", "low"]
    score: float
    coverage_count: int
    evidence: list[str] = Field(default_factory=list)
    suggested_formats: list[str] = Field(default_factory=list)
    adjacency: list[str] = Field(default_factory=list)


class GapResponse(BaseModel):
    gaps: list[ContentGap] = Field(default_factory=list)
    topics_covered: int = 0
    content_analyzed: int = 0
    method: str = ""
    note: str = ""


class AnalyticsResponse(BaseModel):
    content_count: int = 0
    published_with_metrics: int = 0
    total_impressions: int = 0
    total_engagements: int = 0
    total_clicks: int = 0
    avg_engagement_rate: float = 0.0
    median_engagement_rate: float = 0.0
    avg_ctr: float = 0.0
    top_topic: GroupStat | None = None
    top_platform: GroupStat | None = None
    top_content_type: GroupStat | None = None
    top_audience: GroupStat | None = None
    by_platform: list[GroupStat] = Field(default_factory=list)
    by_topic: list[GroupStat] = Field(default_factory=list)
    by_content_type: list[GroupStat] = Field(default_factory=list)
    by_audience: list[GroupStat] = Field(default_factory=list)
    topic_coverage: list[TopicCoverage] = Field(default_factory=list)
    over_time: list[TimeSeriesPoint] = Field(default_factory=list)
    best_content: list[ContentRead] = Field(default_factory=list)
    worst_content: list[ContentRead] = Field(default_factory=list)
    recent_content: list[ContentRead] = Field(default_factory=list)
    coverage_ratio: float = 0.0
    date_range: dict[str, datetime | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------------------
class PlanRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    posts_per_day: int = Field(default=1, ge=1, le=4)
    platforms: list[str] = Field(default_factory=list)
    campaign: str = ""
    notes: str = ""
    start_date: datetime | None = None
    date_range: str = ""
    title: str = ""
    force_learned: bool = False


class ContentPlanItemRead(ORMModel):
    id: int
    plan_id: int = 0
    position: int
    date: datetime
    platform: str
    topic: str
    format: str
    title: str
    description: str
    reason: str
    memory_used: list[Any] = Field(default_factory=list)


PlanItemRead = ContentPlanItemRead


class PlanRead(ORMModel):
    id: int
    title: str
    date_range: str
    strategy_summary: str
    request: str
    memory_count: int
    content_analyzed: int
    gaps_considered: list[Any] = Field(default_factory=list)
    used_memory: bool
    used_historical: bool
    memory_backend: str
    degraded: bool
    warnings: list[Any] = Field(default_factory=list)
    created_at: datetime
    items: list[PlanItemRead] = Field(default_factory=list)


class PlanListResponse(BaseModel):
    items: list[PlanRead]
    total: int


class PlanGenerateResponse(BaseModel):
    plan: PlanRead
    memory_used: list[MemoryRecord] = Field(default_factory=list)
    gaps: list[ContentGap] = Field(default_factory=list)
    context_summary: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


# --------------------------------------------------------------------------------------
# Chat
# --------------------------------------------------------------------------------------
class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: datetime | None = None
    memories_used: list[MemoryRecord] = Field(default_factory=list)
    degraded: bool = False


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    memories_used: list[MemoryRecord] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"] = "low"
    follow_ups: list[str] = Field(default_factory=list)
    content_analyzed: int = 0
    memory_count: int = 0
    degraded: bool = False
    notes: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Brand
# --------------------------------------------------------------------------------------
class BrandProfileRead(ORMModel):
    id: int
    brand_name: str
    target_audience: str
    tone: str
    preferred_formats: list[str] = Field(default_factory=list)
    preferred_platforms: list[str] = Field(default_factory=list)
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class BrandProfileUpsert(BaseModel):
    brand_name: str = Field(min_length=1, max_length=200)
    target_audience: str = ""
    tone: str = ""
    preferred_formats: list[str] = Field(default_factory=list)
    preferred_platforms: list[str] = Field(default_factory=list)
    description: str = ""
    learn_from_content: bool = True


# --------------------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------------------
class LLMExtractedInsight(BaseModel):
    insight_type: InsightType
    insight: str = Field(min_length=5, max_length=400)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=400)

    model_config = ConfigDict(extra="ignore")


class LLMContentAnalysis(BaseModel):
    insights: list[LLMExtractedInsight] = Field(default_factory=list, max_length=8)
    memories: list[MemoryStatement] = Field(default_factory=list, max_length=8)

    model_config = ConfigDict(extra="ignore")


class LLMPlanItem(BaseModel):
    date: str = Field(min_length=8, max_length=32)
    platform: str = Field(min_length=1, max_length=60)
    topic: str = Field(min_length=1, max_length=120)
    format: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=3, max_length=300)
    description: str = Field(default="", max_length=1200)
    reason: str = Field(min_length=10, max_length=800)
    memory_used: list[str] = Field(default_factory=list, max_length=6)

    model_config = ConfigDict(extra="ignore")


class LLMPlan(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    strategy_summary: str = Field(default="", max_length=2000)
    items: list[LLMPlanItem] = Field(min_length=1, max_length=60)
    caveats: list[str] = Field(default_factory=list, max_length=6)

    model_config = ConfigDict(extra="ignore")


class LLMStrategyAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=4000)
    memories_used: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"] = "low"
    follow_ups: list[str] = Field(default_factory=list, max_length=4)

    model_config = ConfigDict(extra="ignore")


class LLMBrandRead(BaseModel):
    target_audience: str = Field(default="", max_length=400)
    tone: str = Field(default="", max_length=400)
    preferred_formats: list[str] = Field(default_factory=list, max_length=8)
    preferred_platforms: list[str] = Field(default_factory=list, max_length=8)
    memories: list[MemoryStatement] = Field(default_factory=list, max_length=6)

    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------------------
# Ingestion / demo
# --------------------------------------------------------------------------------------
class IngestRequest(BaseModel):
    items: list[ContentCreate] = Field(min_length=1, max_length=200)
    remember: bool = True
    analyze: bool = True
    skip_duplicates: bool = True


class IngestResponse(BaseModel):
    created: int
    skipped: int
    insights_created: int
    memories_retained: int
    memory_backend: str
    degraded: bool = False
    warnings: list[str] = Field(default_factory=list)
    insights: list[ContentInsightRead] = Field(default_factory=list)


class DemoSeedRequest(BaseModel):
    records: int = Field(default=72, ge=10, le=200)
    remember: bool = True
    brand_name: str = "Northwind AI"
    reset_first: bool = False


class DemoSeedResponse(BaseModel):
    content_created: int
    insights_created: int
    memories_retained: int
    memory_backend: str
    bank: str
    degraded: bool
    warnings: list[str] = Field(default_factory=list)
    top_topics: list[str] = Field(default_factory=list)
    date_span: str = ""


class DemoResetResponse(BaseModel):
    content_deleted: int
    insights_deleted: int
    plans_deleted: int
    memory_backend: str
    bank_cleared: bool
    degraded: bool
    message: str = ""


class HealthResponse(BaseModel):
    status: str
    version: str
    memory: MemoryStatus
    llm: dict[str, Any]
    config: dict[str, Any]
    database: dict[str, Any]


# --------------------------------------------------------------------------------------
# Media (Phase 2)
# --------------------------------------------------------------------------------------
class MediaAssetRead(ORMModel):
    """Public view of an uploaded asset. Never exposes storage paths."""

    id: int
    filename: str
    mime_type: str
    file_size: int
    media_type: str
    status: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    content_id: int | None = None
    created_at: datetime
    has_dna: bool = False
    job_status: str | None = None


class MediaJobStep(BaseModel):
    """One pipeline step's outcome: ok | failed | skipped | degraded."""

    status: str = "skipped"
    detail: str = ""


class MediaJobRead(ORMModel):
    id: int
    asset_id: int
    job_type: str
    status: str
    error: str = ""
    steps: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    completed_at: datetime | None = None


class MediaAssetDetail(MediaAssetRead):
    """Asset detail including DNA and recent jobs."""

    dna: "ContentDNARead | None" = None
    jobs: list[MediaJobRead] = Field(default_factory=list)


class ContentDNARead(ORMModel):
    id: int
    asset_id: int
    content_id: int | None = None
    transcript: str = ""
    language: str = ""
    scene_description: str = ""
    ocr_text: str = ""
    visual_tags: list[str] = Field(default_factory=list)
    keyframe_analyses: list[dict[str, Any]] = Field(default_factory=list)
    keyframes: list[int] = Field(default_factory=list)  # keyframe indexes
    # NULL = not evaluated (Phase 3 implements real scoring)
    hook_score: float | None = None
    clarity_score: float | None = None
    brand_alignment: float | None = None
    created_at: datetime
    updated_at: datetime


class ContentFromMediaRequest(BaseModel):
    """Optional overrides when creating a Content record from a media asset."""

    title: str | None = Field(default=None, min_length=3, max_length=300)
    body: str | None = None
    platform: str | None = Field(default=None, min_length=1, max_length=60)
    topic: str | None = Field(default=None, min_length=1, max_length=120)
    analyze: bool = True


class MediaUploadResponse(BaseModel):
    asset: MediaAssetRead
    job: MediaJobRead
    warnings: list[str] = Field(default_factory=list)


class MediaAssetListResponse(BaseModel):
    items: list[MediaAssetRead]
    total: int
    limit: int = 25
    offset: int = 0


class MediaJobListResponse(BaseModel):
    items: list[MediaJobRead]
    total: int


# --------------------------------------------------------------------------------------
# LLM contracts for media analysis
# --------------------------------------------------------------------------------------
class LLMImageAnalysis(BaseModel):
    """Strict JSON contract for vision-LLM image analysis (scene + OCR)."""

    scene_description: str = ""
    ocr_text: str = ""
    visual_tags: list[str] = Field(default_factory=list)
    dominant_colors: list[str] = Field(default_factory=list)
    text_heavy: bool = False


class LLMMediaSynthesis(BaseModel):
    """Strict JSON contract for combining transcript + frames into a summary."""

    title_suggestion: str = ""
    topic: str = "General"
    summary: str = ""
    key_points: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Pre-Publish Reviewer (Phase 3)
# --------------------------------------------------------------------------------------
class ReviewerSuggestion(BaseModel):
    """One actionable piece of advice, justified by evidence."""

    category: str = "hook"  # hook | clarity | brand | structure | cta | topic
    severity: str = "improve"  # critical | improve | nice_to_have
    suggestion: str
    rationale: str = ""
    evidence: str = ""


class LLMReviewResult(BaseModel):
    """Strict JSON contract for the reviewer LLM."""

    hook_score: float = Field(default=50, ge=0, le=100)
    clarity_score: float = Field(default=50, ge=0, le=100)
    brand_alignment: float = Field(default=50, ge=0, le=100)
    summary: str = ""
    suggestions: list[ReviewerSuggestion] = Field(default_factory=list)


class ReviewerRequest(BaseModel):
    """A pre-publish draft to review."""

    title: str = Field(default="", max_length=300)
    body: str = Field(..., min_length=1, max_length=20000)
    platform: str = Field(default="", max_length=60)
    topic: str = Field(default="", max_length=120)
    content_id: int | None = None


class ReviewerResponse(BaseModel):
    """Scores + suggestions for one review. Not yet persisted."""

    hook_score: float
    clarity_score: float
    brand_alignment: float
    overall_score: float
    summary: str = ""
    suggestions: list[ReviewerSuggestion] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    degraded: bool = False
    engine: str = "heuristic"
    review_id: int | None = None


class ContentReviewRead(ORMModel):
    """A persisted review (immutable history for iteration tracking)."""

    id: int
    content_id: int | None = None
    asset_id: int | None = None
    source: str
    platform: str
    topic: str
    title: str
    draft_excerpt: str
    hook_score: float
    clarity_score: float
    brand_alignment: float
    overall_score: float
    suggestions: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    degraded: bool
    engine: str
    created_at: datetime


class ReviewerHistoryResponse(BaseModel):
    items: list[ContentReviewRead]
    total: int


# --------------------------------------------------------------------------------------
# Phase 4 — Performance intelligence (published posts + metric snapshots)
# --------------------------------------------------------------------------------------
class MetricSnapshotInput(BaseModel):
    """Manual metric entry. Every field is optional; omitted = unknown.

    Unknown (omitted/None) is deliberately distinct from a genuine 0.
    """

    views: int | None = Field(default=None, ge=0)
    impressions: int | None = Field(default=None, ge=0)
    likes: int | None = Field(default=None, ge=0)
    comments: int | None = Field(default=None, ge=0)
    shares: int | None = Field(default=None, ge=0)
    saves: int | None = Field(default=None, ge=0)
    link_clicks: int | None = Field(default=None, ge=0)
    watch_time_seconds: float | None = Field(default=None, ge=0)
    avg_watch_duration_seconds: float | None = Field(default=None, ge=0)
    audience_retention_pct: float | None = Field(default=None, ge=0, le=100)
    ctr_pct: float | None = Field(default=None, ge=0, le=100)
    source: Literal["manual", "platform"] = "manual"
    recorded_at: datetime | None = None


class MetricSnapshotRead(ORMModel):
    id: int
    source: str
    recorded_at: datetime
    days_since_published: int | None = None
    views: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    link_clicks: int | None = None
    watch_time_seconds: float | None = None
    avg_watch_duration_seconds: float | None = None
    audience_retention_pct: float | None = None
    ctr_pct: float | None = None


class PublishedPostCreate(BaseModel):
    """Register a published post. URL and external_id are untrusted input."""

    platform: str = Field(..., min_length=1, max_length=60)
    title: str = Field(default="", max_length=300)
    published_at: datetime
    url: str = Field(default="", max_length=1000)
    external_id: str = Field(default="", max_length=200)
    content_id: int | None = None
    media_asset_id: int | None = None
    initial_snapshot: MetricSnapshotInput | None = None


class PublishedPostUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    external_id: str | None = Field(default=None, max_length=200)
    status: Literal["published", "archived"] | None = None


class PublishedPostRead(ORMModel):
    id: int
    content_id: int | None = None
    media_asset_id: int | None = None
    platform: str
    title: str
    external_id: str
    url: str
    published_at: datetime
    status: str
    created_at: datetime
    snapshot_count: int = 0
    latest_snapshot: MetricSnapshotRead | None = None


class PublishedPostDetail(PublishedPostRead):
    snapshots: list[MetricSnapshotRead] = Field(default_factory=list)


class PublishedPostListResponse(BaseModel):
    items: list[PublishedPostRead]
    total: int


class PlatformAggregate(BaseModel):
    """Aggregated performance for one platform.

    Rate denominators are fixed per field (documented in PHASE4_IMPLEMENTATION.md):
    * avg_engagement_rate_per_view = mean of (likes+comments+shares)/views
      across posts whose latest snapshot reports views.
    * avg_engagement_rate_per_impression = mean of (likes+comments+shares)/impressions
      across posts whose latest snapshot reports impressions.
    Posts missing the denominator are excluded from that rate only.
    """

    platform: str
    post_count: int
    posts_with_metrics: int
    total_views: int | None = None  # None = no post on this platform reported views
    total_impressions: int | None = None
    avg_engagement_rate_per_view: float | None = None
    avg_engagement_rate_per_impression: float | None = None
    avg_ctr_pct: float | None = None  # mean of platform-reported ctr_pct only
    avg_retention_pct: float | None = None


class AttributeAggregate(BaseModel):
    """Performance grouped by a Content attribute (topic / content_type)."""

    key: str
    post_count: int
    posts_with_views: int
    avg_views: float | None = None
    avg_engagement_rate_per_view: float | None = None
    median_views: float | None = None


class SnapshotTimeSeriesPoint(BaseModel):
    """One daily bucket of metric snapshots (Phase 4)."""

    period: str  # ISO date of the snapshot day
    snapshot_count: int
    total_views: int | None = None
    total_impressions: int | None = None
    avg_engagement_rate_per_view: float | None = None


class PostComparison(BaseModel):
    """Side-by-side comparison of posts on the same platform.

    Only posts sharing a platform AND a comparable observation window
    (days_since_published of latest snapshot within `max_age_gap_days`)
    are compared. Incompatible posts are never mixed.
    """

    post_id: int
    title: str
    platform: str
    days_since_published: int | None = None
    views: int | None = None
    impressions: int | None = None
    engagement_count: int | None = None  # likes+comments+shares, None if all three unknown
    engagement_rate_per_view: float | None = None
    engagement_rate_per_impression: float | None = None


class PerformanceAnalyticsResponse(BaseModel):
    """Dashboard aggregate over the creator's published posts."""

    post_count: int
    posts_with_metrics: int
    date_range: dict[str, datetime | None] = Field(default_factory=dict)
    total_views: int | None = None
    total_impressions: int | None = None
    total_engagements: int | None = None
    avg_views: float | None = None
    avg_engagement_rate_per_view: float | None = None
    avg_engagement_rate_per_impression: float | None = None
    by_platform: list[PlatformAggregate] = Field(default_factory=list)
    by_topic: list[AttributeAggregate] = Field(default_factory=list)
    by_content_type: list[AttributeAggregate] = Field(default_factory=list)
    over_time: list[SnapshotTimeSeriesPoint] = Field(default_factory=list)
    top_posts: list[PostComparison] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------------------
# Phase 4 — Insights
# --------------------------------------------------------------------------------------
class InsightEvidence(BaseModel):
    """One supporting data point for an insight."""

    post_id: int | None = None
    title: str = ""
    platform: str = ""
    value: float | None = None
    note: str = ""


class PerformanceInsight(BaseModel):
    """An evidence-based finding about the creator's own published content.

    Every claim carries its sample size, the metric and comparison used,
    supporting evidence rows, limitations, and a confidence label:
    * strong   — ≥ 10 relevant posts, same platform / comparable windows
    * moderate — 5-9 relevant posts
    * weak     — 2-4 relevant posts (directional only)
    * insufficient — below the minimum sample; the finding is "need more data"
    """

    key: str  # stable identifier, e.g. "topic_performance", "review_vs_performance"
    finding: str
    posts_analyzed: int
    metric: str
    comparison: str
    confidence: Literal["strong", "moderate", "weak", "insufficient"]
    evidence: list[InsightEvidence] = Field(default_factory=list)
    observation_period: str = ""
    limitations: list[str] = Field(default_factory=list)
    recommendation: str = ""
    status: Literal["ok", "insufficient_data"] = "ok"


class InsightReportResponse(BaseModel):
    insights: list[PerformanceInsight] = Field(default_factory=list)
    posts_analyzed: int = 0
    posts_with_metrics: int = 0
    message: str = ""


# --------------------------------------------------------------------------------------
# Phase 5 — Content Strategy Agent
# --------------------------------------------------------------------------------------
STRATEGY_GOALS = ("education", "awareness", "community", "leads", "conversion")


class StrategyProfileUpsert(BaseModel):
    """Creator strategic preferences. All fields optional; empty = unset."""

    niche: str = Field(default="", max_length=300)
    topics: list[str] = Field(default_factory=list, max_length=30)
    target_audience: str = Field(default="", max_length=2000)
    audience_needs: str = Field(default="", max_length=2000)
    goals: list[str] = Field(default_factory=list, max_length=10)
    content_pillars: list[str] = Field(default_factory=list, max_length=15)
    avoid_topics: list[str] = Field(default_factory=list, max_length=30)
    publishing_frequency: str = Field(default="", max_length=60)
    constraints: str = Field(default="", max_length=2000)

    @field_validator("goals")
    @classmethod
    def _valid_goals(cls, v: list[str]) -> list[str]:
        allowed = set(STRATEGY_GOALS)
        bad = [g for g in v if g.strip().lower() not in allowed]
        if bad:
            raise ValueError(f"Unknown goal(s) {bad}; allowed: {sorted(allowed)}")
        return [g.strip().lower() for g in v]


class StrategyProfileRead(ORMModel):
    id: int
    niche: str
    topics: list[str] = Field(default_factory=list)
    target_audience: str
    audience_needs: str
    goals: list[str] = Field(default_factory=list)
    content_pillars: list[str] = Field(default_factory=list)
    avoid_topics: list[str] = Field(default_factory=list)
    publishing_frequency: str
    constraints: str
    feedback_preferences: list[str] = Field(default_factory=list)
    is_active: bool
    created_at: datetime
    updated_at: datetime


class StrategyGenerateRequest(BaseModel):
    """Generate a strategy + calendar for a planning period."""

    period: Literal["week", "month"] = "week"
    days: int | None = Field(default=None, ge=1, le=90)  # overrides period when set
    posts_per_week: int | None = Field(default=None, ge=1, le=21)
    platforms: list[str] = Field(default_factory=list, max_length=10)
    goals: list[str] = Field(default_factory=list, max_length=10)
    constraints: str = Field(default="", max_length=2000)
    start_date: datetime | None = None  # unset => relative sequencing (day 1, 2, ...)

    @field_validator("goals")
    @classmethod
    def _valid_goals(cls, v: list[str]) -> list[str]:
        allowed = set(STRATEGY_GOALS)
        bad = [g for g in v if g.strip().lower() not in allowed]
        if bad:
            raise ValueError(f"Unknown goal(s) {bad}; allowed: {sorted(allowed)}")
        return [g.strip().lower() for g in v]


class RecommendationRead(ORMModel):
    """A strategy recommendation with evidence metadata and creator state."""

    id: int
    plan_id: int | None = None
    sequence_day: int
    pillar: str
    topic: str
    format: str
    platform: str
    working_title: str
    hook: str
    audience: str
    objective: str
    cta: str
    production_notes: str
    is_hypothesis: bool
    reason: str
    evidence: list[str] = Field(default_factory=list)
    sample_size: int | None = None
    observation_period: str
    confidence: str
    success_metric: str
    test_method: str
    status: str
    edited_title: str
    edited_hook: str
    edited_notes: str
    feedback_note: str
    created_at: datetime
    updated_at: datetime


class RecommendationUpdate(BaseModel):
    """Creator edits and lifecycle transitions. All fields optional."""

    status: Literal["proposed", "accepted", "edited", "rejected", "deferred", "completed"] | None = None
    edited_title: str | None = Field(default=None, max_length=300)
    edited_hook: str | None = Field(default=None, max_length=2000)
    edited_notes: str | None = Field(default=None, max_length=4000)
    feedback_note: str | None = Field(default=None, max_length=2000)


class RecommendationListResponse(BaseModel):
    items: list[RecommendationRead] = Field(default_factory=list)
    total: int = 0


class StrategyGenerateResponse(BaseModel):
    """Generated strategy: recommendations + plan metadata."""

    plan_id: int | None = None
    period: str
    summary: str = ""
    recommendations: list[RecommendationRead] = Field(default_factory=list)
    evidence_sources: dict[str, Any] = Field(default_factory=dict)  # which sources were available
    warnings: list[str] = Field(default_factory=list)
    memory_degraded: bool = False


class ExperimentCreate(BaseModel):
    recommendation_id: int | None = None
    title: str = Field(default="", max_length=300)
    hypothesis: str = Field(default="", max_length=2000)
    variation: str = Field(default="", max_length=2000)
    intended_metric: str = Field(default="", max_length=120)


class ExperimentUpdate(BaseModel):
    status: Literal["planned", "running", "completed"] | None = None
    actual_result: str | None = Field(default=None, max_length=4000)
    result_note: str | None = Field(default=None, max_length=4000)


class ExperimentRead(ORMModel):
    id: int
    recommendation_id: int | None = None
    title: str
    hypothesis: str
    variation: str
    intended_metric: str
    status: str
    actual_result: str
    result_note: str
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class FeedbackRequest(BaseModel):
    """Feedback on a recommendation; optionally update preferences."""

    status: Literal["accepted", "rejected", "deferred", "completed"] | None = None
    note: str = Field(default="", max_length=2000)
    update_preferences: bool = False  # persist a preference statement to profile + memory


class LessonRead(BaseModel):
    """A learned lesson surfaced from memory + completed experiments."""

    text: str
    kind: str = ""
    confidence: str = "weak"
    evidence: list[str] = Field(default_factory=list)
    source: str = "memory"  # memory | experiment


class LessonsResponse(BaseModel):
    lessons: list[LessonRead] = Field(default_factory=list)
    message: str = ""
    memory_degraded: bool = False


# --------------------------------------------------------------------------------------
# Phase 6 — Instagram (Meta) Integration
# --------------------------------------------------------------------------------------
class InstagramAuthUrlResponse(BaseModel):
    authorize_url: str
    state: str  # base64-encoded state for CSRF verification


class InstagramCallbackRequest(BaseModel):
    code: str
    state: str


class InstagramConnectionRead(ORMModel):
    """Instagram connection view (no secrets)."""

    id: int
    instagram_account_id: str
    username: str
    account_type: str
    media_count: int | None = None
    followers_count: int | None = None
    follows_count: int | None = None
    profile_picture_url: str
    status: str
    scopes: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    last_refreshed_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_sync_status: str
    last_sync_error: str
    created_at: datetime
    updated_at: datetime


class InstagramConnectionListResponse(BaseModel):
    items: list[InstagramConnectionRead] = Field(default_factory=list)
    total: int = 0


class InstagramSyncJobRead(ORMModel):
    id: int
    connection_id: int
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    posts_examined: int
    posts_imported: int
    snapshots_created: int
    error_category: str
    error_message: str
    created_at: datetime


class InstagramSyncJobListResponse(BaseModel):
    items: list[InstagramSyncJobRead] = Field(default_factory=list)
    total: int = 0


class InstagramSyncTriggerRequest(BaseModel):
    max_posts: int | None = Field(default=None, ge=1, le=200)


class InstagramSyncTriggerResponse(BaseModel):
    job: InstagramSyncJobRead
    connection_id: int


class InstagramPostRead(ORMModel):
    """Instagram post imported as PublishedPost."""

    id: int
    external_id: str
    platform: str
    title: str
    url: str
    published_at: datetime
    status: str
    snapshot_count: int = 0
    latest_snapshot: MetricSnapshotRead | None = None


class InstagramPostListResponse(BaseModel):
    items: list[InstagramPostRead] = Field(default_factory=list)
    total: int = 0
    limit: int = 25
    offset: int = 0


class InstagramAccountInsightsRead(BaseModel):
    """Account-level insights from Meta API."""

    account_id: str
    username: str
    period: str  # day, week, days_28
    impressions: int | None = None
    reach: int | None = None
    profile_views: int | None = None
    follower_count: int | None = None
    website_clicks: int | None = None
    collected_at: datetime


ContentRead.model_rebuild()
MediaAssetDetail.model_rebuild()
