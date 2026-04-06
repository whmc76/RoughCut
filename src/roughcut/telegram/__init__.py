from __future__ import annotations

__all__ = ["handle_telegram_command", "is_allowed_chat", "telegram_agent_enabled"]


def __getattr__(name: str):
    if name == "handle_telegram_command":
        from roughcut.telegram.commands import handle_telegram_command

        return handle_telegram_command
    if name in {"is_allowed_chat", "telegram_agent_enabled"}:
        from roughcut.telegram.policy import is_allowed_chat, telegram_agent_enabled

        if name == "is_allowed_chat":
            return is_allowed_chat
        return telegram_agent_enabled
    raise AttributeError(name)


def __dir__() -> list[str]:
    return sorted(__all__)
