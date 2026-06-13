import pytest

from roughcut.providers.reasoning.base import Message, ToolDefinition
from roughcut.providers.reasoning.zhipu_reasoning import ZhipuReasoningProvider


class _DummySettings:
    zhipu_auth_mode = "api_key"
    zhipu_api_key = "demo-key"
    zhipu_api_key_helper = ""
    zhipu_base_url = "https://open.bigmodel.cn/api/paas/v4"
    active_reasoning_model = "glm-5.2[1m]"
    active_reasoning_effort = "low"


@pytest.mark.asyncio
async def test_zhipu_complete_with_tools_builds_function_payload_and_parses_tool_calls(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_post_zhipu_json(*, url, headers, json_payload, timeout_sec, max_attempts):
        captured["json_payload"] = json_payload
        return {
            "model": "glm-5.2[1m]",
            "choices": [
                {
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query":"GLM-5.2"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }

    async def fake_record_usage_event(**kwargs):
        return None

    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.get_settings", lambda: _DummySettings())
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.post_zhipu_json", fake_post_zhipu_json)
    monkeypatch.setattr("roughcut.providers.reasoning.zhipu_reasoning.record_usage_event", fake_record_usage_event)

    provider = ZhipuReasoningProvider()
    response = await provider.complete_with_tools(
        [Message(role="user", content="查一下 GLM-5.2")],
        tools=[
            ToolDefinition(
                name="web_search",
                description="搜索网页",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ],
        tool_choice="auto",
        max_tokens=512,
    )

    payload = dict(captured["json_payload"] or {})
    assert payload["tools"][0]["function"]["name"] == "web_search"
    assert payload["tool_choice"] == "auto"
    assert "max_tokens" not in payload
    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "web_search"
    assert response.tool_calls[0].arguments == {"query": "GLM-5.2"}
