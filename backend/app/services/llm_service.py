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
            data = base64.b64encode(image.read_bytes()).decode("ascii")
            mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            "temperature": settings.llm_temperature if temperature is None else temperature,
        }
        return self._post_chat(payload)

    def _post_chat(self, payload: dict[str, Any]) -> str:
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        if response.status_code == 401:
            raise RuntimeError("LLM rejected the API key (401). Check LLM_API_KEY.")
        if response.status_code == 429:
            raise RuntimeError("LLM rate limit reached (429).")
        if response.status_code >= 400:
            raise RuntimeError(f"LLM request failed ({response.status_code}): {response.text[:300]}")
        data = response.json()
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected LLM response shape: {str(data)[:300]}") from exc

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
            mime = "image/png" if image.suffix.lower() == ".png" else "image/jpeg"
            parts.append(self._types.Part.from_bytes(data=image.read_bytes(), mime_type=mime))
        try:
            response = client.models.generate_content(
                model=self.model,
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
            raise RuntimeError(f"Gemini returned no text content ({type(exc).__name__}).") from exc
        if not text or not text.strip():
            raise RuntimeError("Gemini returned an empty response.")
        return text

    @staticmethod
    def _raise_mapped(exc: Exception) -> NoReturn:
        """Translate SDK errors into the shared RuntimeError vocabulary.

        Only the error class, HTTP status and message-free detail are used;
        request payloads, headers and raw response bodies are never surfaced,
        because they could contain prompt content or credentials."""
        code = getattr(exc, "code", None)
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        if code in (401, 403):
            raise RuntimeError(
                f"Gemini rejected the API key ({code}). Check GEMINI_API_KEY."
            ) from exc
        if code == 429:
            raise RuntimeError("LLM rate limit reached (429).") from exc
        if code is not None and code >= 500:
            raise RuntimeError(f"Gemini request failed (server error {code}).") from exc
        if code is not None:
            raise RuntimeError(f"Gemini request failed ({code}).") from exc
        if isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower():
            raise RuntimeError("Gemini request timed out.") from exc
        raise RuntimeError(f"Gemini request failed ({type(exc).__name__}).") from exc


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

    def describe(self) -> dict[str, Any]:
        settings = get_settings()
        return {
            "available": self.available,
            "provider": self.provider.name if self.available else "heuristic-fallback",
            "model": settings.llm_model if self.available else "deterministic-strategy-engine",
            "api_key_present": settings.llm_provider_key_present,
            "gemini_key_present": bool(settings.gemini_api_key),
            "last_error": self._last_error,
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
            return self._finalise(schema, fallback, "fallback-unavailable")

        last_error = ""
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
                return schema.model_validate(payload), ("llm" if attempt == 0 else "llm-retry")
            except ValidationError as exc:
                last_error = self._describe_validation_error(exc)
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
            except (ValueError, TypeError, KeyError) as exc:
                last_error = f"Malformed LLM output ({type(exc).__name__}: {exc})"[:400]

            logger.warning("LLM attempt %s failed: %s", attempt + 1, last_error)

        self._last_error = last_error
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
            return self._finalise(schema, fallback, "fallback-unavailable")

        last_error = ""
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
                return schema.model_validate(payload), ("llm-vision" if attempt == 0 else "llm-vision-retry")
            except ValidationError as exc:
                last_error = self._describe_validation_error(exc)
            except (RuntimeError, httpx.HTTPError) as exc:
                last_error = f"{type(exc).__name__}: {exc}"[:400]
            except (ValueError, TypeError, KeyError) as exc:
                last_error = f"Malformed LLM output ({type(exc).__name__}: {exc})"[:400]

            logger.warning("Vision LLM attempt %s failed: %s", attempt + 1, last_error)

        self._last_error = last_error
        return self._finalise(schema, fallback, "fallback-invalid")


_service: LLMService | None = None


def get_llm_service() -> LLMService:
    global _service
    if _service is None:
        _service = LLMService()
    return _service
