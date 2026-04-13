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


def test_shift_subtitles_for_insert_can_model_overlap_reduced_added_duration():
    shifted = steps_mod._shift_subtitles_for_insert(
        [
            {"start_time": 4.5, "end_time": 5.5, "text_final": "跨过插入点"},
            {"start_time": 6.0, "end_time": 7.0, "text_final": "后段"},
        ],
        insert_after_sec=5.0,
        insert_duration=0.84,
    )

    assert shifted[1]["start_time"] == 5.84
    assert shifted[1]["end_time"] == 6.34
    assert shifted[2]["start_time"] == 6.84
    assert shifted[2]["end_time"] == 7.84


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
async def test_map_subtitles_to_packaged_timeline_accounts_for_insert_transition_overlap(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "insert" in name:
            return DummyMeta(3.4)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 2.5, "end_time": 3.2, "text_final": "插入前"},
            {"start_time": 3.4, "end_time": 4.0, "text_final": "插入后"},
        ],
        {
            "insert": {
                "path": "insert.mp4",
                "insert_after_sec": 3.0,
                "insert_target_duration_sec": 1.2,
                "insert_transition_style": "soft_fade",
                "insert_transition_mode": "accented",
            },
        },
    )

    assert mapped[-1]["start_time"] == 4.242
    assert mapped[-1]["end_time"] == 4.842


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
async def test_map_editing_accents_to_packaged_timeline_focuses_insert_adjacent_accent_cluster(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "insert" in name:
            return DummyMeta(3.4)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_editing_accents_to_packaged_timeline(
        {
            "style": "smart_effect_rhythm",
            "emphasis_overlays": [
                {"text": "旧重点", "start_time": 2.9, "end_time": 3.2},
                {"text": "后重点", "start_time": 3.2, "end_time": 3.6},
            ],
            "sound_effects": [{"start_time": 3.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
        {
            "insert": {
                "path": "insert.mp4",
                "insert_after_sec": 3.0,
                "insert_target_duration_sec": 1.2,
                "insert_transition_style": "soft_fade",
                "insert_transition_mode": "accented",
                "insert_overlay_focus": "high",
                "insert_packaging_intent": "detail_support",
            },
        },
    )

    assert [item["text"] for item in mapped["emphasis_overlays"]] == ["旧重点"]
    assert mapped["emphasis_overlays"][0]["start_time"] == pytest.approx(2.901)
    assert mapped["sound_effects"][0]["start_time"] == pytest.approx(2.901)
    assert mapped["sound_effects"][0]["frequency"] == 1120


@pytest.mark.asyncio
async def test_map_editing_accents_to_packaged_timeline_drops_insert_adjacent_accents_for_protected_window(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "insert" in name:
            return DummyMeta(3.4)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_editing_accents_to_packaged_timeline(
        {
            "style": "smart_effect_rhythm",
            "emphasis_overlays": [
                {"text": "插入附近", "start_time": 2.95, "end_time": 3.25},
                {"text": "远处重点", "start_time": 4.8, "end_time": 5.2},
            ],
            "sound_effects": [
                {"start_time": 3.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04},
                {"start_time": 5.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04},
            ],
        },
        {
            "insert": {
                "path": "insert.mp4",
                "insert_after_sec": 3.0,
                "insert_target_duration_sec": 1.2,
                "insert_transition_style": "soft_fade",
                "insert_transition_mode": "protect",
                "insert_overlay_focus": "none",
                "insert_cta_protection": True,
            },
        },
    )

    assert [item["text"] for item in mapped["emphasis_overlays"]] == ["远处重点"]
    assert [item["start_time"] for item in mapped["sound_effects"]] == [6.038]


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_uses_effective_insert_duration(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "insert" in name:
            return DummyMeta(3.2)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 2.5, "end_time": 3.2, "text_final": "插入前"},
            {"start_time": 3.4, "end_time": 4.0, "text_final": "插入后"},
        ],
        {
            "insert": {
                "path": "insert.mp4",
                "insert_after_sec": 3.0,
                "insert_target_duration_sec": 1.2,
            },
        },
    )

    assert mapped[-1]["start_time"] == 4.6
    assert mapped[-1]["end_time"] == 5.2


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
async def test_map_subtitles_to_packaged_timeline_rewrites_copy_by_section_profile(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.0, "end_time": 2.2, "text_final": "先说结论，这个方案现在最稳。"},
            {"start_time": 2.4, "end_time": 4.8, "text_final": "这里开始讲参数细节，重点看尺寸和接口。"},
            {"start_time": 5.2, "end_time": 6.6, "text_final": "记得点赞收藏关注，我们下期再见。"},
        ],
        {
            "subtitles": {
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 2.3},
                    {"role": "detail", "start_sec": 2.3, "end_sec": 5.0},
                    {"role": "cta", "start_sec": 5.0, "end_sec": 6.8},
                ]
            }
        },
    )

    assert mapped[0]["text_final"] == "方案现在最稳。"
    assert mapped[0]["text_original_final"] == "先说结论，这个方案现在最稳。"
    assert mapped[0]["subtitle_copy_strategy"] == "hook_compact"
    assert mapped[1]["text_final"] == "尺寸和接口。"
    assert mapped[1]["subtitle_copy_strategy"] == "detail_focus"
    assert mapped[2]["text_final"] == "记得点赞收藏关注。"
    assert mapped[2]["subtitle_copy_strategy"] == "cta_compact"


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_resegments_copy_by_section(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.0, "end_time": 3.2, "text_final": "先说结论，这个方案现在最稳，后面再看怎么配。"},
            {"start_time": 3.4, "end_time": 7.4, "text_final": "这里开始讲参数细节，重点看尺寸和接口。"},
            {"start_time": 7.8, "end_time": 10.8, "text_final": "记得点赞收藏关注，我们下期再见。"},
        ],
        {
            "subtitles": {
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 3.3},
                    {"role": "detail", "start_sec": 3.3, "end_sec": 7.5},
                    {"role": "cta", "start_sec": 7.5, "end_sec": 11.0},
                ]
            }
        },
    )

    assert [item["text_final"] for item in mapped] == [
        "方案现在最稳。",
        "后面再看怎么配。",
        "参数细节。",
        "尺寸和接口。",
        "记得点赞收藏关注。",
        "下期再见。",
    ]
    assert mapped[0]["start_time"] == 0.0
    assert mapped[0]["end_time"] < mapped[1]["start_time"] + 1e-6 or mapped[0]["end_time"] == mapped[1]["start_time"]
    assert mapped[-1]["end_time"] == 10.8
    assert all(item["subtitle_unit_count"] == 2 for item in mapped)
    assert all(str(item["subtitle_copy_strategy"]).endswith("_resegmented") for item in mapped)
    assert [item["subtitle_unit_role"] for item in mapped] == [
        "lead",
        "support",
        "setup",
        "focus",
        "action",
        "signoff",
    ]


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


