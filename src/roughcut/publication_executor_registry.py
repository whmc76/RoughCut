from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.db.models import PublicationAttempt

PublicationExecutorResult = dict[str, Any]

PublicationSubmitHandler = Callable[
    [AsyncSession, PublicationAttempt],
    Awaitable[PublicationExecutorResult],
]
PublicationReconcileHandler = Callable[
    [AsyncSession, PublicationAttempt],
    Awaitable[PublicationExecutorResult],
]


@dataclass(frozen=True)
class PublicationExecutor:
    adapter: str
    submit: PublicationSubmitHandler
    reconcile: PublicationReconcileHandler


class PublicationExecutorRegistry:
    def __init__(self, executors: dict[str, PublicationExecutor] | None = None) -> None:
        self._executors = dict(executors or {})

    def register(self, *adapters: str, executor: PublicationExecutor) -> None:
        for adapter in adapters:
            normalized = _normalize_adapter_key(adapter)
            if normalized:
                self._executors[normalized] = executor

    def resolve(self, adapter: str | None) -> PublicationExecutor | None:
        return self._executors.get(_normalize_adapter_key(adapter))


def _normalize_adapter_key(value: str | None) -> str:
    return str(value or "").strip().lower().replace("-", "_")
