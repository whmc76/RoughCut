from __future__ import annotations

import difflib
import math
import re
from dataclasses import dataclass

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming

_ALIGNMENT_MODE_OPTIONS = {"auto", "provider_only", "synthetic"}
_ALIGNMENT_PUNCTUATION = set("，。！？!?；;：:,、（）()[]【】{}\"'《》<>")
_SINGLE_CHAR_FUNCTION_TOKENS = {
    "的", "了", "呢", "吗", "嘛", "啊", "呀", "哦", "哈", "把", "给", "在", "向", "和", "与", "及",
    "就", "也", "还", "很", "都", "又", "才", "再", "并", "跟", "让", "被", "地", "得", "是", "有",
    "我", "你", "他", "她", "它", "这", "那", "会", "要", "能", "可", "先", "再",
}
_MULTI_CHAR_ATOMIC_TOKENS = (
    "狐蝠工业",
    "我们",
    "你们",
    "他们",
    "它们",
    "他妈",
    "这个",
    "那个",
    "特色",
    "手感",
    "设计",
    "工业",
    "狐蝠",
    "配色",
    "版本",
    "胸包",
    "副包",
    "小副包",
    "对比",
    "开箱",
    "产品",
    "细节",
    "参数",
    "质感",
    "容量",
    "尺寸",
    "起来",
    "下来",
    "上来",
    "下去",
    "一下",
    "而且",
    "并且",
    "但是",
    "如果",
    "因为",
    "所以",
    "然后",
    "已经",
    "觉得",
    "结构",
    "顺手",
    "磁吸",
    "尾盖",
    "夜骑",
    "补光",
)


@dataclass(slots=True)
class AlignmentSettings:
    mode: str = "auto"
    min_word_coverage: float = 0.72


def enhance_transcript_alignment(
    result: TranscriptResult,
    *,
    settings: AlignmentSettings | None = None,
) -> TranscriptResult:
    resolved = settings or AlignmentSettings()
    mode = str(resolved.mode or "auto").strip().lower()
    if mode not in _ALIGNMENT_MODE_OPTIONS:
        mode = "auto"

    coverage_sum = 0.0
    coverage_count = 0
    provider_word_segments = 0
    synthesized_segments = 0
    usable_segments = 0

    for index, segment in enumerate(result.segments):
        normalized_words = _normalize_word_timings(segment.words, fallback_start=segment.start, fallback_end=segment.end)
        assessment = _assess_word_alignment(segment.text, normalized_words, min_word_coverage=float(resolved.min_word_coverage))
        final_words = normalized_words
        source = "provider"
        if mode == "provider_only":
            source = "provider" if assessment["usable"] else "provider_missing"
        elif mode == "synthetic":
            final_words = _synthesize_word_timings(segment, reference_words=normalized_words)
            source = "synthetic" if final_words else "segment_only"
        elif not assessment["usable"]:
            final_words = _synthesize_word_timings(segment, reference_words=normalized_words)
            source = "synthetic" if final_words else "segment_only"

        segment.words = final_words
        if assessment["word_count"] > 0:
            provider_word_segments += 1
            coverage_sum += float(assessment["coverage"])
            coverage_count += 1
        if assessment["usable"]:
            usable_segments += 1
        if source == "synthetic":
            synthesized_segments += 1

        segment.alignment = _annotate_alignment_payload(
            segment.alignment,
            source=source,
            coverage=float(assessment["coverage"]),
            word_count=len(final_words),
            segment_index=index,
        )
        for word in segment.words:
            word.alignment = _annotate_alignment_payload(
                word.alignment,
                source=source if source != "provider" else "provider",
                coverage=float(assessment["coverage"]),
                word_count=len(segment.words),
                segment_index=index,
            )

    average_coverage = (coverage_sum / coverage_count) if coverage_count else 0.0
    result.alignment = {
        "mode": mode,
        "segments_total": len(result.segments),
        "segments_with_provider_words": provider_word_segments,
        "segments_with_usable_provider_words": usable_segments,
        "segments_with_synthesized_words": synthesized_segments,
        "average_provider_word_coverage": round(average_coverage, 4),
    }
    return result


def _annotate_alignment_payload(existing: object, **metadata: object) -> object:
    payload = {key: value for key, value in metadata.items()}
    if isinstance(existing, dict):
        merged = dict(existing)
        roughcut_meta = dict(merged.get("_roughcut") or {})
        roughcut_meta.update(payload)
        merged["_roughcut"] = roughcut_meta
        return merged
    if existing is None:
        return {"_roughcut": payload}
    return {"provider_alignment": existing, "_roughcut": payload}


def _normalize_word_timings(words: list[WordTiming], *, fallback_start: float, fallback_end: float) -> list[WordTiming]:
    normalized: list[WordTiming] = []
    for word in words or []:
        text = str(word.word or "").strip()
        if not text:
            continue
        start = _coerce_time(word.start, fallback=fallback_start)
        end = _coerce_time(word.end, fallback=max(start, fallback_end))
        normalized.append(
            WordTiming(
                word=text,
                start=start,
                end=max(start, end),
                provider=word.provider,
                model=word.model,
                raw_payload=dict(word.raw_payload or {}),
                raw_text=word.raw_text,
                context=word.context,
                hotword=word.hotword,
                confidence=word.confidence,
                logprob=word.logprob,
                alignment=word.alignment,
            )
        )
    normalized.sort(key=lambda item: (item.start, item.end))
    return normalized


