from __future__ import annotations
from pathlib import Path

import pytest

from roughcut.media.render import (
    _apply_insert_clip,
    _apply_intro_outro,
    _apply_music_and_watermark,
    _build_choreographed_subtitle_items,
    _build_music_volume_expression,
    _build_master_audio_filter_chain,
    _build_overlay_only_editing_accents,
    _build_video_transform_editing_accents,
    _build_insert_packaging_filter_chain,
    _build_sound_effect_filters,
    _build_smart_effect_video_filters,
    _concat_prepared_bookends,
    _materialize_long_filter_complex_args,
    _resolve_transition_map,
    _resolve_effect_overlay_tokens,
    _resolve_insert_after_sec,
    _resolve_delivery_resolution,
    _resolve_video_encoder,
    _resolve_smart_effect_video_tokens,
    _stage_packaging_source,
    _should_apply_smart_effect_video_transforms,
    _video_encode_args,
    render_video,
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


def test_build_overlay_only_editing_accents_strips_transitions():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_punch",
            "transitions": {"enabled": True},
            "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
            "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08}],
        }
    )

    assert accents["style"] == "smart_effect_punch"
    assert "transitions" not in accents
    assert accents["emphasis_overlays"][0]["text"] == "重点"
    assert accents["sound_effects"][0]["duration_sec"] == 0.08


def test_ai_effect_tokens_are_more_aggressive_than_packaged_defaults():
    punch_overlay = _resolve_effect_overlay_tokens("smart_effect_punch")
    ai_overlay = _resolve_effect_overlay_tokens("smart_effect_commercial_ai")
    punch_video = _resolve_smart_effect_video_tokens("smart_effect_punch")
    ai_video = _resolve_smart_effect_video_tokens("smart_effect_commercial_ai")

    assert ai_overlay["fontsize"] > punch_overlay["fontsize"]
    assert ai_overlay["boxborderw"] > punch_overlay["boxborderw"]
    assert ai_video["max_full_transforms"] == 2
    assert ai_video["pre_scale"] < punch_video["pre_scale"]
    assert ai_video["zoom_peak"] < punch_video["zoom_peak"]
    assert ai_video["flash_color"] == "0xfff2cc@0.14"


def test_ai_effect_video_filters_limit_full_frame_transforms_to_primary_event():
    parts, output_label = _build_smart_effect_video_filters(
        "v0",
        {
            "style": "smart_effect_punch_ai",
            "emphasis_overlays": [
                {"text": "", "start_time": 1.0, "end_time": 1.4},
                {"text": "重点", "start_time": 4.0, "end_time": 4.8},
                {"text": "再看这里", "start_time": 9.0, "end_time": 9.9},
            ],
        },
        expected_width=1920,
        expected_height=1080,
    )

    assert output_label == "vsmart2"
    assert sum("zoompan=" in part for part in parts) == 2
    assert sum("drawbox=" in part for part in parts) == 3


def test_overlay_only_editing_accents_normalizes_legacy_rhythm_style():
    accents = _build_overlay_only_editing_accents({"style": "smart_effect_rhythm"})

    assert accents["style"] == "smart_effect_commercial"


def test_build_overlay_only_editing_accents_respects_section_choreography_protection():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_punch",
            "emphasis_overlays": [
                {"text": "开场重点", "start_time": 1.0, "end_time": 1.6},
                {"text": "结尾口播", "start_time": 7.4, "end_time": 7.9},
            ],
            "sound_effects": [
                {"start_time": 1.0, "duration_sec": 0.08},
                {"start_time": 7.5, "duration_sec": 0.08},
            ],
        },
        section_choreography={
            "sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 2.0, "overlay_focus": "high", "cta_protection": False},
                {"role": "cta", "start_sec": 7.0, "end_sec": 8.0, "overlay_focus": "none", "cta_protection": True},
            ]
        },
    )

    assert [item["text"] for item in accents["emphasis_overlays"]] == ["开场重点"]
    assert [item["start_time"] for item in accents["sound_effects"]] == [1.0]


def test_build_overlay_only_editing_accents_synthesizes_subtitle_unit_accents():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_punch",
            "emphasis_overlays": [],
            "sound_effects": [],
        },
        subtitle_items=[
            {
                "text_final": "主结论",
                "start_time": 0.4,
                "end_time": 1.0,
                "subtitle_unit_role": "lead",
            },
            {
                "text_final": "尺寸接口",
                "start_time": 2.2,
                "end_time": 2.9,
                "subtitle_unit_role": "focus",
            },
            {
                "text_final": "记得点赞收藏关注",
                "start_time": 7.2,
                "end_time": 7.8,
                "subtitle_unit_role": "action",
            },
        ],
        section_choreography={
            "sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 1.5, "overlay_focus": "high", "cta_protection": False},
                {"role": "detail", "start_sec": 2.0, "end_sec": 3.5, "overlay_focus": "high", "cta_protection": False},
                {"role": "cta", "start_sec": 7.0, "end_sec": 8.0, "overlay_focus": "none", "cta_protection": True},
            ]
        },
    )

    assert [item["text"] for item in accents["emphasis_overlays"]] == ["主结论", "尺寸接口"]
    assert [item["subtitle_unit_role"] for item in accents["emphasis_overlays"]] == ["lead", "focus"]
    assert [item["frequency"] for item in accents["sound_effects"]] == [1180, 1020]


