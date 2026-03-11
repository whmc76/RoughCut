from __future__ import annotations

import json

import openai

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.reasoning.base import extract_json_text
from roughcut.providers.search.base import SearchProvider, SearchResult


class OpenAISearchProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._client = openai.AsyncOpenAI(
            api_key=resolve_credential(
                mode=settings.openai_auth_mode,
                direct_value=settings.openai_api_key,
                helper_command=settings.openai_api_key_helper,
                provider_name="OpenAI",
            ),
            base_url=settings.openai_base_url.rstrip("/"),
        )
        self._model = settings.active_reasoning_model

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        prompt = (
            f'Search the web for "{query}" and return a JSON object with a single key "results". '
            f"Include at most {max_results} items. "
            'Each item must contain "title", "url", and "snippet". '
            "Do not return any extra text."
        )
        response = await self._client.responses.create(
            model=self._model,
            tools=[{"type": "web_search"}],
            input=prompt,
            max_output_tokens=1200,
        )
        text = response.output_text or ""
        data = json.loads(extract_json_text(text))

        results: list[SearchResult] = []
        for item in list(data.get("results") or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=str(item.get("snippet", "")).strip(),
                    score=0.0,
                )
            )
        return results
