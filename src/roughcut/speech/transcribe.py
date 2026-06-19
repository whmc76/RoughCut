from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import Artifact, FactClaim, JobStep, SubtitleCorrection, SubtitleItem, TranscriptSegment
from roughcut.config import get_settings
from roughcut.media.subtitle_spans import (
    drop_redundant_synthetic_word_payloads,
    has_unsafe_unmatched_alnum_units,
    subtitle_display_unit_key,
    subtitle_display_units,
    word_payloads_have_collapsed_timing,
)
from roughcut.media.subtitle_text import normalize_flashlight_model_alias_text, normalize_source_transcript_text
from roughcut.providers.factory import get_transcription_provider, resolve_transcription_provider_plan
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment as ProviderTranscriptSegment, TranscriptionProgressCallback, WordTiming
from roughcut.providers.transcription.chunking import extract_chunking_summary
from roughcut.review.evidence_types import ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE
from roughcut.review.hotword_learning import extract_prompt_hotwords, record_prompted_hotwords
from roughcut.review.subtitle_memory import resolve_transcription_category_scope
from roughcut.speech.alignment import AlignmentSettings, enhance_transcript_alignment
from roughcut.speech.subtitle_pipeline import (
    ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
    build_transcript_fact_layer_from_result,
)

ARTIFACT_TYPE_ASR_QUALITY_GATE = "asr_quality_gate"


class AsrQualityGateError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: list[dict[str, str]],
        rejected_attempts: list[dict[str, Any]],
    ) -> None:
        super().__init__(message)
        self.attempts = attempts
        self.rejected_attempts = rejected_attempts
        self.payload = {
            "status": "rejected",
            "reason": "asr_quality_gate",
            "message": message,
            "attempts": attempts,
            "rejected_attempts": rejected_attempts,
        }

