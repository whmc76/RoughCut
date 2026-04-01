from __future__ import annotations

from typing import Any


def telegram_bot_ready(settings: Any) -> bool:
    return bool(str(getattr(settings, "telegram_bot_token", "") or "").strip())


def telegram_review_enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "telegram_remote_review_enabled", False)
        and telegram_bot_ready(settings)
    )


def telegram_agent_enabled(settings: Any) -> bool:
    return bool(
        getattr(settings, "telegram_agent_enabled", False)
        and telegram_bot_ready(settings)
    )


def telegram_service_enabled(settings: Any) -> bool:
    return bool(telegram_review_enabled(settings) or telegram_agent_enabled(settings))


def is_allowed_chat(settings: Any, actual_chat_id: str) -> bool:
    expected_chat_id = str(getattr(settings, "telegram_bot_chat_id", "") or "").strip()
    actual = str(actual_chat_id or "").strip()
    return not expected_chat_id or actual == expected_chat_id
