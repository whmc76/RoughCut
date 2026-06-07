import httpx
import pytest

from roughcut.providers.zhipu_http import post_zhipu_json


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
