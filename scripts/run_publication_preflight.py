from __future__ import annotations

import argparse
import asyncio
import json
import sys
import os
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo
from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import httpx
from roughcut.config import get_settings
from roughcut.publication import check_publication_browser_agent_ready
from roughcut.publication_packaging import (
    publication_packaging_entry_blocking_reasons,
    publication_packaging_missing_platform_messages,
    load_publication_packaging_payload,
    publication_packaging_entry_publish_ready,
)
from roughcut.publication_platform_matrix import platform_manual_handoff_only, platform_manual_publish_entry_url

PROBE_CONTRACT = "browser_agent_publication_inventory_v1"


PLATFORM_DOMAINS: dict[str, list[str]] = {
    "douyin": ["creator.douyin.com", "creator-micro.douyin.com"],
    "xiaohongshu": ["creator.xiaohongshu.com"],
    "bilibili": ["member.bilibili.com", "member.bilibili.com/platform/upload"],
    "kuaishou": ["cp.kuaishou.com", "cp.kuaishou.com/article/publish/video"],
    "wechat-channels": ["channels.weixin.qq.com"],
    "toutiao": ["mp.toutiao.com/profile_v4/xigua/upload-video", "mp.toutiao.com/profile_v4/xigua/publish-video", "mp.toutiao.com"],
    "youtube": ["studio.youtube.com"],
    "x": ["x.com", "twitter.com"],
}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _normalize_publication_adapter(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_")


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _normalize_platform(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _coerce_visual_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    artifact_path = str(payload.get("artifact_path") or "").strip()
    capture_type = str(payload.get("capture_type") or "").strip()
    phase = str(payload.get("phase") or "").strip()
    mime_type = str(payload.get("mime_type") or "").strip()
    if not any([artifact_path, capture_type, phase, mime_type]):
        return {}
    evidence: dict[str, Any] = {}
    if artifact_path:
        evidence["artifact_path"] = artifact_path
    if capture_type:
        evidence["capture_type"] = capture_type
    if phase:
        evidence["phase"] = phase
    if mime_type:
        evidence["mime_type"] = mime_type
    return evidence


def _normalize_profile_ids(raw: Iterable[str]) -> list[str]:
    items = []
    for item in raw:
        cleaned = _normalize(item)
        if cleaned:
            items.append(cleaned)
    # stable order for deterministic output
    return sorted(set(items))


def _score_platform_tab(tab: dict[str, Any], platform: str) -> int:
    url = _normalize(tab.get("url"))
    if not url:
        return 0
    try:
        parsed = httpx.URL(url)
    except Exception:
        return 0
    hostname = _normalize(parsed.host)
    pathname = _normalize(parsed.path)
    score = 0
    for raw in PLATFORM_DOMAINS.get(platform, []):
        normalized = _normalize(raw).lower()
        if not normalized:
            continue
        domain = normalized.split("/", 1)[0]
        suffix = normalized.split("/", 1)[1] if "/" in normalized else ""
        if hostname == domain or hostname.endswith(f".{domain}"):
            score = max(score, 10)
            if suffix and pathname.startswith(f"/{suffix}"):
                score = max(score, 20)
            elif not suffix and pathname:
                score = max(score, 12)
    title = _normalize(tab.get("title")).lower()
    if "发布" in title or "创作" in title:
        score += 2
    if tab.get("type") == "page":
        score += 1
    return score


def _find_best_tab(tabs: list[dict[str, Any]], platform: str) -> dict[str, Any] | None:
    candidates = [
        (tab, _score_platform_tab(tab, platform))
        for tab in tabs
        if _normalize(tab.get("type")) in {"page", "background_page"}
    ]
    candidates = [(tab, score) for tab, score in candidates if score > 0]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[1], reverse=True)
    return candidates[0][0]


def _evaluate_packaging_preflight(
    *,
    platforms: list[str],
    material_json: str = "",
    platform_packaging: str = "",
    enforce_gate: bool = True,
) -> dict[str, Any]:
    packaging, sources = load_publication_packaging_payload(
        material_json=material_json,
        platform_packaging=platform_packaging,
        platforms=platforms,
    )
    normalized_platforms = [_normalize_platform(item) for item in platforms if _normalize_platform(item)]
    platform_checks: dict[str, dict[str, Any]] = {}
    manual_handoff_targets: list[dict[str, str]] = []
    failures: list[str] = []

    if packaging is None:
        return {
            "checked": bool(_normalize(material_json) or _normalize(platform_packaging)),
            "status": "missing" if (_normalize(material_json) or _normalize(platform_packaging)) else "skipped",
            "gate_enforced": bool(enforce_gate),
            "reported_failures": [],
            "material_json_path": sources.get("material_json_path", ""),
            "platform_packaging_path": sources.get("platform_packaging_path", ""),
            "source": sources.get("source", ""),
            "platform_checks": platform_checks,
            "manual_handoff_targets": manual_handoff_targets,
            "failures": (
                ["未找到可机读的 platform-packaging/material 合同，无法执行发布前物料预检。"]
                if (_normalize(material_json) or _normalize(platform_packaging))
                else []
            ),
        }

    packaging_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    missing_platform_messages = publication_packaging_missing_platform_messages(
        packaging,
        platforms=normalized_platforms,
    )
    for platform in normalized_platforms:
        entry = packaging_platforms.get(platform) if isinstance(packaging_platforms.get(platform), dict) else {}
        manual_handoff = bool(entry.get("manual_handoff_only")) or platform_manual_handoff_only(platform)
        login_url = str(entry.get("manual_publish_entry_url") or "").strip() or platform_manual_publish_entry_url(platform)
        if not entry:
            missing_platform_message = missing_platform_messages.get(platform) or {}
            platform_checks[platform] = {
                "status": "missing",
                "message": missing_platform_message.get("message") or "未在 packaging 合同中找到该平台的发布物料。",
            }
            failures.append(missing_platform_message.get("failure") or f"发布文案缺失：{platform}")
            continue
        preflight = entry.get("live_publish_preflight") if isinstance(entry.get("live_publish_preflight"), dict) else {}
        preflight_status = str(preflight.get("status") or "").strip().lower()
        missing_required_surfaces = [
            str(item).strip()
            for item in (preflight.get("missing_required_surfaces") or [])
            if str(item).strip()
        ]
        blocking_reasons = publication_packaging_entry_blocking_reasons(entry)
        if manual_handoff:
            platform_checks[platform] = {
                "status": "manual_handoff",
                "message": "该平台当前走人工接管，不进入自动一键发布。",
                "login_url": login_url,
            }
            manual_handoff_targets.append(
                {
                    "platform": platform,
                    "login_url": login_url,
                }
            )
            continue
        if preflight_status in {"blocked", "missing_required_surfaces"} or missing_required_surfaces:
            platform_checks[platform] = {
                "status": "blocked",
                "message": "发布前置门禁未通过。",
                "missing_required_surfaces": missing_required_surfaces,
                "blocking_reasons": blocking_reasons,
            }
            detail = (
                f"缺少关键参数面 {', '.join(missing_required_surfaces)}"
                if missing_required_surfaces
                else blocking_reasons[0]
                if blocking_reasons
                else "预发布门禁阻断"
            )
            failures.append(f"{platform}: {detail}")
            continue
        if not publication_packaging_entry_publish_ready(entry):
            platform_checks[platform] = {
                "status": "blocked",
                "message": "platform-packaging 标记为未就绪。",
                "blocking_reasons": blocking_reasons,
            }
            failures.append(f"发布文案未就绪：{platform}")
            continue
        platform_checks[platform] = {
            "status": "ready",
            "message": "发布物料合同就绪。",
        }

    reported_failures = list(failures)
    effective_failures = list(failures) if enforce_gate else []
    status = "failed" if effective_failures else "passed"
    if not failures and manual_handoff_targets and len(manual_handoff_targets) == len(platform_checks):
        status = "manual_handoff"
    elif reported_failures and not enforce_gate:
        status = "report_only"
    return {
        "checked": True,
        "status": status,
        "gate_enforced": bool(enforce_gate),
        "reported_failures": reported_failures,
        "material_json_path": sources.get("material_json_path", ""),
        "platform_packaging_path": sources.get("platform_packaging_path", ""),
        "source": sources.get("source", ""),
        "platform_checks": platform_checks,
        "manual_handoff_targets": manual_handoff_targets,
        "failures": effective_failures,
    }


def _derive_live_publish_platforms(
    *,
    requested_platforms: list[str],
    packaging_preflight: dict[str, Any] | None,
) -> list[str]:
    normalized_requested = [
        _normalize_platform(item)
        for item in requested_platforms
        if _normalize_platform(item)
    ]
    payload = packaging_preflight if isinstance(packaging_preflight, dict) else {}
    platform_checks = payload.get("platform_checks") if isinstance(payload.get("platform_checks"), dict) else {}
    live_platforms: list[str] = []
    for platform in normalized_requested:
        entry = platform_checks.get(platform) if isinstance(platform_checks.get(platform), dict) else {}
        if _normalize(entry.get("status")).lower() == "manual_handoff":
            continue
        live_platforms.append(platform)
    return live_platforms


async def _fetch_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _fetch_browser_agent_probe_inventory(
    client: httpx.AsyncClient,
    browser_agent_base_url: str,
    auth_token: str,
    platforms: list[str],
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    token = _normalize(auth_token)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = await client.post(
        f"{browser_agent_base_url.rstrip('/')}/probes",
        headers=headers,
        json={
            "contract": PROBE_CONTRACT,
            "platforms": [_normalize_platform(item) for item in platforms if _normalize_platform(item)],
            "browser": "chrome",
            "summary_only": True,
        },
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") if isinstance(payload, dict) else {}
    return result if isinstance(result, dict) else {}


async def _fetch_cdp_tabs_payload(
    client: httpx.AsyncClient,
    cdp_url: str,
    *,
    attempts: int = 3,
    retry_delay_sec: float = 1.0,
) -> Any:
    last_error: Exception | None = None
    normalized_attempts = max(1, int(attempts or 1))
    for attempt_index in range(normalized_attempts):
        try:
            return await _fetch_json(client, f"{cdp_url}/json/list")
        except (httpx.TimeoutException, httpx.ConnectError) as error:
            last_error = error
            if attempt_index >= normalized_attempts - 1:
                break
            try:
                await _fetch_json(client, f"{cdp_url}/json/version")
            except Exception:
                pass
            await asyncio.sleep(max(0.0, float(retry_delay_sec)))
    if last_error is not None:
        try:
            return await asyncio.to_thread(_fetch_cdp_tabs_payload_via_urllib, cdp_url)
        except Exception:
            raise last_error
    return await _fetch_json(client, f"{cdp_url}/json/list")


def _fetch_cdp_tabs_payload_via_urllib(cdp_url: str) -> Any:
    with urllib.request.urlopen(f"{cdp_url}/json/list", timeout=10) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _should_fallback_to_browser_agent_probe_tabs(agent_ready: dict[str, Any]) -> bool:
    health = agent_ready.get("health") if isinstance(agent_ready.get("health"), dict) else {}
    capabilities = health.get("capabilities") if isinstance(health.get("capabilities"), dict) else {}
    transport_kind = _normalize(
        capabilities.get("browser_transport_kind")
        or (health.get("browser_transport") or {}).get("transport")
    ).lower()
    cdp_status = _normalize(health.get("cdp_status")).lower()
    return transport_kind == "chrome_extension_bridge" and cdp_status in {"ok", "ready"}


def _derive_tabs_from_probe_inventory(probe_inventory: dict[str, Any]) -> list[dict[str, Any]]:
    probe_platforms = probe_inventory.get("platforms") if isinstance(probe_inventory.get("platforms"), dict) else {}
    tabs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for platform, entry in probe_platforms.items():
        if not isinstance(entry, dict):
            continue
        route = entry.get("route") if isinstance(entry.get("route"), dict) else {}
        url = _normalize(route.get("url"))
        title = _normalize(route.get("title"))
        if not url:
            continue
        key = f"{platform}:{url}:{title}"
        if key in seen:
            continue
        seen.add(key)
        tabs.append(
            {
                "id": f"probe:{_normalize_platform(platform)}",
                "url": url,
                "title": title,
                "type": "page",
            }
        )
    return tabs


def _derive_tabs_from_creator_sessions(agent_ready: dict[str, Any], *, platforms: list[str]) -> list[dict[str, Any]]:
    health = agent_ready.get("health") if isinstance(agent_ready.get("health"), dict) else {}
    creator_sessions = health.get("creator_sessions") if isinstance(health.get("creator_sessions"), dict) else {}
    tabs: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_platform in platforms:
        platform = _normalize_platform(raw_platform)
        entry = creator_sessions.get(platform) if isinstance(creator_sessions.get(platform), dict) else {}
        route = entry.get("route") if isinstance(entry.get("route"), dict) else {}
        url = _normalize(route.get("url"))
        title = _normalize(route.get("title"))
        if not url:
            continue
        key = f"{platform}:{url}:{title}"
        if key in seen:
            continue
        seen.add(key)
        tabs.append(
            {
                "id": f"session:{platform}",
                "url": url,
                "title": title,
                "type": "page",
            }
        )
    return tabs


def _collect_probe_inventory_gate_failures(
    *,
    platforms: list[str],
    probe_inventory: dict[str, Any],
    packaging_preflight: dict[str, Any],
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    failures: list[str] = []
    metadata: dict[str, dict[str, Any]] = {}
    platform_checks = packaging_preflight.get("platform_checks") if isinstance(packaging_preflight.get("platform_checks"), dict) else {}
    probe_platforms = probe_inventory.get("platforms") if isinstance(probe_inventory.get("platforms"), dict) else {}

    for raw_platform in platforms:
        platform = _normalize_platform(raw_platform)
        if not platform:
            continue
        packaging_entry = platform_checks.get(platform) if isinstance(platform_checks.get(platform), dict) else {}
        if _normalize(packaging_entry.get("status")).lower() in {"manual_handoff", "missing"}:
            continue
        probe_entry = probe_platforms.get(platform) if isinstance(probe_platforms.get(platform), dict) else {}
        if not probe_entry:
            continue
        route_readiness = probe_entry.get("route_readiness") if isinstance(probe_entry.get("route_readiness"), dict) else {}
        probe_status = _normalize(probe_entry.get("status")).lower()
        route_reason = _normalize(route_readiness.get("reason")).lower()
        if probe_status == "route_not_ready" or route_readiness.get("blocked") is True:
            if route_reason == "publish_route_loading":
                failures.append(f"{platform}: 实际发布页仍在加载中，编辑器尚未就绪。")
            else:
                failures.append(f"{platform}: 实际发布页尚未进入可编辑状态。")
            metadata[platform] = {
                "missing_required_surfaces": [],
                "probe_status": probe_status or "route_not_ready",
                "route_url": _normalize((probe_entry.get("route") or {}).get("url")),
                "route_reason": route_reason or "publish_route_not_ready",
            }
            continue
        coverage = probe_entry.get("coverage") if isinstance(probe_entry.get("coverage"), dict) else {}
        missing_surfaces = [
            _normalize(item.get("key") if isinstance(item, dict) else item)
            for item in (coverage.get("missing_required_surfaces") or [])
            if _normalize(item.get("key") if isinstance(item, dict) else item)
        ]
        if not missing_surfaces:
            continue
        unique_missing = list(dict.fromkeys(missing_surfaces))
        failures.append(f"{platform}: 实际发布页缺少关键参数面 {', '.join(unique_missing)}")
        metadata[platform] = {
            "missing_required_surfaces": unique_missing,
            "probe_status": _normalize(probe_entry.get("status")).lower(),
            "route_url": _normalize((probe_entry.get("route") or {}).get("url")),
        }
    return failures, metadata


async def _run_checks(
    *,
    browser_agent_base_url: str,
    auth_token: str,
    publication_adapter: str = "browser_agent",
    cdp_url: str,
    platforms: list[str],
    target_profile_ids: list[str],
    request_timeout_sec: int,
    material_json: str = "",
    platform_packaging: str = "",
    packaging_gate_enforced: bool = True,
) -> dict[str, Any]:
    packaging_preflight = _evaluate_packaging_preflight(
        platforms=platforms,
        material_json=material_json,
        platform_packaging=platform_packaging,
        enforce_gate=packaging_gate_enforced,
    )
    live_publish_platforms = _derive_live_publish_platforms(
        requested_platforms=platforms,
        packaging_preflight=packaging_preflight,
    )
    agent_ready = await check_publication_browser_agent_ready(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=auth_token,
        target_platforms=live_publish_platforms,
        target_profile_ids=target_profile_ids,
        request_timeout_sec=request_timeout_sec,
    )
    cdp_connected = False
    all_tabs: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=request_timeout_sec) as client:
        probe_inventory: dict[str, Any] = {
            "checked": False,
            "status": "skipped",
            "platforms": {},
            "failures": [],
        }
        health_capabilities = agent_ready.get("health", {}).get("capabilities")
        if bool(agent_ready.get("ready")) and isinstance(health_capabilities, dict) and health_capabilities.get("inventory_probe") is True:
            try:
                probe_result = await _fetch_browser_agent_probe_inventory(
                    client,
                    browser_agent_base_url=browser_agent_base_url,
                    auth_token=auth_token,
                    platforms=live_publish_platforms,
                )
                probe_platforms = probe_result.get("platforms") if isinstance(probe_result.get("platforms"), dict) else {}
                probe_inventory = {
                    "checked": True,
                    "status": str(probe_result.get("status") or "ok").strip() or "ok",
                    "platforms": probe_platforms,
                    "generated_at": str(probe_result.get("generated_at") or "").strip(),
                    "probe_id": str(probe_result.get("probe_id") or "").strip(),
                    "failures": [],
                }
            except Exception as exc:
                probe_inventory = {
                    "checked": True,
                    "status": "probe_failed",
                    "platforms": {},
                    "failures": [f"browser-agent probe inventory 拉取失败：{exc}"],
                }

        cdp_fetch_error: Exception | None = None
        try:
            cdp_tabs_payload = await _fetch_cdp_tabs_payload(client, cdp_url)
            if isinstance(cdp_tabs_payload, dict):
                cdp_tabs = cdp_tabs_payload.get("tabs", cdp_tabs_payload.get("value"))
            else:
                cdp_tabs = cdp_tabs_payload
            if not isinstance(cdp_tabs, list):
                cdp_tabs = cdp_tabs_payload if isinstance(cdp_tabs_payload, list) else []
            if isinstance(cdp_tabs, list):
                all_tabs = list(cdp_tabs)
                cdp_connected = True
        except Exception as exc:
            cdp_fetch_error = exc

        if not cdp_connected and _should_fallback_to_browser_agent_probe_tabs(agent_ready):
            derived_tabs = _derive_tabs_from_probe_inventory(probe_inventory)
            if not derived_tabs:
                derived_tabs = _derive_tabs_from_creator_sessions(agent_ready, platforms=live_publish_platforms or platforms)
            if derived_tabs:
                all_tabs = derived_tabs
                cdp_connected = True
            elif cdp_fetch_error is not None:
                probe_inventory.setdefault("failures", [])
                probe_inventory["failures"].append(f"bridge transport 未返回可用 route 证据：{cdp_fetch_error}")

    platform_checks = {}
    for raw_platform in platforms:
        platform = _normalize_platform(raw_platform)
        packaging_entry = (
            packaging_preflight.get("platform_checks", {}).get(platform)
            if isinstance(packaging_preflight.get("platform_checks"), dict)
            else {}
        )
        packaging_status = _normalize((packaging_entry or {}).get("status")).lower()
        if packaging_status == "manual_handoff":
            platform_checks[platform] = {
                "status": "manual_handoff",
                "tab_id": None,
                "tab_url": None,
                "tab_title": None,
                "open_tabs_count": len(all_tabs),
                "message": "该平台当前走人工接管，不进入自动一键发布预检。",
                "probe_status": "skipped",
                "suggestion": "保留人工接管登录入口与交付证据，不阻断其它自动平台。",
            }
            continue
        tab = _find_best_tab(all_tabs, platform)
        probe_entry = (
            probe_inventory.get("platforms", {}).get(platform)
            if isinstance(probe_inventory.get("platforms"), dict)
            else {}
        )
        visual_evidence = _coerce_visual_evidence(probe_entry.get("visual_evidence")) if isinstance(probe_entry, dict) else {}
        if tab is None:
            platform_checks[platform] = {
                "status": "missing",
                "tab_id": None,
                "tab_url": None,
                "tab_title": None,
                "open_tabs_count": len(all_tabs),
                "message": "未检测到该平台发布页在 CDP 会话中打开。",
                "suggestion": "先在绑定浏览器会话中打开该平台发布页，再重试。",
                "probe_status": str(probe_entry.get("status") or "").strip() if isinstance(probe_entry, dict) else "",
                "visual_evidence": visual_evidence,
            }
        else:
            platform_checks[platform] = {
                "status": "found",
                "tab_id": str(tab.get("id") or ""),
                "tab_url": _normalize(tab.get("url")),
                "tab_title": _normalize(tab.get("title")),
                "open_tabs_count": len(all_tabs),
                "probe_status": str(probe_entry.get("status") or "").strip() if isinstance(probe_entry, dict) else "",
                "visual_evidence": visual_evidence,
            }

    failures: list[str] = []
    failures.extend([str(item).strip() for item in (packaging_preflight.get("failures") or []) if str(item).strip()])
    failures.extend([str(item).strip() for item in (probe_inventory.get("failures") or []) if str(item).strip()])
    probe_gate_failures, probe_gate_metadata = _collect_probe_inventory_gate_failures(
        platforms=platforms,
        probe_inventory=probe_inventory,
        packaging_preflight=packaging_preflight,
    )
    failures.extend(probe_gate_failures)

    for platform, item in platform_checks.items():
        if not isinstance(item, dict):
            continue
        metadata = probe_gate_metadata.get(platform) or {}
        if metadata:
            item["missing_required_surfaces"] = list(metadata.get("missing_required_surfaces") or [])
            item["probe_gate_blocked"] = True
            if not _normalize(item.get("message")):
                item["message"] = "实际发布页缺少关键参数面。"

    return {
        "generated_at": _now(),
        "request": {
            "browser_agent_base_url": browser_agent_base_url,
            "cdp_url": cdp_url,
            "platforms": platforms,
            "live_publish_platforms": live_publish_platforms,
            "target_profile_ids": target_profile_ids,
            "publication_adapter": _normalize_publication_adapter(publication_adapter),
        },
        "agent_ready": agent_ready,
        "cdp": {
            "connected": cdp_connected,
            "tab_count": len(all_tabs),
            "platform_checks": platform_checks,
        },
        "probe_inventory": probe_inventory,
        "packaging": packaging_preflight,
        "manual_handoff_targets": list(packaging_preflight.get("manual_handoff_targets") or []),
        "failures": failures,
        "all_tabs": [
            {
                "id": _normalize(tab.get("id")),
                "title": _normalize(tab.get("title")),
                "url": _normalize(tab.get("url")),
                "type": _normalize(tab.get("type")),
            }
            for tab in all_tabs[:200]
        ],
    }


def _print_summary(result: dict[str, Any]) -> None:
    ready = bool(result.get("agent_ready", {}).get("ready"))
    cdp_ready = bool(result.get("cdp", {}).get("connected"))
    print(f"[{_now()}] publication preflight ready={ready} cdp_connected={cdp_ready}")
    print(f"agent code: {result.get('agent_ready', {}).get('code')} message: {result.get('agent_ready', {}).get('message')}")

    platform_checks = result.get("cdp", {}).get("platform_checks", {}) or {}
    for platform, item in platform_checks.items():
        status = item.get("status")
        if status == "found":
            print(f"- {platform}: found tab {item.get('tab_title')} ({item.get('tab_id')})")
        else:
            print(
                f"- {platform}: {status} -> {item.get('message')} "
                f"[suggest: {item.get('suggestion')}]"
            )
    packaging = result.get("packaging") if isinstance(result.get("packaging"), dict) else {}
    if packaging.get("checked"):
        print(
            "packaging:"
                f" {packaging.get('status')} source={packaging.get('source') or 'unknown'}"
                f" material={packaging.get('material_json_path') or '-'}"
                f" packaging={packaging.get('platform_packaging_path') or '-'}"
        )
        if packaging.get("status") == "report_only":
            print("  - packaging gate: report_only (摸底模式，不阻断页面探测)")
        for platform, item in (packaging.get("platform_checks") or {}).items():
            print(f"  - {platform}: {item.get('status')} -> {item.get('message')}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run publication preflight checks before submit.")
    parser.add_argument("--platform", action="append", default=[], help="target platform (repeatable).")
    parser.add_argument(
        "--target-profile-id",
        action="append",
        default=[],
        help="browser profile id to assert for reuse (repeatable).",
    )
    parser.add_argument(
        "--allow-anonymous-profile",
        action="store_true",
        help="允许未指定 --target-profile-id 执行预检（默认禁止）。",
    )
    parser.add_argument("--publication-adapter", default="browser_agent", help="publication adapter in use")
    parser.add_argument("--browser-agent-base-url", default="", help="browser-agent base url, e.g. http://127.0.0.1:49310")
    parser.add_argument("--auth-token", default="", help="browser-agent bearer token")
    parser.add_argument("--cdp-url", default="", help="CDP base url, e.g. http://127.0.0.1:9222")
    parser.add_argument("--timeout", type=int, default=12, help="request timeout seconds")
    parser.add_argument("--output", default="", help="optional json output path")
    parser.add_argument("--material-json", default="", help="可选：smart-copy.json 路径；用于启用物料合同预检。")
    parser.add_argument("--platform-packaging", default="", help="可选：platform-packaging.json 路径；优先于 sibling 推导。")
    parser.add_argument(
        "--probe-only",
        action="store_true",
        help="仅做页面/会话摸底，不让 packaging publish_ready/collection_policy 门禁阻断整体 preflight 结果。",
    )
    parser.add_argument(
        "--require-tabs",
        action="store_true",
        default=True,
        dest="require_tabs",
        help="发布前置必须检测平台发布页 tab（默认开启）。",
    )
    parser.add_argument(
        "--no-require-tabs",
        action="store_false",
        dest="require_tabs",
        help="允许暂不校验平台发布页 tab（仅临时调试）。",
    )
    return parser.parse_args()


def _default_platforms() -> list[str]:
    return ["douyin", "xiaohongshu", "bilibili", "kuaishou", "toutiao", "youtube", "x"]


def _resolve_requested_platforms(
    raw_platforms: Iterable[str],
    *,
    material_json: str = "",
    platform_packaging: str = "",
) -> list[str]:
    explicit_platforms = _normalize_profile_ids(raw_platforms)
    if explicit_platforms:
        return explicit_platforms
    packaging, _ = load_publication_packaging_payload(
        material_json=material_json,
        platform_packaging=platform_packaging,
        platforms=None,
    )
    if isinstance(packaging, dict):
        scope = packaging.get("platform_scope") if isinstance(packaging.get("platform_scope"), dict) else {}
        requested_scope = [
            _normalize_platform(item)
            for item in (scope.get("requested_platforms") or [])
            if _normalize_platform(item)
        ]
        covered_scope = [
            _normalize_platform(item)
            for item in (scope.get("covered_platforms") or [])
            if _normalize_platform(item)
        ]
        scope_platforms = requested_scope or covered_scope
        if scope_platforms:
            return scope_platforms
        raw_packaging_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
        normalized_packaging_platforms = [
            _normalize_platform(item)
            for item in raw_packaging_platforms.keys()
            if _normalize_platform(item)
        ]
        if normalized_packaging_platforms:
            return normalized_packaging_platforms
    return _default_platforms()


def _parse_platforms_from_failure_text(text: str) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    if ":" in normalized:
        head, _ = normalized.split(":", 1)
        head = _normalize_platform(head)
        if head:
            return [head]
    if "缺少目标平台发布页标签" in normalized and ":" in normalized:
        _, tail = normalized.split(":", 1)
        return [_normalize_platform(item) for item in tail.split(",") if _normalize_platform(item)]
    return []


def _append_preflight_recommendation(
    recommendations: list[dict[str, Any]],
    seen: set[tuple[str, str, tuple[str, ...], bool]],
    *,
    platform: str = "",
    issue: str,
    operations: list[str],
    auto_remediable: bool,
) -> None:
    normalized_platform = _normalize_platform(platform)
    normalized_operations = tuple(item for item in [str(value).strip() for value in (operations or [])] if item)
    signature = (normalized_platform, issue, normalized_operations, bool(auto_remediable))
    if signature in seen:
        return
    seen.add(signature)
    recommendations.append(
        {
            "platform": normalized_platform,
            "issue": issue,
            "operations": list(normalized_operations),
            "auto_remediable": bool(auto_remediable),
        }
    )


def _build_preflight_recommendations(result: dict[str, Any], *, requested_platforms: list[str], require_tabs: bool) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...], bool]] = set()
    normalized_platforms = [_normalize_platform(item) for item in requested_platforms if _normalize_platform(item)]

    agent_ready = result.get("agent_ready") if isinstance(result.get("agent_ready"), dict) else {}
    agent_code = _normalize(agent_ready.get("code")).lower()
    if agent_code == "missing_profile_id":
        _append_preflight_recommendation(
            recommendations,
            seen,
            issue="profile_requirement_failed",
            operations=["bind_target_profile", "rerun_preflight"],
            auto_remediable=False,
        )
    if agent_code and agent_code != "ready":
        _append_preflight_recommendation(
            recommendations,
            seen,
            issue="browser_session_not_ready",
            operations=["restore_browser_agent", "restore_cdp_session", "rerun_preflight"],
            auto_remediable=False,
        )
    probe_inventory = result.get("probe_inventory") if isinstance(result.get("probe_inventory"), dict) else {}
    if bool(probe_inventory.get("checked")) and _normalize(probe_inventory.get("status")).lower() == "probe_failed":
        _append_preflight_recommendation(
            recommendations,
            seen,
            issue="probe_inventory_failed",
            operations=["inspect_probe_visual_evidence", "restore_browser_agent", "rerun_preflight"],
            auto_remediable=True,
        )

    for failure in [str(item).strip() for item in (result.get("failures") or []) if str(item).strip()]:
        lowered = failure.lower()
        if "范围不匹配" in failure or "覆盖范围" in failure or "仅覆盖平台" in failure:
            parsed_platforms = _parse_platforms_from_failure_text(failure) or normalized_platforms
            for platform in parsed_platforms or [""]:
                _append_preflight_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="platform_scope_mismatch",
                    operations=["regenerate_platform_material", "restrict_requested_platforms"],
                    auto_remediable=True,
                )
        if "实际发布页缺少关键参数面" in failure:
            parsed_platforms = _parse_platforms_from_failure_text(failure) or normalized_platforms
            for platform in parsed_platforms or [""]:
                _append_preflight_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="probe_gate_blocked",
                    operations=["inspect_probe_visual_evidence", "repair_live_publish_preflight", "rerun_preflight"],
                    auto_remediable=True,
                )
        if "缺少目标平台发布页标签" in failure or "tab" in lowered:
            parsed_platforms = _parse_platforms_from_failure_text(failure) or normalized_platforms
            for platform in parsed_platforms or [""]:
                _append_preflight_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="missing_publish_tab",
                    operations=["open_publish_tab", "rerun_preflight"],
                    auto_remediable=False,
                )
        if "browser-agent" in lowered or "cdp" in lowered:
            _append_preflight_recommendation(
                recommendations,
                seen,
                issue="browser_session_not_ready",
                operations=["restore_browser_agent", "restore_cdp_session", "rerun_preflight"],
                auto_remediable=False,
            )

    if require_tabs:
        platform_checks = result.get("cdp", {}).get("platform_checks") if isinstance(result.get("cdp"), dict) else {}
        if isinstance(platform_checks, dict):
            missing_tabs = [platform for platform, item in platform_checks.items() if (item or {}).get("status") != "found"]
            for platform in missing_tabs:
                _append_preflight_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="missing_publish_tab",
                    operations=["open_publish_tab", "rerun_preflight"],
                    auto_remediable=False,
                )

    return recommendations


