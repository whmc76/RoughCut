from __future__ import annotations

import re
from typing import Any


_DIRECT_SPOKEN_REPLACEMENTS = {
    "零": "0",
    "〇": "0",
    "Ｏ": "0",
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
    "Ⅱ": "II",
}

_CONTEXTUAL_SPOKEN_REPLACEMENTS = (
    ("叉", "X"),
    ("洞", "0"),
    ("欧", "O"),
    ("拐", "G"),
)
_CONTEXTUAL_NEIGHBORS = f"A-Z0-9{re.escape(''.join(source for source, _ in _CONTEXTUAL_SPOKEN_REPLACEMENTS))}XOG"


def canonicalize_spoken_identity_text(value: Any) -> str:
    normalized = str(value or "").upper()
    for source, target in _DIRECT_SPOKEN_REPLACEMENTS.items():
        normalized = normalized.replace(source, target)
    for _ in range(len(_CONTEXTUAL_SPOKEN_REPLACEMENTS)):
        previous = normalized
        for source, target in _CONTEXTUAL_SPOKEN_REPLACEMENTS:
            normalized = re.sub(rf"(?<=[{_CONTEXTUAL_NEIGHBORS}]){source}(?=[{_CONTEXTUAL_NEIGHBORS}])", target, normalized)
        if normalized == previous:
            break
    return normalized
