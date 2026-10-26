"""LLM service abstraction.

Provider-specific logic lives *only* in this file. The rest of the application
asks for validated JSON against a Pydantic model and never learns which
provider answered.

Flow:  prompt -> provider -> JSON -> Pydantic validation
                                     |
                        invalid -----+-----> one corrective retry
                                     |
                          still bad --+-----> deterministic domain fallback
"""

from __future__ import annotations

import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, NoReturn, Sequence, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from ..config import get_settings

logger = logging.getLogger("contentmind.llm")

T = TypeVar("T", bound=BaseModel)

_FENCE_RE = re.compile(r"```(?:json|JSON)?\s*(.*?)```", re.DOTALL)

_IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


class ProviderError(RuntimeError):
    """A provider failure with a safe, machine-readable category.

    ``kind`` is one of ``configuration``, ``auth``, ``rate_limit``,
    ``timeout``, ``unavailable``, ``network``, ``invalid_request``,
    ``invalid_response`` or ``unknown``. Messages are safe to log and to show
    to developers; they never include credentials, request payloads or raw
    provider responses.
    """

    def __init__(
        self,
        message: str,
        kind: str = "unknown",
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.status_code = status_code


def classify_provider_error(exc: BaseException) -> tuple[str, bool]:
    """Return ``(kind, retryable)`` for an arbitrary provider/client error."""
    if isinstance(exc, ProviderError):
        return exc.kind, exc.retryable
    if isinstance(exc, (TimeoutError, httpx.TimeoutException)):
        return "timeout", True
    if isinstance(exc, httpx.HTTPError):
        return "network", True
    return "unknown", False


def image_mime_type(path: Path) -> str:
    """Best-effort MIME type for a local image, based on suffix and magic bytes.

    Providers reject mismatched MIME/bytes pairs, so suffix alone is not
    enough: a ``.jpg`` that actually contains a PNG used to be sent as JPEG.
    """
    try:
        with path.open("rb") as handle:
            header = handle.read(16)
    except OSError:
        header = b""
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if header.startswith(b"BM"):
        return "image/bmp"
    return _IMAGE_MIME_BY_SUFFIX.get(path.suffix.lower(), "image/jpeg")


def extract_json(text: str) -> str:
    """Pull a JSON object/array out of a possibly chatty model response."""
    if not text:
        raise ValueError("empty response")
    candidate = text.strip()

    fence = _FENCE_RE.search(candidate)
    if fence:
        candidate = fence.group(1).strip()

    try:
        json.loads(candidate)
        return candidate
    except ValueError:
        pass

    for opener, closer in (("{", "}"), ("[", "]")):
        start = candidate.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escaped = False
        for idx in range(start, len(candidate)):
            ch = candidate[idx]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return candidate[start : idx + 1]
    raise ValueError("no JSON object found in response")


# ----------------------------------------------------------------------------------
# Providers
# ----------------------------------------------------------------------------------
class LLMProvider(ABC):
    name: str = "unknown"

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str: ...

    @abstractmethod
    def complete_vision(
        self,
        system: str,
        user: str,
        images: Sequence[Path],
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        """Multimodal completion with local image files (base64 data URLs)."""


class OpenAICompatibleProvider(LLMProvider):
    """Works with OpenAI, Groq, OpenRouter, Together, DeepInfra, Ollama, vLLM."""

    name = "openai-compatible"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.llm_api_key
        self.base_url = settings.llm_base_url.rstrip("/")
        self.model = settings.llm_model
        self.vision_model = getattr(settings, "vision_model", "") or settings.llm_model
        self.timeout = settings.llm_timeout
        self._client = httpx.Client(timeout=settings.llm_timeout)

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        # OpenAI-compatible APIs take the schema from the prompt text, so
        # ``response_schema`` is accepted for interface parity and unused here.
        settings = get_settings()
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": settings.llm_temperature if temperature is None else temperature,
        }
        return self._post_chat(payload)

    def complete_vision(
        self,
        system: str,
        user: str,
        images: Sequence[Path],
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        # ``response_schema`` is unused here for the same reason as in ``complete``.
        settings = get_settings()
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for image in images:
            if not image.is_file():
                raise ProviderError(
                    "An image extracted for analysis is missing.", "invalid_request"
                )
            data = base64.b64encode(image.read_bytes()).decode("ascii")
            mime = image_mime_type(image)
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        payload: dict[str, Any] = {
            "model": self.vision_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "temperature": settings.llm_temperature if temperature is None else temperature,
        }
        return self._post_chat(payload)

    def _post_chat(self, payload: dict[str, Any]) -> str:
        try:
            response = self._client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise ProviderError("LLM request timed out.", "timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError("LLM provider is unreachable.", "unavailable", retryable=True) from exc
        if response.status_code in (401, 403):
            raise ProviderError(
                f"LLM rejected the API key ({response.status_code}). Check LLM_API_KEY.",
                "auth",
                status_code=response.status_code,
            )
        if response.status_code == 429:
            raise ProviderError(
                "LLM rate limit reached (429).", "rate_limit", retryable=True, status_code=429
            )
        if response.status_code >= 500:
            raise ProviderError(
                f"LLM provider is temporarily unavailable ({response.status_code}).",
                "unavailable",
                retryable=True,
                status_code=response.status_code,
            )
        if response.status_code == 404:
            raise ProviderError(
                "The configured LLM model or endpoint was not found. Check VISION_MODEL, "
                "LLM_MODEL, and LLM_BASE_URL.",
                "invalid_request",
                status_code=404,
            )
        if response.status_code >= 400:
            raise ProviderError(
                f"LLM rejected the request ({response.status_code}). Check the model and "
                "request format.",
                "invalid_request",
                status_code=response.status_code,
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("LLM returned a non-JSON response.", "invalid_response") from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("Unexpected LLM response shape.", "invalid_response") from exc

    def close(self) -> None:
        self._client.close()


class GeminiProvider(LLMProvider):
    """Google Gemini through the official ``google-genai`` SDK.

    The SDK is imported lazily, so a missing package never breaks application
    startup: ``is_available()`` simply reports False and the caller keeps its
    deterministic fallback. Every SDK exception is translated into the same
    ``RuntimeError`` vocabulary the OpenAI-compatible provider uses, so
    ``LLMService``'s existing fallback handling applies unchanged.

    Retries are deliberately *not* stacked: the SDK client is configured with
    ``attempts=1`` (no SDK-side retries) and ``LLMService`` owns the single
    bounded corrective retry. The SDK's default is ~4 retries, which would
    otherwise multiply every call.
    """

    name = "gemini"

    def __init__(self) -> None:
        settings = get_settings()
        self.api_key = settings.gemini_api_key
        self.model = settings.llm_model
        self.vision_model = getattr(settings, "vision_model", "") or settings.llm_model
        self.timeout = settings.llm_timeout
        self.temperature = settings.llm_temperature
        self.max_output_tokens = settings.llm_max_output_tokens
        self._genai = None
        self._types = None
        self._client = None
        self._sdk_import_error: str | None = None

    # -- lazy SDK loading -----------------------------------------------------
    def _ensure_sdk(self) -> bool:
        if self._genai is not None and self._types is not None:
            return True
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            self._sdk_import_error = f"google-genai not installed ({type(exc).__name__})"
            return False
        self._genai = genai
        self._types = types
        return True

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self._ensure_sdk():
            raise RuntimeError(self._sdk_import_error or "google-genai unavailable")
        http_options = self._types.HttpOptions(
            timeout=int(self.timeout * 1000),
            retry_options=self._types.HttpRetryOptions(
                initial_delay=1.0,
                # ``attempts`` includes the original request; 1 == no retries.
                attempts=1,
                http_status_codes=[408, 429, 500, 502, 503, 504],
            ),
        )
        self._client = self._genai.Client(api_key=self.api_key, http_options=http_options)
        return self._client

    def is_available(self) -> bool:
        return bool(self.api_key) and self._ensure_sdk()

    def _config(self, system: str, temperature: float | None, response_schema: Any):
        """Build a GenerateContentConfig; request JSON output when a schema is given."""
        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": self.temperature if temperature is None else temperature,
            "max_output_tokens": self.max_output_tokens,
        }
        if response_schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = response_schema
        return self._types.GenerateContentConfig(**kwargs)

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        client = self._ensure_client()
        try:
            response = client.models.generate_content(
                model=self.model,
                contents=user,
                config=self._config(system, temperature, response_schema),
            )
        except Exception as exc:
            self._raise_mapped(exc)
        return self._response_text(response)

    def complete_vision(
        self,
        system: str,
        user: str,
        images: Sequence[Path],
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        client = self._ensure_client()
        parts = [self._types.Part.from_text(text=user)]
        for image in images:
            if not image.is_file():
                raise ProviderError(
                    "An image extracted for analysis is missing.", "invalid_request"
                )
            parts.append(
                self._types.Part.from_bytes(
                    data=image.read_bytes(), mime_type=image_mime_type(image)
                )
            )
        try:
            response = client.models.generate_content(
                model=self.vision_model,
                contents=parts,
                config=self._config(system, temperature, response_schema),
            )
        except Exception as exc:
            self._raise_mapped(exc)
        return self._response_text(response)

    @staticmethod
    def _response_text(response: Any) -> str:
        """Extract text, turning an empty/truncated response into a fallback error."""
        try:
            text = response.text
        except Exception as exc:
            raise ProviderError(
                f"Gemini returned no text content ({type(exc).__name__}).",
                "invalid_response",
            ) from exc
        if not text or not text.strip():
            raise ProviderError("Gemini returned an empty response.", "invalid_response")
        return text

    @staticmethod
    def _raise_mapped(exc: Exception) -> NoReturn:
        """Translate SDK errors into the shared ProviderError vocabulary.

        Only the error class, HTTP status and message-free detail are used;
        request payloads, headers and raw response bodies are never surfaced,
        because they could contain prompt content or credentials."""
        if isinstance(exc, ProviderError):
            raise exc
        code = getattr(exc, "code", None)
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        if code in (401, 403):
            raise ProviderError(
                f"Gemini rejected the API key ({code}). Check GEMINI_API_KEY.",
                "auth",
                status_code=code,
            ) from exc
        if code == 429:
            raise ProviderError(
                "LLM rate limit reached (429).", "rate_limit", retryable=True, status_code=code
            ) from exc
        if code is not None and code >= 500:
            raise ProviderError(
                f"Gemini is temporarily unavailable (server error {code}).",
                "unavailable",
                retryable=True,
                status_code=code,
            ) from exc
        if code == 404:
            raise ProviderError(
                "The configured Gemini model was not found. Check VISION_MODEL and LLM_MODEL.",
                "invalid_request",
                status_code=404,
            ) from exc
        if code is not None:
            raise ProviderError(
                f"Gemini rejected the request ({code}). Check the model and request format.",
                "invalid_request",
                status_code=code,
            ) from exc
        if isinstance(exc, (TimeoutError, httpx.TimeoutException)) or "timeout" in type(exc).__name__.lower():
            raise ProviderError("Gemini request timed out.", "timeout", retryable=True) from exc
        if isinstance(exc, httpx.HTTPError):
            raise ProviderError(
                "Gemini provider could not be reached.", "network", retryable=True
            ) from exc
        raise ProviderError(
            f"Gemini request failed ({type(exc).__name__}).", "unknown"
        ) from exc


class DisabledProvider(LLMProvider):
    name = "disabled"

    def is_available(self) -> bool:
        return False

    def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        raise RuntimeError(
            "No LLM provider configured. Set GEMINI_API_KEY (LLM_PROVIDER=gemini) or "
            "LLM_API_KEY to enable generation."
        )

    def complete_vision(
        self,
        system: str,
        user: str,
        images: Sequence[Path],
        *,
        temperature: float | None = None,
        response_schema: Any = None,
    ) -> str:
        raise RuntimeError(
            "No vision-capable LLM provider configured. Set GEMINI_API_KEY "
            "(LLM_PROVIDER=gemini) or LLM_API_KEY."
        )


# ----------------------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------------------
class LLMService:
    def __init__(self) -> None:
        self._provider: LLMProvider | None = None
        self._last_error: str | None = None
        self._last_error_kind: str | None = None

    @property
    def provider(self) -> LLMProvider:
        if self._provider is None:
            settings = get_settings()
            if settings.llm_provider in {"heuristic", "none", "disabled"}:
                self._provider = DisabledProvider()
            elif settings.llm_provider == "gemini":
                # A missing GEMINI_API_KEY disables the provider rather than
                # raising, so the deterministic engine keeps working.
                self._provider = GeminiProvider() if settings.gemini_api_key else DisabledProvider()
            elif not settings.llm_api_key:
                self._provider = DisabledProvider()
            else:
                self._provider = OpenAICompatibleProvider()
        return self._provider

    @property
    def available(self) -> bool:
        try:
            return self.provider.is_available()
        except Exception:  # noqa: BLE001
            return False

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def last_error_kind(self) -> str | None:
        return self._last_error_kind

    def describe(self) -> dict[str, Any]:
        settings = get_settings()
        vision_model = getattr(settings, "vision_model", "") or settings.llm_model
        return {
            "available": self.available,
            "provider": self.provider.name if self.available else "heuristic-fallback",
            "model": settings.llm_model if self.available else "deterministic-strategy-engine",
            "vision_available": self.available,
            "vision_model": vision_model if self.available else None,
            "api_key_present": settings.llm_provider_key_present,
            "gemini_key_present": bool(settings.gemini_api_key),
            "last_error": self._last_error,
            "last_error_kind": self._last_error_kind,
        }

    # -- JSON generation --------------------------------------------------------
    def generate_json(
        self,
        schema: Type[T],
        *,
        system: str,
        user: str,
        fallback: Callable[[], dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> tuple[T | None, str]:
        """Return ``(validated_model_or_None, note)``.

        ``note`` describes what happened: ``"llm"``, ``"llm-retry"``,
        ``"fallback-unavailable"`` or ``"fallback-invalid"``. Callers use it to
        attach graceful-degradation messaging to the response.
        """
        json_instructions = (
            f"{system}\n\n"
            "Respond with a single valid JSON value and nothing else. "
            "No markdown fences, no commentary, no trailing text.\n"
            f"It must validate against this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        )

        if not self.available:
            self._last_error = "No LLM provider configured; using the deterministic strategy engine."
            self._last_error_kind = "configuration"
            return self._finalise(schema, fallback, "fallback-unavailable")

        last_error = ""
        last_kind = "unknown"
        for attempt in range(get_settings().llm_max_retries + 1):
            prompt = user if attempt == 0 else (
                f"{user}\n\n---\nYour previous answer was rejected: {last_error}\n"
                "Return ONLY the corrected JSON object that satisfies the schema exactly."
            )
            try:
                raw = self.provider.complete(
                    json_instructions, prompt, temperature=temperature, response_schema=schema
                )
                payload = json.loads(extract_json(raw))
                validated = schema.model_validate(payload)
                self._last_error = None
                self._last_error_kind = None
                return validated, ("llm" if attempt == 0 else "llm-retry")
            except ValidationError as exc:
                last_error = self._describe_validation_error(exc)
                last_kind = "invalid_response"
            except ProviderError as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
                last_kind = exc.kind
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
                last_kind = classify_provider_error(exc)[0]
            except (ValueError, TypeError, KeyError) as exc:
                last_error = f"Malformed LLM output ({type(exc).__name__}: {exc})"[:400]
                last_kind = "invalid_response"

            logger.warning("LLM attempt %s failed: %s", attempt + 1, last_error)

        self._last_error = last_error
        self._last_error_kind = last_kind
        return self._finalise(schema, fallback, "fallback-invalid")

    @staticmethod
    def _describe_validation_error(exc: ValidationError) -> str:
        parts = []
        for err in exc.errors()[:4]:
            loc = ".".join(str(p) for p in err["loc"]) or "(root)"
            parts.append(f"{loc}: {err['msg']}")
        return "; ".join(parts)

    @staticmethod
    def _finalise(
        schema: Type[T],
        fallback: Callable[[], dict[str, Any]] | None,
        note: str,
    ) -> tuple[T | None, str]:
        if fallback is None:
            return None, note
        try:
            return schema.model_validate(fallback()), f"{note}:fallback"
        except Exception as exc:  # noqa: BLE001
            logger.error("Deterministic fallback produced invalid payload: %s", exc)
            return None, f"{note}:fallback-invalid"

    def complete_text(self, system: str, user: str, *, temperature: float | None = None) -> str | None:
        """Free-form text. Returns ``None`` when no provider is available."""
        if not self.available:
            return None
        try:
            return self.provider.complete(system, user, temperature=temperature)
        except Exception as exc:  # noqa: BLE001
            self._last_error = f"{type(exc).__name__}: {exc}"[:400]
            self._last_error_kind = classify_provider_error(exc)[0]
            logger.warning("Text completion failed: %s", exc)
            return None

    # -- Vision (image) JSON generation ----------------------------------------
    def generate_json_with_images(
        self,
        schema: Type[T],
        *,
        system: str,
        user: str,
        images: Sequence[Path],
        fallback: Callable[[], dict[str, Any]] | None = None,
        temperature: float | None = None,
    ) -> tuple[T | None, str]:
        """Multimodal variant of :meth:`generate_json`.

        Same retry/fallback contract, but the prompt includes local image files
        sent as base64 data URLs. ``note`` is ``"llm-vision"`` on success.
        """
        json_instructions = (
            f"{system}\n\n"
            "Respond with a single valid JSON value and nothing else. "
            "No markdown fences, no commentary, no trailing text.\n"
            f"It must validate against this JSON Schema:\n{json.dumps(schema.model_json_schema())}"
        )

        if not self.available:
            self._last_error = "No vision-capable LLM provider configured."
            self._last_error_kind = "configuration"
            return self._finalise(schema, fallback, "fallback-unavailable")

        last_error = ""
        last_kind = "unknown"
        for attempt in range(get_settings().llm_max_retries + 1):
            prompt = user if attempt == 0 else (
                f"{user}\n\n---\nYour previous answer was rejected: {last_error}\n"
                "Return ONLY the corrected JSON object that satisfies the schema exactly."
            )
            try:
                raw = self.provider.complete_vision(
                    json_instructions,
                    prompt,
                    images,
                    temperature=temperature,
                    response_schema=schema,
                )
                payload = json.loads(extract_json(raw))
                validated = schema.model_validate(payload)
                self._last_error = None
                self._last_error_kind = None
                return validated, ("llm-vision" if attempt == 0 else "llm-vision-retry")
            except ValidationError as exc:
                last_error = self._describe_validation_error(exc)
                last_kind = "invalid_response"
            except ProviderError as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
                last_kind = exc.kind
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
                last_kind = classify_provider_error(exc)[0]
            except (ValueError, TypeError, KeyError) as exc:
                last_error = f"Malformed LLM output ({type(exc).__name__}: {exc})"[:400]
                last_kind = "invalid_response"

            logger.warning("Vision LLM attempt %s failed: %s", attempt + 1, last_error)

        self._last_error = last_error
        self._last_error_kind = last_kind
        return self._finalise(schema, fallback, "fallback-invalid")


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service
