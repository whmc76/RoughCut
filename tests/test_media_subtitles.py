from __future__ import annotations

from pathlib import Path

from roughcut.media.subtitles import (
    _estimate_subtitle_line_capacity,
    _resolve_subtitle_font_size,
    _wrap_subtitle_text,
    write_ass_file,
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


def test_wrap_subtitle_text_prefers_clause_boundary_over_mid_token_split():
    text = "这把刀我觉得非常实用因为螺丝细节也处理得很好"

    wrapped = _wrap_subtitle_text(text, max_chars_per_line=10, max_lines=2)

    first_line, second_line = wrapped.split("\n", 1)
    assert not first_line.endswith(("因", "得", "也"))
    assert second_line.startswith("因为")


def test_write_ass_file_supports_item_style_motion_and_margin_overrides(tmp_path: Path):
    ass_path = tmp_path / "demo.ass"

    write_ass_file(
        [
            {
                "start_time": 0.2,
                "end_time": 1.2,
                "text_final": "第一句字幕",
                "style_name": "white_minimal",
                "motion_style": "motion_pop",
                "margin_v_delta": 12,
            },
            {
                "start_time": 1.4,
                "end_time": 2.0,
                "text_final": "第二句字幕",
            },
        ],
        ass_path,
        style_name="bold_yellow_outline",
        motion_style="motion_static",
        play_res_x=1080,
        play_res_y=1920,
    )

    content = ass_path.read_text(encoding="utf-8-sig")

    assert "Style: Default," in content
    assert "Style: white_minimal," in content
    assert "Dialogue: 0,0:00:00.20,0:00:01.20,white_minimal,,0,0,46,," in content
    assert "{\\an2\\t(0,120,\\fscx122\\fscy122\\bord2)" in content