@pytest.mark.asyncio
async def test_resolve_packaging_trailing_gap_allowance_uses_outro_duration(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        assert str(path) == "outro.mp4"
        return DummyMeta(3.1)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    allowance = await steps_mod._resolve_packaging_trailing_gap_allowance(
        {"outro": {"path": "outro.mp4"}}
    )

    assert allowance == pytest.approx(3.1)


def test_collect_blocking_variant_sync_issues_flags_large_drift():
    issues = steps_mod._collect_blocking_variant_sync_issues(
        {
            "packaged": {
                "warning_codes": ["audio_video_duration_gap_large"],
                "audio_video_duration_gap_sec": 12.0,
            },
            "plain": {
                "warning_codes": ["subtitle_duration_gap_large"],
                "effective_duration_gap_sec": 0.8,
            },
        }
    )

    assert issues == ["packaged: audio_video_duration_gap_large"]


def test_build_variant_timeline_bundle_contains_variants_and_rules():
    keep_segments = [
        {"type": "keep", "start": 0.0, "end": 4.0},
        {"type": "keep", "start": 8.0, "end": 12.0},
    ]
    render_plan = {
        "editing_skill": {
            "key": "tutorial_standard",
            "transition_max_count": 2,
            "section_policy": {"detail": {"insert_allowed": True}},
        },
        "section_choreography": {
            "style_variant": "base",
            "editing_skill_key": "tutorial_standard",
            "sections": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 4.0, "transition_anchor_sec": 0.6, "cta_protection": False},
                {"index": 1, "role": "cta", "start_sec": 7.2, "end_sec": 8.0, "transition_anchor_sec": 7.3, "cta_protection": True},
            ],
            "summary": {"section_count": 2, "broll_section_count": 0, "cta_protected": True},
        },
        "timeline_analysis": {
            "hook_end_sec": 4.0,
            "cta_start_sec": 7.2,
            "semantic_sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 4.0},
                {"role": "cta", "start_sec": 7.2, "end_sec": 8.0},
            ],
            "section_directives": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 4.0, "overlay_weight": 1.3, "music_entry_allowed": False, "insert_allowed": False},
                {"role": "cta", "start_sec": 7.2, "end_sec": 8.0, "overlay_weight": -1.0, "music_entry_allowed": False, "insert_allowed": False},
            ],
            "section_actions": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 4.0, "transition_boost": 0.4, "transition_anchor_sec": 0.6, "broll_anchor_sec": 0.8},
                {"role": "cta", "start_sec": 7.2, "end_sec": 8.0, "transition_boost": 0.8, "transition_anchor_sec": 7.3, "broll_anchor_sec": 7.8},
            ],
        },
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
        editorial_analysis={
            "accepted_cuts": [
                {
                    "start": 4.0,
                    "end": 4.32,
                    "reason": "silence",
                    "boundary_keep_energy": 1.18,
                    "left_keep_role": "hook",
                    "right_keep_role": "cta",
                }
            ],
            "keep_energy_segments": [
                {
                    "start": 0.0,
                    "end": 4.0,
                    "keep_energy": 1.22,
                    "section_role": "hook",
                    "packaging_intent": "hook_focus",
                }
            ],
            "keep_energy_summary": {
                "count": 1,
                "high_energy_count": 1,
                "max_keep_energy": 1.22,
                "avg_keep_energy": 1.22,
            },
            "llm_cut_review": {
                "reviewed": True,
                "candidate_count": 3,
                "decision_count": 3,
                "restored_cut_count": 1,
                "cached": False,
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed",
                "summary": "恢复了 1 个展示型误删。",
            },
        },
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
    assert bundle["timeline_rules"]["editorial_analysis"]["keep_energy_summary"]["max_keep_energy"] == 1.22
    assert bundle["timeline_rules"]["timeline_analysis"]["hook_end_sec"] == 4.0
    assert bundle["timeline_rules"]["editing_skill"]["key"] == "tutorial_standard"
    assert bundle["timeline_rules"]["section_choreography"]["summary"]["cta_protected"] is True
    assert bundle["timeline_rules"]["timeline_analysis"]["section_directives"][0]["role"] == "hook"
    assert bundle["timeline_rules"]["timeline_analysis"]["section_actions"][0]["broll_anchor_sec"] == 0.8
    assert bundle["timeline_rules"]["diagnostics"]["high_energy_keeps"][0]["section_role"] == "hook"
    assert bundle["timeline_rules"]["diagnostics"]["high_risk_cuts"][0]["boundary_keep_energy"] == 1.18
    assert bundle["timeline_rules"]["diagnostics"]["llm_cut_review"]["restored_cut_count"] == 1
    assert bundle["timeline_rules"]["diagnostics"]["review_flags"]["review_recommended"] is True
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


