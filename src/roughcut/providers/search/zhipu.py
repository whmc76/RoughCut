from __future__ import annotations

from roughcut.config import DEFAULT_ZHIPU_SEARCH_ENGINE, get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.search.base import SearchProvider, SearchResult
from roughcut.providers.zhipu_compat import normalize_zhipu_base_url
from roughcut.providers.zhipu_http import build_zhipu_headers, build_zhipu_request_context, post_zhipu_json


class ZhipuSearchProvider(SearchProvider):
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = resolve_credential(
            mode=settings.zhipu_auth_mode,
            direct_value=settings.zhipu_api_key,
            helper_command=settings.zhipu_api_key_helper,
            provider_name="Zhipu",
        )
        self._base_url = normalize_zhipu_base_url(settings.zhipu_base_url)
        self._search_engine = str(getattr(settings, "zhipu_search_engine", "") or DEFAULT_ZHIPU_SEARCH_ENGINE).strip() or DEFAULT_ZHIPU_SEARCH_ENGINE

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        normalized_query = str(query or "").strip()
        if not normalized_query:
            return []

        payload = {
            "search_query": normalized_query,
            "search_engine": self._search_engine,
            "search_intent": False,
            "count": max(1, min(50, int(max_results))),
            "content_size": "medium",
            **build_zhipu_request_context(),
        }
        data = await post_zhipu_json(
            url=f"{self._base_url}/web_search",
            headers=build_zhipu_headers(self._api_key),
            json_payload=payload,
            timeout_sec=30,
            max_attempts=3,
        )

        results: list[SearchResult] = []
        for item in list(data.get("search_result") or [])[:max_results]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("link", "")).strip(),
                    snippet=str(item.get("content", "")).strip(),
                    score=0.0,
                )
            )
        return results
