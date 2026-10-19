"""Hindsight (Vectorize) transport layer.

Thin, well-typed wrapper over the documented HTTP API:

    POST   /v1/default/banks/{bank}/memories          (retain)
    POST   /v1/default/banks/{bank}/memories/recall   (recall)
    POST   /v1/default/banks/{bank}/reflect           (reason over memory)
    GET    /v1/default/banks/{bank}/memories/list     (browse)
    DELETE /v1/default/banks/{bank}/memories          (clear)
    GET    /v1/default/banks/{bank}/stats
    GET    /health

Every call is non-fatal: transport errors are captured on the returned status
object and the caller decides whether to fall back. Hindsight being down must
never take the product down with it.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import get_settings
from .local_memory_backend import LocalMemoryBackend

logger = logging.getLogger("contentmind.hindsight")

TENANT = "default"


class HindsightError(RuntimeError):
    """Raised only when a caller explicitly opts into strict mode."""


class HindsightService:
    """Stateless-per-call wrapper. A single shared httpx client is reused."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        bank: str | None = None,
        timeout: float | None = None,
    ) -> None:
        settings = get_settings()
        self.base_url = (base_url if base_url is not None else settings.hindsight_api_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.hindsight_api_key
        self.bank = bank or settings.hindsight_bank
        self.timeout = timeout if timeout is not None else settings.hindsight_timeout
        self.allow_local_fallback = settings.hindsight_allow_local_fallback

        self._lock = threading.RLock()
        self._client: httpx.Client | None = None
        self._last_error: str | None = None
        self._last_ok_at: datetime | None = None
        self._reached = False
        self._local = LocalMemoryBackend(bank=self.bank)

    # ------------------------------------------------------------------ infra --
    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    @property
    def last_error(self) -> str | None:
        with self._lock:
            return self._last_error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _http(self) -> httpx.Client:
        with self._lock:
            if self._client is None:
                self._client = httpx.Client(
                    timeout=self.timeout,
                    headers=self._headers(),
                    follow_redirects=True,
                )
            return self._client

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}/v1/{TENANT}/banks/{self.bank}{suffix}"

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = self._http().request(method, url, **kwargs)
        with self._lock:
            self._reached = True
            if response.status_code >= 400:
                self._last_error = f"{method} {url} -> {response.status_code}: {response.text[:300]}"
            else:
                self._last_ok_at = datetime.now(timezone.utc)
        if response.status_code == 404:
            raise HindsightError(f"{method} {url} not found (404)")
        if response.status_code >= 400:
            raise HindsightError(f"{method} {url} failed with {response.status_code}: {response.text[:300]}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:  # malformed LLM/provider JSON upstream
            raise HindsightError(f"{method} {url} returned non-JSON body") from exc

    def _try(self, fn, fallback):
        """Run an operation, degrading to the local backend on any failure."""
        if not self.configured:
            return fallback(), "local"
        try:
            return fn(), "hindsight"
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            with self._lock:
                self._last_error = f"{type(exc).__name__}: {exc}"[:400]
            logger.warning("Hindsight call failed, degrading to local memory: %s", exc)
            if not self.allow_local_fallback:
                raise
            return fallback(), "local"

    def close(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None

    # ------------------------------------------------------------------ banks --
    def ensure_bank(self, mission: str = "") -> bool:
        if not self.configured:
            return False
        try:
            self._request(
                "PUT",
                self._url(""),
                json={
                    "bank_id": self.bank,
                    "name": "ContentMind",
                    "mission": mission
                    or (
                        "Long-term strategic memory for a content marketing team. "
                        "Capture what was published, how it performed, which topics and "
                        "formats work, what the audience responds to, where the gaps are, "
                        "and what the brand voice is."
                    ),
                },
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.info("ensure_bank skipped/failed: %s", exc)
            return False

    def health(self) -> bool:
        if not self.configured:
            return False
        try:
            self._request("GET", f"{self.base_url}/health")
            return True
        except Exception:  # noqa: BLE001
            return False

    def stats(self) -> dict[str, Any]:
        def remote() -> dict[str, Any]:
            return self._request("GET", self._url("/stats")) or {}

        result, backend = self._try(remote, self._local.stats)
        result = dict(result or {})
        result["backend"] = backend
        return result

    # ------------------------------------------------------------------ writes --
    def retain_batch(
        self,
        items: list[dict[str, Any]],
        document_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        payload_items = []
        for item in items:
            entry: dict[str, Any] = {"content": item.get("content", "")}
            if item.get("context"):
                entry["context"] = item["context"]
            if item.get("document_id") or document_id:
                entry["document_id"] = item.get("document_id") or document_id
            if item.get("timestamp"):
                entry["timestamp"] = item["timestamp"]
            if item.get("tags") or tags:
                entry["tags"] = list(item.get("tags") or tags or [])
            if item.get("kind"):
                # Hindsight stores free-form metadata; kind rides along so the
                # UI can group recalled memories by category.
                entry["metadata"] = {"kind": item["kind"]}
            payload_items.append(entry)

        body = {"items": payload_items, "async": False}

        def remote() -> dict[str, Any]:
            return self._request("POST", self._url("/memories"), json=body)

        result, backend = self._try(remote, lambda: self._local.retain_batch(items, document_id))
        result = dict(result or {})
        result["backend"] = backend
        return result

    def clear(self) -> dict[str, Any]:
        def remote() -> dict[str, Any]:
            return self._request("DELETE", self._url("/memories"))

        def local() -> dict[str, Any]:
            return {"success": True, "deleted_count": self._local.clear()}

        result, backend = self._try(remote, local)
        result = dict(result or {})
        result["backend"] = backend
        return result

    # ------------------------------------------------------------------- reads --
    def recall(
        self,
        query: str,
        limit: int = 12,
        budget: str = "mid",
        max_tokens: int = 2048,
        types: list[str] | None = None,
        prefer_observations: bool = True,
    ) -> tuple[list[dict[str, Any]], str]:
        body: dict[str, Any] = {
            "query": query,
            "budget": budget,
            "max_tokens": max_tokens,
            "prefer_observations": prefer_observations,
        }
        if types:
            body["types"] = types
        if not prefer_observations:
            body.pop("prefer_observations")

        def remote() -> list[dict[str, Any]]:
            payload = self._request("POST", self._url("/memories/recall"), json=body) or {}
            results = payload.get("results") or []
            return results[:limit]

        result, backend = self._try(remote, lambda: self._local.recall(query, limit=limit))
        return (result or [])[:limit], backend

    def reflect(self, query: str, budget: str = "mid", include_facts: bool = True) -> tuple[str, str]:
        body: dict[str, Any] = {"query": query, "budget": budget}
        if include_facts:
            body["include"] = {"facts": {}}

        def remote() -> str:
            payload = self._request("POST", self._url("/reflect"), json=body) or {}
            return payload.get("text") or ""

        result, backend = self._try(remote, lambda: "")
        return result or "", backend

    def list_memories(self, limit: int = 100, offset: int = 0) -> tuple[list[dict[str, Any]], int, str]:
        def remote() -> tuple[list[dict[str, Any]], int]:
            payload = (
                self._request(
                    "GET", self._url("/memories/list"), params={"limit": limit, "offset": offset}
                )
                or {}
            )
            return list(payload.get("items") or []), int(payload.get("total") or 0)

        result, backend = self._try(remote, lambda: self._local.list_memories(limit, offset))
        items, total = result
        return items, total, backend

    def observations(self, limit: int = 40) -> list[dict[str, Any]]:
        items, _total, _backend = self.list_memories(limit=400, offset=0)
        return [i for i in items if (i.get("fact_type") or i.get("type")) == "observation"][:limit]

    # ------------------------------------------------------------------ status --
    def status(self) -> dict[str, Any]:
        if not self.configured:
            stats = self._local.stats()
            return {
                "backend": "local",
                "available": True,
                "degraded": True,
                "configured": False,
                "bank": self.bank,
                "memory_count": int(stats.get("total_nodes", 0)),
                "observation_count": 0,
                "document_count": int(stats.get("total_documents", 0)),
                "last_error": None,
                "message": (
                    "HINDSIGHT_API_URL is not set. Running on the local memory fallback, so "
                    "the memory loop still works but retrieval quality is lower. Set "
                    "HINDSIGHT_API_URL and HINDSIGHT_API_KEY to use Hindsight by Vectorize."
                ),
            }

        healthy = self.health()
        backend = "hindsight" if healthy else "local"
        if healthy:
            try:
                self.ensure_bank()
            except Exception:  # noqa: BLE001
                pass
        stats = self.stats() if healthy else self._local.stats()
        return {
            "backend": backend,
            "available": True,
            "degraded": not healthy,
            "configured": True,
            "bank": self.bank,
            "memory_count": int(stats.get("total_nodes") or stats.get("total_nodes") or 0),
            "observation_count": int(stats.get("total_observations") or 0),
            "document_count": int(stats.get("total_documents") or 0),
            "last_error": self.last_error,
            "message": (
                f"Hindsight bank '{self.bank}' is reachable."
                if healthy
                else "Hindsight is configured but unreachable. Running on the local memory fallback."
            ),
        }


_service: HindsightService | None = None


def get_hindsight_service() -> HindsightService:
    global _service
    if _service is None:
        _service = HindsightService()
    return _service
