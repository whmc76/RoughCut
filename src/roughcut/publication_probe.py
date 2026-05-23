from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BROWSER_AGENT_INVENTORY_CONTRACT = "browser_agent_publication_inventory_v1"


async def probe_browser_agent_publication_inventory(
    *,
    base_url: str,
    auth_token: str = "",
    browser: str = "chrome",
    creator_profile_id: str = "",
    platforms: list[str],
    content_sample: dict[str, Any] | None = None,
    mode: str = "inventory_only_no_publish",
    request_timeout_sec: int = 120,
    http_client: Any | None = None,
) -> dict[str, Any]:
    normalized_base = str(base_url or "").strip().rstrip("/")
    if not normalized_base:
        return _unavailable_result("browser_agent_base_url_empty", "browser-agent base URL 未配置。", platforms=platforms)

    payload = {
        "contract": BROWSER_AGENT_INVENTORY_CONTRACT,
        "browser": browser,
        "creator_profile_id": creator_profile_id,
        "platforms": platforms,
        "content_sample": content_sample or {},
        "mode": mode,
    }
    try:
        response_payload = await _request_json(
            "POST",
            f"{normalized_base}/probes",
            auth_token=auth_token,
            json_payload=payload,
            request_timeout_sec=request_timeout_sec,
            http_client=http_client,
        )
    except Exception as exc:
        return _unavailable_result(
            "browser_agent_probe_unavailable",
            f"browser-agent 真实摸底服务不可用：{exc}",
            platforms=platforms,
        )

    result = response_payload.get("result") if isinstance(response_payload.get("result"), dict) else response_payload
    if not isinstance(result, dict):
        return _unavailable_result("browser_agent_probe_invalid", "browser-agent 返回的摸底结果不是对象。", platforms=platforms)
    result.setdefault("contract", BROWSER_AGENT_INVENTORY_CONTRACT)
    result.setdefault("generated_at", _now_iso())
    return result


async def _request_json(
    method: str,
    url: str,
    *,
    auth_token: str = "",
    json_payload: dict[str, Any] | None = None,
    request_timeout_sec: int = 120,
    http_client: Any | None = None,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    async def _send(client: httpx.AsyncClient) -> httpx.Response:
        return await client.request(method, url, headers=headers, json=json_payload)

    if http_client is not None:
        response = await http_client.request(method, url, headers=headers, json=json_payload)
    else:
        async with httpx.AsyncClient(timeout=max(5, int(request_timeout_sec or 120))) as client:
            response = await _send(client)
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"payload": payload}


def _unavailable_result(code: str, message: str, *, platforms: list[str]) -> dict[str, Any]:
    return {
        "contract": BROWSER_AGENT_INVENTORY_CONTRACT,
        "status": "unavailable",
        "code": code,
        "message": message,
        "generated_at": _now_iso(),
        "platforms": {
            platform: {
                "status": "unavailable",
                "platform": platform,
                "message": message,
                "route": {},
                "field_groups": [],
                "option_groups": [],
                "operation_steps": [],
                "warnings": [message],
            }
            for platform in platforms
        },
    }


def _now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
