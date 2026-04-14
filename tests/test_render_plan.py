from __future__ import annotations

import uuid

from roughcut.edit.render_plan import (
    build_ai_effect_render_plan,
    build_avatar_render_plan,
    build_plain_render_plan,
    build_render_plan,
    build_smart_editing_accents,
)


def test_build_render_plan_defaults():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(editorial_timeline_id=timeline_id)

    assert plan["editorial_timeline_id"] == str(timeline_id)
    assert plan["workflow_preset"] == "unboxing_standard"
    assert plan["loudness"]["target_lufs"] == -16.0
    assert plan["loudness"]["peak_limit"] == -2.0
    assert plan["voice_processing"]["noise_reduction"] is True
    assert plan["subtitles"]["style"] == "bold_yellow_outline"
    assert plan["cover"]["variant_count"] == 5
    assert plan["intro"] is None
    assert plan["outro"] is None
    assert plan["insert"] is None
    assert plan["watermark"] is None
    assert plan["music"] is None
    assert plan["timeline_analysis"] == {}
    assert plan["editing_skill"] == {}
    assert plan["section_choreography"] == {}
    assert plan["creative_profile"] is None
    assert plan["ai_director"] is None
    assert plan["avatar_commentary"] is None
    assert plan["editing_accents"]["style"] == "smart_effect_commercial"
    assert plan["editing_accents"]["emphasis_overlays"] == []


def test_build_render_plan_custom():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(
        editorial_timeline_id=timeline_id,
        workflow_preset="unboxing_upgrade",
        target_lufs=-16.0,
        noise_reduction=False,
        subtitle_style="white_minimal",
        cover_style="tactical_neon",
        creative_profile={"workflow_mode": "standard_edit", "enhancement_modes": ["ai_director"]},
        ai_director_plan={"voiceover_segments": [{"segment_id": "director_hook"}]},
        avatar_commentary_plan={"segments": [{"segment_id": "avatar_1"}]},
    )
    assert plan["workflow_preset"] == "unboxing_standard"
    assert plan["loudness"]["target_lufs"] == -16.0
    assert plan["voice_processing"]["noise_reduction"] is False
    assert plan["subtitles"]["style"] == "white_minimal"
    assert plan["cover"]["style"] == "tactical_neon"
    assert plan["creative_profile"]["enhancement_modes"] == ["ai_director"]
    assert plan["ai_director"]["voiceover_segments"][0]["segment_id"] == "director_hook"
    assert plan["avatar_commentary"]["segments"][0]["segment_id"] == "avatar_1"


def test_build_render_plan_emits_section_choreography():
    timeline_id = uuid.uuid4()
    plan = build_render_plan(
        editorial_timeline_id=timeline_id,
        timeline_analysis={
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "overlay_weight": 1.3},
                {"index": 1, "role": "cta", "start_sec": 7.0, "end_sec": 8.0, "overlay_weight": -1.0},
            ],
            "section_actions": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "trim_intensity": "balanced", "packaging_intent": "hook_focus", "transition_anchor_sec": 0.6, "broll_allowed": False, "broll_anchor_sec": 0.4},
                {"index": 1, "role": "cta", "start_sec": 7.0, "end_sec": 8.0, "trim_intensity": "preserve", "packaging_intent": "cta_protect", "transition_anchor_sec": 7.2, "broll_allowed": False, "broll_anchor_sec": 7.8},
            ],
        },
        editing_skill={"key": "commentary_focus"},
    )

    assert plan["section_choreography"]["editing_skill_key"] == "commentary_focus"
    assert plan["section_choreography"]["sections"][0]["transition_mode"] == "restrained"
    assert plan["section_choreography"]["sections"][1]["cta_protection"] is True


