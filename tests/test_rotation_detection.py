from __future__ import annotations

import asyncio

from roughcut.media.rotation import (
    _ROTATION_PROMPT,
    _VisionRotation,
    _guard_weak_pov_180_decision,
    _read_cached_orientation_decision,
    _write_cached_orientation_decision,
    build_orientation_video_filter,
    _parse_vision_rotation,
    _probe_rotation_metadata_summary,
    _resolve_rotation_decision,
    detect_video_rotation_decision,
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


def test_build_orientation_video_filter_deletes_metadata_and_applies_visual_rotation() -> None:
    assert build_orientation_video_filter({"rotation_cw": 0}, "scale=960:-2") == (
        "sidedata=mode=delete:type=DISPLAYMATRIX,scale=960:-2"
    )
    assert build_orientation_video_filter({"rotation_cw": 270}, "scale=960:-2") == (
        "transpose=2,sidedata=mode=delete:type=DISPLAYMATRIX,scale=960:-2"
    )
    assert build_orientation_video_filter({"rotation_cw": 180}, "scale=960:-2") == (
        "hflip,vflip,sidedata=mode=delete:type=DISPLAYMATRIX,scale=960:-2"
    )


def test_rotation_prompt_requires_pov_top_bottom_evidence() -> None:
    assert "not merely landscape versus portrait" in _ROTATION_PROMPT
    assert "operator POV" in _ROTATION_PROMPT
    assert "hands and forearms usually enter from the lower edge" in _ROTATION_PROMPT
    assert "never choose 0 over 180 only because both are landscape" in _ROTATION_PROMPT
    assert "choose 180 only when the 180 panel itself unmistakably" in _ROTATION_PROMPT


def test_visual_orientation_decision_cache_survives_rate_limit_fallback(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "IMG_0218.MOV"
    source_path.write_bytes(b"same encoded source bytes")
    cache_dir = tmp_path / "orientation-cache"
    monkeypatch.setattr("roughcut.media.rotation._ORIENTATION_DECISION_CACHE_DIR", cache_dir)

    _write_cached_orientation_decision(
        source_path,
        _resolve_rotation_decision(
            vision=_VisionRotation(
                rotation_cw=180,
                confidence=0.8,
                reason="operator POV hands enter from lower edge",
                raw_answer='{"rotation":180}',
            ),
            metadata_rotation=270,
            frame_count=3,
        ),
    )

    cached = _read_cached_orientation_decision(source_path, metadata_rotation=270)

    assert cached is not None
    assert cached.rotation_cw == 180
    assert cached.source == "vision_cache"
    assert cached.metadata_rotation_cw == 270


def test_weak_pov_180_decision_is_guarded_for_landscape_iphone_metadata(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "demo.mov"
    source_path.write_bytes(b"video")
    monkeypatch.setattr("roughcut.media.rotation._probe_encoded_video_dimensions", lambda _path: (1920, 1080))

    guarded = _guard_weak_pov_180_decision(
        _VisionRotation(
            rotation_cw=180,
            confidence=0.8,
            reason="background artwork looks readable",
            raw_answer='{"rotation":180}',
        ),
        source_path=source_path,
        metadata_rotation=270,
    )

    assert guarded.rotation_cw == 0
    assert guarded.confidence >= 0.62
    assert "POV guard" in guarded.reason


def test_explicit_lower_edge_pov_180_evidence_is_allowed(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "demo.mov"
    source_path.write_bytes(b"video")
    monkeypatch.setattr("roughcut.media.rotation._probe_encoded_video_dimensions", lambda _path: (1920, 1080))
    vision = _VisionRotation(
        rotation_cw=180,
        confidence=0.92,
        reason="in the 180 panel the operator hands enter from the lower edge",
        raw_answer='{"rotation":180}',
    )

    assert _guard_weak_pov_180_decision(vision, source_path=source_path, metadata_rotation=270) is vision


def test_low_confidence_pov_180_is_guarded_even_with_claimed_lower_edge_evidence(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "demo.mov"
    source_path.write_bytes(b"video")
    monkeypatch.setattr("roughcut.media.rotation._probe_encoded_video_dimensions", lambda _path: (1920, 1080))

    guarded = _guard_weak_pov_180_decision(
        _VisionRotation(
            rotation_cw=180,
            confidence=0.8,
            reason="hands enter from the bottom edge",
            raw_answer='{"rotation":180}',
        ),
        source_path=source_path,
        metadata_rotation=270,
    )

    assert guarded.rotation_cw == 0


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


def test_detect_video_rotation_decision_short_circuits_when_metadata_is_upright(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "demo.mp4"
    source_path.write_bytes(b"video")

    monkeypatch.setattr("roughcut.media.rotation._probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        "roughcut.media.rotation._probe_rotation_metadata_summary",
        lambda _path: {"rotation_cw": 0, "has_display_matrix": False},
    )
    monkeypatch.setattr(
        "roughcut.media.rotation._extract_raw_frames",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("vision should be skipped")),
    )

    decision = asyncio.run(detect_video_rotation_decision(source_path))

    assert decision.rotation_cw == 0
    assert decision.source == "metadata_zero"
    assert decision.confidence == 0.92


def test_detect_video_rotation_uses_visual_candidate_sheets(monkeypatch, tmp_path) -> None:
    source_path = tmp_path / "demo.mp4"
    source_path.write_bytes(b"video")
    raw_frame = tmp_path / "raw.jpg"
    raw_frame.write_bytes(b"raw")
    candidate_sheet = tmp_path / "sheet.jpg"
    candidate_sheet.write_bytes(b"sheet")
    captured = {}

    async def fake_complete_with_images(prompt, images, **_kwargs):
        captured["prompt"] = prompt
        captured["images"] = images
        return '{"rotation":0,"confidence":0.82,"reason":"0 panel is upright"}'

    monkeypatch.setattr("roughcut.media.rotation._ORIENTATION_DECISION_CACHE_DIR", tmp_path / "orientation-cache")
    monkeypatch.setattr("roughcut.media.rotation._probe_duration", lambda _path: 12.0)
    monkeypatch.setattr(
        "roughcut.media.rotation._probe_rotation_metadata_summary",
        lambda _path: {"rotation_cw": 270, "has_display_matrix": True},
    )
    monkeypatch.setattr("roughcut.media.rotation._extract_raw_frames", lambda *_args, **_kwargs: [raw_frame])
    monkeypatch.setattr(
        "roughcut.media.rotation._build_orientation_candidate_sheets",
        lambda _frames, _tmpdir: [candidate_sheet],
    )
    monkeypatch.setattr("roughcut.media.rotation.complete_with_images", fake_complete_with_images)

    decision = asyncio.run(detect_video_rotation_decision(source_path))

    assert captured["images"] == [candidate_sheet]
    assert "contact sheet" in captured["prompt"]
    assert "operator POV" in captured["prompt"]
    assert decision.rotation_cw == 0
    assert decision.source == "vision"
    assert decision.metadata_rotation_cw == 270


def test_probe_rotation_metadata_summary_defaults_to_zero(tmp_path) -> None:
    source_path = tmp_path / "missing.mp4"

    summary = _probe_rotation_metadata_summary(source_path)

    assert summary == {"rotation_cw": 0, "has_display_matrix": False}
