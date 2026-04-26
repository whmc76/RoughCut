from __future__ import annotations

from roughcut.media.rotation import (
    _VisionRotation,
    _parse_vision_rotation,
    _resolve_rotation_decision,
)


def test_parse_vision_rotation_accepts_structured_json() -> None:
    parsed = _parse_vision_rotation('{"rotation":90,"confidence":0.86,"reason":"sideways hands"}')

    assert parsed.rotation_cw == 90
    assert parsed.confidence == 0.86
    assert parsed.reason == "sideways hands"


def test_parse_vision_rotation_falls_back_to_number_response() -> None:
    parsed = _parse_vision_rotation("Rotate clockwise 270 degrees")

    assert parsed.rotation_cw == 270
    assert parsed.confidence == 0.7


def test_high_confidence_vision_overrides_metadata() -> None:
    decision = _resolve_rotation_decision(
        vision=_VisionRotation(rotation_cw=0, confidence=0.92, reason="upright", raw_answer="{}"),
        metadata_rotation=90,
        frame_count=3,
    )

    assert decision.rotation_cw == 0
    assert decision.source == "vision"
    assert decision.metadata_rotation_cw == 90


def test_low_confidence_vision_uses_metadata_fallback() -> None:
    decision = _resolve_rotation_decision(
        vision=_VisionRotation(rotation_cw=0, confidence=0.3, reason="unclear", raw_answer="{}"),
        metadata_rotation=270,
        frame_count=3,
    )

    assert decision.rotation_cw == 270
    assert decision.source == "metadata"


def test_lowish_confidence_agreement_uses_rotation() -> None:
    decision = _resolve_rotation_decision(
        vision=_VisionRotation(rotation_cw=180, confidence=0.5, reason="upside down", raw_answer="{}"),
        metadata_rotation=180,
        frame_count=3,
    )

    assert decision.rotation_cw == 180
    assert decision.source == "vision_metadata_agree"
    assert decision.confidence == 0.65
