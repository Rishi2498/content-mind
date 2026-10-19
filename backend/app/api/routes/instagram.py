"""Phase 6 — Instagram (Meta) integration routes.

Endpoints:
- GET  /instagram/authorize           - Start OAuth flow, returns authorize URL
- GET  /instagram/callback            - OAuth callback (Meta redirects here)
- GET  /instagram/connections         - List connected accounts
- GET  /instagram/connections/{id}    - Get connection details
- DELETE /instagram/connections/{id}  - Disconnect an account
- POST /instagram/connections/{id}/sync - Trigger manual sync
- GET  /instagram/connections/{id}/sync-history - Sync job history
- GET  /instagram/connections/{id}/posts - List imported posts
- GET  /instagram/connections/{id}/insights - Account-level insights
"""

from __future__ import annotations

import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...auth import get_current_user
from ...config import get_settings
from ...database import get_db
from ...models import InstagramConnection, InstagramSyncJob, PublishedPost, User
from ...schemas import (
    InstagramAccountInsightsRead,
    InstagramAuthUrlResponse,
    InstagramConnectionListResponse,
    InstagramConnectionRead,
    InstagramPostListResponse,
    InstagramSyncJobListResponse,
    InstagramSyncJobRead,
    InstagramSyncTriggerRequest,
    InstagramSyncTriggerResponse,
)
from ...services.instagram_service import (
    ACCOUNT_INSIGHT_METRICS,
    INSTAGRAM_TOKEN_URL,
    REQUIRED_SCOPES,
    InstagramAPIError,
    InstagramService,
    OAuthState,
    _parse_api_error,
)
from ...services.performance_service import post_to_read

logger = logging.getLogger("contentmind.routes.instagram")

router = APIRouter()

# Maximum age of an OAuth state param before we reject it (CSRF window)
OAUTH_STATE_MAX_AGE_MINUTES = 10


