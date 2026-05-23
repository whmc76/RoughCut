from roughcut.edit.render_plan import build_render_plan
from roughcut.media.render import (
    _build_segment_filter_chain,
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
