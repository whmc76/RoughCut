from __future__ import annotations

from typing import Any

TEXT_REWRITE_POLICY = "disabled"


def disabled_text_rewrite(value: Any, *, strip: bool = False) -> str:
    text = str(value or "")
    return text.strip() if strip else text


def disabled_correction_candidates() -> list[Any]:
    return []