def test_build_render_plan_applies_review_focus_bias_to_section_choreography():
    plan = build_render_plan(
        uuid.uuid4(),
        timeline_analysis={
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "overlay_weight": 1.3},
                {"index": 1, "role": "detail", "start_sec": 2.0, "end_sec": 5.0, "overlay_weight": 1.0},
            ],
            "section_actions": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "trim_intensity": "balanced", "packaging_intent": "hook_focus", "transition_boost": 0.8, "transition_anchor_sec": 0.6, "broll_allowed": False, "broll_anchor_sec": 0.4},
                {"index": 1, "role": "detail", "start_sec": 2.0, "end_sec": 5.0, "trim_intensity": "balanced", "packaging_intent": "detail_support", "transition_boost": 1.2, "transition_anchor_sec": 2.5, "broll_allowed": True, "broll_anchor_sec": 3.0},
            ],
        },
        editing_skill={"key": "commentary_focus", "review_focus": "hook_boundary"},
    )

    assert plan["section_choreography"]["review_focus"] == "hook_boundary"
    assert plan["section_choreography"]["sections"][0]["review_focus_mode"] == "hook_boundary_smooth"
    assert plan["section_choreography"]["sections"][0]["transition_energy_bias"] < 0.0
    assert plan["section_choreography"]["sections"][0]["overlay_density_bias"] == -1
    assert plan["section_choreography"]["sections"][1]["review_focus_mode"] == ""


def test_build_render_plan_binds_insert_to_section_choreography():
    plan = build_render_plan(
        uuid.uuid4(),
        workflow_preset="tutorial_standard",
        insert={
            "path": "insert.mp4",
            "insert_after_sec": 5.1,
            "insert_section_index": 1,
        },
        timeline_analysis={
            "section_actions": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 3.0,
                    "trim_intensity": "balanced",
                    "packaging_intent": "hook_focus",
                    "transition_boost": 0.4,
                    "transition_anchor_sec": 0.5,
                    "broll_allowed": False,
                    "broll_anchor_sec": 0.6,
                },
                {
                    "index": 1,
                    "role": "detail",
                    "start_sec": 4.0,
                    "end_sec": 7.0,
                    "trim_intensity": "balanced",
                    "packaging_intent": "detail_support",
                    "transition_boost": 1.2,
                    "transition_anchor_sec": 4.2,
                    "broll_allowed": True,
                    "broll_anchor_sec": 5.1,
                    "creative_preferences": ["突出近景特写", "突出差异对比"],
                    "creative_rationale": "细节段优先保留近景和做工镜头；细节段优先承载版本差异",
                },
            ],
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 3.0, "overlay_weight": 1.3},
                {"index": 1, "role": "detail", "start_sec": 4.0, "end_sec": 7.0, "overlay_weight": 1.0, "creative_preferences": ["突出近景特写", "突出差异对比"]},
            ],
        },
        editing_skill={"key": "tutorial_standard", "creative_preferences": ["closeup_focus", "comparison_focus"]},
    )

    assert plan["insert"]["insert_transition_mode"] == "accented"
    assert plan["insert"]["insert_packaging_intent"] == "detail_support"
    assert plan["insert"]["insert_overlay_focus"] == "high"
    assert "突出近景特写" in plan["insert"]["insert_creative_preferences"]
    assert "版本差异" in plan["insert"]["insert_creative_rationale"]


def test_build_render_plan_exposes_creative_preference_rationale_in_section_choreography():
    plan = build_render_plan(
        uuid.uuid4(),
        timeline_analysis={
            "section_directives": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "overlay_weight": 1.3,
                    "creative_preferences": ["先给结论", "节奏偏快"],
                    "creative_rationale": "开头优先前置结论；开头节奏收紧，尽快给重点",
                },
            ],
            "section_actions": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "trim_intensity": "tight",
                    "packaging_intent": "hook_focus",
                    "transition_boost": 0.8,
                    "transition_anchor_sec": 0.6,
                    "broll_allowed": False,
                    "broll_anchor_sec": 0.4,
                    "creative_preferences": ["先给结论", "节奏偏快"],
                    "creative_rationale": "开头优先前置结论；开头节奏收紧，尽快给重点",
                },
            ],
        },
        editing_skill={"key": "unboxing_standard", "creative_preferences": ["conclusion_first", "fast_paced"]},
    )

    section = plan["section_choreography"]["sections"][0]
    assert "先给结论" in section["creative_preferences"]
    assert "开头优先前置结论" in section["creative_rationale"]
    assert plan["section_choreography"]["summary"]["creative_preference_count"] == 2


