"""
Subtitle utilities:
- Remap timestamps from original video timeline to edited output timeline
- Write ASS subtitle file with neon/fluorescent style: black text + bright green outline
"""
from __future__ import annotations

import re
from pathlib import Path


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
    font_name: str = "Microsoft YaHei",
    font_size: int = 80,
    text_color_rgb: str = "000000",      # text color: black for neon effect
    outline_color_rgb: str = "00FF00",   # outline/glow color: neon green
    outline_width: int = 5,              # thick outline = fluorescent glow
    margin_v: int = 30,
    play_res_x: int = 1920,
    play_res_y: int = 1080,
) -> Path:
    """
    Write ASS subtitle file with neon/fluorescent style.

    Style: black bold text with thick bright-green outline.
    The outline creates the fluorescent glow effect around each character.
    BorderStyle=1 (outline only, no background box).
    """
    # ASS color format: &HAABBGGRR (alpha, blue, green, red)
    def _rgb_to_ass(rgb_hex: str, alpha: int = 0) -> str:
        r = int(rgb_hex[0:2], 16)
        g = int(rgb_hex[2:4], 16)
        b = int(rgb_hex[4:6], 16)
        return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

    primary  = _rgb_to_ass(text_color_rgb)      # black text
    outline  = _rgb_to_ass(outline_color_rgb)   # neon green outline/glow
    secondary = "&H000000FF"                     # not displayed
    back      = "&H00000000"                     # not displayed (BorderStyle=1)

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
        f"-1,0,0,0,100,100,0,0,1,{outline_width},0,2,10,10,{margin_v},1\n"
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
        lines.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    ass_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return ass_path


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
