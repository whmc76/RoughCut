"""
Subtitle utilities:
- Remap timestamps from original video timeline to edited output timeline
- Write ASS subtitle file with neon/fluorescent style: black text + bright green outline
"""
from __future__ import annotations

import re
from pathlib import Path

from roughcut.media.subtitle_text import clean_final_subtitle_text

_SUBTITLE_FONT_SCALE = 1.0
_WRAP_NO_SPLIT_ENDINGS = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被",
    "然后", "所以", "但是", "而且", "并且", "会", "想", "要", "能",
)
_WRAP_NO_SPLIT_PREFIXES = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "地", "得",
    "起来", "下来", "上来", "下去", "一下", "喜欢",
)
_WRAP_GOOD_BREAK_PREFIXES = (
    "但是", "不过", "所以", "然后", "而且", "并且", "如果", "因为", "另外", "同时",
)
_KEYWORD_HIGHLIGHT_QUIET_STYLES = {
    "white_minimal",
    "soft_shadow",
    "slate_caption",
    "doc_gray",
    "film_subtle",
    "archive_type",
}
_KEYWORD_HIGHLIGHT_PRIORITY_TERMS = (
    "黑白双色",
    "点赞",
    "收藏",
    "关注",
    "注意",
    "重点",
    "关键",
    "参数",
    "细节",
    "结论",
    "接口",
    "尺寸",
    "续航",
    "流明",
    "旗舰",
    "升级",
    "亮点",
    "对比",
    "实测",
    "新款",
    "配色",
    "版本",
    "开箱",
)
_KEYWORD_HIGHLIGHT_EXPANDABLE_SUFFIXES = {
    "版本",
    "配色",
    "型号",
    "款",
    "代",
    "系列",
}
_KEYWORD_HIGHLIGHT_PREFIX_TRIMS = (
    "这个",
    "那个",
    "一种",
    "一个",
    "一款",
    "这款",
    "那款",
    "新的",
    "新出的",
    "主打的",
    "经典的",
    "家",
)
_KEYWORD_HIGHLIGHT_ACTION_TERMS = ("点赞", "收藏", "关注")
_KEYWORD_HIGHLIGHT_PALETTES: dict[str, dict[str, str]] = {
    "default": {
        "primary_text": "FFF3A6",
        "primary_outline": "FF5A36",
        "secondary_text": "FFFCEE",
        "secondary_outline": "FFB347",
    },
    "hook": {
        "primary_text": "FFF0B0",
        "primary_outline": "FF4B2B",
        "secondary_text": "FFF6DA",
        "secondary_outline": "FF9B3D",
    },
    "detail": {
        "primary_text": "C8F6FF",
        "primary_outline": "2E8CFF",
        "secondary_text": "FFF1D8",
        "secondary_outline": "FF9C38",
    },
    "cta": {
        "primary_text": "D9FFD2",
        "primary_outline": "38FF66",
        "secondary_text": "F2FFE8",
        "secondary_outline": "8DFF4A",
    },
}