def test_build_render_plan_binds_music_to_section_and_insert_ducking():
    plan = build_render_plan(
        uuid.uuid4(),
        workflow_preset="tutorial_standard",
        insert={
            "path": "insert.mp4",
            "insert_after_sec": 5.1,
            "insert_target_duration_sec": 1.2,
            "insert_transition_style": "soft_fade",
            "insert_transition_mode": "accented",
            "insert_packaging_intent": "detail_support",
        },
        music={"path": "bgm.mp3", "enter_sec": 4.8, "volume": 0.12},
        timeline_analysis={
            "section_actions": [
                {
                    "index": 1,
                    "role": "detail",
                    "start_sec": 4.0,
                    "end_sec": 7.0,
                    "trim_intensity": "balanced",
                    "packaging_intent": "detail_support",
                    "transition_boost": 1.2,
                    "transition_anchor_sec": 4.2,
                    "broll_allowed": True,
                    "broll_anchor_sec": 5.1,
                },
            ],
            "section_directives": [
                {"index": 1, "role": "detail", "start_sec": 4.0, "end_sec": 7.0, "overlay_weight": 1.0},
            ],
        },
        editing_skill={"key": "tutorial_standard"},
    )

    assert plan["music"]["music_transition_mode"] == "accented"
    assert plan["music"]["music_entry_fade_sec"] == 0.42
    assert plan["music"]["duck_windows"][0]["target_volume"] == 0.42


def test_build_render_plan_binds_subtitles_to_section_choreography():
    plan = build_render_plan(
        uuid.uuid4(),
        workflow_preset="tutorial_standard",
        timeline_analysis={
            "section_actions": [
                {
                    "index": 0,
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 2.4,
                    "trim_intensity": "balanced",
                    "packaging_intent": "hook_focus",
                    "transition_boost": 0.8,
                    "transition_anchor_sec": 0.5,
                    "broll_allowed": False,
                    "broll_anchor_sec": 0.6,
                },
                {
                    "index": 1,
                    "role": "detail",
                    "start_sec": 2.4,
                    "end_sec": 5.8,
                    "trim_intensity": "balanced",
                    "packaging_intent": "detail_support",
                    "transition_boost": 1.2,
                    "transition_anchor_sec": 3.1,
                    "broll_allowed": True,
                    "broll_anchor_sec": 3.5,
                },
                {
                    "index": 2,
                    "role": "cta",
                    "start_sec": 8.0,
                    "end_sec": 9.0,
                    "trim_intensity": "preserve",
                    "packaging_intent": "cta_protect",
                    "transition_boost": 0.1,
                    "transition_anchor_sec": 8.1,
                    "broll_allowed": False,
                    "broll_anchor_sec": 8.2,
                },
            ],
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.4, "overlay_weight": 1.3},
                {"index": 1, "role": "detail", "start_sec": 2.4, "end_sec": 5.8, "overlay_weight": 1.0},
                {"index": 2, "role": "cta", "start_sec": 8.0, "end_sec": 9.0, "overlay_weight": -1.0},
            ],
        },
        editing_skill={"key": "tutorial_standard"},
    )

    profiles = plan["subtitles"]["section_profiles"]
    assert profiles[0]["style_name"] == "teaser_glow"
    assert profiles[0]["motion_style"] == "motion_pop"
    assert profiles[1]["style_name"] == "keyword_highlight"
    assert profiles[1]["motion_style"] == "motion_ripple"
    assert profiles[2]["style_name"] == "white_minimal"
    assert profiles[2]["margin_v_delta"] == 18


def test_build_smart_editing_accents_limits_count_and_prefers_strong_lines():
    keep_segments = [
        {"start": 0.0, "end": 4.0},
        {"start": 5.0, "end": 9.0},
        {"start": 11.0, "end": 15.0},
        {"start": 15.2, "end": 18.0},
    ]
    subtitle_items = [
        {"start_time": 1.0, "end_time": 2.4, "text_final": "这点一定要注意"},
        {"start_time": 9.8, "end_time": 11.0, "text_final": "直接上 PRO"},
        {"start_time": 18.5, "end_time": 19.5, "text_final": "普通描述一下"},
    ]

    accents = build_smart_editing_accents(
        keep_segments=keep_segments,
        subtitle_items=subtitle_items,
    )

    assert accents["transitions"]["enabled"] is True
    assert accents["transitions"]["boundary_indexes"] == [0, 1]
    assert len(accents["emphasis_overlays"]) == 2
    assert accents["emphasis_overlays"][0]["text"] == "这点一定要注意"
    assert accents["emphasis_overlays"][1]["text"] == "直接上PRO"
    assert len(accents["sound_effects"]) == 2