def test_build_overlay_only_editing_accents_dedupes_against_existing_overlay_events():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_punch",
            "emphasis_overlays": [{"text": "已有重点", "start_time": 0.45, "end_time": 1.0}],
            "sound_effects": [{"start_time": 0.45, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
        subtitle_items=[
            {
                "text_final": "主结论",
                "start_time": 0.4,
                "end_time": 1.0,
                "subtitle_unit_role": "lead",
            },
        ],
        section_choreography={
            "sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 1.5, "overlay_focus": "high", "cta_protection": False},
            ]
        },
    )

    assert [item["text"] for item in accents["emphasis_overlays"]] == ["已有重点"]
    assert len(accents["sound_effects"]) == 1


def test_build_video_transform_editing_accents_synthesizes_lead_and_focus_units():
    accents = _build_video_transform_editing_accents(
        {"style": "smart_effect_punch", "emphasis_overlays": [], "sound_effects": []},
        subtitle_items=[
            {"text_final": "主结论", "start_time": 0.5, "end_time": 1.1, "subtitle_unit_role": "lead"},
            {"text_final": "尺寸接口", "start_time": 2.3, "end_time": 3.0, "subtitle_unit_role": "focus"},
            {"text_final": "下期再见", "start_time": 7.2, "end_time": 7.8, "subtitle_unit_role": "signoff"},
        ],
        section_choreography={
            "sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 1.5, "overlay_focus": "high", "cta_protection": False},
                {"role": "detail", "start_sec": 2.0, "end_sec": 3.5, "overlay_focus": "high", "cta_protection": False},
                {"role": "cta", "start_sec": 7.0, "end_sec": 8.0, "overlay_focus": "none", "cta_protection": True},
            ]
        },
    )

    assert [item["subtitle_unit_role"] for item in accents["emphasis_overlays"]] == ["lead", "focus"]
    assert [item["source"] for item in accents["emphasis_overlays"]] == ["subtitle_unit_video", "subtitle_unit_video"]
    assert accents["emphasis_overlays"][0]["transform_intensity"] > accents["emphasis_overlays"][1]["transform_intensity"]


def test_build_smart_effect_video_filters_scales_transform_strength_by_overlay_intensity():
    parts, _ = _build_smart_effect_video_filters(
        "v0",
        {
            "style": "smart_effect_punch",
            "emphasis_overlays": [
                {"text": "强重点", "start_time": 1.0, "end_time": 1.8, "transform_intensity": 1.25},
                {"text": "弱重点", "start_time": 4.0, "end_time": 4.8, "transform_intensity": 0.72},
            ],
        },
        expected_width=1920,
        expected_height=1080,
    )

    assert "0.15" in parts[0] or "0.150" in parts[0]
    assert "@0.2" in parts[0] or "@0.20" in parts[0]
    assert "0.0864" in parts[1] or "0.086" in parts[1] or "@0.115" in parts[1]


def test_resolve_transition_map_respects_section_choreography_modes():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 6.0, "end": 10.0},
        {"start": 12.0, "end": 16.0},
    ]

    resolved = _resolve_transition_map(
        keep_segments,
        {"enabled": True, "boundary_indexes": [0, 1], "duration_sec": 0.12},
        section_choreography={
            "sections": [
                {"role": "detail", "start_sec": 0.0, "end_sec": 5.0, "transition_anchor_sec": 4.0, "transition_mode": "accented"},
                {"role": "cta", "start_sec": 7.0, "end_sec": 9.0, "transition_anchor_sec": 8.0, "transition_mode": "protect"},
            ]
        },
    )

    assert resolved[0] > 0.12
    assert resolved[1] < 0.12


def test_resolve_transition_map_boosts_boundary_near_lead_unit():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 6.0, "end": 10.0},
        {"start": 12.0, "end": 16.0},
    ]

    resolved = _resolve_transition_map(
        keep_segments,
        {"enabled": True, "boundary_indexes": [0, 1], "duration_sec": 0.12},
        subtitle_items=[
            {"start_time": 3.82, "end_time": 4.28, "text_final": "主结论", "subtitle_unit_role": "lead"},
        ],
    )

    assert resolved[0] > resolved[1]
    assert resolved[0] > 0.12
    assert resolved[1] == pytest.approx(0.12)


