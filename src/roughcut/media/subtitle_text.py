from __future__ import annotations

import re

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
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    normalized = _strip_asr_noise_markers(normalized)
    normalized = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", normalized)
    if _is_asr_noise_only(normalized):
        return ""
    normalized = _drop_final_noise_clauses(normalized)
    if not normalized or _is_standalone_subtitle_filler(normalized) or _is_disruption_clause(normalized):
        return ""
    return _format_final_subtitle_text(normalized)


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