_TRANSCRIPT_TAIL_CTA_NOISE_RE = re.compile(
    r"(感谢观看|请不吝点赞|打赏支持|"
    r"点赞.{0,8}(订阅|关注|收藏|转发)|"
    r"(订阅|关注|收藏).{0,8}点赞|"
    r"转发.{0,8}(点赞|订阅|关注|收藏))",
    re.IGNORECASE,
)
_SEMANTIC_HALLUCINATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"鱼头的小章鱼"), ""),
    (re.compile(r"新品小车"), ""),
)
_DUPLICATE_BRAND_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:FOXBAT|Foxbat)\s*(?:DYNAMICS)?\s*(?:Foxbat)?\s*工业", re.IGNORECASE), "狐蝠工业"),
    (re.compile(r"(?:FOXBAT|Foxbat)\s*狐蝠工业", re.IGNORECASE), "狐蝠工业"),
    (
        re.compile(
            r"狐蝠工业(?:\s|x|HSJUN|BOLTBOAT|勃朗峰户外)+狐蝠工业(?:工业)?",
            re.IGNORECASE,
        ),
        "狐蝠工业",
    ),
    (re.compile(r"(狐蝠工业){2,}", re.IGNORECASE), "狐蝠工业"),
    (re.compile(r"狐蝠工业工业+", re.IGNORECASE), "狐蝠工业"),
    (re.compile(r"(勃朗峰户外){2,}", re.IGNORECASE), "勃朗峰户外"),
    (re.compile(r"(NITECORE){2,}", re.IGNORECASE), "NITECORE"),
    (re.compile(r"(OLIGHT){2,}", re.IGNORECASE), "OLIGHT"),
)
_ADJACENT_DUPLICATE_MODEL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?P<token>[A-Za-z]{1,10}[-_]?\d[A-Za-z0-9_-]{0,12})(?:\s+(?P=token)){1,}(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_FLASHLIGHT_CONTAMINATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"电折刀"), "手电"),
    (re.compile(r"\bEDC(17|23|37)折刀(?:帕)?\b", re.IGNORECASE), r"EDC\1"),
    (re.compile(r"(?<![A-Za-z0-9])幺[七7](?![A-Za-z0-9])"), "EDC17"),
)
_FLASHLIGHT_EDC_ALT_LIST_RE = re.compile(
    r"(?<![A-Za-z0-9])(EDC(?:17|23|37))(?:\s*/\s*(EDC(?:17|23|37)))+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_FLASHLIGHT_EDC_ALT_SEQUENCE_RE = re.compile(
    r"(?<![A-Za-z0-9])(EDC(?:17|23|37))(?:[\s/、，,]+(EDC(?:17|23|37)))+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_KNIFE_MATERIAL_SURFACE_MISHEARD_RE = re.compile(r"钢瓦|盖瓦|锆瓦|(?:钢马|锆马).{0,16}泛光")
_LOCAL_ASR_PROVIDER = "local_http_asr"
_ASR_FUNCTION_STUTTER_RE = re.compile(
    r"(?P<char>[啊呃嗯哦哎诶呀呢嘛吧吗还就也都又再没不很太是的了个这那我你他她它给把])(?P=char)"
    r"(?=[\u4e00-\u9fff，,。！？!?、])"
)
_ASR_PREFIX_STUTTER_RE = re.compile(r"(?P<char>[\u4e00-\u9fff])(?P=char)(?=[\u4e00-\u9fff])")
_ASR_REPEAT_ALLOWED_CHARS = frozenset(
    "一二三四五六七八九零两"
    "试看想听说讲问找拿用摸擦敲聊闻尝轻慢快小大多少点微静悄渐晃摇拉推按翻搓揉洗刷切削划扫"
)
_ASR_REPEAT_ALLOWED_PREFIXES = frozenset(("开开箱", "一点点"))
_ASR_NO_TIMING_ADVISORY_DUPLICATES = frozenset(("哈哈", "嘿嘿", "呵呵", "嘻嘻", "哼哼", "哒哒", "啦啦"))


def _is_brand_like_term(term: dict) -> bool:
    category = str(term.get("category") or "").strip().lower()
    return bool(category and "brand" in category)


def _compact_transcript_noise_text(text: str) -> str:
    return re.sub(r"[\s\u3000,，.。!！?？:：;；/\\|_\-]+", "", str(text or ""))


def _looks_like_tail_cta_noise(text: str) -> bool:
    compact = _compact_transcript_noise_text(text)
    if not compact or len(compact) > 40:
        return False
    if "感谢观看" in compact:
        return True
    if "请不吝点赞" in compact or "打赏支持" in compact:
        return True
    return bool(_TRANSCRIPT_TAIL_CTA_NOISE_RE.search(compact))


def _is_tail_noise_candidate(
    *,
    order_index: int,
    segment_count: int,
    start: float,
    end: float,
    duration: float,
) -> bool:
    if end <= start or (end - start) > 8.0:
        return False
    if order_index >= max(segment_count - 2, 0):
        return True
    tail_start = max(duration - 20.0, duration * 0.85)
    return end >= tail_start


def _filter_tail_cta_noise_segments(result: TranscriptResult) -> list[dict[str, Any]]:
    segment_count = len(list(result.segments or []))
    if segment_count <= 0:
        return []

    duration = max(
        float(result.duration or 0.0),
        max((float(getattr(seg, "end", 0.0) or 0.0) for seg in list(result.segments or [])), default=0.0),
    )
    kept_segments: list[ProviderTranscriptSegment] = []
    dropped_segments: list[dict[str, Any]] = []
    for order_index, seg in enumerate(list(result.segments or [])):
        start = float(getattr(seg, "start", 0.0) or 0.0)
        end = float(getattr(seg, "end", 0.0) or 0.0)
        text = str(getattr(seg, "raw_text", None) or getattr(seg, "text", "") or "").strip()
        if (
            text
            and _is_tail_noise_candidate(
                order_index=order_index,
                segment_count=segment_count,
                start=start,
                end=end,
                duration=duration,
            )
            and _looks_like_tail_cta_noise(text)
        ):
            dropped_segments.append(
                {
                    "index": int(getattr(seg, "index", order_index) or order_index),
                    "start": start,
                    "end": end,
                    "text": str(getattr(seg, "text", "") or ""),
                    "raw_text": str(getattr(seg, "raw_text", None) or getattr(seg, "text", "") or ""),
                    "reason": "tail_cta_noise",
                }
            )
            continue
        kept_segments.append(seg)
    if dropped_segments:
        result.segments = kept_segments
        filtering = dict(result.raw_payload.get("_roughcut_filtering") or {})
        filtering["dropped_tail_cta_segments"] = dropped_segments
        result.raw_payload["_roughcut_filtering"] = filtering
    return dropped_segments


def _normalize_semantic_contamination_text(text: str, *, category_scope: str) -> str:
    normalized = str(text or "").strip()
    if str(category_scope or "").strip().lower() == "flashlight":
        normalized = normalize_flashlight_model_alias_text(normalized)
    return normalized


def _collapse_flashlight_edc_alt_lists(text: str) -> str:
    """Collapse ASR alternative lists like "EDC17 / EDC37 / EDC37"."""

    def replace(match: re.Match[str]) -> str:
        models = re.findall(r"EDC(?:17|23|37)", match.group(0), flags=re.IGNORECASE)
        normalized = [item.upper() for item in models]
        if len(normalized) >= 3 or len(set(normalized)) < len(normalized):
            return normalized[0]
        return match.group(0)

    collapsed = _FLASHLIGHT_EDC_ALT_LIST_RE.sub(replace, text)
    return _FLASHLIGHT_EDC_ALT_SEQUENCE_RE.sub(replace, collapsed)


def _normalize_knife_material_surface_text(text: str) -> str:
    if not _KNIFE_MATERIAL_SURFACE_MISHEARD_RE.search(text):
        return text
    cleaned = text.replace("钢瓦", "钢马").replace("盖瓦", "锆马").replace("锆瓦", "锆马")
    if "钢马" in cleaned or "锆马" in cleaned:
        cleaned = cleaned.replace("泛光", "反光")
    return cleaned


def _append_quality_fallbacks(provider_plan: list[tuple[str, str]]) -> list[tuple[str, str]]:
    expanded: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    allow_non_qwen_fallbacks = str(os.getenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    for provider, model in provider_plan:
        item = (provider, model)
        if item not in seen:
            expanded.append(item)
            seen.add(item)
        if not allow_non_qwen_fallbacks:
            continue
        provider_key = str(provider or "").strip().lower()
        model_key = str(model or "").strip().lower()
        if provider_key == _LOCAL_ASR_PROVIDER and "qwen3-asr" in model_key:
            for fallback_model in (
                "faster-whisper-large-v3-beam5-nohot",
            ):
                fallback_item = (provider, fallback_model)
                if fallback_item not in seen:
                    expanded.append(fallback_item)
                    seen.add(fallback_item)
    return expanded


def _result_quality_units(result: TranscriptResult) -> list[dict[str, Any]]:
    model = str(getattr(result, "model", "") or "").strip().lower()
    if "qwen3-asr" in model:
        segment_units = [
            {
                "unit": f"segment:{index}",
                "text": str(getattr(seg, "text", "") or "").strip(),
                "words": list(getattr(seg, "words", None) or []),
            }
            for index, seg in enumerate(result.raw_segments or result.segments or [])
            if str(getattr(seg, "text", "") or "").strip()
        ]
        if segment_units:
            return segment_units

    raw_payload = result.raw_payload if isinstance(result.raw_payload, dict) else {}
    chunks = raw_payload.get("chunks")
    units: list[tuple[str, str]] = []
    if isinstance(chunks, list):
        for index, chunk in enumerate(chunks):
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("text") or chunk.get("raw_text") or "").strip()
            if text:
                units.append({"unit": f"chunk:{index}", "text": text, "words": []})
    if units:
        return units

    for index, seg in enumerate(result.raw_segments or result.segments or []):
        text = str(getattr(seg, "raw_text", None) or getattr(seg, "text", "") or "").strip()
        if text:
            units.append(
                {
                    "unit": f"segment:{index}",
                    "text": text,
                    "words": list(getattr(seg, "words", None) or []),
                }
            )
    return units


def _result_quality_text_units(result: TranscriptResult) -> list[tuple[str, str]]:
    return [
        (str(unit.get("unit") or ""), str(unit.get("text") or ""))
        for unit in _result_quality_units(result)
    ]


def _compact_asr_timing_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _word_text(word: WordTiming) -> str:
    return str(getattr(word, "word", "") or "").strip()


def _word_start(word: WordTiming) -> float:
    try:
        return float(getattr(word, "start", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _word_end(word: WordTiming) -> float:
    try:
        return float(getattr(word, "end", _word_start(word)) or _word_start(word))
    except (TypeError, ValueError):
        return _word_start(word)


def _word_duration(word: WordTiming) -> float:
    return max(0.0, _word_end(word) - _word_start(word))


def _build_compact_word_char_index(words: list[WordTiming]) -> tuple[str, list[int]]:
    compact_parts: list[str] = []
    char_word_indices: list[int] = []
    for word_index, word in enumerate(list(words or [])):
        word_text = _compact_asr_timing_text(_word_text(word))
        if not word_text:
            continue
        compact_parts.append(word_text)
        char_word_indices.extend([word_index] * len(word_text))
    return "".join(compact_parts), char_word_indices


def _word_indices_for_duplicate_span(
    *,
    compact_text: str,
    match_start: int,
    match_end: int,
    words: list[WordTiming],
) -> list[int]:
    if not words:
        return []
    compact_words, char_word_indices = _build_compact_word_char_index(words)
    if not compact_words or not char_word_indices:
        return []
    if len(compact_words) == len(compact_text):
        raw_indices = char_word_indices[match_start:match_end]
    else:
        sample = compact_text[match_start:match_end]
        word_pos = compact_words.find(sample)
        if word_pos < 0:
            return []
        raw_indices = char_word_indices[word_pos: word_pos + len(sample)]
    ordered: list[int] = []
    for word_index in raw_indices:
        if word_index not in ordered:
            ordered.append(word_index)
    return ordered


def _classify_duplicate_timing(
    *,
    compact_text: str,
    match_start: int,
    match_end: int,
    words: list[WordTiming],
) -> dict[str, Any]:
    word_indices = _word_indices_for_duplicate_span(
        compact_text=compact_text,
        match_start=match_start,
        match_end=match_end,
        words=words,
    )
    if not word_indices:
        duplicate_text = compact_text[match_start:match_end]
        if duplicate_text in _ASR_NO_TIMING_ADVISORY_DUPLICATES:
            return {
                "classification": "advisory",
                "reason": "duplicate_text_without_word_timestamps_but_common_laughter_or_sound",
                "word_count": 0,
            }
        return {
            "classification": "confirmed_noise",
            "reason": "duplicate_text_without_usable_word_timestamps",
            "word_count": 0,
        }

    matched_words = [words[index] for index in word_indices if 0 <= index < len(words)]
    starts = [_word_start(word) for word in matched_words]
    ends = [_word_end(word) for word in matched_words]
    durations = [_word_duration(word) for word in matched_words]
    if not matched_words or not starts or not ends:
        return {
            "classification": "confirmed_noise",
            "reason": "duplicate_text_without_usable_word_timestamps",
            "word_count": 0,
        }

    rounded_starts = {round(value, 2) for value in starts}
    zero_duration_count = sum(1 for value in durations if value <= 0.025)
    non_monotonic = any(starts[index] < starts[index - 1] - 0.015 for index in range(1, len(starts)))
    span = max(0.0, max(ends) - min(starts))
    duplicate_text = compact_text[match_start:match_end]
    char_rate = len(duplicate_text) / span if span > 0.0 else math.inf

    timing_summary = {
        "word_count": len(matched_words),
        "start": round(min(starts), 3),
        "end": round(max(ends), 3),
        "span_sec": round(span, 3),
        "zero_duration_count": zero_duration_count,
        "unique_start_count": len(rounded_starts),
        "char_rate": round(char_rate, 3) if math.isfinite(char_rate) else None,
    }
    if duplicate_text in _ASR_NO_TIMING_ADVISORY_DUPLICATES and len(matched_words) <= 2:
        return {
            **timing_summary,
            "classification": "advisory",
            "reason": "duplicate_common_laughter_or_sound_with_limited_timing_evidence",
        }
    if len(matched_words) >= 2 and (
        len(rounded_starts) <= 1
        or zero_duration_count > 0 and span <= 0.16
        or non_monotonic
        or char_rate >= 24.0 and span <= 0.22
    ):
        return {
            **timing_summary,
            "classification": "confirmed_noise",
            "reason": "duplicate_timing_collapsed_or_jittered",
        }
    if span >= max(0.12, len(duplicate_text) * 0.045) and zero_duration_count == 0 and not non_monotonic:
        return {
            **timing_summary,
            "classification": "likely_real_speech",
            "reason": "duplicate_has_plausible_word_timing",
        }
    return {
        **timing_summary,
        "classification": "advisory",
        "reason": "duplicate_timing_ambiguous",
    }


def _find_suspicious_asr_duplicate_findings(
    text: str,
    *,
    words: list[WordTiming] | None = None,
    sample_limit: int = 4,
) -> list[dict[str, Any]]:
    compact = re.sub(r"\s+", "", str(text or ""))
    if not compact:
        return []

    findings: list[dict[str, Any]] = []
    seen_spans: set[tuple[int, int]] = set()

    def add_finding(start: int, end: int, *, kind: str) -> None:
        if len(findings) >= sample_limit:
            return
        span = (start, end)
        if span in seen_spans:
            return
        seen_spans.add(span)
        timing = _classify_duplicate_timing(
            compact_text=compact,
            match_start=start,
            match_end=end,
            words=list(words or []),
        )
        findings.append(
            {
                "sample": compact[max(0, start - 6): min(len(compact), end + 10)],
                "duplicate_text": compact[start:end],
                "kind": kind,
                "classification": timing.pop("classification"),
                "timing_reason": timing.pop("reason"),
                "timing": timing,
            }
        )

    for match in _ASR_FUNCTION_STUTTER_RE.finditer(compact):
        add_finding(match.start(), match.end(), kind="function_stutter")

    for match in _ASR_PREFIX_STUTTER_RE.finditer(compact):
        char = match.group("char")
        prefix = compact[match.start(): match.start() + 3]
        if char in _ASR_REPEAT_ALLOWED_CHARS or prefix in _ASR_REPEAT_ALLOWED_PREFIXES:
            continue
        add_finding(match.start(), match.end(), kind="prefix_stutter")

    return findings


def _find_suspicious_asr_duplicate_samples(text: str, *, sample_limit: int = 4) -> list[str]:
    return [
        str(finding.get("sample") or "")
        for finding in _find_suspicious_asr_duplicate_findings(text, sample_limit=sample_limit)
    ]


def analyze_transcript_asr_quality(result: TranscriptResult) -> dict[str, Any]:
    units = _result_quality_units(result)
    affected_units: list[dict[str, Any]] = []
    advisory_units: list[dict[str, Any]] = []
    suspicious_duplicate_count = 0
    confirmed_noise_count = 0
    severe_timing_noise_count = 0
    likely_real_duplicate_count = 0
    advisory_duplicate_count = 0
    for unit in units:
        unit_id = str(unit.get("unit") or "")
        text = str(unit.get("text") or "")
        words = list(unit.get("words") or [])
        findings = _find_suspicious_asr_duplicate_findings(text, words=words)
        if not findings:
            continue
        noise_findings = [
            finding
            for finding in findings
            if str(finding.get("classification") or "") == "confirmed_noise"
        ]
        real_findings = [
            finding
            for finding in findings
            if str(finding.get("classification") or "") == "likely_real_speech"
        ]
        ambiguous_findings = [
            finding
            for finding in findings
            if str(finding.get("classification") or "") == "advisory"
        ]
        suspicious_duplicate_count += len(noise_findings) + len(ambiguous_findings)
        confirmed_noise_count += len(noise_findings)
        severe_timing_noise_count += sum(
            1
            for finding in noise_findings
            if str(finding.get("timing_reason") or "") == "duplicate_timing_collapsed_or_jittered"
        )
        likely_real_duplicate_count += len(real_findings)
        advisory_duplicate_count += len(ambiguous_findings)
        if noise_findings or ambiguous_findings:
            affected_units.append(
                {
                    "unit": unit_id,
                    "samples": [str(finding.get("sample") or "") for finding in noise_findings + ambiguous_findings],
                    "findings": noise_findings + ambiguous_findings,
                }
            )
        if real_findings:
            advisory_units.append(
                {
                    "unit": unit_id,
                    "samples": [str(finding.get("sample") or "") for finding in real_findings],
                    "findings": real_findings,
                }
            )

    unit_count = len(units)
    affected_count = len(affected_units)
    affected_ratio = affected_count / unit_count if unit_count else 0.0
    rejected = (
        severe_timing_noise_count >= 1
        or confirmed_noise_count >= 3
    )
    return {
        "rejected": rejected,
        "reason": "suspicious_adjacent_cjk_duplicates",
        "unit_count": unit_count,
        "affected_unit_count": affected_count,
        "affected_unit_ratio": round(affected_ratio, 4),
        "suspicious_duplicate_count": suspicious_duplicate_count,
        "confirmed_noise_duplicate_count": confirmed_noise_count,
        "severe_timing_noise_count": severe_timing_noise_count,
        "likely_real_duplicate_count": likely_real_duplicate_count,
        "advisory_duplicate_count": advisory_duplicate_count,
        "affected_units": affected_units[:8],
        "advisory_units": advisory_units[:8],
    }


def analyze_transcript_temporal_coverage(result: TranscriptResult) -> dict[str, Any]:
    duration = max(0.0, float(getattr(result, "duration", 0.0) or 0.0))
    segments = list(result.segments or result.raw_segments or [])
    covered_end = 0.0
    for segment in segments:
        covered_end = max(covered_end, float(getattr(segment, "end", 0.0) or 0.0))
        for word in list(getattr(segment, "words", None) or []):
            covered_end = max(covered_end, float(getattr(word, "end", 0.0) or 0.0))
    trailing_gap = max(0.0, duration - covered_end)
    coverage_ratio = covered_end / duration if duration > 0.0 else 1.0
    rejected = bool(
        duration >= 60.0
        and segments
        and trailing_gap > max(18.0, duration * 0.12)
    )
    return {
        "rejected": rejected,
        "reason": "transcript_temporal_coverage_low",
        "duration_sec": round(duration, 3),
        "covered_end_sec": round(covered_end, 3),
        "trailing_gap_sec": round(trailing_gap, 3),
        "coverage_ratio": round(coverage_ratio, 4),
        "segment_count": len(segments),
    }


def _should_reject_transcription_result(
    provider_name: str,
    model_name: str,
    result: TranscriptResult,
) -> dict[str, Any] | None:
    provider = str(provider_name or result.provider or "").strip().lower()
    if provider != _LOCAL_ASR_PROVIDER:
        return None
    coverage_analysis = analyze_transcript_temporal_coverage(result)
    if coverage_analysis["rejected"]:
        return coverage_analysis
    model = str(model_name or result.model or "").strip().lower()
    if "qwen3-asr" not in model:
        return None
    # Duplicate cleanup is owned by the local ASR provider before TranscriptResult is emitted.
    # This gate is only a residual assertion so polluted output cannot enter downstream stages.
    analysis = analyze_transcript_asr_quality(result)
    if not analysis["rejected"]:
        return None
    return analysis


def _summarize_asr_quality_rejection(analysis: dict[str, Any]) -> str:
    reason = str(analysis.get("reason") or "").strip()
    if reason == "transcript_temporal_coverage_low":
        return (
            "asr_quality_gate: rejected low temporal coverage "
            f"(covered_end={analysis.get('covered_end_sec', 0)}s/"
            f"duration={analysis.get('duration_sec', 0)}s, "
            f"trailing_gap={analysis.get('trailing_gap_sec', 0)}s, "
            f"segments={analysis.get('segment_count', 0)})"
        )
    samples: list[str] = []
    for unit in analysis.get("affected_units") or []:
        if not isinstance(unit, dict):
            continue
        for sample in unit.get("samples") or []:
            samples.append(str(sample))
            if len(samples) >= 3:
                break
        if len(samples) >= 3:
            break
    sample_text = " | ".join(samples)
    return (
        "asr_quality_gate: rejected suspicious local_http_asr output "
        f"({analysis.get('suspicious_duplicate_count', 0)} duplicate findings across "
        f"{analysis.get('affected_unit_count', 0)}/{analysis.get('unit_count', 0)} units"
        f"{'; samples=' + sample_text if sample_text else ''})"
    )


async def execute_transcription_plan(
    *,
    audio_path: Path,
    language: str,
    prompt: str | None,
    provider_plan: list[tuple[str, str]],
    progress_callback: TranscriptionProgressCallback | None = None,
) -> tuple[TranscriptResult, str, str, list[dict[str, str]]]:
    attempt_errors: list[dict[str, str]] = []
    expanded_provider_plan = _append_quality_fallbacks(provider_plan)
    rejected_attempts: list[dict[str, Any]] = []
    for provider_name, model_name in expanded_provider_plan:
        try:
            provider = get_transcription_provider(
                provider=provider_name,
                model=model_name,
                allow_explicit_provider=provider_name != _LOCAL_ASR_PROVIDER,
            )
            result = await provider.transcribe(
                audio_path,
                language=language,
                prompt=prompt,
                progress_callback=progress_callback,
            )
            rejection = _should_reject_transcription_result(provider_name, model_name, result)
            if rejection is not None:
                rejected_attempts.append(
                    {
                        "provider": provider_name,
                        "model": model_name,
                        "analysis": rejection,
                    }
                )
                attempt_errors.append(
                    {
                        "provider": provider_name,
                        "model": model_name,
                        "error": _summarize_asr_quality_rejection(rejection),
                    }
                )
                continue
            if rejected_attempts:
                result.raw_payload = dict(result.raw_payload or {})
                result.raw_payload["_roughcut_asr_quality_gate"] = {
                    "fallback_selected": {"provider": provider_name, "model": model_name},
                    "rejected_attempts": rejected_attempts,
                }
            return result, provider_name, model_name, attempt_errors
        except Exception as exc:
            attempt_errors.append(
                {
                    "provider": provider_name,
                    "model": model_name,
                    "error": str(exc),
                }
            )

    failure_summary = "; ".join(
        f"{item['provider']}/{item['model']}: {item['error']}"
        for item in attempt_errors
    )
    if rejected_attempts:
        raise AsrQualityGateError(
            f"All transcription providers failed: {failure_summary}",
            attempts=attempt_errors,
            rejected_attempts=rejected_attempts,
        )
    raise RuntimeError(f"All transcription providers failed: {failure_summary}")


async def transcribe_audio(
    job_id: uuid.UUID,
    step: JobStep,
    audio_path: Path,
    language: str,
    session: AsyncSession,
    prompt: str | None = None,
    progress_callback: TranscriptionProgressCallback | None = None,
    glossary_terms: list[dict] | None = None,
    review_memory: dict | None = None,
) -> TranscriptResult:
    """
    Transcribe audio using the configured TranscriptionProvider.
    Writes TranscriptSegment rows and an artifact to the DB.
    """
    settings = get_settings()
    provider_plan = resolve_transcription_provider_plan(
        provider=settings.transcription_provider,
        model=settings.transcription_model,
    )
    result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=audio_path,
        language=language,
        prompt=prompt,
        provider_plan=provider_plan,
        progress_callback=progress_callback,
    )

    return await persist_transcript_result(
        job_id=job_id,
        step=step,
        glossary_terms=glossary_terms or [],
        language=language,
        result=result,
        review_memory=review_memory,
        selected_model=selected_model,
        selected_provider=selected_provider,
        session=session,
        prompt=prompt,
        attempt_errors=attempt_errors,
    )


async def persist_empty_transcript_result(
    job_id: uuid.UUID,
    step: JobStep,
    *,
    language: str,
    session: AsyncSession,
    prompt: str | None = None,
    reason: str = "no_audio_stream",
    glossary_terms: list[dict] | None = None,
    review_memory: dict | None = None,
) -> TranscriptResult:
    return await persist_transcript_result(
        job_id=job_id,
        step=step,
        language=language,
        session=session,
        prompt=prompt,
        glossary_terms=glossary_terms or [],
        review_memory=review_memory,
        result=TranscriptResult(
            segments=[],
            language=language,
            duration=0.0,
            provider="system",
            model="no_audio",
            raw_payload={"reason": reason},
            raw_segments=[],
            context=reason,
        ),
        selected_provider="system",
        selected_model="no_audio",
        attempt_errors=[],
    )


async def persist_asr_quality_gate_artifact(
    *,
    job_id: uuid.UUID,
    step: JobStep,
    session: AsyncSession,
    language: str,
    prompt: str | None,
    error: AsrQualityGateError,
) -> None:
    prompt_hotwords = extract_prompt_hotwords(prompt)
    payload = dict(error.payload)
    payload.update(
        {
            "language": language,
            "prompt": str(prompt or ""),
            "prompt_hotwords": prompt_hotwords,
            "prompt_hotword_count": len(prompt_hotwords),
        }
    )
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step.id,
            artifact_type=ARTIFACT_TYPE_ASR_QUALITY_GATE,
            data_json=_json_safe_value(payload),
        )
    )
    await session.flush()


