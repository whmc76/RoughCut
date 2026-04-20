from __future__ import annotations

import pytest

import roughcut.config as config_mod
import roughcut.providers.factory as factory_mod
from roughcut.providers.factory import get_search_provider
from roughcut.providers.search.base import SearchResult
from roughcut.providers.search.hybrid import HybridSearchProvider


def test_get_search_provider_auto_falls_back_to_searxng_for_local_without_ollama_key():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "local")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "search_fallback_provider", "searxng")
    object.__setattr__(settings, "openai_auth_mode", "api_key")
    object.__setattr__(settings, "model_search_helper", "")
    object.__setattr__(settings, "ollama_api_key", "")
    object.__setattr__(settings, "openai_api_key", "")
    object.__setattr__(settings, "anthropic_api_key", "")
    object.__setattr__(settings, "minimax_api_key", "")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert isinstance(provider, HybridSearchProvider)
    assert provider.provider_names == ["searxng"]


def test_get_search_provider_model_uses_helper():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "model")
    object.__setattr__(settings, "model_search_helper", "python -c \"print('[]')\"")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert provider.__class__.__name__ == "ModelSearchProvider"


def test_get_search_provider_auto_prefers_minimax_when_reasoning_uses_minimax():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "minimax")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")
    object.__setattr__(settings, "searxng_url", "http://localhost:8080")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert isinstance(provider, HybridSearchProvider)
    assert provider.provider_names[:2] == ["searxng", "minimax"]


def test_get_search_provider_auto_prefers_openai_when_reasoning_uses_openai():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "openai_auth_mode", "api_key")
    object.__setattr__(settings, "openai_api_key", "test-key")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert isinstance(provider, HybridSearchProvider)
    assert "openai" in provider.provider_names


def test_get_search_provider_auto_prefers_anthropic_when_reasoning_uses_anthropic():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "anthropic")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "anthropic_auth_mode", "api_key")
    object.__setattr__(settings, "anthropic_api_key", "test-key")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert isinstance(provider, HybridSearchProvider)
    assert "anthropic" in provider.provider_names


def test_get_search_provider_auto_prefers_ollama_when_local_has_api_key():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "local")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "ollama_api_key", "test-key")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert isinstance(provider, HybridSearchProvider)
    assert "ollama" in provider.provider_names


def test_get_search_provider_auto_prefers_codex_cli_bridge_for_openai_codex_compat():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "openai_auth_mode", "codex_compat")
    object.__setattr__(settings, "openai_api_key", "")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "minimax-key")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()

    assert isinstance(provider, HybridSearchProvider)
    assert "openai" not in provider.provider_names
    assert "model" in provider.provider_names
    assert provider.provider_names.index("model") < provider.provider_names.index("minimax")
    assert "minimax" in provider.provider_names


def test_get_search_provider_minimax_explicit():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "minimax")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert provider.__class__.__name__ == "MiniMaxSearchProvider"


def test_get_search_provider_ollama_explicit():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "ollama")
    object.__setattr__(settings, "ollama_api_key", "test-key")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()
    assert provider.__class__.__name__ == "OllamaSearchProvider"


@pytest.mark.asyncio
async def test_get_search_provider_falls_back_to_backup_bundle_when_primary_route_fails():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "reasoning_model", "gpt-5.4")
    object.__setattr__(settings, "llm_backup_enabled", True)
    object.__setattr__(settings, "backup_reasoning_provider", "minimax")
    object.__setattr__(settings, "backup_reasoning_model", "MiniMax-M2.7-highspeed")

    calls: list[str] = []

    class _FakeSearchProvider:
        async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            calls.append(f"{config_mod.get_settings().active_reasoning_provider}:{query}:{max_results}")
            return [SearchResult(title="backup", url="https://example.com", snippet="ok")]

    def _fake_build_search_provider():
        provider = config_mod.get_settings().active_reasoning_provider
        if provider == "openai":
            raise RuntimeError("primary search route unavailable")
        return _FakeSearchProvider()

    original = factory_mod._build_search_provider
    factory_mod._build_search_provider = _fake_build_search_provider
    try:
        provider = get_search_provider()
        results = await provider.search("fallback test", max_results=3)
    finally:
        factory_mod._build_search_provider = original

    assert len(results) == 1
    assert calls == ["minimax:fallback test:3"]


@pytest.mark.asyncio
async def test_hybrid_search_provider_merges_results_and_tolerates_partial_failures():
    from roughcut.providers.search.hybrid import HybridSearchProvider

    class _OkProvider:
        def __init__(self, title: str) -> None:
            self._title = title

        async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            return [
                SearchResult(title=self._title, url=f"https://example.com/{self._title}", snippet=query),
                SearchResult(title="shared", url="https://example.com/shared", snippet=query),
            ][:max_results]

        async def probe(self) -> tuple[bool, str]:
            return True, "ok"

    class _FailProvider:
        async def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
            raise RuntimeError("boom")

        async def probe(self) -> tuple[bool, str]:
            return False, "boom"

    provider = HybridSearchProvider(
        [
            ("searxng", _OkProvider("local")),
            ("minimax", _FailProvider()),
            ("anthropic", _OkProvider("remote")),
        ]
    )

    results = await provider.search("demo", max_results=5)
    ok, detail = await provider.probe()

    assert [item.title for item in results] == ["local", "shared", "remote"]
    assert ok is True
    assert "searxng" in detail
    assert "anthropic" in detail
    assert "minimax: boom" in detail
