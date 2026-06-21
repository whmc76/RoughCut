from types import SimpleNamespace

import pytest

from roughcut import publication
from roughcut.publication_executor_registry import PublicationExecutor
from roughcut.publication_executor_registry import PublicationExecutorRegistry


@pytest.mark.asyncio
async def test_publication_executor_registry_resolves_registered_aliases():
    async def submit_handler(session, attempt):
        return {"phase": "submit", "adapter": attempt.adapter}

    async def reconcile_handler(session, attempt):
        return {"phase": "reconcile", "adapter": attempt.adapter}

    registry = PublicationExecutorRegistry()
    executor = PublicationExecutor(
        adapter="browser_agent",
        submit=submit_handler,
        reconcile=reconcile_handler,
    )
    registry.register("browser_agent", "x_link_share", executor=executor)

    resolved = registry.resolve("x-link-share")

    assert resolved is executor
    assert await resolved.submit(None, SimpleNamespace(adapter="x_link_share")) == {
        "phase": "submit",
        "adapter": "x_link_share",
    }


@pytest.mark.asyncio
async def test_submit_publication_attempt_for_adapter_routes_browser_agent_executor(monkeypatch):
    called: dict[str, object] = {}

    async def fake_submit(session, attempt, **kwargs):
        called["session"] = session
        called["attempt"] = attempt
        called["kwargs"] = kwargs
        return {"attempt_id": "attempt-1", "status": "submitted"}

    monkeypatch.setattr(publication, "submit_publication_attempt_to_browser_agent", fake_submit)

    attempt = SimpleNamespace(adapter="browser_agent")
    result = await publication.submit_publication_attempt_for_adapter(
        None,
        attempt,
        browser_agent_base_url="http://browser-agent.local",
        auth_token="token",
        http_client=object(),
        request_timeout_sec=12,
    )

    assert result == {"attempt_id": "attempt-1", "status": "submitted"}
    assert called["attempt"] is attempt
    assert called["kwargs"] == {
        "browser_agent_base_url": "http://browser-agent.local",
        "auth_token": "token",
        "http_client": called["kwargs"]["http_client"],
        "request_timeout_sec": 12,
    }


@pytest.mark.asyncio
async def test_submit_publication_attempt_for_adapter_routes_x_link_share_to_browser_agent_executor(monkeypatch):
    called = {"count": 0}

    async def fake_submit(session, attempt, **kwargs):
        called["count"] += 1
        called["kwargs"] = kwargs
        return {"attempt_id": "attempt-2", "status": "published"}

    monkeypatch.setattr(publication, "submit_publication_attempt_to_browser_agent", fake_submit)

    result = await publication.submit_publication_attempt_for_adapter(
        None,
        SimpleNamespace(adapter="x_link_share"),
        browser_agent_base_url="http://browser-agent.local",
    )

    assert result == {"attempt_id": "attempt-2", "status": "published"}
    assert called["count"] == 1
    assert called["kwargs"]["browser_agent_base_url"] == "http://browser-agent.local"
