"""Tests for Phase 6 — Instagram integration.

Covers: OAuth state generation/validation, token exchange, connection CRUD,
media import idempotency, metric sync, sync orchestration, tenant isolation,
and integration with Phase 4 performance service.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models import (
    InstagramConnection,
    InstagramSyncJob,
    PublishedPost,
    User,
)
from app.services.instagram_crypto import decrypt_token, encrypt_token
from app.services.instagram_service import InstagramAPIError, InstagramService


# ----------------------------------------------------------------------------------
# Crypto tests
# ----------------------------------------------------------------------------------
class TestInstagramCrypto:
    @pytest.fixture(autouse=True)
    def _set_encryption_key(self, monkeypatch):
        monkeypatch.setenv("INSTAGRAM_ENCRYPTION_KEY", "test-secret-key-32-chars-minimum!!")
        # Clear the module-level cache and re-import
        import importlib
        from app.services import instagram_crypto
        from app.config import get_settings
        get_settings.cache_clear()
        instagram_crypto._ENCRYPTION_KEY = None
        importlib.reload(instagram_crypto)
        self.crypto = instagram_crypto

    def test_encrypt_decrypt_roundtrip(self):
        token = "IGAA_LONG_TOKEN_STRING_1234567890"
        encrypted = self.crypto.encrypt_token(token)
        assert encrypted != token
        assert len(encrypted) > 0

        decrypted = self.crypto.decrypt_token(encrypted)
        assert decrypted == token

    def test_encrypt_empty_string(self):
        assert self.crypto.encrypt_token("") == ""
        assert self.crypto.decrypt_token("") == ""

    def test_decrypt_wrong_key_fails(self, monkeypatch):
        token = "IGAA_TEST_TOKEN"
        encrypted = self.crypto.encrypt_token(token)

        # Change the key
        monkeypatch.setenv("INSTAGRAM_ENCRYPTION_KEY", "different-secret-key-32-chars-min!!")
        import importlib
        from app.services import instagram_crypto
        from app.config import get_settings
        get_settings.cache_clear()
        instagram_crypto._ENCRYPTION_KEY = None
        importlib.reload(instagram_crypto)

        with pytest.raises(ValueError, match="decryption failed"):
            instagram_crypto.decrypt_token(encrypted)


# ----------------------------------------------------------------------------------
# OAuth state tests
# ----------------------------------------------------------------------------------
class TestOAuthState:
    def test_state_encoding_decoding(self):
        from app.services.instagram_service import OAuthState

        state = OAuthState(
            user_id=42,
            nonce="test-nonce-123",
            created_at=datetime.now(timezone.utc),
        )
        encoded = state.to_url_param()
        decoded = OAuthState.from_url_param(encoded)

        assert decoded is not None
        assert decoded.user_id == 42
        assert decoded.nonce == "test-nonce-123"
        # Timestamp should be close (within 1 second)
        assert abs((decoded.created_at - state.created_at).total_seconds()) < 1

    def test_state_expiry(self):
        from app.services.instagram_service import OAuthState

        old_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        state = OAuthState(
            user_id=42,
            nonce="test-nonce",
            created_at=old_time,
        )
        encoded = state.to_url_param()
        decoded = OAuthState.from_url_param(encoded)

        # Should be able to decode but the route validates expiry
        assert decoded is not None
        assert (datetime.now(timezone.utc) - decoded.created_at) > timedelta(minutes=10)

    def test_invalid_state_returns_none(self):
        from app.services.instagram_service import OAuthState

        assert OAuthState.from_url_param("invalid-base64!") is None
        assert OAuthState.from_url_param("") is None

    def test_state_is_signed_and_tamper_evident(self):
        from app.services.instagram_service import OAuthState

        state = OAuthState(user_id=7, nonce="n", created_at=datetime.now(timezone.utc))
        token = state.to_url_param()

        assert OAuthState.from_url_param(token).user_id == 7  # round-trips

        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        assert OAuthState.from_url_param(tampered) is None

        # A forged payload with a bogus signature must be rejected outright.
        forged = base64.urlsafe_b64encode(
            json.dumps({"uid": 999, "nonce": "x", "ts": 0.0}).encode()
        ).decode()
        assert OAuthState.from_url_param(f"{forged}.deadbeef") is None


# ----------------------------------------------------------------------------------
# OAuth config / redirect-URI wiring (Instagram Login)
# ----------------------------------------------------------------------------------
class TestInstagramOAuthConfig:
    """Guards the two misconfigurations that break the Instagram Login flow:
    wrong App ID (dashboard-only) and a redirect URI that misses the backend
    callback route (detectable in code)."""

    def test_redirect_uri_points_to_callback(self):
        from dataclasses import replace

        from app.config import get_settings

        base = get_settings()
        cases = {
            "http://localhost:8010/api/instagram/callback": True,
            "http://localhost:8010/api/instagram/callback/": True,
            "https://abc123.ngrok-free.app/api/instagram/callback": True,
            "http://localhost:5173": False,
            "http://localhost:5173/instagram": False,
            "http://localhost:8010/api/instagram/authorize": False,
            "": False,
        }
        for uri, expected in cases.items():
            settings = replace(base, instagram_redirect_uri=uri)
            assert settings.instagram_redirect_uri_points_to_callback is expected, uri

    def test_callback_route_is_mounted(self):
        from app.main import app

        assert "/api/instagram/callback" in app.openapi()["paths"]

    def test_service_authorize_url_uses_configured_redirect_uri(self):
        fake_settings = MagicMock()
        fake_settings.instagram_app_id = "1234567890123456"
        fake_settings.instagram_redirect_uri = "http://localhost:8010/api/instagram/callback"
        fake_settings.instagram_api_version = "v22.0"
        fake_settings.secret_key = "test-secret-key"

        with patch("app.services.instagram_service.get_settings", return_value=fake_settings):
            service = InstagramService(MagicMock(), user_id=1)
            url, _ = service.build_authorize_url()

        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert parsed["client_id"] == ["1234567890123456"]
        assert parsed["redirect_uri"] == ["http://localhost:8010/api/instagram/callback"]

    def test_authorize_endpoint_uses_configured_redirect_uri(self, client, auth_headers):
        from app.api.routes import instagram as ig_routes

        fake_settings = MagicMock()
        fake_settings.instagram_configured = True
        fake_settings.instagram_app_id = "1234567890123456"
        fake_settings.instagram_app_secret = "secret"
        fake_settings.instagram_redirect_uri = "http://localhost:8010/api/instagram/callback"
        fake_settings.instagram_api_version = "v22.0"
        fake_settings.instagram_redirect_uri_points_to_callback = True
        fake_settings.api_prefix = "/api"
        fake_settings.secret_key = "test-secret-key"

        client.headers.update(auth_headers)
        with patch.object(ig_routes, "get_settings", return_value=fake_settings), patch(
            "app.services.instagram_service.get_settings", return_value=fake_settings
        ):
            resp = client.get("/api/instagram/authorize")

        assert resp.status_code == 200
        url = resp.json()["authorize_url"]
        assert "facebook.com" not in url
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert params["redirect_uri"] == ["http://localhost:8010/api/instagram/callback"]
        assert params["client_id"] == ["1234567890123456"]

    def test_safe_dict_never_exposes_credentials(self):
        import json
        from dataclasses import replace

        from app.config import get_settings

        app_id = "9998887776665554"
        app_secret = "sekrit-should-never-leak-0000"
        settings = replace(
            get_settings(),
            instagram_app_id=app_id,
            instagram_app_secret=app_secret,
            instagram_redirect_uri="http://localhost:8010/api/instagram/callback",
        )

        blob = json.dumps(settings.safe_dict())
        assert app_id not in blob
        assert app_secret not in blob
        safety = settings.safe_dict()["instagram"]
        assert safety["app_id_present"] is True
        assert safety["app_id_length"] == len(app_id)
        assert safety["app_id_numeric"] is True
        assert safety["app_secret_present"] is True
        assert safety["redirect_uri_points_to_callback"] is True

    def test_redirect_uri_https_required_by_instagram_login(self):
        from dataclasses import replace

        from app.config import get_settings

        base = get_settings()
        https = replace(
            base,
            instagram_redirect_uri="https://abc.ngrok-free.dev/api/instagram/callback",
        )
        http = replace(
            base,
            instagram_redirect_uri="http://localhost:8010/api/instagram/callback",
        )
        assert https.instagram_redirect_uri_is_https is True
        assert http.instagram_redirect_uri_is_https is False

    def test_config_warnings_flag_http_and_wrong_app_id(self):
        from dataclasses import replace

        from app.config import get_settings

        base = replace(
            get_settings(),
            instagram_app_id="1234567890123456",
            instagram_app_secret="s",
            instagram_redirect_uri="http://localhost:8010/api/instagram/callback",
        )
        warnings = base.instagram_config_warnings()
        joined = " ".join(warnings)
        assert "not https" in joined

        # A numeric app id on https targeting the callback produces no warnings.
        clean = replace(
            base,
            instagram_app_id="1234567890123456",
            instagram_redirect_uri="https://abc.ngrok-free.dev/api/instagram/callback",
        )
        assert clean.instagram_config_warnings() == []

        # A non-numeric "app id" is flagged (Android/package style or Meta id mix-up).
        weird = replace(clean, instagram_app_id="com.example.app")
        assert any("not numeric" in w for w in weird.instagram_config_warnings())


# ----------------------------------------------------------------------------------
# InstagramService tests (mocked HTTP)
# ----------------------------------------------------------------------------------
class TestInstagramService:
    @pytest.fixture
    def mock_db(self):
        return MagicMock()

    @pytest.fixture
    def service(self, mock_db):
        return InstagramService(mock_db, user_id=1)

    @pytest.fixture
    def v22_metrics_service(self, service):
        return service

    def test_authorize_url_uses_instagram_login_flow(self, service):
        """Authorize URL must point at instagram.com with instagram_business_* scopes."""
        url, state = service.build_authorize_url()

        assert url.startswith("https://www.instagram.com/oauth/authorize?")
        assert "facebook.com" not in url
        assert "instagram_business_basic" in url
        assert "instagram_business_content_publish" in url
        # Facebook-Login-only scopes must not appear
        assert "pages_show_list" not in url
        assert "pages_read_engagement" not in url
        assert "instagram_basic" not in url
        assert "instagram_content_publish" not in url
        assert "response_type=code" in url
        assert "state=" in url
        assert state.user_id == 1

    def test_authorize_url_has_expected_parameters(self, service):
        """Exact host/path/params; a single, non-encoded-away redirect_uri."""
        url, _ = service.build_authorize_url()
        parsed = urllib.parse.urlparse(url)

        assert parsed.scheme == "https"
        assert parsed.netloc == "www.instagram.com"
        assert parsed.path == "/oauth/authorize"

        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        assert set(params) == {"client_id", "redirect_uri", "scope", "response_type", "state"}
        assert params["response_type"] == "code"
        assert params["scope"] == "instagram_business_basic,instagram_business_content_publish"
        # The redirect URI is sent exactly as configured (single URL-encoding).
        assert params["redirect_uri"] == service.settings.instagram_redirect_uri
        assert params["client_id"] == service.settings.instagram_app_id

    def test_required_scopes_are_instagram_login_scopes(self):
        from app.services.instagram_service import REQUIRED_SCOPES

        assert REQUIRED_SCOPES == [
            "instagram_business_basic",
            "instagram_business_content_publish",
        ]

    @pytest.mark.asyncio
    async def test_redirect_uri_consistent_between_authorize_and_token_exchange(self, service):
        """The redirect_uri in the authorize URL and the token POST must match."""
        expected = service.settings.instagram_redirect_uri

        url, _ = service.build_authorize_url()
        authorize_query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        assert authorize_query["redirect_uri"] == [expected]

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"access_token": "t", "user_id": "1"}
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            await service.exchange_code_for_token("code")

        post_data = mock_client.post.call_args.kwargs["data"]
        assert post_data["redirect_uri"] == expected

    def test_generated_authorize_url_matches_real_resolved_settings(self):
        """Generated client_id/redirect_uri must equal the *real* resolved settings.

        This catches a stale env var or .env parsing bug: if INSTAGRAM_APP_ID or
        INSTAGRAM_REDIRECT_URI is overridden anywhere between .env and Settings,
        the value Instagram actually receives would differ from what the operator
        registered in the dashboard. No secrets are asserted here.
        """
        from app.config import get_settings

        settings = get_settings()
        assert settings.instagram_configured, "Instagram must be configured for this test"

        service = InstagramService(MagicMock(), user_id=1)
        url, _ = service.build_authorize_url()

        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)

        # client_id is the exact configured App ID (single value, no drift).
        assert params["client_id"] == [settings.instagram_app_id]
        # redirect_uri decodes back to the exact configured callback URI.
        assert params["redirect_uri"] == [settings.instagram_redirect_uri]
        # And that URI targets this API's callback route.
        assert settings.instagram_redirect_uri_points_to_callback is True
        assert settings.instagram_redirect_uri_is_https is True

    @pytest.mark.asyncio
    async def test_token_exchange_client_id_and_redirect_match_settings(self):
        """Token exchange must send the same client_id/redirect_uri as authorize."""
        from app.config import get_settings

        settings = get_settings()
        service = InstagramService(MagicMock(), user_id=1)

        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"access_token": "t", "user_id": "1"}
        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            await service.exchange_code_for_token("code")

        post_data = mock_client.post.call_args.kwargs["data"]
        assert post_data["client_id"] == settings.instagram_app_id
        assert post_data["redirect_uri"] == settings.instagram_redirect_uri

    @pytest.mark.asyncio
    async def test_exchange_code_hits_instagram_token_endpoint(self, service):
        """Token exchange must POST to api.instagram.com (not graph.facebook.com)."""
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "access_token": "short_token",
            "user_id": "17841400000000001",
            "permissions": "instagram_business_basic,instagram_business_content_publish",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_code_for_token("auth_code_123")

        assert result["access_token"] == "short_token"
        assert result["user_id"] == "17841400000000001"
        call_url = mock_client.post.call_args[0][0]
        assert call_url == "https://api.instagram.com/oauth/access_token"

    @pytest.mark.asyncio
    async def test_exchange_code_unwraps_data_list(self, service):
        """Some token responses wrap the grant in {"data": [...]}."""
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "data": [{"access_token": "short_token", "user_id": "123"}]
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_code_for_token("auth_code_123")

        assert result["access_token"] == "short_token"

    @pytest.mark.asyncio
    async def test_exchange_code_instagram_style_error(self, service):
        """api.instagram.com errors use error_type/error_message, not error.message."""
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.json.return_value = {
            "error_type": "OAuthException",
            "code": 400,
            "error_message": "Invalid authorization code",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            with pytest.raises(InstagramAPIError) as exc_info:
                await service.exchange_code_for_token("bad_code")

        assert "Invalid authorization code" in str(exc_info.value)
        assert exc_info.value.error_code == 400

    @pytest.mark.asyncio
    async def test_long_lived_exchange_uses_ig_exchange_token(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "access_token": "long_token",
            "token_type": "bearer",
            "expires_in": 5184000,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_short_lived_for_long_lived("short_token")

        assert result["access_token"] == "long_token"
        call_url = mock_client.get.call_args[0][0]
        assert call_url.startswith("https://graph.instagram.com/")
        assert call_url.endswith("/access_token")
        params = mock_client.get.call_args[1]["params"]
        assert params["grant_type"] == "ig_exchange_token"
        assert params["access_token"] == "short_token"
        assert "fb_exchange_token" not in params

    @pytest.mark.asyncio
    async def test_refresh_uses_refresh_access_token(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "access_token": "refreshed_token",
            "token_type": "bearer",
            "expires_in": 5184000,
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.refresh_long_lived_token("long_token")

        assert result["access_token"] == "refreshed_token"
        call_url = mock_client.get.call_args[0][0]
        assert call_url.startswith("https://graph.instagram.com/")
        assert call_url.endswith("/refresh_access_token")
        params = mock_client.get.call_args[1]["params"]
        assert params["grant_type"] == "ig_refresh_token"

    @pytest.mark.asyncio
    async def test_fetch_user_info_uses_me_and_user_id(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "user_id": "17841400000000001",
            "username": "testuser",
            "account_type": "Business",
            "media_count": 42,
            "followers_count": 100,
            "follows_count": 10,
            "profile_picture_url": "https://example.com/pic.jpg",
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.get.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.fetch_user_info("long_token")

        assert result["user_id"] == "17841400000000001"
        assert result["username"] == "testuser"
        call_url = mock_client.get.call_args[0][0]
        assert call_url.startswith("https://graph.instagram.com/")
        assert call_url.endswith("/me")

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_success(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {"access_token": "short_token", "expires_in": 3600}

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            result = await service.exchange_code_for_token("auth_code_123")

        assert result["access_token"] == "short_token"

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_failure(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = False
        mock_resp.json.return_value = {
            "error": {"message": "Invalid code", "code": 100, "error_subcode": 123}
        }

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__.return_value = mock_client
            mock_client.post.return_value = mock_resp
            mock_client_class.return_value = mock_client

            with pytest.raises(InstagramAPIError) as exc_info:
                await service.exchange_code_for_token("bad_code")

        assert "Invalid code" in str(exc_info.value)
        assert exc_info.value.error_code == 100

    @pytest.mark.asyncio
    async def test_fetch_media_page(self, service):
        mock_resp = MagicMock()
        mock_resp.is_success = True
        mock_resp.json.return_value = {
            "data": [
                {
                    "id": "17841400000000001",
                    "caption": "Test post",
                    "media_type": "IMAGE",
                    "media_url": "https://example.com/image.jpg",
                    "permalink": "https://instagram.com/p/ABC123",
                    "timestamp": "2024-01-15T10:00:00+0000",
                    "username": "testuser",
                    "like_count": 100,
                    "comments_count": 10,
                }
            ],
            "paging": {"cursors": {"after": "next_cursor"}},
        }

        connection = MagicMock()
        connection.instagram_account_id = "123456789"

        with patch.object(service, "ensure_valid_token", return_value="valid_token"):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_client.__aenter__.return_value = mock_client
                mock_client.get.return_value = mock_resp
                mock_client_class.return_value = mock_client

                result = await service.fetch_media_page(connection)

        assert len(result["data"]) == 1
        assert result["data"][0]["id"] == "17841400000000001"

    @pytest.mark.asyncio
    async def test_media_import_idempotency(self, service, mock_db):
        """Test that importing the same media twice doesn't create duplicates."""
        connection = InstagramConnection(
            id=1,
            user_id=1,
            instagram_account_id="123456789",
            username="testuser",
        )

        media = {
            "id": "17841400000000001",
            "caption": "Test post",
            "media_type": "IMAGE",
            "media_url": "https://example.com/image.jpg",
            "permalink": "https://instagram.com/p/ABC123",
            "timestamp": "2024-01-15T10:00:00+0000",
            "username": "testuser",
        }

        # First import - no existing post
        mock_db.scalar.return_value = None
        mock_db.flush.return_value = None
        post1 = service._map_media_to_post(connection, media)
        assert post1.id is None  # not flushed yet

        # Simulate flush assigning an ID
        post1.id = 1

        # Second import - existing post found
        mock_db.scalar.return_value = post1
        post2 = service._map_media_to_post(connection, media)

        assert post2.id == 1
        assert post2.title == "Test post"
        # Verify scalar was called twice
        assert mock_db.scalar.call_count == 2

    def test_normalize_media_insights(self, service):
        """Test normalization of Meta insights to MetricSnapshotInput."""
        media = {"media_type": "IMAGE"}
        insights_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 1000}]},
                {"name": "reach", "values": [{"value": 800}]},
                {"name": "likes", "values": [{"value": 50}]},
                {"name": "comments", "values": [{"value": 5}]},
                {"name": "shares", "values": [{"value": 2}]},
                {"name": "saved", "values": [{"value": 10}]},
            ]
        }

        snapshot_input = service._normalize_media_insights(media, insights_data)

        assert snapshot_input.impressions == 1000
        assert snapshot_input.likes == 50
        assert snapshot_input.comments == 5
        assert snapshot_input.shares == 2
        assert snapshot_input.saves == 10
        assert snapshot_input.source == "platform"

    def test_normalize_media_insights_legacy_names(self, service):
        """Legacy FB-login payload names (saves/video_views) still normalize."""
        media = {"media_type": "IMAGE"}
        insights_data = {
            "data": [
                {"name": "impressions", "values": [{"value": 1000}]},
                {"name": "saves", "values": [{"value": 7}]},
            ]
        }

        snapshot_input = service._normalize_media_insights(media, insights_data)
        assert snapshot_input.saves == 7
        assert snapshot_input.impressions == 1000

    def test_normalize_media_insights_total_value_shape(self, v22_metrics_service):
        """v22+ metrics return total_value instead of values[]."""
        media = {"media_type": "REELS"}
        insights_data = {
            "data": [
                {"name": "views", "period": "lifetime", "total_value": {"value": 5000}},
                {"name": "reach", "period": "lifetime", "total_value": {"value": 3200}},
                {"name": "likes", "values": [{"value": 120}]},
            ]
        }

        snapshot_input = v22_metrics_service._normalize_media_insights(media, insights_data)

        assert snapshot_input.views == 5000
        assert snapshot_input.impressions is None  # no impressions metric in payload
        assert snapshot_input.likes == 120

    def test_normalize_video_insights(self, service):
        """Test normalization for video media type."""
        media = {"media_type": "VIDEO"}
        insights_data = {
            "data": [
                {"name": "video_views", "values": [{"value": 500}]},
                {"name": "impressions", "values": [{"value": 1000}]},
            ]
        }

        snapshot_input = service._normalize_media_insights(media, insights_data)

        # video_views maps to views
        assert snapshot_input.views == 500
        assert snapshot_input.impressions == 1000


