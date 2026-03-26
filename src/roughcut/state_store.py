from __future__ import annotations

import asyncio
from copy import deepcopy
import threading
from typing import Any, Awaitable, Callable, TypeVar


T = TypeVar("T")

RUNTIME_OVERRIDES_KEY = "runtime_overrides"
ACTIVE_CONFIG_PROFILE_KEY = "active_config_profile_id"
PACKAGING_CONFIG_KEY = "packaging_config"


def run_db_operation(operation: Callable[[Any], Awaitable[T]]) -> T:
    async def _runner() -> T:
        from roughcut.db.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            return await operation(session)

    return _run_async(_runner())


def get_json_setting(key: str, default: Any = None) -> Any:
    async def _operation(session: Any) -> Any:
        from roughcut.db.models import AppSetting

        row = await session.get(AppSetting, key)
        if row is None:
            return deepcopy(default)
        return deepcopy(row.value_json)

    return run_db_operation(_operation)


def set_json_setting(key: str, value: Any) -> Any:
    payload = deepcopy(value)

    async def _operation(session: Any) -> Any:
        from roughcut.db.models import AppSetting

        row = await session.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value_json=payload)
            session.add(row)
        else:
            row.value_json = payload
        await session.commit()
        return deepcopy(row.value_json)

    return run_db_operation(_operation)


def delete_setting(key: str) -> None:
    async def _operation(session: Any) -> None:
        from roughcut.db.models import AppSetting

        row = await session.get(AppSetting, key)
        if row is not None:
            await session.delete(row)
            await session.commit()

    run_db_operation(_operation)


def _run_async(coro: Awaitable[T]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            box["error"] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]
