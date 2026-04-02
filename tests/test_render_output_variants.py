from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_offsets_transition_overlap(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.5, "end_time": 1.0, "text_final": "第一段"},
            {"start_time": 4.5, "end_time": 5.5, "text_final": "第二段"},
        ],
        {
            "editing_accents": {
                "transitions": {
                    "enabled": True,
                    "transition": "fade",
                    "duration_sec": 0.12,
                    "boundary_indexes": [0],
                }
            }
        },
        keep_segments=[
            {"type": "keep", "start": 0.0, "end": 4.0},
            {"type": "keep", "start": 8.0, "end": 12.0},
        ],
    )

    assert mapped[0]["start_time"] == 0.5
    assert mapped[0]["end_time"] == 1.0
    assert mapped[1]["start_time"] == pytest.approx(4.38)
    assert mapped[1]["end_time"] == pytest.approx(5.38)


@pytest.mark.asyncio
async def test_map_editing_accents_to_packaged_timeline_offsets_transition_overlap(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_editing_accents_to_packaged_timeline(
        {
            "style": "smart_effect_rhythm",
            "transitions": {
                "enabled": True,
                "transition": "fade",
                "duration_sec": 0.12,
                "boundary_indexes": [0],
            },
            "emphasis_overlays": [{"text": "重点", "start_time": 4.5, "end_time": 5.0}],
            "sound_effects": [{"start_time": 4.6, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
        {
            "editing_accents": {
                "transitions": {
                    "enabled": True,
                    "transition": "fade",
                    "duration_sec": 0.12,
                    "boundary_indexes": [0],
                }
            }
        },
        keep_segments=[
            {"type": "keep", "start": 0.0, "end": 4.0},
            {"type": "keep", "start": 8.0, "end": 12.0},
        ],
    )

    assert mapped["emphasis_overlays"][0]["start_time"] == pytest.approx(4.38)
    assert mapped["emphasis_overlays"][0]["end_time"] == pytest.approx(4.88)
    assert mapped["sound_effects"][0]["start_time"] == pytest.approx(4.48)


def test_build_variant_timeline_bundle_contains_variants_and_rules():
    keep_segments = [
        {"type": "keep", "start": 0.0, "end": 4.0},
        {"type": "keep", "start": 8.0, "end": 12.0},
    ]
    render_plan = {
        "intro": {"path": "intro.mp4"},
        "insert": {"path": "insert.mp4", "insert_after_sec": 3.8},
        "editing_accents": {
            "transitions": {
                "enabled": True,
                "transition": "fade",
                "duration_sec": 0.12,
                "boundary_indexes": [0],
            }
        },
    }

    bundle = steps_mod._build_variant_timeline_bundle(
        editorial_timeline_id="editorial-1",
        render_plan_timeline_id="render-1",
        keep_segments=keep_segments,
        render_plan=render_plan,
        variants={
            "plain": steps_mod._build_variant_timeline_entry(
                media_path=Path("plain.mp4"),
                srt_path=Path("plain.srt"),
                media_meta=SimpleNamespace(duration=8.0, width=1920, height=1080),
                subtitle_events=[{"start_time": 0.5, "end_time": 1.0, "text_final": "plain"}],
                transition_offsets=[],
                segments=keep_segments,
                quality_check={"status": "ok"},
            ),
            "packaged": steps_mod._build_variant_timeline_entry(
                media_path=Path("packaged.mp4"),
                srt_path=Path("packaged.srt"),
                media_meta=SimpleNamespace(duration=9.3, width=1920, height=1080),
                subtitle_events=[{"start_time": 2.0, "end_time": 2.5, "text_final": "packaged"}],
                transition_offsets=[(4.0, 0.12)],
                segments=keep_segments,
                quality_check={"status": "warning"},
            ),
        },
    )

    assert bundle["timeline_rules"]["editorial_timeline_id"] == "editorial-1"
    assert bundle["timeline_rules"]["render_plan_timeline_id"] == "render-1"
    assert bundle["timeline_rules"]["keep_segments"] == keep_segments
    assert bundle["timeline_rules"]["packaging"]["insert"]["insert_after_sec"] == 3.8
    assert set(bundle["variants"]) == {"plain", "packaged"}
    assert bundle["variants"]["packaged"]["media"]["path"] == "packaged.mp4"
    assert bundle["variants"]["packaged"]["subtitle_events"][0]["text"] == "packaged"


def test_build_variant_timeline_bundle_preserves_transition_overlap_metadata():
    keep_segments = [
        {"type": "keep", "start": 0.0, "end": 4.0},
        {"type": "keep", "start": 8.0, "end": 12.0},
    ]
    entry = steps_mod._build_variant_timeline_entry(
        media_path=Path("packaged.mp4"),
        srt_path=Path("packaged.srt"),
        media_meta=SimpleNamespace(duration=7.88, width=1920, height=1080),
        subtitle_events=[{"start_time": 4.38, "end_time": 5.38, "text_final": "第二段"}],
        overlay_events={
            "emphasis_overlays": [{"text": "重点", "start_time": 4.38, "end_time": 4.88}],
            "sound_effects": [{"start_time": 4.48, "duration_sec": 0.08}],
        },
        transition_offsets=[(4.0, 0.12)],
        segments=keep_segments,
        quality_check={"status": "warning", "warning_codes": ["subtitle_duration_gap_large"]},
    )

    assert entry["transitions"] == [{"boundary_time_sec": 4.0, "overlap_sec": 0.12}]
    assert entry["overlay_events"]["emphasis_overlays"][0]["start_time"] == 4.38
    assert entry["overlay_events"]["sound_effects"][0]["start_time"] == 4.48
    assert entry["quality_checks"]["warning_codes"] == ["subtitle_duration_gap_large"]


def test_validate_variant_timeline_bundle_reports_monotonicity_issues():
    bundle = {
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [
                    {"start_time": 1.0, "end_time": 2.0, "text": "one"},
                    {"start_time": 1.8, "end_time": 3.0, "text": "two"},
                    {"start_time": 7.5, "end_time": 8.6, "text": "three"},
                ],
                "quality_checks": {"status": "ok"},
            }
        }
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("not monotonic" in issue for issue in result["issues"])
    assert any("extends beyond media duration" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_returns_ok_for_ordered_events():
    bundle = {
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [
                    {"start_time": 1.0, "end_time": 2.0, "text": "one"},
                    {"start_time": 2.2, "end_time": 3.0, "text": "two"},
                ],
                "quality_checks": {"status": "ok"},
            }
        }
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result == {"status": "ok", "issues": []}


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
