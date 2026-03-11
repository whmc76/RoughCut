from __future__ import annotations

import httpx

from roughcut.config import get_settings
from roughcut.providers.search.base import SearchProvider, SearchResult


class OllamaSearchProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.ollama_api_key.strip()
        if not self._api_key:
            raise ValueError("Ollama API key is not configured")

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not query.strip():
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {"query": query}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                "https://ollama.com/api/web_search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        results: list[SearchResult] = []
        for item in list(data.get("results") or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("content", item.get("snippet", ""))).strip(),
                    score=0.0,
                )
            )
        return results
