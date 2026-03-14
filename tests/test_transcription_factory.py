from __future__ import annotations

from roughcut.config import Settings
from roughcut.providers import factory as provider_factory


def test_transcription_provider_cache_reuses_instance(monkeypatch):
    provider_factory._TRANSCRIPTION_PROVIDER_CACHE.clear()

    settings = Settings(_env_file=None, transcription_provider="local_whisper", transcription_model="base")
    monkeypatch.setattr(provider_factory, "get_settings", lambda: settings)

    created: list[str] = []

    class DummyProvider:
        def __init__(self, *, model_size: str) -> None:
            created.append(model_size)

    import sys
    import types

    monkeypatch.setitem(
        sys.modules,
        "roughcut.providers.transcription.local_whisper",
        types.SimpleNamespace(LocalWhisperProvider=DummyProvider),
    )

    first = provider_factory.get_transcription_provider()
    second = provider_factory.get_transcription_provider()

    assert first is second
    assert created == ["base"]


def test_transcription_provider_supports_funasr(monkeypatch):
    provider_factory._TRANSCRIPTION_PROVIDER_CACHE.clear()

    settings = Settings(_env_file=None, transcription_provider="funasr", transcription_model="sensevoice-small")
    monkeypatch.setattr(provider_factory, "get_settings", lambda: settings)

    created: list[str] = []

    class DummyProvider:
        def __init__(self, *, model_name: str) -> None:
            created.append(model_name)

    import sys
    import types

    monkeypatch.setitem(
        sys.modules,
        "roughcut.providers.transcription.funasr_provider",
        types.SimpleNamespace(FunASRProvider=DummyProvider),
    )

    first = provider_factory.get_transcription_provider()
    second = provider_factory.get_transcription_provider()

    assert first is second
    assert created == ["sensevoice-small"]
