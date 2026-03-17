from __future__ import annotations

from roughcut.media.subtitles import (
    _estimate_subtitle_line_capacity,
    _resolve_subtitle_font_size,
    _wrap_subtitle_text,
)


def test_estimate_subtitle_line_capacity_shrinks_for_portrait_canvas():
    portrait_capacity = _estimate_subtitle_line_capacity(play_res_x=736, font_size=72)
    landscape_capacity = _estimate_subtitle_line_capacity(play_res_x=1920, font_size=72)

    assert portrait_capacity < landscape_capacity
    assert portrait_capacity >= 6
    assert portrait_capacity <= 9


def test_resolve_subtitle_font_size_pushes_large_display_subtitles():
    portrait_font_size = _resolve_subtitle_font_size(play_res_x=736, play_res_y=992, font_size=152)
    landscape_font_size = _resolve_subtitle_font_size(play_res_x=1920, play_res_y=1080, font_size=152)

    assert portrait_font_size >= 88
    assert landscape_font_size >= 92
    assert landscape_font_size > portrait_font_size


def test_wrap_subtitle_text_inserts_line_breaks_for_long_cjk_lines():
    text = "因为我感觉它的功能还是挺不错的大家打开这个东西会有很明显的使用场景"

    wrapped = _wrap_subtitle_text(text, max_chars_per_line=10, max_lines=2)

    assert "\n" in wrapped
    assert len(wrapped.split("\n")) <= 2
    assert all(len(line) <= 16 for line in wrapped.split("\n"))
