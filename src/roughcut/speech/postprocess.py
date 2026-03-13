from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import SubtitleItem, TranscriptSegment


@dataclass
class SubtitleEntry:
    index: int
    start: float
    end: float
    text_raw: str
    text_norm: str


# Chinese filler words / hedge words
FILLER_PATTERNS = re.compile(
    r"(?:那个|这个|嗯|啊|呃|就是|然后|对吧|对对对|好吧|这样子|那么|所以说|总的来说)+",
    re.UNICODE,
)

# Chinese number normalization: 1 -> 一, etc. (basic)
_NUM_MAP = {"0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
            "5": "五", "6": "六", "7": "七", "8": "八", "9": "九"}
_HARD_BREAK_CHARS = "。！？!?；;"
_SOFT_BREAK_CHARS = "，,、：:"
_NO_SPLIT_ENDINGS = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被",
    "然后", "所以", "但是", "而且", "并且", "会", "想", "要", "能",
)
_NO_SPLIT_PREFIXES = (
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "着", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "地", "得",
    "起来", "下来", "上来", "下去", "一下", "喜欢",
)
_GOOD_BREAK_PREFIXES = (
    "但是", "不过", "所以", "然后", "而且", "并且", "如果", "因为", "另外", "同时",
)
_BOUNDARY_PROTECTED_TERMS = (
    "螺丝",
    "螺丝刀",
    "贴片",
    "电镀",
    "渐变",
    "阳极",
    "图纸",
    "美中不足",
    "极致",
    "华丽",
    "极致华丽",
    "EDC",
    "FAS",
    "彩雕",
    "深雕",
    "雾面",
    "拉丝",
    "镜面",
    "刀刃",
    "实用性",
)


def normalize_text(text: str) -> str:
    """Apply punctuation cleanup and whitespace normalization."""
    # Remove leading/trailing whitespace
    text = text.strip()
    # Collapse repeated punctuation
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。.]{2,}", "。", text)
    text = re.sub(r"[，,]+[。.!！？]+", "。", text)
    text = re.sub(r"[。.!！？]+[，,]+", "。", text)
    # Remove space around Chinese characters
    text = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", text)
    # Ensure ends with punctuation if longer than 5 chars
    if len(text) > 5 and not text[-1] in "。！？，、…":
        text += "。"
    return text


def split_into_subtitles(
    segments: list[TranscriptSegment],
    *,
    max_chars: int = 30,
    max_duration: float = 5.0,
) -> list[SubtitleEntry]:
    """
    Split transcript segments into subtitle display units.
    Each subtitle has at most max_chars characters and max_duration seconds.
    """
    subtitles: list[SubtitleEntry] = []
    idx = 0

    for seg in segments:
        text = re.sub(r"\s+", "", seg.text.strip())
        if not text:
            continue

        words = seg.words_json or []

        # If we have word-level timing, split by words
        if words:
            subtitles.extend(_split_with_words(text, words, idx, max_chars, max_duration))
            idx += len(subtitles) - idx
        else:
            # Fall back to time-based splitting
            duration = seg.end_time - seg.start_time
            if len(text) <= max_chars and duration <= max_duration:
                norm = normalize_text(text)
                subtitles.append(SubtitleEntry(idx, seg.start_time, seg.end_time, text, norm))
                idx += 1
            else:
                chunks = _split_plain_text(text, max_chars=max_chars)
                time_per_char = duration / max(len(text), 1)
                char_offset = 0
                for chunk in chunks:
                    chunk_start = seg.start_time + char_offset * time_per_char
                    chunk_end = chunk_start + len(chunk) * time_per_char
                    norm = normalize_text(chunk)
                    subtitles.append(SubtitleEntry(idx, chunk_start, min(chunk_end, seg.end_time), chunk, norm))
                    char_offset += len(chunk)
                    idx += 1

    return _merge_continuation_entries(subtitles, max_chars=max_chars, max_duration=max_duration)