async def persist_transcript_result(
    *,
    job_id: uuid.UUID,
    step: JobStep,
    language: str,
    session: AsyncSession,
    result: TranscriptResult,
    prompt: str | None,
    glossary_terms: list[dict],
    review_memory: dict | None,
    selected_provider: str | None,
    selected_model: str | None,
    attempt_errors: list[dict[str, str]],
) -> TranscriptResult:
    settings = get_settings()
    prompt_hotwords = extract_prompt_hotwords(prompt)
    chunking_summary = extract_chunking_summary(result.raw_payload if isinstance(result.raw_payload, dict) else {})
    result = _normalize_transcript_result(
        result,
        glossary_terms=glossary_terms or [],
        review_memory=review_memory,
        alignment_settings=AlignmentSettings(
            mode=str(getattr(settings, "transcription_alignment_mode", "auto") or "auto"),
            min_word_coverage=float(getattr(settings, "transcription_alignment_min_word_coverage", 0.72) or 0.72),
        ),
    )
    transcript_fact_layer = build_transcript_fact_layer_from_result(result)

    # Replace the previous transcript-derived rows on rerun instead of appending
    # another copy with the same indexes and stale downstream references.
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.version == 1))
    await session.execute(delete(TranscriptSegment).where(TranscriptSegment.job_id == job_id, TranscriptSegment.version == 1))

    # Persist segments
    for seg in result.segments:
        words_json = drop_redundant_synthetic_word_payloads([_serialize_word_timing(w) for w in seg.words])
        db_seg = TranscriptSegment(
            job_id=job_id,
            version=1,
            segment_index=seg.index,
            start_time=seg.start,
            end_time=seg.end,
            speaker=seg.speaker,
            text=seg.text,
            words_json=words_json,
        )
        session.add(db_seg)

    # Save artifact metadata
    artifact = Artifact(
        job_id=job_id,
        step_id=step.id,
        artifact_type="transcript",
        data_json=_json_safe_value({
            "language": language,
            "duration": result.duration,
            "segment_count": len(result.segments),
            "provider": selected_provider or result.provider,
            "model": selected_model or result.model,
            "chunking": _json_safe_value(chunking_summary),
            "alignment": _json_safe_value(deepcopy(result.alignment)),
            "attempts": [
                *attempt_errors,
                *(
                    [{"provider": selected_provider, "model": selected_model, "error": ""}]
                    if selected_provider
                    else []
                ),
            ],
        }),
    )
    session.add(artifact)
    session.add(
        Artifact(
            job_id=job_id,
            step_id=step.id,
            artifact_type=ARTIFACT_TYPE_TRANSCRIPT_FACT_LAYER,
            data_json=_json_safe_value(transcript_fact_layer.as_dict()),
        )
    )
    if bool(getattr(settings, "asr_evidence_enabled", False)):
        session.add(
            Artifact(
                job_id=job_id,
                step_id=step.id,
                artifact_type=ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
                data_json=_json_safe_value({
                    "language": language,
                    "duration": result.duration,
                    "provider": result.provider or selected_provider,
                    "model": result.model or selected_model,
                    "chunking": _json_safe_value(chunking_summary),
                    "prompt": str(prompt or ""),
                    "prompt_hotwords": prompt_hotwords,
                    "prompt_hotword_count": len(prompt_hotwords),
                    "context": result.context,
                    "hotword": result.hotword,
                    "alignment": _json_safe_value(deepcopy(result.alignment)),
                    "attempts": [
                        *attempt_errors,
                        *(
                            [{"provider": selected_provider, "model": selected_model, "error": ""}]
                            if selected_provider
                            else []
                        ),
                    ],
                    "raw_payload": deepcopy(result.raw_payload),
                    "raw_segments": [_serialize_transcript_segment(seg) for seg in (result.raw_segments or [])],
                    "segments": [_serialize_transcript_segment(seg) for seg in result.segments],
                }),
            )
        )
    await record_prompted_hotwords(session, prompt_hotwords=prompt_hotwords)
    await session.flush()

    return result


