from __future__ import annotations

import re
from typing import Any

_STANDALONE_FILLER_TOKENS = (
    "这个",
    "那个",
    "呃",
    "额",
    "嗯",
    "啊",
    "哎",
    "唉",
    "诶",
    "欸",
    "吧",
)

_ASR_NOISE_LABEL = (
    r"(?:background[_\s-]?music|background[_\s-]?noise|environmental[_\s-]?sounds?|"
    r"environmentalsounds|human[_\s-]?sounds?|humansounds|sounds?|"
    r"no[_\s-]?speech|nospeech|silence|music|noise)"
)
_ASR_INLINE_NOISE_LABEL = (
    r"(?:EnvironmentalSounds|Environmental[_\s-]?Sounds?|BackgroundNoise|"
    r"HumanSounds|Human[_\s-]?Sounds?|Sounds?|Noise)"
)
_SUBTITLE_FILLER_SEPARATOR_PATTERN = re.compile(r"[\s，。！？、：；,.!?…~\-—_()\[\]{}<>《》“”\"'‘’（）【】]+")
_FINAL_SUBTITLE_PUNCTUATION_PATTERN = re.compile(r"[\s，。！？、：；,.!?…~\-—_()\[\]{}<>《》“”\"'‘’/\\|｜（）【】]+")
_ASR_NOISE_MARKER_PATTERN = re.compile(
    r"(?i)"
    rf"(?:<\|?\s*(?:{_ASR_NOISE_LABEL}(?:\s+{_ASR_NOISE_LABEL})*)\s*\|?>)"
    rf"|(?:[\[\(（【<]\s*(?:{_ASR_NOISE_LABEL}(?:\s+{_ASR_NOISE_LABEL})*)\s*[\]\)）】>])"
    r"|[♪♫]+"
)
_ASR_INLINE_NOISE_MARKER_PATTERN = re.compile(_ASR_INLINE_NOISE_LABEL, re.IGNORECASE)
_ASR_NOISE_ONLY_PATTERN = re.compile(
    rf"(?i)^(?:(?:{_ASR_NOISE_LABEL})(?:\s+(?:{_ASR_NOISE_LABEL}))*|静音|无语音)$"
)
_DISRUPTION_CLAUSE_PATTERN = re.compile(
    r"^(?:滚|滚开|别吵|别说话|别闹|走开|待会再说|没事|停一下|暂停一下|等一下|先停一下|别打扰|不要打扰|干嘛)$"
)


def clean_final_subtitle_text(text: object) -> str:
    """Remove final-output noise and serialize captions without punctuation."""
    return _clean_final_subtitle_text_and_reason(text)[0]


def subtitle_display_suppression_reason(text: object) -> str:
    return _clean_final_subtitle_text_and_reason(text)[1]


def _clean_final_subtitle_text_and_reason(text: object) -> tuple[str, str]:
    normalized = str(text or "").strip()
    if not normalized:
        return "", "empty_source_text"
    original = normalized
    normalized = _strip_asr_noise_markers(normalized)
    normalized = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", normalized)
    if _is_asr_noise_only(normalized):
        return "", "asr_noise_marker"
    normalized = _drop_final_noise_clauses(normalized)
    if not normalized:
        if _is_disruption_clause(original):
            return "", "disruption_clause"
        if _is_standalone_subtitle_filler(original):
            return "", "standalone_filler"
        return "", "all_clauses_suppressed"
    if _is_standalone_subtitle_filler(normalized):
        return "", "standalone_filler"
    if _is_disruption_clause(normalized):
        return "", "disruption_clause"
    return _format_final_subtitle_text(normalized), ""


def clean_subtitle_payloads(
    subtitles: list[dict[str, Any]],
    *,
    drop_empty: bool = True,
    collapse_repeats: bool = True,
    clean_text: bool = True,
) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for item in subtitles:
        payload = _normalize_subtitle_timing_payload(item)
        source_text = str(payload.get("text_final") or payload.get("text_norm") or payload.get("text_raw", "") or "").strip()
        text_final, suppressed_reason = (
            _clean_final_subtitle_text_and_reason(source_text)
            if clean_text
            else (source_text, "")
        )
        if clean_text and suppressed_reason and source_text:
            payload["display_suppressed_reason"] = suppressed_reason
        if drop_empty and not (text_final if clean_text else source_text):
            continue
        if clean_text:
            payload["text_final"] = text_final
        cleaned.append(payload)
    if not collapse_repeats or not clean_text:
        return cleaned
    return collapse_repeated_subtitle_payloads(cleaned)


