"""'What I've Learned' — accumulated knowledge, with provenance.

Combines two sources so judges can see the loop working:

* ``ContentInsight`` rows in the database (structured, per-item evidence).
* Hindsight memories, including synthesised ``observation`` units.

Every insight is labelled with where it came from.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Content, ContentInsight
from ..schemas import LearnedInsight, LearnedResponse, MemoryRecord
from .hindsight_service import get_hindsight_service

logger = logging.getLogger("contentmind.learned")

INSIGHT_TYPE_TO_CATEGORY = {
    "performance": "performance",
    "topic": "topics",
    "audience": "audience",
    "format": "formats",
    "tone": "brand_voice",
    "strategy": "strategy",
}

KIND_TO_CATEGORY = {
    "content": "content_history",
    "performance": "performance",
    "audience": "audience",
    "topic": "topics",
    "format": "formats",
    "brand": "brand_voice",
    "gap": "gaps",
    "strategy": "strategy",
}

CATEGORY_LABELS = {
    "audience": "Audience — what your audience appears to like",
    "topics": "Topics — what performs well",
    "formats": "Formats — what performs well",
    "platforms": "Platforms — what performs well",
    "brand_voice": "Brand voice — how your brand communicates",
    "gaps": "Content gaps — what has not been covered enough",
    "performance": "Performance — the numbers behind it",
    "strategy": "Strategy — what to do differently",
    "content_history": "Content history — what you have published",
}

MAX_PER_CATEGORY = 12


def _origin_for_memory(backend: str, fact_type: str) -> str:
    if fact_type == "observation":
        return "hindsight_memory"
    return "historical_performance" if backend == "hindsight" else "content_history"


def _hindsight_learnings(user_id: int, limit_per_source: int = 60) -> tuple[list[LearnedInsight], str, bool, str]:
    hindsight = get_hindsight_service()
    backend = "local"
    degraded = not hindsight.configured
    out: list[LearnedInsight] = []

    try:
        items, _total, backend = hindsight.list_memories(limit=400, offset=0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not list memories: %s", exc)
        items, backend = [], "local"
        degraded = True

    wanted_tag = f"user:{user_id}"
    for raw in items[:limit_per_source * 4]:
        if wanted_tag not in (raw.get("tags") or []):
            continue
        text = str(raw.get("text") or raw.get("content") or "").strip()
        if not text or len(text) < 12:
            continue
        metadata = raw.get("metadata") or {}
        kind = raw.get("kind") or (metadata.get("kind") if isinstance(metadata, dict) else None)
        if not kind:
            kind = _kind_from_context(raw.get("context"))
        fact_type = str(raw.get("fact_type") or raw.get("type") or "world")
        category = KIND_TO_CATEGORY.get(str(kind), "strategy")
        out.append(
            LearnedInsight(
                id=str(raw.get("id") or f"h-{abs(hash(text))}"),
                text=text,
                category=category,
                origin=_origin_for_memory(backend, fact_type),
                confidence=0.85 if fact_type == "observation" else 0.7,
                evidence=f"Hindsight {fact_type} · context: {raw.get('context') or 'n/a'}",
            )
        )
    return out, backend, degraded, hindsight.bank


def _kind_from_context(context: str | None) -> str:
    mapping = {
        "Published content record": "content",
        "Historical content performance": "performance",
        "Audience response pattern": "audience",
        "Topic coverage and frequency": "topic",
        "Content gap analysis": "gap",
        "Brand voice and positioning": "brand",
        "Content strategy learning": "strategy",
    }
    return mapping.get(context or "", "strategy")


def get_learned(db: Session, user_id: int, include_memories: bool = True) -> LearnedResponse:
    contents = list(db.scalars(select(Content).where(Content.user_id == user_id)))
    rows = list(
        db.scalars(
            select(ContentInsight)
            .where(ContentInsight.user_id == user_id)
            .order_by(ContentInsight.confidence.desc(), ContentInsight.id.desc())
        )
    )

    items: list[LearnedInsight] = []
    seen: set[str] = set()

    for row in rows:
        key = row.insight.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        items.append(
            LearnedInsight(
                id=f"insight-{row.id}",
                text=row.insight,
                category=INSIGHT_TYPE_TO_CATEGORY.get(row.insight_type, "strategy"),
                origin=row.source or "historical_performance",
                confidence=row.confidence,
                evidence=row.evidence,
                content_id=row.content_id,
                created_at=row.created_at,
            )
        )

    memory_items: list[LearnedInsight] = []
    backend = "none"
    degraded = False
    if include_memories:
        memory_items, backend, degraded, _bank = _hindsight_learnings(user_id)
        for mem in memory_items:
            key = mem.text.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(mem)

    grouped: dict[str, list[LearnedInsight]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item)

    ordered: dict[str, list[LearnedInsight]] = {}
    for category in CATEGORY_LABELS:
        bucket = sorted(
            grouped.get(category, []),
            key=lambda i: (i.origin == "hindsight_memory", i.confidence, i.created_at or i.id),
            reverse=True,
        )
        if bucket:
            ordered[category] = bucket[:MAX_PER_CATEGORY]
    for category, bucket in grouped.items():
        if category not in ordered and bucket:
            ordered[category] = bucket[:MAX_PER_CATEGORY]

    memory_count = 0
    try:
        stats = get_hindsight_service().stats()
        memory_count = int(stats.get("total_nodes") or 0)
    except Exception:  # noqa: BLE001
        memory_count = 0

    if not contents:
        message = (
            "Nothing learned yet. Add content and ContentMind will start building memory."
        )
    elif degraded:
        message = (
            f"Learning from {len(contents)} content items. Hindsight is unavailable, so these "
            "insights come from the local fallback store."
        )
    else:
        message = (
            f"Learned from {len(contents)} content items and {memory_count} memories in Hindsight "
            f"bank '{get_hindsight_service().bank}'."
        )

    return LearnedResponse(
        total=len(items),
        memory_count=memory_count,
        content_analyzed=len(contents),
        insights=items,
        categories=ordered,
        degraded=degraded,
        message=message,
    )