def test_validate_variant_timeline_bundle_reports_semantic_section_order_issues():
    bundle = {
        "timeline_rules": {
            "timeline_analysis": {
                "semantic_sections": [
                    {"role": "hook", "start_sec": 2.0, "end_sec": 4.0},
                    {"role": "body", "start_sec": 1.0, "end_sec": 3.0},
                ]
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("semantic sections are not monotonic" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_reports_section_directive_order_issues():
    bundle = {
        "timeline_rules": {
            "timeline_analysis": {
                "section_directives": [
                    {"role": "detail", "start_sec": 4.0, "end_sec": 6.0},
                    {"role": "body", "start_sec": 3.0, "end_sec": 5.0},
                ]
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("section directives are not monotonic" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_reports_section_action_anchor_issues():
    bundle = {
        "timeline_rules": {
            "timeline_analysis": {
                "section_actions": [
                    {"role": "detail", "start_sec": 4.0, "end_sec": 6.0, "transition_anchor_sec": 4.5, "broll_anchor_sec": 7.0},
                ]
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("anchor outside section window" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_reports_missing_editing_skill_key():
    bundle = {
        "timeline_rules": {
            "editing_skill": {
                "transition_max_count": 2,
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("editing_skill: key missing" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_reports_bad_section_choreography_anchor():
    bundle = {
        "timeline_rules": {
            "section_choreography": {
                "sections": [
                    {"role": "detail", "start_sec": 4.0, "end_sec": 6.0, "transition_anchor_sec": 6.5},
                ]
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("section_choreography: section 1 has transition anchor outside section window" in issue for issue in result["issues"])


def test_validate_variant_timeline_bundle_reports_bad_diagnostics_payload():
    bundle = {
        "timeline_rules": {
            "diagnostics": {
                "keep_energy_summary": [],
                "high_energy_keeps": {},
                "high_risk_cuts": "bad",
                "llm_cut_review": [],
                "review_flags": [],
            }
        },
        "variants": {
            "packaged": {
                "media": {"duration_sec": 8.0},
                "subtitle_events": [],
                "quality_checks": {"status": "ok"},
            }
        },
    }

    result = steps_mod._validate_variant_timeline_bundle(bundle)

    assert result["status"] == "warning"
    assert any("diagnostics: keep_energy_summary is not a dict" in issue for issue in result["issues"])
    assert any("diagnostics: high_energy_keeps is not a list" in issue for issue in result["issues"])
    assert any("diagnostics: high_risk_cuts is not a list" in issue for issue in result["issues"])
    assert any("diagnostics: llm_cut_review is not a dict" in issue for issue in result["issues"])
    assert any("diagnostics: review_flags is not a dict" in issue for issue in result["issues"])


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
        timeline_analysis={"hook_end_sec": 5.4, "cta_start_sec": None},
    )

    assert plan is not None
    assert plan["enter_sec"] == 5.6
    assert plan["timing_summary"]["review_recommended"] is False


@pytest.mark.asyncio
async def test_plan_music_entry_uses_section_directives_to_avoid_hook():
    plan = await steps_mod._plan_music_entry(
        music_plan={"path": "bgm.mp3"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.8, "text_final": "先抛一个结论。"},
            {"start_time": 3.1, "end_time": 5.4, "text_final": "这里开始讲参数细节。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
        timeline_analysis={
            "section_directives": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 3.0, "music_entry_allowed": False},
                {"role": "detail", "start_sec": 3.0, "end_sec": 6.0, "music_entry_allowed": True},
            ]
        },
    )

    assert plan is not None
    assert plan["enter_sec"] == 5.4
    assert "安全音乐区间" in plan["entry_reason"]


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


@pytest.mark.asyncio
async def test_plan_insert_asset_slot_respects_hook_and_cta_windows():
    plan = await steps_mod._plan_insert_asset_slot(
        job_id="demo",
        insert_plan={"path": "insert.mp4"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 4.5, "text_final": "先把结论抛出来。"},
            {"start_time": 4.8, "end_time": 9.2, "text_final": "这里开始讲细节参数。"},
            {"start_time": 9.4, "end_time": 13.5, "text_final": "然后继续展开体验。"},
            {"start_time": 14.0, "end_time": 16.0, "text_final": "记得点赞收藏。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
        timeline_analysis={
            "hook_end_sec": 4.5,
            "cta_start_sec": 14.0,
            "semantic_sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 4.5},
                {"role": "detail", "start_sec": 4.8, "end_sec": 9.2},
                {"role": "body", "start_sec": 9.4, "end_sec": 13.5},
                {"role": "cta", "start_sec": 14.0, "end_sec": 16.0},
            ],
        },
        allow_llm=False,
    )

    assert plan is not None
    assert 8.0 <= plan["insert_after_sec"] < 14.0


@pytest.mark.asyncio
async def test_plan_insert_asset_slot_prefers_section_action_anchor():
    plan = await steps_mod._plan_insert_asset_slot(
        job_id="demo",
        insert_plan={"path": "insert.mp4"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 4.2, "text_final": "开头总结。"},
            {"start_time": 4.6, "end_time": 8.8, "text_final": "这里开始拆参数。"},
            {"start_time": 8.9, "end_time": 10.4, "text_final": "继续说明细节。"},
            {"start_time": 10.6, "end_time": 13.2, "text_final": "然后展开体验。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
        timeline_analysis={
            "hook_end_sec": 4.2,
            "section_actions": [
                {
                    "role": "detail",
                    "start_sec": 4.6,
                    "end_sec": 10.5,
                    "broll_allowed": True,
                    "broll_anchor_sec": 8.9,
                    "action_priority": 1.2,
                },
                {
                    "role": "body",
                    "start_sec": 10.6,
                    "end_sec": 13.2,
                    "broll_allowed": True,
                    "broll_anchor_sec": 12.6,
                    "action_priority": 0.8,
                },
            ],
        },
        allow_llm=False,
    )

    assert plan is not None
    assert plan["insert_after_sec"] == 8.8
    assert plan["insert_section_role"] == "detail"
    assert plan["broll_window"] == {
        "start_sec": 4.6,
        "end_sec": 10.5,
        "anchor_sec": 8.9,
        "priority": 1.2,
    }


@pytest.mark.asyncio
async def test_plan_insert_asset_slot_snaps_llm_choice_back_into_broll_window(monkeypatch):
    class FakeResponse:
        def as_json(self):
            return {"insert_after_sec": 12.9, "reason": "放在这里更自然。"}

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(steps_mod, "get_reasoning_provider", lambda: FakeProvider())

    plan = await steps_mod._plan_insert_asset_slot(
        job_id="demo",
        insert_plan={"path": "insert.mp4"},
        subtitle_items=[
            {"start_time": 0.0, "end_time": 4.2, "text_final": "开头总结。"},
            {"start_time": 4.6, "end_time": 8.8, "text_final": "这里开始拆参数。"},
            {"start_time": 8.9, "end_time": 10.4, "text_final": "继续说明细节。"},
            {"start_time": 10.6, "end_time": 13.2, "text_final": "然后展开体验。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
        timeline_analysis={
            "hook_end_sec": 4.2,
            "section_actions": [
                {
                    "index": 0,
                    "role": "detail",
                    "start_sec": 4.6,
                    "end_sec": 10.5,
                    "broll_allowed": True,
                    "broll_anchor_sec": 8.9,
                    "action_priority": 1.2,
                },
                {
                    "index": 1,
                    "role": "body",
                    "start_sec": 10.6,
                    "end_sec": 13.2,
                    "broll_allowed": True,
                    "broll_anchor_sec": 12.6,
                    "action_priority": 0.8,
                },
            ],
        },
        allow_llm=True,
    )

    assert plan is not None
    assert plan["insert_after_sec"] == 8.9
    assert plan["insert_section_role"] == "detail"


@pytest.mark.asyncio
async def test_plan_insert_asset_slot_retargets_insert_asset_for_detail_section():
    plan = await steps_mod._plan_insert_asset_slot(
        job_id="demo",
        insert_plan={
            "asset_id": "ambient-1",
            "path": "ambient.mp4",
            "original_name": "city_lifestyle_cutaway_insert.mp4",
            "candidate_assets": [
                {
                    "asset_id": "ambient-1",
                    "path": "ambient.mp4",
                    "original_name": "city_lifestyle_cutaway_insert.mp4",
                    "insert_archetype": "lifestyle_context",
                    "insert_motion_profile": "ambient_hold",
                    "insert_transition_style": "soft_fade",
                    "insert_target_duration_sec": 2.6,
                    "selection_score": 0.61,
                    "selection_reasons": [],
                },
                {
                    "asset_id": "demo-1",
                    "path": "demo.mp4",
                    "original_name": "screen_demo_step_insert.mp4",
                    "insert_archetype": "demo_step",
                    "insert_motion_profile": "guided_hold",
                    "insert_transition_style": "clean_hold",
                    "insert_target_duration_sec": 2.2,
                    "selection_score": 0.58,
                    "selection_reasons": [],
                },
            ],
        },
        subtitle_items=[
            {"start_time": 0.0, "end_time": 4.2, "text_final": "开头总结。"},
            {"start_time": 4.6, "end_time": 8.8, "text_final": "这里开始拆参数。"},
            {"start_time": 8.9, "end_time": 10.4, "text_final": "继续说明细节。"},
        ],
        content_profile={"preset_name": "screen_tutorial"},
        timeline_analysis={
            "editing_skill": {"content_kind": "tutorial"},
            "hook_end_sec": 4.2,
            "section_actions": [
                {
                    "index": 0,
                    "role": "detail",
                    "start_sec": 4.6,
                    "end_sec": 10.5,
                    "broll_allowed": True,
                    "broll_anchor_sec": 8.9,
                    "action_priority": 1.2,
                    "packaging_intent": "detail_support",
                },
            ],
        },
        allow_llm=False,
    )

    assert plan is not None
    assert plan["asset_id"] == "demo-1"
    assert plan["path"] == "demo.mp4"
    assert plan["insert_archetype"] == "demo_step"
    assert plan["insert_target_duration_sec"] == 2.2
