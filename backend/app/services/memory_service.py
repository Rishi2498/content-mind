"""Domain memory layer.

This is where the REMEMBER → RECALL → REASON loop is wired. Route handlers
never touch Hindsight directly; they call these functions.

Public surface (mirrors the intended conceptual interface):

* ``remember(statements)``   – write meaningful statements into the memory bank
* ``recall(query)``          – retrieve relevant memories
* ``learn(...)``             – turn an observation into new durable knowledge
* ``get_relevant_memories``  – convenience recall scoped to a strategy question
"""

from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Content, ContentInsight, MemoryEvent
from ..schemas import MemoryRecord, MemoryRecallResponse, MemoryStatement, MemoryStatus
from .analytics_service import build_analytics
from .hindsight_service import get_hindsight_service

logger = logging.getLogger("contentmind.memory")

# Context labels make memories browsable in the Hindsight control plane.
CONTEXT_CONTENT = "Published content record"
CONTEXT_PERFORMANCE = "Historical content performance"
CONTEXT_AUDIENCE = "Audience response pattern"
CONTEXT_TOPIC = "Topic coverage and frequency"
CONTEXT_GAP = "Content gap analysis"
CONTEXT_BRAND = "Brand voice and positioning"
CONTEXT_STRATEGY = "Content strategy learning"

CONTEXT_BY_KIND = {
    "content": CONTEXT_CONTENT,
    "performance": CONTEXT_PERFORMANCE,
    "audience": CONTEXT_AUDIENCE,
    "topic": CONTEXT_TOPIC,
    "gap": CONTEXT_GAP,
    "brand": CONTEXT_BRAND,
    "strategy": CONTEXT_STRATEGY,
}


# ----------------------------------------------------------------------------------
# Statement construction
# ----------------------------------------------------------------------------------
def _fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def build_content_statements(
    content: Content,
    account_avg_rate: float,
    account_avg_ctr: float,
) -> list[MemoryStatement]:
    """Turn one content record + its metrics into durable, factual statements."""
    statements: list[MemoryStatement] = []
    when = content.published_at.strftime("%Y-%m-%d") if content.published_at else "an undated date"
    label = f"'{content.title}'"

    statements.append(
        MemoryStatement(
            text=(
                f"On {when} this company published {label} on {content.platform} "
                f"as {content.content_type} content about {content.topic}"
                + (f", aimed at {content.audience}" if content.audience else "")
                + "."
            ),
            kind="content",
            context=CONTEXT_CONTENT,
        )
    )

    if content.impressions:
        rate = content.engagement_rate
        ratio = (rate / account_avg_rate) if account_avg_rate else 0.0
        detail = (
            f"{label} reached {content.impressions:,} impressions with "
            f"{content.engagement_count:,} engagements ({_fmt_pct(rate)} engagement rate"
            + (f", {_fmt_pct(content.ctr)} click-through rate" if content.clicks else "")
            + ")"
        )
        if account_avg_rate and ratio >= 1.25:
            comparison = (
                f", which is {ratio:.1f}x the account average engagement rate and clearly above baseline"
            )
        elif account_avg_rate and ratio <= 0.75:
            comparison = f", which is {ratio:.1f}x the account average and below baseline"
        else:
            comparison = ", in line with the account average"
        statements.append(
            MemoryStatement(
                text=f"{detail}{comparison}. Topic: {content.topic}. Platform: {content.platform}.",
                kind="performance",
                context=CONTEXT_PERFORMANCE,
            )
        )
        if content.clicks and account_avg_ctr:
            ctr_ratio = content.ctr / account_avg_ctr if account_avg_ctr else 0.0
            if ctr_ratio >= 1.25:
                statements.append(
                    MemoryStatement(
                        text=(
                            f"{label} converted clicks at {ctr_ratio:.1f}x the account average "
                            f"click-through rate, indicating strong intent from the audience."
                        ),
                        kind="audience",
                        context=CONTEXT_AUDIENCE,
                    )
                )
    return statements


