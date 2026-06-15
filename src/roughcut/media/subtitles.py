"""
Subtitle utilities:
- Remap timestamps from original video timeline to edited output timeline
- Write ASS subtitle file with neon/fluorescent style: black text + bright green outline
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from roughcut.edit.subtitle_surfaces import (
    subtitle_canonical_rule_text,
    subtitle_display_rule_text,
    subtitle_raw_rule_text,
)
from roughcut.media.subtitle_spans import (
    build_subtitle_span_alignment,
    drop_redundant_synthetic_word_payloads,
    normalize_subtitle_items_for_timeline_projection,
    split_text_by_timed_span_units,
)
from roughcut.media.subtitle_text import clean_final_subtitle_text, normalize_source_transcript_text
from roughcut.speech.subtitle_segmentation import normalize_display_numbers

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
    sorted_segs = sorted(
        (
            {"start": float(segment["start"]), "end": float(segment["end"])}
            for segment in keep_segments
            if float(segment.get("end", 0.0) or 0.0) > float(segment.get("start", 0.0) or 0.0)
        ),
        key=lambda s: s["start"],
    )

    seg_map: list[dict] = []
    out_time = 0.0
    for seg in sorted_segs:
        seg_map.append({
            "in_start": seg["start"],
            "in_end":   seg["end"],
            "out_start": out_time,
        })
        out_time += seg["end"] - seg["start"]

    projection_items = normalize_subtitle_items_for_timeline_projection(
        [item for item in subtitle_items if isinstance(item, dict)]
    )

    remapped: list[dict] = []
    for item in projection_items:
        sub_start = float(item["start_time"])
        sub_end   = float(item["end_time"])

        mapped_ranges: list[tuple[float, float, float, float]] = []

        for seg in seg_map:
            overlap_in_s = max(sub_start, seg["in_start"])
            overlap_in_e = min(sub_end,   seg["in_end"])
            overlap = overlap_in_e - overlap_in_s
            if overlap <= 0.05:
                continue
            new_s = seg["out_start"] + (overlap_in_s - seg["in_start"])
            new_e = seg["out_start"] + (overlap_in_e - seg["in_start"])
            if new_e > new_s + 0.05:
                mapped_ranges.append((new_s, new_e, overlap_in_s, overlap_in_e))

        if not mapped_ranges:
            continue
        range_components = {mapped_range: [mapped_range] for mapped_range in mapped_ranges}
        mapped_ranges, range_components = _merge_short_atomic_mapped_ranges(item, mapped_ranges, range_components)
        fragment_texts = _split_remapped_subtitle_text(item, mapped_ranges)
        mapped_ranges, fragment_texts, range_components = _merge_short_remapped_text_fragments(
            mapped_ranges,
            fragment_texts,
            range_components,
        )
        raw_fragment_texts = _split_remapped_subtitle_surface_text(
            item,
            mapped_ranges,
            text=subtitle_raw_rule_text(item),
        )
        canonical_fragment_texts = _split_remapped_subtitle_surface_text(
            item,
            mapped_ranges,
            text=subtitle_canonical_rule_text(item),
        )
        emitted_ranges = [
            (mapped_range, fragment_text)
            for mapped_range, fragment_text in zip(mapped_ranges, fragment_texts)
            if str(fragment_text or "").strip()
        ]
        item_index = _subtitle_index_as_int(item.get("index"), len(remapped))
        source_index, source_indexes = _subtitle_source_index_metadata(item, item_index)
        for fragment_index, ((new_start, new_end, overlap_start, overlap_end), fragment_text) in enumerate(emitted_ranges):
            fragment_words = _remapped_fragment_word_payloads(
                item,
                (new_start, new_end, overlap_start, overlap_end),
                fragment_text=fragment_text,
                components=range_components.get((new_start, new_end, overlap_start, overlap_end)),
            )
            raw_fragment_text = (
                str(raw_fragment_texts[fragment_index] or "").strip()
                if fragment_index < len(raw_fragment_texts)
                else ""
            )
            canonical_fragment_text = (
                str(canonical_fragment_texts[fragment_index] or "").strip()
                if fragment_index < len(canonical_fragment_texts)
                else ""
            )
            remapped_item = {
                **item,
                "index": item_index,
                "source_index": source_index,
                "source_indexes": source_indexes,
                "start_time": new_start,
                "end_time": new_end,
            }
            if len(emitted_ranges) > 1:
                remapped_item["source_fragment_index"] = fragment_index
                remapped_item["source_fragment_count"] = len(emitted_ranges)
                remapped_item["source_text_full"] = _subtitle_item_display_text(item)
                remapped_item["source_overlap_start_time"] = overlap_start
                remapped_item["source_overlap_end_time"] = overlap_end
            if fragment_words:
                remapped_item["words"] = fragment_words
                remapped_item["transcript_text"] = _remapped_fragment_transcript_text(
                    item,
                    fragment_words,
                    fragment_text,
                    overlap_start=overlap_start,
                    overlap_end=overlap_end,
                )
                remapped_item = _tighten_remapped_item_to_fragment_words(remapped_item)
            remapped_item = _with_remapped_fragment_text(
                remapped_item,
                raw_text=raw_fragment_text,
                canonical_text=canonical_fragment_text,
                display_text=fragment_text,
            )
            remapped.append(remapped_item)

    return _with_unique_remapped_subtitle_indexes(remapped)


def _subtitle_index_as_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _subtitle_source_index_metadata(item: dict[str, Any], fallback: int) -> tuple[int, list[int]]:
    source_index = _subtitle_index_as_int(item.get("source_index", item.get("index")), fallback)
    raw_source_indexes = item.get("source_indexes")
    source_indexes: list[int] = []
    if isinstance(raw_source_indexes, list):
        for raw_index in raw_source_indexes:
            normalized_index = _subtitle_index_as_int(raw_index, source_index)
            if normalized_index not in source_indexes:
                source_indexes.append(normalized_index)
    if source_index not in source_indexes:
        source_indexes.insert(0, source_index)
    return source_index, source_indexes


def _with_unique_remapped_subtitle_indexes(items: list[dict]) -> list[dict]:
    index_counts: dict[int, int] = {}
    normalized_indexes: list[int] = []
    for position, item in enumerate(items):
        index = _subtitle_index_as_int(item.get("index"), position)
        normalized_indexes.append(index)
        index_counts[index] = index_counts.get(index, 0) + 1
    used_indexes: set[int] = set()
    occupied_indexes = set(normalized_indexes)
    next_index = max(occupied_indexes, default=-1) + 1
    unique_items: list[dict] = []
    for position, item in enumerate(items):
        original_index = normalized_indexes[position]
        source_index, source_indexes = _subtitle_source_index_metadata(item, original_index)
        unique_item = dict(item)
        if index_counts.get(original_index, 0) > 1:
            unique_item["source_index"] = source_index
            unique_item["source_indexes"] = source_indexes
        if original_index in used_indexes:
            while next_index in occupied_indexes or next_index in used_indexes:
                next_index += 1
            unique_item["index"] = next_index
            used_indexes.add(next_index)
            next_index += 1
        else:
            unique_item["index"] = original_index
            used_indexes.add(original_index)
        unique_items.append(unique_item)
    return unique_items


def _subtitle_item_display_text(item: dict[str, Any]) -> str:
    return subtitle_display_rule_text(item)


def _split_remapped_subtitle_surface_text(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
    *,
    text: str,
) -> list[str]:
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return ["" for _ in mapped_ranges]
    surface_item = dict(item)
    surface_item["projection_text"] = normalized_text
    surface_item["text_final"] = normalized_text
    return _split_remapped_subtitle_text(surface_item, mapped_ranges)


def _with_remapped_fragment_text(
    item: dict[str, Any],
    *,
    raw_text: str,
    canonical_text: str,
    display_text: str,
) -> dict[str, Any]:
    resolved = dict(item)
    resolved.pop("projection_text", None)
    resolved.pop("projection_text_source", None)
    if "text_raw" in resolved:
        resolved["text_raw"] = raw_text
    if "text_norm" in resolved:
        resolved["text_norm"] = canonical_text
    if "text_final" in resolved:
        resolved["text_final"] = display_text
    if "display_source_text" in resolved:
        resolved["display_source_text"] = display_text
    if "text" in resolved:
        resolved["text"] = display_text
    if not any(key in resolved for key in ("text_raw", "text_norm", "text_final", "text")):
        resolved["text_final"] = display_text
    return resolved


def _normalized_subtitle_word_payloads(item: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()
    raw_words = drop_redundant_synthetic_word_payloads(list((item or {}).get("words") or (item or {}).get("words_json") or []))
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        text = str(raw_word.get("word") or raw_word.get("raw_text") or raw_word.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(raw_word.get("start", 0.0) or 0.0)
            end = float(raw_word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        key = (text, round(start, 6), round(end, 6))
        if key in seen:
            continue
        seen.add(key)
        payload = dict(raw_word)
        payload["word"] = text
        payload["start"] = start
        payload["end"] = end
        normalized.append(payload)
    normalized.sort(key=lambda word: (float(word["start"]), float(word["end"])))
    return normalized


def _remapped_fragment_word_payloads(
    item: dict[str, Any],
    mapped_range: tuple[float, float, float, float],
    *,
    fragment_text: str = "",
    components: list[tuple[float, float, float, float]] | None = None,
) -> list[dict[str, Any]]:
    new_start, _new_end, overlap_start, overlap_end = mapped_range
    words = _normalized_subtitle_word_payloads(item)
    if not words:
        return []
    component_ranges = list(components or [mapped_range])
    clipped: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()
    for word in words:
        for component_new_start, _component_new_end, component_overlap_start, component_overlap_end in component_ranges:
            source_start = max(float(word["start"]), float(component_overlap_start))
            source_end = min(float(word["end"]), float(component_overlap_end))
            if source_end <= source_start + 0.001:
                continue
            payload = dict(word)
            payload["start"] = round(float(component_new_start) + (source_start - float(component_overlap_start)), 3)
            payload["end"] = round(float(component_new_start) + (source_end - float(component_overlap_start)), 3)
            key = (str(payload.get("word") or ""), float(payload["start"]), float(payload["end"]))
            if key in seen:
                continue
            seen.add(key)
            clipped.append(payload)
    clipped.sort(key=lambda payload: (float(payload.get("start", 0.0) or 0.0), float(payload.get("end", 0.0) or 0.0)))
    return _filter_remapped_words_to_fragment_text(clipped, fragment_text) or clipped


def _filter_remapped_words_to_fragment_text(words: list[dict[str, Any]], fragment_text: str) -> list[dict[str, Any]]:
    display_keys = [_subtitle_display_unit_key(char) for char in _subtitle_display_units(fragment_text)]
    if not words or not display_keys:
        return words
    word_units: list[dict[str, Any]] = []
    for word_index, word in enumerate(words):
        for char in _subtitle_display_units(str(word.get("word") or "")):
            word_units.append({"key": _subtitle_display_unit_key(char), "word_index": word_index})
    if not word_units:
        return words
    word_keys = [str(unit["key"]) for unit in word_units]
    match_start = _find_subsequence(word_keys, display_keys)
    if match_start < 0:
        return words
    matched_word_indexes = {
        int(word_units[match_start + offset]["word_index"])
        for offset in range(len(display_keys))
        if 0 <= match_start + offset < len(word_units)
    }
    if not matched_word_indexes:
        return words
    return [
        dict(word)
        for index, word in enumerate(words)
        if index in matched_word_indexes
    ]


def _tighten_remapped_item_to_fragment_words(item: dict[str, Any]) -> dict[str, Any]:
    words = _normalized_subtitle_word_payloads(item)
    if not words:
        return item
    word_start = min(float(word["start"]) for word in words)
    word_end = max(float(word["end"]) for word in words)
    if word_end <= word_start:
        return item
    payload = dict(item)
    try:
        row_start = float(payload.get("start_time", payload.get("start", word_start)) or word_start)
        row_end = float(payload.get("end_time", payload.get("end", word_end)) or word_end)
    except (TypeError, ValueError):
        row_start = word_start
        row_end = word_end
    if word_start >= row_start - 0.001 and word_end <= row_end + 0.001:
        payload["start_time"] = round(word_start, 3)
        payload["end_time"] = round(word_end, 3)
    return payload


def _remapped_fragment_transcript_text(
    item: dict[str, Any],
    fragment_words: list[dict[str, Any]],
    fragment_text: str,
    *,
    overlap_start: float,
    overlap_end: float,
) -> str | None:
    if fragment_words:
        transcript_joiner = (
            " "
            if " " in str((item or {}).get("transcript_text") or (item or {}).get("text_raw") or "").strip()
            else ""
        )
        transcript_text = transcript_joiner.join(
            str(word.get("word") or "").strip()
            for word in fragment_words
            if str(word.get("word") or "").strip()
        ).strip()
        if transcript_text:
            return transcript_text
    source_transcript_text = str((item or {}).get("transcript_text") or "").strip()
    if not source_transcript_text:
        return None
    return _slice_subtitle_text_by_source_overlap(
        item,
        source_transcript_text or fragment_text,
        overlap_start,
        overlap_end,
    )


def _split_remapped_subtitle_text(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
) -> list[str]:
    text = _subtitle_item_display_text(item)
    if not text:
        return [text for _ in mapped_ranges]

    if len(mapped_ranges) == 1 and _mapped_range_covers_full_subtitle(item, mapped_ranges[0]):
        return [text.strip()]

    if (dominant_fragment_texts := _dominant_fragment_texts_for_lopsided_ranges(text, mapped_ranges)) is not None:
        return dominant_fragment_texts

    span_fragment_texts = split_text_by_timed_span_units(item, mapped_ranges)
    if span_fragment_texts is not None:
        return span_fragment_texts

    display_word_fragment_texts = _split_remapped_subtitle_text_by_display_words(item, mapped_ranges)
    if display_word_fragment_texts is not None:
        return display_word_fragment_texts

    word_fragment_texts = _split_remapped_subtitle_text_by_words(item, mapped_ranges)
    if word_fragment_texts is not None:
        return word_fragment_texts

    if len(mapped_ranges) <= 1:
        if not mapped_ranges:
            return []
        _new_start, _new_end, overlap_start, overlap_end = mapped_ranges[0]
        return [_slice_subtitle_text_by_source_overlap(item, text, overlap_start, overlap_end)]

    weights = [max(0.0, float(end) - float(start)) for _new_start, _new_end, start, end in mapped_ranges]
    if sum(weights) <= 0:
        weights = [1.0 for _ in mapped_ranges]
    if " " in text.strip():
        tokens = [token for token in text.strip().split(" ") if token]
        pieces = _split_tokens_by_weights(tokens, weights)
        return [" ".join(piece).strip() for piece in pieces]
    return ["".join(piece).strip() for piece in _split_tokens_by_weights(list(text.strip()), weights)]


def _mapped_range_covers_full_subtitle(
    item: dict[str, Any],
    mapped_range: tuple[float, float, float, float],
) -> bool:
    try:
        sub_start = float(item.get("start_time", 0.0) or 0.0)
        sub_end = float(item.get("end_time", sub_start) or sub_start)
    except (TypeError, ValueError):
        return False
    _new_start, _new_end, overlap_start, overlap_end = mapped_range
    return overlap_start <= sub_start + 0.01 and overlap_end >= sub_end - 0.01


def _merge_short_atomic_mapped_ranges(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
    range_components: dict[tuple[float, float, float, float], list[tuple[float, float, float, float]]],
) -> tuple[
    list[tuple[float, float, float, float]],
    dict[tuple[float, float, float, float], list[tuple[float, float, float, float]]],
]:
    if len(mapped_ranges) <= 1:
        return mapped_ranges, range_components
    text = _subtitle_item_display_text(item)
    compact = "".join(_subtitle_display_units(text))
    if not (2 <= len(compact) <= 5):
        return mapped_ranges, range_components

    fragment_texts = _split_remapped_subtitle_text_by_display_words(item, mapped_ranges)
    if fragment_texts is None:
        fragment_texts = _split_remapped_subtitle_text_by_words(item, mapped_ranges)
    if fragment_texts is None:
        return mapped_ranges, range_components
    if "".join(str(fragment or "").strip() for fragment in fragment_texts) != compact:
        return mapped_ranges, range_components

    first = mapped_ranges[0]
    last = mapped_ranges[-1]
    merged_range = (first[0], last[1], first[2], last[3])
    merged_components: list[tuple[float, float, float, float]] = []
    for mapped_range in mapped_ranges:
        merged_components.extend(range_components.get(mapped_range, [mapped_range]))
    return [merged_range], {merged_range: merged_components}


def _merge_short_remapped_text_fragments(
    mapped_ranges: list[tuple[float, float, float, float]],
    fragment_texts: list[str],
    range_components: dict[tuple[float, float, float, float], list[tuple[float, float, float, float]]],
) -> tuple[
    list[tuple[float, float, float, float]],
    list[str],
    dict[tuple[float, float, float, float], list[tuple[float, float, float, float]]],
]:
    if len(mapped_ranges) <= 1 or len(mapped_ranges) != len(fragment_texts):
        return mapped_ranges, fragment_texts, range_components
    pairs = [
        [mapped_range, str(fragment_text or "").strip()]
        for mapped_range, fragment_text in zip(mapped_ranges, fragment_texts)
    ]
    current_components = dict(range_components)
    index = 0
    while index < len(pairs):
        mapped_range = pairs[index][0]
        text = str(pairs[index][1] or "")
        duration = max(0.0, float(mapped_range[1]) - float(mapped_range[0]))
        compact_len = len(_subtitle_display_units(text))
        if compact_len == 0:
            pairs.pop(index)
            continue
        if compact_len <= 1 and duration <= 0.55 and len(pairs) > 1:
            target_index = index + 1 if index + 1 < len(pairs) else index - 1
            target_range = pairs[target_index][0]
            merged_range = (
                min(float(target_range[0]), float(mapped_range[0])),
                max(float(target_range[1]), float(mapped_range[1])),
                min(float(target_range[2]), float(mapped_range[2])),
                max(float(target_range[3]), float(mapped_range[3])),
            )
            if target_index > index:
                pairs[target_index][1] = f"{text}{pairs[target_index][1]}".strip()
            else:
                pairs[target_index][1] = f"{pairs[target_index][1]}{text}".strip()
            pairs[target_index][0] = merged_range
            current_components[merged_range] = [
                *current_components.get(target_range, [target_range]),
                *current_components.get(mapped_range, [mapped_range]),
            ]
            current_components.pop(target_range, None)
            current_components.pop(mapped_range, None)
            pairs.pop(index)
            if target_index < index:
                index = max(0, target_index)
            continue
        index += 1
    merged_components = {
        pair[0]: current_components.get(pair[0], [pair[0]])
        for pair in pairs
    }
    return (
        [pair[0] for pair in pairs],
        [str(pair[1]) for pair in pairs],
        merged_components,
    )


def _dominant_fragment_texts_for_lopsided_ranges(
    text: str,
    mapped_ranges: list[tuple[float, float, float, float]],
) -> list[str] | None:
    if len(mapped_ranges) <= 1:
        return None
    durations = [max(0.0, float(new_end) - float(new_start)) for new_start, new_end, _start, _end in mapped_ranges]
    total_duration = sum(durations)
    if total_duration <= 0:
        return None
    dominant_index = max(range(len(durations)), key=lambda index: durations[index])
    short_durations = [duration for index, duration in enumerate(durations) if index != dominant_index]
    if not short_durations:
        return None
    if max(short_durations) > 0.45 and max(short_durations) / total_duration > 0.22:
        return None
    fragments = ["" for _ in mapped_ranges]
    fragments[dominant_index] = text.strip()
    return fragments


def _slice_subtitle_text_by_source_overlap(
    item: dict[str, Any],
    text: str,
    overlap_start: float,
    overlap_end: float,
) -> str:
    try:
        sub_start = float(item.get("start_time", 0.0) or 0.0)
        sub_end = float(item.get("end_time", sub_start) or sub_start)
    except (TypeError, ValueError):
        return text
    duration = max(0.001, sub_end - sub_start)
    if overlap_start <= sub_start + 0.01 and overlap_end >= sub_end - 0.01:
        return text
    chars = list(text.strip())
    if not chars:
        return text
    start_index = max(0, min(len(chars), round(len(chars) * max(0.0, overlap_start - sub_start) / duration)))
    end_index = max(start_index, min(len(chars), round(len(chars) * max(0.0, overlap_end - sub_start) / duration)))
    sliced = "".join(chars[start_index:end_index]).strip()
    return sliced or text


def _split_remapped_subtitle_text_by_words(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
) -> list[str] | None:
    words = _normalized_subtitle_words(item)
    if not words:
        return None
    text = _subtitle_item_display_text(item)
    joiner = " " if " " in text.strip() else ""
    fragments: list[str] = []
    for _new_start, _new_end, overlap_start, overlap_end in mapped_ranges:
        fragment_words = [
            word["word"]
            for word in words
            if min(float(overlap_end), word["end"]) - max(float(overlap_start), word["start"]) > 0.001
        ]
        fragment_text = joiner.join(fragment_words).strip()
        if not fragment_text:
            return None
        fragments.append(fragment_text)
    return fragments


def _split_remapped_subtitle_text_by_display_words(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
) -> list[str] | None:
    words = _normalized_subtitle_words(item)
    if not words:
        return None
    text = _subtitle_item_display_text(item).strip()
    if not text or " " in text:
        return None
    display_units = _subtitle_display_units(text)
    if len(display_units) < 2:
        return None
    word_units: list[dict[str, Any]] = []
    for word in words:
        for char in _subtitle_display_units(str(word.get("word") or "")):
            word_units.append(
                {
                    "key": _subtitle_display_unit_key(char),
                    "text": char,
                    "start": float(word["start"]),
                    "end": float(word["end"]),
                }
            )
    if not word_units:
        return None
    display_keys = [_subtitle_display_unit_key(char) for char in display_units]
    word_keys = [str(unit["key"]) for unit in word_units]
    match_start = _find_subsequence(word_keys, display_keys)
    if match_start < 0:
        return None
    matched_units = [
        {**word_units[match_start + offset], "text": display_units[offset]}
        for offset in range(len(display_units))
    ]
    fragments: list[str] = []
    for _new_start, _new_end, overlap_start, overlap_end in mapped_ranges:
        chars = [
            str(unit["text"])
            for unit in matched_units
            if min(float(overlap_end), float(unit["end"])) - max(float(overlap_start), float(unit["start"])) > 0.001
        ]
        fragment_text = "".join(chars).strip()
        if not fragment_text:
            return None
        fragments.append(fragment_text)
    return fragments


def _subtitle_display_units(text: str) -> list[str]:
    return [
        char
        for char in str(text or "")
        if char.strip() and (char.isalnum() or "\u4e00" <= char <= "\u9fff")
    ]


_CHINESE_DIGIT_KEYS = {
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}


def _subtitle_display_unit_key(char: str) -> str:
    value = str(char or "").strip().lower()
    return _CHINESE_DIGIT_KEYS.get(value, value)


def _find_subsequence(values: list[str], target: list[str]) -> int:
    if not target or len(target) > len(values):
        return -1
    for index in range(0, len(values) - len(target) + 1):
        if values[index:index + len(target)] == target:
            return index
    return -1


def _normalized_subtitle_words(item: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    raw_words = drop_redundant_synthetic_word_payloads(list((item or {}).get("words") or (item or {}).get("words_json") or []))
    for raw_word in raw_words:
        if not isinstance(raw_word, dict):
            continue
        text = str(raw_word.get("word") or raw_word.get("raw_text") or raw_word.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(raw_word.get("start", 0.0) or 0.0)
            end = float(raw_word.get("end", start) or start)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        normalized.append({"word": text, "start": start, "end": end})
    normalized.sort(key=lambda word: (word["start"], word["end"]))
    return normalized


def _split_tokens_by_weights(tokens: list[str], weights: list[float]) -> list[list[str]]:
    if not weights:
        return []
    if not tokens:
        return [[] for _ in weights]

    total_weight = sum(max(0.0, weight) for weight in weights) or float(len(weights))
    token_count = len(tokens)
    pieces: list[list[str]] = []
    cursor = 0
    for index, weight in enumerate(weights):
        remaining_fragments = len(weights) - index
        remaining_tokens = token_count - cursor
        if index == len(weights) - 1:
            take = remaining_tokens
        else:
            ideal_end = round(token_count * sum(weights[: index + 1]) / total_weight)
            take = max(0, int(ideal_end) - cursor)
            if remaining_tokens > remaining_fragments - 1:
                take = max(1, take)
            take = min(take, max(0, remaining_tokens - (remaining_fragments - 1)))
        pieces.append(tokens[cursor: cursor + take])
        cursor += take
    return pieces


def split_subtitle_display_item(
    *,
    start_time: float,
    end_time: float,
    text: str,
    subtitle_item: dict[str, Any] | None = None,
    max_duration_sec: float = 6.0,
    max_chars: int = 32,
) -> list[dict[str, Any]]:
    duration = max(0.0, float(end_time) - float(start_time))
    compact_len = len(str(text or "").replace(" ", ""))
    if duration <= max_duration_sec and compact_len <= max_chars:
        return [{"start_time": start_time, "end_time": end_time, "text": text}]

    target_chars = min(max_chars, max(12, int(max_chars * max_duration_sec / max(duration, 0.001))))
    pieces = split_subtitle_display_text(text, max_chars=target_chars)
    if len(pieces) <= 1:
        return [{"start_time": start_time, "end_time": end_time, "text": text}]

    if subtitle_item:
        aligned_segments = _split_subtitle_display_item_with_timed_alignment(
            subtitle_item=subtitle_item,
            start_time=float(start_time),
            end_time=float(end_time),
            pieces=pieces,
        )
        if aligned_segments is not None:
            return aligned_segments

    weights = [max(1, len(piece.replace(" ", ""))) for piece in pieces]
    total_weight = sum(weights) or len(pieces)
    cursor = float(start_time)
    segments: list[dict[str, Any]] = []
    for index, (piece, weight) in enumerate(zip(pieces, weights)):
        if index == len(pieces) - 1:
            next_cursor = float(end_time)
        else:
            next_cursor = min(float(end_time), cursor + duration * (weight / total_weight))
        if next_cursor <= cursor:
            next_cursor = min(float(end_time), cursor + 0.18)
        segments.append({"start_time": round(cursor, 3), "end_time": round(next_cursor, 3), "text": piece})
        cursor = next_cursor
    return segments


def resolve_subtitle_serialization_text(item: dict[str, Any]) -> str:
    if str((item or {}).get("display_suppressed_reason") or "").strip():
        return ""
    display_text = clean_final_subtitle_text(subtitle_display_rule_text(item))
    source_text = _subtitle_serialization_source_text(item)
    if not display_text:
        return source_text
    if not source_text:
        return display_text

    normalized_source_display = clean_final_subtitle_text(normalize_display_numbers(source_text))
    if _compact_subtitle_text(normalized_source_display) == _compact_subtitle_text(display_text):
        return display_text

    display_key = _compact_subtitle_text(display_text)
    source_key = _compact_subtitle_text(source_text)
    if len(display_key) >= 4 and len(source_key) >= 4:
        common_length = _subtitle_common_subsequence_length(source_key, display_key)
        source_missing_units = len(source_key) - common_length
        display_coverage = common_length / max(1, len(display_key))
        source_coverage = common_length / max(1, len(source_key))
        if display_coverage >= 0.98 and source_missing_units >= 2:
            return source_text
        if source_missing_units >= 2 and source_coverage >= 0.68:
            return source_text
        if display_coverage < 0.72 and len(source_key) > len(display_key):
            return source_text
    if len(display_key) >= 4 and len(source_key) >= 4 and display_key in source_key and len(source_key) - len(display_key) >= 2:
        return source_text

    alignment_item = dict(item)
    alignment_item["projection_text"] = display_text
    alignment_item["text_final"] = display_text
    alignment = build_subtitle_span_alignment(alignment_item)
    unmatched_edge_units = len(_subtitle_display_units(alignment.unmatched_prefix)) + len(
        _subtitle_display_units(alignment.unmatched_suffix)
    )
    if alignment.matched_ratio >= 0.82 and unmatched_edge_units <= 2:
        return display_text

    if len(display_key) < 4 or len(source_key) < 4:
        return display_text

    return display_text


def build_serialization_subtitle_item(item: dict[str, Any]) -> tuple[dict[str, Any], str]:
    serialization_text = resolve_subtitle_serialization_text(item)
    if not serialization_text:
        return dict(item), ""
    payload = dict(item)
    payload["projection_text"] = serialization_text
    payload["text_final"] = serialization_text
    if "display_source_text" in payload:
        payload["display_source_text"] = serialization_text
    return payload, serialization_text


def _subtitle_serialization_source_text(item: dict[str, Any]) -> str:
    words = _normalized_subtitle_words(item)
    if words:
        transcript_hint = str(
            (item or {}).get("transcript_text")
            or (item or {}).get("text_raw")
            or (item or {}).get("text_norm")
            or ""
        ).strip()
        joiner = " " if " " in transcript_hint else ""
        word_text = joiner.join(str(word.get("word") or "").strip() for word in words if str(word.get("word") or "").strip())
        cleaned_word_text = normalize_source_transcript_text(word_text)
        if cleaned_word_text:
            return cleaned_word_text
    for candidate in (
        str((item or {}).get("transcript_text") or "").strip(),
        str((item or {}).get("text_norm") or "").strip(),
        str((item or {}).get("text_raw") or "").strip(),
    ):
        cleaned_candidate = normalize_source_transcript_text(candidate)
        if cleaned_candidate:
            return cleaned_candidate
    return ""


def _split_subtitle_display_item_with_timed_alignment(
    *,
    subtitle_item: dict[str, Any],
    start_time: float,
    end_time: float,
    pieces: list[str],
) -> list[dict[str, Any]] | None:
    alignment = build_subtitle_span_alignment(subtitle_item)
    if not alignment.units or alignment.matched_ratio < 0.72:
        return None
    piece_unit_counts = [len(_subtitle_display_units(piece)) for piece in pieces]
    total_piece_units = sum(piece_unit_counts)
    if total_piece_units <= 0:
        return None

    total_aligned_units = len(alignment.units)
    segments: list[dict[str, Any]] = []
    cursor = 0
    for index, (piece, piece_unit_count) in enumerate(zip(pieces, piece_unit_counts)):
        if not piece_unit_count:
            continue
        remaining_segments = len(pieces) - index
        remaining_units = total_aligned_units - cursor
        if remaining_units <= 0:
            return None
        if index == len(pieces) - 1:
            next_cursor = total_aligned_units
        else:
            ideal_end = round(total_aligned_units * sum(piece_unit_counts[: index + 1]) / total_piece_units)
            next_cursor = max(cursor + 1, ideal_end)
            next_cursor = min(next_cursor, total_aligned_units - (remaining_segments - 1))
        slice_units = alignment.units[cursor:next_cursor]
        if not slice_units:
            return None
        segment_start = max(float(start_time), float(slice_units[0].start))
        segment_end = min(float(end_time), float(slice_units[-1].end))
        if segment_end <= segment_start:
            return None
        segments.append(
            {
                "start_time": round(segment_start, 3),
                "end_time": round(segment_end, 3),
                "text": piece,
            }
        )
        cursor = next_cursor

    if not segments:
        return None
    segments[0]["start_time"] = round(float(start_time), 3)
    segments[-1]["end_time"] = round(float(end_time), 3)
    previous_end = float(segments[0]["start_time"])
    for segment in segments:
        segment_start = max(previous_end, float(segment["start_time"]))
        segment_end = max(segment_start + 0.001, float(segment["end_time"]))
        segment["start_time"] = round(segment_start, 3)
        segment["end_time"] = round(min(float(end_time), segment_end), 3)
        previous_end = float(segment["end_time"])
    if any(float(segment["end_time"]) <= float(segment["start_time"]) for segment in segments):
        return None
    return segments


def _compact_subtitle_text(value: str) -> str:
    return re.sub(r"[\s，,。.!！?？、；;：:“”\"'‘’（）()[\]【】]+", "", str(value or ""))


def _subtitle_common_subsequence_length(left: str, right: str) -> int:
    left_chars = list(str(left or ""))
    right_chars = list(str(right or ""))
    if not left_chars or not right_chars:
        return 0
    previous = [0] * (len(right_chars) + 1)
    for left_char in left_chars:
        diagonal = 0
        for right_index, right_char in enumerate(right_chars):
            saved = previous[right_index + 1]
            previous[right_index + 1] = (
                diagonal + 1
                if left_char == right_char
                else max(previous[right_index + 1], previous[right_index])
            )
            diagonal = saved
    return previous[-1]


def split_subtitle_display_text(text: str, *, max_chars: int) -> list[str]:
    normalized = re.sub(r"\s{2,}", " ", str(text or "").strip())
    if not normalized:
        return []
    max_chars = max(1, int(max_chars or 1))
    tokens = normalized.split(" ")
    if len(tokens) <= 1:
        compact = normalized.replace(" ", "")
        if len(compact) <= max_chars:
            return [normalized]
        return [compact[index:index + max_chars] for index in range(0, len(compact), max_chars)]

    pieces: list[str] = []
    current = ""
    for token in tokens:
        compact_token = token.replace(" ", "")
        if len(compact_token) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(
                compact_token[index:index + max_chars]
                for index in range(0, len(compact_token), max_chars)
            )
            continue
        candidate = f"{current} {token}".strip() if current else token
        if len(candidate.replace(" ", "")) <= max_chars:
            current = candidate
            continue
        if current:
            pieces.append(current)
        current = token
    if current:
        pieces.append(current)
    return pieces


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
        style_id = str(item.get("style_name") or "").strip()
        if not style_id or style_id not in style_definitions:
            style_id = "Default"
        style_definition = style_definitions[style_id]
        max_chars_per_line = _estimate_subtitle_line_capacity(
            play_res_x=play_res_x,
            font_size=int(style_definition["font_size"]),
        )
        serialization_item, text = build_serialization_subtitle_item(item)
        if not text:
            continue
        for display_segment in split_subtitle_display_item(
            start_time=float(item["start_time"]),
            end_time=float(item["end_time"]),
            text=str(text),
            subtitle_item=serialization_item,
            max_chars=max_chars_per_line * 2,
        ):
            segment_text = str(display_segment["text"])
            segment_text = _wrap_subtitle_text(
                segment_text,
                max_chars_per_line=max_chars_per_line,
                max_lines=2,
                preserve_terms=_collect_highlight_preserve_terms(
                    segment_text,
                    item=item,
                    style_name=str(item.get("style_name") or style_id or "Default").strip() or "Default",
                ),
            )
            segment_text = _apply_keyword_highlight_markup(
                segment_text,
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
                f"Dialogue: 0,{_ass_time(float(display_segment['start_time']))},"
                f"{_ass_time(float(display_segment['end_time']))},{style_id},,0,0,{item_margin_v},,"
                f"{_build_motion_tag(segment_text, resolved_motion_style)}"
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
