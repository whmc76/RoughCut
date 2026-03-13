"""
Subtitle utilities:
- Remap timestamps from original video timeline to edited output timeline
- Write ASS subtitle file with neon/fluorescent style: black text + bright green outline
"""
from __future__ import annotations

import re
from pathlib import Path

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
        "text_color_rgb": "FFFFFF",
        "outline_color_rgb": "FF9A3D",
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "000000",
        "back_alpha": 0,
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
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "0A1230",
        "back_alpha": 45,
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
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "1A0F08",
        "back_alpha": 40,
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
        "outline_width": 5,
        "margin_v": 28,
        "bold": True,
        "shadow": 1,
        "back_color_rgb": "5A140A",
        "back_alpha": 55,
        "border_style": 1,
    },
    "coupon_green": {
        "font_name": "Microsoft YaHei",
        "font_size": 76,
        "text_color_rgb": "11210F",
        "outline_color_rgb": "7DFF7A",
        "outline_width": 4,
        "margin_v": 30,
        "bold": True,
        "shadow": 0,
        "back_color_rgb": "D6FFD1",
        "back_alpha": 36,
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
    style = dict(SUBTITLE_STYLE_PRESETS.get(style_name, SUBTITLE_STYLE_PRESETS["bold_yellow_outline"]))
    font_name = str(style.get("font_name") or font_name)
    font_size = int(style.get("font_size") or font_size)
    text_color_rgb = str(style.get("text_color_rgb") or text_color_rgb)
    outline_color_rgb = str(style.get("outline_color_rgb") or outline_color_rgb)
    motion_style = _normalize_motion_style(motion_style)
    outline_width = int(style.get("outline_width") or outline_width)
    margin_v = int(style.get("margin_v") or margin_v)
    if margin_v_override is not None:
        margin_v = max(margin_v, int(margin_v_override))
    bold_flag = -1 if style.get("bold", True) else 0
    shadow = int(style.get("shadow") or 0)
    border_style = int(style.get("border_style") or 1)
    back_color_rgb = str(style.get("back_color_rgb") or "000000")
    back_alpha = int(style.get("back_alpha") or 0)

    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    def _rgb_to_ass(rgb_hex: str, alpha: int = 0) -> str:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    primary  = _rgb_to_ass(text_color_rgb)
    outline  = _rgb_to_ass(outline_color_rgb)
    secondary = "&H000000FF"                     # not displayed
    back      = _rgb_to_ass(back_color_rgb, alpha=back_alpha)

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
        # BorderStyle=1: text outline (not background box)
        # Outline=outline_width: thick border = fluorescent glow
        # Shadow=0: no drop shadow
        # Bold=-1, Alignment=2 (bottom center)
        f"Style: Default,{font_name},{font_size},"
        f"{primary},{secondary},{outline},{back},"
        f"{bold_flag},0,0,0,100,100,0,0,{border_style},{outline_width},{shadow},2,10,10,{margin_v},1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    )

    lines = [header]
    for item in subtitle_items:
        start = _ass_time(item["start_time"])
        end   = _ass_time(item["end_time"])
        text  = (
            item.get("text_final")
            or item.get("text_norm")
            or item.get("text_raw", "")
        )
        text = text.replace("{", r"\{").replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{_build_motion_tag(text, motion_style)}")

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return ass_path


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
            "{\\an2\\move(0,22,0,0)\\t(0,220,\\fscx118\\fscy118)\\t(220,420,\\fscx100\\fscy100)}"
            f"{text}"
        )
    if motion_style == "motion_pop":
        return (
            "{\\an2\\t(0,120,\\fscx122\\fscy122\\bord2)\\t(120,240,\\fscx100\\fscy100\\bord1)\\t(240,420,\\bord1)}"
            f"{text}"
        )
    if motion_style == "motion_wave":
        return (
            "{\\an2\\t(0,140,\\fscx102\\fscy98)\\t(140,280,\\fscx100\\fscy102)\\t(280,420,\\fscx98\\fscy102)\\t(420,520,\\fscx100\\fscy100)}"
            f"{text}"
        )
    if motion_style == "motion_slide":
        return (
            "{\\an2\\move(280,120,0,2)\\t(0,360,\\fad(220,0))\\t(360,520,\\move(0,2,0,2))}"
            f"{text}"
        )
    if motion_style == "motion_glitch":
        return (
            "{\\an2\\t(0,100,\\frz8)\\t(100,220,\\frz-8\\fscx102\\fscy102)\\t(220,340,\\frz0\\fscx100\\fscy100)}"
            f"{text}"
        )
    if motion_style == "motion_ripple":
        return (
            "{\\an2\\t(0,110,\\fscx105\\fscy105\\frz0)\\t(110,220,\\fscx130\\fscy100\\bord0)\\t(220,340,\\bord2\\frz0)}"
            f"{text}"
        )
    if motion_style == "motion_strobe":
        return (
            "{\\an2\\t(0,40,\\fscx90\\fscy90\\bord1\\alpha&H88&)\\t(40,100,\\fscx100\\fscy100\\bord2\\alpha&H00&)\\t(100,160,\\fscx108\\fscy108\\alpha&H44&)\\t(160,260,\\fscx100\\fscy100\\alpha&H00&)}"
            f"{text}"
        )
    if motion_style == "motion_echo":
        return (
            "{\\an2\\t(0,110,\\move(-10,2,-4,0)\\fscx102\\fscy98)\\t(110,220,\\move(-4,0,0,0)\\fscx100\\fscy100)\\t(220,360,\\move(0,0,6,-1)\\fscx99\\fscy99)}"
            f"{text}"
        )
    return text


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
