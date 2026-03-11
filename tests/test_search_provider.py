from __future__ import annotations

import roughcut.config as config_mod
from roughcut.providers.factory import get_search_provider


def test_get_search_provider_auto_falls_back_to_searxng():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "auto")
    object.__setattr__(settings, "search_fallback_provider", "searxng")
    object.__setattr__(settings, "model_search_helper", "")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "SearXNGProvider"


def test_get_search_provider_model_uses_helper():
    config_mod._settings = None
    settings = config_mod.get_settings()
    object.__setattr__(settings, "search_provider", "model")
    object.__setattr__(settings, "model_search_helper", "python -c \"print('[]')\"")

    provider = get_search_provider()
    assert provider.__class__.__name__ == "ModelSearchProvider"
