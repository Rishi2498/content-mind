"""Combine transcript, keyframe observations and metadata into ContentDNA.

The synthesis step merges only signals that were actually produced by the
pipeline. It never invents a title, topic, score or summary for a file whose
analysis failed. A missing score is stored as ``None`` ("not evaluated"),
never as zero.

Scores shown on Content DNA are produced by a defined heuristic evaluation of
the transcript/on-screen text (and brand profile when one exists). They are
model-free estimates, not measured performance metrics; the UI labels them as
such.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BrandProfile, ContentDNA
from ..schemas import (
    ContentDNABrand,
    ContentDNAInsights,
    ContentDNARead,
    ContentDNARecommendation,
    ContentDNAScore,
    LLMMediaSynthesis,
)
from .llm_service import get_llm_service
from .transcription_service import TranscriptionResult
from .vision_service import merge_analyses

logger = logging.getLogger("contentmind.dna")

_SYNTH_SYSTEM = (
    "You are a content analyst. You receive a video/audio transcript (if any) "
    "and visual observations from keyframes (scene descriptions, on-screen text, "
    "tags). Produce a concise title suggestion, a topic label, a short summary, "
    "and 3-6 key points. Base everything strictly on the provided signals. If a "
    "field cannot be supported by the signals, return an empty string or empty "
    "list instead of guessing."
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
    media_type: str = ""
    filename: str = ""
    duration_seconds: float | None = None
    vision_available: bool = False
    transcription_available: bool = False
    transcription_applicable: bool = True


def _has_signals(inp: DNASynthesisInput) -> bool:
    return bool(
        inp.transcript.strip()
        or inp.scene_description.strip()
        or inp.ocr_text.strip()
        or inp.visual_tags
    )


def _first_sentence(text: str, limit: int = 220) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    for separator in (". ", "! ", "? ", "\n"):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
            break
    return cleaned[:limit]


def _heuristic_synthesis(inp: DNASynthesisInput) -> dict:
    """Deterministic synthesis from real signals only (no invented filler)."""
    source = (
        inp.transcript.strip()
        or inp.ocr_text.strip()
        or inp.scene_description.strip()
        or ", ".join(tag.strip() for tag in inp.visual_tags if tag.strip())
    )
    if not source:
        return {"title_suggestion": "", "topic": "", "summary": "", "key_points": []}

    words = source.split()
    title = " ".join(words[:12]) + ("…" if len(words) > 12 else "")

    topic = ""
    lowered = source.lower()
    words = set(re.findall(r"[a-z0-9]+", lowered))
    tags = {tag.lower() for tag in inp.visual_tags}
    for candidate in (
        "ai", "marketing", "product", "tutorial", "finance", "health",
        "education", "news", "travel", "food", "fitness", "design",
    ):
        if candidate in words or candidate in tags:
            topic = candidate.title()
            break

    summary_bits = []
    if inp.scene_description:
        summary_bits.append(f"Visuals: {inp.scene_description}")
    if inp.transcript:
        summary_bits.append(f"Spoken: {inp.transcript[:400]}")
    if inp.ocr_text:
        summary_bits.append(f"On-screen text: {inp.ocr_text[:200]}")
    if not summary_bits and inp.visual_tags:
        summary_bits.append(f"Visual elements: {', '.join(inp.visual_tags[:6])}")
    summary = " | ".join(summary_bits)

    key_points = [t for t in inp.visual_tags[:5]]
    if inp.transcript:
        sentences = [
            s.strip()
            for s in inp.transcript.replace("\n", " ").replace("!", ".").replace("?", ".").split(".")
            if s.strip()
        ]
        key_points.extend(sentences[:3])

    return {
        "title_suggestion": title.strip()[:290],
        "topic": topic[:120],
        "summary": summary[:1500],
        "key_points": key_points[:6],
    }


def synthesize(inp: DNASynthesisInput) -> tuple[dict, str]:
    """Return ``(synthesis, source)`` where source is ``llm`` or ``heuristic``."""
    if not _has_signals(inp):
        return {"title_suggestion": "", "topic": "", "summary": "", "key_points": []}, "none"

    llm = get_llm_service()
    user = (
        f"MEDIA TYPE: {inp.media_type or 'unknown'}\n"
        f"TRANSCRIPT:\n{inp.transcript or '(none)'}\n\n"
        f"SCENE DESCRIPTION:\n{inp.scene_description or '(none)'}\n\n"
        f"ON-SCREEN TEXT (OCR):\n{inp.ocr_text or '(none)'}\n\n"
        f"VISUAL TAGS: {', '.join(inp.visual_tags) or '(none)'}\n"
    )

    def fallback() -> dict:
        return _heuristic_synthesis(inp)

    result, note = llm.generate_json(
        LLMMediaSynthesis, system=_SYNTH_SYSTEM, user=user, fallback=fallback, temperature=0.3
    )
    if result is None:
        return _heuristic_synthesis(inp), "heuristic"
    fallback_values = _heuristic_synthesis(inp)
    return {
        "title_suggestion": result.title_suggestion or fallback_values["title_suggestion"],
        "topic": result.topic or fallback_values["topic"],
        "summary": result.summary or fallback_values["summary"],
        "key_points": result.key_points or fallback_values["key_points"],
    }, ("llm" if note.startswith("llm") else "heuristic")


def _brand_for_user(db: Session, user_id: int) -> BrandProfile | None:
    return db.scalar(
        select(BrandProfile)
        .where(BrandProfile.user_id == user_id, BrandProfile.is_active.is_(True))
        .limit(1)
    )


def _evaluate_scores(
    *,
    transcript: str,
    ocr_text: str,
    scene_description: str,
    brand: BrandProfile | None,
    media_type: str,
) -> tuple[dict[str, ContentDNAScore], float | None, float | None, float | None]:
    """Defined heuristic evaluation of whatever text signals exist.

    Hook/clarity are only evaluated when there is transcript or on-screen
    text to read. Brand alignment is only evaluated when a brand profile with
    usable guidance exists. Scene descriptions alone are not scored as a
    "hook".
    """
    text = (transcript or ocr_text or "").strip()
    hook_score = clarity_score = brand_score = None
    scores: dict[str, ContentDNAScore] = {}

    if text:
        from .reviewer_service import ReviewContext, _heuristic_scores

        ctx = ReviewContext(
            title=_first_sentence(text, 120),
            body=text[:6000],
            platform="",
            topic="",
            brand=brand,
        )
        hook_score, clarity_score, heuristic_brand = _heuristic_scores(ctx)

        scores["hook"] = ContentDNAScore(
            value=round(hook_score, 1),
            status="evaluated",
            meaning="How strongly the opening line earns attention (0-100).",
            source="heuristic",
            reason="Estimated from the first line of the transcript or on-screen text.",
        )
        scores["clarity"] = ContentDNAScore(
            value=round(clarity_score, 1),
            status="evaluated",
            meaning="How easy the message is to follow (0-100).",
            source="heuristic",
            reason="Estimated from sentence length, filler words, and available text length.",
        )

        if brand is not None and (brand.tone or brand.description or brand.target_audience):
            brand_score = heuristic_brand
            scores["brand"] = ContentDNAScore(
                value=round(brand_score, 1),
                status="evaluated",
                meaning="How closely the content language matches your brand profile (0-100).",
                source="heuristic",
                reason="Estimated by comparing the available text with your brand tone and audience.",
            )
        else:
            scores["brand"] = ContentDNAScore(
                value=None,
                status="not_evaluated",
                meaning="How closely the content matches your brand voice (0-100).",
                source="",
                reason="Add a brand profile with a tone or audience to evaluate brand alignment.",
            )
    else:
        reason = (
            "No transcript or on-screen text was available to evaluate."
            if media_type in {"video", "audio"}
            else "No readable text was detected in this image."
        )
        scores["hook"] = ContentDNAScore(
            value=None,
            status="not_evaluated",
            meaning="How strongly the opening earns attention (0-100).",
            reason=reason,
        )
        scores["clarity"] = ContentDNAScore(
            value=None,
            status="not_evaluated",
            meaning="How easy the message is to follow (0-100).",
            reason=reason,
        )
        scores["brand"] = ContentDNAScore(
            value=None,
            status="not_evaluated",
            meaning="How closely the content matches your brand voice (0-100).",
            reason="Add a brand profile and text signals to evaluate brand alignment.",
        )

    return scores, hook_score, clarity_score, brand_score


def _recommendations(
    inp: DNASynthesisInput,
    scores: dict[str, ContentDNAScore],
    brand: BrandProfile | None,
    topic: str,
) -> list[ContentDNARecommendation]:
    recommendations: list[ContentDNARecommendation] = []
    if inp.media_type != "audio" and not inp.vision_available:
        recommendations.append(
            ContentDNARecommendation(
                title="Retry visual analysis",
                detail="Scene, on-screen text, and visual tags are missing. Retrying does not require another upload.",
                basis="The visual analysis step did not return a usable result.",
            )
        )
    if inp.transcription_applicable and not inp.transcription_available:
        recommendations.append(
            ContentDNARecommendation(
                title="Add captions from the audio",
                detail="Speech wasn't transcribed, so spoken-message insights are incomplete. Check the audio track and retry analysis.",
                basis="No transcript was produced for this file.",
            )
        )
    if inp.ocr_text:
        recommendations.append(
            ContentDNARecommendation(
                title="Reuse the on-screen text",
                detail="The image or video already contains readable text. Pull the strongest line into your caption or title.",
                basis=f"On-screen text detected: {_first_sentence(inp.ocr_text, 100)}",
            )
        )
    if inp.transcript and scores.get("hook", ContentDNAScore()).value is not None:
        hook_value = scores["hook"].value or 0
        if hook_value < 60:
            recommendations.append(
                ContentDNARecommendation(
                    title="Tighten the opening",
                    detail="Lead with the concrete result or question in the first sentence.",
                    basis=f"Opening-line estimate is {hook_value:.0f}/100.",
                )
            )
    if topic:
        recommendations.append(
            ContentDNARecommendation(
                title="Turn the topic into a follow-up",
                detail=f"Create a follow-up piece that goes deeper on “{topic}”.",
                basis="Topic detected from the available analysis.",
            )
        )
    if brand is None or not (brand.tone or brand.description or brand.target_audience):
        recommendations.append(
            ContentDNARecommendation(
                title="Set up your brand profile",
                detail="Add your tone, audience, and preferred platforms to unlock brand-alignment feedback.",
                basis="No active brand profile with usable guidance is configured.",
            )
        )
    return recommendations[:6]


def _build_insights(
    *,
    db: Session,
    user_id: int,
    inp: DNASynthesisInput,
    synthesis: dict,
    synthesis_source: str,
    scores: dict[str, ContentDNAScore],
    notes: list[str],
) -> tuple[ContentDNAInsights, BrandProfile | None]:
    brand = _brand_for_user(db, user_id)
    brand_configured = bool(
        brand is not None and (brand.tone or brand.description or brand.target_audience)
    )
    brand_schema = ContentDNABrand(
        status="configured" if brand_configured else "not_configured",
        name=(brand.brand_name if brand else ""),
        message=(
            ""
            if brand_configured
            else "Add a brand profile with your tone and audience to evaluate brand alignment."
        ),
    )

    media_labels = {"image": "Image post", "video": "Video", "audio": "Audio clip"}
    content_format = media_labels.get(inp.media_type, "Media")
    if inp.media_type == "video" and inp.duration_seconds is not None and inp.duration_seconds <= 60:
        content_format = "Short video"

    main_message = _first_sentence(inp.transcript) or _first_sentence(inp.ocr_text)
    strategy_signals: list[str] = []
    if inp.ocr_text:
        strategy_signals.append("Contains on-screen text that can be reused as a caption or title.")
    if inp.visual_tags:
        strategy_signals.append(f"Visual themes: {', '.join(inp.visual_tags[:6])}.")
    if inp.transcript:
        strategy_signals.append("Spoken message is available for repurposing into text content.")
    if inp.media_type == "image":
        strategy_signals.append("Still image: pair it with a written hook or carousel copy.")

    insights = ContentDNAInsights(
        summary=synthesis.get("summary", ""),
        topic=synthesis.get("topic", ""),
        main_message=main_message,
        content_format=content_format,
        key_points=synthesis.get("key_points", []),
        recommendations=_recommendations(inp, scores, brand, synthesis.get("topic", "")),
        audience=(brand.target_audience if brand else ""),
        strategy_signals=strategy_signals,
        brand=brand_schema,
        scores=scores,
        generated_by=synthesis_source,
        notes=notes,
    )
    return insights, brand


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
    preserve_previous: bool = True,
) -> ContentDNA | None:
    """Create or update ContentDNA using only genuinely available signals.

    Returns ``None`` when there is nothing valid to save. Successful results
    from an earlier run are preserved when a retry step fails, so a temporary
    provider outage does not erase working analysis.
    """
    metadata = metadata or {}
    media_type = metadata.get("media_type", "")
    transcription_applicable = (
        media_type == "audio"
        or (media_type == "video" and bool(metadata.get("has_audio", True)))
        or (media_type not in {"image", "video", "audio"})
    )
    existing = db.query(ContentDNA).filter(ContentDNA.asset_id == asset_id).first()
    merged = merge_analyses(vision_result.analyses)
    notes: list[str] = []

    new_transcript = (transcript_result.transcript or "").strip()
    previous_transcript = (existing.transcript or "").strip() if existing else ""
    transcript = new_transcript or (previous_transcript if preserve_previous else "")
    if not new_transcript and previous_transcript:
        notes.append("Kept the transcript from an earlier successful run.")
    language = transcript_result.language or (existing.language if existing else "")

    new_scene = merged["scene_description"].strip()
    new_ocr = merged["ocr_text"].strip()
    new_tags = list(merged["visual_tags"])
    scene = new_scene or ((existing.scene_description or "").strip() if existing and preserve_previous else "")
    ocr = new_ocr or ((existing.ocr_text or "").strip() if existing and preserve_previous else "")
    tags = new_tags or (list(existing.visual_tags or []) if existing and preserve_previous else [])
    if not new_scene and existing and (existing.scene_description or existing.visual_tags):
        notes.append("Kept visual insights from an earlier successful run.")

    if not (transcript or scene or ocr or tags):
        return None

    inp = DNASynthesisInput(
        transcript=transcript,
        language=language,
        scene_description=scene,
        ocr_text=ocr,
        visual_tags=tags,
        keyframe_analyses=[a.model_dump() for a in vision_result.analyses] or (
            list(existing.keyframe_analyses or []) if existing and preserve_previous else []
        ),
        keyframes=list(range(len(keyframe_paths))) or (
            list(existing.keyframes or []) if existing and preserve_previous else []
        ),
        audio_path=str(audio_path) if audio_path else "",
        media_type=media_type,
        filename=metadata.get("filename", ""),
        duration_seconds=metadata.get("duration_seconds"),
        vision_available=bool(vision_result.analyses),
        transcription_available=bool(transcript),
        transcription_applicable=transcription_applicable,
    )
    synthesis, synthesis_source = synthesize(inp)
    scores, hook_score, clarity_score, brand_score = _evaluate_scores(
        transcript=transcript,
        ocr_text=ocr,
        scene_description=scene,
        brand=_brand_for_user(db, user_id),
        media_type=metadata.get("media_type", ""),
    )
    insights, _brand = _build_insights(
        db=db,
        user_id=user_id,
        inp=inp,
        synthesis=synthesis,
        synthesis_source=synthesis_source,
        scores=scores,
        notes=notes,
    )

    if existing is None:
        existing = ContentDNA(user_id=user_id, asset_id=asset_id)
        db.add(existing)

    existing.transcript = transcript
    existing.language = language
    existing.scene_description = scene
    existing.ocr_text = ocr
    existing.visual_tags = tags
    existing.keyframe_analyses = inp.keyframe_analyses
    existing.keyframes = inp.keyframes
    existing.audio_path = str(audio_path) if audio_path else (existing.audio_path or "")
    existing.hook_score = hook_score if hook_score is not None else existing.hook_score
    existing.clarity_score = clarity_score if clarity_score is not None else existing.clarity_score
    existing.brand_alignment = brand_score if brand_score is not None else (
        existing.brand_alignment if insights.brand.status == "configured" else None
    )
    # Keep legacy keys at the top level so older callers keep working.
    existing.raw_analysis = [
        {
            **synthesis,
            "insights": insights.model_dump(),
            "synthesis_source": synthesis_source,
        }
    ]
    db.flush()
    return existing


def _last_raw_analysis(raw_analysis: object) -> dict:
    """Return the most recent raw-analysis object, tolerating legacy shapes."""
    if isinstance(raw_analysis, dict):
        return raw_analysis
    if isinstance(raw_analysis, list):
        for item in reversed(raw_analysis):
            if isinstance(item, dict):
                return item
    return {}


def insights_from_dna(db: Session, dna: ContentDNA, asset=None) -> ContentDNAInsights:
    """Build the public insights view, including for DNA rows from older runs."""
    raw = _last_raw_analysis(dna.raw_analysis)
    stored = raw.get("insights")
    if isinstance(stored, dict):
        try:
            return ContentDNAInsights.model_validate(stored)
        except Exception:  # noqa: BLE001 - tolerate old/partial JSON
            logger.info("Falling back to derived insights for DNA %s", dna.id)

    media_type = getattr(asset, "media_type", "") or ""
    text = (dna.transcript or dna.ocr_text or "").strip()
    scores, _h, _c, _b = _evaluate_scores(
        transcript=dna.transcript,
        ocr_text=dna.ocr_text,
        scene_description=dna.scene_description,
        brand=_brand_for_user(db, dna.user_id),
        media_type=media_type,
    )
    brand = _brand_for_user(db, dna.user_id)
    brand_configured = bool(brand and (brand.tone or brand.description or brand.target_audience))
    summary = (raw.get("summary") if isinstance(raw, dict) else "") or ""
    if not summary:
        bits = []
        if dna.scene_description:
            bits.append(f"Visuals: {dna.scene_description}")
        if dna.transcript:
            bits.append(f"Spoken: {dna.transcript[:400]}")
        if dna.ocr_text:
            bits.append(f"On-screen text: {dna.ocr_text[:200]}")
        summary = " | ".join(bits)
    return ContentDNAInsights(
        summary=summary,
        topic=(raw.get("topic") if isinstance(raw, dict) else "") or "",
        main_message=_first_sentence(dna.transcript) or _first_sentence(dna.ocr_text),
        content_format={"image": "Image post", "video": "Video", "audio": "Audio clip"}.get(
            media_type, "Media"
        ),
        key_points=(raw.get("key_points") if isinstance(raw, dict) else []) or [],
        recommendations=[],
        audience=(brand.target_audience if brand else ""),
        strategy_signals=[],
        brand=ContentDNABrand(
            status="configured" if brand_configured else "not_configured",
            name=(brand.brand_name if brand else ""),
            message="Add a brand profile to evaluate brand alignment." if not brand_configured else "",
        ),
        scores=scores,
        generated_by=(raw.get("synthesis_source") if isinstance(raw, dict) else "") or "",
        notes=["Scores are estimates from the available text, not measured performance."] if text else [],
    )


def dna_to_read(db: Session, dna: ContentDNA, asset=None) -> ContentDNARead:
    return ContentDNARead(
        id=dna.id,
        asset_id=dna.asset_id,
        content_id=dna.content_id,
        transcript=dna.transcript or "",
        language=dna.language or "",
        scene_description=dna.scene_description or "",
        ocr_text=dna.ocr_text or "",
        visual_tags=list(dna.visual_tags or []),
        keyframe_analyses=list(dna.keyframe_analyses or []),
        keyframes=list(dna.keyframes or []),
        hook_score=dna.hook_score,
        clarity_score=dna.clarity_score,
        brand_alignment=dna.brand_alignment,
        insights=insights_from_dna(db, dna, asset=asset),
        created_at=dna.created_at,
        updated_at=dna.updated_at,
    )


def synthesis_summary(dna: ContentDNA) -> dict:
    """Return the most recent synthesis dict stored on the DNA row."""
    last = _last_raw_analysis(dna.raw_analysis)
    if last:
        return last
    return {
        "title_suggestion": "",
        "topic": "",
        "summary": (dna.transcript or dna.ocr_text or dna.scene_description or "")[:400],
        "key_points": [],
    }
