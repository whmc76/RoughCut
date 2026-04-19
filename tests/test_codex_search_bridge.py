from __future__ import annotations

import roughcut.config as config_mod
from roughcut.providers.factory import get_search_provider
from roughcut.providers.search.hybrid import HybridSearchProvider


def test_get_search_provider_auto_prefers_codex_cli_bridge_for_openai_codex_compat():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "llm_mode", "performance")
    object.__setattr__(settings, "reasoning_provider", "openai")
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "openai_auth_mode", "codex_compat")
    object.__setattr__(settings, "openai_api_key", "")
    object.__setattr__(settings, "model_search_helper", "python scripts/codex_model_search_helper.py")
    object.__setattr__(settings, "minimax_coding_plan_api_key", "minimax-key")
    object.__setattr__(settings, "minimax_api_host", "https://api.minimaxi.com")
    object.__setattr__(settings, "llm_backup_enabled", False)

    provider = get_search_provider()

    assert isinstance(provider, HybridSearchProvider)
    assert "openai" not in provider.provider_names
    assert "model" in provider.provider_names
    assert provider.provider_names.index("model") < provider.provider_names.index("minimax")
    assert "minimax" in provider.provider_names