def test_resolve_transition_map_tames_boundary_energy_in_protected_cta_context():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 6.0, "end": 10.0},
        {"start": 12.0, "end": 16.0},
    ]

    resolved = _resolve_transition_map(
        keep_segments,
        {"enabled": True, "boundary_indexes": [0, 1], "duration_sec": 0.12},
        subtitle_items=[
            {"start_time": 3.84, "end_time": 4.22, "text_final": "开场钩子", "subtitle_unit_role": "lead"},
            {"start_time": 7.82, "end_time": 8.24, "text_final": "记得点赞收藏关注", "subtitle_unit_role": "lead"},
        ],
        section_choreography={
            "sections": [
                {
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                    "transition_anchor_sec": 4.0,
                    "transition_mode": "accented",
                    "packaging_intent": "hook_focus",
                },
                {
                    "role": "cta",
                    "start_sec": 7.4,
                    "end_sec": 8.6,
                    "transition_anchor_sec": 8.0,
                    "transition_mode": "protect",
                    "packaging_intent": "cta_protect",
                },
            ]
        },
    )

    assert resolved[0] > 0.16
    assert 1 not in resolved


def test_resolve_transition_map_applies_review_focus_transition_energy_bias():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 6.0, "end": 10.0},
        {"start": 12.0, "end": 16.0},
    ]

    baseline = _resolve_transition_map(
        keep_segments,
        {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
        section_choreography={
            "sections": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                    "transition_anchor_sec": 4.0,
                    "transition_mode": "accented",
                    "transition_energy_bias": 0.0,
                },
            ]
        },
    )
    focused = _resolve_transition_map(
        keep_segments,
        {"enabled": True, "boundary_indexes": [0], "duration_sec": 0.12},
        section_choreography={
            "sections": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 5.0,
                    "transition_anchor_sec": 4.0,
                    "transition_mode": "accented",
                    "transition_energy_bias": -0.18,
                },
            ]
        },
    )

    assert focused[0] < baseline[0]


def test_build_overlay_only_editing_accents_prunes_density_in_review_focus_section():
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_commercial",
            "emphasis_overlays": [
                {"text": "开场一", "start_time": 0.2, "end_time": 0.6},
                {"text": "开场二", "start_time": 0.8, "end_time": 1.2},
                {"text": "中段", "start_time": 2.4, "end_time": 2.9},
            ],
            "sound_effects": [
                {"start_time": 0.2, "duration_sec": 0.1, "frequency": 1180, "volume": 0.05},
                {"start_time": 0.8, "duration_sec": 0.1, "frequency": 1180, "volume": 0.05},
                {"start_time": 2.4, "duration_sec": 0.1, "frequency": 1020, "volume": 0.05},
            ],
        },
        section_choreography={
            "sections": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 1.5, "overlay_focus": "high", "overlay_density_bias": -1},
                {"index": 1, "role": "detail", "start_sec": 2.0, "end_sec": 3.5, "overlay_focus": "high", "overlay_density_bias": 0},
            ]
        },
    )

    kept_hook_overlays = [item for item in accents["emphasis_overlays"] if float(item.get("start_time", 0.0) or 0.0) < 1.5]
    kept_hook_sounds = [item for item in accents["sound_effects"] if float(item.get("start_time", 0.0) or 0.0) < 1.5]
    assert len(kept_hook_overlays) == 1
    assert len(kept_hook_sounds) == 1
    assert any(float(item.get("start_time", 0.0) or 0.0) == pytest.approx(2.4) for item in accents["emphasis_overlays"])


def test_resolve_insert_after_sec_snaps_back_to_broll_anchor_when_outside_window():
    resolved = _resolve_insert_after_sec(
        13.8,
        source_duration=20.0,
        insert_plan={
            "broll_window": {
                "start_sec": 8.8,
                "end_sec": 10.4,
                "anchor_sec": 8.9,
            }
        },
    )

    assert resolved == 8.9


def test_resolve_insert_after_sec_clamps_window_to_source_duration():
    resolved = _resolve_insert_after_sec(
        13.8,
        source_duration=12.0,
        insert_plan={
            "broll_window": {
                "start_sec": 11.4,
                "end_sec": 13.8,
                "anchor_sec": 13.5,
            }
        },
    )

    assert resolved == 11.9


def test_build_insert_packaging_filter_chain_uses_transition_and_motion_profiles():
    video_filter, audio_filter = _build_insert_packaging_filter_chain(
        insert_plan={
            "insert_transition_style": "soft_fade",
            "insert_motion_profile": "quick_punch",
        },
        runtime_duration_sec=1.2,
    )

    assert "setpts=PTS/1.080" in video_filter
    assert "fade=t=in:st=0:d=0.129" in video_filter
    assert "fade=t=out:st=1.071:d=0.129" in video_filter
    assert "atempo=1.080" in audio_filter
    assert "afade=t=in:st=0:d=0.08" in audio_filter