SUBTITLE_STYLE_PRESETS: dict[str, dict[str, object]] = {
    "bold_yellow_outline": {
        "font_name": "Microsoft YaHei",
        "font_size": 80,
        "text_color_rgb": "FFE45C",
        "outline_color_rgb": "111111",
        "outline_width": 6,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "000000",
        "back_alpha": 180,
        "border_style": 1,
    },
    "white_minimal": {
        "font_name": "Microsoft YaHei",
        "font_size": 70,
        "text_color_rgb": "FFFFFF",
        "outline_color_rgb": "1C2333",
        "outline_width": 2,
        "margin_v": 34,
        "bold": False,
        "shadow": 0,
        "back_color_rgb": "000000",
        "back_alpha": 0,
        "border_style": 1,
    },
    "neon_green_glow": {
        "font_name": "Microsoft YaHei",
        "font_size": 80,
        "text_color_rgb": "050505",
        "outline_color_rgb": "45FF95",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "000000",
        "back_alpha": 0,
        "border_style": 1,
    },
    "cinema_blue": {
        "font_name": "Microsoft YaHei",
        "font_size": 74,
        "text_color_rgb": "F5F7FF",
        "outline_color_rgb": "425E9C",
        "outline_width": 3,
        "margin_v": 40,
        "bold": False,
        "shadow": 1,
        "back_color_rgb": "0C1220",
        "back_alpha": 120,
        "border_style": 1,
    },
    "bubble_pop": {
        "font_name": "Microsoft YaHei",
        "font_size": 72,
        "text_color_rgb": "FFFFFF",
        "outline_color_rgb": "FF6B9E",
        "outline_width": 3,
        "margin_v": 34,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "2E1630",
        "back_alpha": 110,
        "border_style": 3,
    },
    "keyword_highlight": {
        "font_name": "Microsoft YaHei",
        "font_size": 76,
        "text_color_rgb": "FFF9EF",
        "outline_color_rgb": "FF7A2F",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "311109",
        "back_alpha": 52,
        "border_style": 1,
    },
    "amber_news": {
        "font_name": "Microsoft YaHei",
        "font_size": 74,
        "text_color_rgb": "FFF2D6",
        "outline_color_rgb": "B86B21",
        "outline_width": 4,
        "margin_v": 32,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "27160A",
        "back_alpha": 70,
        "border_style": 1,
    },
    "punch_red": {
        "font_name": "Microsoft YaHei",
        "font_size": 80,
        "text_color_rgb": "FFF8F8",
        "outline_color_rgb": "FF4B5C",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "1D0D12",
        "back_alpha": 60,
        "border_style": 1,
    },
    "lime_box": {
        "font_name": "Microsoft YaHei",
        "font_size": 72,
        "text_color_rgb": "111111",
        "outline_color_rgb": "D7FF5C",
        "outline_width": 3,
        "margin_v": 32,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "D7FF5C",
        "back_alpha": 35,
        "border_style": 3,
    },
    "soft_shadow": {
        "font_name": "Microsoft YaHei",
        "font_size": 70,
        "text_color_rgb": "F8FAFF",
        "outline_color_rgb": "2F3648",
        "outline_width": 1,
        "margin_v": 38,
        "bold": False,
        "shadow": 2,
        "back_color_rgb": "000000",
        "back_alpha": 0,
        "border_style": 1,
    },
    "clean_box": {
        "font_name": "Microsoft YaHei",
        "font_size": 72,
        "text_color_rgb": "FFFFFF",
        "outline_color_rgb": "101010",
        "outline_width": 2,
        "margin_v": 34,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "101010",
        "back_alpha": 92,
        "border_style": 3,
    },
    "midnight_magenta": {
        "font_name": "Microsoft YaHei",
        "font_size": 78,
        "text_color_rgb": "FFF4FF",
        "outline_color_rgb": "C94CFF",
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "15071D",
        "back_alpha": 45,
        "border_style": 1,
    },
    "mint_outline": {
        "font_name": "Microsoft YaHei",
        "font_size": 74,
        "text_color_rgb": "F8FFF9",
        "outline_color_rgb": "58DFA9",
        "outline_width": 3,
        "margin_v": 32,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "071711",
        "back_alpha": 35,
        "border_style": 1,
    },
    "cobalt_pop": {
        "font_name": "Microsoft YaHei",
        "font_size": 78,
        "text_color_rgb": "F8FBFF",
        "outline_color_rgb": "3B6BFF",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "0A1230",
        "back_alpha": 58,
        "border_style": 1,
    },
    "rose_gold": {
        "font_name": "Microsoft YaHei",
        "font_size": 74,
        "text_color_rgb": "FFF6F3",
        "outline_color_rgb": "E39A86",
        "outline_width": 3,
        "margin_v": 34,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "2A1510",
        "back_alpha": 55,
        "border_style": 1,
    },
    "slate_caption": {
        "font_name": "Microsoft YaHei",
        "font_size": 70,
        "text_color_rgb": "F4F7FA",
        "outline_color_rgb": "4D5A66",
        "outline_width": 2,
        "margin_v": 38,
        "bold": False,
        "shadow": 1,
        "back_color_rgb": "0D1318",
        "back_alpha": 30,
        "border_style": 1,
    },
    "ivory_serif": {
        "font_name": "SimSun",
        "font_size": 72,
        "text_color_rgb": "FFF8E9",
        "outline_color_rgb": "6E5535",
        "outline_width": 2,
        "margin_v": 36,
        "bold": False,
        "shadow": 1,
        "back_color_rgb": "20170F",
        "back_alpha": 28,
        "border_style": 1,
    },
    "cyber_orange": {
        "font_name": "Microsoft YaHei",
        "font_size": 78,
        "text_color_rgb": "FFF9F1",
        "outline_color_rgb": "FF8A1F",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "1A0F08",
        "back_alpha": 56,
        "border_style": 1,
    },
    "streamer_duo": {
        "font_name": "Microsoft YaHei",
        "font_size": 76,
        "text_color_rgb": "FDFDFF",
        "outline_color_rgb": "7F5BFF",
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "111126",
        "back_alpha": 42,
        "border_style": 1,
    },
    "doc_gray": {
        "font_name": "Microsoft YaHei",
        "font_size": 68,
        "text_color_rgb": "F3F4F6",
        "outline_color_rgb": "3C4148",
        "outline_width": 1,
        "margin_v": 40,
        "bold": False,
        "shadow": 0,
        "back_color_rgb": "000000",
        "back_alpha": 0,
        "border_style": 1,
    },
    "sale_banner": {
        "font_name": "Microsoft YaHei",
        "font_size": 80,
        "text_color_rgb": "FFFBEF",
        "outline_color_rgb": "FF6238",
        "outline_width": 6,
        "margin_v": 28,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "5A140A",
        "back_alpha": 72,
        "border_style": 1,
    },
    "coupon_green": {
        "font_name": "Microsoft YaHei",
        "font_size": 76,
        "text_color_rgb": "11210F",
        "outline_color_rgb": "7DFF7A",
        "outline_width": 5,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "D6FFD1",
        "back_alpha": 48,
        "border_style": 3,
    },
    "luxury_caps": {
        "font_name": "Microsoft YaHei",
        "font_size": 74,
        "text_color_rgb": "FFF8EA",
        "outline_color_rgb": "C6A45A",
        "outline_width": 3,
        "margin_v": 34,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "17120A",
        "back_alpha": 45,
        "border_style": 1,
    },
    "film_subtle": {
        "font_name": "SimSun",
        "font_size": 68,
        "text_color_rgb": "F7F4EC",
        "outline_color_rgb": "2C2A28",
        "outline_width": 1,
        "margin_v": 42,
        "bold": False,
        "shadow": 1,
        "back_color_rgb": "000000",
        "back_alpha": 0,
        "border_style": 1,
    },
    "archive_type": {
        "font_name": "Consolas",
        "font_size": 66,
        "text_color_rgb": "E9ECEF",
        "outline_color_rgb": "4A5259",
        "outline_width": 1,
        "margin_v": 40,
        "bold": False,
        "shadow": 0,
        "back_color_rgb": "0B0D10",
        "back_alpha": 24,
        "border_style": 1,
    },
    "teaser_glow": {
        "font_name": "Microsoft YaHei",
        "font_size": 80,
        "text_color_rgb": "FFF7FF",
        "outline_color_rgb": "6BE8FF",
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 2,
        "back_color_rgb": "0C1422",
        "back_alpha": 30,
        "border_style": 1,
    },
}

