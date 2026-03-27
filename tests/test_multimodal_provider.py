from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import roughcut.providers.multimodal as multimodal_mod


@pytest.fixture(autouse=True)
def _reset_multimodal_state():
    multimodal_mod._VISION_MODEL_CACHE = None
    multimodal_mod._MULTIMODAL_RESULT_CACHE.clear()
    multimodal_mod._MULTIMODAL_PROVIDER_COOLDOWNS.clear()
    multimodal_mod._MULTIMODAL_PROVIDER_SEMAPHORES.clear()
    yield
    multimodal_mod._VISION_MODEL_CACHE = None
    multimodal_mod._MULTIMODAL_RESULT_CACHE.clear()
    multimodal_mod._MULTIMODAL_PROVIDER_COOLDOWNS.clear()
    multimodal_mod._MULTIMODAL_PROVIDER_SEMAPHORES.clear()


def _make_settings(**overrides):
    base = {
        "active_reasoning_provider": "openai",
        "active_vision_model": "gpt-4.1-mini",
        "vision_model": "",
        "multimodal_fallback_provider": "",
        "multimodal_fallback_model": "",
        "llm_mode": "cloud",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_auth_mode": "direct",
        "openai_api_key": "openai-test-key",
        "openai_api_key_helper": "",
        "minimax_base_url": "https://api.minimaxi.com/v1",
        "minimax_api_key": "minimax-test-key",
        "ollama_base_url": "http://127.0.0.1:11434",
        "anthropic_base_url": "https://api.anthropic.com",
        "anthropic_auth_mode": "direct",
        "anthropic_api_key": "anthropic-test-key",
        "anthropic_api_key_helper": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class _DummyAsyncClient:
    def __init__(self, responses: list[httpx.Response], calls: list[dict], *args, **kwargs) -> None:
        del args, kwargs
        self._responses = responses
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb

    async def post(self, url: str, *, headers=None, json=None):
        self._calls.append({"url": url, "headers": headers or {}, "json": json})
        if not self._responses:
            raise AssertionError(f"Unexpected extra multimodal request to {url}")
        return self._responses.pop(0)

    async def get(self, url: str):
        self._calls.append({"url": url, "method": "GET"})
        if not self._responses:
            raise AssertionError(f"Unexpected extra multimodal request to {url}")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_complete_with_images_reuses_cached_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"same-frame")

    calls: list[dict] = []
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": "cached multimodal answer"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 34},
            },
        )
    ]

    async def _noop_record_usage_event(**kwargs):
        del kwargs

    monkeypatch.setattr(multimodal_mod, "get_settings", lambda: _make_settings())
    monkeypatch.setattr(multimodal_mod, "resolve_credential", lambda **kwargs: "openai-test-key")
    monkeypatch.setattr(multimodal_mod, "record_usage_event", _noop_record_usage_event)
    monkeypatch.setattr(
        multimodal_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _DummyAsyncClient(responses, calls, *args, **kwargs),
    )

    first = await multimodal_mod.complete_with_images("describe frame", [image_path], json_mode=False)
    second = await multimodal_mod.complete_with_images("describe frame", [image_path], json_mode=False)

    assert first == "cached multimodal answer"
    assert second == "cached multimodal answer"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://api.openai.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_complete_with_images_cools_down_minimax_and_falls_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"frame-a")

    calls: list[dict] = []
    responses = [
        httpx.Response(
            429,
            headers={"retry-after": "2"},
            request=httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions"),
            json={"error": {"message": "Too many requests. Retry after 2 seconds."}},
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": "fallback answer"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": "second fallback answer"}}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 21},
            },
        ),
    ]

    async def _noop_record_usage_event(**kwargs):
        del kwargs

    monkeypatch.setattr(
        multimodal_mod,
        "get_settings",
        lambda: _make_settings(
            active_reasoning_provider="minimax",
            active_vision_model="MiniMax-VL-01",
            multimodal_fallback_provider="openai",
            multimodal_fallback_model="gpt-4.1-mini",
        ),
    )
    monkeypatch.setattr(multimodal_mod, "resolve_credential", lambda **kwargs: "openai-test-key")
    monkeypatch.setattr(multimodal_mod, "record_usage_event", _noop_record_usage_event)
    monkeypatch.setattr(
        multimodal_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _DummyAsyncClient(responses, calls, *args, **kwargs),
    )

    first = await multimodal_mod.complete_with_images("rank cover", [image_path], json_mode=False)
    second = await multimodal_mod.complete_with_images("draft title", [image_path], json_mode=False)

    assert first == "fallback answer"
    assert second == "second fallback answer"
    assert [call["url"] for call in calls] == [
        "https://api.minimaxi.com/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions",
        "https://api.openai.com/v1/chat/completions",
    ]
    cooldown = multimodal_mod._provider_cooldown_status("minimax")
    assert cooldown is not None
    assert cooldown[0] >= 40