def _normalize_transcript_result(
    result: TranscriptResult,
    *,
    glossary_terms: list[dict],
    review_memory: dict | None,
    alignment_settings: AlignmentSettings | None = None,
) -> TranscriptResult:
    raw_segments = deepcopy(result.raw_segments or result.segments)
    normalized = deepcopy(result)
    normalized.raw_segments = raw_segments
    normalized.raw_payload = deepcopy(result.raw_payload)
    category_scope = resolve_transcription_category_scope(review_memory)

    for raw_seg, seg in zip(raw_segments, normalized.segments):
        seg.raw_text = raw_seg.raw_text or raw_seg.text
        seg.raw_payload = deepcopy(raw_seg.raw_payload)
        seg.provider = seg.provider or raw_seg.provider or result.provider
        seg.model = seg.model or raw_seg.model or result.model
        seg.context = seg.context or raw_seg.context or result.context
        seg.hotword = seg.hotword or raw_seg.hotword or result.hotword
        seg.confidence = seg.confidence if seg.confidence is not None else raw_seg.confidence
        seg.logprob = seg.logprob if seg.logprob is not None else raw_seg.logprob
        seg.alignment = seg.alignment if seg.alignment is not None else raw_seg.alignment

        raw_words = raw_seg.words or []
        for raw_word, word in zip(raw_words, seg.words):
            word.raw_text = raw_word.raw_text or raw_word.word
            word.raw_payload = deepcopy(raw_word.raw_payload)
            word.provider = word.provider or raw_word.provider or seg.provider
            word.model = word.model or raw_word.model or seg.model
            word.context = word.context or raw_word.context or seg.context
            word.hotword = word.hotword or raw_word.hotword or seg.hotword
            word.confidence = word.confidence if word.confidence is not None else raw_word.confidence
            word.logprob = word.logprob if word.logprob is not None else raw_word.logprob
            word.alignment = word.alignment if word.alignment is not None else raw_word.alignment

    for seg in normalized.segments:
        text = str(seg.text or "").strip()
        if not text:
            continue
        normalized_text = _normalize_semantic_contamination_text(
            normalize_source_transcript_text(text),
            category_scope=category_scope,
        )
        if normalized_text != text:
            normalization_payload = dict(seg.raw_payload or {})
            roughcut_normalization = dict(normalization_payload.get("_roughcut_asr_normalization") or {})
            roughcut_normalization.update(
                {
                    "original_text": text,
                    "normalized_text": normalized_text,
                    "stage": "transcribe.normalize",
                }
            )
            normalization_payload["_roughcut_asr_normalization"] = roughcut_normalization
            seg.raw_payload = normalization_payload
        seg.text = normalized_text
        seg.words = _normalize_segment_word_timings_for_text(seg, normalized_text=normalized_text)
    normalized.segments = [seg for seg in normalized.segments if str(seg.text or "").strip()]
    _filter_tail_cta_noise_segments(normalized)
    return enhance_transcript_alignment(normalized, settings=alignment_settings)


