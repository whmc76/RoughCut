from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from roughcut.config import get_settings
from roughcut.providers.auth import resolve_credential
from roughcut.providers.zhipu_compat import build_zhipu_mcp_server_catalog, normalize_zhipu_base_url
from roughcut.providers.zhipu_http import build_zhipu_headers, build_zhipu_request_context, post_zhipu_json


@dataclass(frozen=True, slots=True)
class ZhipuReaderResult:
    url: str
    title: str
    description: str
    content: str
    metadata: dict[str, Any]
    raw: dict[str, Any]


async def read_webpage(
    url: str,
    *,
    timeout_sec: int = 20,
    no_cache: bool = False,
    return_format: str = "markdown",
    retain_images: bool = True,
    with_images_summary: bool = False,
    with_links_summary: bool = False,
) -> ZhipuReaderResult:
    settings = get_settings()
    api_key = resolve_credential(
        mode=settings.zhipu_auth_mode,
        direct_value=settings.zhipu_api_key,
        helper_command=settings.zhipu_api_key_helper,
        provider_name="Zhipu",
    )
    payload = {
        "url": str(url or "").strip(),
        "timeout": max(1, int(timeout_sec)),
        "no_cache": bool(no_cache),
        "return_format": str(return_format or "markdown").strip() or "markdown",
        "retain_images": bool(retain_images),
        "with_images_summary": bool(with_images_summary),
        "with_links_summary": bool(with_links_summary),
        **build_zhipu_request_context(),
    }
    data = await post_zhipu_json(
        url=f"{normalize_zhipu_base_url(settings.zhipu_base_url)}/reader",
        headers=build_zhipu_headers(api_key),
        json_payload=payload,
        timeout_sec=max(10, int(timeout_sec) + 5),
        max_attempts=3,
    )

    result = data.get("reader_result") or {}
    return ZhipuReaderResult(
        url=str(result.get("url", "")).strip(),
        title=str(result.get("title", "")).strip(),
        description=str(result.get("description", "")).strip(),
        content=str(result.get("content", "")).strip(),
        metadata=dict(result.get("metadata") or {}),
        raw=data,
    )


def get_mcp_server_catalog(*, api_key: str = "") -> dict[str, dict[str, Any]]:
    settings = get_settings()
    resolved_api_key = str(api_key or "").strip()
    if not resolved_api_key:
        resolved_api_key = resolve_credential(
            mode=settings.zhipu_auth_mode,
            direct_value=settings.zhipu_api_key,
            helper_command=settings.zhipu_api_key_helper,
            provider_name="Zhipu",
        )
    catalog = build_zhipu_mcp_server_catalog(
        api_key=resolved_api_key,
        mcp_http_base_url=settings.zhipu_mcp_http_base_url,
    )
    return {name: item.as_dict() for name, item in catalog.items()}
