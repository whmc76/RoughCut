from __future__ import annotations

from collections import Counter
import re
from typing import Any, Iterable, Mapping, Sequence

from roughcut.speech.subtitle_segmentation import _boundary_splits_generic_word

ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT = "subtitle_quality_report"

_BAD_TERM_PATTERNS: dict[str, re.Pattern[str]] = {
    "hotword_unboxing_misheard": re.compile(r"开枪"),
    "hotword_model_mt34_misheard": re.compile(r"MP三四|MP34|MP\s*三四"),
    "hotword_brand_noc_misheard": re.compile(r"NZ家|\bNZ\b"),
    "hotword_trim_variant_misheard": re.compile(r"四顶配"),
    "hotword_numeric_edc17_uncorrected": re.compile(r"幺7|幺七"),
    "hotword_flashlight_model_knifedrift": re.compile(
        r"(?:折刀帕|刀)(?:幺七|幺7|一七|17|二三|23|三七|37)|EDC(?:17|23|37)折刀(?:帕)?|EDC17刀(?:幺七|幺7|一七|17)|EDC23刀(?:二三|23)|EDC37刀(?:三七|37)"
    ),
    "hotword_overcorrection_7": re.compile(r"这7个|这7咱"),
}

_PURE_FILLER_RE = re.compile(r"^(嗯|呃|啊|哎|哦|诶|欸|好|对|然后|那个|这个|就是|吧|呢){1,4}$")
_LOW_SIGNAL_RE = re.compile(r"^(好开始|嗯今天|啊这个什么呢|待会再说|待会再说那个刀|哎哦对|完梗了啊这个)$")
_SHORT_FRAGMENT_RE = re.compile(r"^[^，。！？；：,.!?;:]{1,4}$")
_KEEP_SHORT_FRAGMENT_RE = re.compile(
    r"(MT34|EDC17|EDC37|FXX1|EXO|NOC|FAS|OLIGHT|foxbat|MT33|S11|PC件|凯夫拉|大力马)",
    re.IGNORECASE,
)
_ALLOWED_SHORT_UTTERANCE_RE = re.compile(
    r"^(?:"
    r"我发现|你看|你说|算了|但是|不过|并且|然后|后来|所以|其实|另外|再说|比如|例如|行了|好了|没事|确实|真的"
    r")$"
)
_ALLOWED_SHORT_TEMPORAL_PHRASE_RE = re.compile(
    r"^(?:前|这|那|近|后)?(?:\d+|[一二三四五六七八九十两几])(?:天|周|年|个月|分钟|秒钟?)$"
)
_GENERIC_SUMMARY_PHRASES = (
    "适合后续做搜索校验、字幕纠错和剪辑包装",
    "具体品牌型号待人工确认",
    "主体品牌型号待进一步确认",
)
_CONSERVATIVE_IDENTITY_SUMMARY_PHRASES = {
    "具体品牌型号待人工确认",
    "主体品牌型号待进一步确认",
}
_IDENTITY_HINT_RE = re.compile(r"(MT34|EDC17|EDC37|FXX1|EXO|NOC|FAS|foxbat|OLIGHT|NITECORE|REATE)", re.IGNORECASE)
_SHORT_FRAGMENT_BLOCKING_MIN_COUNT = 5

_SEMANTIC_CONTAMINATION_CODES = {
    "hotword_flashlight_model_knifedrift",
}

_LEXICAL_CORRECTION_CODES = set(_BAD_TERM_PATTERNS) - _SEMANTIC_CONTAMINATION_CODES


