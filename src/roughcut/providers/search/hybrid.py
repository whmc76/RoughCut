from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

from roughcut.providers.search.base import SearchProvider, SearchResult


def _normalize_result_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    parts = urlsplit(value)
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


class HybridSearchProvider(SearchProvider):
    def __init__(self, providers: list[tuple[str, SearchProvider]]) -> None:
        self._providers = [(str(name or "").strip(), provider) for name, provider in providers if provider is not None]
        if not self._providers:
            raise ValueError("No search providers are configured for hybrid search")

    @property
    def provider_names(self) -> list[str]:
        return [name for name, _provider in self._providers]

    async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        if not query.strip():
            return []

        tasks = [
            provider.search(query, max_results=max(max_results, 3))
            for _name, provider in self._providers
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        merged: list[SearchResult] = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()
        failures: list[str] = []

        for (name, _provider), result in zip(self._providers, raw_results, strict=False):
            if isinstance(result, Exception):
                failures.append(f"{name}: {result}")
                continue
            for item in list(result or []):
                normalized_url = _normalize_result_url(item.url)
                normalized_title = str(item.title or "").strip().lower()
                if normalized_url:
                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)
                elif normalized_title:
                    if normalized_title in seen_titles:
                        continue
                    seen_titles.add(normalized_title)
                merged.append(item)
                if len(merged) >= max_results:
                    return merged[:max_results]

        if merged:
            return merged[:max_results]
        if failures:
            raise RuntimeError("; ".join(failures))
        return []

    async def probe(self) -> tuple[bool, str]:
        tasks = [provider.probe() for _name, provider in self._providers]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        ok_names: list[str] = []
        failed: list[str] = []
        for (name, _provider), result in zip(self._providers, raw_results, strict=False):
            if isinstance(result, Exception):
                failed.append(f"{name}: {result}")
                continue
            ok, detail = result
            if ok:
                ok_names.append(name)
            else:
                failed.append(f"{name}: {detail}")

        if ok_names:
            detail = f"ok via {', '.join(ok_names)}"
            if failed:
                detail += f"; degraded={'; '.join(failed)}"
            return True, detail
        if failed:
            return False, "; ".join(failed)
        return False, "No hybrid search providers responded"
