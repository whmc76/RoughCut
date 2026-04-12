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


def test_wrap_subtitle_text_preserves_highlight_terms_from_split():
    wrapped = _wrap_subtitle_text(
        "前面铺垫一下直接上PRO版本看升级",
        max_chars_per_line=8,
        max_lines=2,
        preserve_terms=["PRO版本"],
    )

    assert "PRO版\n本" not in wrapped
    assert "PRO版本" in wrapped


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
    assert "{\\an2\\fscx84\\fscy84\\blur3\\bord7\\shad2" in content
    assert "\\fscx130\\fscy100" not in content


def test_write_ass_file_highlights_keywords_inside_subtitle_line(tmp_path: Path):
    ass_path = tmp_path / "keyword.ass"

    write_ass_file(
        [
            {
                "start_time": 0.2,
                "end_time": 1.2,
                "text_final": "直接上 PRO",
                "style_name": "keyword_highlight",
                "subtitle_unit_role": "focus",
            },
            {
                "start_time": 1.4,
                "end_time": 2.2,
                "text_final": "点赞收藏",
                "style_name": "sale_banner",
                "subtitle_unit_role": "action",
            },
        ],
        ass_path,
        style_name="bold_yellow_outline",
        motion_style="motion_static",
        play_res_x=1080,
        play_res_y=1920,
    )

    content = ass_path.read_text(encoding="utf-8-sig")

    assert "\\1c&H00FFF6C8\\3c&H00FF8C2E" in content
    assert "PRO{\\1c" in content
    assert "\\t(60,160,\\alpha&H00&\\fscx114\\fscy114)" in content
    assert "\\1c&H00D2FFD9\\3c&H0066FF38" in content
    assert "\\1c&H00E8FFF2\\3c&H004AFF8D" in content
    assert "点赞{" in content
    assert "收藏{" in content


def test_write_ass_file_uses_section_role_highlight_palettes(tmp_path: Path):
    ass_path = tmp_path / "palette.ass"

    write_ass_file(
        [
            {
                "start_time": 0.2,
                "end_time": 1.0,
                "text_final": "开箱重点",
                "style_name": "sale_banner",
                "subtitle_section_role": "hook",
                "subtitle_unit_role": "lead",
            },
            {
                "start_time": 1.2,
                "end_time": 2.0,
                "text_final": "参数接口",
                "style_name": "keyword_highlight",
                "subtitle_section_role": "detail",
                "subtitle_unit_role": "focus",
            },
            {
                "start_time": 2.2,
                "end_time": 3.0,
                "text_final": "点赞收藏",
                "style_name": "sale_banner",
                "subtitle_section_role": "cta",
                "subtitle_unit_role": "action",
            },
        ],
        ass_path,
        style_name="bold_yellow_outline",
        motion_style="motion_static",
        play_res_x=1080,
        play_res_y=1920,
    )

    content = ass_path.read_text(encoding="utf-8-sig")

    assert "\\1c&H00B0F0FF\\3c&H002B4BFF" in content
    assert "\\1c&H00FFF6C8\\3c&H00FF8C2E" in content
    assert "\\1c&H00D2FFD9\\3c&H0066FF38" in content