def test_build_insert_packaging_filter_chain_scales_fade_by_transition_mode():
    accented_video_filter, _ = _build_insert_packaging_filter_chain(
        insert_plan={
            "insert_transition_style": "soft_fade",
            "insert_motion_profile": "balanced_hold",
            "insert_transition_mode": "accented",
        },
        runtime_duration_sec=1.2,
    )
    protected_video_filter, _ = _build_insert_packaging_filter_chain(
        insert_plan={
            "insert_transition_style": "soft_fade",
            "insert_motion_profile": "balanced_hold",
            "insert_transition_mode": "protect",
        },
        runtime_duration_sec=1.2,
    )

    assert "fade=t=in:st=0:d=0.179" in accented_video_filter
    assert "fade=t=in:st=0:d=0.081" in protected_video_filter


def test_build_choreographed_subtitle_items_applies_section_profiles_and_linger():
    choreographed = _build_choreographed_subtitle_items(
        [
            {"start_time": 0.2, "end_time": 0.9, "text_final": "开场句"},
            {"start_time": 1.3, "end_time": 1.9, "text_final": "细节句"},
            {"start_time": 3.0, "end_time": 3.6, "text_final": "收尾 CTA"},
        ],
        subtitles_plan={
            "default_linger_sec": 0.04,
            "timing_guard_sec": 0.07,
            "section_profiles": [
                {
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 1.2,
                    "style_name": "teaser_glow",
                    "motion_style": "motion_pop",
                    "margin_v_delta": 0,
                    "linger_sec": 0.12,
                    "guard_sec": 0.04,
                },
                {
                    "role": "detail",
                    "start_sec": 1.2,
                    "end_sec": 2.4,
                    "style_name": "keyword_highlight",
                    "motion_style": "motion_ripple",
                    "margin_v_delta": 6,
                    "linger_sec": 0.08,
                    "guard_sec": 0.05,
                },
                {
                    "role": "cta",
                    "start_sec": 2.8,
                    "end_sec": 4.0,
                    "style_name": "white_minimal",
                    "motion_style": "motion_static",
                    "margin_v_delta": 18,
                    "linger_sec": 0.0,
                    "guard_sec": 0.08,
                },
            ],
        },
    )

    assert choreographed[0]["style_name"] == "teaser_glow"
    assert choreographed[0]["motion_style"] == "motion_pop"
    assert choreographed[0]["end_time"] == pytest.approx(1.02)
    assert choreographed[1]["style_name"] == "keyword_highlight"
    assert choreographed[1]["margin_v_delta"] == 6
    assert choreographed[1]["end_time"] == pytest.approx(1.98)
    assert choreographed[2]["style_name"] == "white_minimal"
    assert choreographed[2]["end_time"] == 3.6


def test_build_choreographed_subtitle_items_applies_unit_level_motion_choreography():
    choreographed = _build_choreographed_subtitle_items(
        [
            {
                "start_time": 0.0,
                "end_time": 1.0,
                "text_final": "主结论",
                "subtitle_unit_role": "lead",
                "subtitle_unit_index": 0,
                "subtitle_unit_count": 2,
            },
            {
                "start_time": 1.0,
                "end_time": 1.7,
                "text_final": "支撑句",
                "subtitle_unit_role": "support",
                "subtitle_unit_index": 1,
                "subtitle_unit_count": 2,
            },
            {
                "start_time": 3.0,
                "end_time": 4.0,
                "text_final": "参数细节",
                "subtitle_unit_role": "setup",
                "subtitle_unit_index": 0,
                "subtitle_unit_count": 2,
            },
            {
                "start_time": 4.0,
                "end_time": 5.0,
                "text_final": "尺寸接口",
                "subtitle_unit_role": "focus",
                "subtitle_unit_index": 1,
                "subtitle_unit_count": 2,
            },
            {
                "start_time": 6.0,
                "end_time": 6.8,
                "text_final": "记得点赞收藏关注",
                "subtitle_unit_role": "action",
                "subtitle_unit_index": 0,
                "subtitle_unit_count": 2,
            },
            {
                "start_time": 6.8,
                "end_time": 7.6,
                "text_final": "下期再见",
                "subtitle_unit_role": "signoff",
                "subtitle_unit_index": 1,
                "subtitle_unit_count": 2,
            },
        ],
        subtitles_plan={
            "default_linger_sec": 0.04,
            "timing_guard_sec": 0.07,
            "section_profiles": [
                {
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 1.8,
                    "style_name": "teaser_glow",
                    "motion_style": "motion_pop",
                    "margin_v_delta": 0,
                    "linger_sec": 0.08,
                    "guard_sec": 0.05,
                },
                {
                    "role": "detail",
                    "start_sec": 2.8,
                    "end_sec": 5.2,
                    "style_name": "keyword_highlight",
                    "motion_style": "motion_ripple",
                    "margin_v_delta": 6,
                    "linger_sec": 0.06,
                    "guard_sec": 0.05,
                },
                {
                    "role": "cta",
                    "start_sec": 5.8,
                    "end_sec": 8.0,
                    "style_name": "white_minimal",
                    "motion_style": "motion_static",
                    "margin_v_delta": 18,
                    "linger_sec": 0.03,
                    "guard_sec": 0.08,
                },
            ],
        },
    )

    assert choreographed[0]["motion_style"] == "motion_strobe"
    assert choreographed[0]["style_name"] == "sale_banner"
    assert choreographed[1]["motion_style"] == "motion_slide"
    assert choreographed[1]["style_name"] == "coupon_green"
    assert choreographed[3]["motion_style"] == "motion_pop"
    assert choreographed[3]["style_name"] == "cyber_orange"
    assert choreographed[3]["margin_v_delta"] == 14
    assert choreographed[5]["motion_style"] == "motion_echo"
    assert choreographed[5]["style_name"] == "soft_shadow"


