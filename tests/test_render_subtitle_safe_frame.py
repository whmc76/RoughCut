from roughcut.edit.render_plan import build_ai_effect_render_plan, build_render_plan
from roughcut.media.render import _build_smart_effect_video_filters
from roughcut.media.subtitles import _resolve_subtitle_font_size


def test_smart_effect_filters_do_not_crop_showcase_frames() -> None:
    filters, label = _build_smart_effect_video_filters(
        "v0",
        {
            "style": "smart_effect_commercial_ai",
            "emphasis_overlays": [
                {"start_time": 1.0, "end_time": 2.0, "text": "细节", "transform_intensity": 1.35}
            ],
        },
        expected_width=1080,
        expected_height=1920,
    )

    filter_text = ";".join(filters)
    assert label == "vsmart0"
    assert "crop=" not in filter_text
    assert "zoompan=" not in filter_text


def test_unboxing_content_policy_suppresses_full_frame_color_filters() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        workflow_preset="tutorial_standard",
        smart_effect_style="smart_effect_glitch",
        content_profile={
            "content_kind": "unboxing",
            "video_theme": "NITECORE EDC17 开箱与 EDC37 对比",
            "subject_type": "flashlight",
        },
        editing_accents={
            "style": "smart_effect_glitch",
            "emphasis_overlays": [
                {"start_time": 1.0, "end_time": 2.0, "text": "细节", "transform_intensity": 1.35}
            ],
            "sound_effects": [],
        },
    )

    accents = plan["editing_accents"]
    assert plan["content_effect_policy"]["content_class"] == "product_fidelity"
    assert accents["style"] == "smart_effect_commercial"
    assert accents["preserve_color"] is True
    assert accents["suppress_full_frame_color_flash"] is True
    assert build_ai_effect_render_plan(plan, reuse_bound_assets=True)["editing_accents"]["style"] == "smart_effect_commercial_ai"

    filters, label = _build_smart_effect_video_filters(
        "v0",
        accents,
        expected_width=1080,
        expected_height=1920,
    )

    assert filters == []
    assert label == "v0"


def test_subtitle_font_size_uses_comfortable_aspect_ratio_cap() -> None:
    assert _resolve_subtitle_font_size(play_res_x=1080, play_res_y=1920, font_size=144) == 73
    assert _resolve_subtitle_font_size(play_res_x=1920, play_res_y=1080, font_size=144) == 69
