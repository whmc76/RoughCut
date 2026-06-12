import pytest

from roughcut.edit.manual_editor_contract import manual_editor_is_subtitle_only_render
from roughcut.edit import render_plan as render_plan_module
from roughcut.edit.render_plan import build_ai_effect_render_plan, build_render_plan
from roughcut.media.render import (
    _build_overlay_only_editing_accents,
    _render_packaging_context,
    _build_segment_filter_chain,
    _build_video_transform_editing_accents,
    _ffmpeg_fps_expr,
    _resolve_delivery_frame_rate,
)
from roughcut.packaging.library import _normalize_config


def test_packaging_config_accepts_export_frame_rate_selection() -> None:
    config = _normalize_config(
        {
            "export_frame_rate_mode": "specified",
            "export_frame_rate_preset": "50",
        },
        {},
    )

    assert config["export_frame_rate_mode"] == "specified"
    assert config["export_frame_rate_preset"] == "50"


def test_render_plan_carries_user_selected_frame_rate() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        export_frame_rate_mode="specified",
        export_frame_rate_preset="25",
    )

    assert plan["delivery"]["frame_rate_mode"] == "specified"
    assert plan["delivery"]["frame_rate_preset"] == "25"


def test_delivery_frame_rate_uses_source_or_selected_preset() -> None:
    assert _resolve_delivery_frame_rate(source_fps=29.97, delivery={"frame_rate_mode": "source"}) == 29.97
    assert _resolve_delivery_frame_rate(
        source_fps=29.97,
        delivery={"frame_rate_mode": "specified", "frame_rate_preset": "60"},
    ) == 60.0
    assert _ffmpeg_fps_expr(29.97) == "30000/1001"


def test_segment_filters_force_target_frame_rate_before_concat() -> None:
    filters, video_label, _audio_label = _build_segment_filter_chain(
        [
            {"type": "keep", "start": 0.0, "end": 1.0},
            {"type": "keep", "start": 2.0, "end": 3.0},
        ],
        transpose_suffix="",
        editing_accents={"transitions": {"enabled": False}},
        target_fps_expr="25",
    )

    assert video_label == "vout"
    assert any("fps=25,settb=AVTB[v0]" in item for item in filters)
    assert any("fps=25,settb=AVTB[v1]" in item for item in filters)


def test_ai_effect_render_plan_reuses_bound_assets_for_manual_subtitle_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        render_plan_module,
        "_build_section_choreography",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild section choreography")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_insert_to_section_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind insert")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_music_to_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind music")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_bind_subtitles_to_choreography",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebind subtitles")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_select_transition_boundaries",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild transition boundaries")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_select_emphasis_overlays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild emphasis overlays")),
    )
    monkeypatch.setattr(
        render_plan_module,
        "_build_transition_pulse_overlays",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not rebuild transition pulse overlays")),
    )

    plan = build_ai_effect_render_plan(
        {
            "workflow_preset": "unboxing_standard",
            "section_choreography": {"sections": [{"start_time": 0.0, "end_time": 5.0}]},
            "insert": {"asset_id": "insert-a", "start_time": 1.0},
            "music": {"asset_id": "music-a", "start_time": 0.0},
            "subtitles": {"style": "bold_yellow_outline", "motion_style": "motion_static", "version": 1},
            "editing_accents": {
                "style": "smart_effect_commercial",
                "transitions": {"enabled": True, "boundary_indexes": [1], "duration_sec": 0.12},
                "emphasis_overlays": [{"text": "kept", "start_time": 0.8, "end_time": 1.2}],
                "sound_effects": [{"start_time": 0.8, "duration_sec": 0.08, "frequency": 880, "volume": 0.04}],
            },
        },
        reuse_bound_assets=True,
    )

    assert plan["section_choreography"] == {"sections": [{"start_time": 0.0, "end_time": 5.0}]}
    assert plan["insert"] == {"asset_id": "insert-a", "start_time": 1.0}
    assert plan["music"] == {"asset_id": "music-a", "start_time": 0.0}
    assert plan["subtitles"]["style"] == "bold_yellow_outline"
    assert plan["editing_accents"]["transitions"]["boundary_indexes"] == [1]
    assert plan["editing_accents"]["emphasis_overlays"] == [{"text": "kept", "start_time": 0.8, "end_time": 1.2}]
    assert plan["editing_accents"]["sound_effects"] == [
        {"start_time": 0.8, "duration_sec": 0.08, "frequency": 880, "volume": 0.04}
    ]


def test_manual_editor_subtitle_only_contract_is_shared_with_render() -> None:
    assert manual_editor_is_subtitle_only_render(
        {
            "change_scope": "subtitle_only",
            "render_strategy": "reuse_timeline_effect_plan",
            "timeline_changed": False,
        }
    ) is True
    assert manual_editor_is_subtitle_only_render(
        {
            "change_scope": "timeline",
            "render_strategy": "full_timeline_render",
            "timeline_changed": True,
        }
    ) is False


def test_overlay_only_editing_accents_can_skip_subtitle_unit_synthesis() -> None:
    accents = _build_overlay_only_editing_accents(
        {
            "style": "smart_effect_commercial",
            "emphasis_overlays": [{"text": "kept", "start_time": 0.4, "end_time": 0.8}],
            "sound_effects": [{"start_time": 0.4, "frequency": 880}],
        },
        subtitle_items=[
            {
                "text_final": "new subtitle text",
                "start_time": 1.0,
                "end_time": 1.5,
                "subtitle_unit_role": "lead",
            }
        ],
        synthesize_subtitle_unit_accents=False,
    )

    assert accents["emphasis_overlays"] == [{"text": "kept", "start_time": 0.4, "end_time": 0.8}]
    assert accents["sound_effects"] == [{"start_time": 0.4, "frequency": 880}]


def test_render_packaging_context_reads_nested_packaging_timeline_payload() -> None:
    context = _render_packaging_context(
        {
            "packaging_timeline": {
                "subtitles": {"style": "clean_white", "motion_style": "motion_slide"},
                "section_choreography": {"sections": [{"start_time": 0.0, "end_time": 5.0}]},
                "editing_accents": {"style": "smart_effect_punch"},
                "packaging": {
                    "intro": {"path": "intro.mp4"},
                    "music": {"path": "music.mp3"},
                },
            }
        }
    )

    assert context["subtitles"]["style"] == "clean_white"
    assert context["section_choreography"]["sections"] == [{"start_time": 0.0, "end_time": 5.0}]
    assert context["editing_accents"]["style"] == "smart_effect_punch"
    assert context["assets"]["intro"] == {"path": "intro.mp4"}
    assert context["assets"]["music"] == {"path": "music.mp3"}


def test_video_transform_accents_can_skip_subtitle_unit_synthesis() -> None:
    accents = _build_video_transform_editing_accents(
        {
            "style": "smart_effect_commercial",
            "emphasis_overlays": [{"text": "kept", "start_time": 0.6, "end_time": 1.0}],
            "sound_effects": [{"start_time": 0.6, "frequency": 920}],
        },
        subtitle_items=[
            {
                "text_final": "new subtitle text",
                "start_time": 1.0,
                "end_time": 1.6,
                "subtitle_unit_role": "lead",
            }
        ],
        synthesize_subtitle_unit_accents=False,
    )

    assert accents["emphasis_overlays"] == [{"text": "kept", "start_time": 0.6, "end_time": 1.0}]
    assert accents["sound_effects"] == [{"start_time": 0.6, "frequency": 920}]
