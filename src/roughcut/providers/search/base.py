from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    score: float = 0.0


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        """Search the web and return structured results."""

    async def probe(self) -> tuple[bool, str]:
        """Probe whether the provider is operational for live search."""
        try:
            await self.search("runtime readiness probe", max_results=1)
        except Exception as exc:
            return False, str(exc)
        return True, "ok"