@pytest.mark.asyncio
async def test_complete_with_images_cache_key_tracks_provider_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"frame-b")

    async def _noop_record_usage_event(**kwargs):
        del kwargs

    calls: list[dict] = []
    responses = [
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
            json={
                "model": "gpt-4.1-mini",
                "choices": [{"message": {"content": "openai answer"}}],
                "usage": {"prompt_tokens": 8, "completion_tokens": 16},
            },
        ),
        httpx.Response(
            200,
            request=httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions"),
            json={
                "model": "MiniMax-VL-01",
                "choices": [{"message": {"content": "minimax answer"}}],
                "usage": {"prompt_tokens": 9, "completion_tokens": 18},
            },
        ),
    ]

    state = {"provider": "openai"}

    def _settings():
        if state["provider"] == "openai":
            return _make_settings(active_reasoning_provider="openai", active_vision_model="gpt-4.1-mini")
        return _make_settings(active_reasoning_provider="minimax", active_vision_model="MiniMax-VL-01")

    monkeypatch.setattr(multimodal_mod, "get_settings", _settings)
    monkeypatch.setattr(multimodal_mod, "resolve_credential", lambda **kwargs: "openai-test-key")
    monkeypatch.setattr(multimodal_mod, "record_usage_event", _noop_record_usage_event)
    monkeypatch.setattr(
        multimodal_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _DummyAsyncClient(responses, calls, *args, **kwargs),
    )

    openai_answer = await multimodal_mod.complete_with_images("same prompt", [image_path], json_mode=False)
    state["provider"] = "minimax"
    minimax_answer = await multimodal_mod.complete_with_images("same prompt", [image_path], json_mode=False)

    assert openai_answer == "openai answer"
    assert minimax_answer == "minimax answer"
    assert [call["url"] for call in calls] == [
        "https://api.openai.com/v1/chat/completions",
        "https://api.minimaxi.com/v1/chat/completions",
    ]


@pytest.mark.asyncio
async def test_complete_with_images_preserves_pressure_context_and_cools_unreachable_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"frame-c")

    calls: list[dict] = []
    responses = [
        httpx.Response(
            429,
            headers={"retry-after": "2"},
            request=httpx.Request("POST", "https://api.minimaxi.com/v1/chat/completions"),
            json={"error": {"message": "Token Plan 当前请求量较高，请稍后重试。 (2062)"}},
        )
    ]

    async def _noop_record_usage_event(**kwargs):
        del kwargs

    class _ClientWithBrokenOllama(_DummyAsyncClient):
        async def post(self, url: str, *, headers=None, json=None):
            self._calls.append({"url": url, "headers": headers or {}, "json": json})
            if "11434" in url:
                raise httpx.ConnectError("Connection refused", request=httpx.Request("POST", url))
            if not self._responses:
                raise AssertionError(f"Unexpected extra multimodal request to {url}")
            return self._responses.pop(0)

    monkeypatch.setattr(
        multimodal_mod,
        "get_settings",
        lambda: _make_settings(
            active_reasoning_provider="minimax",
            active_vision_model="MiniMax-VL-01",
            multimodal_fallback_provider="ollama",
            multimodal_fallback_model="llava:latest",
            ollama_base_url="http://localhost:11434",
        ),
    )
    monkeypatch.setattr(multimodal_mod, "record_usage_event", _noop_record_usage_event)
    monkeypatch.setattr(
        multimodal_mod.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _ClientWithBrokenOllama(responses, calls, *args, **kwargs),
    )

    with pytest.raises(ValueError) as exc_info:
        await multimodal_mod.complete_with_images("first prompt", [image_path], json_mode=False)

    assert "cooling down" in str(exc_info.value).lower()
    assert "minimax" in str(exc_info.value).lower()
    assert [call["url"] for call in calls] == [
        "https://api.minimaxi.com/v1/chat/completions",
        "http://localhost:11434/api/chat",
    ]
    minimax_cooldown = multimodal_mod._provider_cooldown_status("minimax")
    ollama_cooldown = multimodal_mod._provider_cooldown_status("ollama")
    assert minimax_cooldown is not None
    assert minimax_cooldown[0] >= 170
    assert ollama_cooldown is not None
    assert ollama_cooldown[0] >= 100

    calls_before_second = len(calls)
    with pytest.raises(ValueError):
        await multimodal_mod.complete_with_images("second prompt", [image_path], json_mode=False)

    assert len(calls) == calls_before_second
