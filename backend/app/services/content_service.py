"""Content ingestion, metric calculation and insight extraction."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..models import Content
from ..schemas import (
    ContentCreate,
    ContentInsightRead,
    ContentListResponse,
    ContentRead,
    ContentUpdate,
    LLMContentAnalysis,
    LLMExtractedInsight,
)
from .analytics_service import engagement_count, engagement_rate, click_through_rate
from .llm_service import get_llm_service

logger = logging.getLogger("contentmind.content")

PERFORMANCE_PROMPT = """You are the analyst inside ContentMind, a content strategy memory system.

You are given ONE published content record plus the account's average engagement rate.
Extract only what the record actually supports. Never invent numbers.

Rules:
- insight_type must be one of: performance, topic, audience, format, tone, strategy.
- Each insight must be a single self-contained sentence that will still make sense a year
  from now, written in third person about "this company".
- Use "appears to", "suggests" or "based on a single item" when evidence is thin.
- Never state certainty about future performance.
- confidence is 0.0-1.0 reflecting how much data supports the claim.
- 'memories' are the durable statements worth retaining long-term. Include the comparative
  performance sentence and any audience/format signal.
- If the record has no impressions, produce at most one topic observation and set
  confidence below 0.4.
"""


# ----------------------------------------------------------------------------------
# Metric calculation
# ----------------------------------------------------------------------------------
def apply_metrics(content: Content) -> Content:
    content.engagement_count = engagement_count(content.likes, content.comments, content.shares)
    content.engagement_rate = engagement_rate(
        content.likes, content.comments, content.shares, content.impressions
    )
    content.ctr = click_through_rate(content.clicks, content.impressions)
    return content


def account_average_rate(db: Session, user_id: int, exclude_id: int | None = None) -> float:
    stmt = select(Content.engagement_rate, Content.impressions).where(
        Content.user_id == user_id, 
        Content.impressions > 0
    )
    if exclude_id is not None:
        stmt = stmt.where(Content.id != exclude_id)
    rows = db.execute(stmt).all()
    if not rows:
        return 0.0
    return sum(r[0] for r in rows) / len(rows)



# ----------------------------------------------------------------------------------
# Deterministic insight extraction (fallback + corpus seed)
# ----------------------------------------------------------------------------------
def heuristic_insights(content: Content, account_avg_rate: float) -> list[LLMExtractedInsight]:
    insights: list[LLMExtractedInsight] = []
    rate = content.engagement_rate
    ratio = (rate / account_avg_rate) if account_avg_rate else 0.0

    if content.impressions:
        if ratio >= 1.4:
            verdict, conf = "significantly above", min(0.95, 0.6 + ratio / 6)
        elif ratio >= 1.1:
            verdict, conf = "above", 0.75
        elif ratio <= 0.7:
            verdict, conf = "below", min(0.9, 0.6 + (1 - ratio) / 2)
        else:
            verdict, conf = "in line with", 0.5

        insights.append(
            LLMExtractedInsight(
                insight_type="performance",
                insight=(
                    f"'{content.title}' performed {verdict} the account average at "
                    f"{rate * 100:.1f}% engagement across {content.impressions:,} impressions"
                    + (f" ({ratio:.1f}x baseline)" if account_avg_rate else "")
                    + "."
                ),
                confidence=round(conf, 2),
                evidence=f"impressions={content.impressions} rate={rate:.4f} avg={account_avg_rate:.4f}",
            )
        )
        insights.append(
            LLMExtractedInsight(
                insight_type="topic",
                insight=f"'{content.topic}' content generated {rate * 100:.1f}% engagement in this instance.",
                confidence=0.45,
                evidence=f"topic={content.topic}",
            )
        )
        if content.audience:
            insights.append(
                LLMExtractedInsight(
                    insight_type="audience",
                    insight=(
                        f"Content aimed at {content.audience} reached {content.impressions:,} people "
                        f"at {rate * 100:.1f}% engagement."
                    ),
                    confidence=0.4,
                    evidence=f"audience={content.audience}",
                )
            )
        insights.append(
            LLMExtractedInsight(
                insight_type="format",
                insight=(
                    f"The '{content.content_type}' format on {content.platform} produced "
                    f"{content.engagement_count:,} engagements from {content.impressions:,} impressions."
                ),
                confidence=0.5,
                evidence=f"type={content.content_type} platform={content.platform}",
            )
        )
    else:
        insights.append(
            LLMExtractedInsight(
                insight_type="topic",
                insight=(
                    f"This company published '{content.title}' about {content.topic}; "
                    "no performance data recorded yet."
                ),
                confidence=0.3,
                evidence="no impressions",
            )
        )
    return insights


def extract_insights(content: Content, account_avg_rate: float) -> list[LLMExtractedInsight]:
    """LLM-backed insight extraction with a deterministic fallback."""
    llm = get_llm_service()
    user = f"""ACCOUNT AVERAGE ENGAGEMENT RATE: {account_avg_rate * 100:.2f}%

