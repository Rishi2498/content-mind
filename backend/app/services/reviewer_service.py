"""Pre-publish reviewer: hook, clarity, and brand-consistency analysis.

Given a draft (title + body) or a media asset's ContentDNA, the reviewer
produces 0-100 scores for hook strength, clarity, and brand alignment, plus
actionable suggestions. Every suggestion carries evidence — either the brand
rule it references or a learned memory statement recalled from the account's
history — so advice is grounded, not generic.

Flow: draft + brand profile + recalled memories -> LLM (strict JSON)
                                                   |
                                    invalid/absent +-----> deterministic heuristic
                                                              |
                                                    scores + suggestions + evidence
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import BrandProfile, ContentDNA, ContentReview
from ..schemas import LLMReviewResult, ReviewerRequest, ReviewerResponse, ReviewerSuggestion
from .llm_service import get_llm_service
from .memory_service import MemoryService

logger = logging.getLogger("contentmind.reviewer")

_REVIEW_SYSTEM = (
    "You are a strict pre-publish content reviewer for a social/media team. "
    "You score drafts on three axes (0-100): (1) HOOK — does the opening "
    "line earn the next second? (2) CLARITY — is the message skimmable and "
    "unambiguous? (3) BRAND ALIGNMENT — does it fit the stated brand voice "
    "and audience? You also produce 2-6 actionable suggestions, each with a "
    "category (hook|clarity|brand|structure|cta|topic), severity "
    "(critical|improve|nice_to_have), the concrete rewrite advice, a short "
    "rationale, and the evidence (quote the brand rule or memory) that "
    "justifies it. Never invent performance numbers. If evidence is thin, "
    "say so in the rationale."
)

_POWER_OPENERS = re.compile(
    r"^(how|why|what|when|where|which|who)\b|^\d+\s|\b(secrets?|mistakes?|truth|nobody|everyone|stop|start|imagine|picture this)\b",
    re.IGNORECASE,
)
_FILLER = re.compile(
    r"\b(very|really|just|actually|basically|literally|simply|quite|rather|somewhat|in order to|it is important to note|as we all know)\b",
    re.IGNORECASE,
)
_WEAK_CTA = re.compile(r"\b(like and subscribe|follow for more|check it out|learn more|stay tuned)\b", re.IGNORECASE)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text)


@dataclass
class ReviewContext:
    title: str = ""
    body: str = ""
    platform: str = ""
    topic: str = ""
    brand: BrandProfile | None = None
    memories: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------------
# Heuristic engine (deterministic fallback; also seeds evidence when no LLM)
# ----------------------------------------------------------------------------------
def _heuristic_scores(ctx: ReviewContext) -> tuple[float, float, float]:
    body = ctx.body or ""
    title = ctx.title or ""
    combined = f"{title}\n{body}".strip()
    first_line = (body.strip().splitlines() or [""])[0].strip() or title.strip()
    words = _words(combined)
    sentences = _sentences(combined)

    # --- hook -------------------------------------------------------------------
    hook = 40.0
    if first_line:
        if _POWER_OPENERS.search(first_line):
            hook += 22
        first_words = len(_words(first_line))
        if 3 <= first_words <= 14:
            hook += 16
        elif first_words > 25:
            hook -= 12
        if re.search(r"[?]", first_line):
            hook += 8
        if re.search(r"\d", first_line):
            hook += 8
        if len(first_line) <= 80:
            hook += 6
    else:
        hook = 15.0
    hook = max(0.0, min(100.0, hook))

    # --- clarity ----------------------------------------------------------------
    clarity = 70.0
    if sentences:
        avg_len = mean(len(_words(s)) for s in sentences)
        if avg_len <= 16:
            clarity += 12
        elif avg_len > 26:
            clarity -= 18
    else:
        clarity = 30.0
    filler_hits = len(_FILLER.findall(combined))
    clarity -= min(25.0, filler_hits * 5)
    if len(words) < 15:
        clarity -= 20
    if len(words) > 800:
        clarity -= 10
    clarity = max(0.0, min(100.0, clarity))

    # --- brand alignment --------------------------------------------------------
    brand = ctx.brand
    if brand is None or not (brand.tone or brand.description or brand.target_audience):
        alignment = 55.0  # neutral: nothing to compare against
    else:
        alignment = 50.0
        brand_tokens = set(
            _words((brand.tone or "") + " " + (brand.description or "") + " " + (brand.target_audience or ""))
        )
        body_tokens = set(_words(combined.lower()))
        overlap = brand_tokens & body_tokens
        if overlap:
            alignment += min(30.0, len(overlap) * 4)
        if brand.tone and any(t in combined.lower() for t in _words(brand.tone.lower())):
            alignment += 10
        if brand.preferred_platforms and ctx.platform:
            if any(ctx.platform.lower() == p.lower() for p in brand.preferred_platforms):
                alignment += 8
        if _WEAK_CTA.search(combined):
            alignment -= 6
    alignment = max(0.0, min(100.0, alignment))
    return hook, clarity, alignment


def _heuristic_suggestions(ctx: ReviewContext) -> list[ReviewerSuggestion]:
    suggestions: list[ReviewerSuggestion] = []
    body = (ctx.body or "").strip()
    first_line = (body.splitlines() or [""])[0].strip() or (ctx.title or "").strip()
    combined = f"{ctx.title}\n{body}".strip()

    if not _POWER_OPENERS.search(first_line):
        suggestions.append(
            ReviewerSuggestion(
                category="hook",
                severity="improve",
                suggestion="Open with a question, a number, or a concrete claim in the first line.",
                rationale=f"The current opener ('{first_line[:80]}…') does not create an information gap.",
                evidence="Hook heuristic: power openers (question/number/contrarian word) lift read-through.",
            )
        )
    if len(_words(first_line)) > 20:
        suggestions.append(
            ReviewerSuggestion(
                category="hook",
                severity="improve",
                suggestion="Cut the first line to under ~15 words; move detail to sentence two.",
                rationale=f"The opener is {len(_words(first_line))} words long.",
                evidence="Hook heuristic: long openers dilute the promise on scrolling feeds.",
            )
        )

    sentences = _sentences(combined)
    if sentences:
        avg_len = mean(len(_words(s)) for s in sentences)
        if avg_len > 24:
            suggestions.append(
                ReviewerSuggestion(
                    category="clarity",
                    severity="improve",
                    suggestion="Break long sentences; aim for ~15-20 words each.",
                    rationale=f"Average sentence length is {avg_len:.0f} words.",
                    evidence="Clarity heuristic: sentences over ~24 words reduce skim-comprehension.",
                )
            )
    filler_hits = _FILLER.findall(combined)
    if filler_hits:
        sample = ", ".join(sorted(set(f.lower() for f in filler_hits))[:4])
        suggestions.append(
            ReviewerSuggestion(
                category="clarity",
                severity="nice_to_have",
                suggestion=f"Remove filler words where possible (found: {sample}).",
                rationale=f"{len(filler_hits)} filler occurrences.",
                evidence="Clarity heuristic: filler weakens assertions and eats character budgets.",
            )
        )

    brand = ctx.brand
    if brand is not None and brand.tone:
        suggestions.append(
            ReviewerSuggestion(
                category="brand",
                severity="nice_to_have",
                suggestion=f"Re-read once with the brand tone in mind: '{brand.tone[:120]}'.",
                rationale="Brand profile exists; tone match was scored heuristically.",
                evidence=f"Brand rule (profile): tone = {brand.tone[:200]}",
            )
        )
    if not re.search(r"(comment|reply|try|share|tell us|what do you|dm|book|download|subscribe)", combined, re.IGNORECASE):
        suggestions.append(
            ReviewerSuggestion(
                category="cta",
                severity="nice_to_have",
                suggestion="Add a single explicit next step (question, invite to reply, or link).",
                rationale="No clear call-to-action detected in the draft.",
                evidence="CTA heuristic: one concrete ask converts passive readers.",
            )
        )
    for mem in ctx.memories[:2]:
        suggestions.append(
            ReviewerSuggestion(
                category="topic",
                severity="nice_to_have",
                suggestion="Compare this draft against the learned pattern below before publishing.",
                rationale="A learned memory from your own history is relevant to this draft.",
                evidence=f"Learned memory: {mem[:300]}",
            )
        )
    return suggestions[:6]


# ----------------------------------------------------------------------------------
# LLM engine
# ----------------------------------------------------------------------------------
def _llm_review(ctx: ReviewContext) -> tuple[LLMReviewResult | None, str]:
    llm = get_llm_service()
    brand = ctx.brand
    brand_block = (
        f"BRAND: {brand.brand_name}\nTONE: {brand.tone or '(unset)'}\n"
        f"AUDIENCE: {brand.target_audience or '(unset)'}\n"
        f"DESCRIPTION: {brand.description or '(unset)'}"
        if brand
        else "BRAND: (no brand profile configured — score brand alignment neutrally)"
    )
    memories_block = (
        "LEARNED MEMORIES (cite as evidence where relevant):\n- "
        + "\n- ".join(ctx.memories[:8])
        if ctx.memories
        else "LEARNED MEMORIES: (none)"
    )
    user = (
        f"{brand_block}\n{memories_block}\n\n"
        f"PLATFORM: {ctx.platform or '(unspecified)'}\n"
        f"TOPIC: {ctx.topic or '(unspecified)'}\n"
        f"TITLE: {ctx.title or '(none)'}\n\n"
        f"DRAFT BODY:\n{ctx.body[:6000]}\n\n"
        "Score the draft and produce suggestions per the schema."
    )

    def fallback() -> dict:
        hook, clarity, alignment = _heuristic_scores(ctx)
        return {
            "hook_score": hook,
            "clarity_score": clarity,
            "brand_alignment": alignment,
            "summary": "Heuristic review (no LLM available).",
            "suggestions": [s.model_dump() for s in _heuristic_suggestions(ctx)],
        }

    result, note = llm.generate_json(
        LLMReviewResult, system=_REVIEW_SYSTEM, user=user, fallback=fallback, temperature=0.3
    )
    return result, note


# ----------------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------------
def _overall(hook: float, clarity: float, alignment: float) -> float:
    return round(hook * 0.35 + clarity * 0.35 + alignment * 0.30, 1)


def _recall_memories(db: Session, user_id: int, query: str) -> list[str]:
    try:
        response = MemoryService(db).recall(query[:500], user_id=user_id, limit=6)
        return [m.text for m in response.memories if getattr(m, "text", None)][:6]
    except Exception as exc:  # noqa: BLE001 - recall must never break review
        logger.info("Memory recall for review skipped: %s", exc)
        return []


def _get_brand(db: Session, user_id: int) -> BrandProfile | None:
    return db.scalar(
        select(BrandProfile).where(
            BrandProfile.user_id == user_id, BrandProfile.is_active.is_(True)
        ).limit(1)
    )


def review_draft(
    db: Session,
    payload: ReviewerRequest,
    user_id: int,
    *,
    persist: bool = True,
) -> ReviewerResponse:
    """Review a text draft; optionally persist as ContentReview history."""
    brand = _get_brand(db, user_id)
    query = f"{payload.title} {payload.body[:300]}"
    memories = _recall_memories(db, user_id, query)
    ctx = ReviewContext(
        title=payload.title,
        body=payload.body,
        platform=payload.platform,
        topic=payload.topic,
        brand=brand,
        memories=memories,
    )

    result, note = _llm_review(ctx)
    if result is None:
        hook, clarity, alignment = _heuristic_scores(ctx)
        suggestions = _heuristic_suggestions(ctx)
        engine, degraded, summary = "heuristic", True, "Heuristic review (LLM unavailable or invalid)."
    else:
        hook = max(0.0, min(100.0, result.hook_score))
        clarity = max(0.0, min(100.0, result.clarity_score))
        alignment = max(0.0, min(100.0, result.brand_alignment))
        suggestions = result.suggestions[:8]
        engine = "llm" if note.startswith("llm") else "heuristic"
        degraded = engine != "llm"
        summary = result.summary or ("LLM review." if engine == "llm" else "Heuristic review.")

    evidence = [s.evidence for s in suggestions if s.evidence]
    if memories:
        evidence.extend(f"Recalled memory: {m[:200]}" for m in memories[:3])

    response = ReviewerResponse(
        hook_score=round(hook, 1),
        clarity_score=round(clarity, 1),
        brand_alignment=round(alignment, 1),
        overall_score=_overall(hook, clarity, alignment),
        summary=summary,
        suggestions=suggestions,
        evidence=list(dict.fromkeys(evidence))[:8],
        degraded=degraded,
        engine=engine,
    )

    if persist:
        review = ContentReview(
            user_id=user_id,
            content_id=payload.content_id,
            source="draft",
            platform=payload.platform,
            topic=payload.topic,
            title=payload.title,
            draft_excerpt=(payload.body or "")[:1000],
            hook_score=response.hook_score,
            clarity_score=response.clarity_score,
            brand_alignment=response.brand_alignment,
            overall_score=response.overall_score,
            suggestions=[s.model_dump() for s in suggestions],
            evidence=response.evidence,
            degraded=degraded,
            engine=engine,
        )
        db.add(review)
        db.flush()
        response.review_id = review.id
    return response


def review_media_asset(
    db: Session,
    *,
    user_id: int,
    asset_id: int,
    platform: str = "",
    topic: str = "",
    persist: bool = True,
) -> ReviewerResponse | None:
    """Review a processed media asset using its ContentDNA.

    On success the DNA's reviewer scores (previously NULL = not evaluated)
    are written, closing the Phase 2 -> Phase 3 loop.
    """
    from ..models import MediaAsset

    asset = db.get(MediaAsset, asset_id)
    if asset is None or asset.user_id != user_id:
        return None
    dna = db.query(ContentDNA).filter(ContentDNA.asset_id == asset_id).first()
    if dna is None:
        return None

    body_parts = [
        dna.transcript,
        f"Scene: {dna.scene_description}" if dna.scene_description else "",
        f"On-screen text: {dna.ocr_text}" if dna.ocr_text else "",
        f"Visual tags: {', '.join(dna.visual_tags)}" if dna.visual_tags else "",
    ]
    body = "\n".join(p for p in body_parts if p).strip() or "(no signals extracted from this asset)"

    payload = ReviewerRequest(
        title=asset.filename,
        body=body,
        platform=platform,
        topic=topic or dna.raw_analysis[-1].get("topic", "") if dna.raw_analysis else topic,
    )
    response = review_draft(db, payload, user_id, persist=persist)
    response.review_id = response.review_id

    # write scores back onto the DNA (first real evaluation)
    dna.hook_score = response.hook_score
    dna.clarity_score = response.clarity_score
    dna.brand_alignment = response.brand_alignment
    db.flush()

    if persist:
        review = db.get(ContentReview, response.review_id) if response.review_id else None
        if review is not None:
            review.source = "media"
            review.asset_id = asset_id
            db.flush()
    return response


def review_history(
    db: Session,
    user_id: int,
    *,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[ContentReview], int]:
    from sqlalchemy import func

    total = db.scalar(select(func.count(ContentReview.id)).where(ContentReview.user_id == user_id)) or 0
    rows = list(
        db.scalars(
            select(ContentReview)
            .where(ContentReview.user_id == user_id)
            .order_by(ContentReview.id.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total