def _normalize_segment_word_timings_for_text(
    seg: ProviderTranscriptSegment,
    *,
    normalized_text: str,
) -> list[WordTiming]:
    canonical_units = subtitle_display_units(normalized_text)
    if not canonical_units or not seg.words:
        return list(seg.words or [])

    raw_units: list[dict[str, Any]] = []
    for word in seg.words:
        units = subtitle_display_units(word.word)
        if not units:
            continue
        try:
            start = float(word.start)
            end = float(word.end)
        except (TypeError, ValueError):
            continue
        if end <= start:
            continue
        duration = end - start
        for offset, unit in enumerate(units):
            raw_units.append(
                {
                    "text": unit,
                    "key": subtitle_display_unit_key(unit),
                    "start": start + duration * (offset / len(units)),
                    "end": start + duration * ((offset + 1) / len(units)),
                    "word": word,
                }
            )
    if not raw_units:
        return list(seg.words or [])

    pairs = _lcs_index_pairs(
        [subtitle_display_unit_key(unit) for unit in canonical_units],
        [str(unit["key"]) for unit in raw_units],
    )
    matched_by_canonical = {canonical_index: raw_index for canonical_index, raw_index in pairs}
    if has_unsafe_unmatched_alnum_units(
        canonical_units,
        matched_indexes=set(matched_by_canonical),
    ):
        return list(seg.words or [])
    previous_end = float(raw_units[0]["start"])
    normalized_words: list[WordTiming] = []
    for canonical_index, unit in enumerate(canonical_units):
        raw_index = matched_by_canonical.get(canonical_index)
        raw_unit = raw_units[raw_index] if raw_index is not None else None
        raw_word = raw_unit.get("word") if raw_unit else None
        start = float(raw_unit["start"]) if raw_unit else previous_end
        end = float(raw_unit["end"]) if raw_unit else max(start + 0.001, previous_end)
        previous_end = max(previous_end, end)
        raw_payload = dict(getattr(raw_word, "raw_payload", None) or {})
        raw_payload["_roughcut_asr_normalization"] = {
            "original_word": getattr(raw_word, "word", None),
            "normalized_word": unit,
            "stage": "transcribe.words.normalize",
            "matched": raw_unit is not None,
        }
        normalized_words.append(
            WordTiming(
                word=unit,
                start=round(start, 3),
                end=round(end, 3),
                provider=getattr(raw_word, "provider", None),
                model=getattr(raw_word, "model", None),
                raw_payload=raw_payload,
                raw_text=getattr(raw_word, "raw_text", None) or getattr(raw_word, "word", None),
                context=getattr(raw_word, "context", None),
                hotword=getattr(raw_word, "hotword", None),
                confidence=getattr(raw_word, "confidence", None),
                logprob=getattr(raw_word, "logprob", None),
                alignment=getattr(raw_word, "alignment", None),
            )
        )
    serialized_normalized = [_serialize_word_timing(word) for word in normalized_words]
    sanitized_normalized = drop_redundant_synthetic_word_payloads(serialized_normalized)
    if len(sanitized_normalized) != len(serialized_normalized):
        return list(seg.words or [])
    if word_payloads_have_collapsed_timing(sanitized_normalized):
        return list(seg.words or [])
    return normalized_words