def _assess_word_alignment(text: str, words: list[WordTiming], *, min_word_coverage: float) -> dict[str, float | int | bool]:
    compact_text = _compact_alignment_text(text)
    compact_words = _compact_alignment_text("".join(item.word for item in words))
    if not compact_text:
        return {"coverage": 1.0, "word_count": len(words), "usable": bool(words)}
    if not compact_words:
        return {"coverage": 0.0, "word_count": 0, "usable": False}
    coverage = difflib.SequenceMatcher(a=compact_words, b=compact_text).ratio()
    timed_words = [
        item for item in words
        if math.isfinite(float(item.start)) and math.isfinite(float(item.end)) and float(item.end) >= float(item.start)
    ]
    timed_ratio = len(timed_words) / max(1, len(words))
    usable = coverage >= min_word_coverage and timed_ratio >= 0.7
    return {
        "coverage": coverage,
        "word_count": len(words),
        "usable": usable,
    }


def _synthesize_word_timings(segment: TranscriptSegment, *, reference_words: list[WordTiming]) -> list[WordTiming]:
    tokens = tokenize_alignment_text(segment.text)
    if not tokens:
        return []

    duration = max(0.0, float(segment.end) - float(segment.start))
    total_weight = sum(_token_weight(token) for token in tokens)
    if total_weight <= 0.0:
        total_weight = float(len(tokens))

    cursor = float(segment.start)
    synthesized: list[WordTiming] = []
    for index, token in enumerate(tokens):
        weight = _token_weight(token)
        slice_duration = duration * weight / total_weight if duration > 0 else 0.0
        end = float(segment.end) if index == len(tokens) - 1 else cursor + slice_duration
        payload: dict[str, object] = {}
        if index < len(reference_words):
            payload.update(dict(reference_words[index].raw_payload or {}))
            payload["reference_word"] = reference_words[index].word
        if "source" not in payload:
            payload["source"] = "roughcut_synthesized"
        else:
            payload["_roughcut_source"] = "roughcut_synthesized"
        synthesized.append(
            WordTiming(
                word=token,
                start=round(cursor, 3),
                end=round(max(cursor, end), 3),
                provider=segment.provider,
                model=segment.model,
                raw_payload=payload,
                raw_text=token,
                context=segment.context,
                hotword=segment.hotword,
                confidence=segment.confidence,
                logprob=segment.logprob,
                alignment={"source": "roughcut_synthesized"},
            )
        )
        cursor = end
    return synthesized


def tokenize_alignment_text(text: str) -> list[str]:
    normalized = str(text or "").strip()
    if not normalized:
        return []

    if " " in normalized:
        spaced = [chunk.strip() for chunk in normalized.split() if chunk.strip()]
        if len(spaced) >= 2:
            return [_strip_outer_punctuation(chunk) for chunk in spaced if _strip_outer_punctuation(chunk)]

    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_\-./]*|[\u4e00-\u9fff]+|[^\s]", normalized):
        chunk = str(match.group(0) or "").strip()
        if not chunk:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            tokens.extend(_chunk_cjk_tokens(chunk))
        elif chunk in _ALIGNMENT_PUNCTUATION:
            if tokens:
                tokens[-1] = f"{tokens[-1]}{chunk}"
            else:
                tokens.append(chunk)
        else:
            tokens.append(chunk)
    return [token for token in tokens if token]


def _chunk_cjk_tokens(chunk: str) -> list[str]:
    text = str(chunk or "")
    if not text:
        return []

    tokens: list[str] = []
    index = 0
    while index < len(text):
        for atomic in _MULTI_CHAR_ATOMIC_TOKENS:
            if text.startswith(atomic, index):
                tokens.append(atomic)
                index += len(atomic)
                break
        else:
            char = text[index]
            remaining = len(text) - index
            if char in _SINGLE_CHAR_FUNCTION_TOKENS or remaining == 1:
                tokens.append(char)
                index += 1
                continue
            if remaining == 3 and text[index + 2] in _SINGLE_CHAR_FUNCTION_TOKENS:
                tokens.append(text[index:index + 2])
                tokens.append(text[index + 2])
                break
            tokens.append(text[index:index + 2])
            index += 2
    return tokens


def _strip_outer_punctuation(token: str) -> str:
    value = str(token or "").strip()
    return value.strip("，。！？!?；;：:,、（）()[]【】{}\"'《》<>")


def _token_weight(token: str) -> float:
    value = str(token or "")
    if not value:
        return 0.0
    if all(char in _ALIGNMENT_PUNCTUATION for char in value):
        return 0.35
    if re.fullmatch(r"[A-Za-z0-9_\-./]+", value):
        return max(1.0, len(value) * 0.8)
    return max(0.8, float(len(value)))


def _coerce_time(value: object, *, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(fallback)
    if not math.isfinite(number):
        return float(fallback)
    return max(0.0, number)


def _compact_alignment_text(text: str) -> str:
    return re.sub(r"[\s，。！？!?；;：:,、（）()[]【】{}\"'《》<>]+", "", str(text or "").strip())
