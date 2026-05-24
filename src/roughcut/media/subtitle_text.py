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
    rf"(?i)^(?:(?:{_ASR_NOISE_LABEL})(?:\s+(?:{_ASR_NOISE_LABEL}))*|静音|无语音|噪音|杂音|背景音|环境音|音乐|笑声|咳嗽|掌声)$"
)
_DISRUPTION_CLAUSE_PATTERN = re.compile(
    r"^(?:滚|滚开|别吵|别说话|别闹|走开|待会再说|没事|停一下|暂停一下|等一下|先停一下|别打扰|不要打扰|干嘛)$"
)
_ASCII_MODEL_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9+#.-]{3,}")
_ASCII_SPELLOUT_SEQUENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]|\d+|mini|Mini|MINI)(?:\s+(?:[A-Za-z]|\d+|mini|Mini|MINI)){1,}(?![A-Za-z0-9])"
)
_ASR_PARTIAL_PREFIX_STUTTER_PATTERN = re.compile(r"(没没有没有|没没有|还还是|好好不过|太太难难|太难难|一一般)")
_ASR_MEASURE_WORD_ALT_PATTERN = re.compile(r"一个(?=一[款把台支只件颗枚套])")
_ASR_FUNCTION_PREFIX_STUTTER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"纸纸(?=[箱盒])"), "纸"),
    (re.compile(r"既既(?=能|可以)"), "既"),
    (re.compile(r"又又(?=很|是|可以|能|要)"), "又"),
    (re.compile(r"有有(?=一个|一[款把台支只件颗枚套]|点|些)"), "有"),
    (re.compile(r"我我(?=应该|建议|觉得|知道|看|这)"), "我"),
)
_CJK_SINGLE_PREFIX_STUTTER_CHARS = frozenset(
    "还没好难过在算抢到了的个发售这那也我就"
)
_FLASHLIGHT_MODEL_ALIAS_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?<![A-Za-z0-9])(?:EDC)?(?:幺七|一七|么七)(?![A-Za-z0-9])", re.IGNORECASE), "EDC17"),
    (re.compile(r"(?<![A-Za-z0-9])(?:EDC)?(?:二三|两三)(?![A-Za-z0-9])", re.IGNORECASE), "EDC23"),
    (re.compile(r"(?<![A-Za-z0-9])(?:EDC)?三七(?![A-Za-z0-9])", re.IGNORECASE), "EDC37"),
)
_NOC_CONTEXT_PATTERN = re.compile(r"(?<![A-Za-z0-9])NOC(?![A-Za-z0-9])", re.IGNORECASE)
_NFC_TOKEN_PATTERN = re.compile(r"(?<![A-Za-z0-9])NFC(?![A-Za-z0-9])", re.IGNORECASE)


def clean_final_subtitle_text(text: object) -> str:
    """Remove final-output noise and serialize captions without punctuation."""
    return _clean_final_subtitle_text_and_reason(text)[0]


def normalize_editable_subtitle_text(text: object) -> str:
    """Normalize ASR noise for editable transcript surfaces without hiding spoken content."""
    return normalize_source_transcript_text(text)


def normalize_source_transcript_text(text: object) -> str:
    """Denoise source transcript text without deleting real spoken words.

    This is the only normalization allowed before the manual full-transcript
    stage. It removes mechanical ASR jitter/noise markers, but it must not
    suppress fillers, interjections, profanity,口误, or low-information speech.
    """
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    normalized = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", normalized)
    normalized = _strip_asr_noise_markers(normalized)
    normalized = re.sub(r"^[\s，。！？、：；,.!?…~\-—_]+", "", normalized).strip()
    normalized = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", normalized)
    normalized = _collapse_asr_stutter_text(normalized)
    normalized = re.sub(r"([，。！？、：；,.!?])\1+", r"\1", normalized)
    return re.sub(r"\s{2,}", " ", normalized).strip()


def normalize_flashlight_model_alias_text(text: object) -> str:
    normalized = str(text or "")
    for pattern, replacement in _FLASHLIGHT_MODEL_ALIAS_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def normalize_contextual_noc_alias_text(text: object, *, context_text: object = "") -> str:
    normalized = str(text or "")
    if not normalized or not _NOC_CONTEXT_PATTERN.search(str(context_text or "")):
        return normalized
    return _NFC_TOKEN_PATTERN.sub("NOC", normalized)


def subtitle_display_suppression_reason(text: object) -> str:
    return _clean_final_subtitle_text_and_reason(text)[1]


def _clean_final_subtitle_text_and_reason(text: object) -> tuple[str, str]:
    normalized = str(text or "").strip()
    if not normalized:
        return "", "empty_source_text"
    original = normalized
    normalized = normalize_editable_subtitle_text(normalized)
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
    normalized = _collapse_asr_stutter_text(str(text or "").strip())
    return re.sub(r"\s{2,}", " ", _FINAL_SUBTITLE_PUNCTUATION_PATTERN.sub(" ", normalized)).strip()


