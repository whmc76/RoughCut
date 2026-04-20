from __future__ import annotations

from types import SimpleNamespace

import pytest


async def test_check_storage_ready_accepts_local_storage_without_client(monkeypatch):
    import roughcut.runtime_health as health_mod

    class LocalStorage:
        def __init__(self) -> None:
            self.bucket_checked = False

        def ensure_bucket(self) -> None:
            self.bucket_checked = True

    storage = LocalStorage()

    monkeypatch.setattr(
        "roughcut.storage.s3.get_storage",
        lambda: storage,
    )

    ok, detail = await health_mod._check_storage_ready()

    assert ok is True
    assert detail == "ok"
    assert storage.bucket_checked is True


@pytest.mark.asyncio
async def test_check_search_ready_skips_when_research_is_disabled(monkeypatch: pytest.MonkeyPatch):
    import roughcut.runtime_health as health_mod

    monkeypatch.setattr(
        health_mod,
        "get_settings",
        lambda: SimpleNamespace(research_verifier_enabled=False, fact_check_enabled=False),
    )

    ok, detail = await health_mod._check_search_ready()

    assert ok is True
    assert detail == "skipped"


@pytest.mark.asyncio
async def test_check_search_ready_reports_probe_failure(monkeypatch: pytest.MonkeyPatch):
    import roughcut.runtime_health as health_mod

    class _FakeSearchProvider:
        async def probe(self) -> tuple[bool, str]:
            return False, "Missing scopes: api.responses.write"

    monkeypatch.setattr(
        health_mod,
        "get_settings",
        lambda: SimpleNamespace(research_verifier_enabled=True, fact_check_enabled=False),
    )
    monkeypatch.setattr(health_mod, "get_search_provider", lambda: _FakeSearchProvider())

    ok, detail = await health_mod._check_search_ready()

    assert ok is False
    assert "api.responses.write" in detail