@pytest.mark.asyncio
async def test_apply_insert_clip_passes_trimmed_duration_into_prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_prepare_packaging_clip(source_path, output_path, *, expected_width, expected_height, trim_duration_sec=None):
        captured["trim_duration_sec"] = trim_duration_sec
        output_path.write_bytes(b"prepared")
        return output_path

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(render_mod, "_prepare_packaging_clip", fake_prepare_packaging_clip)
    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0 if "source" in str(path) else 3.4)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await _apply_insert_clip(
        source,
        insert_plan={
            "path": str(tmp_path / "insert.mp4"),
            "insert_after_sec": 4.2,
            "insert_target_duration_sec": 1.2,
        },
        expected_width=1080,
        expected_height=1920,
        output_path=output,
        debug_dir=None,
    )

    assert captured["trim_duration_sec"] == 1.2


@pytest.mark.asyncio
async def test_apply_insert_clip_writes_transition_and_motion_filters_into_ffmpeg_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_prepare_packaging_clip(source_path, output_path, *, expected_width, expected_height, trim_duration_sec=None):
        captured["trim_duration_sec"] = trim_duration_sec
        output_path.write_bytes(b"prepared")
        return output_path

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd

        class Result:
            returncode = 0
            stderr = ""

        return Result()

    monkeypatch.setattr(render_mod, "_prepare_packaging_clip", fake_prepare_packaging_clip)
    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0 if "source" in str(path) else 3.4)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await _apply_insert_clip(
        source,
        insert_plan={
            "path": str(tmp_path / "insert.mp4"),
            "insert_after_sec": 4.2,
            "insert_target_duration_sec": 1.2,
            "insert_transition_style": "soft_fade",
            "insert_motion_profile": "quick_punch",
        },
        expected_width=1080,
        expected_height=1920,
        output_path=output,
        debug_dir=None,
    )

    assert captured["trim_duration_sec"] == 1.296
    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "setpts=PTS/1.080" in filter_complex
    assert "fade=t=in:st=0:d=0.129" in filter_complex
    assert "atempo=1.080" in filter_complex
    assert "xfade=transition=fade:duration=0.129:offset=4.071" in filter_complex
    assert "acrossfade=d=0.129" in filter_complex