def _split_with_words(
    text: str,
    words: list[dict],
    start_idx: int,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    current_words: list[dict] = []
    idx = start_idx

    for word in words:
        word_text = re.sub(r"\s+", "", str(word.get("word", "")))
        if not word_text:
            continue
        candidate_words = current_words + [word]
        candidate = _words_to_text(candidate_words)

        seg_start = current_words[0]["start"] if current_words else word["start"]
        seg_end = word["end"]
        duration = seg_end - seg_start

        if current_words and (len(candidate) > max_chars or duration > max_duration):
            split_at = _choose_word_split_index(candidate_words, max_chars=max_chars, max_duration=max_duration)
            left_words = candidate_words[:split_at]
            right_words = candidate_words[split_at:]
            left_text = _words_to_text(left_words)
            if not left_words or not left_text:
                left_words = current_words
                right_words = [word]
                left_text = _words_to_text(left_words)
            norm = normalize_text(left_text)
            entries.append(
                SubtitleEntry(idx, left_words[0]["start"], left_words[-1]["end"], left_text, norm)
            )
            idx += 1
            current_words = right_words
        else:
            current_words = candidate_words

    if current_words:
        current_text = _words_to_text(current_words)
        norm = normalize_text(current_text)
        entries.append(
            SubtitleEntry(idx, current_words[0]["start"], current_words[-1]["end"], current_text, norm)
        )

    return _merge_continuation_entries(entries, max_chars=max_chars, max_duration=max_duration)


def _split_plain_text(text: str, *, max_chars: int) -> list[str]:
    compact = re.sub(r"\s+", "", str(text or "").strip())
    if not compact:
        return []
    chunks: list[str] = []
    remaining = compact
    while len(remaining) > max_chars:
        split_at = _choose_char_split_index(remaining, max_chars=max_chars)
        chunks.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def _choose_char_split_index(text: str, *, max_chars: int) -> int:
    limit = min(len(text) - 1, max_chars + 4)
    min_chars = min(limit, max(8, max_chars // 2))
    target = min(limit, max(10, int(max_chars * 0.78)))
    best_index = min(max_chars, len(text) - 1)
    best_score = float("-inf")
    for index in range(min_chars, limit + 1):
        score = _score_break_boundary(text[:index], text[index:], index=index, target=target)
        if score > best_score:
            best_score = score
            best_index = index
    return max(1, min(best_index, len(text) - 1))


def _choose_word_split_index(words: list[dict], *, max_chars: int, max_duration: float) -> int:
    if len(words) <= 1:
        return 1
    target = min(max_chars, max(8, int(max_chars * 0.78)))
    best_index = len(words) - 1
    best_score = float("-inf")
    for index in range(1, len(words)):
        left = _words_to_text(words[:index])
        right = _words_to_text(words[index:])
        if not left or not right:
            continue
        duration = float(words[index - 1]["end"]) - float(words[0]["start"])
        overflow_penalty = max(0.0, duration - max_duration) * 8.0
        score = _score_break_boundary(left, right, index=len(left), target=target) - overflow_penalty
        if len(left) > max_chars + 2:
            score -= (len(left) - max_chars) * 6
        if score > best_score:
            best_score = score
            best_index = index
    return max(1, min(best_index, len(words) - 1))


def _score_break_boundary(left: str, right: str, *, index: int, target: int) -> float:
    score = -abs(index - target)
    left_text = str(left or "")
    right_text = str(right or "")
    if not left_text or not right_text:
        return score - 100

    last_char = left_text[-1]
    if last_char in _HARD_BREAK_CHARS:
        score += 48
    elif last_char in _SOFT_BREAK_CHARS:
        score += 32

    if any(right_text.startswith(prefix) for prefix in _GOOD_BREAK_PREFIXES):
        score += 18

    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        score -= 24
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        score -= 26
    if _boundary_splits_protected_term(left_text, right_text):
        score -= 64

    if re.match(r"^[，。！？、：；,.!?]", right_text):
        score -= 30
    return score


def _merge_continuation_entries(
    entries: list[SubtitleEntry],
    *,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    if not entries:
        return []
    merged: list[SubtitleEntry] = []
    for entry in entries:
        if not merged:
            merged.append(entry)
            continue
        prev = merged[-1]
        combined_text = f"{prev.text_raw}{entry.text_raw}"
        combined_duration = float(entry.end) - float(prev.start)
        protected_boundary = _boundary_splits_protected_term(prev.text_raw, entry.text_raw)
        fragment_boundary = _starts_with_attached_fragment(entry.text_raw)
        allowed_chars = max_chars + 6 + (4 if protected_boundary else 0)
        short_text_bonus = 2.0 if len(combined_text) <= max(16, max_chars - 8) else 0.0
        allowed_duration = (
            max_duration
            + 1.0
            + (1.5 if protected_boundary else 0.0)
            + (0.6 if fragment_boundary else 0.0)
            + short_text_bonus
        )
        if (
            entry.start - prev.end <= 0.18
            and len(combined_text) <= allowed_chars
            and combined_duration <= allowed_duration
            and _should_merge_subtitle_pair(prev.text_raw, entry.text_raw)
        ):
            merged[-1] = SubtitleEntry(
                prev.index,
                prev.start,
                entry.end,
                combined_text,
                normalize_text(combined_text),
            )
            continue
        merged.append(entry)
    return [SubtitleEntry(i, item.start, item.end, item.text_raw, item.text_norm) for i, item in enumerate(merged)]


def _should_merge_subtitle_pair(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text[-1] in _HARD_BREAK_CHARS:
        return False
    if any(left_text.endswith(token) for token in _NO_SPLIT_ENDINGS):
        return True
    if any(right_text.startswith(token) for token in _NO_SPLIT_PREFIXES):
        return True
    if (
        left_text[-1] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and len(left_text) <= 6
        and len(right_text) >= len(left_text) + 2
    ):
        return True
    if (
        right_text[0] not in (_HARD_BREAK_CHARS + _SOFT_BREAK_CHARS)
        and len(right_text) <= 4
        and len(left_text) >= len(right_text) + 2
    ):
        return True
    if _boundary_splits_protected_term(left_text, right_text):
        return True
    if _starts_with_attached_fragment(right_text):
        return True
    if re.match(r"^[，。！？、：；,.!?]", right_text):
        return True
    return False


def _boundary_splits_protected_term(left: str, right: str) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    for term in _BOUNDARY_PROTECTED_TERMS:
        for split_at in range(1, len(term)):
            if left_text.endswith(term[:split_at]) and right_text.startswith(term[split_at:]):
                return True
    return False


def _starts_with_attached_fragment(text: str) -> bool:
    right_text = str(text or "").strip()
    if not right_text:
        return False
    match = re.match(r"^([\u4e00-\u9fffA-Za-z0-9])[，、：,.!?]", right_text)
    if not match:
        return False
    token = match.group(1)
    if token in _GOOD_BREAK_PREFIXES or token in _NO_SPLIT_PREFIXES:
        return False
    return True


def _words_to_text(words: list[dict]) -> str:
    return "".join(re.sub(r"\s+", "", str(word.get("word", ""))) for word in words)


async def save_subtitle_items(
    job_id: uuid.UUID,
    entries: list[SubtitleEntry],
    session: AsyncSession,
    version: int = 1,
) -> list[SubtitleItem]:
    """Persist subtitle entries to the database."""
    items: list[SubtitleItem] = []
    for entry in entries:
        item = SubtitleItem(
            job_id=job_id,
            version=version,
            item_index=entry.index,
            start_time=entry.start,
            end_time=entry.end,
            text_raw=entry.text_raw,
            text_norm=entry.text_norm,
        )
        session.add(item)
        items.append(item)
    await session.flush()
    return items
