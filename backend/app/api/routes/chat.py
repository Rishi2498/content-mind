"""AI strategy chat."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import get_db
from ...schemas import ChatRequest, ChatResponse
from ...services.strategy_service import answer_question, detect_intent
from ...auth import get_current_user
from ...models import User


logger = logging.getLogger("contentmind.routes.chat")
router = APIRouter()

SUGGESTIONS = [
    "What should I post next week?",
    "What topics have worked best?",
    "What content have we overused?",
    "What are our biggest content gaps?",
    "What has our audience responded to?",
    "Describe our brand voice.",
    "Why did you recommend this topic?",
    "What did you learn from our latest content?",
]


@router.get("/suggestions")
def suggestions() -> dict:
    return {"suggestions": SUGGESTIONS}


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
) -> ChatResponse:
    try:
        response = answer_question(db, payload.message, current_user.id, payload.history)
    except Exception as exc:  # noqa: BLE001 - chat must always return something
        db.rollback()
        logger.exception("Chat failed")
        from ...services.strategy_service import build_strategy_context

        ctx = build_strategy_context(db, payload.message, user_id=current_user.id)
        if not ctx.has_history:
            return ChatResponse(
                answer=(
                    "I don't have any content history for this account yet, so anything I say "
                    "would be generic. Add your past content with its performance numbers and I "
                    "can answer this properly."
                ),
                confidence="low",
                degraded=True,
                notes=[str(exc)[:200]],
            )
        return ChatResponse(
            answer=(
                "Something went wrong while answering that, and I've fallen back to a partial "
                f"answer: you have {ctx.analytics.content_count} content items and "
                f"{len(ctx.memories)} memories recalled. Try asking about topics, gaps or "
                "audience response."
            ),
            confidence="low",
            degraded=True,
            notes=[str(exc)[:200]],
        )
    response.follow_ups = response.follow_ups or []
    return response



@router.get("/intent")
def intent(q: str) -> dict:
    return {"query": q, "intent": detect_intent(q)}