def _normalize_subtitle_timing_payload(item: dict[str, Any]) -> dict[str, Any]:
    payload = dict(item)
    start_value = payload.get("start_time", payload.get("start"))
    end_value = payload.get("end_time", payload.get("end"))
    if start_value is None and end_value is None:
        return payload
    try:
        start_time = max(0.0, float(start_value or 0.0))
        end_time = max(start_time, float(end_value if end_value is not None else start_time))
    except (TypeError, ValueError):
        return payload
    payload["start_time"] = round(start_time, 3)
    payload["end_time"] = round(end_time, 3)
    payload.pop("start", None)
    payload.pop("end", None)
    return payload


def collapse_repeated_subtitle_payloads(
    subtitles: list[dict[str, Any]],
    *,
    min_repeat_count: int = 3,
    min_key_chars: int = 8,
    max_gap_sec: float = 1.5,
) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    pending_run: list[dict[str, Any]] = []
    pending_key = ""

    def flush_pending() -> None:
        nonlocal pending_run, pending_key
        if not pending_run:
            return
        if len(pending_run) >= min_repeat_count and len(pending_key) >= min_key_chars:
            collapsed.append(pending_run[0])
        else:
            collapsed.extend(pending_run)
        pending_run = []
        pending_key = ""

    for item in subtitles:
        payload = dict(item)
        key = _subtitle_repetition_key(str(payload.get("text_final") or ""))
        if (
            pending_run
            and key
            and key == pending_key
            and _subtitle_payload_gap_sec(pending_run[-1], payload) <= max_gap_sec
        ):
            pending_run.append(payload)
            continue
        flush_pending()
        pending_key = key
        pending_run = [payload]

    flush_pending()
    return collapsed


def _strip_asr_noise_markers(text: str) -> str:
    normalized = _ASR_NOISE_MARKER_PATTERN.sub(" ", str(text or ""))
    normalized = _ASR_INLINE_NOISE_MARKER_PATTERN.sub("，", normalized)
    return re.sub(r"\s{2,}", " ", normalized).strip()


def _drop_final_noise_clauses(text: str) -> str:
    pieces = [piece for piece in _SUBTITLE_FILLER_SEPARATOR_PATTERN.split(str(text or "")) if piece.strip()]
    if not pieces:
        return ""
    kept: list[str] = []
    for piece in pieces:
        candidate = piece.strip()
        if _is_standalone_subtitle_filler(candidate) or _is_disruption_clause(candidate):
            continue
        kept.append(candidate)
    return " ".join(kept).strip()


def _format_final_subtitle_text(text: str) -> str:
    return re.sub(r"\s{2,}", " ", _FINAL_SUBTITLE_PUNCTUATION_PATTERN.sub(" ", str(text or "").strip())).strip()


def _subtitle_repetition_key(text: str) -> str:
    return "".join(ch for ch in str(text or "") if ch.isalnum()).lower()


def _subtitle_payload_gap_sec(left: dict[str, Any], right: dict[str, Any]) -> float:
    try:
        left_end = float(left.get("end_time", left.get("end", 0.0)) or 0.0)
        right_start = float(right.get("start_time", right.get("start", 0.0)) or 0.0)
    except (TypeError, ValueError):
        return float("inf")
    return max(0.0, right_start - left_end)


def _is_standalone_subtitle_filler(text: str) -> bool:
    compact = _SUBTITLE_FILLER_SEPARATOR_PATTERN.sub("", str(text or "").strip()).lower()
    if not compact:
        return True
    index = 0
    while index < len(compact):
        matched = False
        for token in _STANDALONE_FILLER_TOKENS:
            if compact.startswith(token, index):
                index += len(token)
                matched = True
                break
        if not matched:
            return False
    return True


def _is_asr_noise_only(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    normalized = _SUBTITLE_FILLER_SEPARATOR_PATTERN.sub(" ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized).strip()
    return bool(_ASR_NOISE_ONLY_PATTERN.fullmatch(normalized))


def _is_disruption_clause(text: str) -> bool:
    compact = _SUBTITLE_FILLER_SEPARATOR_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return False
    return bool(_DISRUPTION_CLAUSE_PATTERN.fullmatch(compact))
