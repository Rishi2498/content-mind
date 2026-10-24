"""Central configuration for ContentMind.

All secrets are read from the environment (loaded from ``.env``).
Nothing in this module ever returns a secret value to the API layer.
"""

from __future__ import annotations

import os
import urllib.parse
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

load_dotenv(PROJECT_ROOT / ".env", override=False)
load_dotenv(BACKEND_DIR / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return default if value is None else value.strip()


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


# Built-in development key. It signs JWTs (auth) and Instagram OAuth state, so
# anyone who has read the source could forge both. It must never be used outside
# local development.
DEFAULT_SECRET_KEY = "dev-secret-key-12345"


@dataclass(frozen=True)
class Settings:
    app_name: str = "ContentMind"
    tagline: str = "Your content strategy remembers."
    environment: str = field(default_factory=lambda: _env("ENVIRONMENT", "development"))
    api_prefix: str = "/api"
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        )
    )

    database_url: str = field(
        default_factory=lambda: _env("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'contentmind.db').as_posix()}")
    )
    sql_echo: bool = field(default_factory=lambda: _env_bool("SQL_ECHO", False))

    # ---- Hindsight (Vectorize) -------------------------------------------------
    hindsight_api_url: str = field(default_factory=lambda: _env("HINDSIGHT_API_URL", ""))
    hindsight_api_key: str = field(default_factory=lambda: _env("HINDSIGHT_API_KEY", ""))
    hindsight_bank: str = field(default_factory=lambda: _env("HINDSIGHT_BANK", "contentmind"))
    hindsight_timeout: float = field(default_factory=lambda: _env_float("HINDSIGHT_TIMEOUT", 30.0))
    hindsight_retain_batch_size: int = field(
        default_factory=lambda: _env_int("HINDSIGHT_RETAIN_BATCH_SIZE", 10)
    )
    # When Hindsight is unreachable the app keeps working against a local
    # in-process memory store. This is surfaced in the UI as a degraded state.
    hindsight_allow_local_fallback: bool = field(
        default_factory=lambda: _env_bool("HINDSIGHT_ALLOW_LOCAL_FALLBACK", True)
    )

    # ---- LLM -------------------------------------------------------------------
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openai"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY", ""))
    # Gemini uses its own key; keep it separate so the OpenAI-compatible path is
    # never accidentally handed a Google credential (and vice versa).
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY", ""))
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "https://api.openai.com/v1")
    )
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "gpt-4o-mini"))
    llm_timeout: float = field(default_factory=lambda: _env_float("LLM_TIMEOUT", 60.0))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.3))
    llm_max_retries: int = field(default_factory=lambda: _env_int("LLM_MAX_RETRIES", 1))
    llm_max_output_tokens: int = field(
        default_factory=lambda: _env_int("LLM_MAX_OUTPUT_TOKENS", 2048)
    )

    # ---- Strategy defaults -----------------------------------------------------
    default_plan_days: int = field(default_factory=lambda: _env_int("DEFAULT_PLAN_DAYS", 7))
    max_plan_items: int = field(default_factory=lambda: _env_int("MAX_PLAN_ITEMS", 21))
    default_brand_name: str = field(default_factory=lambda: _env("DEFAULT_BRAND_NAME", "Our Company"))
    secret_key: str = field(default_factory=lambda: _env("SECRET_KEY", DEFAULT_SECRET_KEY))

    # ---- Instagram (Meta) integration (Phase 6) ---------------------------------
    instagram_app_id: str = field(default_factory=lambda: _env("INSTAGRAM_APP_ID", ""))
    instagram_app_secret: str = field(default_factory=lambda: _env("INSTAGRAM_APP_SECRET", ""))
    instagram_redirect_uri: str = field(default_factory=lambda: _env("INSTAGRAM_REDIRECT_URI", ""))
    instagram_api_version: str = field(default_factory=lambda: _env("INSTAGRAM_API_VERSION", "v22.0"))
    instagram_frontend_base_url: str = field(default_factory=lambda: _env("INSTAGRAM_FRONTEND_BASE_URL", "http://localhost:5173"))
    instagram_encryption_key: str = field(default_factory=lambda: _env("INSTAGRAM_ENCRYPTION_KEY", ""))
    instagram_sync_cooldown_seconds: int = field(default_factory=lambda: _env_int("INSTAGRAM_SYNC_COOLDOWN_SECONDS", 300))
    instagram_max_posts_per_sync: int = field(default_factory=lambda: _env_int("INSTAGRAM_MAX_POSTS_PER_SYNC", 50))

    # ---- Demo mode --------------------------------------------------------------
    demo_mode: bool = field(default_factory=lambda: _env_bool("CONTENTMIND_DEMO_MODE", False))

    # ---- Media processing (Phase 2) --------------------------------------------
    ffmpeg_path: str = field(default_factory=lambda: _env("FFMPEG_PATH", "ffmpeg"))
    ffprobe_path: str = field(default_factory=lambda: _env("FFPROBE_PATH", "ffprobe"))
    media_uploads_dir: str = field(
        default_factory=lambda: _env("MEDIA_UPLOADS_DIR", str(BACKEND_DIR / "uploads"))
    )
    media_max_video_mb: int = field(default_factory=lambda: _env_int("MEDIA_MAX_VIDEO_MB", 500))
    media_max_image_mb: int = field(default_factory=lambda: _env_int("MEDIA_MAX_IMAGE_MB", 25))
    media_ffmpeg_timeout: int = field(default_factory=lambda: _env_int("MEDIA_FFMPEG_TIMEOUT", 300))
    media_keyframe_count: int = field(default_factory=lambda: _env_int("MEDIA_KEYFRAME_COUNT", 4))
    whisper_provider: str = field(default_factory=lambda: _env("WHISPER_PROVIDER", "auto"))
    whisper_api_model: str = field(default_factory=lambda: _env("WHISPER_API_MODEL", "whisper-1"))
    whisper_local_model: str = field(default_factory=lambda: _env("WHISPER_LOCAL_MODEL", "base"))
    vision_model: str = field(default_factory=lambda: _env("VISION_MODEL", ""))


    @property
    def instagram_configured(self) -> bool:
        return bool(self.instagram_app_id and self.instagram_app_secret and self.instagram_redirect_uri)

    @property
    def instagram_redirect_uri_points_to_callback(self) -> bool:
        """True when INSTAGRAM_REDIRECT_URI targets this API's /instagram/callback route.

        The OAuth code can only be exchanged on the backend callback; a URI that
        points at the frontend (e.g. http://localhost:5173) breaks the flow even
        when the Meta app itself is configured correctly.
        """
        try:
            path = urllib.parse.urlparse(self.instagram_redirect_uri).path.rstrip("/")
        except ValueError:
            return False
        return path.endswith(f"{self.api_prefix}/instagram/callback")

    @property
    def instagram_redirect_uri_is_https(self) -> bool:
        """True when the redirect URI uses https (required by Instagram Login)."""
        return urllib.parse.urlparse(self.instagram_redirect_uri).scheme == "https"

    def instagram_config_warnings(self) -> list[str]:
        """Secret-free hints for common Instagram Login misconfigurations.

        Covers what is detectable from configuration alone. The redirect URI
        still has to be registered against the Instagram App ID in the Meta
        dashboard, which code cannot verify.
        """
        if not self.instagram_configured:
            return []
        warnings: list[str] = []
        if not self.instagram_redirect_uri_is_https:
            warnings.append(
                "INSTAGRAM_REDIRECT_URI is not https; Instagram Login only accepts "
                "https redirect URIs."
            )
        if not self.instagram_redirect_uri_points_to_callback:
            warnings.append(
                f"INSTAGRAM_REDIRECT_URI must target {self.api_prefix}/instagram/callback."
            )
        if self.instagram_app_id and not self.instagram_app_id.isdigit():
            warnings.append(
                "INSTAGRAM_APP_ID is not numeric; Instagram Login expects the numeric "
                "Instagram App ID (not the Meta App ID)."
            )
        return warnings

    @property
    def secret_key_is_default(self) -> bool:
        """True when SECRET_KEY is empty or still the shipped development default.

        Both cases are insecure: the key signs JWTs and Instagram OAuth state, so
        a known/empty value lets anyone forge either. Startup warns loudly.
        """
        return not self.secret_key or self.secret_key == DEFAULT_SECRET_KEY

    @property
    def hindsight_configured(self) -> bool:
        return bool(self.hindsight_api_url)

    @property
    def llm_provider_key_present(self) -> bool:
        """True when the active provider has the credential it actually uses.

        Gemini authenticates with ``GEMINI_API_KEY``; the OpenAI-compatible
        providers use ``LLM_API_KEY``. Never conflate the two.
        """
        if self.llm_provider == "gemini":
            return bool(self.gemini_api_key)
        return bool(self.llm_api_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def llm_configured(self) -> bool:
        return (
            self.llm_provider_key_present
            and self.llm_provider not in {"heuristic", "none", "disabled"}
        )

    def safe_dict(self) -> dict:
        """Configuration snapshot safe to expose over the API (no secrets)."""
        return {
            "app_name": self.app_name,
            "tagline": self.tagline,
            "environment": self.environment,
            "database_url_scheme": self.database_url.split("://", 1)[0],
            "hindsight": {
                "configured": self.hindsight_configured,
                "bank": self.hindsight_bank,
                "api_host": self.hindsight_api_url.split("://", 1)[-1] if self.hindsight_api_url else None,
                "api_key_present": bool(self.hindsight_api_key),
                "local_fallback_enabled": self.hindsight_allow_local_fallback,
            },
            "llm": {
                "configured": self.llm_configured,
                "provider": self.llm_provider,
                "model": self.llm_model,
                # Booleans only; secret values are never exposed here.
                "api_key_present": self.llm_provider_key_present,
                "gemini_key_present": bool(self.gemini_api_key),
                "max_output_tokens": self.llm_max_output_tokens,
            },
            "media": {
                "uploads_dir_configured": bool(self.media_uploads_dir),
                "max_video_mb": self.media_max_video_mb,
                "max_image_mb": self.media_max_image_mb,
                "whisper_provider": self.whisper_provider,
            },
            "instagram": {
                "configured": self.instagram_configured,
                "api_version": self.instagram_api_version,
                # Never expose the app id/secret values themselves.
                "app_id_present": bool(self.instagram_app_id),
                "app_id_length": len(self.instagram_app_id),
                "app_id_numeric": self.instagram_app_id.isdigit(),
                "app_secret_present": bool(self.instagram_app_secret),
                "redirect_uri": self.instagram_redirect_uri,
                "redirect_uri_points_to_callback": self.instagram_redirect_uri_points_to_callback,
                "redirect_uri_is_https": self.instagram_redirect_uri_is_https,
            },
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