def _collapse_asr_stutter_text(text: str) -> str:
    normalized = str(text or "")
    if not normalized:
        return ""
    normalized = _collapse_spaced_ascii_spellout_noise(normalized)
    normalized = _collapse_measure_word_alternative_noise(normalized)
    normalized = _collapse_repeated_mixed_anchor_noise(normalized)
    normalized = _collapse_partial_prefix_stutter_noise(normalized)
    normalized = _collapse_function_prefix_stutter_noise(normalized)
    normalized = _collapse_repeated_cjk_phrase_noise(normalized)
    normalized = _collapse_repeated_cjk_char_noise(normalized)
    normalized = _collapse_partial_prefix_stutter_noise(normalized)
    normalized = _collapse_function_prefix_stutter_noise(normalized)
    return _collapse_repeated_cjk_phrase_noise(normalized)


def _collapse_spaced_ascii_spellout_noise(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        value = match.group(0)
        tokens = re.findall(r"[A-Za-z]+|\d+", value)
        if len(tokens) < 2:
            return value
        if len(tokens) < 3 and not any(token.isdigit() for token in tokens):
            return value
        alpha_tokens = [token for token in tokens if re.search(r"[A-Za-z]", token)]
        if not alpha_tokens:
            return value
        has_model_shape = any(token.isdigit() for token in tokens) or all(len(token) == 1 for token in alpha_tokens)
        if not has_model_shape:
            return value
        if not any(token.isupper() for token in alpha_tokens) and not any(token.isdigit() for token in tokens):
            return value
        return "".join(tokens)

    return _ASCII_SPELLOUT_SEQUENCE_PATTERN.sub(replace, str(text or ""))


def _collapse_measure_word_alternative_noise(text: str) -> str:
    return _ASR_MEASURE_WORD_ALT_PATTERN.sub("", str(text or ""))


def _collapse_function_prefix_stutter_noise(text: str) -> str:
    normalized = str(text or "")
    for pattern, replacement in _ASR_FUNCTION_PREFIX_STUTTER_PATTERNS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def _collapse_repeated_mixed_anchor_noise(text: str) -> str:
    normalized = _ASCII_MODEL_TOKEN_PATTERN.sub(
        lambda match: _collapse_ascii_overlap_token(match.group(0)),
        str(text or ""),
    )
    return re.sub(
        r"([A-Za-z0-9+#.-]{2,})([\u4e00-\u9fff]{1,2})?\1([\u4e00-\u9fff]{1,6})",
        lambda match: f"{match.group(1)}{match.group(3)}",
        normalized,
    )


def _collapse_ascii_overlap_token(token: str) -> str:
    value = str(token or "")
    if len(value) < 4:
        return value
    if re.search(r"[a-z]", value):
        return value
    collapsed = re.sub(r"([A-Z])\1(?=[A-Z])", r"\1", value)
    for unit_len in range(2, min(8, len(collapsed)) + 1):
        unit = collapsed[:unit_len]
        if unit * max(2, len(collapsed) // unit_len) == collapsed:
            return unit
        for overlap in range(1, unit_len):
            if collapsed == unit + unit[overlap:]:
                return unit
    for unit_len in range(3, min(8, len(collapsed)) + 1):
        unit = collapsed[-unit_len:]
        if collapsed == unit[:-1] + unit:
            return unit
    return collapsed


def _collapse_partial_prefix_stutter_noise(text: str) -> str:
    replacements = {
        "没没有没有": "没有",
        "没没有": "没有",
        "还还是": "还是",
        "好好不过": "好不过",
        "太太难难": "太难",
        "太难难": "太难",
        "一一般": "一般",
    }
    return _ASR_PARTIAL_PREFIX_STUTTER_PATTERN.sub(lambda match: replacements[match.group(0)], str(text or ""))


def _collapse_repeated_cjk_phrase_noise(text: str) -> str:
    result = str(text or "")
    for unit_len in range(4, 1, -1):
        pattern = re.compile(rf"([\u4e00-\u9fff]{{{unit_len}}})\1+")
        result = pattern.sub(
            lambda match: match.group(0) if match.group(1) in {"没有", "工业"} else match.group(1),
            result,
        )
    return result


def _collapse_repeated_cjk_char_noise(text: str) -> str:
    result: list[str] = []
    for chunk in re.split(r"([^\u4e00-\u9fff]+)", str(text or "")):
        if not chunk:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]+", chunk):
            result.append(_collapse_repeated_cjk_char_chunk(chunk))
        else:
            result.append(chunk)
    return "".join(result)


def _collapse_repeated_cjk_char_chunk(chunk: str) -> str:
    chars = list(str(chunk or ""))
    if len(chars) < 3:
        return chunk
    if len(set(chars)) == 1 and len(chars) <= 4:
        return chunk
    duplicate_pairs = sum(1 for index in range(1, len(chars)) if chars[index] == chars[index - 1])
    has_common_stutter_particle = bool(re.search(r"([的了个款只次年])\1", chunk))
    has_prefix_stutter = len(chars) >= 3 and chars[0] == chars[1] and chars[0] in _CJK_SINGLE_PREFIX_STUTTER_CHARS
    if duplicate_pairs < 2 and not (
        (duplicate_pairs == 1 and has_common_stutter_particle and len(chars) >= 5)
        or has_prefix_stutter
    ):
        return chunk
    collapsed: list[str] = []
    previous = ""
    for char in chars:
        if char == previous:
            continue
        collapsed.append(char)
        previous = char
    return "".join(collapsed)


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
