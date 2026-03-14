from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.media.render import (
    _apply_music_and_watermark,
    _resolve_delivery_resolution,
    _should_apply_smart_effect_video_transforms,
)


@pytest.mark.asyncio
async def test_apply_music_and_watermark_keys_out_white_background_when_not_preprocessed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    watermark = tmp_path / "logo.jpg"
    watermark.write_bytes(b"jpg")
    output = tmp_path / "out.mp4"

    await _apply_music_and_watermark(
        source,
        music_plan=None,
        watermark_plan={
            "path": str(watermark),
            "position": "top_right",
            "opacity": 0.82,
            "scale": 0.16,
            "watermark_preprocessed": False,
        },
        expected_width=736,
        expected_height=992,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "colorkey=0xF8F8F8:0.20:0.08" in filter_complex


def test_smart_effect_video_transforms_are_disabled_for_picture_in_picture_avatar():
    assert _should_apply_smart_effect_video_transforms({"integration_mode": "picture_in_picture"}) is False
    assert _should_apply_smart_effect_video_transforms({"integration_mode": "full_frame"}) is True


def test_resolve_delivery_resolution_supports_source_and_specified_modes():
    assert _resolve_delivery_resolution(
        expected_width=3840,
        expected_height=2160,
        delivery={"resolution_mode": "source", "resolution_preset": "1080p"},
    ) == (3840, 2160)
    assert _resolve_delivery_resolution(
        expected_width=3840,
        expected_height=2160,
        delivery={"resolution_mode": "specified", "resolution_preset": "1080p"},
    ) == (1920, 1080)
    assert _resolve_delivery_resolution(
        expected_width=1080,
        expected_height=1920,
        delivery={"resolution_mode": "specified", "resolution_preset": "1440p"},
    ) == (1440, 2560)
