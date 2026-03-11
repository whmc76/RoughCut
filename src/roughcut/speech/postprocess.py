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


def normalize_text(text: str) -> str:
    """Apply punctuation cleanup and whitespace normalization."""
    # Remove leading/trailing whitespace
    text = text.strip()
    # Collapse repeated punctuation
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。.]{2,}", "。", text)
    # Remove space around Chinese characters
    text = re.sub(r"(\u4e00-\u9fff)\s+(?=\u4e00-\u9fff)", r"\1", text)
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
        text = seg.text.strip()
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
                # Split by characters with proportional time
                chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
                time_per_char = duration / max(len(text), 1)
                char_offset = 0
                for chunk in chunks:
                    chunk_start = seg.start_time + char_offset * time_per_char
                    chunk_end = chunk_start + len(chunk) * time_per_char
                    norm = normalize_text(chunk)
                    subtitles.append(SubtitleEntry(idx, chunk_start, min(chunk_end, seg.end_time), chunk, norm))
                    char_offset += len(chunk)
                    idx += 1

    return subtitles


def _split_with_words(
    text: str,
    words: list[dict],
    start_idx: int,
    max_chars: int,
    max_duration: float,
) -> list[SubtitleEntry]:
    entries: list[SubtitleEntry] = []
    current_words: list[dict] = []
    current_text = ""
    idx = start_idx

    for word in words:
        word_text = word.get("word", "")
        candidate = current_text + word_text

        seg_start = current_words[0]["start"] if current_words else word["start"]
        seg_end = word["end"]
        duration = seg_end - seg_start

        if current_words and (len(candidate) > max_chars or duration > max_duration):
            # Flush current
            norm = normalize_text(current_text)
            entries.append(
                SubtitleEntry(idx, current_words[0]["start"], current_words[-1]["end"], current_text, norm)
            )
            idx += 1
            current_words = [word]
            current_text = word_text
        else:
            current_words.append(word)
            current_text = candidate

    if current_words:
        norm = normalize_text(current_text)
        entries.append(
            SubtitleEntry(idx, current_words[0]["start"], current_words[-1]["end"], current_text, norm)
        )

    return entries


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
