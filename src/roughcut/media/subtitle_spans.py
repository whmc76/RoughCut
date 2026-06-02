from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class SubtitleSpanUnit:
    text: str
    key: str
    start: float
    end: float
    matched: bool = True


@dataclass(frozen=True)
class SubtitleSpanAlignment:
    text: str
    units: list[SubtitleSpanUnit]
    word_text: str
    matched_ratio: float
    unmatched_prefix: str
    unmatched_suffix: str


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


def subtitle_display_text(item: dict[str, Any]) -> str:
    for key in ("projection_text", "text_final", "text_norm", "text_raw", "text"):
        value = str((item or {}).get(key) or "").strip()
        if value:
            return value
    return ""


def subtitle_display_units(text: str) -> list[str]:
    return [
        char
        for char in str(text or "")
        if char.strip() and (char.isalnum() or "\u4e00" <= char <= "\u9fff")
    ]


def subtitle_display_unit_key(char: str) -> str:
    value = str(char or "").strip().lower()
    return _CHINESE_DIGIT_KEYS.get(value, value)


def has_unsafe_unmatched_alnum_units(
    display_units: list[str],
    *,
    matched_indexes: set[int],
) -> bool:
    for index, unit in enumerate(display_units):
        if index in matched_indexes:
            continue
        if re.fullmatch(r"[A-Za-z0-9]", subtitle_display_unit_key(unit), re.IGNORECASE):
            return True
    return False


def normalized_subtitle_words(item: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, float, float]] = set()
    for raw_word in list((item or {}).get("words") or (item or {}).get("words_json") or []):
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
        normalized.append({"word": text, "start": start, "end": end})
    normalized.sort(key=lambda word: (word["start"], word["end"]))
    return normalized


def subtitle_word_span_units(item: dict[str, Any]) -> list[SubtitleSpanUnit]:
    units: list[SubtitleSpanUnit] = []
    for word in normalized_subtitle_words(item):
        chars = subtitle_display_units(str(word.get("word") or ""))
        if not chars:
            continue
        start = float(word["start"])
        end = float(word["end"])
        for char in chars:
            units.append(
                SubtitleSpanUnit(
                    text=char,
                    key=subtitle_display_unit_key(char),
                    start=start,
                    end=end,
                )
            )
    return sorted(units, key=lambda unit: (unit.start, unit.end))


def build_subtitle_span_alignment(item: dict[str, Any]) -> SubtitleSpanAlignment:
    text = subtitle_display_text(item)
    display_units = subtitle_display_units(text)
    word_units = subtitle_word_span_units(item)
    if not text or not display_units or not word_units:
        return SubtitleSpanAlignment(
            text=text,
            units=[],
            word_text="".join(unit.text for unit in word_units),
            matched_ratio=0.0,
            unmatched_prefix="",
            unmatched_suffix="",
        )

    display_keys = [subtitle_display_unit_key(char) for char in display_units]
    word_keys = [unit.key for unit in word_units]
    pairs = _lcs_index_pairs(display_keys, word_keys)
    matched_by_display = {display_index: word_index for display_index, word_index in pairs}
    matched_indexes = sorted(matched_by_display)
    if not matched_indexes:
        return SubtitleSpanAlignment(
            text=text,
            units=[],
            word_text="".join(unit.text for unit in word_units),
            matched_ratio=0.0,
            unmatched_prefix="".join(display_units),
            unmatched_suffix="".join(display_units),
        )

    units = [
        SubtitleSpanUnit(
            text=display_units[display_index],
            key=display_keys[display_index],
            start=word_units[word_index].start,
            end=word_units[word_index].end,
        )
        for display_index, word_index in pairs
    ]
    first_matched = matched_indexes[0]
    last_matched = matched_indexes[-1]
    return SubtitleSpanAlignment(
        text=text,
        units=units,
        word_text="".join(unit.text for unit in units),
        matched_ratio=len(matched_indexes) / max(1, len(display_units)),
        unmatched_prefix="".join(display_units[:first_matched]),
        unmatched_suffix="".join(display_units[last_matched + 1:]),
    )


def subtitle_span_alignment_diagnostics(item: dict[str, Any]) -> dict[str, Any]:
    alignment = build_subtitle_span_alignment(item)
    text_units = subtitle_display_units(alignment.text)
    word_units = subtitle_word_span_units(item)
    issues: list[str] = []
    if text_units and not word_units:
        issues.append("missing_word_timing")
    if word_units and not text_units:
        issues.append("missing_display_text")
    if text_units and word_units and alignment.matched_ratio < 0.6:
        issues.append("low_text_word_alignment")
    if alignment.unmatched_prefix and not _subtitle_fragment_boundary_alignment_noise(
        item,
        unmatched_text=alignment.unmatched_prefix,
        matched_ratio=alignment.matched_ratio,
        side="prefix",
    ):
        issues.append("unmatched_text_prefix")
    if alignment.unmatched_suffix and not _subtitle_fragment_boundary_alignment_noise(
        item,
        unmatched_text=alignment.unmatched_suffix,
        matched_ratio=alignment.matched_ratio,
        side="suffix",
    ):
        issues.append("unmatched_text_suffix")
    status = "ok" if not issues else "warning"
    return {
        "status": status,
        "issues": issues,
        "matched_ratio": round(alignment.matched_ratio, 4),
        "text_unit_count": len(text_units),
        "word_unit_count": len(alignment.units) if alignment.units else len(word_units),
        "timed_unit_count": len(alignment.units),
        "unmatched_prefix": alignment.unmatched_prefix,
        "unmatched_suffix": alignment.unmatched_suffix,
        "word_text": alignment.word_text,
    }