def test_build_smart_editing_accents_prefers_timeline_analysis_candidates():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 4.0},
            {"start": 5.0, "end": 9.0},
        ],
        subtitle_items=[
            {"start_time": 1.0, "end_time": 2.0, "text_final": "普通描述"},
        ],
        timeline_analysis={
            "emphasis_candidates": [
                {"text": "先说结论", "start_time": 0.8, "end_time": 1.8, "role": "hook", "score": 3.1},
            ]
        },
    )

    assert accents["emphasis_overlays"][0]["text"] == "先说结论"


def test_build_smart_editing_accents_respects_editing_skill_density():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
            {"start": 6.0, "end": 8.0},
        ],
        subtitle_items=[
            {"start_time": 0.2, "end_time": 1.2, "text_final": "这点非常关键"},
            {"start_time": 4.0, "end_time": 5.0, "text_final": "一定要看这里"},
        ],
        editing_skill={
            "transition_max_count": 1,
            "overlay_max_count": 1,
            "overlay_spacing_sec": 9.0,
        },
    )

    assert accents["transitions"]["boundary_indexes"] == [1]
    assert len(accents["emphasis_overlays"]) == 1


def test_build_smart_editing_accents_prefers_semantic_transition_boundary():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
            {"start": 6.0, "end": 8.0},
        ],
        subtitle_items=[],
        timeline_analysis={
            "semantic_sections": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 2.0},
                {"role": "detail", "start_sec": 4.0, "end_sec": 8.0},
            ]
        },
    )

    assert accents["transitions"]["boundary_indexes"] == [1]


def test_build_smart_editing_accents_uses_section_action_transition_boost():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
            {"start": 6.0, "end": 8.0},
        ],
        subtitle_items=[],
        timeline_analysis={
            "section_actions": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 2.0, "transition_boost": 0.2, "transition_anchor_sec": 0.5, "broll_anchor_sec": 0.5},
                {"role": "detail", "start_sec": 3.0, "end_sec": 5.0, "transition_boost": 1.8, "transition_anchor_sec": 4.0, "broll_anchor_sec": 3.8},
                {"role": "body", "start_sec": 6.0, "end_sec": 8.0, "transition_boost": 0.4, "transition_anchor_sec": 6.2, "broll_anchor_sec": 7.0},
            ]
        },
        editing_skill={"transition_max_count": 1},
    )

    assert accents["transitions"]["boundary_indexes"] == [1]


def test_build_smart_editing_accents_avoids_cta_overlay_window():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 4.0},
            {"start": 5.0, "end": 9.0},
        ],
        subtitle_items=[
            {"start_time": 1.2, "end_time": 2.2, "text_final": "这里是重点参数"},
            {"start_time": 7.2, "end_time": 8.2, "text_final": "记得点赞收藏"},
        ],
        timeline_analysis={
            "section_directives": [
                {"role": "detail", "start_sec": 0.0, "end_sec": 4.5, "overlay_weight": 1.0},
                {"role": "cta", "start_sec": 6.8, "end_sec": 8.5, "overlay_weight": -1.0},
            ]
        },
    )

    assert [item["text"] for item in accents["emphasis_overlays"]] == ["这里是重点参数"]


def test_build_smart_editing_accents_hook_focus_prefers_hook_boundary_and_overlay():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
            {"start": 6.0, "end": 8.0},
        ],
        subtitle_items=[
            {"start_time": 0.4, "end_time": 1.3, "text_final": "先说结论这里最关键"},
            {"start_time": 3.4, "end_time": 4.3, "text_final": "这里看参数细节"},
        ],
        timeline_analysis={
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "overlay_weight": 1.3},
                {"index": 1, "role": "detail", "start_sec": 3.0, "end_sec": 5.0, "overlay_weight": 1.0},
                {"index": 2, "role": "body", "start_sec": 6.0, "end_sec": 8.0, "overlay_weight": 0.3},
            ],
            "section_actions": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 2.0, "transition_boost": 0.2, "transition_anchor_sec": 1.9, "broll_anchor_sec": 1.0},
                {"role": "detail", "start_sec": 3.0, "end_sec": 5.0, "transition_boost": 1.2, "transition_anchor_sec": 4.0, "broll_anchor_sec": 4.0},
                {"role": "body", "start_sec": 6.0, "end_sec": 8.0, "transition_boost": 0.4, "transition_anchor_sec": 6.2, "broll_anchor_sec": 7.0},
            ],
        },
        editing_skill={
            "review_focus": "hook_boundary",
            "transition_max_count": 3,
            "overlay_max_count": 3,
            "overlay_spacing_sec": 3.0,
        },
    )

    assert accents["transitions"]["boundary_indexes"] == [0]
    assert [item["text"] for item in accents["emphasis_overlays"]] == ["先说结论这里最关键"]


def test_build_smart_editing_accents_mid_focus_prefers_mid_overlay():
    accents = build_smart_editing_accents(
        keep_segments=[
            {"start": 0.0, "end": 2.0},
            {"start": 3.0, "end": 5.0},
            {"start": 6.0, "end": 8.0},
        ],
        subtitle_items=[
            {"start_time": 0.4, "end_time": 1.3, "text_final": "开场先说结论"},
            {"start_time": 3.4, "end_time": 4.4, "text_final": "这里的参数细节最关键"},
            {"start_time": 6.2, "end_time": 7.2, "text_final": "后面普通描述"},
        ],
        timeline_analysis={
            "section_directives": [
                {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 2.0, "overlay_weight": 1.3},
                {"index": 1, "role": "detail", "start_sec": 3.0, "end_sec": 5.0, "overlay_weight": 1.0},
                {"index": 2, "role": "body", "start_sec": 6.0, "end_sec": 8.0, "overlay_weight": 0.35},
            ],
            "section_actions": [
                {"role": "hook", "start_sec": 0.0, "end_sec": 2.0, "transition_boost": 0.2, "transition_anchor_sec": 1.9, "broll_anchor_sec": 1.0},
                {"role": "detail", "start_sec": 3.0, "end_sec": 5.0, "transition_boost": 0.9, "transition_anchor_sec": 4.0, "broll_anchor_sec": 4.0},
                {"role": "body", "start_sec": 6.0, "end_sec": 8.0, "transition_boost": 0.4, "transition_anchor_sec": 6.2, "broll_anchor_sec": 7.0},
            ],
        },
        editing_skill={
            "review_focus": "mid_transition",
            "transition_max_count": 3,
            "overlay_max_count": 3,
            "overlay_spacing_sec": 3.0,
        },
    )

    assert accents["transitions"]["boundary_indexes"] == [1]
    assert accents["emphasis_overlays"][0]["text"] == "这里的参数细节最关键"


def test_build_plain_render_plan_disables_packaging_and_accents():
    plan = build_plain_render_plan(
        {
            "intro": {"path": "intro.mp4"},
            "outro": {"path": "outro.mp4"},
            "insert": {"path": "insert.mp4"},
            "watermark": {"path": "mark.png"},
            "music": {"path": "music.mp3"},
            "avatar_commentary": {"mode": "full_track_audio_passthrough"},
            "editing_accents": {
                "style": "restrained",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意", "start_time": 1.0, "end_time": 2.0}],
                "sound_effects": [{"start_time": 1.0}],
            },
        }
    )

    assert plan["intro"] is None
    assert plan["outro"] is None
    assert plan["insert"] is None
    assert plan["watermark"] is None
    assert plan["music"] is None
    assert plan["subtitles"] is None
    assert plan["avatar_commentary"] is None
    assert plan["editing_accents"]["transitions"]["enabled"] is False
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == []
    assert plan["editing_accents"]["emphasis_overlays"] == []
    assert plan["editing_accents"]["sound_effects"] == []


def test_build_avatar_render_plan_keeps_packaging_but_disables_accents():
    plan = build_avatar_render_plan(
        {
            "intro": {"path": "intro.mp4"},
            "subtitles": {"style": "bold_yellow_outline"},
            "avatar_commentary": {"mode": "full_track_audio_passthrough", "integration_mode": "picture_in_picture"},
            "editing_accents": {
                "style": "restrained",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意"}],
                "sound_effects": [{"start_time": 1.0}],
            },
        }
    )

    assert plan["intro"] == {"path": "intro.mp4"}
    assert plan["subtitles"] == {"style": "bold_yellow_outline"}
    assert plan["avatar_commentary"]["integration_mode"] == "picture_in_picture"
    assert plan["editing_accents"]["transitions"]["enabled"] is False
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == []
    assert plan["editing_accents"]["emphasis_overlays"] == []
    assert plan["editing_accents"]["sound_effects"] == []


