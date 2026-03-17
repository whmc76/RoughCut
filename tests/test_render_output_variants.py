from __future__ import annotations

from pathlib import Path

import pytest

import roughcut.pipeline.steps as steps_mod


def test_shift_subtitles_for_insert_splits_crossing_item():
    shifted = steps_mod._shift_subtitles_for_insert(
        [
            {"start_time": 1.0, "end_time": 2.0, "text_final": "前段"},
            {"start_time": 4.5, "end_time": 5.5, "text_final": "跨过插入点"},
            {"start_time": 6.0, "end_time": 7.0, "text_final": "后段"},
        ],
        insert_after_sec=5.0,
        insert_duration=1.2,
    )

    assert shifted[0]["start_time"] == 1.0
    assert shifted[0]["end_time"] == 2.0
    assert shifted[1]["start_time"] == 4.5
    assert shifted[1]["end_time"] == 5.0
    assert shifted[2]["start_time"] == 6.2
    assert shifted[2]["end_time"] == 6.7
    assert shifted[3]["start_time"] == 7.2
    assert shifted[3]["end_time"] == 8.2


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_offsets_intro_and_insert(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "intro" in name:
            return DummyMeta(1.5)
        if "insert" in name:
            return DummyMeta(0.8)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.5, "end_time": 1.0, "text_final": "开头"},
            {"start_time": 3.0, "end_time": 4.0, "text_final": "后半段"},
        ],
        {
            "intro": {"path": "intro.mp4"},
            "insert": {"path": "insert.mp4", "insert_after_sec": 3.8},
        },
    )

    assert mapped[0]["start_time"] == 2.0
    assert mapped[0]["end_time"] == 2.5
    assert mapped[1]["start_time"] == 4.5
    assert mapped[1]["end_time"] == 5.3
    assert mapped[2]["start_time"] == 6.1
    assert mapped[2]["end_time"] == 6.3


@pytest.mark.asyncio
async def test_map_editing_accents_to_packaged_timeline_offsets_overlay_events(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "intro" in name:
            return DummyMeta(1.5)
        if "insert" in name:
            return DummyMeta(0.8)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_editing_accents_to_packaged_timeline(
        {
            "style": "smart_effect_rhythm",
            "emphasis_overlays": [{"text": "重点", "start_time": 3.0, "end_time": 4.0}],
            "sound_effects": [{"start_time": 4.2, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
        {
            "intro": {"path": "intro.mp4"},
            "insert": {"path": "insert.mp4", "insert_after_sec": 3.8},
        },
    )

    assert mapped["emphasis_overlays"][0]["start_time"] == 4.5
    assert mapped["emphasis_overlays"][0]["end_time"] == 5.3
    assert mapped["emphasis_overlays"][1]["start_time"] == 6.1
    assert mapped["emphasis_overlays"][1]["end_time"] == 6.3
    assert mapped["sound_effects"][0]["start_time"] == 6.5


def test_resolve_packaged_render_variant_defaults_to_original_timeline():
    source_path = Path("source.mp4")
    editorial_timeline = {"segments": [{"type": "keep", "start": 10.0, "end": 18.0}]}
    subtitle_items = [{"start_time": 10.2, "end_time": 11.0, "text_final": "原始字幕"}]

    packaged_source_path, packaged_editorial_timeline, packaged_subtitle_items = steps_mod._resolve_packaged_render_variant(
        original_source_path=source_path,
        original_editorial_timeline=editorial_timeline,
        original_subtitle_items=subtitle_items,
    )

    assert packaged_source_path == source_path
    assert packaged_editorial_timeline == editorial_timeline
    assert packaged_subtitle_items == subtitle_items
    assert packaged_editorial_timeline is not editorial_timeline
    assert packaged_subtitle_items is not subtitle_items


def test_resolve_packaged_render_variant_uses_full_length_timeline_for_variant_video():
    variant_path = Path("output_plain.avatar_pip.mp4")
    subtitle_items = [{"start_time": 0.2, "end_time": 1.0, "text_final": "成片字幕"}]

    packaged_source_path, packaged_editorial_timeline, packaged_subtitle_items = steps_mod._resolve_packaged_render_variant(
        original_source_path=Path("source.mp4"),
        original_editorial_timeline={"segments": [{"type": "keep", "start": 10.0, "end": 18.0}]},
        original_subtitle_items=[{"start_time": 10.2, "end_time": 11.0, "text_final": "原始字幕"}],
        variant_source_path=variant_path,
        variant_duration_sec=123.456,
        variant_subtitle_items=subtitle_items,
    )

    assert packaged_source_path == variant_path
    assert packaged_editorial_timeline == {"segments": [{"type": "keep", "start": 0.0, "end": 123.456}]}
    assert packaged_subtitle_items == subtitle_items
    assert packaged_subtitle_items is not subtitle_items


def test_resolve_packaged_render_variant_rejects_missing_variant_duration():
    with pytest.raises(ValueError, match="variant_duration_sec must be positive"):
        steps_mod._resolve_packaged_render_variant(
            original_source_path=Path("source.mp4"),
            original_editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 1.0}]},
            original_subtitle_items=[],
            variant_source_path=Path("output_plain.avatar_pip.mp4"),
            variant_duration_sec=0.0,
            variant_subtitle_items=[],
        )


@pytest.mark.asyncio
async def test_plan_music_entry_prefers_natural_pause_after_hook():
    plan = await steps_mod._plan_music_entry(
        music_plan={"path": "bgm.mp3"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.2, "text_final": "先抛一个结论。"},
            {"start_time": 2.4, "end_time": 5.6, "text_final": "这里把整个剪映批量字幕流程先讲完整。"},
            {"start_time": 6.1, "end_time": 8.2, "text_final": "接下来再看怎么统一字号和描边。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
    )

    assert plan is not None
    assert plan["enter_sec"] == 5.6
    assert plan["timing_summary"]["review_recommended"] is False


@pytest.mark.asyncio
async def test_plan_insert_asset_slot_marks_short_transcript_for_review():
    plan = await steps_mod._plan_insert_asset_slot(
        job_id="demo",
        insert_plan={"path": "insert.mp4"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "开头一句"},
            {"start_time": 2.1, "end_time": 6.5, "text_final": "后面很快就结束"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
    )

    assert plan is not None
    assert plan["timing_summary"]["review_recommended"] is True
    assert "建议确认" in plan["timing_summary"]["review_reason"]