# ----------------------------------------------------------------------------------
# OAuth — Start & Callback
# ----------------------------------------------------------------------------------
@router.get("/authorize", response_model=InstagramAuthUrlResponse)
def start_oauth(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramAuthUrlResponse:
    """Initiate Instagram OAuth flow. Returns the authorize URL to redirect the user."""
    settings = get_settings()
    if not settings.instagram_configured:
        raise HTTPException(
            status_code=503,
            detail="Instagram integration not configured.",
        )

    svc = InstagramService(db, current_user.id)
    authorize_url, state = svc.build_authorize_url()

    # Safe diagnostics only: hosts, the redirect URI (not a secret), scope names
    # and presence/shape flags. The app id/secret values and the state/signed
    # token are never logged. client_id is public (it appears in the authorize
    # URL) but is still masked to its last 4 digits for hygiene.
    parsed = urllib.parse.urlparse(authorize_url)
    token_host = urllib.parse.urlparse(INSTAGRAM_TOKEN_URL).netloc
    logger.info(
        "Instagram authorize: authorize_host=%s token_host=%s redirect_uri=%s "
        "redirect_uri_encoded=%s scopes=%s response_type=code "
        "app_id_present=%s app_id_length=%d app_id_numeric=%s "
        "app_id_last4=%s app_secret_present=%s",
        parsed.netloc,
        token_host,
        settings.instagram_redirect_uri,
        urllib.parse.quote(settings.instagram_redirect_uri, safe=""),
        ",".join(REQUIRED_SCOPES),
        bool(settings.instagram_app_id),
        len(settings.instagram_app_id),
        settings.instagram_app_id.isdigit(),
        settings.instagram_app_id[-4:] if settings.instagram_app_id else "",
        bool(settings.instagram_app_secret),
    )
    # The authorize and token-exchange requests must send the identical
    # redirect_uri, otherwise Instagram rejects the exchange even when the
    # authorize step was accepted.
    if parsed.netloc != "www.instagram.com":
        logger.warning(
            "Instagram authorize host is %s, expected www.instagram.com for Instagram Login.",
            parsed.netloc,
        )
    for hint in settings.instagram_config_warnings():
        logger.warning("Instagram authorize config: %s", hint)

    return InstagramAuthUrlResponse(authorize_url=authorize_url, state=state.to_url_param())


@router.get("/callback")
async def oauth_callback(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    error_reason: str | None = Query(default=None),
    error_description: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Handle OAuth callback from Meta. Exchanges code for tokens and stores connection."""
    settings = get_settings()
    frontend_url = settings.instagram_frontend_base_url

    def _redirect_error(message: str, code: str = "oauth_error") -> RedirectResponse:
        query = urllib.parse.urlencode({"error": message, "error_code": code})
        return RedirectResponse(f"{frontend_url}/instagram?{query}")

    # Handle OAuth errors from Meta (user denied, invalid scopes, etc.)
    if error:
        logger.warning("OAuth error: %s - %s", error, error_description)
        error_msg = error_description or error_reason or error
        # Preserve Meta's code (e.g. "access_denied" = the user cancelled)
        return _redirect_error(error_msg, code=error)

    # The callback is always reached via a browser redirect (no Bearer token),
    # so every failure is surfaced to the frontend instead of raw JSON.
    if not code or not state:
        logger.warning("OAuth callback missing code or state parameter")
        return _redirect_error("Missing authorization code or state", "missing_params")

    # Decode and validate the signed state (CSRF protection + user correlation)
    state_obj = OAuthState.from_url_param(state)
    if state_obj is None:
        logger.warning("Invalid or forged OAuth state parameter")
        return _redirect_error("Invalid or expired state parameter", "invalid_state")
    if datetime.now(timezone.utc) - state_obj.created_at > timedelta(
        minutes=OAUTH_STATE_MAX_AGE_MINUTES
    ):
        logger.warning("Expired OAuth state parameter")
        return _redirect_error("OAuth state expired", "state_expired")
    user_id = state_obj.user_id

    # Get the user the flow was started for (never taken from query params)
    user = db.get(User, user_id)
    if not user:
        logger.warning("OAuth callback referenced unknown user id")
        return _redirect_error("Your session is no longer valid", "session_expired")

    # Exchange code for tokens via the Instagram Login flow
    svc = InstagramService(db, user_id)
    try:
        token_data = await svc.exchange_code_for_token(code)
        short_token = token_data.get("access_token")
        if not short_token:
            logger.error("Token exchange response missing access_token")
            return _redirect_error("Failed to exchange authorization code", "token_exchange_failed")
        # Exchange for long-lived token (60 days)
        long_token_data = await svc.exchange_short_lived_for_long_lived(short_token)
        long_token = long_token_data["access_token"]
        expires_in = long_token_data.get("expires_in")
    except InstagramAPIError as e:
        logger.error("Token exchange failed: %s", e)
        return _redirect_error(f"Failed to exchange token: {e}", "token_exchange_failed")

    # Fetch account info to get Instagram account ID and metadata
    try:
        account_data = await svc.fetch_user_info(long_token)
    except InstagramAPIError as e:
        logger.error("Failed to fetch account info: %s", e)
        return _redirect_error("Failed to fetch Instagram account info", "account_fetch_failed")

    # Instagram Login flow: the professional account ID is in user_id
    instagram_account_id = account_data.get("user_id") or account_data.get("id")
    if not instagram_account_id:
        logger.error("Account info response missing user_id")
        return _redirect_error("Failed to fetch Instagram account info", "account_fetch_failed")

    # Store the connection with encrypted token
    conn = svc.store_connection(
        instagram_account_id=instagram_account_id,
        username=account_data.get("username", ""),
        account_type=account_data.get("account_type", ""),
        access_token=long_token,
        expires_in=expires_in,
        scopes=list(REQUIRED_SCOPES),
        media_count=account_data.get("media_count"),
        followers_count=account_data.get("followers_count"),
        follows_count=account_data.get("follows_count"),
        profile_picture_url=account_data.get("profile_picture_url", ""),
    )

    # Redirect to frontend success page
    return RedirectResponse(f"{frontend_url}/instagram?connected={conn.id}")


# ----------------------------------------------------------------------------------
# Connections CRUD
# ----------------------------------------------------------------------------------
@router.get("/connections", response_model=InstagramConnectionListResponse)
def list_connections(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramConnectionListResponse:
    svc = InstagramService(db, current_user.id)
    connections = svc.list_connections()
    return InstagramConnectionListResponse(
        items=[InstagramConnectionRead.model_validate(c) for c in connections],
        total=len(connections),
    )


@router.get("/connections/{connection_id}", response_model=InstagramConnectionRead)
def get_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramConnectionRead:
    svc = InstagramService(db, current_user.id)
    conn = svc.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return InstagramConnectionRead.model_validate(conn)


@router.delete("/connections/{connection_id}")
def disconnect_connection(
    connection_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    svc = InstagramService(db, current_user.id)
    if not svc.disconnect_connection(connection_id):
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"status": "disconnected"}


# ----------------------------------------------------------------------------------
# Sync
# ----------------------------------------------------------------------------------
@router.post("/connections/{connection_id}/sync", response_model=InstagramSyncTriggerResponse)
def trigger_sync(
    connection_id: int,
    payload: InstagramSyncTriggerRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramSyncTriggerResponse:
    svc = InstagramService(db, current_user.id)
    max_posts = payload.max_posts if payload else None
    try:
        job = svc.run_full_sync(connection_id, max_posts=max_posts)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Sync failed for connection %s", connection_id)
        raise HTTPException(status_code=500, detail=f"Sync failed: {e}")

    return InstagramSyncTriggerResponse(
        job=InstagramSyncJobRead.model_validate(job), connection_id=connection_id
    )


@router.get("/connections/{connection_id}/sync-history", response_model=InstagramSyncJobListResponse)
def list_sync_history(
    connection_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramSyncJobListResponse:
    # Verify connection ownership
    conn = db.scalar(
        select(InstagramConnection).where(
            InstagramConnection.id == connection_id,
            InstagramConnection.user_id == current_user.id,
        )
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    base = select(InstagramSyncJob).where(InstagramSyncJob.connection_id == connection_id)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    jobs = list(
        db.scalars(
            base.order_by(InstagramSyncJob.started_at.desc()).limit(limit).offset(offset)
        )
    )
    return InstagramSyncJobListResponse(
        items=[InstagramSyncJobRead.model_validate(j) for j in jobs],
        total=total,
    )


# ----------------------------------------------------------------------------------
# Imported posts
# ----------------------------------------------------------------------------------
@router.get("/connections/{connection_id}/posts", response_model=InstagramPostListResponse)
def list_imported_posts(
    connection_id: int,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramPostListResponse:
    # Verify connection ownership
    conn = db.scalar(
        select(InstagramConnection).where(
            InstagramConnection.id == connection_id,
            InstagramConnection.user_id == current_user.id,
        )
    )
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    base = select(PublishedPost).where(
        PublishedPost.user_id == current_user.id,
        PublishedPost.platform == "Instagram",
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    posts = list(
        db.scalars(
            base.order_by(PublishedPost.published_at.desc()).limit(limit).offset(offset)
        )
    )

    items = [post_to_read(p) for p in posts]

    return InstagramPostListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


# ----------------------------------------------------------------------------------
# Account insights
# ----------------------------------------------------------------------------------
@router.get("/connections/{connection_id}/insights", response_model=InstagramAccountInsightsRead)
async def get_account_insights(
    connection_id: int,
    period: Literal["day", "week", "days_28"] = Query(default="day"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InstagramAccountInsightsRead:
    svc = InstagramService(db, current_user.id)
    conn = svc.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")

    try:
        token = await svc.ensure_valid_token(conn)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                svc._graph_url(f"/{conn.instagram_account_id}/insights"),
                params={
                    "metric": ",".join(ACCOUNT_INSIGHT_METRICS),
                    "period": period,
                    "access_token": token,
                },
            )
            if not resp.is_success:
                raise _parse_api_error(resp.json(), "Failed to fetch insights")
            data = resp.json()

        # Parse the response. v22+ metrics (views, reach) return total_value;
        # legacy metrics (profile_views, website_clicks) return values[].
        metrics = {}
        for item in data.get("data", []):
            name = item.get("name")
            val = None
            if "total_value" in item:
                tv = item["total_value"]
                val = tv.get("total", tv.get("value")) if isinstance(tv, dict) else tv
            else:
                values = item.get("values", [])
                if values:
                    val = values[-1].get("value")
                    if isinstance(val, dict):
                        val = val.get("total", val.get("value"))
            if val is not None:
                metrics[name] = val

        # "views" (v22+) replaces the deprecated "impressions" account metric;
        # report it in the impressions field for schema compatibility.
        impressions = metrics.get("impressions") or metrics.get("views")

        return InstagramAccountInsightsRead(
            account_id=conn.instagram_account_id,
            username=conn.username,
            period=period,
            impressions=impressions,
            reach=metrics.get("reach"),
            profile_views=metrics.get("profile_views"),
            follower_count=metrics.get("follower_count"),
            website_clicks=metrics.get("website_clicks"),
            collected_at=datetime.now(timezone.utc),
        )
    except InstagramAPIError as e:
        logger.warning("Insights fetch failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Failed to fetch insights: {e}")


@router.get("/config-status", response_model=dict)
def config_status() -> dict:
    """Safe diagnostic: reports which required Instagram configuration variables
    are present or missing without exposing their values.

    Returns:
        - instagram_configured: bool
        - variables: dict with keys 'app_id', 'app_secret', 'redirect_uri'
          each valued 'present' or 'missing'
    """
    from app.config import get_settings
    settings = get_settings()
    required = {
        "instagram_configured": settings.instagram_configured,
    }
    var_status: dict[str, str] = {}
    if settings.instagram_app_id:
        var_status["app_id"] = "present"
    else:
        var_status["app_id"] = "missing"
    if settings.instagram_app_secret:
        var_status["app_secret"] = "present"
    else:
        var_status["app_secret"] = "missing"
    if settings.instagram_redirect_uri:
        var_status["redirect_uri"] = "present"
    else:
        var_status["redirect_uri"] = "missing"
    required["variables"] = var_status
    return required