CONTENT RECORD
title: {content.title}
platform: {content.platform}
content_type: {content.content_type}
topic: {content.topic}
audience: {content.audience or "(not specified)"}
published_at: {content.published_at.isoformat() if content.published_at else "(unknown)"}
impressions: {content.impressions}
likes: {content.likes}
comments: {content.comments}
shares: {content.shares}
clicks: {content.clicks}
engagement_rate: {content.engagement_rate:.5f}
body_excerpt: {(content.body or "")[:600] or "(empty)"}

Return {{"insights": [...], "memories": [...]}}. JSON Schema:
{{"type":"object","properties":{{"insights":{{"type":"array","items":{{"type":"object","properties":{{
  "insight_type":{{"enum":["performance","topic","audience","format","tone","strategy"]}},
  "insight":{{"type":"string"}},"confidence":{{"type":"number"}},"evidence":{{"type":"string"}}
}},"required":["insight_type","insight","confidence"]}}}},"memories":{{"type":"array","items":{{"type":"object",
  "properties":{{"text":{{"type":"string"}},"kind":{{"enum":["content","performance","audience","topic","gap","brand","strategy","format"]}},
  "context":{{"type":"string"}}}},"required":["text"]}}}}}},"required":["insights","memories"]}}
"""

    def fallback() -> dict:
        insights = heuristic_insights(content, account_avg_rate)
        return {
            "insights": [i.model_dump() for i in insights],
            "memories": [
                {"text": i.insight, "kind": _kind_for(i.insight_type), "context": "ContentMind content performance history"}
                for i in insights
                if i.confidence >= 0.45
            ],
        }

    result, _note = llm.generate_json(
        LLMContentAnalysis, system=PERFORMANCE_PROMPT, user=user, fallback=fallback, temperature=0.2
    )
    if result is None or not result.insights:
        return heuristic_insights(content, account_avg_rate)
    return result.insights[:8]


def _kind_for(insight_type: str) -> str:
    return {
        "performance": "performance",
        "topic": "topic",
        "audience": "audience",
        "format": "format",
        "tone": "brand",
        "strategy": "strategy",
    }.get(insight_type, "strategy")


# ----------------------------------------------------------------------------------
# CRUD
# ----------------------------------------------------------------------------------
def create_content(db: Session, payload: ContentCreate, user_id: int) -> Content:
    content = Content(
        user_id=user_id,
        title=payload.title,
        body=payload.body,
        platform=payload.platform,
        content_type=payload.content_type,
        topic=payload.topic,
        audience=payload.audience,
        published_at=payload.published_at or datetime.now(timezone.utc),
        impressions=payload.impressions,
        likes=payload.likes,
        comments=payload.comments,
        shares=payload.shares,
        clicks=payload.clicks,
        status=payload.status,
        source="manual",
    )
    apply_metrics(content)
    db.add(content)
    db.flush()
    return content



def bulk_create_content(db: Session, payloads: list[ContentCreate], user_id: int, skip_duplicates: bool = True) -> tuple[list[Content], int]:
    created: list[Content] = []
    skipped = 0
    for payload in payloads:
        if skip_duplicates:
            existing = db.scalar(
                select(Content.id).where(
                    Content.user_id == user_id,
                    func.lower(Content.title) == payload.title.strip().lower()
                )
            )
            if existing:
                skipped += 1
                continue
        created.append(create_content(db, payload, user_id))
    return created, skipped



def update_content(db: Session, content: Content, payload: ContentUpdate) -> Content:
    data = payload.model_dump(exclude_unset=True, exclude={"re_analyze"})
    for field, value in data.items():
        if value is not None:
            setattr(content, field, value)
    apply_metrics(content)
    db.flush()
    return content


def get_content(db: Session, content_id: int) -> Content | None:
    return db.get(Content, content_id)


def list_content(
    db: Session,
    *,
    user_id: int,
    search: str | None = None,
    platform: str | None = None,
    topic: str | None = None,
    content_type: str | None = None,
    status: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> ContentListResponse:
    stmt = select(Content).where(Content.user_id == user_id)
    count_stmt = select(func.count(Content.id)).where(Content.user_id == user_id)


    conditions = []
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(or_(Content.title.ilike(pattern), Content.body.ilike(pattern), Content.topic.ilike(pattern)))
    for column, value in (("platform", platform), ("topic", topic), ("content_type", content_type), ("status", status)):
        if value:
            conditions.append(getattr(Content, column) == value)

    if conditions:
        stmt = stmt.where(*conditions)
        count_stmt = count_stmt.where(*conditions)

    total = db.scalar(count_stmt) or 0
    rows = list(
        db.scalars(
            stmt.order_by(Content.published_at.desc().nullslast(), Content.id.desc()).limit(limit).offset(offset)
        )
    )
    return ContentListResponse(
        items=[ContentRead.model_validate(r) for r in rows], total=total, limit=limit, offset=offset
    )


def all_contents(db: Session, user_id: int, limit: int = 2000) -> list[Content]:
    return list(db.scalars(select(Content).where(Content.user_id == user_id).order_by(Content.published_at.asc().nullslast()).limit(limit)))



def insights_for(db: Session, content_id: int) -> list[ContentInsightRead]:
    from ..models import ContentInsight

    rows = db.scalars(
        select(ContentInsight).where(ContentInsight.content_id == content_id).order_by(ContentInsight.id)
    )
    return [ContentInsightRead.model_validate(r) for r in rows]
