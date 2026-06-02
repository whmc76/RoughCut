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
