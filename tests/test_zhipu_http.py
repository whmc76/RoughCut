import httpx
import pytest

import roughcut.providers.zhipu_http as zhipu_http
from roughcut.providers.zhipu_http import post_zhipu_json, zhipu_response_diagnostics


@pytest.mark.asyncio
async def test_post_zhipu_json_retries_transient_status(monkeypatch) -> None:
    attempts = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(
                429,
                headers={"retry-after-ms": "1"},
                request=request,
                json={"error": {"message": "rate limit"}},
            )
        return httpx.Response(200, request=request, json={"ok": True})

    transport = httpx.MockTransport(handler)

    class DummyClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("roughcut.providers.zhipu_http.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("roughcut.providers.zhipu_http.asyncio.sleep", fast_sleep)

    result = await post_zhipu_json(
        url="https://example.com/chat/completions",
        headers={"Authorization": "Bearer demo"},
        json_payload={"model": "glm-5.1"},
        timeout_sec=5,
        max_attempts=3,
    )

    assert result == {"ok": True}
    assert attempts["count"] == 2


@pytest.mark.asyncio
async def test_post_zhipu_json_waits_for_active_provider_cooldown(monkeypatch) -> None:
    sleeps: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, json={"ok": True})

    transport = httpx.MockTransport(handler)

    class DummyClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        zhipu_http._ZHIPU_PROVIDER_COOLDOWNS.clear()

    monkeypatch.setattr("roughcut.providers.zhipu_http.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("roughcut.providers.zhipu_http.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("roughcut.providers.zhipu_http.time.monotonic", lambda: 100.0)

    zhipu_http._ZHIPU_PROVIDER_COOLDOWNS.clear()
    zhipu_http._ZHIPU_PROVIDER_COOLDOWNS["https://example.com"] = (101.5, "rate limited")

    result = await post_zhipu_json(
        url="https://example.com/chat/completions",
        headers={"Authorization": "Bearer demo"},
        json_payload={"model": "glm-5.2"},
        timeout_sec=5,
        max_attempts=1,
    )

    assert result == {"ok": True}
    assert sleeps == [1.5]


@pytest.mark.asyncio
async def test_post_zhipu_json_records_provider_cooldown_after_terminal_429(monkeypatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"retry-after-ms": "25"},
            request=request,
            json={"error": {"message": "rate limit"}},
        )

    transport = httpx.MockTransport(handler)

    class DummyClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("roughcut.providers.zhipu_http.httpx.AsyncClient", DummyClient)
    monkeypatch.setattr("roughcut.providers.zhipu_http.asyncio.sleep", fast_sleep)
    monkeypatch.setattr("roughcut.providers.zhipu_http.time.monotonic", lambda: 100.0)

    zhipu_http._ZHIPU_PROVIDER_COOLDOWNS.clear()

    with pytest.raises(httpx.HTTPStatusError):
        await post_zhipu_json(
            url="https://example.com/chat/completions",
            headers={"Authorization": "Bearer demo"},
            json_payload={"model": "glm-5.2"},
            timeout_sec=5,
            max_attempts=1,
        )

    cooldown = zhipu_http._ZHIPU_PROVIDER_COOLDOWNS.get("https://example.com")
    assert cooldown is not None
    assert cooldown[0] > 100.0


def test_zhipu_response_diagnostics_extracts_error_fields() -> None:
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(
        429,
        request=request,
        headers={"retry-after-ms": "25", "x-log-id": "trace-123"},
        json={"error": {"code": "1113", "message": "余额不足或无可用资源包,请充值。"}},
    )

    diagnostics = zhipu_response_diagnostics(response)

    assert diagnostics == {
        "status_code": 429,
        "error_code": "1113",
        "error_message": "余额不足或无可用资源包,请充值。",
        "retry_after_seconds": 0.025,
        "x_log_id": "trace-123",
        "body_excerpt": '{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}',
    }