def test_sound_effect_filters_do_not_normalize_down_main_audio():
    filters, output_label = _build_sound_effect_filters(
        "0:a",
        {
            "sound_effects": [
                {"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04},
                {"start_time": 2.5, "duration_sec": 0.08, "frequency": 840, "volume": 0.04},
            ]
        },
    )

    assert output_label == "amix1"
    assert sum("normalize=0" in part for part in filters) == 2


def test_video_encode_args_falls_back_to_nvenc_when_integrated_encoders_are_unavailable(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_qsv_available", lambda: False)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: True)
    monkeypatch.setattr(render_mod, "_amf_available", lambda: False)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_nvenc"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "h264_nvenc"]
    assert "-cq:v" in args


def test_video_encode_args_falls_back_to_cpu_when_nvenc_unavailable(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_qsv_available", lambda: False)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: False)
    monkeypatch.setattr(render_mod, "_amf_available", lambda: False)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "libx264"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "libx264"]
    assert "-crf" in args


def test_video_encode_args_supports_explicit_qsv(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_qsv_available", lambda: True)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "h264_qsv")
    monkeypatch.setattr(render_mod.get_settings(), "render_crf", 19)

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_qsv"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "h264_qsv"]
    assert "-global_quality" in args
    assert "nv12" in args


def test_video_encode_args_supports_explicit_amf(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_amf_available", lambda: True)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "h264_amf")
    monkeypatch.setattr(render_mod.get_settings(), "render_crf", 19)

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_amf"
    args = _video_encode_args()
    assert args[:2] == ["-c:v", "h264_amf"]
    assert "-rc" in args
    assert "cqp" in args
    assert "-qp_i" in args


def test_video_encode_args_auto_prefers_qsv_over_other_hardware(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_qsv_available", lambda: True)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: True)
    monkeypatch.setattr(render_mod, "_amf_available", lambda: True)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_qsv"


def test_video_encode_args_auto_prefers_amf_before_nvenc(monkeypatch: pytest.MonkeyPatch):
    import roughcut.media.render as render_mod

    render_mod._nvenc_available.cache_clear()
    render_mod._qsv_available.cache_clear()
    render_mod._amf_available.cache_clear()
    render_mod._nvidia_device_available.cache_clear()
    render_mod._intel_device_available.cache_clear()
    render_mod._amd_device_available.cache_clear()
    render_mod._host_graphics_adapter_text.cache_clear()
    render_mod._ffmpeg_encoder_available.cache_clear()
    monkeypatch.setattr(render_mod, "_qsv_available", lambda: False)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: False)
    monkeypatch.setattr(render_mod, "_amf_available", lambda: True)
    monkeypatch.setattr(render_mod.get_settings(), "render_video_encoder", "auto")

    assert _resolve_video_encoder(prefer_hardware=True) == "h264_amf"


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


def test_materialize_long_filter_complex_args_uses_script_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    monkeypatch.setattr(render_mod, "tempfile", type("TmpModule", (), {"gettempdir": staticmethod(lambda: str(tmp_path))}))
    monkeypatch.setattr(render_mod.os, "name", "nt")
    monkeypatch.setattr(render_mod, "_WINDOWS_CMD_SOFT_LIMIT", 32)

    cmd = [
        "ffmpeg",
        "-i",
        "input.mp4",
        "-filter_complex",
        "[0:v]trim=start=0:end=10,setpts=PTS-STARTPTS[v0];" * 8,
        "-map",
        "[v0]",
        "out.mp4",
    ]

    rewritten, temp_files = _materialize_long_filter_complex_args(cmd)

    assert "-filter_complex_script" in rewritten
    assert "-filter_complex" not in rewritten
    assert len(temp_files) == 1
    assert temp_files[0].exists()
    assert temp_files[0].read_text(encoding="utf-8").startswith("[0:v]trim=")


def test_build_master_audio_filter_chain_applies_declipping_limiter_and_target_peak():
    chain = _build_master_audio_filter_chain(
        input_label="ain",
        voice_processing={"noise_reduction": True},
        loudness={"target_lufs": -16.0, "peak_limit": -2.0, "lra": 10.0},
        output_label="aout",
        allow_noise_reduction=True,
        include_declipping=True,
        include_async_resample=True,
    )

    assert chain.startswith("[ain]")
    assert "adeclip" in chain
    assert "anlmdn" in chain
    assert "loudnorm=I=-16.0:TP=-2.0:LRA=10.0:linear=true" in chain
    assert "alimiter=limit=" in chain
    assert chain.endswith("[aout]")


def test_stage_packaging_source_keeps_same_drive_inputs(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    staged = _stage_packaging_source(source, tmp_path)
    assert staged == source


@pytest.mark.asyncio
async def test_concat_prepared_bookends_prefers_stream_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    class Result:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd
        Path(cmd[-1]).write_bytes(b"video")
        return Result()

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 4.0)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)

    intro = tmp_path / "intro.mp4"
    body = tmp_path / "body.mp4"
    outro = tmp_path / "outro.mp4"
    for path in (intro, body, outro):
        path.write_bytes(b"video")

    output = tmp_path / "combined.mp4"
    copied = await _concat_prepared_bookends([intro, body, outro], output_path=output, debug_dir=None)

    assert copied is True
    assert captured["cmd"][0:7] == ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i"]
    assert captured["cmd"][-2:] == ["-c", "copy"] or captured["cmd"][-3:-1] == ["-c", "copy"]


@pytest.mark.asyncio
async def test_apply_intro_outro_normalizes_all_inputs_before_concat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    captured: dict[str, object] = {}

    async def fake_prepare_packaging_clip(source_path, output_path, *, expected_width, expected_height, trim_duration_sec=None):
        output_path.write_bytes(b"prepared")
        return output_path

    class Result:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        captured["cmd"] = cmd
        output = Path(cmd[-1])
        output.write_bytes(b"video")
        return Result()

    monkeypatch.setattr(render_mod, "_prepare_packaging_clip", fake_prepare_packaging_clip)
    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 8.0)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)

    source = tmp_path / "body.mp4"
    intro = tmp_path / "intro.mp4"
    outro = tmp_path / "outro.mp4"
    source.write_bytes(b"video")
    intro.write_bytes(b"video")
    outro.write_bytes(b"video")
    output = tmp_path / "packaged.mp4"

    await _apply_intro_outro(
        source,
        intro_plan={"path": str(intro)},
        outro_plan={"path": str(outro)},
        expected_width=1920,
        expected_height=1080,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "setsar=1,format=yuv420p[v0]" in filter_complex
    assert "setsar=1,format=yuv420p[v1]" in filter_complex
    assert "setsar=1,format=yuv420p[v2]" in filter_complex
    assert "aformat=sample_rates=48000:channel_layouts=stereo,asetpts=N/SR/TB[a0]" in filter_complex
    assert "concat=n=3:v=1:a=1[vout][aout]" in filter_complex


@pytest.mark.asyncio
async def test_apply_music_and_watermark_ducks_music_under_voice(
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
    music = tmp_path / "music.mp3"
    music.write_bytes(b"audio")
    output = tmp_path / "out.mp4"

    await _apply_music_and_watermark(
        source,
        music_plan={
            "path": str(music),
            "loop_mode": "loop_single",
            "volume": 0.12,
            "enter_sec": 0.0,
        },
        watermark_plan=None,
        expected_width=736,
        expected_height=992,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "highpass=f=120" in filter_complex
    assert "lowpass=f=6000" in filter_complex
    assert "sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1" in filter_complex
    assert "amix=inputs=2:duration=first:dropout_transition=2" in filter_complex


def test_build_music_volume_expression_embeds_duck_windows():
    expr = _build_music_volume_expression(
        base_volume=0.12,
        duck_windows=[
            {"start_sec": 4.5, "end_sec": 5.8, "target_volume": 0.042},
            {"start_sec": 9.0, "end_sec": 9.6, "target_volume": 0.06},
        ],
    )

    assert "if(between(t\\,4.500\\,5.800)\\,0.042" in expr
    assert "if(between(t\\,9.000\\,9.600)\\,0.060" in expr


@pytest.mark.asyncio
async def test_apply_music_and_watermark_applies_insert_ducking_and_entry_fade(
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
    music = tmp_path / "music.mp3"
    music.write_bytes(b"audio")
    output = tmp_path / "out.mp4"

    await _apply_music_and_watermark(
        source,
        music_plan={
            "path": str(music),
            "loop_mode": "loop_single",
            "volume": 0.12,
            "enter_sec": 4.8,
            "music_entry_fade_sec": 0.42,
            "duck_windows": [
                {"start_sec": 4.842, "end_sec": 6.162, "target_volume": 0.042},
            ],
        },
        watermark_plan=None,
        expected_width=736,
        expected_height=992,
        output_path=output,
        debug_dir=None,
    )

    filter_complex = captured["cmd"][captured["cmd"].index("-filter_complex") + 1]
    assert "volume='if(between(t\\,4.842\\,6.162)\\,0.042\\,0.120)'" in filter_complex
    assert "adelay=4800|4800" in filter_complex
    assert "afade=t=in:st=4.800:d=0.420" in filter_complex


@pytest.mark.asyncio
async def test_render_video_keeps_subtitle_and_effect_overlays_in_single_pass_when_packaging_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    commands: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return DummyResult()

    async def fake_detect_video_rotation(path: Path) -> int:
        return 0

    async def fake_normalize_rendered_output(*args, **kwargs):
        return None

    async def fake_resolve_subtitle_margin_with_avatar(**kwargs):
        return None

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(
        render_mod,
        "_probe_video_stream",
        lambda path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
        },
    )
    monkeypatch.setattr(render_mod, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_mod, "_write_debug_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_resolve_subtitle_margin_with_avatar", fake_resolve_subtitle_margin_with_avatar)

    from roughcut.media import rotation as rotation_mod

    monkeypatch.setattr(rotation_mod, "detect_video_rotation", fake_detect_video_rotation)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await render_video(
        source_path=source,
        render_plan={
            "voice_processing": {},
            "loudness": {},
            "delivery": {"resolution_mode": "source"},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {
                "style": "smart_effect_punch",
                "transitions": {"enabled": False, "boundary_indexes": []},
                "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
                "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
            },
            "avatar_commentary": None,
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 4.0}]},
        output_path=output,
        subtitle_items=[{"start_time": 0.2, "end_time": 1.2, "text_final": "字幕"}],
        overlay_editing_accents={
            "style": "smart_effect_punch",
            "emphasis_overlays": [{"text": "重点", "start_time": 1.0, "end_time": 1.6}],
            "sound_effects": [{"start_time": 1.0, "duration_sec": 0.08, "frequency": 960, "volume": 0.04}],
        },
    )

    assert len(commands) == 1
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]

    assert "zoompan=" in filter_complex
    assert "subtitles='" in filter_complex
    assert "drawtext=" in filter_complex


@pytest.mark.asyncio
async def test_render_video_uses_subtitle_units_to_drive_base_smart_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    commands: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return DummyResult()

    async def fake_detect_video_rotation(path: Path) -> int:
        return 0

    async def fake_normalize_rendered_output(*args, **kwargs):
        return None

    async def fake_resolve_subtitle_margin_with_avatar(**kwargs):
        return None

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(
        render_mod,
        "_probe_video_stream",
        lambda path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
        },
    )
    monkeypatch.setattr(render_mod, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_mod, "_write_debug_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_resolve_subtitle_margin_with_avatar", fake_resolve_subtitle_margin_with_avatar)

    from roughcut.media import rotation as rotation_mod

    monkeypatch.setattr(rotation_mod, "detect_video_rotation", fake_detect_video_rotation)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await render_video(
        source_path=source,
        render_plan={
            "voice_processing": {},
            "loudness": {},
            "delivery": {"resolution_mode": "source"},
            "subtitles": {
                "style": "bold_yellow_outline",
                "motion_style": "motion_static",
                "section_profiles": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 1.5, "style_name": "teaser_glow", "motion_style": "motion_pop", "margin_v_delta": 0, "linger_sec": 0.08, "guard_sec": 0.05},
                    {"role": "detail", "start_sec": 1.5, "end_sec": 3.5, "style_name": "keyword_highlight", "motion_style": "motion_ripple", "margin_v_delta": 6, "linger_sec": 0.06, "guard_sec": 0.05},
                ],
            },
            "editing_accents": {
                "style": "smart_effect_punch",
                "transitions": {"enabled": False, "boundary_indexes": []},
                "emphasis_overlays": [],
                "sound_effects": [],
            },
            "section_choreography": {
                "sections": [
                    {"role": "hook", "start_sec": 0.0, "end_sec": 1.5, "overlay_focus": "high", "cta_protection": False},
                    {"role": "detail", "start_sec": 1.5, "end_sec": 3.5, "overlay_focus": "high", "cta_protection": False},
                ]
            },
            "avatar_commentary": None,
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 4.0}]},
        output_path=output,
        subtitle_items=[
            {"start_time": 0.2, "end_time": 1.0, "text_final": "主结论", "subtitle_unit_role": "lead"},
            {"start_time": 2.0, "end_time": 2.8, "text_final": "尺寸接口", "subtitle_unit_role": "focus"},
        ],
        overlay_editing_accents={"style": "smart_effect_punch", "emphasis_overlays": [], "sound_effects": []},
    )

    base_filter = commands[0][commands[0].index("-filter_complex") + 1]
    assert "drawbox=" in base_filter


