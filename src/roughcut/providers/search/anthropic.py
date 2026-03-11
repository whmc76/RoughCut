from __future__ import annotations

import json

import httpx

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.providers.search.base import SearchProvider, SearchResult


class AnthropicSearchProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._base_url = settings.anthropic_base_url.rstrip("/")
        self._model = settings.active_reasoning_model
        self._credential = resolve_credential(
            mode=settings.anthropic_auth_mode,
            direct_value=settings.anthropic_api_key,
            helper_command=settings.anthropic_api_key_helper,
            provider_name="Anthropic",
        )

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        prompt = (
            f'Search the web for "{query}" and return a JSON object with a single key "results". '
            f"Include at most {max_results} items. "
            'Each item must contain "title", "url", and "snippet". '
            "Do not return any extra text."
        )
        payload = {
            "model": self._model,
            "max_tokens": 1200,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        }
        headers = {
            "content-type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self._credential,
            "authorization": f"Bearer {self._credential}",
        }
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(f"{self._base_url}/v1/messages", json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()

        text = "".join(part.get("text", "") for part in data.get("content", []) if part.get("type") == "text")
        parsed = json.loads(extract_json_text(text))

        results: list[SearchResult] = []
        for item in list(parsed.get("results") or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("snippet", "")).strip(),
                    score=0.0,
                )
            )
        return results