def build_corpus_statements(db: Session, user_id: int) -> list[MemoryStatement]:
    """Derive portfolio-level strategy knowledge from the full content history."""
    from .content_service import all_contents

    contents = all_contents(db, user_id=user_id)
    if not contents:
        return []


    analytics = build_analytics(contents)
    statements: list[MemoryStatement] = []
    total = analytics.content_count
    baseline = analytics.avg_engagement_rate

    def idx_word(index: float) -> str:
        if index >= 1.6:
            return "clearly"
        if index >= 1.2:
            return "consistently"
        if index <= 0.8:
            return "reliably"
        return "slightly"

    # Topic-level learnings
    for stat in analytics.by_topic[:6]:
        if not stat.count:
            continue
        direction = "outperforms" if stat.index_vs_average > 1.0 else "underperforms"
        statements.append(
            MemoryStatement(
                text=(
                    f"Content about '{stat.key}' {direction} the account average: "
                    f"{stat.count} item(s) at {_fmt_pct(stat.avg_engagement_rate)} average engagement "
                    f"({stat.index_vs_average:.1f}x baseline)."
                ),
                kind="topic",
                context=CONTEXT_TOPIC,
            )
        )

    # Platform learnings
    for stat in analytics.by_platform[:5]:
        if stat.index_vs_average >= 1.2:
            statements.append(
                MemoryStatement(
                    text=(
                        f"{stat.key} is currently the strongest platform at "
                        f"{stat.index_vs_average:.1f}x the account average engagement rate "
                        f"across {stat.count} item(s)."
                    ),
                    kind="topic",
                    context=CONTEXT_TOPIC,
                )
            )
        elif stat.index_vs_average <= 0.85 and stat.count >= 2:
            statements.append(
                MemoryStatement(
                    text=(
                        f"{stat.key} {idx_word(stat.index_vs_average)} underperforms: "
                        f"{stat.index_vs_average:.1f}x the account average engagement across "
                        f"{stat.count} item(s)."
                    ),
                    kind="topic",
                    context=CONTEXT_TOPIC,
                )
            )

    # Format learnings
    for stat in analytics.by_content_type[:6]:
        if stat.index_vs_average >= 1.25:
            statements.append(
                MemoryStatement(
                    text=(
                        f"The '{stat.key}' format {idx_word(stat.index_vs_average)} outperforms: "
                        f"{stat.index_vs_average:.1f}x baseline engagement across {stat.count} item(s)."
                    ),
                    kind="format",
                    context=CONTEXT_PERFORMANCE,
                )
            )
        elif stat.index_vs_average <= 0.75 and stat.count >= 2:
            statements.append(
                MemoryStatement(
                    text=(
                        f"The '{stat.key}' format has {idx_word(stat.index_vs_average)} underperformed: "
                        f"{stat.index_vs_average:.1f}x baseline engagement across {stat.count} item(s)."
                    ),
                    kind="format",
                    context=CONTEXT_PERFORMANCE,
                )
            )

    # Audience learnings
    for stat in analytics.by_audience[:4]:
        if stat.count >= 2 and stat.index_vs_average >= 1.2:
            statements.append(
                MemoryStatement(
                    text=(
                        f"Content aimed at {stat.key} generates {stat.index_vs_average:.1f}x average "
                        f"engagement, so this audience is a reliable source of interest."
                    ),
                    kind="audience",
                    context=CONTEXT_AUDIENCE,
                )
            )
        elif stat.count >= 2 and stat.index_vs_average <= 0.8:
            statements.append(
                MemoryStatement(
                    text=(
                        f"Content aimed at {stat.key} generates below-average engagement "
                        f"({stat.index_vs_average:.1f}x baseline) across {stat.count} item(s)."
                    ),
                    kind="audience",
                    context=CONTEXT_AUDIENCE,
                )
            )

    # Coverage / fatigue signal
    top = analytics.by_topic[0] if analytics.by_topic else None
    if top and total >= 8:
        statements.append(
            MemoryStatement(
                text=(
                    f"'{top.key}' is the most covered topic in this history with {top.count} of "
                    f"{total} items; the account is at risk of topic fatigue here."
                ),
                kind="topic",
                context=CONTEXT_TOPIC,
            )
        )

    # A single cross-cutting strategy observation
    winners = [s.key for s in analytics.by_content_type[:2] if s.index_vs_average >= 1.2]
    losers = [s.key for s in analytics.by_content_type if s.count >= 2 and s.index_vs_average <= 0.8]
    if winners and losers:
        statements.append(
            MemoryStatement(
                text=(
                    f"Strategy pattern: {winners[0]} style content historically outperforms, while "
                    f"{losers[0]} content has underperformed. Weight future plans toward the former."
                ),
                kind="strategy",
                context=CONTEXT_STRATEGY,
            )
        )
    if baseline:
        statements.append(
            MemoryStatement(
                text=(
                    f"Account baseline engagement rate is {_fmt_pct(baseline)} across {total} published "
                    f"items; treat anything meaningfully above that as a winner."
                ),
                kind="performance",
                context=CONTEXT_PERFORMANCE,
            )
        )
    return statements


