"""Focused tests for deterministic Content DNA insights."""

from __future__ import annotations

from app.services.content_dna_service import (
    DNASynthesisInput,
    _heuristic_synthesis,
    _recommendations,
)


def _titles(recommendations) -> list[str]:
    return [recommendation.title for recommendation in recommendations]


def test_audio_does_not_suggest_visual_retry():
    inp = DNASynthesisInput(
        transcript="A short spoken update.",
        media_type="audio",
        vision_available=False,
        transcription_available=True,
        transcription_applicable=True,
    )

    titles = _titles(_recommendations(inp, {}, None, ""))

    assert "Retry visual analysis" not in titles


def test_video_without_audio_does_not_suggest_captions():
    inp = DNASynthesisInput(
        scene_description="A city street at sunrise.",
        media_type="video",
        vision_available=True,
        transcription_available=False,
        transcription_applicable=False,
    )

    titles = _titles(_recommendations(inp, {}, None, ""))

    assert "Add captions from the audio" not in titles


def test_topic_detection_uses_whole_words():
    inp = DNASynthesisInput(transcript="She said hello to the whole team.")

    synthesis = _heuristic_synthesis(inp)

    assert synthesis["topic"] == ""


def test_tags_only_still_produce_grounded_synthesis():
    inp = DNASynthesisInput(visual_tags=["beach", "sunset"])

    synthesis = _heuristic_synthesis(inp)

    assert "beach" in synthesis["title_suggestion"].lower()
    assert synthesis["key_points"][:2] == ["beach", "sunset"]