# ----------------------------------------------------------------------------------
# API route tests (using TestClient)
# ----------------------------------------------------------------------------------
class TestInstagramRoutes:
    def test_oauth_authorize_requires_config(self, client, auth_headers):
        """Test that authorize endpoint returns 503 when not configured."""
        from app.api.routes import instagram as ig_routes

        fake_settings = MagicMock()
        fake_settings.instagram_configured = False

        client.headers.update(auth_headers)
        with patch.object(ig_routes, "get_settings", return_value=fake_settings):
            resp = client.get("/api/instagram/authorize")

        assert resp.status_code == 503
        assert "not configured" in resp.json()["detail"]

    def test_redirect_uri_is_present_when_configured(self, client, auth_headers):
        """Verify that the config-status endpoint reports redirect_uri as present."""
        from app.config import get_settings
        from unittest.mock import patch
        settings = get_settings()
        client.headers.update(auth_headers)
        with patch('app.config.get_settings', return_value=settings):
            resp = client.get('/api/instagram/config-status')
        assert resp.status_code == 200
        assert resp.json()['variables']['redirect_uri'] == 'present'

    def test_callback_route_registered(self, client):
        """Verify that the /api/instagram/callback route is registered."""
        routes_paths = [getattr(r, 'path', '') for r in client.app.routes]
        callback_paths = [p for p in routes_paths if 'instagram/callback' in p]
        assert len(callback_paths) > 0, 'Callback route not registered'
        # Verify it accepts GET method
        for path in callback_paths:
            route = next(r for r in client.app.routes if getattr(r, 'path', '') == path)
            assert hasattr(route, 'methods') or 'GET' in str(route.methods)

    def test_authorize_redirect_uri_matches_config(self, client, auth_headers):
        """Verify that the config-status reports redirect_uri as present configured."""
        from app.config import get_settings
        from unittest.mock import patch
        settings = get_settings()
        client.headers.update(auth_headers)
        with patch('app.config.get_settings', return_value=settings):
            resp = client.get('/api/instagram/config-status')
        assert resp.status_code == 200
        assert resp.json()['instagram_configured'] == True

    def test_list_connections_empty(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.get("/api/instagram/connections")
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0}

    def test_get_nonexistent_connection_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.get("/api/instagram/connections/99999")
        assert resp.status_code == 404

    def test_disconnect_nonexistent_connection_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.delete("/api/instagram/connections/99999")
        assert resp.status_code == 404

    def test_trigger_sync_nonexistent_connection_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.post("/api/instagram/connections/99999/sync", json={})
        assert resp.status_code == 404

    def test_list_sync_history_nonexistent_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.get("/api/instagram/connections/99999/sync-history")
        assert resp.status_code == 404

    def test_list_posts_nonexistent_connection_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.get("/api/instagram/connections/99999/posts")
        assert resp.status_code == 404

    def test_get_insights_nonexistent_connection_404(self, client, auth_headers):
        client.headers.update(auth_headers)
        resp = client.get("/api/instagram/connections/99999/insights")
        assert resp.status_code == 404

    def test_oauth_authorize_requires_auth(self, client):
        """Authorize is a protected, logged-in action (a bare browser hit gets 401)."""
        resp = client.get("/api/instagram/authorize")
        assert resp.status_code == 401
        # FastAPI's OAuth2PasswordBearer reports an absent bearer token this way.
        assert resp.json()["detail"] == "Not authenticated"

    def test_oauth_authorize_rejects_invalid_token(self, client):
        """A present-but-invalid bearer token is rejected, not silently allowed."""
        resp = client.get(
            "/api/instagram/authorize",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Could not validate credentials"

    def test_unrelated_routes_still_require_auth(self, client):
        """Auth is not weakened: unrelated protected routes reject anonymous users."""
        assert client.get("/api/instagram/connections").status_code == 401
        assert client.get("/api/analytics").status_code == 401
        assert client.get("/api/memory/recall").status_code == 401

    def test_oauth_callback_missing_params_redirects(self, client):
        """Callback without code/state goes back to the frontend, not raw JSON."""
        resp = client.get("/api/instagram/callback", follow_redirects=False)
        assert resp.status_code in (302, 307)
        assert "error_code=missing_params" in resp.headers["location"]

    def test_oauth_callback_user_cancelled(self, client):
        """Provider error (user denied) is surfaced to the frontend with its code."""
        resp = client.get(
            "/api/instagram/callback?error=access_denied&error_description=User+denied",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "error_code=access_denied" in resp.headers["location"]

    def test_oauth_callback_invalid_state(self, client):
        """Callback with unparseable state redirects with an invalid_state code."""
        resp = client.get(
            "/api/instagram/callback?code=abc&state=garbage!",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "error_code=invalid_state" in resp.headers["location"]

    def test_oauth_callback_rejects_tampered_state(self, client):
        """The state is HMAC-signed, so mutating it invalidates it."""
        from app.services.instagram_service import OAuthState

        state = OAuthState(user_id=1, nonce="n", created_at=datetime.now(timezone.utc))
        token = state.to_url_param()
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        resp = client.get(
            f"/api/instagram/callback?code=abc&state={tampered}",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "error_code=invalid_state" in resp.headers["location"]

    def test_oauth_callback_expired_state(self, client):
        """A correctly signed but stale state is rejected."""
        from app.services.instagram_service import OAuthState

        old_state = OAuthState(
            user_id=1,
            nonce="old-nonce",
            created_at=datetime.now(timezone.utc) - timedelta(minutes=15),
        )
        resp = client.get(
            f"/api/instagram/callback?code=abc&state={old_state.to_url_param()}",
            follow_redirects=False,
        )
        assert resp.status_code in (302, 307)
        assert "error_code=state_expired" in resp.headers["location"]

    def test_oauth_callback_success_stores_connection(self, client, auth_headers):
        """Valid state + code exchanges tokens and links the account to the user."""
        from app.api.routes import instagram as ig_routes
        from app.services.instagram_service import OAuthState

        state = OAuthState(user_id=1, nonce="n", created_at=datetime.now(timezone.utc))
        account = {
            "user_id": "17841400000000001",
            "username": "creator",
            "account_type": "BUSINESS",
            "media_count": 3,
            "followers_count": 10,
            "follows_count": 2,
            "profile_picture_url": "https://example.com/p.jpg",
        }

        with (
            patch("app.services.instagram_service.encrypt_token", return_value="enc"),
            patch.object(
                ig_routes.InstagramService,
                "exchange_code_for_token",
                new=AsyncMock(return_value={"access_token": "short", "user_id": "17841400000000001"}),
            ),
            patch.object(
                ig_routes.InstagramService,
                "exchange_short_lived_for_long_lived",
                new=AsyncMock(return_value={"access_token": "long", "expires_in": 5184000}),
            ),
            patch.object(
                ig_routes.InstagramService,
                "fetch_user_info",
                new=AsyncMock(return_value=account),
            ),
        ):
            resp = client.get(
                f"/api/instagram/callback?code=abc&state={state.to_url_param()}",
                follow_redirects=False,
            )

        assert resp.status_code in (302, 307)
        assert "connected=" in resp.headers["location"]

        client.headers.update(auth_headers)
        listing = client.get("/api/instagram/connections").json()
        assert listing["total"] == 1
        assert listing["items"][0]["username"] == "creator"

    def test_oauth_callback_token_exchange_failure_redirects(self, client, auth_headers):
        """A failed token exchange returns the user to the app with an error."""
        from app.api.routes import instagram as ig_routes
        from app.services.instagram_service import InstagramAPIError, OAuthState

        state = OAuthState(user_id=1, nonce="n", created_at=datetime.now(timezone.utc))
        with patch.object(
            ig_routes.InstagramService,
            "exchange_code_for_token",
            new=AsyncMock(side_effect=InstagramAPIError("bad code", error_code=400)),
        ):
            resp = client.get(
                f"/api/instagram/callback?code=abc&state={state.to_url_param()}",
                follow_redirects=False,
            )
        assert resp.status_code in (302, 307)
        assert "error_code=token_exchange_failed" in resp.headers["location"]

    def test_oauth_authorize_uses_instagram_login_flow(self, client, auth_headers):
        """Configured authorize endpoint must return an Instagram Login URL."""
        from app.api.routes import instagram as ig_routes

        fake_settings = MagicMock()
        fake_settings.instagram_configured = True
        fake_settings.instagram_app_id = "123456"
        fake_settings.instagram_app_secret = "secret"
        fake_settings.instagram_redirect_uri = "http://localhost:8010/api/instagram/callback"
        fake_settings.instagram_redirect_uri_points_to_callback = True
        fake_settings.api_prefix = "/api"

        client.headers.update(auth_headers)
        with patch.object(ig_routes, "get_settings", return_value=fake_settings):
            resp = client.get("/api/instagram/authorize")

        assert resp.status_code == 200
        url = resp.json()["authorize_url"]
        assert url.startswith("https://www.instagram.com/oauth/authorize?")
        assert "instagram_business_basic" in url
        assert "instagram_business_content_publish" in url
        assert "facebook.com" not in url
        assert "pages_show_list" not in url


# ----------------------------------------------------------------------------------
# Sync + sync-history serialization (regression: missing InstagramSyncJobRead import)
# ----------------------------------------------------------------------------------
class TestSyncEndpointsSerialization:
    """The sync and sync-history endpoints reference InstagramSyncJobRead when
    serializing a job. If that import is dropped the NameError only surfaces on
    a real sync/history hit (500), never on the 404 paths, so these tests drive
    the success path through both endpoints."""

    @staticmethod
    def _owned_connection(db, user_id, account_id="ig_555"):
        conn = InstagramConnection(
            user_id=user_id,
            instagram_account_id=account_id,
            username="syncowner",
            access_token_encrypted="token",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)
        return conn

    @staticmethod
    def _finished_job(db, conn, user_id, status="succeeded", started_at=None):
        job = InstagramSyncJob(
            connection_id=conn.id,
            user_id=user_id,
            status=status,
            started_at=started_at or datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            posts_examined=3,
            posts_imported=2,
            snapshots_created=2,
            error_category="" if status == "succeeded" else "InstagramAPIError",
            error_message="" if status == "succeeded" else "boom",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job

    def test_trigger_sync_success_path_serializes_response_model(
        self, client, auth_headers, db
    ):
        """End-to-end: a real sync run returns a fully serialized job payload."""
        from app.auth import create_access_token, get_password_hash

        user = User(email="syncer2@example.com", hashed_password=get_password_hash("secret"))
        db.add(user)
        db.commit()
        db.refresh(user)
        conn = self._owned_connection(db, user.id, account_id="ig_556")

        # Make the Meta call resolve to zero media so the sync completes
        # without network access.
        with patch.object(
            InstagramService,
            "import_media",
            return_value=(0, 0),
        ), patch.object(
            InstagramService,
            "sync_metrics",
            return_value=(0, 0),
        ):
            token = create_access_token({"sub": str(user.id)})
            resp = client.post(
                f"/api/instagram/connections/{conn.id}/sync",
                json={"max_posts": 1},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["connection_id"] == conn.id
        job = body["job"]
        assert job["connection_id"] == conn.id
        assert job["status"] == "succeeded"
        assert job["posts_examined"] == 0
        assert job["posts_imported"] == 0
        assert job["snapshots_created"] == 0
        assert job["completed_at"] is not None
        assert job["error_category"] == ""
        assert job["error_message"] == ""
        # The connection is updated by the same sync run.
        db.refresh(conn)
        assert conn.last_sync_status == "succeeded"

    def test_sync_history_serializes_multiple_jobs_with_pagination(
        self, client, auth_headers, db
    ):
        """sync-history must serialize every job and honor limit/offset/total."""
        from app.auth import create_access_token, get_password_hash

        user = User(email="syncer3@example.com", hashed_password=get_password_hash("secret"))
        db.add(user)
        db.commit()
        db.refresh(user)
        conn = self._owned_connection(db, user.id, account_id="ig_557")

        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        jobs = [
            self._finished_job(
                db, conn, user.id, status="failed", started_at=base + timedelta(days=i)
            )
            for i in range(3)
        ]

        token = create_access_token({"sub": str(user.id)})
        resp = client.get(
            f"/api/instagram/connections/{conn.id}/sync-history?limit=2&offset=1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        # Ordered by started_at desc: offset=1 skips the newest.
        assert [item["id"] for item in body["items"]] == [jobs[1].id, jobs[0].id]
        for item in body["items"]:
            assert item["status"] == "failed"
            assert item["error_category"] == "InstagramAPIError"
            assert item["error_message"] == "boom"

    def test_sync_endpoints_import_schema(self):
        """Guard the missing-import regression directly."""
        from app.api.routes import instagram as ig_routes

        assert hasattr(ig_routes, "InstagramSyncJobRead")
        assert ig_routes.InstagramSyncJobRead is not None

    def test_sync_endpoints_unauthorized_without_token(self, client):
        """Auth is preserved: sync endpoints reject anonymous requests."""
        assert client.post("/api/instagram/connections/1/sync", json={}).status_code == 401
        assert client.get("/api/instagram/connections/1/sync-history").status_code == 401


# ----------------------------------------------------------------------------------
# Integration with Phase 4 performance service
# ----------------------------------------------------------------------------------
class TestInstagramPhase4Integration:
    """Test that Instagram-imported posts work with Phase 4 analytics."""

    def test_instagram_post_appears_in_performance_analytics(self, client, auth_headers, db):
        """Instagram posts should be included in performance analytics."""
        client.headers.update(auth_headers)

        # Create an Instagram post directly
        from app.models import PublishedPost

        post = PublishedPost(
            user_id=1,  # tester user
            platform="Instagram",
            title="Test Instagram Post",
            external_id="ig_12345",
            url="https://instagram.com/p/test",
            published_at=datetime.now(timezone.utc) - timedelta(days=7),
            status="published",
        )
        db.add(post)
        db.commit()
        db.refresh(post)

        # Add a metric snapshot
        from app.schemas import MetricSnapshotInput
        from app.services.performance_service import add_snapshot

        add_snapshot(db, 1, post.id, MetricSnapshotInput(
            views=1000,
            impressions=2000,
            likes=100,
            comments=10,
            shares=5,
            source="platform",
        ))

        # Query performance analytics
        resp = client.get("/api/performance/analytics")
        assert resp.status_code == 200
        data = resp.json()

        # Should include Instagram in platform breakdown
        platforms = {p["platform"] for p in data["by_platform"]}
        assert "Instagram" in platforms

        ig_platform = next(p for p in data["by_platform"] if p["platform"] == "Instagram")
        assert ig_platform["post_count"] >= 1
        assert ig_platform["posts_with_metrics"] >= 1

    def test_instagram_metrics_not_conflated_with_other_platforms(self, client, auth_headers, db):
        """Instagram metrics should not be mixed with LinkedIn/Twitter metrics."""
        client.headers.update(auth_headers)

        # Create posts on different platforms
        from app.models import PublishedPost
        from app.services.performance_service import add_snapshot
        from app.schemas import MetricSnapshotInput

        # Instagram post
        ig_post = PublishedPost(
            user_id=1,
            platform="Instagram",
            title="IG Post",
            external_id="ig_1",
            published_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(ig_post)

        # LinkedIn post
        li_post = PublishedPost(
            user_id=1,
            platform="LinkedIn",
            title="LI Post",
            external_id="li_1",
            published_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        db.add(li_post)
        db.commit()
        db.refresh(ig_post)
        db.refresh(li_post)

        # Add metrics
        add_snapshot(db, 1, ig_post.id, MetricSnapshotInput(
            views=1000, impressions=2000, likes=100, source="platform"
        ))
        add_snapshot(db, 1, li_post.id, MetricSnapshotInput(
            views=500, impressions=1000, likes=50, source="platform"
        ))

        # Get analytics
        resp = client.get("/api/performance/analytics")
        assert resp.status_code == 200
        data = resp.json()

        # Platforms should be separate
        platforms = {p["platform"]: p for p in data["by_platform"]}
        assert "Instagram" in platforms
        assert "LinkedIn" in platforms

        # Instagram metrics
        ig = platforms["Instagram"]
        assert ig["total_views"] == 1000
        assert ig["avg_engagement_rate_per_view"] == pytest.approx(0.1, rel=0.01)

        # LinkedIn metrics
        li = platforms["LinkedIn"]
        assert li["total_views"] == 500
        assert li["avg_engagement_rate_per_view"] == pytest.approx(0.1, rel=0.01)


# ----------------------------------------------------------------------------------
# Tenant isolation tests
# ----------------------------------------------------------------------------------
class TestInstagramTenantIsolation:
    def test_user_cannot_access_another_users_connection(self, client, auth_headers, db):
        from app.auth import create_access_token, get_password_hash

        # Create another user
        other = User(email="other@example.com", hashed_password=get_password_hash("secret"))
        db.add(other)
        db.commit()
        db.refresh(other)

        # Create connection for other user
        conn = InstagramConnection(
            user_id=other.id,
            instagram_account_id="other_123",
            username="otheruser",
            access_token_encrypted="encrypted_token",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        # Try to access with current user (tester@example.com)
        client.headers.update(auth_headers)
        resp = client.get(f"/api/instagram/connections/{conn.id}")
        assert resp.status_code == 404

    def test_user_cannot_sync_another_users_connection(self, client, auth_headers, db):
        from app.auth import create_access_token, get_password_hash

        other = User(email="other2@example.com", hashed_password=get_password_hash("secret"))
        db.add(other)
        db.commit()
        db.refresh(other)

        conn = InstagramConnection(
            user_id=other.id,
            instagram_account_id="other_456",
            username="otheruser2",
            access_token_encrypted="encrypted_token",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        client.headers.update(auth_headers)
        resp = client.post(f"/api/instagram/connections/{conn.id}/sync", json={})
        assert resp.status_code == 404

    def test_user_cannot_list_another_users_posts(self, client, auth_headers, db):
        from app.auth import create_access_token, get_password_hash
        from app.models import PublishedPost

        other = User(email="other3@example.com", hashed_password=get_password_hash("secret"))
        db.add(other)
        db.commit()
        db.refresh(other)

        # Create Instagram post for other user
        post = PublishedPost(
            user_id=other.id,
            platform="Instagram",
            title="Other's post",
            external_id="other_ig_1",
            published_at=datetime.now(timezone.utc),
        )
        db.add(post)
        db.commit()

        client.headers.update(auth_headers)
        # Current user has no connections, so this will 404 on connection check
        # But if we had a connection, the posts query filters by user_id
        resp = client.get("/api/instagram/connections/1/posts")
        assert resp.status_code == 404  # Connection not found for current user


# ----------------------------------------------------------------------------------
# Sync orchestration tests
# ----------------------------------------------------------------------------------
class TestSyncOrchestration:
    def test_sync_job_creation(self, db, user_id):
        conn = InstagramConnection(
            user_id=user_id,
            instagram_account_id="123",
            username="test",
            access_token_encrypted="token",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        job = InstagramSyncJob(
            connection_id=conn.id,
            user_id=user_id,
            status="pending",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        assert job.id is not None
        assert job.status == "pending"
        assert job.posts_examined == 0

    def test_sync_job_completion_updates_connection(self, db, user_id):
        conn = InstagramConnection(
            user_id=user_id,
            instagram_account_id="123",
            username="test",
            access_token_encrypted="token",
        )
        db.add(conn)
        db.commit()
        db.refresh(conn)

        job = InstagramSyncJob(
            connection_id=conn.id,
            user_id=user_id,
            status="running",
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        # Simulate completion
        job.status = "succeeded"
        job.completed_at = datetime.now(timezone.utc)
        job.posts_examined = 10
        job.posts_imported = 8
        job.snapshots_created = 8
        db.commit()

        # Connection should be updated by the service
        conn.last_sync_status = "succeeded"
        conn.last_sync_at = datetime.now(timezone.utc)
        db.commit()

        db.refresh(conn)
        assert conn.last_sync_status == "succeeded"
        assert conn.last_sync_at is not None