def _lcs_index_pairs(left: list[str], right: list[str]) -> list[tuple[int, int]]:
    if not left or not right:
        return []
    rows = len(left) + 1
    cols = len(right) + 1
    table = [[0] * cols for _ in range(rows)]
    for row in range(1, rows):
        for col in range(1, cols):
            table[row][col] = (
                table[row - 1][col - 1] + 1
                if left[row - 1] == right[col - 1]
                else max(table[row - 1][col], table[row][col - 1])
            )
    pairs: list[tuple[int, int]] = []
    row = len(left)
    col = len(right)
    while row > 0 and col > 0:
        if left[row - 1] == right[col - 1]:
            pairs.append((row - 1, col - 1))
            row -= 1
            col -= 1
        elif table[row - 1][col] >= table[row][col - 1]:
            row -= 1
        else:
            col -= 1
    pairs.reverse()
    return pairs


def _serialize_word_timing(word: WordTiming) -> dict[str, object]:
    return {
        "word": word.word,
        "raw_text": word.raw_text,
        "start": _json_safe_value(word.start),
        "end": _json_safe_value(word.end),
        "provider": word.provider,
        "model": word.model,
        "context": word.context,
        "hotword": word.hotword,
        "confidence": _json_safe_value(word.confidence),
        "logprob": _json_safe_value(word.logprob),
        "alignment": _json_safe_value(deepcopy(word.alignment)),
        "raw_payload": _json_safe_value(deepcopy(word.raw_payload)),
    }


