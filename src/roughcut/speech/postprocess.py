from __future__ import annotations

import difflib
import re
import uuid
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import FactClaim, SubtitleCorrection, SubtitleItem, TranscriptSegment


@dataclass
class SubtitleEntry:
    index: int
    start: float
    end: float
    text_raw: str
    text_norm: str


_ER_FILLER_RE = re.compile(r"呃+")
_CHINESE_DIGIT_VALUES = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNIT_VALUES = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}
_DISPLAY_ORDINAL_UNITS = (
    "分钟",
    "小时",
    "句",
    "步",
    "代",
    "次",
    "档",
    "页",
    "期",
    "集",
    "层",
    "排",
    "条",
    "款",
    "件",
    "章",
    "轮",
    "名",
    "天",
    "年",
    "月",
    "秒",
    "个",
)
_DISPLAY_QUANTITY_UNITS = (
    "分钟",
    "小时",
    "毫米",
    "厘米",
    "英寸",
    "代",
    "档",
    "个",
    "倍",
    "号",
    "日",
    "次",
    "年",
    "月",
    "天",
    "秒",
    "寸",
    "项",
    "种",
    "款",
    "把",
    "条",
    "层",
    "米",
    "毫升",
    "升",
    "克",
    "千克",
    "公斤",
    "元",
    "块",
    "颗",
    "排",
    "面",
    "页",
    "张",
    "集",
    "级",
    "斤",
    "瓦",
    "伏",
    "安",
)
_DISPLAY_NUM_TOKEN = r"[零〇一二两三四五六七八九十百千万\d]+"
_DISPLAY_ORDINAL_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_ORDINAL_UNITS), key=len, reverse=True)
)
_DISPLAY_QUANTITY_UNIT_PATTERN = "|".join(
    sorted((re.escape(unit) for unit in _DISPLAY_QUANTITY_UNITS), key=len, reverse=True)
)
_PERCENT_NUMBER_RE = re.compile(rf"百分之(?P<number>{_DISPLAY_NUM_TOKEN})")
_ORDINAL_NUMBER_RE = re.compile(
    rf"第(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_ORDINAL_UNIT_PATTERN})"
)
_QUANTITY_NUMBER_RE = re.compile(
    rf"(?<![第A-Za-z0-9])(?P<number>{_DISPLAY_NUM_TOKEN})(?P<unit>{_DISPLAY_QUANTITY_UNIT_PATTERN})"
)
_TIME_WITH_MINUTE_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上)?)"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点(?P<minute>{_DISPLAY_NUM_TOKEN})(?:分|分钟)?"
)
_TIME_HALF_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上)?)"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点半"
)
_TIME_HOUR_ONLY_RE = re.compile(
    rf"(?P<prefix>(?:凌晨|早上|上午|中午|下午|晚上))"
    rf"(?P<hour>{_DISPLAY_NUM_TOKEN})点(?=(?:整|钟|左右|前|后|开始|开播|上线|下班|出发|到|[，,。！？!?；;]|$))"
)
_COLLOQUIAL_PRICE_RE = re.compile(
    rf"(?P<integer>{_DISPLAY_NUM_TOKEN})块(?P<fraction>{_DISPLAY_NUM_TOKEN})(?![\u4e00-\u9fffA-Za-z0-9])"
)
_ALPHA_NUMERIC_COMBO_RE = re.compile(
    rf"(?P<prefix>[A-Za-z])(?P<number>{_DISPLAY_NUM_TOKEN})(?=[\u4e00-\u9fff]|$)"
)
_SPACED_MODEL_TOKEN_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<letters>(?:[A-Za-z]\s+){{1,7}}[A-Za-z])\s+"
    rf"(?P<number>{_DISPLAY_NUM_TOKEN})(?:\s+(?P<suffix>[A-Za-z]+))?(?![A-Za-z0-9])"
)
_NATURAL_SINGLE_UNITS = {"个", "次", "年", "月", "天", "小时", "分钟", "秒"}
_VAGUE_NUMBER_TOKENS = {
    "一两",
    "一二",
    "二三",
    "两三",
    "三四",
    "四五",
    "五六",
    "六七",
    "七八",
    "八九",
}
_INFO_COUNT_NOUN_PREFIXES = (
    "档位",
    "接口",
    "版本",
    "型号",
    "规格",
    "参数",
    "模式",
    "方案",
    "步骤",
    "配色",
    "功能",
    "层",
    "页",
    "面",
    "代",
    "代目",
    "级",
    "级别",
    "平台",
    "模块",
    "尺寸",
    "机位",
    "镜头",
    "孔位",
    "按钮",
    "刀型",
    "钢材",
    "容量",
    "续航",
)
_SUBTITLE_FILLER_PREFIX_TOKENS = (
    "呃",
    "嗯",
    "啊",
    "吧",
    "呢",
    "吗",
    "嘛",
    "呀",
    "哈",
    "哦",
    "诶",
    "欸",
    "哎",
    "那个",
    "这个",
    "就是",
    "然后",
    "其实",
    "那么",
    "对吧",
    "好吧",
    "这样子",
    "所以说",
    "总的来说",
)
_SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS = {
    "那个",
    "这个",
    "就是",
    "然后",
    "其实",
    "那么",
    "对吧",
    "好吧",
    "这样子",
    "所以说",
    "总的来说",
}
_INLINE_FILLER_RE = re.compile(r"(?:呃|嗯|诶|欸|哎|哈|哦)+")
_INLINE_PARTICLE_RE = re.compile(r"(?<=[\u4e00-\u9fffA-Za-z0-9])(?:啊|吧|呢|吗|嘛|呀)(?=[\u4e00-\u9fffA-Za-z0-9])")
_TRAILING_FILLER_RE = re.compile(r"(?:呢|吗|嘛|呀|哈|哦|诶|欸|哎)+$")
_TRAILING_KEEPABLE_PARTICLE_RE = re.compile(r"(?:啊+|吧+)$")
_TERMINAL_PUNCTUATION = "。！？!?"
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
    text = normalize_display_text(text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[。.]{2,}", "。", text)
    text = re.sub(r"[，,]+[。.!！？]+", "。", text)
    text = re.sub(r"[。.!！？]+[，,]+", "。", text)
    if len(text) > 5 and text and text[-1] not in "。！？，、…":
        text += "。"
    return text


def normalize_display_text(text: str, *, cleanup_fillers: bool = True) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    result = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", result)
    if cleanup_fillers:
        result = cleanup_subtitle_fillers(result)
    result = _normalize_display_numbers(result)
    result = apply_subtitle_clause_spacing(result)
    result = re.sub(r"\s+([，,。.!！？；;：:])", r"\1", result)
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[。.]{2,}", "。", result)
    result = re.sub(r"[，,]+([。.!！？])", r"\1", result)
    result = re.sub(r"\s{2,}", " ", result)
    return result.strip("，,")


def normalize_display_numbers(text: str) -> str:
    """Normalize numeric expressions in subtitle text without touching spacing/punctuation."""
    return _normalize_display_numbers(str(text or "").strip())


def cleanup_subtitle_fillers(text: str) -> str:
    result = str(text or "").strip()
    if not result:
        return result

    pieces = [piece for piece in re.split(r"([，,。！？!?；;])", result) if piece != ""]
    cleaned: list[str] = []
    for index, piece in enumerate(pieces):
        if piece in "，,。！？!?；;":
            if cleaned and cleaned[-1] in "，,；;" and piece in _TERMINAL_PUNCTUATION:
                cleaned[-1] = piece
                continue
            if cleaned and cleaned[-1] not in "，,。！？!?；;":
                cleaned.append(piece)
            continue

        clause = piece.strip()
        if not clause:
            continue
        clause = _strip_subtitle_filler_prefixes(clause)
        clause = _ER_FILLER_RE.sub("", clause)
        clause = _INLINE_FILLER_RE.sub("", clause)
        clause = _INLINE_PARTICLE_RE.sub("", clause)
        clause = _strip_subtitle_filler_suffixes(
            clause,
            keep_sentence_final_particle=_next_piece_is_terminal_punctuation(pieces, index),
        )
        clause = _strip_subtitle_filler_prefixes(clause)
        clause = clause.strip("，, ")
        if not clause or clause in _SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS:
            continue
        cleaned.append(clause)

    collapsed = "".join(cleaned).strip("，,")
    collapsed = re.sub(r"([，,；;]){2,}", lambda match: match.group(0)[0], collapsed)
    collapsed = re.sub(r"[，,]+([。！？!?；;])", r"\1", collapsed)
    return collapsed


def apply_subtitle_clause_spacing(text: str) -> str:
    result = str(text or "").strip()
    if not result or len(result.replace(" ", "")) <= 10:
        return result
    result = re.sub(r"([，；：])(?=[^\s])", r"\1 ", result)
    if " " not in result and len(result) >= 14:
        for token in _GOOD_BREAK_PREFIXES:
            result = re.sub(rf"(?<!^)(?<!\s)(?={re.escape(token)})", " ", result)
    return re.sub(r"\s{2,}", " ", result).strip()


def _normalize_display_numbers(text: str) -> str:
    if not text:
        return text

    result = _normalize_spaced_model_tokens(text)
    result = _normalize_colloquial_price_tokens(result)
    result = _normalize_alpha_numeric_tokens(result)
    result = _normalize_time_tokens(result)

    def replace_percent(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        return f"{number}%" if number else match.group(0)

    def replace_ordinal(match: re.Match[str]) -> str:
        number = _normalize_numeric_token(match.group("number"))
        unit = match.group("unit")
        return f"第{number}{unit}" if number else match.group(0)

    def replace_quantity(match: re.Match[str]) -> str:
        raw_number = match.group("number")
        number = _normalize_numeric_token(match.group("number"))
        unit = match.group("unit")
        if _should_preserve_natural_quantity(
            raw_number,
            unit,
            match.string[match.end():match.end() + 6],
        ):
            return match.group(0)
        return f"{number}{unit}" if number else match.group(0)

    result = _PERCENT_NUMBER_RE.sub(replace_percent, result)
    result = _ORDINAL_NUMBER_RE.sub(replace_ordinal, result)
    result = _QUANTITY_NUMBER_RE.sub(replace_quantity, result)
    return result


def _normalize_colloquial_price_tokens(text: str) -> str:
    def replace_price(match: re.Match[str]) -> str:
        integer = _normalize_numeric_token(match.group("integer"))
        fraction = _normalize_numeric_token(match.group("fraction"))
        if not integer or not fraction:
            return match.group(0)
        return f"{integer}块{fraction}"

    return _COLLOQUIAL_PRICE_RE.sub(replace_price, text)


def _normalize_spaced_model_tokens(text: str) -> str:
    def replace_model(match: re.Match[str]) -> str:
        letters = re.sub(r"\s+", "", str(match.group("letters") or "")).upper()
        number = _normalize_numeric_token(match.group("number"))
        suffix = re.sub(r"\s+", "", str(match.group("suffix") or ""))
        if not letters or not number:
            return match.group(0)
        suffix_text = suffix.lower() if suffix else ""
        return f"{letters}-{number}{suffix_text}"

    return _SPACED_MODEL_TOKEN_RE.sub(replace_model, text)


def _normalize_alpha_numeric_tokens(text: str) -> str:
    def replace_alpha_numeric(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "").upper()
        number = _normalize_numeric_token(match.group("number"))
        return f"{prefix}{number}" if number else match.group(0)

    return _ALPHA_NUMERIC_COMBO_RE.sub(replace_alpha_numeric, text)


def _normalize_time_tokens(text: str) -> str:
    def replace_time_with_minute(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        minute = _normalize_numeric_token(match.group("minute"))
        if not hour or not minute:
            return match.group(0)
        return f"{prefix}{hour}点{minute}"

    def replace_time_half(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        return f"{prefix}{hour}点30" if hour else match.group(0)

    def replace_time_hour_only(match: re.Match[str]) -> str:
        prefix = str(match.group("prefix") or "")
        hour = _normalize_numeric_token(match.group("hour"))
        return f"{prefix}{hour}点" if hour else match.group(0)

    result = _TIME_HALF_RE.sub(replace_time_half, text)
    result = _TIME_WITH_MINUTE_RE.sub(replace_time_with_minute, result)
    result = _TIME_HOUR_ONLY_RE.sub(replace_time_hour_only, result)
    return result


def _should_preserve_natural_quantity(number_token: str, unit: str, tail_text: str) -> bool:
    normalized_token = str(number_token or "").strip()
    if not normalized_token:
        return False
    if normalized_token in _VAGUE_NUMBER_TOKENS:
        return True
    if normalized_token == "一" and unit in _NATURAL_SINGLE_UNITS:
        if unit == "个" and _starts_with_info_count_noun(tail_text):
            return False
        return True
    return False


def _starts_with_info_count_noun(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    return any(candidate.startswith(prefix) for prefix in _INFO_COUNT_NOUN_PREFIXES)


def _normalize_numeric_token(token: str) -> str:
    value = str(token or "").strip()
    if not value:
        return value
    if value.isdigit():
        return value
    if re.fullmatch(r"[零〇一二两三四五六七八九]+", value):
        return "".join(str(_CHINESE_DIGIT_VALUES[char]) for char in value)
    parsed = _parse_chinese_number(value)
    return str(parsed) if parsed is not None else value


def _parse_chinese_number(token: str) -> int | None:
    if not token:
        return None
    total = 0
    section = 0
    number = 0
    saw_token = False
    for char in token:
        if char.isdigit():
            number = number * 10 + int(char)
            saw_token = True
            continue
        if char in _CHINESE_DIGIT_VALUES:
            number = _CHINESE_DIGIT_VALUES[char]
            saw_token = True
            continue
        unit = _CHINESE_UNIT_VALUES.get(char)
        if unit is None:
            return None
        saw_token = True
        if unit == 10000:
            section = (section + (number or 1)) * unit
            total += section
            section = 0
            number = 0
            continue
        section += (number or 1) * unit
        number = 0
    if not saw_token:
        return None
    return total + section + number


def _strip_subtitle_filler_prefixes(text: str) -> str:
    result = str(text or "").strip()
    changed = True
    while result and changed:
        changed = False
        result = result.lstrip("，, ")
        for token in _SUBTITLE_FILLER_PREFIX_TOKENS:
            if result.startswith(token) and len(result) > len(token):
                result = result[len(token):].lstrip("，, ")
                changed = True
                break
    return result


def _strip_subtitle_filler_suffixes(text: str, *, keep_sentence_final_particle: bool) -> str:
    result = str(text or "").strip().rstrip("，, ")
    if not result:
        return result

    while True:
        changed = False
        for token in (*_SUBTITLE_FILLER_WHOLE_CLAUSE_TOKENS, "呢", "吗", "嘛", "呀", "哈", "哦", "诶", "欸", "哎"):
            if result.endswith(token):
                result = result[:-len(token)].rstrip("，, ")
                changed = True
                break
        if not changed:
            break

    result = _TRAILING_FILLER_RE.sub("", result).rstrip("，, ")
    if keep_sentence_final_particle:
        result = _TRAILING_KEEPABLE_PARTICLE_RE.sub(lambda match: match.group(0)[-1], result)
    else:
        result = _TRAILING_KEEPABLE_PARTICLE_RE.sub("", result).rstrip("，, ")
    return result


def _next_piece_is_terminal_punctuation(pieces: list[str], index: int) -> bool:
    for next_index in range(index + 1, len(pieces)):
        next_piece = pieces[next_index]
        if not next_piece.strip():
            continue
        return next_piece in _TERMINAL_PUNCTUATION
    return True


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

    merged = _merge_continuation_entries(subtitles, max_chars=max_chars, max_duration=max_duration)
    return _cleanup_subtitle_entries(merged)


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


def _cleanup_subtitle_entries(entries: list[SubtitleEntry]) -> list[SubtitleEntry]:
    cleaned: list[SubtitleEntry] = []
    for entry in entries:
        duration = float(entry.end) - float(entry.start)
        if duration <= 0.08:
            continue
        normalized_text = normalize_text(entry.text_raw)
        if not normalized_text.strip("，。！？!?、,.；;：:\"'()（）[]【】"):
            continue
        if cleaned:
            previous = cleaned[-1]
            previous_norm = normalize_text(previous.text_raw)
            gap = float(entry.start) - float(previous.end)
            if normalized_text == previous_norm and gap <= 0.18:
                cleaned[-1] = SubtitleEntry(
                    previous.index,
                    previous.start,
                    max(previous.end, entry.end),
                    previous.text_raw,
                    previous_norm,
                )
                continue
            if gap <= 0.35 and _are_near_duplicate_subtitles(previous.text_raw, entry.text_raw):
                merged_text = _pick_clearer_duplicate_text(previous.text_raw, entry.text_raw)
                cleaned[-1] = SubtitleEntry(
                    previous.index,
                    previous.start,
                    max(previous.end, entry.end),
                    merged_text,
                    normalize_text(merged_text),
                )
                continue
        cleaned.append(
            SubtitleEntry(
                len(cleaned),
                entry.start,
                entry.end,
                entry.text_raw,
                normalized_text,
            )
        )
    return cleaned


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


def _compact_compare_text(text: str) -> str:
    compact = re.sub(r"[，。！？!?、；;：:,.\-\"'()\[\]（）【】\s]+", "", str(text or "").strip())
    compact = re.sub(r"(其实|就是|然后|那个|这个|当然|的话|一下|一下子|也算|算是|上是|吧)+", "", compact)
    return compact


def _are_near_duplicate_subtitles(left: str, right: str) -> bool:
    left_compact = _compact_compare_text(left)
    right_compact = _compact_compare_text(right)
    if not left_compact or not right_compact:
        return False
    if left_compact == right_compact:
        return True
    shorter, longer = sorted((left_compact, right_compact), key=len)
    if len(shorter) >= 4 and shorter in longer:
        return True
    ratio = difflib.SequenceMatcher(a=left_compact, b=right_compact).ratio()
    return ratio >= 0.8


def _pick_clearer_duplicate_text(left: str, right: str) -> str:
    left_text = _normalize_compare_subtitle_text(left).rstrip("。！？!?")
    right_text = _normalize_compare_subtitle_text(right).rstrip("。！？!?")
    left_compact = _compact_compare_text(left_text)
    right_compact = _compact_compare_text(right_text)
    if len(right_compact) > len(left_compact):
        return right_text
    if len(left_compact) > len(right_compact):
        return left_text
    if len(right_text) > len(left_text):
        return right_text
    return left_text


def _words_to_text(words: list[dict]) -> str:
    return "".join(re.sub(r"\s+", "", str(word.get("word", ""))) for word in words)


def _normalize_compare_subtitle_text(text: str) -> str:
    result = str(text or "").strip()
    result = re.sub(r"[，,]{2,}", "，", result)
    result = re.sub(r"[。.]{2,}", "。", result)
    result = re.sub(r"[，,]+[。.!！？]+", "。", result)
    result = re.sub(r"[。.!！？]+[，,]+", "。", result)
    result = re.sub(r"([\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", r"\1", result)
    return result


async def save_subtitle_items(
    job_id: uuid.UUID,
    entries: list[SubtitleEntry],
    session: AsyncSession,
    version: int = 1,
) -> list[SubtitleItem]:
    """Persist subtitle entries to the database."""
    await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job_id))
    await session.execute(delete(FactClaim).where(FactClaim.job_id == job_id))
    await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job_id, SubtitleItem.version == version))

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