def test_build_ai_effect_render_plan_drops_avatar_but_keeps_effects():
    plan = build_ai_effect_render_plan(
        {
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "avatar_commentary": {"mode": "full_track_audio_passthrough"},
            "timeline_analysis": {
                "section_directives": [
                    {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 3.0, "overlay_weight": 1.3},
                    {"index": 1, "role": "detail", "start_sec": 4.0, "end_sec": 7.0, "overlay_weight": 1.0},
                ],
                "section_actions": [
                    {"index": 0, "role": "hook", "start_sec": 0.0, "end_sec": 3.0, "trim_intensity": "balanced", "packaging_intent": "hook_focus", "transition_boost": 0.4, "transition_anchor_sec": 0.5, "broll_allowed": False, "broll_anchor_sec": 0.6},
                    {"index": 1, "role": "detail", "start_sec": 4.0, "end_sec": 7.0, "trim_intensity": "balanced", "packaging_intent": "detail_support", "transition_boost": 1.2, "transition_anchor_sec": 4.2, "broll_allowed": True, "broll_anchor_sec": 5.1},
                ],
            },
            "editing_skill": {"key": "unboxing_standard"},
            "editing_accents": {
                "style": "smart_effect_glitch",
                "transitions": {"enabled": True, "transition": "fade", "duration_sec": 0.12, "boundary_indexes": [0]},
                "emphasis_overlays": [{"text": "注意", "start_time": 1.0, "end_time": 1.6}],
                "sound_effects": [{"start_time": 1.0}],
            },
        },
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 7.0},
            {"start": 9.0, "end": 12.0},
            {"start": 14.5, "end": 18.0},
        ],
        subtitle_items=[
            {"start_time": 0.8, "end_time": 2.1, "text_final": "这点一定要注意"},
            {"start_time": 5.0, "end_time": 6.4, "text_final": "直接上 PRO"},
            {"start_time": 9.2, "end_time": 10.4, "text_final": "黑白双色都很能打"},
            {"start_time": 13.0, "end_time": 14.0, "text_final": "普通描述一下"},
        ],
    )

    assert plan["avatar_commentary"] is None
    assert plan["subtitles"]["motion_style"] == "motion_glitch"
    assert plan["editing_accents"]["style"] == "smart_effect_glitch_ai"
    assert plan["editing_accents"]["transitions"]["enabled"] is True
    assert plan["editing_accents"]["transitions"]["transition"] == "pixelize"
    assert plan["editing_accents"]["transitions"]["duration_sec"] == 0.16
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == [0]
    assert plan["section_choreography"]["style_variant"] == "ai_effect"
    profiles = plan["subtitles"]["section_profiles"]
    assert profiles[0]["style_name"] == "sale_banner"
    assert profiles[0]["motion_style"] == "motion_strobe"
    assert profiles[1]["style_name"] == "cyber_orange"
    assert profiles[1]["motion_style"] == "motion_glitch"
    assert any(item["text"] == "注意" for item in plan["editing_accents"]["emphasis_overlays"])
    assert any(item["text"] == "这点一定要注意" for item in plan["editing_accents"]["emphasis_overlays"])
    assert any(item["text"] == "" for item in plan["editing_accents"]["emphasis_overlays"])
    assert len(plan["editing_accents"]["sound_effects"]) == len(plan["editing_accents"]["emphasis_overlays"])


def test_build_ai_effect_render_plan_maps_legacy_rhythm_to_commercial_ai():
    plan = build_ai_effect_render_plan(
        {
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {"style": "smart_effect_rhythm"},
        },
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 8.0},
        ],
        subtitle_items=[
            {"start_time": 0.8, "end_time": 2.1, "text_final": "这点一定要注意"},
        ],
    )

    assert plan["editing_accents"]["style"] == "smart_effect_commercial_ai"
    assert plan["subtitles"]["motion_style"] == "motion_strobe"


def test_build_ai_effect_render_plan_preserves_color_for_unboxing_workflows():
    plan = build_ai_effect_render_plan(
        {
            "workflow_preset": "unboxing_standard",
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static"},
            "editing_accents": {"style": "smart_effect_glitch"},
        },
        keep_segments=[
            {"start": 0.0, "end": 3.0},
            {"start": 4.0, "end": 8.0},
        ],
        subtitle_items=[
            {"start_time": 0.8, "end_time": 2.1, "text_final": "这点一定要注意"},
        ],
    )

    assert plan["editing_accents"]["style"] == "smart_effect_commercial_ai"
    assert plan["editing_accents"]["preserve_color"] is True
    assert plan["subtitles"]["motion_style"] == "motion_strobe"
