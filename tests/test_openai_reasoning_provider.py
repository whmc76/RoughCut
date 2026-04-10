from __future__ import annotations

from types import SimpleNamespace

import pytest

from roughcut.providers.reasoning.base import Message
from roughcut.providers.reasoning.openai_reasoning import OpenAIReasoningProvider


class _DummyResponsesAPI:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        return SimpleNamespace(
            model="gpt-5.4",
            output_text='{"answer":"ok"}',
            usage=SimpleNamespace(input_tokens=21, output_tokens=9),
            output=[],
        )


class _DummyOpenAIClient:
    def __init__(self, calls: list[dict], *args, **kwargs) -> None:
        del args, kwargs
        self.responses = _DummyResponsesAPI(calls)


@pytest.mark.asyncio
async def test_openai_reasoning_provider_uses_responses_api_for_gpt5(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []
    usage_events: list[dict] = []

    monkeypatch.setattr(
        "roughcut.providers.reasoning.openai_reasoning.get_settings",
        lambda: SimpleNamespace(
            openai_auth_mode="codex_compat",
            openai_api_key="",
            openai_api_key_helper="python -c \"print('token')\"",
            openai_base_url="https://api.openai.com/v1",
            active_reasoning_model="gpt-5.4",
        ),
    )
    monkeypatch.setattr(
        "roughcut.providers.reasoning.openai_reasoning.openai.AsyncOpenAI",
        lambda *args, **kwargs: _DummyOpenAIClient(calls, *args, **kwargs),
    )

    async def _fake_record_usage_event(**kwargs):
        usage_events.append(kwargs)

    monkeypatch.setattr("roughcut.providers.reasoning.openai_reasoning.record_usage_event", _fake_record_usage_event)

    provider = OpenAIReasoningProvider()
    response = await provider.complete(
        [
            Message(role="system", content="你是 coding planner"),
            Message(role="user", content="给我一个实现计划"),
        ],
        json_mode=True,
        max_tokens=512,
    )

    assert response.content == '{"answer":"ok"}'
    assert response.usage == {"prompt_tokens": 21, "completion_tokens": 9}
    assert response.model == "gpt-5.4"
    assert len(calls) == 1
    assert calls[0]["model"] == "gpt-5.4"
    assert calls[0]["max_output_tokens"] == 512
    assert calls[0]["reasoning"] == {"effort": "medium"}
    assert calls[0]["text"] == {"format": {"type": "json_object"}}
    assert calls[0]["input"][0]["role"] == "system"
    assert calls[0]["input"][0]["content"] == [{"type": "input_text", "text": "你是 coding planner"}]
    assert calls[0]["input"][1]["role"] == "user"
    assert usage_events[0]["kind"] == "reasoning"
