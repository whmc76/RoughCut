from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping, Sequence

from roughcut.config import get_settings, llm_task_route
from roughcut.edit.subtitle_surfaces import subtitle_display_rule_text
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message


ARTIFACT_TYPE_CHAPTER_ANALYSIS = "chapter_analysis"
CHAPTER_ANALYSIS_SCHEMA = "roughcut.chapter_analysis.v1"


async def build_chapter_analysis_payload(
    *,
    source_name: str = "",
    subtitle_items: Sequence[dict[str, Any]] | None = None,
    transcript_segments: Sequence[dict[str, Any]] | None = None,
    content_profile: Mapping[str, Any] | None = None,
    duration_sec: float | None = None,
    max_chapters: int = 8,
    allow_llm: bool = True,
) -> dict[str, Any]:
    duration = _resolve_duration(duration_sec, subtitle_items=subtitle_items, transcript_segments=transcript_segments)
    evidence_rows = _chapter_evidence_rows(
        transcript_segments=transcript_segments,
        subtitle_items=subtitle_items,
        limit=90,
    )
    fingerprint = _chapter_input_fingerprint(
        source_name=source_name,
        evidence_rows=evidence_rows,
        content_profile=content_profile,
        duration_sec=duration,
    )
    base_payload = {
        "schema": CHAPTER_ANALYSIS_SCHEMA,
        "artifact_type": ARTIFACT_TYPE_CHAPTER_ANALYSIS,
        "source": "llm_chapter_analysis",
        "input_fingerprint": fingerprint,
        "duration_sec": round(duration, 3),
        "chapters": [],
        "status": "unavailable",
        "fallback_reason": "",
    }
    if not evidence_rows:
        return {
            **base_payload,
            "source": "chapter_analysis_unavailable",
            "fallback_reason": "missing_asr_timed_text",
        }
    if not allow_llm:
        return {
            **base_payload,
            "source": "chapter_analysis_disabled",
            "status": "skipped",
            "fallback_reason": "llm_disabled",
        }

    prompt = _build_chapter_prompt(
        source_name=source_name,
        evidence_rows=evidence_rows,
        content_profile=content_profile,
        duration_sec=duration,
        max_chapters=max_chapters,
    )
    try:
        settings = get_settings()
        provider = get_reasoning_provider()
        with llm_task_route("chapter_analysis", search_enabled=False, settings=settings):
            response = await provider.complete(
                [
                    Message(role="system", content="你是视频内容章节分析器，只输出严格 JSON。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.2,
                max_tokens=1400,
                json_mode=True,
            )
        raw_payload = response.as_json()
    except Exception as exc:
        return {
            **base_payload,
            "source": "chapter_analysis_failed",
            "fallback_reason": f"llm_failed:{type(exc).__name__}",
        }

    chapters = normalize_chapter_analysis_segments(raw_payload, duration_sec=duration, max_chapters=max_chapters)
    if len(chapters) < 2:
        return {
            **base_payload,
            "source": "chapter_analysis_unusable",
            "fallback_reason": "llm_returned_too_few_valid_chapters",
            "raw_status": _text(raw_payload.get("status")) if isinstance(raw_payload, dict) else "",
        }
    return {
        **base_payload,
        "status": "ready",
        "fallback_reason": "",
        "chapters": chapters,
        "chapter_count": len(chapters),
        "confidence": _coerce_confidence((raw_payload or {}).get("confidence") if isinstance(raw_payload, dict) else None),
    }


def normalize_chapter_analysis_segments(
    payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    *,
    duration_sec: float | None,
    max_chapters: int = 8,
) -> list[dict[str, Any]]:
    raw_chapters: Any
    if isinstance(payload, Mapping):
        raw_chapters = payload.get("chapters") or payload.get("segments") or []
    else:
        raw_chapters = payload or []
    if not isinstance(raw_chapters, Sequence) or isinstance(raw_chapters, (str, bytes)):
        return []
    duration = max(0.0, float(duration_sec or 0.0))
    candidates: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_chapters):
        if not isinstance(raw, Mapping):
            continue
        start = _coerce_seconds(raw.get("start_sec", raw.get("start_time", raw.get("start"))))
        end = _coerce_seconds(raw.get("end_sec", raw.get("end_time", raw.get("end"))))
        if start is None:
            continue
        if end is None:
            end = start
        summary = _text(raw.get("summary"))[:160]
        evidence = _text(raw.get("evidence"))[:160]
        title = _clean_title(
            raw.get("title_short")
            or raw.get("short_title")
            or raw.get("title")
            or raw.get("chapter_title")
            or raw.get("topic")
            or raw.get("label"),
            fallback_text=summary or evidence,
        )
        if not title:
            title = f"章节{index + 1}"
        if not title:
            continue
        candidates.append(
            {
                "index": index,
                "start_sec": max(0.0, start),
                "end_sec": max(start, end),
                "title": title,
                "summary": summary,
                "evidence": evidence,
            }
        )
    candidates.sort(key=lambda item: (float(item["start_sec"]), float(item["end_sec"])))
    if not candidates:
        return []
    limited = candidates[: max(1, min(int(max_chapters or 8), 12))]
    if duration <= 0.0:
        duration = max(float(item["end_sec"]) for item in limited)
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(limited):
        next_start = float(limited[index + 1]["start_sec"]) if index + 1 < len(limited) else duration
        start = 0.0 if index == 0 else max(float(item["start_sec"]), float(normalized[-1]["end_sec"]))
        end = max(float(item["end_sec"]), next_start if index + 1 < len(limited) else duration)
        if index + 1 < len(limited):
            end = max(start, min(end, next_start))
        if duration > 0:
            start = min(start, duration)
            end = min(max(start, end), duration)
        if end - start < 0.55:
            continue
        normalized_item = {
            "start_sec": round(start, 3),
            "end_sec": round(end, 3),
            "title": item["title"],
            "role": "semantic_topic",
            "source": "llm_chapter_analysis",
        }
        if item["summary"]:
            normalized_item["summary"] = item["summary"]
        if item["evidence"]:
            normalized_item["evidence"] = item["evidence"]
        normalized.append(normalized_item)
    if normalized and duration > 0:
        normalized[0]["start_sec"] = 0.0
        normalized[-1]["end_sec"] = round(duration, 3)
    return normalized


def _build_chapter_prompt(
    *,
    source_name: str,
    evidence_rows: Sequence[dict[str, Any]],
    content_profile: Mapping[str, Any] | None,
    duration_sec: float,
    max_chapters: int,
) -> str:
    profile = content_profile if isinstance(content_profile, Mapping) else {}
    profile_summary = {
        "subject_brand": profile.get("subject_brand"),
        "subject_model": profile.get("subject_model"),
        "subject_type": profile.get("subject_type"),
        "video_theme": profile.get("video_theme"),
        "summary": profile.get("summary"),
    }
    transcript_lines = "\n".join(
        f"{row['start_sec']:.2f}-{row['end_sec']:.2f}: {row['text']}"
        for row in evidence_rows
        if row.get("text")
    )
    return (
        "请根据 ASR 内容为视频底部进度条划分语义章节。\n"
        "要求：\n"
        f"- 章节必须表达本视频真实内容主题，不能使用固定模板；最多 {max_chapters} 段，通常 3-7 段。\n"
        "- 每段 title_short 必须是你根据本视频 ASR 自己总结的 2-8 字短标题；不要照抄示例，不要使用固定模板。\n"
        "- title 可以稍完整，title_short 用于进度条展示；如果无法概括，就输出最贴近本段内容的名词短语。\n"
        "- start_sec/end_sec 必须使用视频输出时间轴秒数，连续覆盖主要内容，边界优先贴近 ASR 话题转换处。\n"
        "- 不要逐句分段，不要按等长时间切分，不要把字幕原文直接当标题。\n"
        "- 只输出 JSON：{\"chapters\":[{\"title_short\":\"\",\"title\":\"\",\"start_sec\":0,\"end_sec\":0,\"summary\":\"\",\"evidence\":\"\"}],\"confidence\":0.0}\n\n"
        f"source_name: {source_name}\n"
        f"duration_sec: {duration_sec:.3f}\n"
        f"content_profile: {profile_summary}\n\n"
        "ASR 时间文本：\n"
        f"{transcript_lines}"
    )


def _chapter_evidence_rows(
    *,
    transcript_segments: Sequence[dict[str, Any]] | None,
    subtitle_items: Sequence[dict[str, Any]] | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = [_timed_text_row(item) for item in list(transcript_segments or [])]
    rows = [row for row in rows if row is not None]
    if not rows:
        rows = [_timed_text_row(item) for item in list(subtitle_items or [])]
        rows = [row for row in rows if row is not None]
    rows.sort(key=lambda item: (item["start_sec"], item["end_sec"]))
    return rows[:limit]


def _timed_text_row(item: Mapping[str, Any]) -> dict[str, Any] | None:
    start = _coerce_seconds(item.get("start_sec", item.get("start_time", item.get("start"))))
    end = _coerce_seconds(item.get("end_sec", item.get("end_time", item.get("end"))))
    if start is None:
        return None
    if end is None or end <= start:
        end = start + 1.0
    text = (
        _text(item.get("text_canonical"))
        or _text(item.get("canonical_text"))
        or _text(item.get("transcript_text"))
        or _text(item.get("text"))
        or subtitle_display_rule_text(dict(item))
    )
    text = " ".join(text.split())
    if not text:
        return None
    return {"start_sec": round(max(0.0, start), 3), "end_sec": round(max(start, end), 3), "text": text[:160]}


def _resolve_duration(
    duration_sec: float | None,
    *,
    subtitle_items: Sequence[dict[str, Any]] | None,
    transcript_segments: Sequence[dict[str, Any]] | None,
) -> float:
    explicit = max(0.0, float(duration_sec or 0.0))
    if explicit > 0:
        return explicit
    ends = []
    for item in [*list(subtitle_items or []), *list(transcript_segments or [])]:
        if not isinstance(item, Mapping):
            continue
        end = _coerce_seconds(item.get("end_sec", item.get("end_time", item.get("end"))))
        if end is not None:
            ends.append(end)
    return max(ends, default=0.0)


def _chapter_input_fingerprint(
    *,
    source_name: str,
    evidence_rows: Sequence[dict[str, Any]],
    content_profile: Mapping[str, Any] | None,
    duration_sec: float,
) -> str:
    profile = content_profile if isinstance(content_profile, Mapping) else {}
    parts = [
        source_name,
        f"{duration_sec:.3f}",
        _text(profile.get("subject_brand")),
        _text(profile.get("subject_model")),
        _text(profile.get("video_theme")),
    ]
    parts.extend(f"{row.get('start_sec')}:{row.get('end_sec')}:{row.get('text')}" for row in evidence_rows)
    return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _coerce_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None


def _coerce_confidence(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        parsed = 0.0
    return round(max(0.0, min(parsed, 1.0)), 3)


_CHAPTER_TITLE_SENTENCE_MARKERS = (
    "这个",
    "那个",
    "就是",
    "然后",
    "但是",
    "所以",
    "因为",
    "可能",
    "其实",
    "感觉",
    "我觉得",
    "可以说",
    "本质上",
)


def _clean_title(value: Any, *, fallback_text: str = "") -> str:
    text = _text(value)
    if not text:
        return ""
    text = text.strip(" -_：:，,。.;；")
    cleaned = _clean_llm_chapter_title(text)
    if cleaned:
        return cleaned
    fallback = _clean_llm_chapter_title(fallback_text)
    if fallback:
        return fallback
    return ""


def _clean_llm_chapter_title(value: Any) -> str:
    text = _normalize_title_text(value)
    if not text:
        return ""
    if not _title_looks_like_sentence(text) and _chapter_title_visual_units(text) <= 8.0:
        return text
    if _title_looks_like_sentence(text):
        return ""
    return _clip_chapter_title(text)


def _normalize_title_text(value: Any) -> str:
    text = _text(value)
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[\"'“”‘’《》【】\[\]()（）]", "", text)
    return text.strip(" -_：:，,。.;；！？!?")


def _title_looks_like_sentence(text: str) -> bool:
    if len(text) > 14:
        return True
    return any(marker in text for marker in _CHAPTER_TITLE_SENTENCE_MARKERS)


def _clip_chapter_title(text: str) -> str:
    normalized = _normalize_title_text(text)
    if not normalized:
        return ""
    if _chapter_title_visual_units(normalized) <= 8.0:
        return normalized
    clipped = ""
    units = 0.0
    for char in normalized:
        units += 1.0 if "\u4e00" <= char <= "\u9fff" else 0.55
        if units > 8.0:
            break
        clipped += char
    return clipped.strip(" -_：:，,。.;；！？!?")


def _chapter_title_visual_units(text: str) -> float:
    return sum(1.0 if "\u4e00" <= char <= "\u9fff" else 0.55 for char in str(text or ""))


def _text(value: Any) -> str:
    return str(value or "").strip()
