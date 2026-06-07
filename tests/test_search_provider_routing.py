from types import SimpleNamespace

from roughcut.providers import factory


def test_auto_search_bundle_includes_searxng_from_settings_without_env(monkeypatch) -> None:
    settings = SimpleNamespace(
        searxng_url="http://localhost:8080",
        active_reasoning_provider="minimax",
        active_search_fallback_provider="searxng",
    )

    monkeypatch.delenv("SEARXNG_URL", raising=False)
    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_has_minimax_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_openai_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_openai_codex_cli_search_bridge", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_anthropic_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_ollama_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_build_searxng_search_provider", lambda: "searxng-provider")

    providers = factory._build_auto_search_provider_bundle()

    assert providers == [("searxng", "searxng-provider")]


def test_auto_search_bundle_prefers_zhipu_when_credentials_exist(monkeypatch) -> None:
    settings = SimpleNamespace(
        searxng_url="",
        active_reasoning_provider="zhipu",
        active_search_fallback_provider="searxng",
        zhipu_auth_mode="api_key",
        zhipu_api_key="test-key",
        zhipu_api_key_helper="",
    )

    monkeypatch.setattr(factory, "get_settings", lambda: settings)
    monkeypatch.setattr(factory, "_has_minimax_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_zhipu_search_credentials", lambda _settings: True)
    monkeypatch.setattr(factory, "_has_openai_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_openai_codex_cli_search_bridge", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_anthropic_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_has_ollama_search_credentials", lambda _settings: False)
    monkeypatch.setattr(factory, "_build_zhipu_search_provider", lambda: "zhipu-provider")

    providers = factory._build_auto_search_provider_bundle()

    assert providers == [("zhipu", "zhipu-provider")]
