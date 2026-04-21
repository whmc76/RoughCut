from __future__ import annotations

import re

_STANDALONE_FILLER_TOKENS = (
    "这个",
    "那个",
    "呃",
    "额",
    "嗯",
    "啊",
    "吧",
)

_SUBTITLE_FILLER_SEPARATOR_PATTERN = re.compile(r"[\s，。！？、：；,.!?…~\-—_()\[\]{}<>《》“”\"'‘’]+")


def clean_final_subtitle_text(text: object) -> str:
    """Remove standalone filler-only subtitle lines at final subtitle output time."""
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if _is_standalone_subtitle_filler(normalized):
        return ""
    return normalized


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
