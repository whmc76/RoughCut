from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_ZHIPU_CODING_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_ZHIPU_MCP_HTTP_BASE_URL = "https://open.bigmodel.cn/api/mcp"
DEFAULT_ZHIPU_VISION_MODEL = "glm-4.6v-flash"


def normalize_zhipu_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    return value or DEFAULT_ZHIPU_BASE_URL


def normalize_zhipu_coding_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    return value or DEFAULT_ZHIPU_CODING_BASE_URL


def normalize_zhipu_mcp_http_base_url(base_url: str) -> str:
    value = str(base_url or "").strip().rstrip("/")
    return value or DEFAULT_ZHIPU_MCP_HTTP_BASE_URL


@dataclass(frozen=True, slots=True)
class ZhipuMCPServerConfig:
    name: str
    transport: str
    description: str
    url: str = ""
    headers: dict[str, str] | None = None
    command: str = ""
    args: tuple[str, ...] = ()
    env: dict[str, str] | None = None
    tools: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "transport": self.transport,
            "description": self.description,
            "url": self.url,
            "headers": dict(self.headers or {}),
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env or {}),
            "tools": list(self.tools),
        }
        return payload


def build_zhipu_mcp_server_catalog(*, api_key: str = "", mcp_http_base_url: str = "") -> dict[str, ZhipuMCPServerConfig]:
    normalized_http_base = normalize_zhipu_mcp_http_base_url(mcp_http_base_url)
    auth_header = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return {
        "web_search_prime": ZhipuMCPServerConfig(
            name="web-search-prime",
            transport="http",
            description="智谱联网搜索 MCP",
            url=f"{normalized_http_base}/web_search_prime/mcp",
            headers=auth_header,
            tools=("webSearchPrime",),
        ),
        "web_reader": ZhipuMCPServerConfig(
            name="web-reader",
            transport="http",
            description="智谱网页读取 MCP",
            url=f"{normalized_http_base}/web_reader/mcp",
            headers=auth_header,
            tools=("webReader",),
        ),
        "zread": ZhipuMCPServerConfig(
            name="zread",
            transport="http",
            description="智谱开源仓库 MCP",
            url=f"{normalized_http_base}/zread/mcp",
            headers=auth_header,
            tools=("search_doc", "get_repo_structure", "read_file"),
        ),
        "vision": ZhipuMCPServerConfig(
            name="zai-mcp-server",
            transport="stdio",
            description="智谱视觉理解 MCP",
            command="npx",
            args=("-y", "@z_ai/mcp-server@latest"),
            env={"Z_AI_API_KEY": api_key, "Z_AI_MODE": "ZHIPU"} if api_key else {"Z_AI_MODE": "ZHIPU"},
            tools=(
                "ui_to_artifact",
                "extract_text_from_screenshot",
                "diagnose_error_screenshot",
                "understand_technical_diagram",
                "analyze_data_visualization",
                "ui_diff_check",
                "analyze_image",
                "analyze_video",
            ),
        ),
    }
