from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest

import roughcut.config as config_mod
import roughcut.providers.reasoning.minimax_reasoning as minimax_mod
from roughcut.config import get_settings
from roughcut.providers.reasoning.base import Message
from roughcut.providers.reasoning.minimax_reasoning import MiniMaxReasoningProvider


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self._content = content

    async def create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self._content),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22),
            model=kwargs["model"],
        )


class _FakeAsyncOpenAI:
    def __init__(self, *, api_key: str, base_url: str, content: str) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.chat = SimpleNamespace(completions=_FakeCompletions(content))
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_minimax_complete_strips_think_tags(monkeypatch):
    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "reasoning_provider", "minimax")
    object.__setattr__(settings, "reasoning_model", "MiniMax-M2.7")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")

    captured: dict[str, object] = {}

    def _fake_client(*, api_key: str, base_url: str):
        client = _FakeAsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            content="<think>internal reasoning</think>\n最终答案",
        )
        captured["client"] = client
        return client

    monkeypatch.setattr(minimax_mod.openai, "AsyncOpenAI", _fake_client)

    provider = MiniMaxReasoningProvider()
    response = await provider.complete([Message(role="user", content="test")])

    assert response.content == "最终答案"
    assert response.model == "MiniMax-M2.7"
    assert response.usage == {"prompt_tokens": 11, "completion_tokens": 22}
    assert cast(_FakeAsyncOpenAI, captured["client"]).closed is True


@pytest.mark.asyncio
async def test_minimax_complete_keeps_json_payload_after_think(monkeypatch):
    config_mod._settings = None
    settings = get_settings()
    object.__setattr__(settings, "reasoning_provider", "minimax")
    object.__setattr__(settings, "reasoning_model", "MiniMax-M2.7")
    object.__setattr__(settings, "minimax_api_key", "test-key")
    object.__setattr__(settings, "minimax_base_url", "https://api.minimaxi.com/v1")

    def _fake_client(*, api_key: str, base_url: str):
        return _FakeAsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            content='<think>hidden</think>\n{"preset_name":"unboxing_upgrade"}',
        )

    monkeypatch.setattr(minimax_mod.openai, "AsyncOpenAI", _fake_client)

    provider = MiniMaxReasoningProvider()
    response = await provider.complete([Message(role="user", content="test")], json_mode=True)

    assert response.content == '{"preset_name":"unboxing_upgrade"}'
    assert response.as_json()["preset_name"] == "unboxing_upgrade"