SUBTITLE_MOTION_PRESETS = {
    "motion_static",
    "motion_typewriter",
    "motion_pop",
    "motion_wave",
    "motion_slide",
    "motion_glitch",
    "motion_ripple",
    "motion_strobe",
    "motion_echo",
}


def remap_subtitles_to_timeline(
    subtitle_items: list[dict],
    keep_segments: list[dict],
) -> list[dict]:
    """
    Remap subtitle timestamps from original video timeline to edited output timeline.

    When segments are cut (silence/fillers removed), the output video is shorter.
    This function maps each subtitle's original [start, end] to new [start, end]
    based on the cumulative output time of kept segments.

    Subtitles that fall entirely within removed segments are dropped.
    Subtitles that span a cut boundary are clipped to the kept portion.
    """
    sorted_segs = sorted(keep_segments, key=lambda s: s["start"])

    seg_map: list[dict] = []
    out_time = 0.0
    for seg in sorted_segs:
        seg_map.append({
            "in_start": float(seg["start"]),
            "in_end":   float(seg["end"]),
            "out_start": out_time,
        })
        out_time += seg["end"] - seg["start"]

    remapped: list[dict] = []
    for item in subtitle_items:
        sub_start = float(item["start_time"])
        sub_end   = float(item["end_time"])

        best_duration = 0.0
        best_new: tuple[float, float] | None = None

        for seg in seg_map:
            overlap_in_s = max(sub_start, seg["in_start"])
            overlap_in_e = min(sub_end,   seg["in_end"])
            overlap = overlap_in_e - overlap_in_s
            if overlap > best_duration:
                best_duration = overlap
                new_s = seg["out_start"] + (overlap_in_s - seg["in_start"])
                new_e = seg["out_start"] + (overlap_in_e - seg["in_start"])
                best_new = (new_s, new_e)

        if best_new and best_new[1] > best_new[0] + 0.05:
            remapped.append({**item, "start_time": best_new[0], "end_time": best_new[1]})

    return remapped


