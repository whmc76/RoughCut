from __future__ import annotations

import pytest

from roughcut.providers.search.minimax import MiniMaxSearchProvider, _normalize_minimax_api_host


def test_normalize_minimax_api_host_strips_v1_and_anthropic_suffix():
    assert _normalize_minimax_api_host("https://api.minimaxi.com/v1") == "https://api.minimaxi.com"
    assert _normalize_minimax_api_host("https://api.minimaxi.com/anthropic") == "https://api.minimaxi.com"


def test_search_provider_prefers_coding_plan_key(monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "minimax_api_key", "reasoning-key")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "coding-plan-key")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")

    provider = MiniMaxSearchProvider()

    assert provider._api_key == "coding-plan-key"
    assert provider._api_host == "https://api.minimaxi.com"


def test_search_provider_falls_back_to_reasoning_key(monkeypatch):
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "minimax_api_key", "reasoning-key")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")

    provider = MiniMaxSearchProvider()

    assert provider._api_key == "reasoning-key"
    assert provider._api_host == "https://api.minimaxi.com"


def test_search_provider_requires_some_key():
    import roughcut.config as config_mod

    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "minimax_api_key", "")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")

    with pytest.raises(ValueError, match="Coding Plan API key"):
        MiniMaxSearchProvider()
