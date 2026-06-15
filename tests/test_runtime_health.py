import pytest

from roughcut.runtime_health import build_readiness_payload
from scripts.run_fullchain_batch import ensure_batch_runtime_ready


@pytest.mark.asyncio
async def test_runtime_health_marks_search_as_non_blocking_warning(monkeypatch) -> None:
    async def ok_check() -> tuple[bool, str]:
        return True, "ok"

    async def failed_search() -> tuple[bool, str]:
        return False, "rate limited"

    monkeypatch.setattr("roughcut.runtime_health._check_database_ready", ok_check)
    monkeypatch.setattr("roughcut.runtime_health._check_redis_ready", ok_check)
    monkeypatch.setattr("roughcut.runtime_health._check_storage_ready", ok_check)
    monkeypatch.setattr("roughcut.runtime_health._check_search_ready", failed_search)

    payload = await build_readiness_payload()

    assert payload["status"] == "ready"
    assert payload["warning_checks"] == ["search"]
    assert payload["checks"]["search"]["status"] == "failed"
    assert payload["checks"]["search"]["blocking"] is False


def test_batch_runtime_ready_ignores_non_blocking_search_failures(monkeypatch) -> None:
    async def fake_build_readiness_payload() -> dict:
        return {
            "status": "ready",
            "checks": {
                "database": {"status": "ok", "detail": "ok", "blocking": True},
                "search": {"status": "failed", "detail": "rate limited", "blocking": False},
            },
        }

    monkeypatch.setattr("scripts.run_fullchain_batch.build_readiness_payload", fake_build_readiness_payload)

    ensure_batch_runtime_ready()
