"""In-process fallback for the long-term memory layer.

Used **only** when Hindsight is not configured or unreachable. It implements the
same small contract the rest of the app depends on (``retain`` / ``recall`` /
``list`` / ``clear`` / ``stats``) so the product keeps working end to end
without degrading into a crash.

Retrieval here is deliberately simple (lexical overlap + phrase boost +
recency). It is not a substitute for Hindsight's four-arm TEMPR retrieval; the
UI always labels which backend answered.
"""

from __future__ import annotations

import math
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have",
    "how", "i", "in", "is", "it", "of", "on", "or", "our", "that", "the", "their",
    "them", "this", "to", "was", "we", "were", "what", "when", "which", "who",
    "why", "with", "you", "your", "about", "should", "would", "could", "do", "does",
}

# Category hints so "what should I post next week" can reach brand/strategy
# memories even when wording differs.
_QUERY_AFFINITY: tuple[tuple[tuple[str, ...], str], ...] = (
    (("post", "publish", "next", "plan", "schedule", "content"), "strategy"),
    (("voice", "tone", "brand", "sound", "style"), "brand"),
    (("gap", "missing", "undercovered", "neglected", "uncovered"), "gap"),
    (("audience", "engagement", "respond", "customer", "reader"), "audience"),
    (("topic", "subject", "theme"), "topic"),
    (("platform", "channel", "linkedin", "twitter", "blog", "youtube"), "topic"),
    (("format", "carousel", "video", "thread", "newsletter"), "topic"),
    (("performance", "best", "worst", "underperform", "outperform", "top"), "performance"),
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall((text or "").lower()) if t and t not in _STOPWORDS]


class LocalMemoryBackend:
    """Thread-safe, JSON-serialisable memory store used as a safety net."""

    name = "local"

    def __init__(self, bank: str = "contentmind") -> None:
        self.bank = bank
        self._lock = threading.RLock()
        self._memories: list[dict[str, Any]] = []
        self._documents: dict[str, list[str]] = {}

    # -- writes -----------------------------------------------------------------
    def retain_batch(
        self,
        items: list[dict[str, Any]],
        document_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            created: list[str] = []
            for item in items:
                content = (item.get("content") or "").strip()
                if not content:
                    continue
                mid = uuid.uuid4().hex
                self._memories.append(
                    {
                        "id": mid,
                        "text": content,
                        "context": item.get("context") or "",
                        "kind": item.get("kind") or "strategy",
                        "tags": list(item.get("tags") or []),
                        "document_id": item.get("document_id") or document_id,
                        "occurred_at": item.get("timestamp") or datetime.now(timezone.utc).isoformat(),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
                created.append(mid)
                if item.get("document_id"):
                    self._documents.setdefault(item["document_id"], []).append(mid)
            return {"success": True, "bank_id": self.bank, "items_count": len(created), "ids": created}

    # -- reads ------------------------------------------------------------------
    def recall(self, query: str, limit: int = 12, **_kwargs: Any) -> list[dict[str, Any]]:
        q_tokens = set(_tokenize(query))
        q_lower = (query or "").lower()
        wanted_kinds = {kind for keys, kind in _QUERY_AFFINITY if any(k in q_lower for k in keys)}

        now = datetime.now(timezone.utc)
        scored: list[tuple[float, dict[str, Any]]] = []
        with self._lock:
            snapshot = list(self._memories)

        for mem in snapshot:
            score = self._score(mem, q_tokens, wanted_kinds, now)
            if score > 0:
                scored.append((score, mem))

        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [
            {**mem, "score": round(score, 4), "type": "world", "backend": self.name}
            for score, mem in scored[:limit]
        ]

    @staticmethod
    def _score(
        mem: dict[str, Any],
        q_tokens: set[str],
        wanted_kinds: set[str],
        now: datetime,
    ) -> float:
        haystack = f"{mem.get('text', '')} {mem.get('context', '')}"
        m_tokens = set(_tokenize(haystack))
        if not m_tokens:
            return 0.0

        overlap = q_tokens & m_tokens
        if not overlap and not (wanted_kinds and mem.get("kind") in wanted_kinds):
            return 0.0

        score = len(overlap) / max(1, len(q_tokens))

        m_lower = haystack.lower()
        for phrase in ("above average", "below average", "outperform", "underperform", "brand voice"):
            if phrase in m_lower:
                score += 0.12

        if mem.get("kind") in wanted_kinds:
            score += 0.35
        if "observation" in (mem.get("kind") or "") or mem.get("kind") == "strategy":
            score += 0.08

        try:
            occurred = datetime.fromisoformat(str(mem.get("occurred_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            occurred = now
        age_days = max(0.0, (now - occurred).total_seconds() / 86400.0)
        recency = 1.0 / (1.0 + math.log1p(age_days) / 3.0)
        return score * (0.75 + 0.25 * recency)

    def list_memories(self, limit: int = 200, offset: int = 0) -> tuple[list[dict[str, Any]], int]:
        with self._lock:
            ordered = sorted(self._memories, key=lambda m: m.get("created_at") or "", reverse=True)
        return ordered[offset : offset + limit], len(ordered)

    def clear(self) -> int:
        with self._lock:
            n = len(self._memories)
            self._memories.clear()
            self._documents.clear()
            return n

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "bank_id": self.bank,
                "total_nodes": len(self._memories),
                "total_documents": len(self._documents),
                "total_observations": 0,
                "backend": self.name,
            }

    def health(self) -> bool:
        return True

    def recent_window(self, days: int) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        out = []
        for mem in self.list_memories(limit=10_000)[0]:
            try:
                occurred = datetime.fromisoformat(str(mem.get("occurred_at")).replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if occurred >= cutoff:
                out.append(mem)
        return out
