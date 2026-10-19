"""Phase 6 — Instagram (Meta) integration service.

Handles:
- OAuth 2.0 authorization flow (Instagram Login)
- Token exchange, storage (encrypted), and refresh
- Media import (posts, reels, carousels) from connected accounts
- Metric insights retrieval and normalization into MetricSnapshot
- Sync orchestration with observable states

All external HTTP calls use httpx with timeouts and bounded retries.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import (
    InstagramConnection,
    InstagramSyncJob,
    MetricSnapshot,
    PublishedPost,
)
from ..schemas import MetricSnapshotInput
from .instagram_crypto import decrypt_token, encrypt_token
from .performance_service import build_snapshot

logger = logging.getLogger("contentmind.instagram")

# Meta API constants — Instagram API with Instagram Login (Business Login for Instagram).
# Docs: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login
INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_GRAPH_BASE = "https://graph.instagram.com"

# Scopes for the Instagram Login flow. instagram_business_basic covers profile,
# media, and insights reads; instagram_business_content_publish covers publishing.
# Note: pages_show_list / pages_read_engagement belong to the Facebook Login flow
# and are rejected by the Instagram Login authorize endpoint ("Invalid Scopes").
REQUIRED_SCOPES = [
    "instagram_business_basic",
    "instagram_business_content_publish",
]

# Media types we support importing
SUPPORTED_MEDIA_TYPES = {"IMAGE", "VIDEO", "CAROUSEL_ALBUM"}

# Insight metrics available per media type on the Instagram Login flow.
# Meta renamed saves -> saved and video_views -> views for this flow.
MEDIA_INSIGHT_METRICS = {
    "IMAGE": ["impressions", "reach", "likes", "comments", "shares", "saved"],
    "VIDEO": [
        "impressions",
        "reach",
        "likes",
        "comments",
        "shares",
        "saved",
        "views",
    ],
    "CAROUSEL_ALBUM": [
        "impressions",
        "reach",
        "likes",
        "comments",
        "shares",
        "saved",
    ],
}

# Account-level insight metrics. "impressions" was deprecated for v22.0 and
# replaced by "views"; follower_count requires >= 100 followers.
ACCOUNT_INSIGHT_METRICS = [
    "views",
    "reach",
    "profile_views",
    "follower_count",
    "website_clicks",
]


@dataclass
class OAuthState:
    """OAuth state payload for CSRF protection.

    The serialized form is a signed token: ``base64url(json).hmac_sha256``.
    The HMAC (keyed by ``SECRET_KEY``) means the callback can trust the
    embedded ``user_id`` — an attacker cannot craft a state that links their
    Instagram account to someone else's ContentMind account.
    """

    user_id: int
    nonce: str
    created_at: datetime

    @staticmethod
    def _sign(payload: str) -> str:
        key = get_settings().secret_key.encode()
        return hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()

    def to_url_param(self) -> str:
        payload = base64.urlsafe_b64encode(
            json.dumps(
                {
                    "uid": self.user_id,
                    "nonce": self.nonce,
                    "ts": self.created_at.timestamp(),
                }
            ).encode()
        ).decode()
        return f"{payload}.{self._sign(payload)}"

    @staticmethod
    def from_url_param(param: str) -> OAuthState | None:
        try:
            payload, signature = param.rsplit(".", 1)
        except (AttributeError, ValueError):
            return None
        if not hmac.compare_digest(signature, OAuthState._sign(payload)):
            return None
        try:
            data = json.loads(base64.urlsafe_b64decode(payload).decode())
            return OAuthState(
                user_id=data["uid"],
                nonce=data["nonce"],
                created_at=datetime.fromtimestamp(data["ts"], tz=timezone.utc),
            )
        except Exception:
            return None


class InstagramAPIError(Exception):
    """Raised when the Meta Graph API returns an error response."""

    def __init__(self, message: str, error_code: int | None = None, error_subcode: int | None = None):
        super().__init__(message)
        self.error_code = error_code
        self.error_subcode = error_subcode


def _parse_api_error(payload: dict[str, Any], fallback: str) -> InstagramAPIError:
    """Parse an error payload from either Graph-style or Instagram-style APIs.

    Graph API errors look like ``{"error": {"message", "code", "error_subcode"}}``;
    the Instagram token endpoint (api.instagram.com) returns a flat
    ``{"error_type", "code", "error_message"}`` shape.
    """
    err = payload.get("error")
    if isinstance(err, dict):
        return InstagramAPIError(
            err.get("message", fallback),
            error_code=err.get("code"),
            error_subcode=err.get("error_subcode"),
        )
    return InstagramAPIError(
        payload.get("error_message") or payload.get("message") or fallback,
        error_code=payload.get("code"),
    )


class InstagramService:
    """Service for Instagram API operations."""

    def __init__(self, db: Session, user_id: int):
        self.db = db
        self.user_id = user_id
        self.settings = get_settings()

    # ------------------------------------------------------------------
    # OAuth — Authorization URL & Callback (Instagram Login flow)
    # ------------------------------------------------------------------
    def _graph_url(self, path: str) -> str:
        """Build a versioned graph.instagram.com URL."""
        version = self.settings.instagram_api_version
        return f"{INSTAGRAM_GRAPH_BASE}/{version}{path}"

    def build_authorize_url(self) -> tuple[str, OAuthState]:
        """Build the Instagram Login authorize URL and return (url, state)."""
        state = OAuthState(
            user_id=self.user_id,
            nonce=secrets.token_urlsafe(16),
            created_at=datetime.now(timezone.utc),
        )

        params = {
            "client_id": self.settings.instagram_app_id,
            "redirect_uri": self.settings.instagram_redirect_uri,
            "scope": ",".join(REQUIRED_SCOPES),
            "response_type": "code",
            "state": state.to_url_param(),
        }
        url = f"{INSTAGRAM_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
        return url, state

    async def exchange_code_for_token(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for a short-lived Instagram User token.

        POST https://api.instagram.com/oauth/access_token
        Returns a flat dict: {access_token, user_id, permissions}.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                INSTAGRAM_TOKEN_URL,
                data={
                    "client_id": self.settings.instagram_app_id,
                    "client_secret": self.settings.instagram_app_secret,
                    "redirect_uri": self.settings.instagram_redirect_uri,
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
            if resp.is_success:
                payload = resp.json()
                # Some responses wrap the grant in {"data": [{...}]}
                data = payload.get("data")
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return data[0]
                return payload
            raise _parse_api_error(resp.json(), "Token exchange failed")

    async def exchange_short_lived_for_long_lived(
        self, short_token: str
    ) -> dict[str, Any]:
        """Exchange short-lived token for long-lived (60-day) token.

        GET https://graph.instagram.com/{version}/access_token
          ?grant_type=ig_exchange_token&client_secret=...&access_token=...
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url("/access_token"),
                params={
                    "grant_type": "ig_exchange_token",
                    "client_secret": self.settings.instagram_app_secret,
                    "access_token": short_token,
                },
            )
            if resp.is_success:
                return resp.json()
            raise _parse_api_error(resp.json(), "Long-lived token exchange failed")

    async def refresh_long_lived_token(self, long_token: str) -> dict[str, Any]:
        """Refresh a long-lived token (extends by 60 days from refresh time).

        GET https://graph.instagram.com/{version}/refresh_access_token
          ?grant_type=ig_refresh_token&access_token=...
        The token must be at least 24 hours old but not yet expired.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url("/refresh_access_token"),
                params={
                    "grant_type": "ig_refresh_token",
                    "access_token": long_token,
                },
            )
            if resp.is_success:
                return resp.json()
            raise _parse_api_error(resp.json(), "Token refresh failed")

    async def fetch_user_info(self, access_token: str) -> dict[str, Any]:
        """Fetch the Instagram professional account info for a token via /me.

        GET https://graph.instagram.com/{version}/me
          ?fields=user_id,username,account_type,media_count,followers_count,...
        Returns a flat dict. The IG professional account ID is in ``user_id``.
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url("/me"),
                params={
                    "fields": (
                        "user_id,username,account_type,media_count,"
                        "followers_count,follows_count,profile_picture_url"
                    ),
                    "access_token": access_token,
                },
            )
            if resp.is_success:
                payload = resp.json()
                data = payload.get("data")
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return data[0]
                return payload
            raise _parse_api_error(resp.json(), "Failed to fetch Instagram account info")

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------
    def get_connection(self, connection_id: int) -> InstagramConnection | None:
        return self.db.scalar(
            select(InstagramConnection).where(
                InstagramConnection.id == connection_id,
                InstagramConnection.user_id == self.user_id,
            )
        )

    def list_connections(self) -> list[InstagramConnection]:
        return list(
            self.db.scalars(
                select(InstagramConnection).where(
                    InstagramConnection.user_id == self.user_id,
                    InstagramConnection.status != "disconnected",
                )
            )
        )

    def store_connection(
        self,
        instagram_account_id: str,
        username: str,
        account_type: str,
        access_token: str,
        expires_in: int | None,
        scopes: list[str],
        media_count: int | None = None,
        followers_count: int | None = None,
        follows_count: int | None = None,
        profile_picture_url: str = "",
    ) -> InstagramConnection:
        """Create or update an InstagramConnection with encrypted token."""
        existing = self.db.scalar(
            select(InstagramConnection).where(
                InstagramConnection.user_id == self.user_id,
                InstagramConnection.instagram_account_id == instagram_account_id,
            )
        )

        now = datetime.now(timezone.utc)
        expires_at = (
            now + timedelta(seconds=expires_in) if expires_in else None
        )

        token_encrypted = encrypt_token(access_token)

        if existing:
            existing.username = username
            existing.account_type = account_type
            existing.access_token_encrypted = token_encrypted
            existing.token_type = "bearer"
            existing.expires_at = expires_at
            existing.last_refreshed_at = now
            existing.scopes = scopes
            existing.media_count = media_count
            existing.followers_count = followers_count
            existing.follows_count = follows_count
            existing.profile_picture_url = profile_picture_url
            existing.status = "connected"
            existing.last_sync_error = ""
            existing.updated_at = now
            conn = existing
        else:
            conn = InstagramConnection(
                user_id=self.user_id,
                instagram_account_id=instagram_account_id,
                username=username,
                account_type=account_type,
                access_token_encrypted=token_encrypted,
                token_type="bearer",
                expires_at=expires_at,
                last_refreshed_at=now,
                scopes=scopes,
                media_count=media_count,
                followers_count=followers_count,
                follows_count=follows_count,
                profile_picture_url=profile_picture_url,
                status="connected",
            )
            self.db.add(conn)

        self.db.commit()
        self.db.refresh(conn)
        return conn

    def disconnect_connection(self, connection_id: int) -> bool:
        """Disconnect (soft delete) an Instagram connection."""
        conn = self.get_connection(connection_id)
        if not conn:
            return False
        conn.status = "disconnected"
        conn.access_token_encrypted = ""
        conn.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return True

    # ------------------------------------------------------------------
    # Token access (decrypt on use)
    # ------------------------------------------------------------------
    def get_decrypted_token(self, connection: InstagramConnection) -> str:
        if not connection.access_token_encrypted:
            raise ValueError("No stored token for this connection")
        return decrypt_token(connection.access_token_encrypted)

    async def ensure_valid_token(self, connection: InstagramConnection) -> str:
        """Return a valid access token, refreshing if needed."""
        token = self.get_decrypted_token(connection)

        # If token expires within 24 hours, try to refresh
        if connection.expires_at and connection.expires_at < datetime.now(timezone.utc) + timedelta(hours=24):
            try:
                refreshed = await self.refresh_long_lived_token(token)
                new_token = refreshed["access_token"]
                expires_in = refreshed.get("expires_in")
                self.store_connection(
                    instagram_account_id=connection.instagram_account_id,
                    username=connection.username,
                    account_type=connection.account_type,
                    access_token=new_token,
                    expires_in=expires_in,
                    scopes=connection.scopes,
                    media_count=connection.media_count,
                    followers_count=connection.followers_count,
                    follows_count=connection.follows_count,
                    profile_picture_url=connection.profile_picture_url,
                )
                return new_token
            except InstagramAPIError as e:
                logger.warning(
                    "Token refresh failed for connection %s: %s",
                    connection.id,
                    e,
                )
                # Return the old token anyway; API call will fail if truly expired
        return token

    # ------------------------------------------------------------------
    # Account info
    # ------------------------------------------------------------------
    async def fetch_account_info(
        self, connection: InstagramConnection
    ) -> dict[str, Any]:
        """Fetch basic account info from the Graph API."""
        token = await self.ensure_valid_token(connection)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url(f"/{connection.instagram_account_id}"),
                params={
                    "fields": "user_id,username,account_type,media_count,followers_count,follows_count,profile_picture_url",
                    "access_token": token,
                },
            )
            if resp.is_success:
                payload = resp.json()
                data = payload.get("data")
                if isinstance(data, list) and data and isinstance(data[0], dict):
                    return data[0]
                return payload
            raise _parse_api_error(resp.json(), "Failed to fetch account info")

    # ------------------------------------------------------------------
    # Media import
    # ------------------------------------------------------------------
    async def fetch_media_page(
        self,
        connection: InstagramConnection,
        after: str | None = None,
        limit: int = 25,
    ) -> dict[str, Any]:
        """Fetch a page of media from the Instagram account."""
        token = await self.ensure_valid_token(connection)
        params = {
            "fields": "id,caption,media_type,media_url,permalink,timestamp,username,like_count,comments_count",
            "limit": min(limit, 100),
            "access_token": token,
        }
        if after:
            params["after"] = after

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url(f"/{connection.instagram_account_id}/media"),
                params=params,
            )
            if resp.is_success:
                return resp.json()
            raise _parse_api_error(resp.json(), "Failed to fetch media")

    def _map_media_to_post(
        self,
        connection: InstagramConnection,
        media: dict[str, Any],
    ) -> PublishedPost:
        """Convert Instagram media to PublishedPost (idempotent by external_id)."""
        # Check if already exists
        existing = self.db.scalar(
            select(PublishedPost).where(
                PublishedPost.user_id == self.user_id,
                PublishedPost.external_id == media["id"],
                PublishedPost.platform == "Instagram",
            )
        )
        if existing:
            # Update mutable fields only
            existing.title = media.get("caption", "")[:300] or existing.title
            existing.url = media.get("permalink", "") or existing.url
            existing.updated_at = datetime.now(timezone.utc)
            return existing

        published_at = datetime.fromisoformat(
            media["timestamp"].replace("Z", "+00:00")
        )

        post = PublishedPost(
            user_id=self.user_id,
            platform="Instagram",
            title=media.get("caption", "")[:300],
            external_id=media["id"],
            url=media.get("permalink", ""),
            published_at=published_at,
            status="published",
        )
        self.db.add(post)
        self.db.flush()
        return post

    def import_media(
        self,
        connection: InstagramConnection,
        max_posts: int | None = None,
    ) -> tuple[int, int]:
        """Import all media for a connection. Returns (examined, imported)."""
        limit = max_posts or self.settings.instagram_max_posts_per_sync
        examined = 0
        imported = 0
        after = None

        while examined < limit:
            page = self._run_async(self.fetch_media_page(connection, after=after, limit=50))
            data = page.get("data", [])
            if not data:
                break

            for media in data:
                if examined >= limit:
                    break
                if media.get("media_type") not in SUPPORTED_MEDIA_TYPES:
                    examined += 1
                    continue

                self._map_media_to_post(connection, media)
                examined += 1
                imported += 1

            paging = page.get("paging", {})
            after = paging.get("cursors", {}).get("after")
            if not after:
                break

        self.db.commit()
        return examined, imported

    # ------------------------------------------------------------------
    # Metric insights sync
    # ------------------------------------------------------------------
    async def fetch_media_insights(
        self,
        connection: InstagramConnection,
        media_id: str,
        media_type: str,
    ) -> dict[str, Any]:
        """Fetch insights for a single media item."""
        token = await self.ensure_valid_token(connection)
        metrics = MEDIA_INSIGHT_METRICS.get(media_type, MEDIA_INSIGHT_METRICS["IMAGE"])

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url(f"/{media_id}/insights"),
                params={
                    "metric": ",".join(metrics),
                    "access_token": token,
                },
            )
            if resp.is_success:
                return resp.json()
            error = resp.json().get("error", {})
            # Some metrics may not be available for all posts — log and return empty
            logger.warning(
                "Insights fetch failed for media %s: %s",
                media_id,
                error.get("message") if isinstance(error, dict) else None,
            )
            return {"data": []}

    def _normalize_media_insights(
        self,
        media: dict[str, Any],
        insights_data: dict[str, Any],
    ) -> MetricSnapshotInput:
        """Convert Meta insights to our MetricSnapshotInput schema."""
        metrics_map: dict[str, Any] = {}
        for item in insights_data.get("data", []):
            name = item.get("name")
            val: Any = None
            if "total_value" in item:
                # v22+ metrics (reach, views, ...) return total_value instead of values[]
                tv = item["total_value"]
                if isinstance(tv, dict):
                    val = tv.get("total", tv.get("value"))
                else:
                    val = tv
            else:
                values = item.get("values", [])
                if values:
                    # Take the most recent value
                    val = values[-1].get("value")
                    if isinstance(val, dict):
                        # Some metrics return breakdowns; take total if available
                        val = val.get("total", val.get("value"))
            if val is not None:
                metrics_map[name] = val

        # Map Meta metric names to our schema.
        # Instagram Login flow reports "saved"/"views"; older FB-login payloads
        # used "saves"/"video_views" — accept both.
        return MetricSnapshotInput(
            views=metrics_map.get("views")
            or metrics_map.get("video_views")
            or metrics_map.get("impressions"),
            impressions=metrics_map.get("impressions"),
            likes=metrics_map.get("likes"),
            comments=metrics_map.get("comments"),
            shares=metrics_map.get("shares"),
            saves=metrics_map.get("saved") or metrics_map.get("saves"),
            link_clicks=None,  # Not directly available from media insights
            watch_time_seconds=None,
            avg_watch_duration_seconds=None,
            audience_retention_pct=None,
            ctr_pct=None,
            source="platform",
            recorded_at=datetime.now(timezone.utc),
        )

    def sync_metrics(
        self,
        connection: InstagramConnection,
        max_posts: int | None = None,
    ) -> tuple[int, int]:
        """Sync metrics for recently imported media. Returns (examined, snapshots_created)."""
        # Get posts that belong to this connection (by external_id pattern or platform)
        posts = list(
            self.db.scalars(
                select(PublishedPost)
                .where(
                    PublishedPost.user_id == self.user_id,
                    PublishedPost.platform == "Instagram",
                )
                .order_by(PublishedPost.published_at.desc())
                .limit(max_posts or self.settings.instagram_max_posts_per_sync)
            )
        )

        examined = 0
        snapshots_created = 0

        for post in posts:
            if max_posts and examined >= max_posts:
                break
            examined += 1

            # Fetch insights for this post
            try:
                insights = self._run_async(
                    self.fetch_media_insights(connection, post.external_id, "")
                )
                # We need media_type to know which metrics to expect; fetch media info
                media_info = self._run_async(self._fetch_media_info(connection, post.external_id))
                media_type = media_info.get("media_type", "IMAGE")
            except Exception as e:
                logger.warning("Failed to fetch insights for post %s: %s", post.id, e)
                continue

            snapshot_input = self._normalize_media_insights(
                {"media_type": media_type}, insights
            )
            snapshot = build_snapshot(post, snapshot_input)
            self.db.add(snapshot)
            snapshots_created += 1

        self.db.commit()
        return examined, snapshots_created

    async def _fetch_media_info(
        self, connection: InstagramConnection, media_id: str
    ) -> dict[str, Any]:
        token = await self.ensure_valid_token(connection)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                self._graph_url(f"/{media_id}"),
                params={
                    "fields": "id,media_type",
                    "access_token": token,
                },
            )
            if resp.is_success:
                return resp.json()
            return {}

    # ------------------------------------------------------------------
    # Sync orchestration
    # ------------------------------------------------------------------
    def start_sync_job(self, connection_id: int) -> InstagramSyncJob:
        """Create a new sync job record."""
        job = InstagramSyncJob(
            connection_id=connection_id,
            user_id=self.user_id,
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(job)
        self.db.commit()
        self.db.refresh(job)
        return job

    def complete_sync_job(
        self,
        job: InstagramSyncJob,
        status: str,
        posts_examined: int = 0,
        posts_imported: int = 0,
        snapshots_created: int = 0,
        error_category: str = "",
        error_message: str = "",
    ) -> None:
        job.status = status
        job.completed_at = datetime.now(timezone.utc)
        job.posts_examined = posts_examined
        job.posts_imported = posts_imported
        job.snapshots_created = snapshots_created
        job.error_category = error_category
        job.error_message = error_message
        self.db.commit()

    def run_full_sync(self, connection_id: int, max_posts: int | None = None) -> InstagramSyncJob:
        """Run a full sync: import media + sync metrics."""
        connection = self.get_connection(connection_id)
        if not connection:
            raise ValueError("Connection not found")

        job = self.start_sync_job(connection_id)
        try:
            # Update connection status
            connection.last_sync_at = datetime.now(timezone.utc)
            connection.last_sync_status = "running"
            self.db.commit()

            # Import media
            examined, imported = self.import_media(connection, max_posts=max_posts)

            # Sync metrics
            metrics_examined, snapshots = self.sync_metrics(connection, max_posts=max_posts)

            # Update connection
            connection.last_sync_at = datetime.now(timezone.utc)
            connection.last_sync_status = "succeeded"
            connection.last_sync_error = ""
            self.db.commit()

            self.complete_sync_job(
                job,
                status="succeeded",
                posts_examined=examined,
                posts_imported=imported,
                snapshots_created=snapshots,
            )
        except Exception as e:
            connection.last_sync_at = datetime.now(timezone.utc)
            connection.last_sync_status = "failed"
            connection.last_sync_error = str(e)[:500]
            self.db.commit()

            self.complete_sync_job(
                job,
                status="failed",
                error_category=type(e).__name__,
                error_message=str(e)[:500],
            )
            raise

        return job

    def _run_async(self, coro):
        """Helper to run async methods in sync context (for now)."""
        import asyncio
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)