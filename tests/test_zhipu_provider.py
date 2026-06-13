from roughcut.config import DEFAULT_ZHIPU_REASONING_MODEL, normalize_reasoning_model_for_provider
from roughcut.api.config import _redact_secret_map
from roughcut.providers.zhipu_http import build_zhipu_request_context
from roughcut.providers.zhipu_compat import DEFAULT_ZHIPU_MCP_HTTP_BASE_URL, build_zhipu_mcp_server_catalog
from roughcut.providers.reasoning.zhipu_reasoning import _should_enable_zhipu_thinking


def test_zhipu_provider_defaults_to_glm_5_2() -> None:
    assert normalize_reasoning_model_for_provider("zhipu", "") == DEFAULT_ZHIPU_REASONING_MODEL


def test_zhipu_mcp_catalog_exposes_required_servers() -> None:
    catalog = build_zhipu_mcp_server_catalog(api_key="demo-key")

    assert catalog["web_search_prime"].url == f"{DEFAULT_ZHIPU_MCP_HTTP_BASE_URL}/web_search_prime/mcp"
    assert catalog["web_reader"].url == f"{DEFAULT_ZHIPU_MCP_HTTP_BASE_URL}/web_reader/mcp"
    assert catalog["zread"].url == f"{DEFAULT_ZHIPU_MCP_HTTP_BASE_URL}/zread/mcp"
    assert catalog["vision"].command == "npx"
    assert catalog["vision"].args == ("-y", "@z_ai/mcp-server@latest")
    assert catalog["vision"].env == {"Z_AI_API_KEY": "demo-key", "Z_AI_MODE": "ZHIPU"}
    assert "analyze_image" in catalog["vision"].tools
    assert "analyze_video" in catalog["vision"].tools


def test_zhipu_low_effort_does_not_force_thinking() -> None:
    assert _should_enable_zhipu_thinking(effort="low", max_tokens=1024, model="glm-5.1") is False
    assert _should_enable_zhipu_thinking(effort="medium", max_tokens=64, model="glm-5.1") is False
    assert _should_enable_zhipu_thinking(effort="high", max_tokens=512, model="glm-5.1") is True
    assert _should_enable_zhipu_thinking(effort="max", max_tokens=512, model="glm-5.1") is True
    assert _should_enable_zhipu_thinking(effort="high", max_tokens=4096, json_mode=True, model="glm-5.1") is False


def test_zhipu_glm_5_2_keeps_low_as_non_thinking_and_max_as_complex_thinking() -> None:
    assert _should_enable_zhipu_thinking(effort="minimal", max_tokens=1024, model="glm-5.2[1m]") is False
    assert _should_enable_zhipu_thinking(effort="low", max_tokens=1024, model="glm-5.2[1m]") is False
    assert _should_enable_zhipu_thinking(effort="medium", max_tokens=1024, model="glm-5.2[1m]") is True
    assert _should_enable_zhipu_thinking(effort="max", max_tokens=1024, model="glm-5.2[1m]") is True


def test_zhipu_request_context_provides_traceable_ids() -> None:
    payload = build_zhipu_request_context()

    assert len(str(payload["request_id"])) >= 6
    assert str(payload["user_id"]).startswith("roughcut-")


def test_redact_secret_map_masks_sensitive_keys() -> None:
    assert _redact_secret_map(
        {
            "Authorization": "Bearer secret",
            "Z_AI_API_KEY": "secret",
            "Z_AI_MODE": "ZHIPU",
        }
    ) == {
        "Authorization": "[secure]",
        "Z_AI_API_KEY": "[secure]",
        "Z_AI_MODE": "ZHIPU",
    }
