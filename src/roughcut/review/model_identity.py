from __future__ import annotations

import re
from typing import Any

from roughcut.review.spoken_identity import canonicalize_spoken_identity_text


_MODEL_LIKE_RE = re.compile(
    r"^(?P<prefix>[A-Za-z]{1,8})(?P<number>[0-9零〇幺一二两三四五六七八九十百千万]{1,6})(?P<suffix>[A-Za-z0-9\u4e00-\u9fff-]*)$",
    re.IGNORECASE,
)

_CHINESE_DIGIT_VALUES = {
    "零": 0,
    "〇": 0,
    "幺": 1,
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

_CHINESE_DIGIT_TEXT_MAP = {
    "零": "0",
    "〇": "0",
    "幺": "1",
    "一": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
}

_CHINESE_UNIT_VALUES = {
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
}


def _compact_model_text(value: Any) -> str:
    compact = re.sub(r"\s+", "", str(value or "").strip())
    if not compact:
        return ""
    return canonicalize_spoken_identity_text(compact)


def parse_model_number_token(token: str) -> int | None:
    if not token:
        return None
    total = 0
    section = 0
    number = 0
    saw_token = False
    for char in str(token):
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


def normalize_model_number(token: str) -> str:
    value = _compact_model_text(token)
    if not value:
        return ""
    if value.isdigit():
        return value
    if re.fullmatch(r"[零〇幺一二两三四五六七八九]+", value):
        return "".join(_CHINESE_DIGIT_TEXT_MAP.get(char, char) for char in value)
    parsed = parse_model_number_token(value)
    return str(parsed) if parsed is not None else ""


def extract_model_signature(value: Any) -> tuple[str, str, str] | None:
    compact = _compact_model_text(value)
    if not compact:
        return None
    match = _MODEL_LIKE_RE.fullmatch(compact)
    if not match:
        return None
    number = normalize_model_number(match.group("number"))
    if not number:
        return None
    return (
        str(match.group("prefix") or "").upper(),
        number,
        str(match.group("suffix") or "").casefold(),
    )


def model_numbers_conflict(source: Any, target: Any) -> bool:
    source_signature = extract_model_signature(source)
    target_signature = extract_model_signature(target)
    if not source_signature or not target_signature:
        return False
    return (
        source_signature[0] == target_signature[0]
        and source_signature[2] == target_signature[2]
        and source_signature[1] != target_signature[1]
    )


def filter_conflicting_model_wrong_forms(*, correct_form: Any, wrong_forms: list[Any]) -> list[str]:
    filtered: list[str] = []
    for wrong_form in wrong_forms:
        value = str(wrong_form or "").strip()
        if not value or model_numbers_conflict(value, correct_form):
            continue
        filtered.append(value)
    return filtered
