import pytest

from roughcut.providers.reasoning.base import Message
from roughcut.providers.reasoning.zhipu_reasoning import ZhipuReasoningProvider


class _DummySettings:
    zhipu_auth_mode = "api_key"
    zhipu_api_key = "demo-key"
    zhipu_api_key_helper = ""
    zhipu_base_url = "https://open.bigmodel.cn/api/paas/v4"
    active_reasoning_model = "glm-5.2[1m]"
    active_reasoning_effort = "high"


@pytest.mark.asyncio
async def test_zhipu_reasoning_json_mode_sets_response_format_and_disables_thinking(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_post_zhipu_json(*, url, headers, json_payload, timeout_sec, max_attempts):
        captured["url"] = url
        captured["headers"] = headers
        captured["json_payload"] = json_payload
        return {
            "model": "glm-5.2[1m]",
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def fake_record_usage_event(**kwargs):
        return None

    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.get_settings", lambda: _DummySettings())
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.post_zhipu_json", fake_post_zhipu_json)
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.record_usage_event", fake_record_usage_event)

    provider = ZhipuReasoningProvider()
    response = await provider.complete([Message(role="user", content="return json")], json_mode=True, max_tokens=512)

    payload = dict(captured["json_payload"] or {})
    assert response.content == '{"ok":true}'
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["thinking"] == {"type": "disabled"}
    assert str(payload["user_id"]).startswith("roughcut-")


@pytest.mark.asyncio
async def test_zhipu_reasoning_default_max_tokens_matches_glm_capacity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_post_zhipu_json(*, url, headers, json_payload, timeout_sec, max_attempts):
        captured["json_payload"] = json_payload
        captured["timeout_sec"] = timeout_sec
        return {
            "model": "glm-5.2[1m]",
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        }

    async def fake_record_usage_event(**kwargs):
        return None

    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.get_settings", lambda: _DummySettings())
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.post_zhipu_json", fake_post_zhipu_json)
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.record_usage_event", fake_record_usage_event)

    provider = ZhipuReasoningProvider()
    response = await provider.complete([Message(role="user", content="long-form answer")])

    payload = dict(captured["json_payload"] or {})
    assert response.content == "ok"
    assert payload["model"] == "glm-5.2[1m]"
    assert payload["max_tokens"] == 65536
    assert captured["timeout_sec"] == 600
