"""Vision analysis of extracted keyframes.

Each keyframe is sent to the vision-capable LLM, which returns a strict
``LLMImageAnalysis`` (scene description, OCR text, visual tags). When no
vision provider is configured the service degrades gracefully: analyses are
empty and the caller marks the vision step as degraded rather than failed.
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


@dataclass
class VisionResult:
    analyses: list[LLMImageAnalysis] = field(default_factory=list)
    failed_frames: int = 0
    degraded: bool = False
    note: str = ""


def analyze_keyframe(path: Path) -> tuple[LLMImageAnalysis | None, str]:
    """Analyze one keyframe. Returns ``(analysis_or_None, note)``."""
    if not path.is_file():
        return None, "keyframe-missing"
    llm = get_llm_service()

    def _fallback() -> dict:
        return {}

    analysis, note = llm.generate_json_with_images(
        LLMImageAnalysis,
        system=_SYSTEM,
        user=_USER,
        images=[path],
        fallback=_fallback,
    )
    if analysis is None:
        return None, note
    return analysis, note


def analyze_keyframes(paths: list[Path]) -> VisionResult:
    """Analyze all keyframes; tolerate per-frame failures."""
    if not paths:
        return VisionResult(degraded=True, note="no-keyframes")
    llm = get_llm_service()
    if not llm.available:
        return VisionResult(degraded=True, note="vision-llm-unavailable")

    analyses: list[LLMImageAnalysis] = []
    failed = 0
    for path in paths:
        analysis, _note = analyze_keyframe(path)
        if analysis is not None:
            analyses.append(analysis)
        else:
            failed += 1

    degraded = not analyses or failed > 0
    return VisionResult(
        analyses=analyses,
        failed_frames=failed,
        degraded=degraded,
        note=f"{len(analyses)}/{len(paths)} frames analyzed",
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