@pytest.mark.asyncio
async def test_render_video_keeps_overlay_work_in_base_pass_when_packaging_is_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import roughcut.media.render as render_mod

    commands: list[list[str]] = []

    class DummyResult:
        returncode = 0
        stderr = ""

    async def fake_run_process(cmd: list[str], timeout: int):
        commands.append(cmd)
        Path(cmd[-1]).write_bytes(b"video")
        return DummyResult()

    async def fake_detect_video_rotation(path: Path) -> int:
        return 0

    async def fake_normalize_rendered_output(*args, **kwargs):
        return None

    async def fake_resolve_subtitle_margin_with_avatar(**kwargs):
        return None

    monkeypatch.setattr(render_mod, "_run_process", fake_run_process)
    monkeypatch.setattr(render_mod, "_probe_duration", lambda path: 12.0)
    monkeypatch.setattr(
        render_mod,
        "_probe_video_stream",
        lambda path: {
            "width": 1920,
            "height": 1080,
            "display_width": 1920,
            "display_height": 1080,
            "rotation_raw": 0,
            "rotation_cw": 0,
        },
    )
    monkeypatch.setattr(render_mod, "_normalize_rendered_output", fake_normalize_rendered_output)
    monkeypatch.setattr(render_mod, "_write_debug_json", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_debug_text", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_write_process_debug", lambda *args, **kwargs: None)
    monkeypatch.setattr(render_mod, "_resolve_subtitle_margin_with_avatar", fake_resolve_subtitle_margin_with_avatar)
    monkeypatch.setattr(render_mod, "_nvenc_available", lambda: False)

    from roughcut.media import rotation as rotation_mod

    monkeypatch.setattr(rotation_mod, "detect_video_rotation", fake_detect_video_rotation)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    output = tmp_path / "out.mp4"

    await render_video(
        source_path=source,
        render_plan={
            "voice_processing": {},
            "loudness": {},
            "delivery": {"resolution_mode": "source"},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {
                "style": "smart_effect_rhythm",
                "transitions": {"enabled": False, "boundary_indexes": []},
                "emphasis_overlays": [],
                "sound_effects": [],
            },
            "avatar_commentary": None,
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
        },
        editorial_timeline={"segments": [{"type": "keep", "start": 0.0, "end": 4.0}]},
        output_path=output,
        subtitle_items=[{"start_time": 0.2, "end_time": 1.2, "text_final": "字幕"}],
        overlay_editing_accents={"style": "smart_effect_rhythm", "emphasis_overlays": [], "sound_effects": []},
    )

    assert len(commands) == 1
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "subtitles='" in filter_complex
    assert commands[0][commands[0].index("-c:a") + 1] == "aac"
