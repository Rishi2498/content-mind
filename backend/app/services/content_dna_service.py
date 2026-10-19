"""Combine transcript, keyframe observations and metadata into ContentDNA.

The synthesis step is deterministic at the data level: it merges whatever the
transcription and vision steps produced into a single structured record. An
optional LLM pass can suggest a title/topic from the combined signals; when
no LLM is configured we derive these from the transcript and OCR text.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from ..models import ContentDNA
from ..schemas import LLMMediaSynthesis
from .llm_service import get_llm_service
from .transcription_service import TranscriptionResult
from .vision_service import merge_analyses

logger = logging.getLogger("contentmind.dna")

_SYNTH_SYSTEM = (
    "You are a content analyst. You receive a video/audio transcript (if any) "
    "and visual observations from keyframes (scene descriptions, on-screen text, "
    "tags). Produce a concise title suggestion, a topic label, a short summary, "
    "and 3-6 key points. Base everything strictly on the provided signals."
)


@dataclass
class DNASynthesisInput:
    transcript: str = ""
    language: str = ""
    scene_description: str = ""
    ocr_text: str = ""
    visual_tags: list[str] = field(default_factory=list)
    keyframe_analyses: list[dict] = field(default_factory=list)
    keyframes: list[int] = field(default_factory=list)
    audio_path: str = ""


def _heuristic_synthesis(inp: DNASynthesisInput) -> dict:
    """Deterministic title/topic/summary when no LLM is available."""
    source = inp.transcript.strip() or inp.ocr_text.strip() or inp.scene_description.strip()
    words = source.split()
    title = " ".join(words[:12]) + ("…" if len(words) > 12 else "")
    title = title.strip() or "Untitled media asset"

    topic = "General"
    lowered = source.lower()
    for candidate in ("ai", "marketing", "product", "tutorial", "finance", "health", "education", "news"):
        if candidate in lowered or candidate in [t.lower() for t in inp.visual_tags]:
            topic = candidate.title()
            break

    summary_bits = []
    if inp.scene_description:
        summary_bits.append(f"Visuals: {inp.scene_description}")
    if inp.transcript:
        summary_bits.append(f"Spoken: {inp.transcript[:400]}")
    if inp.ocr_text:
        summary_bits.append(f"On-screen text: {inp.ocr_text[:200]}")
    summary = " | ".join(summary_bits) or "No transcript or visual signals extracted."

    key_points = [t for t in inp.visual_tags[:5]]
    if inp.transcript:
        sentences = [s.strip() for s in inp.transcript.replace("\n", " ").split(".") if s.strip()]
        key_points.extend(sentences[:3])

    return {
        "title_suggestion": title[:290],
        "topic": topic,
        "summary": summary[:1500],
        "key_points": key_points[:6],
    }


def synthesize(inp: DNASynthesisInput) -> dict:
    """Return ``{"title_suggestion", "topic", "summary", "key_points"}``."""
    if not (inp.transcript or inp.scene_description or inp.ocr_text or inp.visual_tags):
        return _heuristic_synthesis(inp)

    llm = get_llm_service()
    user = (
        f"TRANSCRIPT:\n{inp.transcript or '(none)'}\n\n"
        f"SCENE DESCRIPTION:\n{inp.scene_description or '(none)'}\n\n"
        f"ON-SCREEN TEXT (OCR):\n{inp.ocr_text or '(none)'}\n\n"
        f"VISUAL TAGS: {', '.join(inp.visual_tags) or '(none)'}\n"
    )

    def fallback() -> dict:
        return _heuristic_synthesis(inp)

    result, _note = llm.generate_json(
        LLMMediaSynthesis, system=_SYNTH_SYSTEM, user=user, fallback=fallback, temperature=0.3
    )
    if result is None:
        return _heuristic_synthesis(inp)
    return {
        "title_suggestion": result.title_suggestion or _heuristic_synthesis(inp)["title_suggestion"],
        "topic": result.topic or "General",
        "summary": result.summary,
        "key_points": result.key_points,
    }


def build_dna(
    db: Session,
    *,
    user_id: int,
    asset_id: int,
    transcript_result: TranscriptionResult,
    vision_result,
    keyframe_paths: list[Path],
    audio_path: Path | None,
    metadata: dict | None = None,
) -> ContentDNA:
    """Create (or replace) the ContentDNA row for an asset."""
    merged = merge_analyses(vision_result.analyses)
    analyses_dicts = [a.model_dump() for a in vision_result.analyses]

    inp = DNASynthesisInput(
        transcript=transcript_result.transcript,
        language=transcript_result.language,
        scene_description=merged["scene_description"],
        ocr_text=merged["ocr_text"],
        visual_tags=merged["visual_tags"],
        keyframe_analyses=analyses_dicts,
        keyframes=list(range(len(keyframe_paths))),
        audio_path=str(audio_path) if audio_path else "",
    )
    synthesis = synthesize(inp)

    existing = db.query(ContentDNA).filter(ContentDNA.asset_id == asset_id).first()
    if existing is None:
        existing = ContentDNA(user_id=user_id, asset_id=asset_id)
        db.add(existing)

    existing.transcript = transcript_result.transcript
    existing.language = transcript_result.language
    existing.scene_description = merged["scene_description"]
    existing.ocr_text = merged["ocr_text"]
    existing.visual_tags = merged["visual_tags"]
    existing.keyframe_analyses = analyses_dicts
    existing.keyframes = inp.keyframes
    existing.audio_path = str(audio_path) if audio_path else ""
    # Reviewer scores stay NULL (not evaluated) — Phase 3 implements scoring.
    existing.raw_analysis = [synthesis]
    db.flush()
    return existing


def synthesis_summary(dna: ContentDNA) -> dict:
    """Return the most recent synthesis dict stored on the DNA row."""
    if dna.raw_analysis:
        last = dna.raw_analysis[-1]
        if isinstance(last, dict):
            return last
    return {"title_suggestion": "", "topic": dna.transcript[:80] or "General", "summary": "", "key_points": []}