def _serialize_transcript_segment(seg: ProviderTranscriptSegment) -> dict[str, object]:
    return {
        "index": seg.index,
        "start": _json_safe_value(seg.start),
        "end": _json_safe_value(seg.end),
        "text": seg.text,
        "raw_text": seg.raw_text,
        "speaker": seg.speaker,
        "provider": seg.provider,
        "model": seg.model,
        "context": seg.context,
        "hotword": seg.hotword,
        "confidence": _json_safe_value(seg.confidence),
        "logprob": _json_safe_value(seg.logprob),
        "alignment": _json_safe_value(deepcopy(seg.alignment)),
        "raw_payload": _json_safe_value(deepcopy(seg.raw_payload)),
        "words": [_serialize_word_timing(word) for word in seg.words],
    }


def _json_safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            scalar = item_method()
        except Exception:
            scalar = None
        else:
            if scalar is not value:
                return _json_safe_value(scalar)

    for attr in ("model_dump", "dict", "to_dict"):
        method = getattr(value, attr, None)
        if not callable(method):
            continue
        try:
            dumped = method()
        except TypeError:
            try:
                dumped = method(mode="json")
            except Exception:
                continue
        except Exception:
            continue
        return _json_safe_value(dumped)

    if hasattr(value, "__dict__"):
        return {
            key: _json_safe_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }

    return repr(value)