def write_ass_file(
    subtitle_items: list[dict],
    ass_path: Path,
    *,
    style_name: str = "bold_yellow_outline",
    font_name: str = "Microsoft YaHei",
    font_size: int = 80,
    text_color_rgb: str = "000000",      # text color: black for neon effect
    outline_color_rgb: str = "00FF00",   # outline/glow color: neon green
    outline_width: int = 5,              # thick outline = fluorescent glow
    margin_v: int = 30,
    margin_v_override: int | None = None,
    motion_style: str = "motion_static",
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> Path:
    """
    Write ASS subtitle file with neon/fluorescent style.

    Style: black bold text with thick bright-green outline.
    The outline creates the fluorescent glow effect around each character.
    BorderStyle=1 (outline only, no background box).
    """
    motion_style = _normalize_motion_style(motion_style)
    base_style_name = str(style_name or "bold_yellow_outline")

    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    def _rgb_to_ass(rgb_hex: str, alpha: int = 0) -> str:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    style_definitions: dict[str, dict[str, object]] = {
        "Default": _resolve_ass_style_definition(
            base_style_name,
            font_name=font_name,
            font_size=font_size,
            text_color_rgb=text_color_rgb,
            outline_color_rgb=outline_color_rgb,
            outline_width=outline_width,
            margin_v=margin_v,
            margin_v_override=margin_v_override,
            play_res_x=play_res_x,
            play_res_y=play_res_y,
        )
    }
    for item in subtitle_items:
        item_style_name = str((item or {}).get("style_name") or "").strip()
        if not item_style_name or item_style_name == base_style_name:
            continue
        if item_style_name in style_definitions:
            continue
        style_definitions[item_style_name] = _resolve_ass_style_definition(
            item_style_name,
            font_name=font_name,
            font_size=font_size,
            text_color_rgb=text_color_rgb,
            outline_color_rgb=outline_color_rgb,
            outline_width=outline_width,
            margin_v=margin_v,
            margin_v_override=margin_v_override,
            play_res_x=play_res_x,
            play_res_y=play_res_y,
        )

    style_lines = [
        _build_ass_style_line(style_id, style_definition, rgb_to_ass=_rgb_to_ass)
        for style_id, style_definition in style_definitions.items()
    ]

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "Collisions: Normal\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{chr(10).join(style_lines)}\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )

    lines = [header]
    for item in subtitle_items:
        start = _ass_time(item["start_time"])
        end   = _ass_time(item["end_time"])
        style_id = str(item.get("style_name") or "").strip()
        if not style_id or style_id not in style_definitions:
            style_id = "Default"
        style_definition = style_definitions[style_id]
        text = clean_final_subtitle_text(
            item.get("text_final")
            or item.get("text_norm")
            or item.get("text_raw", "")
        )
        if not text:
            continue
        text = _wrap_subtitle_text(
            str(text),
            max_chars_per_line=_estimate_subtitle_line_capacity(
                play_res_x=play_res_x,
                font_size=int(style_definition["font_size"]),
            ),
            max_lines=2,
            preserve_terms=_collect_highlight_preserve_terms(
                str(text),
                item=item,
                style_name=str(item.get("style_name") or style_id or "Default").strip() or "Default",
            ),
        )
        text = _apply_keyword_highlight_markup(
            text,
            item=item,
            style_id=style_id,
            style_definition=style_definition,
            rgb_to_ass=_rgb_to_ass,
        )
        resolved_motion_style = _normalize_motion_style(str(item.get("motion_style") or motion_style))
        margin_floor = int(style_definition["margin_v"])
        margin_delta = int(item.get("margin_v_delta", 0) or 0)
        item_margin_v_override = item.get("margin_v_override")
        if item_margin_v_override is None:
            item_margin_v_override = margin_floor + margin_delta
        item_margin_v = max(margin_floor, int(item_margin_v_override or 0))
        lines.append(
            f"Dialogue: 0,{start},{end},{style_id},,0,0,{item_margin_v},,"
            f"{_build_motion_tag(text, resolved_motion_style)}"
        )

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return ass_path


def _resolve_ass_style_definition(
    style_name: str,
    *,
    font_name: str,
    font_size: int,
    text_color_rgb: str,
    outline_color_rgb: str,
    outline_width: int,
    margin_v: int,
    margin_v_override: int | None,
    play_res_x: int,
    play_res_y: int,
) -> dict[str, object]:
    style = dict(SUBTITLE_STYLE_PRESETS.get(style_name, SUBTITLE_STYLE_PRESETS["bold_yellow_outline"]))
    resolved_font_name = str(style.get("font_name") or font_name)
    base_font_size = int(style.get("font_size") or font_size)
    resolved_font_size = int(round(base_font_size * _SUBTITLE_FONT_SCALE))
    resolved_font_size = _resolve_subtitle_font_size(
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        font_size=resolved_font_size,
    )
    resolved_margin_v = int(style.get("margin_v") or margin_v)
    if margin_v_override is not None:
        resolved_margin_v = max(resolved_margin_v, int(margin_v_override))
    return {
        "font_name": resolved_font_name,
        "font_size": resolved_font_size,
        "text_color_rgb": str(style.get("text_color_rgb") or text_color_rgb),
        "outline_color_rgb": str(style.get("outline_color_rgb") or outline_color_rgb),
        "outline_width": int(style.get("outline_width") or outline_width),
        "margin_v": resolved_margin_v,
        "bold_flag": -1 if style.get("bold", True) else 0,
        "shadow": int(style.get("shadow") or 0),
        "border_style": int(style.get("border_style") or 1),
        "back_color_rgb": str(style.get("back_color_rgb") or "000000"),
        "back_alpha": int(style.get("back_alpha") or 0),
        "margin_h": _resolve_subtitle_horizontal_margin(play_res_x=play_res_x),
    }


def _build_ass_style_line(
    style_id: str,
    style_definition: dict[str, object],
    *,
    rgb_to_ass,
) -> str:
    primary = rgb_to_ass(str(style_definition["text_color_rgb"]))
    outline = rgb_to_ass(str(style_definition["outline_color_rgb"]))
    secondary = "&H000000FF"
    back = rgb_to_ass(str(style_definition["back_color_rgb"]), alpha=int(style_definition["back_alpha"]))
    return (
        f"Style: {style_id},{style_definition['font_name']},{style_definition['font_size']},"
        f"{primary},{secondary},{outline},{back},"
        f"{style_definition['bold_flag']},0,0,0,100,100,0,0,{style_definition['border_style']},"
        f"{style_definition['outline_width']},{style_definition['shadow']},2,"
        f"{style_definition['margin_h']},{style_definition['margin_h']},{style_definition['margin_v']},1"
    )


def _normalize_motion_style(value: str) -> str:
    normalized = str(value or "motion_static").strip().lower()
    if normalized in SUBTITLE_MOTION_PRESETS:
        return normalized
    return "motion_static"


def _build_motion_tag(text: str, motion_style: str) -> str:
    if motion_style == "motion_static":
        return text
    if motion_style == "motion_typewriter":
        return (
            "{\\an2\\fsp18\\blur2\\alpha&H22&\\fscx92\\fscy92\\t(0,160,\\fsp0\\blur0\\alpha&H00&\\fscx112\\fscy112)\\t(160,280,\\fscx100\\fscy100)}"
            f"{text}"
        )
    if motion_style == "motion_pop":
        return (
            "{\\an2\\fscx84\\fscy84\\blur3\\bord7\\shad2\\t(0,120,\\fscx132\\fscy132\\blur0.6\\bord8)\\t(120,220,\\fscx100\\fscy100\\bord5\\shad1)}"
            f"{text}"
        )
    if motion_style == "motion_wave":
        return (
            "{\\an2\\fscx94\\fscy94\\frz-2\\t(0,120,\\fscx108\\fscy108\\frz1)\\t(120,240,\\fscx102\\fscy102\\frz-1)\\t(240,360,\\fscx100\\fscy100\\frz0)}"
            f"{text}"
        )
    if motion_style == "motion_slide":
        return (
            "{\\an2\\fsp26\\alpha&H66&\\blur3\\fscx108\\fscy108\\t(0,160,\\fsp0\\alpha&H00&\\blur0\\fscx102\\fscy102)\\t(160,300,\\fscx100\\fscy100)}"
            f"{text}"
        )
    if motion_style == "motion_glitch":
        return (
            "{\\an2\\frz-3\\blur1.4\\t(0,70,\\frz5\\alpha&H22&\\bord6)\\t(70,150,\\frz-4\\alpha&H00&\\bord5)\\t(150,260,\\frz0\\blur0.4)}"
            f"{text}"
        )
    if motion_style == "motion_ripple":
        return (
            "{\\an2\\fscx90\\fscy90\\blur4\\bord8\\shad0\\t(0,110,\\fscx124\\fscy124\\blur1.2\\bord10)\\t(110,210,\\fscx108\\fscy108\\blur0\\bord6\\shad2)\\t(210,320,\\fscx100\\fscy100\\bord4\\shad1)}"
            f"{text}"
        )
    if motion_style == "motion_strobe":
        return (
            "{\\an2\\fscx88\\fscy88\\alpha&H88&\\blur3\\t(0,45,\\fscx104\\fscy104\\alpha&H10&\\blur0.8)\\t(45,100,\\fscx118\\fscy118\\alpha&H00&\\bord7)\\t(100,180,\\fscx102\\fscy102\\alpha&H22&)\\t(180,260,\\fscx100\\fscy100\\alpha&H00&\\bord5)}"
            f"{text}"
        )
    if motion_style == "motion_echo":
        return (
            "{\\an2\\fsp10\\blur2\\fscx96\\fscy96\\alpha&H18&\\t(0,140,\\fsp2\\blur0.5\\fscx108\\fscy108\\alpha&H00&)\\t(140,260,\\fsp0\\fscx100\\fscy100)\\t(260,420,\\blur1\\alpha&H10&)}"
            f"{text}"
        )
    return text


def _apply_keyword_highlight_markup(
    text: str,
    *,
    item: dict[str, object],
    style_id: str,
    style_definition: dict[str, object],
    rgb_to_ass,
) -> str:
    lines = str(text or "").split("\n")
    rendered_lines: list[str] = []
    style_name = str(item.get("style_name") or style_id or "Default").strip() or "Default"
    section_role = str(item.get("subtitle_section_role") or "").strip().lower()
    unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
    explicit_terms = [
        str(value).strip()
        for value in (item.get("highlight_terms") or [])
        if str(value).strip()
    ]
    allow_auto_highlight = style_name not in _KEYWORD_HIGHLIGHT_QUIET_STYLES or unit_role in {"lead", "focus", "action"}
    for line in lines:
        spans: list[tuple[int, int]] = []
        if allow_auto_highlight or explicit_terms:
            spans = _select_keyword_highlight_spans(line, unit_role=unit_role, explicit_terms=explicit_terms)
        rendered_lines.append(
            _render_highlighted_subtitle_line(
                line,
                highlight_spans=spans,
                style_definition=style_definition,
                palette=_resolve_keyword_highlight_palette(section_role=section_role, unit_role=unit_role),
                rgb_to_ass=rgb_to_ass,
            )
        )
    return r"\N".join(rendered_lines)


def _select_keyword_highlight_spans(
    line: str,
    *,
    unit_role: str,
    explicit_terms: list[str],
) -> list[tuple[int, int]]:
    candidates = _build_keyword_highlight_candidates(line, unit_role=unit_role, explicit_terms=explicit_terms)
    return _pick_non_overlapping_highlight_spans(line, candidates)


def _build_keyword_highlight_candidates(
    line: str,
    *,
    unit_role: str,
    explicit_terms: list[str],
) -> list[tuple[str, float]]:
    stripped = str(line or "").strip()
    if len(stripped) < 2:
        return []
    candidates: list[tuple[str, float]] = []
    for index, term in enumerate(sorted(explicit_terms, key=len, reverse=True)):
        if term in stripped:
            candidates.append((term, 120.0 - index))
    if unit_role == "action":
        for index, term in enumerate(_KEYWORD_HIGHLIGHT_ACTION_TERMS):
            if term in stripped:
                candidates.append((term, 96.0 - index))
    upper_token = re.search(r"\b[A-Z][A-Z0-9+\-]{1,}\b", stripped)
    if upper_token:
        candidates.append((upper_token.group(0), 92.0))
    mixed_token = re.search(r"\b[A-Za-z]*\d+[A-Za-z0-9+\-]*\b", stripped)
    if mixed_token:
        candidates.append((mixed_token.group(0), 88.0))
    for index, term in enumerate(_KEYWORD_HIGHLIGHT_PRIORITY_TERMS):
        if term in stripped:
            candidates.append((_expand_keyword_highlight_term(stripped, term), 80.0 - index * 0.5))
    compact = "".join(stripped.split())
    if unit_role in {"lead", "focus"} and 3 <= len(compact) <= 6 and _contains_cjk(compact):
        candidates.append((compact, 60.0))
    return candidates


def _expand_keyword_highlight_term(line: str, term: str) -> str:
    suffix = str(term or "").strip()
    text = str(line or "").strip()
    if suffix not in _KEYWORD_HIGHLIGHT_EXPANDABLE_SUFFIXES or suffix not in text:
        return suffix
    start = text.find(suffix)
    lookback = text[max(0, start - 14):start]
    if not lookback:
        return suffix
    split_markers = ("，", "。", "！", "？", "；", "：", ",", ".", "!", "?", ";", ":", " ", "\n")
    cut = max((lookback.rfind(marker) for marker in split_markers), default=-1)
    prefix = lookback[cut + 1:] if cut >= 0 else lookback
    for marker in (
        "这个",
        "那个",
        "一款",
        "一个",
        "主打的",
        "新出的",
        "经典的",
        "包括",
        "还有",
        "以及",
        "是",
        "叫",
        "算",
        "有",
        "为",
        "和",
        "跟",
        "的",
    ):
        marker_index = prefix.rfind(marker)
        if marker_index >= 0:
            prefix = prefix[marker_index + len(marker):]
    changed = True
    while prefix and changed:
        changed = False
        for marker in _KEYWORD_HIGHLIGHT_PREFIX_TRIMS:
            if prefix.startswith(marker) and len(prefix) > len(marker):
                prefix = prefix[len(marker):]
                changed = True
                break
    prefix = prefix.strip()
    if not prefix:
        return suffix
    if len(prefix) > 10:
        prefix = prefix[-10:]
    if len(prefix) < 2 and not re.search(r"[A-Za-z0-9]", prefix):
        return suffix
    return f"{prefix}{suffix}"


def _collect_highlight_preserve_terms(
    text: str,
    *,
    item: dict[str, object],
    style_name: str,
) -> list[str]:
    unit_role = str(item.get("subtitle_unit_role") or "").strip().lower()
    explicit_terms = [
        str(value).strip()
        for value in (item.get("highlight_terms") or [])
        if str(value).strip()
    ]
    allow_auto_highlight = style_name not in _KEYWORD_HIGHLIGHT_QUIET_STYLES or unit_role in {"lead", "focus", "action"}
    if not (allow_auto_highlight or explicit_terms):
        return []
    candidates = _build_keyword_highlight_candidates(text, unit_role=unit_role, explicit_terms=explicit_terms)
    seen: set[str] = set()
    terms: list[str] = []
    for term, _score in sorted(candidates, key=lambda item: (-item[1], -len(item[0]), text.find(item[0]))):
        normalized = str(term).strip()
        if not normalized or normalized in seen or normalized not in text:
            continue
        seen.add(normalized)
        terms.append(normalized)
        if len(terms) >= 4:
            break
    return terms


def _pick_non_overlapping_highlight_spans(
    line: str,
    candidates: list[tuple[str, float]],
) -> list[tuple[int, int]]:
    ranked: list[tuple[float, int, int, str]] = []
    seen_terms: set[str] = set()
    for term, score in candidates:
        normalized_term = str(term or "").strip()
        if not normalized_term or normalized_term in seen_terms:
            continue
        start = line.find(normalized_term)
        if start < 0:
            continue
        seen_terms.add(normalized_term)
        ranked.append((score, start, len(normalized_term), normalized_term))
    ranked.sort(key=lambda item: (-item[0], -item[2], item[1]))
    selected: list[tuple[int, int]] = []
    for _score, start, length, _term in ranked:
        end = start + length
        if any(not (end <= existing_start or start >= existing_end) for existing_start, existing_end in selected):
            continue
        selected.append((start, end))
        if len(selected) >= 2:
            break
    selected.sort(key=lambda item: item[0])
    return selected


def _render_highlighted_subtitle_line(
    line: str,
    *,
    highlight_spans: list[tuple[int, int]],
    style_definition: dict[str, object],
    palette: dict[str, str],
    rgb_to_ass,
) -> str:
    if not highlight_spans:
        return _escape_ass_text(line)
    base_primary = rgb_to_ass(str(style_definition["text_color_rgb"]))
    base_outline = rgb_to_ass(str(style_definition["outline_color_rgb"]))
    base_outline_width = int(style_definition["outline_width"])
    base_shadow = int(style_definition["shadow"])
    parts: list[str] = []
    cursor = 0
    for highlight_index, (start, end) in enumerate(highlight_spans):
        if start < cursor or end <= start:
            continue
        parts.append(_escape_ass_text(line[cursor:start]))
        focus = _escape_ass_text(line[start:end])
        if highlight_index == 0:
            highlight_primary = rgb_to_ass(str(palette["primary_text"]))
            highlight_outline = rgb_to_ass(str(palette["primary_outline"]))
            border = min(10, base_outline_width + 2)
            shadow = max(1, base_shadow + 1)
            scale = 108
            blur = "0.6"
            intro = "\\alpha&H55&\\fscx96\\fscy96\\t(60,160,\\alpha&H00&\\fscx114\\fscy114)\\t(160,280,\\fscx108\\fscy108)"
        else:
            highlight_primary = rgb_to_ass(str(palette["secondary_text"]))
            highlight_outline = rgb_to_ass(str(palette["secondary_outline"]))
            border = min(9, base_outline_width + 1)
            shadow = max(1, base_shadow)
            scale = 104
            blur = "0.4"
            intro = "\\alpha&H44&\\fscx98\\fscy98\\t(110,210,\\alpha&H00&\\fscx108\\fscy108)\\t(210,320,\\fscx104\\fscy104)"
        parts.append(
            "{"
            + f"\\1c{highlight_primary}\\3c{highlight_outline}"
            + f"\\bord{border}\\shad{shadow}"
            + f"\\blur{blur}\\fscx{scale}\\fscy{scale}"
            + intro
            + "}"
            + focus
            + "{"
            + f"\\1c{base_primary}\\3c{base_outline}"
            + f"\\bord{base_outline_width}\\shad{base_shadow}"
            + "\\blur0\\alpha&H00&\\fscx100\\fscy100"
            + "}"
        )
        cursor = end
    parts.append(_escape_ass_text(line[cursor:]))
    return "".join(parts)


def _escape_ass_text(text: str) -> str:
    return str(text or "").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _resolve_keyword_highlight_palette(*, section_role: str, unit_role: str) -> dict[str, str]:
    if section_role in _KEYWORD_HIGHLIGHT_PALETTES:
        return _KEYWORD_HIGHLIGHT_PALETTES[section_role]
    if unit_role == "action":
        return _KEYWORD_HIGHLIGHT_PALETTES["cta"]
    if unit_role in {"lead", "support"}:
        return _KEYWORD_HIGHLIGHT_PALETTES["hook"]
    if unit_role in {"focus", "setup"}:
        return _KEYWORD_HIGHLIGHT_PALETTES["detail"]
    return _KEYWORD_HIGHLIGHT_PALETTES["default"]


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _estimate_subtitle_line_capacity(*, play_res_x: int, font_size: int) -> int:
    safe_margin = _resolve_subtitle_horizontal_margin(play_res_x=play_res_x)
    usable_width = max(220, int(play_res_x) - (safe_margin * 2))
    estimated_char_width = max(28.0, float(font_size) * 1.08)
    return max(6, min(14, int(usable_width / estimated_char_width)))


def _resolve_subtitle_font_size(*, play_res_x: int, play_res_y: int, font_size: int) -> int:
    width = max(1, int(play_res_x))
    height = max(1, int(play_res_y))
    short_edge = min(width, height)
    aspect = max(width, height) / max(short_edge, 1)
    portrait = height > width
    if portrait:
        max_ratio = 0.068 if aspect < 1.9 else 0.064
        min_ratio = 0.045
    else:
        max_ratio = 0.064 if aspect < 1.9 else 0.06
        min_ratio = 0.04
    min_size = max(28, int(round(short_edge * min_ratio)))
    max_size = max(min_size, int(round(short_edge * max_ratio)))
    return max(min_size, min(int(font_size), max_size))


def _resolve_subtitle_horizontal_margin(*, play_res_x: int) -> int:
    return max(28, int(play_res_x * 0.06))


def _wrap_subtitle_text(
    text: str,
    *,
    max_chars_per_line: int,
    max_lines: int = 2,
    preserve_terms: list[str] | None = None,
) -> str:
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if "\n" in raw:
        return "\n".join(
            _wrap_subtitle_text(
                part,
                max_chars_per_line=max_chars_per_line,
                max_lines=max_lines,
                preserve_terms=preserve_terms,
            )
            for part in raw.split("\n")
        )
    compact = raw.strip()
    if len(compact) <= max_chars_per_line:
        return compact

    segments: list[str] = []
    remaining = compact
    while len(remaining) > max_chars_per_line and len(segments) < max_lines - 1:
        split_at = _find_subtitle_wrap_index(remaining, max_chars_per_line, preserve_terms=preserve_terms)
        if split_at <= 0 or split_at >= len(remaining):
            break
        segments.append(remaining[:split_at].strip())
        remaining = remaining[split_at:].strip()

    if remaining:
        if len(segments) >= max_lines - 1 and len(remaining) > max_chars_per_line:
            truncated = remaining[:max_chars_per_line].rstrip()
            if len(remaining) > max_chars_per_line and max_chars_per_line >= 2:
                truncated = truncated[:-1].rstrip() + "…"
            segments.append(truncated)
        else:
            segments.append(remaining)
    return "\n".join(part for part in segments if part)


def _find_subtitle_wrap_index(text: str, target: int, *, preserve_terms: list[str] | None = None) -> int:
    punctuation = "，。！？；：,.!?、）)]】》> "
    lower = max(2, target - 4)
    upper = min(len(text) - 1, target + 2)
    best_index = min(len(text) - 1, max(1, target))
    best_score = float("-inf")
    protected_ranges = _term_ranges_in_text(text, preserve_terms or [])
    for index in range(lower, upper + 1):
        left = text[:index].strip()
        right = text[index:].strip()
        if not left or not right:
            continue
        score = -abs(index - target)
        if text[index - 1] in punctuation:
            score += 8
        if any(right.startswith(prefix) for prefix in _WRAP_GOOD_BREAK_PREFIXES):
            score += 6
        if any(left.endswith(token) for token in _WRAP_NO_SPLIT_ENDINGS):
            score -= 10
        if any(right.startswith(token) for token in _WRAP_NO_SPLIT_PREFIXES):
            score -= 10
        if re.match(r"^[，。！？、：；,.!?]", right):
            score -= 12
        if len(right) <= 2:
            score -= 6
        if len(left) <= 2:
            score -= 4
        if len(left) <= len(right) + 2:
            score += 1.5
        if any(start < index < end for start, end in protected_ranges):
            score -= 30
        if score > best_score:
            best_score = score
            best_index = index
    return best_index


def _term_ranges_in_text(text: str, terms: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for term in terms:
        normalized = str(term or "").strip()
        if len(normalized) < 2:
            continue
        search_start = 0
        while search_start < len(text):
            index = text.find(normalized, search_start)
            if index < 0:
                break
            ranges.append((index, index + len(normalized)))
            search_start = index + len(normalized)
    return ranges


def escape_path_for_ffmpeg_filter(path: Path) -> str:
    """
    Escape a file path for use inside ffmpeg filter_complex on Windows.

    ffmpeg filter syntax uses ':' as option separator and '\\' for escaping,
    so Windows paths need:
      - backslashes → forward slashes
      - drive letter colon → escaped colon  (C: → C\\:)
    """
    s = str(path).replace("\\", "/")
    s = re.sub(r"^([A-Za-z]):", r"\1\\:", s)
    return s


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"
