from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

import httpx

from roughcut.config import get_settings
from roughcut.providers.search.base import SearchProvider, SearchResult


def _normalize_minimax_api_host(api_host: str) -> str:
    value = (api_host or "").strip().rstrip("/")
    if not value:
        raise ValueError("MiniMax API host is not configured")

    parts = urlsplit(value)
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    if path.endswith("/anthropic"):
        path = path[:-10]
    normalized = urlunsplit((parts.scheme, parts.netloc, path, parts.query, parts.fragment)).rstrip("/")
    if not normalized:
        raise ValueError("MiniMax API host is invalid")
    return normalized


class MiniMaxSearchProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.minimax_coding_plan_api_key.strip() or settings.minimax_api_key.strip()
        if not self._api_key:
            raise ValueError("MiniMax Coding Plan API key is not configured")
        self._api_host = _normalize_minimax_api_host(settings.minimax_api_host)

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not query.strip():
            return []

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "MM-API-Source": "Minimax-MCP",
            "Content-Type": "application/json",
        }
        payload = {"q": query}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                f"{self._api_host}/v1/coding_plan/search",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        base_resp = data.get("base_resp") or {}
        if int(base_resp.get("status_code", 0) or 0) != 0:
            msg = str(base_resp.get("status_msg") or "MiniMax search failed")
            raise RuntimeError(msg)

        results: list[SearchResult] = []
        for item in list(data.get("organic") or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("link", "")).strip(),
                    snippet=str(item.get("snippet", "")).strip(),
                    score=0.0,
                )
            )
        return results