def _build_preflight_recovery_index(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: dict[str, int] = {}
    platform_counts: dict[str, int] = {}
    for recommendation in recommendations:
        issue = _normalize(recommendation.get("issue"))
        platform = _normalize_platform(recommendation.get("platform"))
        if issue:
            issue_counts[issue] = int(issue_counts.get(issue) or 0) + 1
        if platform:
            platform_counts[platform] = int(platform_counts.get(platform) or 0) + 1
    return {
        "issue_counts": issue_counts,
        "platform_counts": platform_counts,
        "auto_recoverable_recommendations": len([item for item in recommendations if bool(item.get("auto_remediable"))]),
        "manual_required_recommendations": len([item for item in recommendations if not bool(item.get("auto_remediable"))]),
    }


def _build_preflight_mitigation(
    failures: list[str],
    recommendations: list[dict[str, Any]],
    *,
    summary_status: str,
) -> dict[str, Any]:
    suggestion_map = {
        "profile_requirement_failed": "检测到 profile 绑定缺失，请显式指定 --target-profile-id 后重跑 preflight。",
        "browser_session_not_ready": "检测到 browser-agent/CDP 会话未就绪，请先恢复浏览器会话后再重跑 preflight。",
        "probe_inventory_failed": "检测到 browser-agent 页面探测失败，请先恢复探测链路或检查当前页面状态后再重跑 preflight。",
        "missing_publish_tab": "检测到目标平台发布页标签缺失，请先打开对应发布页后再重跑 preflight。",
        "platform_scope_mismatch": "检测到目标平台超出本期物料合同覆盖范围，请重生成该平台物料或缩小发布平台范围后再发。",
        "probe_gate_blocked": "检测到实际发布页缺少关键参数面，请结合截图证据修复 live_publish_preflight 或页面能力后再重跑 preflight。",
    }
    steps: list[str] = []
    playbook: dict[str, list[str]] = {}
    for item in recommendations:
        issue = _normalize(item.get("issue"))
        if issue in suggestion_map:
            steps.append(suggestion_map[issue])
        operations = [str(op).strip() for op in (item.get("operations") or []) if str(op).strip()]
        if issue and operations:
            playbook.setdefault(issue, [])
            playbook[issue].extend(operations)
    if not steps and failures:
        if summary_status == "manual_handoff":
            steps.append("检测到当前平台仅支持人工接管，请转入人工发布。")
            playbook.setdefault("manual_handoff_required", []).extend(["open_manual_login", "continue_manual_publish"])
        else:
            steps.append("preflight 未通过，请先修复浏览器会话、平台页签、物料合同或页面关键参数面后再重跑。")
            playbook.setdefault("preflight", []).extend(["inspect_live_gate", "inspect_packaging", "inspect_probe_visual_evidence", "rerun_preflight"])
    for key, values in playbook.items():
        playbook[key] = sorted({value for value in values if value})
    return {
        "steps": sorted({item for item in steps if item}),
        "playbook": playbook,
    }


def _build_preflight_publication_verification(
    result: dict[str, Any],
    *,
    requested_platforms: list[str],
    require_tabs: bool,
) -> dict[str, Any]:
    failures = [str(item).strip() for item in (result.get("failures") or []) if str(item).strip()]
    packaging = result.get("packaging") if isinstance(result.get("packaging"), dict) else {}
    creator_sessions = result.get("agent_ready", {}).get("health", {}).get("creator_sessions") if isinstance(result.get("agent_ready"), dict) else {}
    creator_session_visual_evidence = {
        _normalize_platform(platform): dict(item.get("visual_evidence"))
        for platform, item in (creator_sessions or {}).items()
        if isinstance(item, dict) and isinstance(item.get("visual_evidence"), dict) and item.get("visual_evidence")
    }
    probe_inventory = result.get("probe_inventory") if isinstance(result.get("probe_inventory"), dict) else {}
    probe_inventory_visual_evidence = {
        _normalize_platform(platform): dict(item.get("visual_evidence"))
        for platform, item in ((probe_inventory.get("platforms") or {}) if isinstance(probe_inventory, dict) else {}).items()
        if isinstance(item, dict) and isinstance(item.get("visual_evidence"), dict) and item.get("visual_evidence")
    }
    summary_status = "passed"
    probe_inventory_status = _normalize((probe_inventory or {}).get("status")).lower()
    agent_ready_flag = bool((result.get("agent_ready") or {}).get("ready"))
    cdp_connected_flag = bool((result.get("cdp") or {}).get("connected"))
    if failures or not agent_ready_flag or not cdp_connected_flag or probe_inventory_status == "probe_failed":
        summary_status = "failed"
    elif packaging.get("status") == "manual_handoff":
        summary_status = "manual_handoff"
    recommendations = _build_preflight_recommendations(
        result,
        requested_platforms=requested_platforms,
        require_tabs=require_tabs,
    )
    return {
        "scope": "preflight",
        "summary_status": summary_status,
        "creator_session_visual_evidence_by_platform": creator_session_visual_evidence,
        "probe_inventory_visual_evidence_by_platform": probe_inventory_visual_evidence,
        "recommendations": recommendations,
        "recovery_index": _build_preflight_recovery_index(recommendations),
    }


async def main() -> int:
    os.chdir(str(REPO_ROOT))

    args = _parse_args()
    settings = get_settings()

    browser_agent_base_url = _normalize(args.browser_agent_base_url) or _normalize(
        getattr(settings, "publication_browser_agent_base_url", "")
    )
    cdp_url = _normalize(args.cdp_url) or _normalize(getattr(settings, "publication_browser_cdp_url", "http://127.0.0.1:9222")).rstrip("/")
    auth_token = _normalize(args.auth_token) or _normalize(getattr(settings, "publication_browser_agent_auth_token", ""))
    platforms = _resolve_requested_platforms(
        args.platform,
        material_json=_normalize(getattr(args, "material_json", "")),
        platform_packaging=_normalize(getattr(args, "platform_packaging", "")),
    )
    target_profile_ids = _normalize_profile_ids(args.target_profile_id)
    if not target_profile_ids and not args.allow_anonymous_profile:
        print("预检前置: 未提供 --target-profile-id。为避免匿名草稿与脏环境，默认不允许执行。")
        print("若必须进行临时匿名验证，请显式传入 --allow-anonymous-profile。")
        return 2

    result = await _run_checks(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=auth_token,
        publication_adapter=_normalize_publication_adapter(args.publication_adapter),
        cdp_url=cdp_url,
        platforms=platforms,
        target_profile_ids=target_profile_ids,
        request_timeout_sec=max(3, int(args.timeout or 12)),
        material_json=_normalize(getattr(args, "material_json", "")),
        platform_packaging=_normalize(getattr(args, "platform_packaging", "")),
        packaging_gate_enforced=not bool(getattr(args, "probe_only", False)),
    )
    publication_verification = _build_preflight_publication_verification(
        result,
        requested_platforms=platforms,
        require_tabs=bool(args.require_tabs),
    )
    result["publication_verification"] = publication_verification
    result["mitigation"] = _build_preflight_mitigation(
        [str(item).strip() for item in (result.get("failures") or []) if str(item).strip()],
        publication_verification.get("recommendations") or [],
        summary_status=_normalize(publication_verification.get("summary_status")).lower(),
    )
    result["suggestions"] = list(result.get("mitigation", {}).get("steps") or [])
    if result.get("failures"):
        result["status"] = "failed"
    elif result.get("packaging", {}).get("status") == "manual_handoff":
        result["status"] = "manual_handoff"
    elif not result.get("agent_ready", {}).get("ready") or not result.get("cdp", {}).get("connected"):
        result["status"] = "failed"
    else:
        result["status"] = "passed"

    _print_summary(result)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"report: {output_path}")

    if not result.get("agent_ready", {}).get("ready"):
        return 2
    if not result.get("cdp", {}).get("connected"):
        return 3
    packaging = result.get("packaging") if isinstance(result.get("packaging"), dict) else {}
    if (
        packaging.get("checked")
        and bool(packaging.get("gate_enforced", True))
        and (packaging.get("failures") or [])
    ):
        return 5
    if result.get("failures"):
        return 6
    if args.require_tabs:
        platform_checks = result.get("cdp", {}).get("platform_checks", {})
        live_publish_platforms = [
            _normalize_platform(item)
            for item in (result.get("request", {}).get("live_publish_platforms") or [])
            if _normalize_platform(item)
        ]
        if any((platform_checks.get(platform) or {}).get("status") != "found" for platform in live_publish_platforms):
            return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
