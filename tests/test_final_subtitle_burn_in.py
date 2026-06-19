from __future__ import annotations

from pathlib import Path

import pytest

from roughcut import hyperframes
from roughcut.media import render


def test_ffmpeg_map_label_keeps_input_stream_specs_unwrapped() -> None:
    assert render._ffmpeg_map_label("0:a") == "0:a"
    assert render._ffmpeg_map_label("0:v:0") == "0:v:0"
    assert render._ffmpeg_map_label("vsub") == "[vsub]"
    assert render._ffmpeg_map_label("[aout]") == "[aout]"


@pytest.mark.asyncio
async def test_final_subtitle_burn_in_does_not_reapply_audio_or_visual_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        render,
        "_probe_video_stream",
        lambda _path: {"display_width": 1920, "display_height": 1080, "width": 1920, "height": 1080},
    )

    async def fake_apply_timed_overlays_to_video(source_path: Path, **kwargs):
        captured["source_path"] = source_path
        captured.update(kwargs)
        return kwargs["output_path"]

    monkeypatch.setattr(render, "_apply_timed_overlays_to_video", fake_apply_timed_overlays_to_video)

    subtitles_plan = {"style": "keyword_highlight", "motion_style": "motion_pop"}
    packaging_context = {
        "hyperframes": hyperframes.build_static_packaging_plan(
            subtitles_plan=subtitles_plan,
            editing_accents={
                "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 2.0}],
                "sound_effects": [{"start_time": 1.0, "duration_sec": 0.15}],
            },
            source="test",
        )
    }

    source_path = tmp_path / "candidate.mp4"
    output_path = tmp_path / "final.mp4"
    result = await render.burn_subtitles_on_rendered_video(
        source_path,
        output_path=output_path,
        subtitle_items=[{"start_time": 1.0, "end_time": 2.0, "text_final": "最终字幕"}],
        subtitles_plan=subtitles_plan,
        debug_dir=tmp_path / "debug",
        packaging_context=packaging_context,
    )

    assert result == output_path
    assert captured["source_path"] == source_path
    assert captured["overlay_plan"] == {"emphasis_overlays": [], "sound_effects": []}
    assert captured["synthesize_subtitle_unit_accents"] is False
    assert captured["subtitles_plan"] == subtitles_plan
    subtitle_only_plan = captured["hyperframes_plan"]
    assert isinstance(subtitle_only_plan, dict)
    assert hyperframes.unified_subtitle_style_enabled(subtitle_only_plan)
    assert not hyperframes.progress_bar_enabled(subtitle_only_plan)
    assert hyperframes.overlay_plan_from_plan(subtitle_only_plan) == {"style": "smart_effect_commercial", "emphasis_overlays": [], "sound_effects": []}
