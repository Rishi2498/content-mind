"""Vision analysis of extracted keyframes.

Each keyframe is sent to the vision-capable LLM, which returns a strict
``LLMImageAnalysis`` (scene description, OCR text, visual tags). A failed
provider call is *never* converted into an empty "successful" analysis: the
caller receives a structured failure kind so the pipeline can report the
vision step as failed/retryable while preserving metadata and transcript work.

The provider itself is easy to mock in tests: ``get_llm_service`` is the only
dependency and ``generate_json_with_images`` is the only call.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from ..schemas import LLMImageAnalysis
from .llm_service import get_llm_service

logger = logging.getLogger("contentmind.vision")

_SYSTEM = (
    "You are a precise visual analyst for a content strategy platform. "
    "Given a video keyframe (or image), extract: (1) a concise scene "
    "description, (2) any readable on-screen text (OCR), (3) short visual "
    "tags (objects, setting, style, mood), (4) dominant colors, and (5) "
    "whether the frame is text-heavy. Be literal; do not invent text that "
    "is not visible."
)

_USER = (
    "Analyze this keyframe from an uploaded media asset. Return the JSON "
    "object matching the required schema."
)

ERROR_MESSAGES = {
    "configuration": "Visual analysis isn't available because the AI provider isn't configured.",
    "auth": "The AI provider rejected the configured credentials.",
    "rate_limit": "The AI provider is busy right now. Try again in a moment.",
    "timeout": "Visual analysis took too long to complete.",
    "unavailable": "The AI provider is temporarily unavailable.",
    "network": "The AI provider could not be reached.",
    "invalid_request": "The AI provider couldn't process this image.",
    "invalid_response": "The AI provider returned an unreadable analysis.",
    "partial": "Some frames couldn't be analyzed.",
    "unknown": "Visual analysis couldn't be completed.",
}


@dataclass
class VisionResult:
    analyses: list[LLMImageAnalysis] = field(default_factory=list)
    failed_frames: int = 0
    degraded: bool = False
    note: str = ""
    error_kind: str = ""
    user_message: str = ""
    attempted: bool = True

    @property
    def ok(self) -> bool:
        return bool(self.analyses) and not self.degraded

    @property
    def failed(self) -> bool:
        return self.attempted and not self.analyses


def _is_meaningful(analysis: LLMImageAnalysis) -> bool:
    """An all-empty object is not a successful image analysis.

    Colors alone are not enough for Content DNA: scene text, OCR text, or a
    visual tag must be present, otherwise the result would look analyzed while
    contributing no evidence to the insights.
    """
    return bool(
        (analysis.scene_description or "").strip()
        or (analysis.ocr_text or "").strip()
        or any((tag or "").strip() for tag in analysis.visual_tags)
    )


def _failure_result(
    kind: str,
    note: str,
    *,
    attempted: bool = True,
    failed_frames: int = 0,
) -> VisionResult:
    return VisionResult(
        failed_frames=failed_frames,
        degraded=True,
        note=note,
        error_kind=kind,
        user_message=ERROR_MESSAGES.get(kind, ERROR_MESSAGES["unknown"]),
        attempted=attempted,
    )


def analyze_keyframe(path: Path) -> tuple[LLMImageAnalysis | None, str, str]:
    """Analyze one keyframe. Returns ``(analysis_or_None, note, error_kind)``."""
    if not path.is_file():
        return None, "keyframe-missing", "invalid_request"
    llm = get_llm_service()

    # Deliberately no ``fallback``: an empty dict validates against this
    # all-optional schema and would look like a successful analysis.
    analysis, note = llm.generate_json_with_images(
        LLMImageAnalysis,
        system=_SYSTEM,
        user=_USER,
        images=[path],
        fallback=None,
    )
    if analysis is None:
        kind = getattr(llm, "last_error_kind", None) or "unknown"
        return None, note, kind
    if not _is_meaningful(analysis):
        return None, "empty-analysis", "invalid_response"
    return analysis, note, ""


def analyze_keyframes(paths: list[Path]) -> VisionResult:
    """Analyze all keyframes; tolerate per-frame failures without faking success."""
    if not paths:
        return VisionResult(
            degraded=True,
            note="no-keyframes",
            error_kind="invalid_request",
            user_message="No images were available to analyze.",
            attempted=False,
        )
    llm = get_llm_service()
    if not llm.available:
        return _failure_result(
            "configuration", "vision-llm-unavailable", attempted=False
        )

    analyses: list[LLMImageAnalysis] = []
    failed = 0
    last_kind = ""
    last_note = ""
    for path in paths:
        analysis, note, kind = analyze_keyframe(path)
        if analysis is not None:
            analyses.append(analysis)
        else:
            failed += 1
            last_kind = kind or "unknown"
            last_note = note

    if not analyses:
        return _failure_result(
            last_kind or "unknown", last_note or "no-analysis", failed_frames=failed
        )

    degraded = failed > 0
    return VisionResult(
        analyses=analyses,
        failed_frames=failed,
        degraded=degraded,
        note=f"{len(analyses)}/{len(paths)} frames analyzed",
        error_kind="partial" if degraded else "",
        user_message=ERROR_MESSAGES["partial"] if degraded else "",
        attempted=True,
    )


def merge_analyses(analyses: list[LLMImageAnalysis]) -> dict:
    """Combine per-frame analyses into scene/OCR/tags for ContentDNA."""
    if not analyses:
        return {"scene_description": "", "ocr_text": "", "visual_tags": [], "dominant_colors": [], "text_heavy": False}

    scenes = [a.scene_description.strip() for a in analyses if a.scene_description.strip()]
    ocr_parts = [a.ocr_text.strip() for a in analyses if a.ocr_text.strip()]
    tags: list[str] = []
    colors: list[str] = []
    for a in analyses:
        for t in a.visual_tags:
            if t not in tags:
                tags.append(t)
        for c in a.dominant_colors:
            if c not in colors:
                colors.append(c)

    return {
        "scene_description": " / ".join(dict.fromkeys(scenes)),
        "ocr_text": "\n".join(dict.fromkeys(ocr_parts)),
        "visual_tags": tags[:20],
        "dominant_colors": colors[:12],
        "text_heavy": any(a.text_heavy for a in analyses),
    }