def _subtitle_text(item: Mapping[str, Any]) -> str:
    for key in ("text_final", "text_norm", "text_raw", "text"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _subtitle_duration(item: Mapping[str, Any]) -> float | None:
    start = item.get("start_time", item.get("start"))
    end = item.get("end_time", item.get("end"))
    try:
        if start is None or end is None:
            return None
        return max(0.0, float(end) - float(start))
    except (TypeError, ValueError):
        return None


def _is_allowed_short_utterance(text: str, duration: float | None) -> bool:
    candidate = str(text or "").strip()
    if not candidate or not _ALLOWED_SHORT_UTTERANCE_RE.match(candidate):
        return False
    if duration is None:
        return True
    return duration >= 0.5


def _is_allowed_short_temporal_phrase(text: str, duration: float | None) -> bool:
    candidate = str(text or "").strip()
    if not candidate or not _ALLOWED_SHORT_TEMPORAL_PHRASE_RE.match(candidate):
        return False
    if duration is None:
        return True
    return duration >= 0.8


def _profile_subject(profile: Mapping[str, Any] | None) -> str:
    candidate = profile or {}
    for key in ("subject", "content_subject"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    brand = str(candidate.get("subject_brand") or "").strip()
    model = str(candidate.get("subject_model") or "").strip()
    return " ".join(part for part in (brand, model) if part).strip()


def _profile_summary(profile: Mapping[str, Any] | None) -> str:
    candidate = profile or {}
    for key in ("summary", "content_summary"):
        value = str(candidate.get(key) or "").strip()
        if value:
            return value
    return ""


def _profile_has_stable_identity_context(profile: Mapping[str, Any] | None) -> bool:
    candidate = profile or {}
    if _profile_subject(candidate):
        return True
    summary = _profile_summary(candidate)
    if not summary or summary in _GENERIC_SUMMARY_PHRASES:
        return False
    return True


def _profile_uses_conservative_identity_summary(profile: Mapping[str, Any] | None) -> bool:
    candidate = profile or {}
    identity_review = candidate.get("identity_review")
    if not isinstance(identity_review, Mapping):
        return False
    return bool(identity_review.get("conservative_summary"))


def _summary_generic_phrase_hits(profile: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    summary = _profile_summary(profile)
    conservative_identity_summary = _profile_uses_conservative_identity_summary(profile)
    active_hits: list[str] = []
    suppressed_hits: list[str] = []
    for phrase in _GENERIC_SUMMARY_PHRASES:
        if phrase not in summary:
            continue
        if conservative_identity_summary and phrase in _CONSERVATIVE_IDENTITY_SUMMARY_PHRASES:
            suppressed_hits.append(phrase)
            continue
        active_hits.append(phrase)
    return active_hits, suppressed_hits


def build_subtitle_quality_report(
    *,
    subtitle_items: Sequence[Mapping[str, Any]],
    source_name: str = "",
    content_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    total = len(subtitle_items)
    texts = [_subtitle_text(item) for item in subtitle_items]
    joined_text = "\n".join(texts)

    bad_term_counts = Counter()
    for code, pattern in _BAD_TERM_PATTERNS.items():
        bad_term_counts[code] = len(list(pattern.finditer(joined_text)))

    semantic_bad_term_total = sum(
        count for code, count in bad_term_counts.items()
        if code in _SEMANTIC_CONTAMINATION_CODES
    )
    lexical_bad_term_total = sum(
        count for code, count in bad_term_counts.items()
        if code in _LEXICAL_CORRECTION_CODES
    )

    filler_count = 0
    low_signal_count = 0
    short_fragment_count = 0
    generic_word_split_count = 0
    for item, text in zip(subtitle_items, texts):
        if not text:
            continue
        if _PURE_FILLER_RE.match(text):
            filler_count += 1
        if _LOW_SIGNAL_RE.match(text):
            low_signal_count += 1
        duration = _subtitle_duration(item) if isinstance(item, Mapping) else None
        if (
            _SHORT_FRAGMENT_RE.match(text)
            and not _KEEP_SHORT_FRAGMENT_RE.search(text)
            and not _is_allowed_short_utterance(text, duration)
            and not _is_allowed_short_temporal_phrase(text, duration)
        ):
            short_fragment_count += 1
    for left_text, right_text in zip(texts, texts[1:]):
        if _boundary_splits_generic_word(left_text, right_text):
            generic_word_split_count += 1

    subject = _profile_subject(content_profile)
    summary = _profile_summary(content_profile)
    summary_generic_hits, suppressed_summary_generic_hits = _summary_generic_phrase_hits(content_profile)
    identity_expected = bool(_IDENTITY_HINT_RE.search(source_name))
    identity_check_ready = bool(identity_expected and _profile_has_stable_identity_context(content_profile))
    identity_missing = bool(identity_check_ready and not _IDENTITY_HINT_RE.search(f"{subject} {summary}"))

    short_fragment_rate = (short_fragment_count / total) if total else 0.0
    filler_rate = (filler_count / total) if total else 0.0
    low_signal_rate = (low_signal_count / total) if total else 0.0
    bad_term_total = sum(bad_term_counts.values())

    blocking_reasons: list[str] = []
    warning_reasons: list[str] = []

    if semantic_bad_term_total > 0:
        blocking_reasons.append(f"检测到语义污染 {semantic_bad_term_total} 处，必须人工确认")
    if lexical_bad_term_total > 0:
        blocking_reasons.append(f"可词级纠偏的热词/型号残留 {lexical_bad_term_total} 处")
    if short_fragment_rate > 0.015 and short_fragment_count >= _SHORT_FRAGMENT_BLOCKING_MIN_COUNT:
        blocking_reasons.append(f"短碎句率过高 {short_fragment_rate:.2%}")
    elif short_fragment_rate > 0.008:
        warning_reasons.append(f"短碎句率偏高 {short_fragment_rate:.2%}")
    if generic_word_split_count > 0:
        blocking_reasons.append(f"普通词跨字幕截断 {generic_word_split_count} 处")
    if filler_rate > 0.01:
        warning_reasons.append(f"独立语气词偏多 {filler_rate:.2%}")
    if low_signal_rate > 0.005:
        warning_reasons.append(f"低信息碎句偏多 {low_signal_rate:.2%}")
    if summary_generic_hits:
        warning_reasons.append(f"摘要模板化命中 {len(summary_generic_hits)} 项")
    if identity_missing:
        warning_reasons.append("摘要/主体未保住文件名中的品牌型号")

    score = 100.0
    score -= float(bad_term_total * 6)
    score -= float(generic_word_split_count * 8)
    score -= min(25.0, short_fragment_rate * 180.0)
    score -= min(10.0, filler_rate * 120.0)
    score -= min(8.0, low_signal_rate * 160.0)
    score -= float(len(summary_generic_hits) * 8)
    score -= 12.0 if identity_missing else 0.0
    score = max(0.0, round(score, 2))

    return {
        "score": score,
        "blocking": bool(blocking_reasons),
        "blocking_reasons": blocking_reasons,
        "warning_reasons": warning_reasons,
        "metrics": {
            "subtitle_count": total,
            "bad_term_total": bad_term_total,
            "bad_term_counts": dict(bad_term_counts),
            "lexical_bad_term_total": lexical_bad_term_total,
            "semantic_bad_term_total": semantic_bad_term_total,
            "lexical_correction_codes": sorted(_LEXICAL_CORRECTION_CODES),
            "semantic_contamination_codes": sorted(_SEMANTIC_CONTAMINATION_CODES),
            "filler_count": filler_count,
            "low_signal_count": low_signal_count,
            "short_fragment_count": short_fragment_count,
            "generic_word_split_count": generic_word_split_count,
            "short_fragment_rate": round(short_fragment_rate, 4),
            "filler_rate": round(filler_rate, 4),
            "low_signal_rate": round(low_signal_rate, 4),
            "summary_generic_hits": summary_generic_hits,
            "suppressed_summary_generic_hits": suppressed_summary_generic_hits,
            "conservative_identity_summary": _profile_uses_conservative_identity_summary(content_profile),
            "identity_expected": identity_expected,
            "identity_check_ready": identity_check_ready,
            "identity_missing": identity_missing,
        },
        "source_name": source_name,
        "subject": subject,
        "summary": summary,
    }


def build_subtitle_quality_report_from_items(
    *,
    subtitle_items: Iterable[Any],
    source_name: str = "",
    content_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_items = [
        {
            "text_raw": getattr(item, "text_raw", None),
            "text_norm": getattr(item, "text_norm", None),
            "text_final": getattr(item, "text_final", None),
            "start_time": getattr(item, "start_time", getattr(item, "start", None)),
            "end_time": getattr(item, "end_time", getattr(item, "end", None)),
        }
        for item in subtitle_items
    ]
    return build_subtitle_quality_report(
        subtitle_items=normalized_items,
        source_name=source_name,
        content_profile=content_profile,
    )
