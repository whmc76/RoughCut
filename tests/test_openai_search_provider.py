from __future__ import annotations

from types import SimpleNamespace

import pytest

from roughcut.providers.search.openai import OpenAISearchProvider


class _DummyResponsesAPI:
    def __init__(self, calls: list[dict]) -> None:
        self._calls = calls

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        return SimpleNamespace(
            output_text='{"results":[{"title":"Codex docs","url":"https://openai.com/codex","snippet":"agentic coding"}]}',
            output=[],
        )


class _DummyOpenAIClient:
    def __init__(self, calls: list[dict], *args, **kwargs) -> None:
        del args, kwargs
        self.responses = _DummyResponsesAPI(calls)


@pytest.mark.asyncio
async def test_openai_search_provider_uses_web_search_with_json_output(monkeypatch: pytest.MonkeyPatch):
    calls: list[dict] = []

    monkeypatch.setattr(
        "roughcut.providers.search.openai.get_settings",
        lambda: SimpleNamespace(
            openai_auth_mode="codex_compat",
            openai_api_key="",
            openai_api_key_helper="python -c \"print('token')\"",
            openai_base_url="https://api.openai.com/v1",
            active_reasoning_model="gpt-5.4",
        ),
    )
    monkeypatch.setattr(
        "roughcut.providers.search.openai.openai.AsyncOpenAI",
        lambda *args, **kwargs: _DummyOpenAIClient(calls, *args, **kwargs),
    )

    provider = OpenAISearchProvider()
    results = await provider.search("codex coding plan", max_results=3)

    assert len(results) == 1
    assert results[0].title == "Codex docs"
    assert results[0].url == "https://openai.com/codex"
    assert results[0].snippet == "agentic coding"
    assert calls[0]["model"] == "gpt-5.4"
    assert calls[0]["tools"] == [{"type": "web_search"}]
    assert calls[0]["text"] == {"format": {"type": "json_object"}}
    assert calls[0]["reasoning"] == {"effort": "medium"}
