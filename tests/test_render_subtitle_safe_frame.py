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


def test_subtitle_font_size_uses_comfortable_aspect_ratio_cap() -> None:
    assert _resolve_subtitle_font_size(play_res_x=1080, play_res_y=1920, font_size=144) == 73
    assert _resolve_subtitle_font_size(play_res_x=1920, play_res_y=1080, font_size=144) == 69
