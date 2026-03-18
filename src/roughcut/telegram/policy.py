from __future__ import annotations

from typing import Any


def telegram_agent_enabled(settings: Any) -> bool:
    enabled = bool(
        getattr(settings, "telegram_agent_enabled", False)
        or getattr(settings, "telegram_remote_review_enabled", False)
    )
    return bool(
        enabled
        and str(getattr(settings, "telegram_bot_token", "") or "").strip()
    )


def is_allowed_chat(settings: Any, actual_chat_id: str) -> bool:
    expected_chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
    actual = str(actual_chat_id or "").strip()
    return not expected_chat_id or actual == expected_chat_id