# ----------------------------------------------------------------------------------
# Service surface
# ----------------------------------------------------------------------------------
class MemoryService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.hindsight = get_hindsight_service()

    # -- write ------------------------------------------------------------------
    def remember(
        self,
        statements: list[MemoryStatement],
        document_id: str | None = None,
        related_content_id: int | None = None,
        user_id: int | None = None,
    ) -> tuple[int, str, bool]:
        """Persist statements to long-term memory. Returns (count, backend, degraded)."""
        settings = get_settings()
        statements = [s for s in statements if s.text and len(s.text.strip()) >= 5]
        if not statements:
            return 0, "none", False

        retained = 0
        backend = "none"
        degraded = not self.hindsight.configured
        batch_size = max(1, settings.hindsight_retain_batch_size)

        for start in range(0, len(statements), batch_size):
            chunk = statements[start : start + batch_size]
            items = [
                {
                    "content": s.text,
                    "context": s.context or CONTEXT_BY_KIND.get(s.kind, CONTEXT_STRATEGY),
                    "kind": s.kind,
                    "tags": [f"kind:{s.kind}", f"user:{user_id}"] if user_id else [f"kind:{s.kind}"],
                }
                for s in chunk
            ]
            try:
                result = self.hindsight.retain_batch(
                    items, document_id=document_id, tags=[f"bank:{self.hindsight.bank}"]
                )
            except Exception as exc:  # noqa: BLE001 - memory must never break ingestion
                logger.warning("Hindsight retain failed: %s", exc)
                degraded = True
                result = {"backend": "local", "items_count": 0}

            backend = result.get("backend", backend)
            if backend != "hindsight":
                degraded = True
            retained += int(result.get("items_count") or 0)

        self._log_event("remember", backend, ok=not degraded, detail=f"{retained} memories", count=retained,
                        related_content_id=related_content_id, user_id=user_id)
        return retained, backend, degraded


    # -- read -------------------------------------------------------------------
    def recall(
        self,
        query: str,
        user_id: int | None = None,
        limit: int = 12,
        budget: str = "mid",
    ) -> MemoryRecallResponse:
        # Hindsight's recall endpoint has no server-side tag filter, so we
        # over-fetch and filter client-side by the user: tag written at retain
        # time. Local backend stores tags on each memory dict too.
        over_fetch = min(200, limit * 4) if user_id else limit
        try:
            results, backend = self.hindsight.recall(query, limit=over_fetch, budget=budget)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hindsight recall failed: %s", exc)
            results, backend = [], "local"

        if user_id:
            wanted = f"user:{user_id}"
            results = [r for r in results if wanted in (r.get("tags") or [])]
        results = results[:limit]

        memories = [self._to_record(r, backend) for r in results]
        self._log_event("recall", backend, ok=True, detail=query[:200], count=len(memories), user_id=user_id)

        total = None
        try:
            stats = self.hindsight.stats()
            total = int(stats.get("total_nodes") or 0) or None
        except Exception:  # noqa: BLE001
            total = None

        return MemoryRecallResponse(
            query=query,
            memories=memories,
            backend=backend,
            degraded=backend != "hindsight",
            total_available=total,
        )


    def get_relevant_memories(self, request: str, user_id: int, aspects: list[str] | None = None, limit: int = 14) -> MemoryRecallResponse:
        """Recall across the aspects a strategy request depends on.

        Issues one focused recall per aspect so topical breadth is not lost to
        a single blended query.
        """
        aspects = aspects or ["what to publish next", "historical performance patterns", "content gaps", "brand voice"]
        merged: list[MemoryRecord] = []
        seen: set[str] = set()
        backends: set[str] = set()

        per_aspect = max(3, limit // max(1, len(aspects)))
        for aspect in aspects:
            try:
                response = self.recall(f"{request} - {aspect}", user_id=user_id, limit=per_aspect, budget="low")
            except Exception:  # noqa: BLE001
                continue
            backends.add(response.backend)
            for mem in response.memories:
                key = mem.text.strip().lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(mem)

        backend = "hindsight" if "hindsight" in backends else ("local" if backends else "hindsight")
        if not merged:
            try:
                fallback = self.hindsight.list_memories(limit=limit)[0]
                merged = [self._to_record(m, "hindsight") for m in fallback]
            except Exception:  # noqa: BLE001
                merged = []

        return MemoryRecallResponse(
            query=request,
            memories=merged[:limit],
            backend=backend,
            degraded=backend != "hindsight",
        )


    # -- learn ------------------------------------------------------------------
    def learn_from_content(self, content: Content, account_avg_rate: float) -> tuple[list[ContentInsight], int, str, bool]:
        """Extract insights + memories from a single (new or updated) content record.

        This is the OBSERVE RESULT �+' LEARN step. Called on every ingestion and on
        every performance update, which is what makes recommendations change.
        """
        from .content_service import extract_insights  # local import avoids a cycle

        insights_models = extract_insights(content, account_avg_rate)
        insights: list[ContentInsight] = []
        for model in insights_models:
            row = ContentInsight(
                content_id=content.id,
                user_id=content.user_id,
                insight_type=model.insight_type,
                insight=model.insight,
                confidence=model.confidence,
                source="historical_performance",
                evidence=model.evidence,
            )
            self.db.add(row)
            insights.append(row)

        statements = build_content_statements(content, account_avg_rate, 0.0)
        statements += [
            MemoryStatement(text=model.insight, kind=_kind_for(model.insight_type), context=_context_for(model.insight_type))
            for model in insights_models
            if model.confidence >= 0.4
        ]
        retained, backend, degraded = self.remember(statements, document_id=f"content-{content.id}",
                                                    related_content_id=content.id, user_id=content.user_id)
        for row in insights:
            row.memory_retained = retained > 0
        return insights, retained, backend, degraded

    def learn_portfolio(self, user_id: int, document_id: str = "portfolio-synthesis") -> tuple[int, str, bool]:
        """Re-derive corpus-level strategy memories and store them."""
        statements = build_corpus_statements(self.db, user_id=user_id)
        retained, backend, degraded = self.remember(statements, document_id=document_id, user_id=user_id)
        return retained, backend, degraded


    # -- status -----------------------------------------------------------------
    def status(self) -> MemoryStatus:
        try:
            raw = self.hindsight.status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Hindsight status failed: %s", exc)
            raw = {
                "backend": "local",
                "available": True,
                "degraded": True,
                "configured": bool(self.hindsight.configured),
                "bank": self.hindsight.bank,
                "memory_count": 0,
                "message": f"Could not reach Hindsight ({exc}).",
            }
        return MemoryStatus(**raw)

    def memories_learned(self) -> int:
        try:
            stats = self.hindsight.stats()
            return int(stats.get("total_nodes") or 0)
        except Exception:  # noqa: BLE001
            return 0

    # -- internals --------------------------------------------------------------
    def _log_event(
        self,
        event_type: str,
        backend: str,
        ok: bool,
        detail: str = "",
        count: int = 0,
        related_content_id: int | None = None,
        user_id: int | None = None,
    ) -> None:
        if user_id is None:
            # MemoryEvent.user_id is NOT NULL (multi-tenant audit trail);
            # logging without a user would fail and roll back the caller's work.
            return
        try:
            self.db.add(
                MemoryEvent(
                    event_type=event_type,
                    backend=backend,
                    ok=ok,
                    detail=detail,
                    count=count,
                    related_content_id=related_content_id,
                    user_id=user_id,
                )
            )
            self.db.flush()
        except Exception:  # noqa: BLE001 - audit logging must never break a request
            self.db.rollback()


    @staticmethod
    def _to_record(raw: dict, backend: str) -> MemoryRecord:
        occurred = raw.get("occurred_at") or raw.get("occurred_start") or raw.get("created_at")
        parsed: datetime | None = None
        if occurred:
            try:
                parsed = datetime.fromisoformat(str(occurred).replace("Z", "+00:00"))
            except ValueError:
                parsed = None
        metadata = raw.get("metadata") or {}
        kind = raw.get("kind") or (metadata.get("kind") if isinstance(metadata, dict) else None) or _kind_from_context(raw.get("context"))
        return MemoryRecord(
            id=str(raw.get("id") or ""),
            text=str(raw.get("text") or raw.get("content") or ""),
            type=str(raw.get("fact_type") or raw.get("type") or "world"),
            kind=str(kind),
            context=raw.get("context"),
            entities=[str(e) for e in (raw.get("entities") or [])],
            score=float(raw.get("score") or 0.0),
            document_id=raw.get("document_id"),
            occurred_at=parsed,
            backend=backend,
        )


_KIND_BY_INSIGHT = {
    "performance": "performance",
    "topic": "topic",
    "audience": "audience",
    "format": "performance",
    "tone": "brand",
    "strategy": "strategy",
}

_CONTEXT_BY_INSIGHT = {
    "performance": CONTEXT_PERFORMANCE,
    "topic": CONTEXT_TOPIC,
    "audience": CONTEXT_AUDIENCE,
    "format": CONTEXT_PERFORMANCE,
    "tone": CONTEXT_BRAND,
    "strategy": CONTEXT_STRATEGY,
}


def _kind_for(insight_type: str) -> str:
    return _KIND_BY_INSIGHT.get(insight_type, "strategy")


def _context_for(insight_type: str) -> str:
    return _CONTEXT_BY_INSIGHT.get(insight_type, CONTEXT_STRATEGY)


def _kind_from_context(context: str | None) -> str:
    mapping = {
        CONTEXT_CONTENT: "content",
        CONTEXT_PERFORMANCE: "performance",
        CONTEXT_AUDIENCE: "audience",
        CONTEXT_TOPIC: "topic",
        CONTEXT_GAP: "gap",
        CONTEXT_BRAND: "brand",
        CONTEXT_STRATEGY: "strategy",
    }
    return mapping.get(context or "", "strategy")
