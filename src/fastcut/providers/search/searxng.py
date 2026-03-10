"""Phase 2 placeholder — SearXNG search provider."""
from __future__ import annotations

import httpx

from fastcut.config import get_settings
from fastcut.providers.search.base import SearchProvider, SearchResult


class SearXNGProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.searxng_url.rstrip("/")

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        params = {
            "q": query,
            "format": "json",
            "engines": "google,bing,duckduckgo",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(f"{self._base_url}/search", params=params)
            response.raise_for_status()
            data = response.json()

        results: list[SearchResult] = []
        for item in data.get("results", [])[:max_results]:
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    snippet=item.get("content", ""),
                    score=item.get("score", 0.0),
                )
            )
        return results
