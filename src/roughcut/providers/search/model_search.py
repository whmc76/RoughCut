from __future__ import annotations

import asyncio
import json
import os
import subprocess

from roughcut.config import get_settings
from roughcut.providers.search.base import SearchProvider, SearchResult


class ModelSearchProvider(SearchProvider):
    """Bridge to provider-native search/MCP through a local helper command."""

    def __init__(self) -> None:
        settings = get_settings()
        self._helper = settings.active_model_search_helper.strip()
        if not self._helper:
            raise ValueError("model_search_helper is not configured")

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        env = os.environ.copy()
        env["ROUGHCUT_SEARCH_QUERY"] = query
        env["ROUGHCUT_SEARCH_MAX_RESULTS"] = str(max_results)
        result = await asyncio.to_thread(
            subprocess.run,
            self._helper,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "model search helper failed")

        raw = result.stdout.strip()
        if not raw:
            return []

        data = json.loads(raw)
        items = data.get("results", data) if isinstance(data, dict) else data
        results: list[SearchResult] = []
        for item in list(items or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("snippet", item.get("content", ""))).strip(),
                    score=float(item.get("score", 0.0) or 0.0),
                )
            )
        return results