def _subtitle_fragment_boundary_alignment_noise(
    item: dict[str, Any],
    *,
    unmatched_text: str,
    matched_ratio: float,
    side: str,
) -> bool:
    unmatched_units = subtitle_display_units(unmatched_text)
    if not unmatched_units or len(unmatched_units) > 2 or matched_ratio < 0.85:
        return False
    try:
        fragment_index = int(item.get("source_fragment_index"))
        fragment_count = int(item.get("source_fragment_count"))
    except (TypeError, ValueError):
        return False
    if fragment_count <= 1:
        return False
    if side == "prefix":
        return fragment_index > 0
    if side == "suffix":
        return fragment_index < fragment_count - 1
    return False


def subtitle_span_token_payloads(item: dict[str, Any]) -> list[dict[str, Any]]:
    alignment = build_subtitle_span_alignment(item)
    return [
        {
            "text": unit.text,
            "start": round(float(unit.start), 3),
            "end": round(float(unit.end), 3),
            "source": "span_alignment",
        }
        for unit in alignment.units
        if unit.end > unit.start
    ]


def normalize_subtitle_items_for_timeline_projection(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return projection-ready items with adjacent text/word boundary drift reconciled."""
    alignments = [build_subtitle_span_alignment(item) for item in items]
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        alignment = alignments[index]
        projection_units = subtitle_display_units(alignment.text)
        if alignment.units and alignment.matched_ratio >= 0.35:
            trim_start = _boundary_trim_prefix_units(
                alignment.unmatched_prefix,
                alignments[index - 1] if index > 0 else None,
            )
            trim_end = _boundary_trim_suffix_units(
                alignment.unmatched_suffix,
                alignments[index + 1] if index + 1 < len(alignments) else None,
            )
            start_index = min(len(projection_units), trim_start)
            end_index = max(start_index, len(projection_units) - trim_end)
            if start_index or trim_end:
                projected_text = "".join(projection_units[start_index:end_index]).strip()
                if projected_text:
                    payload = dict(item)
                    payload["projection_text"] = projected_text
                    payload["projection_text_source"] = "span_alignment"
                    normalized.append(payload)
                    continue
        normalized.append(dict(item))
    return normalized


def split_text_by_timed_span_units(
    item: dict[str, Any],
    mapped_ranges: list[tuple[float, float, float, float]],
    *,
    min_matched_ratio: float = 0.35,
) -> list[str] | None:
    alignment = build_subtitle_span_alignment(item)
    if not alignment.units or alignment.matched_ratio < min_matched_ratio:
        return None
    fragments: list[str] = []
    for _new_start, _new_end, overlap_start, overlap_end in mapped_ranges:
        chars = [
            unit.text
            for unit in alignment.units
            if min(float(overlap_end), unit.end) - max(float(overlap_start), unit.start) > 0.001
        ]
        fragment_text = "".join(chars).strip()
        if not fragment_text:
            return None
        fragments.append(fragment_text)
    return fragments


def _boundary_trim_prefix_units(prefix: str, previous: SubtitleSpanAlignment | None) -> int:
    if not prefix or previous is None:
        return 0
    context = previous.word_text or "".join(unit.text for unit in previous.units) or previous.text
    overlap = _suffix_prefix_overlap(context, prefix)
    if overlap >= 2:
        return overlap
    return overlap if overlap == len(prefix) == 1 else 0


def _boundary_trim_suffix_units(suffix: str, following: SubtitleSpanAlignment | None) -> int:
    if not suffix or following is None:
        return 0
    context = following.word_text or "".join(unit.text for unit in following.units) or following.text
    overlap = _suffix_prefix_overlap(suffix, context)
    if overlap >= 2:
        return overlap
    return overlap if overlap == len(suffix) == 1 else 0


def _suffix_prefix_overlap(left: str, right: str, *, max_overlap: int = 12) -> int:
    left_units = subtitle_display_units(left)
    right_units = subtitle_display_units(right)
    limit = min(max_overlap, len(left_units), len(right_units))
    for size in range(limit, 0, -1):
        left_key = [subtitle_display_unit_key(char) for char in left_units[-size:]]
        right_key = [subtitle_display_unit_key(char) for char in right_units[:size]]
        if left_key == right_key:
            return size
    return 0


def _lcs_index_pairs(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    if not left or not right:
        return []
    rows = len(left) + 1
    cols = len(right) + 1
    dp = [[0] * cols for _ in range(rows)]
    for i, left_key in enumerate(left, start=1):
        for j, right_key in enumerate(right, start=1):
            if left_key == right_key:
                dp[i][j] = dp[i - 1][j - 1] + 1
            else:
                dp[i][j] = max(dp[i - 1][j], dp[i][j - 1])

    pairs: list[tuple[int, int]] = []
    i = len(left)
    j = len(right)
    while i > 0 and j > 0:
        if left[i - 1] == right[j - 1]:
            pairs.append((i - 1, j - 1))
            i -= 1
            j -= 1
        elif dp[i - 1][j] >= dp[i][j - 1]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs
