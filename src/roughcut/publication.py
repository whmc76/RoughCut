from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.config import DEFAULT_PROJECT_ROOT, get_settings
from roughcut.intelligent_copy_layout import (
    resolve_smart_copy_cover_group_output_path,
    resolve_smart_copy_material_json_path,
    resolve_smart_copy_platform_packaging_json_path,
    smart_copy_cover_dir,
)
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.db.models import PublicationAttempt, PublicationAttemptRun
from roughcut.publication_platform_matrix import (
    platform_allows_field_edits_while_processing,
    platform_cover_project_mode,
    platform_cover_asset_policy,
    platform_default_declaration,
    platform_draft_resume_policy,
    platform_manual_handoff_only,
    platform_manual_publish_entry_url,
    platform_manual_publish_reason,
    platform_publish_entry_url,
    platform_publish_projects,
    platform_required_cover_slots,
    platform_requires_custom_cover_policy,
    platform_requires_explicit_collection_policy,
    platform_stop_when_current_page_already_correct,
    platform_supports_scheduled_publish,
    platform_upload_processing_blocks_final_publish_only,
)
from roughcut.publication_packaging import (
    derive_publication_cover_slots,
    load_publication_packaging_payload,
    publication_packaging_entry_publish_ready,
    publication_primary_cover_path,
)

CANONICAL_PUBLICATION_ADAPTER = "browser_agent"
BROWSER_AGENT_PUBLICATION_RUN_CONTRACT = "browser_agent_publication_v1"
PUBLICATION_BROWSER_AGENT_TASK_IDENTITY_CONTRACT = "publication_task_identity_v1"
PUBLICATION_BROWSER_AGENT_CREATOR_SESSION_CONTRACT = "publication_creator_session_probe_v1"
X_LINK_SHARE_PUBLICATION_ADAPTER = "x_link_share"
X_LINK_SHARE_PUBLICATION_RUN_CONTRACT = "x_link_share_publication_v1"
BROWSER_AGENT_EXECUTION_MODE = "browser_agent"
PUBLISHABLE_CREDENTIAL_STATUSES = {"logged_in", "available", "verified"}
PUBLICATION_ACTIVE_STATUSES = {"queued", "claimed", "submitted", "processing", "scheduled_pending"}
PUBLICATION_RECONCILE_STATUSES = {"submitted", "processing", "scheduled_pending"}
PUBLICATION_TERMINAL_STATUSES = {"published", "draft_created", "failed", "needs_human", "cancelled"}
PUBLICATION_SUCCESS_STATUSES = {"published", "draft_created", "scheduled_pending"}
PUBLICATION_BROWSER_SESSION_BINDING_CONTRACT = "publication_browser_session_binding_v1"
BROWSER_AGENT_RETRYABLE_STATUSES = {"network_error", "rate_limited", "upload_failed"}
BROWSER_AGENT_HUMAN_STATUSES = {"auth_expired", "captcha_required", "human_confirm", "needs_human"}
BROWSER_AGENT_FAILED_STATUSES = {
    "content_rejected",
    "dom_changed",
    "failed",
    "failed_permanent",
    "partial_failed",
    "unknown",
}
PUBLICATION_LLM_RECOVERY_TIMEOUT_SEC = 8
PUBLICATION_LLM_RECOVERY_REQUIRED_FIELDS = {"severity", "action", "next_steps"}
PUBLICATION_LLM_MAX_SUMMARY_LENGTH = 1800
PUBLICATION_LLM_AUTO_RECOVERY_ENABLED = True
PUBLICATION_LLM_AUTO_RECOVERY_ACTIONS = {"retry", "requeue"}
PUBLICATION_LLM_AUTO_RECOVERY_CONFIDENCE_THRESHOLD = 0.85
PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION = 1
PUBLICATION_RECOVERY_ADAPTIVE_HISTORY_LIMIT = 80
PUBLICATION_RECOVERY_REPEAT_LIMIT = 3
PUBLICATION_RECOVERY_OVERRIDE_KEYS = {
    "clear_draft_context",
    "force_publish_page_refresh",
    "recovery_mode",
    "verification_only_current_page",
    "repair_only_current_page",
    "prepublish_only_current_page",
    "prepare_only_current_page",
    "fresh_start_platform_tab",
    "verify_media_upload",
    "wait_for_publish_confirmation",
}
_PUBLICATION_DRAFT_RESET_ERROR_SUFFIXES = {
    "publication_audit_unverified",
    "publication_content_mismatch",
    "publication_signature_missing",
    "publication_signature_mismatch",
    "publication_signature_fields_missing",
    "publication_signature_fields_mismatch",
    "publication_public_url_missing",
    "publication_schedule_receipt_missing",
    "bilibili_final_publish_unconfirmed",
    "kuaishou_final_publish_unconfirmed",
    "_final_publish_unconfirmed",
    "_material_integrity_failed",
    "_pre_publish_material_integrity_failed",
    "_content_plan_mismatch",
    "_pre_publish_content_plan_mismatch",
    "_post_publish_content_plan_mismatch",
    "_scheduled_receipt_content_plan_mismatch",
    "_publish_content_plan_mismatch",
    "_receipt_content_plan_mismatch",
    "_final_publish_route_not_ready",
}
_PUBLICATION_AUTH_REQUIRED_ERROR_SUFFIXES = {
    "_route_auth_required",
    "_final_publish_route_auth_required",
    "_auth_required",
    "_authentication",
    "_need_login",
    "_need_relogin",
}
_YOUTUBE_CATEGORY_PLACEHOLDER_VALUES = {
    "category",
    "categories",
    "language",
    "captions",
    "subtitles",
    "视频",
    "类别",
    "分类",
    "语言",
    "字幕",
    "内容检测",
    "创收",
    "信息中心",
    "数据分析",
    "社区",
    "自定义",
    "音频库",
    "设置",
    "发送反馈",
    "内容",
}


def _normalize_publication_adapter(value: Any) -> str:
    normalized = str(value or CANONICAL_PUBLICATION_ADAPTER).strip().lower().replace("-", "_")
    if normalized in {"xlinkshare", "xlink_share", "xlink", "xshare", "x_link", "xshare_task", "x_share", "x_share_only"}:
        return X_LINK_SHARE_PUBLICATION_ADAPTER
    if normalized in {""}:
        return CANONICAL_PUBLICATION_ADAPTER
    return normalized


def _resolve_publication_adapter_publication_contract(value: Any) -> str:
    adapter = _normalize_publication_adapter(value)
    if adapter == X_LINK_SHARE_PUBLICATION_ADAPTER:
        return X_LINK_SHARE_PUBLICATION_RUN_CONTRACT
    return BROWSER_AGENT_PUBLICATION_RUN_CONTRACT


def _resolve_publication_browser_agent_service_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "publication_browser_agent_service.mjs"


def _local_publication_browser_agent_service_sha256() -> str:
    try:
        payload = _resolve_publication_browser_agent_service_script_path().read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(payload).hexdigest()


def _publication_adapter_display_name(adapter: str) -> str:
    normalized = _normalize_publication_adapter(adapter)
    if normalized == X_LINK_SHARE_PUBLICATION_ADAPTER:
        return "x_link_share"
    if normalized == "browser_agent":
        return "browser-agent"
    return normalized or CANONICAL_PUBLICATION_ADAPTER

SUPPORTED_PUBLICATION_PLATFORMS: dict[str, dict[str, str]] = {
    "douyin": {"label": "抖音", "kind": "video"},
    "xiaohongshu": {"label": "小红书", "kind": "video"},
    "bilibili": {"label": "B站", "kind": "video"},
    "kuaishou": {"label": "快手", "kind": "video"},
    "wechat-channels": {"label": "视频号", "kind": "video"},
    "toutiao": {"label": "头条号", "kind": "video"},
    "youtube": {"label": "YouTube", "kind": "video"},
    "x": {"label": "X", "kind": "video"},
}

STABLE_PUBLICATION_PLATFORMS: tuple[str, ...] = (
    "douyin",
    "xiaohongshu",
    "bilibili",
    "kuaishou",
    "toutiao",
    "youtube",
    "x",
)
STABLE_PUBLICATION_PLATFORM_SET = set(STABLE_PUBLICATION_PLATFORMS)
PLATFORM_LOCAL_MEDIA_REQUIRED: dict[str, bool] = {platform: platform != "x" for platform in SUPPORTED_PUBLICATION_PLATFORMS}
DEFAULT_PUBLICATION_TIMEZONE = ZoneInfo("Asia/Shanghai")
REQUIRED_BROWSER_AGENT_COMPOSITE_FRAMEWORKS: dict[str, str] = {
    "douyin": "douyin_creator_composite_v1",
    "bilibili": "bilibili_creator_native_composite_v1",
    "youtube": "youtube_studio_composite_v1",
    "xiaohongshu": "xiaohongshu_creator_composite_v1",
    "kuaishou": "kuaishou_creator_composite_v1",
    "toutiao": "toutiao_xigua_composite_v1",
    "wechat-channels": "wechat_channels_composite_v1",
    "x": "x_composer_composite_v1",
}

_PUBLICATION_BROWSER_ALIASES = {
    "chrome": "chrome",
    "google-chrome": "chrome",
    "edge": "edge",
    "msedge": "edge",
    "microsoft-edge": "edge",
    "firefox": "firefox",
    "browser-agent": "browser-agent",
    "default": "browser-agent",
}


def normalize_publication_browser_name(value: Any) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "-").replace("_", "-")
    return _PUBLICATION_BROWSER_ALIASES.get(normalized, normalized)


def _normalize_publication_browser_path(value: Any) -> str | None:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return None
    normalized = re.sub(r"/+", "/", text).rstrip("/")
    return normalized or None


def build_publication_browser_profile_id(
    *,
    browser: Any,
    user_data_dir: Any,
    profile_directory: Any,
) -> str | None:
    normalized_browser = normalize_publication_browser_name(browser)
    normalized_user_data_dir = _normalize_publication_browser_path(user_data_dir)
    normalized_profile_directory = str(profile_directory or "").strip()
    if not normalized_browser or not normalized_user_data_dir or not normalized_profile_directory:
        return None
    digest = hashlib.sha1(
        "\n".join(
            (
                normalized_browser,
                normalized_user_data_dir.lower(),
                normalized_profile_directory.lower(),
            )
        ).encode("utf-8")
    ).hexdigest()[:20]
    return f"browser-profile:{normalized_browser}:{digest}"


def _looks_like_publication_browser_profile_ref(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized.startswith("browser-profile:") or normalized.startswith("browser-agent:")


def normalize_publication_browser_binding(value: Any) -> dict[str, Any]:
    payload = value if isinstance(value, dict) else {}
    browser = normalize_publication_browser_name(payload.get("browser"))
    user_data_dir = _normalize_publication_browser_path(payload.get("user_data_dir") or payload.get("browser_user_data_dir"))
    profile_directory = str(
        payload.get("profile_directory") or payload.get("browser_profile_directory") or ""
    ).strip() or None
    cdp_base_url = str(payload.get("cdp_base_url") or payload.get("browser_cdp_base_url") or "").strip().rstrip("/") or None
    profile_name = str(payload.get("profile_name") or payload.get("browser_profile_name") or "").strip() or None
    profile_email = str(payload.get("profile_email") or payload.get("browser_profile_email") or "").strip() or None
    profile_id = str(payload.get("profile_id") or payload.get("browser_profile_id") or "").strip() or None
    if not profile_id:
        profile_id = build_publication_browser_profile_id(
            browser=browser,
            user_data_dir=user_data_dir,
            profile_directory=profile_directory,
        )
    if not browser and not user_data_dir and not profile_directory and not cdp_base_url and not profile_id:
        return {}
    return {
        "browser": browser or None,
        "user_data_dir": user_data_dir,
        "profile_directory": profile_directory,
        "profile_name": profile_name,
        "profile_email": profile_email,
        "cdp_base_url": cdp_base_url,
        "profile_id": profile_id,
    }


def build_publication_browser_session_binding(
    *,
    platform: Any,
    creator_profile_id: Any = None,
    browser_profile_id: Any = None,
    credential_ref: Any = None,
    account_label: Any = None,
    browser_binding: Any = None,
    allowed_route_contexts: Any = None,
) -> dict[str, Any]:
    normalized_platform = normalize_publication_platform(platform) or str(platform or "").strip().lower()
    normalized_browser_binding = normalize_publication_browser_binding(browser_binding)
    normalized_credential_ref = str(credential_ref or "").strip()
    normalized_account_label = str(account_label or "").strip()
    resolved_profile_id = (
        str(browser_profile_id or "").strip()
        or str(normalized_browser_binding.get("profile_id") or "").strip()
        or (normalized_credential_ref if _looks_like_publication_browser_profile_ref(normalized_credential_ref) else "")
        or (normalized_account_label if _looks_like_publication_browser_profile_ref(normalized_account_label) else "")
    )
    route_contexts = sorted(
        {
            str(item or "").strip()
            for item in (allowed_route_contexts or [])
            if str(item or "").strip()
        }
    )
    if (
        not normalized_platform
        and not str(creator_profile_id or "").strip()
        and not resolved_profile_id
        and not str(credential_ref or "").strip()
        and not str(account_label or "").strip()
        and not normalized_browser_binding
        and not route_contexts
    ):
        return {}
    payload: dict[str, Any] = {
        "contract": PUBLICATION_BROWSER_SESSION_BINDING_CONTRACT,
        "platform": normalized_platform or None,
        "creator_profile_id": str(creator_profile_id or "").strip() or None,
        "browser_profile_id": resolved_profile_id or None,
        "credential_ref": normalized_credential_ref or None,
        "account_label": normalized_account_label or None,
        "allowed_profile_ids": [resolved_profile_id] if resolved_profile_id else [],
        "allowed_route_contexts": route_contexts,
    }
    if normalized_browser_binding:
        payload["browser_binding"] = normalized_browser_binding
    return payload


async def check_publication_browser_agent_ready(
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    target_platforms: list[str] | None = None,
    target_profile_ids: list[str] | None = None,
    session_bindings: dict[str, dict[str, Any]] | None = None,
    http_client: Any | None = None,
    request_timeout_sec: int = 10,
    require_live_publish: bool = True,
) -> dict[str, Any]:
    """Validate that the configured browser-agent can execute real publish tasks."""
    requested_platforms = [
        platform
        for platform in (normalize_publication_platform(item) for item in (target_platforms or []))
        if platform
    ]
    requested_profile_ids = [
        str(item or "").strip()
        for item in (target_profile_ids or [])
        if str(item or "").strip()
    ]
    requested_browser_profile_ids = [
        item
        for item in requested_profile_ids
        if _looks_like_publication_browser_profile_ref(item)
    ]
    normalized_session_bindings = {
        platform: build_publication_browser_session_binding(
            platform=platform,
            creator_profile_id=(binding or {}).get("creator_profile_id"),
            browser_profile_id=(binding or {}).get("browser_profile_id"),
            credential_ref=(binding or {}).get("credential_ref"),
            account_label=(binding or {}).get("account_label"),
            browser_binding=(binding or {}).get("browser_binding"),
            allowed_route_contexts=(binding or {}).get("allowed_route_contexts"),
        )
        for platform, binding in (session_bindings or {}).items()
        if normalize_publication_platform(platform)
    }
    health_path = "/healthz"
    if requested_platforms:
        query_payload: dict[str, str] = {
            "check_session": "1",
            "platforms": ",".join(requested_platforms),
        }
        if requested_browser_profile_ids:
            query_payload["target_profile_ids"] = ",".join(requested_browser_profile_ids)
        if normalized_session_bindings:
            query_payload["session_bindings"] = json.dumps(
                normalized_session_bindings,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        health_path = "/healthz?" + urlencode(query_payload)
    try:
        payload = await _browser_agent_request_json(
            "GET",
            health_path,
            base_url=browser_agent_base_url,
            auth_token=auth_token,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    except Exception as exc:
        return {
            "ready": False,
            "code": "browser_agent_unavailable",
            "message": f"browser-agent 不可用，不能开始正式发布：{exc}",
            "health": {},
        }

    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    if capabilities.get("publication_tasks") is not True:
        return {
            "ready": False,
            "code": "browser_agent_publication_tasks_unsupported",
            "message": "当前 browser-agent 只支持摸底，不支持 /tasks 正式发布执行；已阻止创建假发布任务。",
            "health": payload,
        }
    if capabilities.get("task_identity_echo") is not True or str(
        capabilities.get("task_identity_contract") or ""
    ).strip() != PUBLICATION_BROWSER_AGENT_TASK_IDENTITY_CONTRACT:
        return {
            "ready": False,
            "code": "browser_agent_task_identity_contract_unsupported",
            "message": "当前 browser-agent 未声明 attempt_id/content_id 回显合同，已阻止继续发布以避免终态无法回写 attempt。",
            "health": payload,
        }
    local_runtime_sha256 = _local_publication_browser_agent_service_sha256()
    runtime_sha256 = str(payload.get("service_script_sha256") or "").strip().lower()
    if local_runtime_sha256 and runtime_sha256 and runtime_sha256 != local_runtime_sha256:
        return {
            "ready": False,
            "code": "browser_agent_runtime_drift",
            "message": "当前 browser-agent 运行脚本与工作区版本不一致，已阻止继续发布以避免静默吃掉 task identity 或回执合同。",
            "health": payload,
        }
    if require_live_publish and capabilities.get("live_publish") is not True:
        return {
            "ready": False,
            "code": "browser_agent_live_publish_unsupported",
            "message": "当前 browser-agent 可以接收发布任务，但未声明支持最终预约/发布点击；已阻止正式 live 发布。",
            "health": payload,
        }
    if require_live_publish:
        final_platforms = {
            platform
            for platform in (normalize_publication_platform(item) for item in (capabilities.get("final_publish_platforms") or []))
            if platform
        }
        missing_platforms = sorted(set(requested_platforms) - final_platforms, key=_platform_sort_key)
        if missing_platforms:
            labels = "、".join(platform_label(platform) for platform in missing_platforms)
            return {
                "ready": False,
                "code": "browser_agent_live_publish_platform_unsupported",
                "message": f"browser-agent 当前未声明支持这些平台的最终发布点击器：{labels}；已阻止创建假发布任务。",
                "health": payload,
            }
    requested_composite_platforms = [
        platform for platform in requested_platforms if platform in REQUIRED_BROWSER_AGENT_COMPOSITE_FRAMEWORKS
    ]
    if requested_composite_platforms and capabilities.get("legacy_lightweight_scripts_blocked") is not True:
        labels = "、".join(platform_label(platform) for platform in requested_composite_platforms)
        return {
            "ready": False,
            "code": "browser_agent_legacy_lightweight_scripts_not_blocked",
            "message": f"browser-agent 未声明阻断旧轻量脚本入口，不能对这些平台执行正式发布：{labels}。",
            "health": payload,
        }
    framework_map = capabilities.get("platform_composite_frameworks")
    framework_map = framework_map if isinstance(framework_map, dict) else {}
    missing_frameworks = [
        platform
        for platform in requested_composite_platforms
        if framework_map.get(platform) != REQUIRED_BROWSER_AGENT_COMPOSITE_FRAMEWORKS[platform]
    ]
    if missing_frameworks:
        labels = "、".join(
            f"{platform_label(platform)}({REQUIRED_BROWSER_AGENT_COMPOSITE_FRAMEWORKS[platform]})"
            for platform in missing_frameworks
        )
        return {
            "ready": False,
            "code": "browser_agent_composite_framework_missing",
            "message": f"browser-agent 未声明这些平台的专用复合框架：{labels}；已阻止退回旧轻量脚本。",
            "health": payload,
        }
    if str(payload.get("cdp_status") or "").strip().lower() not in {"", "ok", "ready"}:
        return {
            "ready": False,
            "code": "browser_agent_cdp_unavailable",
            "message": f"browser-agent 已启动但浏览器 CDP 不可用：{payload.get('cdp_error') or payload.get('cdp_status')}",
            "health": payload,
        }
    if requested_profile_ids:
        profile_reuse = assess_browser_agent_profile_reuse(payload, target_profile_ids=requested_browser_profile_ids)
        if not profile_reuse.get("reusable"):
            return {
                "ready": False,
                "code": "browser_agent_profile_reuse_unverified",
                "message": str(profile_reuse.get("message") or "browser-agent 未声明可复用指定 CDP profile。"),
            "health": payload,
            "profile_reuse": profile_reuse,
        }
    if requested_platforms:
        if capabilities.get("creator_session_probe") is not True or str(
            capabilities.get("creator_session_contract") or ""
        ).strip() != PUBLICATION_BROWSER_AGENT_CREATOR_SESSION_CONTRACT:
            return {
                "ready": False,
                "code": "browser_agent_creator_session_contract_unsupported",
                "message": "当前 browser-agent 未声明 creator 会话探测合同，已阻止继续发布以避免登录态漂移被误判成可发布。",
                "health": payload,
            }
        raw_creator_sessions = payload.get("creator_sessions")
        creator_sessions = raw_creator_sessions if isinstance(raw_creator_sessions, dict) else {}
        auth_required_platforms: list[str] = []
        unverified_platforms: list[str] = []
        binding_invalid_platforms: list[str] = []
        for platform in requested_platforms:
            session_state = creator_sessions.get(platform)
            if not isinstance(session_state, dict):
                unverified_platforms.append(platform)
                continue
            session_status = str(session_state.get("status") or "").strip().lower()
            if session_status == "auth_required":
                auth_required_platforms.append(platform)
            elif session_status in {"binding_missing", "binding_mismatch"}:
                binding_invalid_platforms.append(platform)
            elif session_status not in {"ready"}:
                unverified_platforms.append(platform)
        if auth_required_platforms:
            labels = "、".join(platform_label(platform) for platform in auth_required_platforms)
            return {
                "ready": False,
                "code": "browser_agent_creator_session_auth_required",
                "message": f"browser-agent 绑定的创作者会话当前未登录或已失效：{labels}；已阻止继续发布以避免把登录页误当成发布页。",
                "health": payload,
            }
        if binding_invalid_platforms:
            labels = "、".join(platform_label(platform) for platform in binding_invalid_platforms)
            return {
                "ready": False,
                "code": "browser_agent_creator_session_binding_mismatch",
                "message": f"browser-agent 当前附着的浏览器会话与这些平台的 creator profile/profile 绑定不一致：{labels}；已 fail-closed 阻止继续验证或发布。",
                "health": payload,
            }
        if unverified_platforms:
            labels = "、".join(platform_label(platform) for platform in unverified_platforms)
            return {
                "ready": False,
                "code": "browser_agent_creator_session_unverified",
                "message": f"browser-agent 当前无法确认这些平台的创作者会话已进入可发布态：{labels}；已阻止继续发布。",
                "health": payload,
            }
    return {
        "ready": True,
        "code": "ready",
        "message": "browser-agent 支持正式发布任务。",
        "health": payload,
    }


def assess_browser_agent_profile_reuse(
    health_payload: dict[str, Any] | None,
    *,
    target_profile_ids: list[str],
) -> dict[str, Any]:
    """Check whether browser-agent can bind tasks to the requested CDP profiles.

    The browser-agent may be connected to one already-open CDP session. In that
    mode a saved creator credential is only a logical account label; it is not a
    reusable browser profile selector unless the agent explicitly says so.
    """
    payload = health_payload if isinstance(health_payload, dict) else {}
    capabilities = payload.get("capabilities") if isinstance(payload.get("capabilities"), dict) else {}
    requested = sorted({str(item or "").strip() for item in target_profile_ids if str(item or "").strip()})
    declared_profiles = sorted(
        {
            str(item or "").strip()
            for item in (capabilities.get("reusable_profile_ids") or capabilities.get("cdp_profile_ids") or [])
            if str(item or "").strip()
        }
    )
    binding_mode = str(
        capabilities.get("profile_binding_mode")
        or capabilities.get("cdp_profile_binding")
        or capabilities.get("browser_profile_binding")
        or ""
    ).strip().lower()
    supports_binding = capabilities.get("profile_reuse") is True or binding_mode in {
        "profile_id",
        "persistent_profile",
        "persistent_cdp_profile",
        "per_profile_cdp",
    }
    if not requested:
        return {
            "reusable": True,
            "code": "no_target_profiles",
            "message": "未请求特定 CDP profile 复用。",
            "requested_profile_ids": [],
            "declared_profile_ids": declared_profiles,
            "binding_mode": binding_mode,
        }
    if not supports_binding:
        return {
            "reusable": False,
            "code": "profile_binding_not_declared",
            "message": "browser-agent 当前只声明了 CDP 可用，未声明能按 profile_id 选择或复用指定浏览器 profile。",
            "requested_profile_ids": requested,
            "declared_profile_ids": declared_profiles,
            "binding_mode": binding_mode,
        }
    if not declared_profiles:
        return {
            "reusable": False,
            "code": "target_profiles_not_declared",
            "message": "browser-agent 声明支持 profile 复用，但未返回具体可复用的 profile_id 清单；请检查发布 agent 能力配置。",
            "requested_profile_ids": requested,
            "declared_profile_ids": declared_profiles,
            "binding_mode": binding_mode,
        }
    if declared_profiles:
        missing = sorted(set(requested) - set(declared_profiles))
        if missing:
            return {
                "reusable": False,
                "code": "target_profiles_not_declared",
                "message": "browser-agent 未声明这些目标 CDP profile 可复用：" + "、".join(missing),
                "requested_profile_ids": requested,
                "declared_profile_ids": declared_profiles,
                "binding_mode": binding_mode,
            }
    return {
        "reusable": True,
        "code": "reusable",
        "message": "browser-agent 声明支持按 profile_id 复用目标 CDP profile。",
        "requested_profile_ids": requested,
        "declared_profile_ids": declared_profiles,
        "binding_mode": binding_mode,
    }

_PLATFORM_ALIASES = {
    "抖音": "douyin",
    "douyin": "douyin",
    "小红书": "xiaohongshu",
    "xiaohongshu": "xiaohongshu",
    "rednote": "xiaohongshu",
    "b站": "bilibili",
    "哔哩哔哩": "bilibili",
    "bilibili": "bilibili",
    "快手": "kuaishou",
    "kuaishou": "kuaishou",
    "kwai": "kuaishou",
    "wechat-channels": "wechat-channels",
    "wechat_channels": "wechat-channels",
    "视频号": "wechat-channels",
    "微信视频号": "wechat-channels",
    "头条": "toutiao",
    "头条号": "toutiao",
    "toutiao": "toutiao",
    "youtube": "youtube",
    "yt": "youtube",
    "x": "x",
    "twitter": "x",
}


def normalize_publication_platform(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    compact = re.sub(r"\s+", "", text).lower().replace("_", "-")
    return _PLATFORM_ALIASES.get(compact) or (compact if compact in SUPPORTED_PUBLICATION_PLATFORMS else None)


def platform_label(platform: str) -> str:
    return SUPPORTED_PUBLICATION_PLATFORMS.get(platform, {}).get("label") or platform


def normalize_publication_credentials(value: Any) -> list[dict[str, Any]]:
    raw_items = value if isinstance(value, list) else []
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        platform = normalize_publication_platform(item.get("platform"))
        if not platform:
            continue
        credential_ref = str(item.get("credential_ref") or item.get("browser_profile") or "").strip()
        account_label = str(item.get("account_label") or item.get("account") or "").strip()
        status = str(item.get("status") or "unverified").strip().lower().replace("-", "_")
        adapter = _normalize_publication_adapter(item.get("adapter"))
        enabled = bool(item.get("enabled", True))
        browser_binding = normalize_publication_browser_binding(
            item.get("browser_binding")
            if isinstance(item.get("browser_binding"), dict)
            else item
        )
        browser_profile_id = (
            str(item.get("browser_profile_id") or "").strip()
            or str(browser_binding.get("profile_id") or "").strip()
            or credential_ref
            or account_label
        )
        key = (platform, credential_ref or account_label)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "id": str(item.get("id") or uuid.uuid4().hex),
                "platform": platform,
                "platform_label": platform_label(platform),
                "account_label": account_label or platform_label(platform),
                "credential_ref": credential_ref,
                "browser_profile_id": browser_profile_id,
                "browser_binding": browser_binding,
                "status": status,
                "enabled": enabled,
                "adapter": adapter,
                "verified_at": str(item.get("verified_at") or "").strip() or None,
                "notes": str(item.get("notes") or "").strip() or None,
                "last_error": str(item.get("last_error") or "").strip() or None,
            }
        )
    return normalized[:16]


def active_publication_credentials(profile: dict[str, Any] | None) -> list[dict[str, Any]]:
    creator_profile = profile.get("creator_profile") if isinstance(profile, dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile, dict) else {}
    credentials = normalize_publication_credentials(
        publishing.get("platform_credentials") if isinstance(publishing, dict) else []
    )
    return [
        item
        for item in credentials
        if item["enabled"]
        and item["status"] in PUBLISHABLE_CREDENTIAL_STATUSES
    ]


def _lookup_current_publication_credential(
    *,
    creator_profile_id: str,
    platform: str,
) -> dict[str, Any] | None:
    normalized_profile_id = str(creator_profile_id or "").strip()
    normalized_platform = normalize_publication_platform(platform)
    if not normalized_profile_id or not normalized_platform:
        return None
    try:
        from roughcut.avatar.materials import get_avatar_material_profile

        profile = get_avatar_material_profile(normalized_profile_id)
    except Exception:
        return None
    for credential in active_publication_credentials(profile):
        if normalize_publication_platform(credential.get("platform")) == normalized_platform:
            return dict(credential)
    return None


def _default_release_gate_browser_binding() -> dict[str, Any]:
    chrome_user_data_dir = Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "User Data"
    user_data_dir = str(
        os.getenv("ROUGHCUT_PUBLICATION_BROWSER_USER_DATA_DIR")
        or (chrome_user_data_dir if chrome_user_data_dir.exists() else (DEFAULT_PROJECT_ROOT / "data" / "runtime" / "publication-browser-profile-stable" / "chrome-user-data"))
    ).strip()
    profile_directory = str(os.getenv("ROUGHCUT_PUBLICATION_BROWSER_PROFILE_DIRECTORY") or "Profile 2").strip()
    return normalize_publication_browser_binding(
        {
            "browser": "chrome",
            "user_data_dir": user_data_dir,
            "profile_directory": profile_directory,
        }
    )


def _lookup_release_gate_publication_credential(
    *,
    creator_profile_id: str,
    platform: str,
) -> dict[str, Any] | None:
    normalized_profile_id = str(creator_profile_id or "").strip()
    normalized_platform = normalize_publication_platform(platform)
    if normalized_profile_id != "release-gate-profile" or not normalized_platform:
        return None
    browser_binding = _default_release_gate_browser_binding()
    browser_profile_id = str(browser_binding.get("profile_id") or "").strip()
    if not browser_profile_id:
        return None
    return {
        "id": f"release-gate-profile-{normalized_platform}",
        "platform": normalized_platform,
        "credential_ref": browser_profile_id,
        "account_label": f"{normalized_platform} release-gate",
        "browser_profile_id": browser_profile_id,
        "browser_binding": browser_binding,
        "status": "logged_in",
        "enabled": True,
        "adapter": CANONICAL_PUBLICATION_ADAPTER,
        "execution_mode": BROWSER_AGENT_EXECUTION_MODE,
    }


def _rehydrate_publication_attempt_runtime_metadata(
    attempt: PublicationAttempt,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    normalized_metadata = dict(metadata or {})
    creator_profile_id = str(
        normalized_metadata.get("creator_profile_id") or getattr(attempt, "creator_profile_id", "") or ""
    ).strip()
    credential = _lookup_current_publication_credential(
        creator_profile_id=creator_profile_id,
        platform=str(getattr(attempt, "platform", "") or ""),
    )
    if not credential:
        credential = _lookup_release_gate_publication_credential(
            creator_profile_id=creator_profile_id,
            platform=str(getattr(attempt, "platform", "") or ""),
        )
    if not credential:
        return normalized_metadata

    browser_binding = normalize_publication_browser_binding(
        credential.get("browser_binding")
        if isinstance(credential.get("browser_binding"), dict)
        else normalized_metadata.get("browser_binding")
    )
    browser_profile_id = str(
        credential.get("browser_profile_id")
        or browser_binding.get("profile_id")
        or normalized_metadata.get("browser_profile_id")
        or ""
    ).strip()
    credential_ref = str(credential.get("credential_ref") or normalized_metadata.get("credential_ref") or "").strip()
    account_label = str(credential.get("account_label") or normalized_metadata.get("account_label") or "").strip()

    if creator_profile_id:
        normalized_metadata["creator_profile_id"] = creator_profile_id
    if str(credential.get("id") or "").strip():
        normalized_metadata["credential_id"] = str(credential.get("id") or "").strip()
    if credential_ref:
        normalized_metadata["credential_ref"] = credential_ref
    if account_label:
        normalized_metadata["account_label"] = account_label
    if browser_profile_id:
        normalized_metadata["browser_profile_id"] = browser_profile_id
    if browser_binding:
        normalized_metadata["browser_binding"] = browser_binding
    normalized_metadata["session_binding"] = build_publication_browser_session_binding(
        platform=getattr(attempt, "platform", ""),
        creator_profile_id=creator_profile_id,
        browser_profile_id=browser_profile_id,
        credential_ref=credential_ref,
        account_label=account_label,
        browser_binding=browser_binding,
    )
    return normalized_metadata


def build_publication_plan(
    *,
    job: Any,
    render_output: Any | None,
    source_media_path: Any | None = None,
    platform_packaging: dict[str, Any] | None,
    creator_profile: dict[str, Any] | None,
    requested_platforms: list[str] | None = None,
    platform_options: dict[str, Any] | None = None,
    existing_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    blocked_reasons: list[str] = []
    warnings: list[str] = []
    manual_handoff_targets: list[dict[str, Any]] = []
    manual_handoff_reasons: list[str] = []
    if str(getattr(job, "status", "") or "") != "done":
        blocked_reasons.append("任务尚未完成，不能发布。")

    media_path = _resolve_render_media_path(render_output)
    if media_path is None:
        blocked_reasons.append("缺少本地成片文件，browser-agent 不能上传 remote-only media。")

    packages = _normalize_platform_packages(platform_packaging)
    title_audit_by_platform = _normalize_publication_title_audit_by_platform(platform_packaging)
    if not packages:
        blocked_reasons.append("缺少多平台发布文案包，请先完成 platform_package。")
    credentials = active_publication_credentials(creator_profile)
    if not credentials:
        blocked_reasons.append("创作者档案没有可发布的 browser-agent 登录凭据绑定。")

    requested = {
        platform
        for platform in (normalize_publication_platform(item) for item in (requested_platforms or []))
        if platform
    }
    credential_by_platform = {item["platform"]: item for item in credentials}
    options_by_platform = _normalize_publication_platform_options(platform_options)
    candidate_platforms = requested or STABLE_PUBLICATION_PLATFORM_SET
    target_platforms = sorted(
        candidate_platforms & set(credential_by_platform) & set(packages),
        key=_platform_sort_key,
    )
    targets: list[dict[str, Any]] = []
    preflight_blocked_count = 0
    title_audit_blocked_count = 0
    packaging_blocked_count = 0
    packaging_block_reasons: list[str] = []
    for platform in target_platforms:
        credential = credential_by_platform.get(platform)
        package = packages.get(platform) or {}
        title_audit = title_audit_by_platform.get(platform) or {}
        normalized_title = _truncate_publication_title(
            _package_primary_title(package),
            _publication_title_hard_limit(platform, title_audit),
        )
        publish_options = options_by_platform.get(platform, {})
        platform_overrides = (
            publish_options.get("platform_specific_overrides")
            if isinstance(publish_options.get("platform_specific_overrides"), dict)
            else {}
        )
        ignore_publish_ready_gate = bool(platform_overrides.get("ignore_publish_ready_gate"))
        if not credential:
            warnings.append(f"{platform_label(platform)} 没有可用登录凭据，已跳过。")
            continue
        if not _package_has_publish_copy(package):
            warnings.append(f"{platform_label(platform)} 文案包为空，已跳过。")
            continue
        declared = str(
            platform_overrides.get("declaration")
            or publish_options.get("declaration")
            or package.get("declaration")
            or ""
        ).strip()
        declaration = declared or platform_default_declaration(platform)
        category = _sanitize_publication_target_category(
            platform,
            publish_options.get("category") or _package_publish_option(package, "category"),
        )
        collection = publish_options.get("collection") or _package_publish_option(package, "collection")
        visibility_or_publish_mode = (
            publish_options.get("visibility_or_publish_mode")
            or _package_publish_option(package, "visibility_or_publish_mode")
        )
        scheduled_publish_at = (
            publish_options.get("scheduled_publish_at")
            or _normalize_scheduled_publish_at(_package_publish_option(package, "scheduled_publish_at"))
        )
        if platform == "youtube":
            visibility_or_publish_mode = _normalize_youtube_visibility_or_publish_mode(
                visibility_or_publish_mode,
                scheduled_publish_at=scheduled_publish_at,
            )
        merged_platform_overrides = (
            dict(package.get("platform_specific_overrides"))
            if isinstance(package.get("platform_specific_overrides"), dict)
            else {}
        )
        if isinstance(publish_options.get("platform_specific_overrides"), dict):
            merged_platform_overrides.update(publish_options.get("platform_specific_overrides") or {})
        collection = _resolve_publication_collection_target(
            platform=platform,
            collection=collection,
            platform_specific_overrides=merged_platform_overrides,
        )
        merged_platform_overrides = _normalize_publication_plan_platform_specific_overrides(
            platform=platform,
            collection=collection,
            platform_specific_overrides=merged_platform_overrides,
        )
        native_topics = _resolve_publication_native_topics(
            package=package,
            publish_options=publish_options,
            platform_specific_overrides=merged_platform_overrides,
        )
        package_cover_contract = {
            **package,
            "platform": platform,
            "key": platform,
        }
        primary_cover_path, cover_slots = _resolve_authoritative_publication_cover_contract(
            package_cover_contract,
            platform=platform,
            requested_media_path=str(source_media_path or media_path or ""),
        )
        copy_material = dict(package.get("copy_material")) if isinstance(package.get("copy_material"), dict) else {}
        copy_material.update(
            {
                "primary_title": normalized_title,
                "titles": [str(item).strip() for item in (package.get("titles") or []) if str(item).strip()],
                "body": str(package.get("description") or package.get("body") or "").strip(),
                "tags": [str(item).strip() for item in (package.get("tags") or []) if str(item).strip()],
                "cover_path": primary_cover_path,
                "cover_slots": [dict(item) for item in cover_slots],
                "declaration": declaration,
                "full_copy": str(package.get("full_copy") or "").strip(),
            }
        )
        if "source" not in copy_material:
            copy_material["source"] = "platform_packaging"
        if platform_manual_handoff_only(platform):
            reason = platform_manual_publish_reason(platform) or "当前平台仅支持人工登录后继续发布。"
            entry_url = platform_manual_publish_entry_url(platform)
            manual_handoff_reasons.append(f"{platform_label(platform)}：{reason}")
            warnings.append(
                f"{platform_label(platform)} 已切换为人工接管平台：{reason}"
                + (f" 登录入口：{entry_url}" if entry_url else "")
            )
            manual_handoff_targets.append(
                {
                    "platform": platform,
                    "platform_label": platform_label(platform),
                    "credential_id": credential["id"],
                    "credential_ref": credential["credential_ref"],
                    "browser_profile_id": str(
                        credential.get("browser_profile_id")
                        or credential.get("credential_ref")
                        or credential.get("account_label")
                        or platform
                    ),
                    "browser_binding": credential.get("browser_binding") if isinstance(credential.get("browser_binding"), dict) else {},
                    "account_label": credential["account_label"],
                    "adapter": _normalize_publication_adapter(credential.get("adapter")),
                    "execution_mode": str(
                        credential.get("execution_mode") or BROWSER_AGENT_EXECUTION_MODE
                    ).strip()
                    or BROWSER_AGENT_EXECUTION_MODE,
                    "login_url": entry_url,
                    "manual_reason": reason,
                    "content_kind": "video",
                    "title": normalized_title,
                    "body": str(package.get("description") or package.get("body") or "").strip(),
                    "declaration": declaration,
                    "tags": [str(item).strip() for item in (package.get("tags") or []) if str(item).strip()],
                    "titles": [str(item).strip() for item in (package.get("titles") or []) if str(item).strip()],
                    "description": str(package.get("description") or package.get("body") or "").strip(),
                    "cover_path": primary_cover_path,
                    "cover_slots": [dict(item) for item in cover_slots],
                    "full_copy": str(package.get("full_copy") or "").strip(),
                    "copy_material": copy_material,
                    "category": category,
                    "collection": collection,
                    "native_topics": list(native_topics),
                    "visibility_or_publish_mode": visibility_or_publish_mode,
                    "scheduled_publish_at": scheduled_publish_at,
                    "platform_specific_overrides": merged_platform_overrides,
                    "status": "manual_handoff",
                }
            )
            continue
        title_audit_block_reason = _publication_title_audit_block_reason(platform, title_audit)
        if title_audit_block_reason:
            title_audit_blocked_count += 1
            warnings.append(title_audit_block_reason)
            continue
        if not publication_packaging_entry_publish_ready(package):
            block_reasons = [str(item).strip() for item in (package.get("blocking_reasons") or []) if str(item).strip()]
            if not block_reasons:
                block_reasons = ["文案未通过发布预检。"]
            normalized_block_reasons = [str(item).strip() for item in block_reasons if str(item).strip()]
            packaging_blocked_count += 1
            if ignore_publish_ready_gate:
                warnings.append(
                    f"{platform_label(platform)} 已触发草稿恢复补偿，尽管文案未就绪（{'; '.join(normalized_block_reasons)}）仍继续执行。"
                )
            else:
                packaging_block_reasons.extend(normalized_block_reasons)
                for reason in normalized_block_reasons:
                    warnings.append(f"{platform_label(platform)} 未就绪：{reason}")
                continue
        preflight_block_reason = _publication_preflight_block_reason(platform, publish_options)
        if preflight_block_reason:
            preflight_blocked_count += 1
            warnings.append(preflight_block_reason)
            continue
        targets.append(
            {
                "platform": platform,
                "platform_label": platform_label(platform),
                "credential_id": credential["id"],
                "credential_ref": credential["credential_ref"],
                "browser_profile_id": str(
                    credential.get("browser_profile_id")
                    or credential.get("credential_ref")
                    or credential.get("account_label")
                    or platform
                ),
                "browser_binding": credential.get("browser_binding") if isinstance(credential.get("browser_binding"), dict) else {},
                "account_label": credential["account_label"],
                "adapter": _normalize_publication_adapter(credential.get("adapter")),
                "execution_mode": str(
                    credential.get("execution_mode") or BROWSER_AGENT_EXECUTION_MODE
                ).strip()
                or BROWSER_AGENT_EXECUTION_MODE,
                "content_kind": "video",
                "title": normalized_title,
                "body": str(package.get("description") or package.get("body") or "").strip(),
                "declaration": declaration,
                "tags": [str(item).strip() for item in (package.get("tags") or []) if str(item).strip()],
                "titles": [str(item).strip() for item in (package.get("titles") or []) if str(item).strip()],
                "description": str(package.get("description") or package.get("body") or "").strip(),
                "cover_path": primary_cover_path,
                "cover_slots": [dict(item) for item in cover_slots],
                "full_copy": str(package.get("full_copy") or "").strip(),
                "copy_material": copy_material,
                "category": category,
                "collection": collection,
                "native_topics": list(native_topics),
                "visibility_or_publish_mode": visibility_or_publish_mode,
                "scheduled_publish_at": scheduled_publish_at,
                "platform_specific_overrides": merged_platform_overrides,
                "status": "ready",
            }
        )

    manual_handoff_ready = False
    if credentials and packages and not targets:
        if manual_handoff_targets and not blocked_reasons:
            blocked_reasons.append(
                "以下平台已切换为人工登录/人工发布，不再进入自动一键发布："
                + "；".join(dict.fromkeys([str(item) for item in manual_handoff_reasons if str(item)]))
            )
            manual_handoff_ready = True
        elif packaging_blocked_count:
            blocked_reasons.append(
                "平台文案未就绪：" + "；".join(dict.fromkeys([str(item) for item in packaging_block_reasons if str(item)]))
            )
        elif preflight_blocked_count:
            blocked_reasons.append("所有候选平台都未通过发布前页面验证。")
        elif title_audit_blocked_count:
            blocked_reasons.append("所有候选平台都未通过发布文案质量门。")
        else:
            blocked_reasons.append("当前创作者凭据与文案包平台没有交集。")

    plan_status = "manual_handoff" if manual_handoff_ready else ("ready" if not blocked_reasons and targets else "blocked")
    return {
        "job_id": str(getattr(job, "id", "")),
        "status": plan_status,
        "publish_ready": not blocked_reasons and bool(targets),
        "manual_handoff_ready": manual_handoff_ready,
        "blocked_reasons": blocked_reasons,
        "warnings": warnings,
        "adapter": (
            _normalize_publication_adapter((targets or [{}])[0].get("adapter"))
            if targets
            else _normalize_publication_adapter(CANONICAL_PUBLICATION_ADAPTER)
        ),
        "content_kind": "video",
        "publication_guard": {
            "ready": not blocked_reasons and bool(targets),
            "review_gate_blocked": False,
            "formal_plan": {
                "ready": str(getattr(job, "status", "") or "") == "done",
                "reasons": [] if str(getattr(job, "status", "") or "") == "done" else ["job_not_done"],
            },
            "release_payload": {
                "ready": bool(media_path and packages),
                "reasons": [] if media_path and packages else ["local_media_or_platform_package_missing"],
            },
        },
        "creator_profile_id": str((creator_profile or {}).get("id") or ""),
        "creator_profile_name": str((creator_profile or {}).get("display_name") or ""),
        "media_path": str(media_path) if media_path else None,
        "source_media_path": str(source_media_path or "").strip() or (str(media_path) if media_path else None),
        "targets": targets,
        "manual_handoff_targets": manual_handoff_targets,
        "existing_attempts": list(existing_attempts or [])[:20],
    }


def publication_plan_is_manual_handoff_ready(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    if publication_plan_status(plan) != "manual_handoff":
        return False
    if publication_plan_is_publishable(plan):
        return False
    if plan.get("targets"):
        return False
    return bool(plan.get("manual_handoff_targets"))


def publication_plan_status(plan: dict[str, Any] | None) -> str:
    if not isinstance(plan, dict):
        return "blocked"
    status = str(plan.get("status") or "").strip().lower()
    has_targets = bool(plan.get("targets"))
    if status == "manual_handoff":
        return "manual_handoff"
    if status in {"ready", "passed"} and has_targets:
        return "ready"
    if status in {"blocked", "failed"}:
        return "blocked"
    has_manual_handoff_targets = bool(plan.get("manual_handoff_targets"))
    if bool(plan.get("manual_handoff_ready")) and not has_targets:
        return "manual_handoff"
    if has_manual_handoff_targets and not has_targets:
        return "manual_handoff"
    if any(str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip()):
        return "blocked"
    if plan.get("publish_ready") is True and has_targets:
        return "ready"
    return "blocked"


def _sanitize_publication_target_category(platform: str, category: Any) -> str | None:
    text = str(category or "").strip()
    if not text:
        return None
    normalized_platform = str(platform or "").strip().lower()
    if normalized_platform != "youtube":
        return text
    lowered = text.casefold()
    if lowered in _YOUTUBE_CATEGORY_PLACEHOLDER_VALUES:
        return None
    if re.search(r"语言|字幕|caption|subtitle|内容检测|创收|信息中心|数据分析|社区|自定义|音频库|发送反馈", text, re.IGNORECASE):
        return None
    if re.search(r"(信息中心|内容|数据分析|社区|字幕|内容检测|创收|自定义|音频库|设置|发送反馈).+(信息中心|内容|数据分析|社区|字幕|内容检测|创收|自定义|音频库|设置|发送反馈)", text):
        return None
    return text


def _normalize_youtube_visibility_or_publish_mode(
    value: Any,
    *,
    scheduled_publish_at: Any = None,
) -> str | None:
    text = str(value or "").strip()
    scheduled = bool(str(scheduled_publish_at or "").strip())
    if not text:
        return "scheduled" if scheduled else "public"
    lowered = text.casefold()
    if "schedule" in lowered or "scheduled" in lowered or "安排" in text or "预约" in text or "定时" in text:
        return "scheduled"
    if "unlisted" in lowered or "不公开" in text:
        return "unlisted"
    if "private" in lowered or "私享" in text or "私密" in text:
        return "private"
    if "public" in lowered or "公开" in text:
        return "public"
    return text


def publication_plan_is_publishable(plan: dict[str, Any] | None) -> bool:
    if not isinstance(plan, dict):
        return False
    if publication_plan_status(plan) != "ready":
        return False
    if not bool(plan.get("targets")):
        return False
    if any(str(item).strip() for item in (plan.get("blocked_reasons") or []) if str(item).strip()):
        return False
    if bool(plan.get("manual_handoff_ready")) and not bool(plan.get("targets")):
        return False
    if plan.get("publish_ready") is False:
        return False
    return True


def _merge_platform_specific_overrides_with_current_target(
    current_overrides: Any,
    recovery_overrides: Any,
) -> dict[str, Any]:
    merged = dict(recovery_overrides or {}) if isinstance(recovery_overrides, dict) else {}
    if isinstance(current_overrides, dict):
        # The current plan/target is the source of truth. Historical recovery hints
        # may fill gaps, but they must not override explicit recovery intent.
        merged.update(current_overrides)
    return merged


async def submit_publication_attempts(session: AsyncSession, plan: dict[str, Any]) -> dict[str, Any]:
    if not publication_plan_is_publishable(plan):
        return {**plan, "created_attempts": [], "skipped_targets": []}

    created: list[dict[str, Any]] = []
    skipped_targets: list[dict[str, Any]] = []
    plan_job_id = str(plan.get("job_id") or "")
    plan_creator_profile_id = str(plan.get("creator_profile_id") or "").strip()
    requested_platforms = sorted(
        {
            str(target.get("platform") or "").strip().lower()
            for target in (plan.get("targets") or [])
            if str(target.get("platform") or "").strip()
        }
    )
    narrow_candidate_conditions: list[Any] = [PublicationAttempt.content_id == plan_job_id]
    if plan_creator_profile_id and requested_platforms:
        narrow_candidate_conditions.append(
            (PublicationAttempt.creator_profile_id == plan_creator_profile_id)
            & (PublicationAttempt.platform.in_(requested_platforms))
        )
    existing_attempt_stmt = select(PublicationAttempt).where(or_(*narrow_candidate_conditions))
    existing_attempt_rows = await session.execute(existing_attempt_stmt)
    broad_history_attempts: list[PublicationAttempt] = []
    if requested_platforms:
        broad_history_stmt = select(PublicationAttempt).where(
            (PublicationAttempt.platform.in_(requested_platforms))
            & (
                PublicationAttempt.status.in_(
                    sorted(PUBLICATION_ACTIVE_STATUSES | PUBLICATION_SUCCESS_STATUSES)
                )
            )
        )
        broad_history_rows = await session.execute(broad_history_stmt)
        broad_history_attempts = list(broad_history_rows.scalars().all())
    attempts_by_fingerprint: dict[str, list[PublicationAttempt]] = {}
    attempts_by_dedupe_signature: dict[str, list[PublicationAttempt]] = {}
    attempts_by_logical_signature: dict[str, list[PublicationAttempt]] = {}
    attempts_by_platform: dict[str, list[PublicationAttempt]] = {}
    for attempt in existing_attempt_rows.scalars().all():
        fingerprint = str(attempt.semantic_fingerprint or "").strip()
        if not fingerprint:
            fingerprint = _extract_publication_content_signature(
                attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
            )
        if fingerprint:
            attempts_by_fingerprint.setdefault(fingerprint, []).append(attempt)
        dedupe_signature = _extract_publication_dedupe_signature(
            attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
        )
        if dedupe_signature:
            attempts_by_dedupe_signature.setdefault(dedupe_signature, []).append(attempt)
        logical_signature = _extract_publication_logical_signature(
            attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
        )
        if logical_signature:
            attempts_by_logical_signature.setdefault(logical_signature, []).append(attempt)
        platform = str(attempt.platform or "").strip().lower()
        attempts_by_platform.setdefault(platform, []).append(attempt)
    broad_attempts_by_logical_signature: dict[str, list[PublicationAttempt]] = {}
    for attempt in broad_history_attempts:
        logical_signature = _extract_publication_logical_signature(
            attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
        )
        if not logical_signature:
            continue
        broad_attempts_by_logical_signature.setdefault(logical_signature, []).append(attempt)
    for target in plan.get("targets") or []:
        request_payload = _build_request_payload(plan=plan, target=target)
        request_plan_signature = _extract_publication_plan_signature(request_payload)
        raw_target_overrides = (
            target.get("platform_specific_overrides")
            if isinstance(target.get("platform_specific_overrides"), dict)
            else {}
        )
        force_republish = bool(
            target.get("force_republish")
            or target.get("force_republish_now")
            or target.get("force_publish")
            or target.get("allow_duplicate")
            or bool(raw_target_overrides.get("force_republish"))
            or bool(raw_target_overrides.get("allow_duplicate_publication"))
        )
        current_page_scoped_attempt = bool(
            raw_target_overrides.get("verification_only_current_page")
            or raw_target_overrides.get("repair_only_current_page")
            or raw_target_overrides.get("prepublish_only_current_page")
            or raw_target_overrides.get("prepare_only_current_page")
        )
        is_recovery_target = _is_publication_recovery_target(target)
        target_adapter = _normalize_publication_adapter(target.get("adapter"))
        target_execution_mode = str(target.get("execution_mode") or BROWSER_AGENT_EXECUTION_MODE).strip() or BROWSER_AGENT_EXECUTION_MODE
        target_collection = target.get("collection")
        target_collection_name = ""
        if isinstance(target_collection, dict):
            target_collection_name = str(target_collection.get("name") or "").strip()
        if not target_collection_name:
            target_collection_name = str(target.get("collection_name") or "").strip()
        fingerprint = _semantic_fingerprint(
            job_id=str(plan.get("job_id") or ""),
            platform=str(target.get("platform") or ""),
            adapter=target_adapter,
            title=str(target.get("title") or ""),
            body=str(target.get("body") or ""),
            tags=list(dict.fromkeys([str(item).strip().lstrip("#") for item in (target.get("tags") or []) if str(item).strip()])),
            collection_name=target_collection_name,
            scheduled_publish_at=str(target.get("scheduled_publish_at") or "").strip(),
            media_path=str(plan.get("media_path") or ""),
        )
        dedupe_signature = _extract_publication_dedupe_signature(request_payload)
        logical_signature = _extract_publication_logical_signature(request_payload)
        existing_attempts_for_fingerprint = attempts_by_fingerprint.get(fingerprint) or []
        existing_attempts_for_dedupe = attempts_by_dedupe_signature.get(dedupe_signature) or []
        existing_attempts_for_logical = attempts_by_logical_signature.get(logical_signature) or []
        history_attempts_for_logical = broad_attempts_by_logical_signature.get(logical_signature) or []
        has_terminal_success = False
        if not current_page_scoped_attempt:
            has_terminal_success = any(
                str(item.status or "").strip().lower() in {"published", "draft_created", "scheduled_pending"}
                for item in [*existing_attempts_for_dedupe, *existing_attempts_for_logical, *history_attempts_for_logical]
                if item
            )
        if has_terminal_success and not force_republish:
            skipped_targets.append(
                {
                    "platform": str(target.get("platform") or "").strip().lower(),
                    "reason": "terminal_success_exists",
                }
            )
            continue
        safe_active_receipt_rebind = False
        active_attempt = None
        if not current_page_scoped_attempt:
            active_attempt = next(
                (
                    item
                    for item in sorted(
                        [*existing_attempts_for_dedupe, *existing_attempts_for_logical, *history_attempts_for_logical],
                        key=lambda current: (current.updated_at or current.created_at or _utc_now()),
                        reverse=True,
                    )
                    if str(item.status or "").strip().lower() in PUBLICATION_ACTIVE_STATUSES
                    and not _is_retry_queued_publication_attempt(item)
                ),
                None,
            )
        force_new_attempt_for_active_recovery = False
        if active_attempt is not None and str(active_attempt.status or "").strip().lower() in PUBLICATION_ACTIVE_STATUSES:
            active_override_mode = str(raw_target_overrides.get("recovery_mode") or "").strip().lower()
            safe_active_receipt_rebind = (
                is_recovery_target
                and active_override_mode == "receipt_rebind"
            )
            force_new_attempt_for_active_recovery = bool(
                force_republish
                or raw_target_overrides.get("clear_draft_context")
                or (
                    raw_target_overrides.get("force_publish_page_refresh")
                    and not safe_active_receipt_rebind
                )
            )
            force_new_attempt_for_active_recovery = (
                force_new_attempt_for_active_recovery
                or active_override_mode in {"draft_reset", "clear_draft", "auto_recover"}
                or (
                    is_recovery_target
                    and active_override_mode not in {"", "none", "receipt_rebind"}
                )
            )
        if active_attempt is not None and not force_republish and not safe_active_receipt_rebind:
            skipped_targets.append(
                {
                    "platform": str(target.get("platform") or "").strip().lower(),
                    "reason": "active_attempt_exists",
                    "attempt_id": str(active_attempt.id),
                    "status": str(active_attempt.status or "").strip().lower(),
                    "run_status": str(active_attempt.run_status or "").strip().lower(),
                    "error_code": str(active_attempt.error_code or "").strip().lower(),
                }
            )
            continue
        if force_new_attempt_for_active_recovery:
            active_attempt = None
        reusable_attempt = None
        if not current_page_scoped_attempt:
            reusable_attempt = next(
                (
                    item
                    for item in sorted(
                        existing_attempts_for_fingerprint or existing_attempts_for_dedupe or existing_attempts_for_logical,
                        key=lambda current: (current.updated_at or current.created_at or _utc_now()),
                        reverse=True,
                    )
                    if (
                        str(item.status or "").strip().lower() in (PUBLICATION_TERMINAL_STATUSES - {"published", "draft_created"})
                        or _is_retry_queued_publication_attempt(item)
                    )
                ),
                None,
            )
        if active_attempt is not None and (force_republish or is_recovery_target):
            reusable_attempt = active_attempt
        target_platform = str(target.get("platform") or "").strip().lower()
        platform_recovery_attempt = None
        platform_recovery_overrides = {}
        platform_recovery_state = None
        if target_platform and is_recovery_target and not current_page_scoped_attempt:
            platform_attempts_for_recovery = _select_recovery_candidate_attempts_for_platform(
                attempts_by_platform.get(target_platform, [])
            )
            if platform_attempts_for_recovery:
                platform_recovery_attempt = platform_attempts_for_recovery[0]
                platform_recovery_overrides, platform_recovery_state = _build_platform_recovery_overrides(
                    attempt=platform_recovery_attempt,
                    request_plan_signature=request_plan_signature,
                )
        if reusable_attempt is not None:
            reusable_recovery_overrides, reusable_recovery_state = _build_platform_recovery_overrides(
                attempt=reusable_attempt,
                request_plan_signature=request_plan_signature,
            )
            if not reusable_recovery_overrides and platform_recovery_overrides:
                reusable_recovery_overrides = dict(platform_recovery_overrides)
            if reusable_recovery_state is None:
                reusable_recovery_state = platform_recovery_state
            request_payload["platform_specific_overrides"] = _merge_platform_specific_overrides_with_current_target(
                request_payload.get("platform_specific_overrides"),
                reusable_recovery_overrides,
            )
            if reusable_recovery_overrides or reusable_recovery_state:
                request_payload["publication_recovery_state"] = {
                    **(reusable_recovery_state or {}),
                    "schema_version": PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION,
                    "plan_signature": request_plan_signature,
                    "carry_over_from_attempt_id": str(reusable_attempt.id),
                }
            attempt = reusable_attempt
            is_recovery = _is_publication_recovery_target(target) or bool(reusable_recovery_overrides) or bool(reusable_recovery_state)
            adapter_label = _publication_adapter_display_name(target_adapter)
            is_scheduled = bool(target.get("scheduled_publish_at"))
            operator_suffix = " 并清理草稿上下文" if is_recovery else ""
            attempt.attempt_number = int(attempt.attempt_number or 0) + 1
            attempt.content_id = str(plan.get("job_id") or "")
            attempt.job_id = uuid.UUID(str(plan.get("job_id") or ""))
            attempt.creator_profile_id = str(plan.get("creator_profile_id") or "")
            attempt.creator_profile_name = str(plan.get("creator_profile_name") or "")
            attempt.platform = str(target.get("platform") or "")
            attempt.platform_label = str(target.get("platform_label") or "")
            attempt.account_label = str(target.get("account_label") or "")
            attempt.credential_id = str(target.get("credential_id") or "")
            attempt.adapter = target_adapter
            attempt.semantic_fingerprint = fingerprint
            attempt.idempotency_key = f"{str(plan.get('job_id'))}:{str(target.get('platform'))}:{attempt.id}"
            attempt.status = "queued"
            attempt.run_status = "awaiting_browser_agent"
            attempt.execution_mode = target_execution_mode
            attempt.retry_count = 0
            attempt.max_retries = 3
            attempt.error_code = None
            attempt.error_message = None
            attempt.external_receipt_id = None
            attempt.external_post_id = None
            attempt.external_url = None
            attempt.provider_task_id = None
            attempt.provider_execution_id = None
            attempt.provider_status = None
            attempt.response_payload = None
            attempt.request_payload = request_payload
            attempt.scheduled_at = _parse_datetime(target.get("scheduled_publish_at"))
            attempt.submitted_at = None
            attempt.published_at = None
            attempt.next_retry_at = None
            attempt.operator_summary = (
                f"已重新排队 {adapter_label}{operator_suffix}，等待运行器认领。"
                if not is_scheduled
                else f"已重新排队 {adapter_label}{operator_suffix} 预约发布任务，等待运行器认领。"
            )
            attempt.run_status = "retry_scheduled" if is_recovery else attempt.run_status
            if is_recovery:
                attempt.error_code = "auto_recover_retry"
                attempt.error_message = "自动恢复重试：清理草稿上下文后重试发布。"
            attempt_id = attempt.id
        else:
            attempt_id = uuid.uuid4().hex
            is_recovery = (
                _is_publication_recovery_target(target)
                or bool(platform_recovery_overrides)
                or bool(platform_recovery_state)
            )
            request_payload["platform_specific_overrides"] = _merge_platform_specific_overrides_with_current_target(
                request_payload.get("platform_specific_overrides"),
                platform_recovery_overrides,
            )
            if is_recovery and platform_recovery_state:
                request_payload["publication_recovery_state"] = platform_recovery_state
                request_payload["publication_recovery_state"]["schema_version"] = PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION
                request_payload["publication_recovery_state"]["plan_signature"] = request_plan_signature
                if platform_recovery_attempt is not None:
                    request_payload["publication_recovery_state"]["carry_over_from_attempt_id"] = str(platform_recovery_attempt.id)
            attempt = PublicationAttempt(
                id=attempt_id,
                content_id=str(plan.get("job_id") or ""),
                job_id=uuid.UUID(str(plan.get("job_id") or "")),
                creator_profile_id=str(plan.get("creator_profile_id") or ""),
                creator_profile_name=str(plan.get("creator_profile_name") or ""),
                platform=str(target.get("platform") or ""),
                platform_label=str(target.get("platform_label") or ""),
                account_label=str(target.get("account_label") or ""),
                credential_id=str(target.get("credential_id") or ""),
                adapter=target_adapter,
                status="queued",
                run_status="awaiting_browser_agent",
                attempt_number=1,
                retry_count=0,
                max_retries=3,
                execution_mode=target_execution_mode,
                content_kind="video",
                request_payload=request_payload,
                response_payload=None,
                scheduled_at=_parse_datetime(target.get("scheduled_publish_at")),
                semantic_fingerprint=fingerprint,
                idempotency_key=f"{str(plan.get('job_id'))}:{str(target.get('platform'))}:{attempt_id}",
            operator_summary=(
                f"已创建 {_publication_adapter_display_name(target_adapter)} 预约发布任务，等待运行器认领。"
                if target.get("scheduled_publish_at")
                else f"已创建 {_publication_adapter_display_name(target_adapter)} 发布任务，等待运行器认领。"
            ),
            )
            session.add(attempt)
        run = PublicationAttemptRun(
            attempt_id=attempt_id,
            content_id=str(plan.get("job_id") or ""),
            platform=str(target.get("platform") or ""),
            adapter=target_adapter,
            execution_mode=target_execution_mode or BROWSER_AGENT_EXECUTION_MODE,
            content_kind="video",
            consumer_id="",
            attempt_number=int(attempt.attempt_number or 1),
            status="queued",
            phase="materialized",
            metadata_json={
                "contract": _resolve_publication_adapter_publication_contract(target_adapter),
                "reconcileMode": "browser_agent_task_poll",
            },
        )
        session.add(run)
        await session.flush()
        if reusable_attempt is not None:
            await session.refresh(attempt)
        created.append(serialize_publication_attempt(attempt, runs=[run]))
        attempts_by_fingerprint.setdefault(fingerprint, []).append(attempt)
        if dedupe_signature:
            attempts_by_dedupe_signature.setdefault(dedupe_signature, []).append(attempt)
        if logical_signature:
            attempts_by_logical_signature.setdefault(logical_signature, []).append(attempt)
        attempts_by_platform.setdefault(str(target.get("platform") or "").strip().lower(), []).append(attempt)
    existing_attempts = await list_publication_attempts(session, job_id=str(plan.get("job_id") or ""))
    return {
        **plan,
        "status": "queued" if created else plan.get("status"),
        "created_attempts": created,
        "skipped_targets": skipped_targets,
        "existing_attempts": existing_attempts[:20],
    }


async def claim_publication_attempts(
    session: AsyncSession,
    *,
    limit: int = 5,
    worker_id: str = "",
    lease_seconds: int = 300,
    content_ids: list[str] | None = None,
) -> list[PublicationAttempt]:
    now = _utc_now()
    normalized_content_ids = [
        str(item or "").strip()
        for item in (content_ids or [])
        if str(item or "").strip()
    ]
    claim_conditions = [
        PublicationAttempt.status == "queued",
        or_(PublicationAttempt.next_retry_at.is_(None), PublicationAttempt.next_retry_at <= now),
    ]
    if normalized_content_ids:
        claim_conditions.insert(1, PublicationAttempt.content_id.in_(normalized_content_ids))
    stmt = (
        select(PublicationAttempt)
        .where(*claim_conditions)
        .order_by(PublicationAttempt.created_at.asc(), PublicationAttempt.id.asc())
        .limit(max(1, int(limit or 1)))
        .with_for_update(skip_locked=True)
    )
    result = await session.execute(stmt)
    attempts = result.scalars().all()
    claimed: list[PublicationAttempt] = []
    for attempt in attempts:
        attempt.status = "claimed"
        attempt.run_status = "claimed"
        attempt.error_code = None
        attempt.error_message = None
        adapter_label = _publication_adapter_display_name(attempt.adapter)
        attempt.operator_summary = f"发布任务已被 worker 认领，准备提交 {adapter_label}。"
        run = PublicationAttemptRun(
            attempt_id=attempt.id,
            content_id=attempt.content_id,
            platform=attempt.platform,
            adapter=attempt.adapter,
            execution_mode=attempt.execution_mode or BROWSER_AGENT_EXECUTION_MODE,
            content_kind=attempt.content_kind or "video",
            consumer_id=str(worker_id or ""),
            attempt_number=max(1, int(attempt.attempt_number or 1)),
            status="claimed",
            phase="claim",
            started_at=now,
            heartbeat_at=now,
            lease_expires_at=now + timedelta(seconds=max(30, int(lease_seconds or 300))),
            metadata_json={
                "contract": _resolve_publication_adapter_publication_contract(attempt.adapter),
                "reconcileMode": "browser_agent_task_poll",
            },
        )
        session.add(run)
        claimed.append(attempt)
    if claimed:
        await session.flush()
    return claimed


async def submit_publication_attempt_to_browser_agent(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    run = await _latest_publication_run(session, attempt.id)
    try:
        task_payload = build_browser_agent_task_payload_from_attempt(attempt)
    except ValueError as exc:
        _mark_publication_attempt_failed(
            attempt,
            run,
            code="publication_payload_invalid",
            message=str(exc),
            retryable=False,
        )
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}

    try:
        response_payload = await _browser_agent_request_json(
            "POST",
            "/tasks",
            base_url=browser_agent_base_url,
            auth_token=auth_token,
            json_payload=task_payload,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    except Exception as exc:
        _mark_publication_attempt_failed(
            attempt,
            run,
            code="browser_agent_submit_failed",
            message=str(exc),
            retryable=True,
        )
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}

    task = _extract_browser_agent_task(response_payload)
    provider_task_id = str(task.get("task_id") or task.get("id") or attempt.id).strip() or attempt.id
    now = _utc_now()
    attempt.provider_task_id = provider_task_id
    attempt.provider_execution_id = str(task.get("execution_id") or task.get("run_id") or "").strip() or None
    attempt.provider_status = str(task.get("status") or "submitted").strip() or "submitted"
    attempt.response_payload = response_payload
    attempt.status = "submitted"
    attempt.run_status = "submitted"
    attempt.submitted_at = now
    attempt.next_retry_at = None
    attempt.adapter = attempt.adapter or CANONICAL_PUBLICATION_ADAPTER
    attempt.operator_summary = f"已提交 {_publication_adapter_display_name(attempt.adapter)}，等待平台侧执行结果。"
    if run is not None:
        run.status = "submitted"
        run.phase = "submitted"
        run.heartbeat_at = now
        run.provider_task_id = provider_task_id
        run.provider_execution_id = attempt.provider_execution_id
        run.provider_status = attempt.provider_status
        run.result_json = response_payload
    await _apply_browser_agent_task_state(attempt, run, task, response_payload=response_payload)
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "provider_task_id": provider_task_id}


async def reconcile_publication_attempt_with_browser_agent(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    provider_task_id = str(attempt.provider_task_id or attempt.id).strip()
    run = await _latest_publication_run(session, attempt.id)
    try:
        response_payload = await _browser_agent_request_json(
            "GET",
            f"/tasks/{provider_task_id}",
            base_url=browser_agent_base_url,
            auth_token=auth_token,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    except Exception as exc:
        if _browser_agent_task_missing(exc):
            now = _utc_now()
            attempt.error_code = "browser_agent_task_missing"
            adapter_label = _publication_adapter_display_name(attempt.adapter)
            attempt.error_message = (
                f"{adapter_label} 运行态里找不到该 task_id。通常是执行器重启后 task 丢失，"
                "已立即回退为待重新提交。"
            )
            attempt.status = "queued"
            attempt.run_status = "awaiting_browser_agent"
            attempt.next_retry_at = None
            attempt.operator_summary = f"{adapter_label} 任务丢失，已回退为待重新提交。"
            attempt.provider_status = "task_missing"
            attempt.provider_task_id = None
            attempt.provider_execution_id = None
            attempt.response_payload = None
            if run is not None:
                run.status = "retry_scheduled"
                run.phase = "reconcile"
                run.heartbeat_at = now
                run.completed_at = now
                run.error_message = attempt.error_message
            await session.flush()
            return {"attempt_id": attempt.id, "status": attempt.status, "error": attempt.error_message}
        if run is not None:
            run.status = "poll_failed"
            run.phase = "reconcile"
            run.heartbeat_at = _utc_now()
            run.error_message = str(exc)
        attempt.run_status = "poll_failed"
        attempt.operator_summary = f"{_publication_adapter_display_name(attempt.adapter)} 对账失败，等待下次轮询：{exc}"
        await session.flush()
        return {"attempt_id": attempt.id, "status": attempt.status, "error": str(exc)}
    task = _extract_browser_agent_task(response_payload)
    await _apply_browser_agent_task_state(attempt, run, task, response_payload=response_payload)
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "provider_status": attempt.provider_status}


def _extract_browser_agent_task_identity(
    task: dict[str, Any],
    *,
    response_payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    payload = response_payload if isinstance(response_payload, dict) else {}
    raw_task = task if isinstance(task, dict) else {}
    result = raw_task.get("result") if isinstance(raw_task.get("result"), dict) else {}
    candidate_sources = [raw_task, result, payload]
    normalized: dict[str, str] = {
        "task_id": "",
        "attempt_id": "",
        "content_id": "",
        "carry_over_from_attempt_id": "",
        "content_signature": "",
        "recovery_mode": "",
        "platform": "",
    }
    for source in candidate_sources:
        if not isinstance(source, dict):
            continue
        if not normalized["task_id"]:
            normalized["task_id"] = str(source.get("task_id") or source.get("id") or "").strip()
        if not normalized["attempt_id"]:
            normalized["attempt_id"] = str(source.get("attempt_id") or "").strip()
        if not normalized["content_id"]:
            normalized["content_id"] = str(
                source.get("content_id") or source.get("job_id") or ""
            ).strip()
        if not normalized["carry_over_from_attempt_id"]:
            normalized["carry_over_from_attempt_id"] = str(
                source.get("carry_over_from_attempt_id") or ""
            ).strip()
        if not normalized["recovery_mode"]:
            normalized["recovery_mode"] = str(source.get("recovery_mode") or "").strip()
        if not normalized["platform"]:
            normalized["platform"] = str(source.get("platform") or "").strip().lower()
        if not normalized["content_signature"]:
            normalized["content_signature"] = _extract_publication_content_signature(source)
    return normalized


async def _resolve_publication_attempt_from_browser_agent_identity(
    session: AsyncSession,
    identity: dict[str, str],
) -> tuple[PublicationAttempt | None, str]:
    direct_ids = [
        str(identity.get("attempt_id") or "").strip(),
        str(identity.get("carry_over_from_attempt_id") or "").strip(),
    ]
    for attempt_id in [item for item in direct_ids if item]:
        attempt = await session.get(PublicationAttempt, attempt_id)
        if attempt is not None:
            matched_by = "attempt_id" if attempt_id == direct_ids[0] else "carry_over_from_attempt_id"
            return attempt, matched_by

    provider_task_id = str(identity.get("task_id") or "").strip()
    if provider_task_id:
        result = await session.execute(
            select(PublicationAttempt)
            .where(PublicationAttempt.provider_task_id == provider_task_id)
            .order_by(PublicationAttempt.updated_at.desc(), PublicationAttempt.created_at.desc())
            .limit(1)
        )
        attempt = result.scalars().first()
        if attempt is not None:
            return attempt, "provider_task_id"

    content_id = str(identity.get("content_id") or "").strip()
    platform = str(identity.get("platform") or "").strip().lower()
    if content_id:
        candidate_stmt = select(PublicationAttempt).where(PublicationAttempt.content_id == content_id)
        if platform:
            candidate_stmt = candidate_stmt.where(PublicationAttempt.platform == platform)
        candidate_stmt = candidate_stmt.order_by(
            PublicationAttempt.updated_at.desc(),
            PublicationAttempt.created_at.desc(),
        ).limit(25)
        result = await session.execute(candidate_stmt)
        candidates = list(result.scalars().all())
        signature = str(identity.get("content_signature") or "").strip()
        if signature:
            for attempt in candidates:
                request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
                if _extract_publication_content_signature(request_payload) == signature:
                    return attempt, "content_signature"
        if len(candidates) == 1:
            return candidates[0], "content_id_unique"
    return None, ""


async def reconcile_publication_attempt_from_browser_agent_payload(
    session: AsyncSession,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response_payload = payload if isinstance(payload, dict) else {}
    task = _extract_browser_agent_task(response_payload)
    identity = _extract_browser_agent_task_identity(task, response_payload=response_payload)
    attempt, matched_by = await _resolve_publication_attempt_from_browser_agent_identity(
        session,
        identity,
    )
    if attempt is None:
        return {
            "status": "not_found",
            "matched_by": matched_by or None,
            "task_id": identity.get("task_id") or None,
            "attempt_id": identity.get("attempt_id") or None,
            "content_id": identity.get("content_id") or None,
            "content_signature": identity.get("content_signature") or None,
        }
    run = await _latest_publication_run(session, attempt.id)
    await _apply_browser_agent_task_state(attempt, run, task, response_payload=response_payload)
    await session.flush()
    return {
        "status": attempt.status,
        "matched_by": matched_by,
        "attempt_id": attempt.id,
        "provider_task_id": attempt.provider_task_id,
        "external_receipt_id": attempt.external_receipt_id,
    }


async def submit_publication_attempt_for_adapter(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    adapter = _normalize_publication_adapter(attempt.adapter)
    if adapter == X_LINK_SHARE_PUBLICATION_ADAPTER or adapter == CANONICAL_PUBLICATION_ADAPTER:
        return await submit_publication_attempt_to_browser_agent(
            session,
            attempt,
            browser_agent_base_url=browser_agent_base_url,
            auth_token=auth_token,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    _mark_publication_attempt_failed(
        attempt,
        await _latest_publication_run(session, attempt.id),
        code="publication_adapter_unsupported",
        message=f"不支持的发布适配器：{adapter}",
        retryable=False,
    )
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "error": f"不支持的发布适配器：{adapter}"}


async def reconcile_publication_attempt_for_adapter(
    session: AsyncSession,
    attempt: PublicationAttempt,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    adapter = _normalize_publication_adapter(attempt.adapter)
    if adapter == X_LINK_SHARE_PUBLICATION_ADAPTER or adapter == CANONICAL_PUBLICATION_ADAPTER:
        return await reconcile_publication_attempt_with_browser_agent(
            session,
            attempt,
            browser_agent_base_url=browser_agent_base_url,
            auth_token=auth_token,
            http_client=http_client,
            request_timeout_sec=request_timeout_sec,
        )
    _mark_publication_attempt_failed(
        attempt,
        await _latest_publication_run(session, attempt.id),
        code="publication_adapter_unsupported",
        message=f"不支持的发布适配器：{adapter}",
        retryable=False,
    )
    await session.flush()
    return {"attempt_id": attempt.id, "status": attempt.status, "error": f"不支持的发布适配器：{adapter}"}


async def run_publication_worker_once(
    session: AsyncSession,
    *,
    browser_agent_base_url: str,
    auth_token: str = "",
    worker_id: str = "",
    limit: int = 5,
    lease_seconds: int = 300,
    request_timeout_sec: int = 60,
    http_client: Any | None = None,
    target_content_ids: list[str] | None = None,
) -> dict[str, Any]:
    normalized_content_ids = [
        str(item or "").strip()
        for item in (target_content_ids or [])
        if str(item or "").strip()
    ]
    if normalized_content_ids:
        # Prefer deterministic and isolated execution for a known job set (例如：一次发布回归门禁中的单次作业)。
        normalized_content_ids = list(dict.fromkeys(normalized_content_ids))
    claimed = await claim_publication_attempts(
        session,
        limit=limit,
        worker_id=worker_id,
        lease_seconds=lease_seconds,
        content_ids=normalized_content_ids,
    )
    submitted: list[dict[str, Any]] = []
    for attempt in claimed:
        submitted.append(
            await submit_publication_attempt_for_adapter(
                session,
                attempt,
                browser_agent_base_url=browser_agent_base_url,
                auth_token=auth_token,
                http_client=http_client,
                request_timeout_sec=request_timeout_sec,
            )
        )

    claimed_ids = {attempt.id for attempt in claimed}
    reconcile_attempts: list[PublicationAttempt] = []
    seen_reconcile_ids: set[str] = set()
    if normalized_content_ids:
        # Targeted publication runs are deterministic gate/execution loops. Reconcile
        # freshly submitted attempts in the same tick so early loop exits do not leave
        # their DB state stranded at "submitted" when the browser-agent task has already
        # progressed or terminated.
        for attempt in claimed:
            if attempt.status not in PUBLICATION_RECONCILE_STATUSES:
                continue
            reconcile_attempts.append(attempt)
            seen_reconcile_ids.add(attempt.id)

    reconcile_stmt = (
        select(PublicationAttempt).where(
            PublicationAttempt.status.in_(PUBLICATION_RECONCILE_STATUSES),
            *(
                [PublicationAttempt.content_id.in_(normalized_content_ids)]
                if normalized_content_ids
                else []
            ),
        )
        .order_by(PublicationAttempt.updated_at.asc(), PublicationAttempt.created_at.asc())
        .limit(max(1, int(limit or 1)))
    )
    reconcile_result = await session.execute(reconcile_stmt)
    for attempt in reconcile_result.scalars().all():
        if not normalized_content_ids and attempt.id in claimed_ids:
            continue
        if attempt.id in seen_reconcile_ids:
            continue
        reconcile_attempts.append(attempt)
        seen_reconcile_ids.add(attempt.id)
    reconciled: list[dict[str, Any]] = []
    for attempt in reconcile_attempts:
        reconciled.append(
            await reconcile_publication_attempt_for_adapter(
                session,
                attempt,
                browser_agent_base_url=browser_agent_base_url,
                auth_token=auth_token,
                http_client=http_client,
                request_timeout_sec=request_timeout_sec,
            )
        )

    active_result = await session.execute(
        select(PublicationAttempt.id).where(
            PublicationAttempt.status.in_(PUBLICATION_ACTIVE_STATUSES),
        )
    )
    active_count = len(active_result.scalars().all())
    return {
        "claimed": len(claimed),
        "submitted": submitted,
        "reconciled": reconciled,
        "active_count": active_count,
    }


async def list_publication_attempts(
    session: AsyncSession,
    *,
    job_id: str | None = None,
    creator_profile_id: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    stmt = select(PublicationAttempt).order_by(PublicationAttempt.created_at.desc(), PublicationAttempt.id.desc())
    if job_id:
        stmt = stmt.where(PublicationAttempt.content_id == str(job_id))
    if creator_profile_id:
        stmt = stmt.where(PublicationAttempt.creator_profile_id == str(creator_profile_id))
    if limit is not None:
        stmt = stmt.limit(max(1, int(limit)))
    result = await session.execute(stmt)
    attempts = result.scalars().all()
    if not attempts:
        return []
    attempt_ids = [attempt.id for attempt in attempts]
    run_result = await session.execute(
        select(PublicationAttemptRun)
        .where(PublicationAttemptRun.attempt_id.in_(attempt_ids))
        .order_by(PublicationAttemptRun.created_at.desc(), PublicationAttemptRun.id.desc())
    )
    runs_by_attempt: dict[str, list[PublicationAttemptRun]] = {}
    for run in run_result.scalars().all():
        runs_by_attempt.setdefault(run.attempt_id, []).append(run)
    return [serialize_publication_attempt(attempt, runs=runs_by_attempt.get(attempt.id, [])) for attempt in attempts]


def serialize_publication_attempt(
    attempt: PublicationAttempt,
    *,
    runs: list[PublicationAttemptRun] | None = None,
) -> dict[str, Any]:
    cover_path, cover_slots = _resolve_publication_cover_contract_fields(
        attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    )
    return {
        "id": attempt.id,
        "content_id": attempt.content_id,
        "job_id": str(attempt.job_id),
        "creator_profile_id": attempt.creator_profile_id,
        "creator_profile_name": attempt.creator_profile_name,
        "platform": attempt.platform,
        "platform_label": attempt.platform_label,
        "account_label": attempt.account_label,
        "credential_id": attempt.credential_id,
        "adapter": attempt.adapter,
        "status": attempt.status,
        "run_status": attempt.run_status,
        "attempt_number": attempt.attempt_number,
        "retry_count": attempt.retry_count,
        "max_retries": attempt.max_retries,
        "execution_mode": attempt.execution_mode,
        "content_kind": attempt.content_kind,
        "request_payload": attempt.request_payload or {},
        "response_payload": attempt.response_payload,
        "cover_path": cover_path,
        "cover_slots": cover_slots,
        "provider_task_id": attempt.provider_task_id,
        "provider_execution_id": attempt.provider_execution_id,
        "provider_status": attempt.provider_status,
        "external_receipt_id": attempt.external_receipt_id,
        "external_post_id": attempt.external_post_id,
        "external_url": attempt.external_url,
        "public_url": attempt.external_url,
        "scheduled_at": _iso_or_none(attempt.scheduled_at),
        "error_code": attempt.error_code,
        "error_message": attempt.error_message,
        "semantic_fingerprint": attempt.semantic_fingerprint,
        "idempotency_key": attempt.idempotency_key,
        "operator_summary": attempt.operator_summary,
        "created_at": _iso_or_none(attempt.created_at),
        "updated_at": _iso_or_none(attempt.updated_at),
        "runs": [serialize_publication_attempt_run(run) for run in (runs or [])],
    }


def serialize_publication_attempt_run(run: PublicationAttemptRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "attempt_id": run.attempt_id,
        "content_id": run.content_id,
        "platform": run.platform,
        "adapter": run.adapter,
        "execution_mode": run.execution_mode,
        "content_kind": run.content_kind,
        "consumer_id": run.consumer_id,
        "attempt_number": run.attempt_number,
        "status": run.status,
        "phase": run.phase,
        "started_at": _iso_or_none(run.started_at),
        "heartbeat_at": _iso_or_none(run.heartbeat_at),
        "lease_expires_at": _iso_or_none(run.lease_expires_at),
        "completed_at": _iso_or_none(run.completed_at),
        "provider_task_id": run.provider_task_id,
        "provider_execution_id": run.provider_execution_id,
        "provider_status": run.provider_status,
        "result": run.result_json,
        "error_message": run.error_message,
        "metadata": run.metadata_json or {},
        "created_at": _iso_or_none(run.created_at),
        "updated_at": _iso_or_none(run.updated_at),
    }


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_publication_cover_contract_fields(source: dict[str, Any] | None) -> tuple[str | None, list[dict[str, Any]]]:
    cover_slots = derive_publication_cover_slots(source)
    primary_cover_path = publication_primary_cover_path(source) or None
    return primary_cover_path, [dict(item) for item in cover_slots if isinstance(item, dict)]


def _looks_like_workspace_publication_cover_mirror(raw_path: Any) -> bool:
    normalized = re.sub(r"[\\/]+", "/", str(raw_path or "").strip()).lower()
    return "/artifacts/publish-material-mirror/" in normalized


def _publication_cover_contract_is_suspicious(
    cover_path: str | None,
    cover_slots: list[dict[str, Any]] | None = None,
) -> bool:
    if _looks_like_workspace_publication_cover_mirror(cover_path):
        return True
    for item in (cover_slots or []):
        if _looks_like_workspace_publication_cover_mirror((item or {}).get("cover_path")):
            return True
    return False


def _recover_publication_cover_contract_from_generation_group(
    source: dict[str, Any] | None,
    *,
    platform: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(source, dict):
        return None, []
    cover_generation = source.get("cover_generation") if isinstance(source.get("cover_generation"), dict) else {}
    cover_group = cover_generation.get("cover_group") if isinstance(cover_generation.get("cover_group"), dict) else {}
    if not cover_group and isinstance(cover_generation.get("group_generation"), dict):
        nested_group = cover_generation["group_generation"].get("cover_group")
        if isinstance(nested_group, dict):
            cover_group = nested_group
    group_cover_path = str(cover_group.get("cover_path") or "").strip()
    if not group_cover_path:
        return None, []
    members = [
        str(item or "").strip().lower()
        for item in (cover_group.get("members") or [])
        if str(item or "").strip()
    ]
    normalized_platform = str(platform or source.get("platform") or source.get("key") or "").strip().lower()
    if members and normalized_platform and normalized_platform not in members:
        return None, []
    target_size = cover_generation.get("target_size") if isinstance(cover_generation.get("target_size"), dict) else {}
    required_specs = platform_required_cover_slots(normalized_platform)
    label = ""
    matrix_key = str(cover_group.get("key") or "").strip()
    if required_specs:
        label = str(required_specs[0].get("label") or "").strip()
    slot: dict[str, Any] = {
        "slot": str(required_specs[0].get("slot") or "primary").strip() if required_specs else "primary",
        "cover_path": group_cover_path,
    }
    if label:
        slot["label"] = label
    if matrix_key:
        slot["matrix_key"] = matrix_key
    if target_size:
        slot["target_size"] = dict(target_size)
    return group_cover_path, [slot]


def _prefer_xiaohongshu_landscape_cover_contract(
    source: dict[str, Any] | None,
    *,
    platform: str = "",
    cover_path: str | None,
    cover_slots: list[dict[str, Any]] | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    if not isinstance(source, dict):
        return cover_path, [dict(item) for item in (cover_slots or []) if isinstance(item, dict)]
    normalized_platform = str(platform or source.get("platform") or source.get("key") or "").strip().lower()
    resolved_slots = [dict(item) for item in (cover_slots or []) if isinstance(item, dict)]
    if normalized_platform != "xiaohongshu":
        return cover_path, resolved_slots

    cover_matrix = source.get("cover_matrix") if isinstance(source.get("cover_matrix"), dict) else {}
    landscape_matrix = cover_matrix.get("landscape_4_3") if isinstance(cover_matrix.get("landscape_4_3"), dict) else {}
    landscape_cover_path = str(landscape_matrix.get("cover_path") or "").strip()
    if not landscape_cover_path:
        candidate_parent = None
        for raw_candidate in [str(cover_path or "").strip(), *(str(item.get("cover_path") or "").strip() for item in resolved_slots)]:
            if not raw_candidate:
                continue
            candidate_parent = Path(raw_candidate).expanduser().parent
            break
        if candidate_parent is not None:
            for sibling in (
                candidate_parent / "00-cover-landscape_4_3.jpg",
                smart_copy_cover_dir(candidate_parent) / "00-cover-landscape_4_3.jpg",
                resolve_smart_copy_cover_group_output_path(candidate_parent, "landscape_4_3"),
            ):
                try:
                    if sibling.exists() and sibling.is_file():
                        landscape_cover_path = str(sibling)
                        break
                except OSError:
                    continue
    if not landscape_cover_path:
        return cover_path, resolved_slots
    return landscape_cover_path, [
        {
            "slot": "landscape_4_3",
            "label": "4:3 横版母版",
            "matrix_key": "landscape_4_3",
            "target_size": {"width": 1440, "height": 1080},
            "cover_path": landscape_cover_path,
        }
    ]


def _load_publication_platform_cover_source_from_media_candidates(
    *,
    media_paths: list[str],
    platform: str,
) -> dict[str, Any] | None:
    normalized_platform = str(platform or "").strip().lower()
    if not media_paths or not normalized_platform:
        return None
    for raw_media_path in media_paths:
        normalized_media_path = str(raw_media_path or "").strip()
        if not normalized_media_path:
            continue
        media_path = Path(normalized_media_path).expanduser()
        material_dir = media_path.parent / "smart-copy"
        packaging, _ = load_publication_packaging_payload(
            material_json=str(resolve_smart_copy_material_json_path(material_dir)),
            platform_packaging=str(resolve_smart_copy_platform_packaging_json_path(material_dir)),
            platforms=[normalized_platform],
        )
        platforms = packaging.get("platforms") if isinstance(packaging, dict) and isinstance(packaging.get("platforms"), dict) else {}
        entry = platforms.get(normalized_platform)
        if isinstance(entry, dict):
            return dict(entry)
    return None


def _publication_cover_runtime_root() -> Path:
    settings = get_settings()
    base_root = Path(getattr(settings, "output_root", Path(__file__).resolve().parents[2] / "data" / "runtime")).expanduser()
    return base_root / "publication-covers"


def _materialized_publication_cover_target(raw_path: str) -> Path:
    normalized = re.sub(r"[\\/]+", "/", str(raw_path or "").strip())
    file_name = Path(normalized).name or "publication-cover.bin"
    stem = Path(file_name).stem or "publication-cover"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "publication-cover"
    digest = hashlib.sha1(normalized.casefold().encode("utf-8", errors="ignore")).hexdigest()[:16]
    target_dir = _publication_cover_runtime_root() / f"{digest}-{safe_stem[:48]}"
    return target_dir / file_name


def _should_copy_publication_cover(source_path: Path, target_path: Path) -> bool:
    if not target_path.exists():
        return True
    try:
        source_stat = source_path.stat()
        target_stat = target_path.stat()
    except OSError:
        return True
    return (
        source_stat.st_size != target_stat.st_size
        or int(source_stat.st_mtime) != int(target_stat.st_mtime)
    )


def _materialize_publication_cover_file(raw_path: str) -> Path | None:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return None
    target_path = _materialized_publication_cover_target(normalized)
    source_path = Path(normalized).expanduser()
    try:
        if not source_path.exists() or not source_path.is_file():
            return None
    except OSError:
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if _should_copy_publication_cover(source_path, target_path):
        shutil.copy2(source_path, target_path)
    if target_path.exists() and target_path.is_file():
        return target_path.resolve()
    return None


def resolve_publication_local_cover_path(raw_path: Any) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        if path.exists() and path.is_file():
            return path.resolve()
    except OSError:
        pass
    if _looks_like_external_media_path(raw):
        return _materialize_publication_cover_file(raw)
    return None


def _resolve_authoritative_publication_cover_contract(
    source: dict[str, Any] | None,
    *,
    platform: str = "",
    requested_media_path: str = "",
) -> tuple[str | None, list[dict[str, Any]]]:
    normalized_source = dict(source or {}) if isinstance(source, dict) else {}
    normalized_platform = str(platform or normalized_source.get("platform") or normalized_source.get("key") or "").strip().lower()
    cover_path, cover_slots = _resolve_publication_cover_contract_fields(normalized_source)
    if _publication_cover_contract_is_suspicious(cover_path, cover_slots):
        recovered_cover_path, recovered_cover_slots = _recover_publication_cover_contract_from_generation_group(
            normalized_source,
            platform=normalized_platform,
        )
        if recovered_cover_path:
            cover_path, cover_slots = recovered_cover_path, recovered_cover_slots
    media_path_candidates: list[str] = []
    for candidate in (
        requested_media_path,
        normalized_source.get("resolved_media_path"),
        ((normalized_source.get("metadata") or {}) if isinstance(normalized_source.get("metadata"), dict) else {}).get("requested_media_path"),
        ((normalized_source.get("metadata") or {}) if isinstance(normalized_source.get("metadata"), dict) else {}).get("resolved_media_path"),
    ):
        text = str(candidate or "").strip()
        if text and text not in media_path_candidates:
            media_path_candidates.append(text)
    for item in normalized_source.get("media_items") or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("local_path") or "").strip()
        if text and text not in media_path_candidates:
            media_path_candidates.append(text)
    if not cover_path or _publication_cover_contract_is_suspicious(cover_path, cover_slots):
        recovered_source = _load_publication_platform_cover_source_from_media_candidates(
            media_paths=media_path_candidates,
            platform=normalized_platform,
        )
        if recovered_source:
            recovered_cover_path, recovered_cover_slots = _resolve_publication_cover_contract_fields(recovered_source)
            recovered_group_cover_path, recovered_group_cover_slots = _recover_publication_cover_contract_from_generation_group(
                recovered_source,
                platform=normalized_platform,
            )
            if recovered_group_cover_path:
                recovered_cover_path, recovered_cover_slots = recovered_group_cover_path, recovered_group_cover_slots
            if recovered_cover_path:
                cover_path, cover_slots = recovered_cover_path, recovered_cover_slots
    cover_path, cover_slots = _prefer_xiaohongshu_landscape_cover_contract(
        normalized_source,
        platform=normalized_platform,
        cover_path=cover_path,
        cover_slots=cover_slots,
    )
    resolved_cover_slots: list[dict[str, Any]] = []
    for item in cover_slots:
        if not isinstance(item, dict):
            continue
        normalized_item = dict(item)
        slot_cover_path = str(normalized_item.get("cover_path") or "").strip()
        resolved_slot_cover_path = resolve_publication_local_cover_path(slot_cover_path)
        if resolved_slot_cover_path is not None:
            normalized_item["cover_path"] = str(resolved_slot_cover_path)
        resolved_cover_slots.append(normalized_item)
    resolved_cover_path = str(cover_path or "").strip()
    resolved_primary_cover_path = resolve_publication_local_cover_path(resolved_cover_path)
    if resolved_primary_cover_path is not None:
        resolved_cover_path = str(resolved_primary_cover_path)
    if not resolved_cover_path:
        for item in resolved_cover_slots:
            slot_cover_path = str(item.get("cover_path") or "").strip()
            if slot_cover_path:
                resolved_cover_path = slot_cover_path
                break
    return resolved_cover_path or None, resolved_cover_slots


def build_browser_agent_task_payload(attempt_id: str, *, plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    request_payload = _build_request_payload(plan=plan, target=target)
    metadata = request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {}
    media_items = list(request_payload.get("media_items") or [])
    publication_capability = request_payload.get("publication_capability") or {}
    requires_local_media = bool(publication_capability.get("requires_local_media", True))
    local_file_count = sum(1 for item in media_items if str(item.get("local_path") or "").strip()) if requires_local_media else 0
    cover_path, cover_slots = _resolve_authoritative_publication_cover_contract(
        request_payload,
        platform=str(target.get("platform") or ""),
        requested_media_path=str(metadata.get("requested_media_path") or ""),
    )
    copy_material = dict(request_payload.get("copy_material") or {}) if isinstance(request_payload.get("copy_material"), dict) else {}
    copy_material["cover_path"] = cover_path
    copy_material["cover_slots"] = cover_slots
    runtime_platform_specific_overrides = _build_runtime_publication_platform_specific_overrides(
        platform=str(target.get("platform") or "").strip(),
        collection=request_payload.get("collection"),
        cover_path=cover_path,
        cover_slots=cover_slots,
        platform_specific_overrides=request_payload.get("platform_specific_overrides"),
    )
    return {
        "task_id": attempt_id,
        "platform": target.get("platform"),
        "profile_id": _sanitize_profile_id(
            metadata.get("browser_profile_id"),
            fallback=str(target.get("platform") or "default"),
        ),
        "session_binding": metadata.get("session_binding") if isinstance(metadata.get("session_binding"), dict) else {},
        "content": {
            "title": request_payload.get("title") or "",
            "body": request_payload.get("body") or "",
            "content_kind": "video",
            "hashtags": request_payload.get("hashtags") or [],
            "display_hashtags": request_payload.get("display_hashtags") or [],
            "structured_tags": request_payload.get("structured_tags") or [],
            "native_topics": request_payload.get("native_topics") or [],
            "category": request_payload.get("category"),
            "collection": request_payload.get("collection"),
            "cover_path": cover_path,
            "cover_slots": cover_slots,
            "declaration": request_payload.get("declaration"),
            "copy_material": copy_material,
            "visibility_or_publish_mode": request_payload.get("visibility_or_publish_mode"),
            "scheduled_publish_at": request_payload.get("scheduled_publish_at"),
            "ui_control_semantics": request_payload.get("ui_control_semantics") or {},
            "platform_specific_overrides": runtime_platform_specific_overrides,
            "publication_content_signature": request_payload.get("publication_content_signature"),
            "publication_plan_signature": request_payload.get("publication_plan_signature"),
            "publication_recovery_state": request_payload.get("publication_recovery_state") or {},
            "publication_capability": request_payload.get("publication_capability") or {},
            "validation_contract": request_payload.get("validation_contract") or BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
            "publish_media_source": {
                "provider": "local_file" if requires_local_media else "link_only",
                "mode": "platform_native_upload" if requires_local_media else "link_only",
                "requires_public_url": False,
                "local_file_count": local_file_count,
            },
            "media_urls": list(request_payload.get("media_urls") or []),
            "media_items": media_items,
            "metadata": metadata,
        },
    }


def _is_publication_recovery_target(target: dict[str, Any] | None) -> bool:
    raw_overrides = target.get("platform_specific_overrides") if isinstance(target, dict) else {}
    if not isinstance(raw_overrides, dict):
        raw_overrides = {}
    recovery_mode = str(raw_overrides.get("recovery_mode") or "").strip().lower()
    return (
        bool(raw_overrides.get("clear_draft_context"))
        or recovery_mode in {
            "draft_reset",
            "clear_draft",
            "auto_recover",
            "receipt_rebind",
            "prepublish_resume",
            "content_plan",
        }
        or bool(raw_overrides.get("force_publish_page_refresh"))
        or bool(raw_overrides.get("verification_only_current_page"))
        or bool(raw_overrides.get("repair_only_current_page"))
        or bool(raw_overrides.get("prepublish_only_current_page"))
        or bool(raw_overrides.get("prepare_only_current_page"))
    )


def _is_platform_draft_reset_recoverable_status(
    status: str,
    error_code: str,
) -> bool:
    normalized_status = str(status or "").strip().lower()
    if normalized_status not in {"failed", "needs_human"}:
        return False
    normalized_error_code = str(error_code or "").strip().lower()
    if not normalized_error_code:
        return False
    if normalized_error_code in _PUBLICATION_DRAFT_RESET_ERROR_SUFFIXES:
        return True
    return any(normalized_error_code.endswith(suffix) for suffix in _PUBLICATION_DRAFT_RESET_ERROR_SUFFIXES)


def _is_retry_queued_publication_attempt(attempt: PublicationAttempt | None) -> bool:
    if attempt is None:
        return False
    status = str(getattr(attempt, "status", "") or "").strip().lower()
    if status != "queued":
        return False
    run_status = str(getattr(attempt, "run_status", "") or "").strip().lower()
    error_code = str(getattr(attempt, "error_code", "") or "").strip().lower()
    if error_code:
        return True
    return run_status == "retry_scheduled"


def _should_recover_attempt_with_draft_refresh(attempt: PublicationAttempt) -> bool:
    context = _extract_publication_failure_context(
        attempt,
        raw_status=str(getattr(attempt, "provider_status", "") or getattr(attempt, "status", "") or ""),
        task=attempt.response_payload if isinstance(getattr(attempt, "response_payload", None), dict) else {},
        response_payload=attempt.response_payload if isinstance(getattr(attempt, "response_payload", None), dict) else {},
    )
    if (
        _has_unbound_receipt_target(context)
        or _is_publish_receipt_pending_context(context)
        or _is_pre_publish_upload_pending_context(context)
        or _is_media_upload_not_applied_context(context)
        or _should_preserve_post_repair_context(context)
        or _is_route_auth_required_context(context)
    ):
        return False
    if _is_platform_draft_reset_recoverable_status(str(attempt.status or ""), str(attempt.error_code or "")):
        return True
    raw_response_payload = attempt.response_payload
    response_payload = raw_response_payload if isinstance(raw_response_payload, dict) else {}
    publication_audit = response_payload.get("publication_audit")
    if isinstance(publication_audit, dict):
        required_unverified = publication_audit.get("required_unverified", [])
        required_reupload = publication_audit.get("required_reupload", [])
        if any(str(item).strip() for item in required_unverified if item is not None):
            return True
        if any(str(item).strip() for item in required_reupload if item is not None):
            return True
        if str(publication_audit.get("notes") or "").strip():
            return True
    return False


def _should_recover_draft_context_for_attempt(attempt: PublicationAttempt) -> bool:
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    prior_overrides = request_payload.get("platform_specific_overrides")
    if not isinstance(prior_overrides, dict):
        prior_overrides = {}
    if not _is_publication_recovery_target({"platform_specific_overrides": prior_overrides}):
        return False
    return _should_recover_attempt_with_draft_refresh(attempt)


def _select_recovery_candidate_attempts_for_platform(
    attempts: list[PublicationAttempt],
) -> list[PublicationAttempt]:
    terminal_recoverable_statuses = PUBLICATION_TERMINAL_STATUSES - {"published", "draft_created"}
    return [
        item
        for item in sorted(
            attempts,
            key=lambda current: (current.updated_at or current.created_at or _utc_now()),
            reverse=True,
        )
        if str(item.status or "").strip().lower() in terminal_recoverable_statuses
    ]


def _coerce_reusable_recovery_state(attempt: PublicationAttempt | None) -> dict[str, Any] | None:
    if attempt is None:
        return None
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    raw_state = request_payload.get("publication_recovery_state")
    if not isinstance(raw_state, dict):
        return None
    return _coerce_publication_recovery_state(raw_state)


def _sanitize_carried_recovery_overrides(
    recovery_overrides: dict[str, Any],
    *,
    failure_context: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(recovery_overrides or {})
    recovery_mode = str(normalized.get("recovery_mode") or "").strip().lower()

    if recovery_mode == "receipt_rebind" and not (
        _has_unbound_receipt_target(failure_context)
        or _is_publish_receipt_pending_context(failure_context)
    ):
        normalized.pop("verification_only_current_page", None)
        normalized.pop("wait_for_publish_confirmation", None)
        normalized.pop("verify_media_upload", None)
        normalized.pop("recovery_mode", None)

    if recovery_mode == "prepublish_resume" and not (
        _is_pre_publish_upload_pending_context(failure_context)
        or _is_media_upload_not_applied_context(failure_context)
        or _should_preserve_post_repair_context(failure_context)
    ):
        normalized.pop("prepare_only_current_page", None)
        normalized.pop("repair_only_current_page", None)
        normalized.pop("prepublish_only_current_page", None)
        normalized.pop("wait_for_publish_confirmation", None)
        normalized.pop("verify_media_upload", None)
        normalized.pop("recovery_mode", None)

    return normalized


def _build_platform_recovery_overrides(
    *,
    attempt: PublicationAttempt,
    request_plan_signature: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if attempt is None:
        return {}, None
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    request_signature = _extract_publication_plan_signature(request_payload)
    prior_overrides = request_payload.get("platform_specific_overrides")
    if not isinstance(prior_overrides, dict):
        prior_overrides = {}
    response_payload = attempt.response_payload if isinstance(attempt.response_payload, dict) else {}
    failure_context = _extract_publication_failure_context(
        attempt,
        raw_status=str(getattr(attempt, "provider_status", "") or getattr(attempt, "status", "") or ""),
        task=response_payload,
        response_payload=response_payload,
    )
    carried_recovery_overrides = {
        key: value for key, value in prior_overrides.items()
        if key in PUBLICATION_RECOVERY_OVERRIDE_KEYS
    } if request_signature == request_plan_signature else {}
    carried_recovery_overrides = _sanitize_carried_recovery_overrides(
        carried_recovery_overrides,
        failure_context=failure_context,
    )
    recovery_overrides = dict(carried_recovery_overrides) if _should_recover_draft_context_for_attempt(attempt) else {}
    if _has_unbound_receipt_target(failure_context) or _is_publish_receipt_pending_context(failure_context):
        recovery_overrides.update(
            {
                "clear_draft_context": False,
                "force_publish_page_refresh": True,
                "verification_only_current_page": True,
                "wait_for_publish_confirmation": True,
                "recovery_mode": "receipt_rebind",
            }
        )
    elif (
        _is_pre_publish_upload_pending_context(failure_context)
        or _is_media_upload_not_applied_context(failure_context)
        or _should_preserve_post_repair_context(failure_context)
    ):
        recovery_overrides.update(
            {
                "clear_draft_context": False,
                "force_publish_page_refresh": True,
                "prepare_only_current_page": True,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
                "recovery_mode": "prepublish_resume",
            }
        )
    if _should_recover_attempt_with_draft_refresh(attempt):
        recovery_overrides.update(
            {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
                "recovery_mode": "draft_reset",
            }
        )
    recovery_state = _coerce_reusable_recovery_state(attempt)
    if recovery_state:
        recovery_state["schema_version"] = PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION
        recovery_state["plan_signature"] = request_plan_signature
        recovery_state["carry_over_from_attempt_id"] = str(attempt.id)
        recovery_state["reused_attempt_count"] = int(recovery_state.get("reused_attempt_count") or 0) + 1
    return recovery_overrides, recovery_state


def build_browser_agent_task_payload_from_attempt(attempt: PublicationAttempt) -> dict[str, Any]:
    request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
    media_items = [item for item in (request_payload.get("media_items") or []) if isinstance(item, dict)]
    platform = str(attempt.platform or "").strip()
    publication_capability = request_payload.get("publication_capability") or {}
    requires_local_media = bool(
        publication_capability.get("requires_local_media", PLATFORM_LOCAL_MEDIA_REQUIRED.get(platform, True))
    )
    metadata = request_payload.get("metadata") if isinstance(request_payload.get("metadata"), dict) else {}
    metadata = _rehydrate_publication_attempt_runtime_metadata(attempt, metadata)
    requested_media_path = str(metadata.get("requested_media_path") or "").strip()
    refreshed_media_items: list[dict[str, Any]] = []
    workspace_runtime_root = (Path(__file__).resolve().parents[2] / "data" / "runtime").resolve()
    for item in media_items:
        refreshed = dict(item)
        raw_local_path = str(refreshed.get("local_path") or "").strip()
        candidate_paths = [raw_local_path] if raw_local_path else []
        if requested_media_path and requested_media_path not in candidate_paths:
            candidate_paths.append(requested_media_path)
        resolved_local_path = ""
        for candidate in candidate_paths:
            resolved = resolve_publication_local_media_path(candidate)
            if resolved is not None:
                resolved_local_path = str(resolved)
                break
        if resolved_local_path:
            refreshed["local_path"] = resolved_local_path
        elif raw_local_path:
            clear_unresolved_path = bool(requested_media_path)
            if not clear_unresolved_path:
                try:
                    clear_unresolved_path = Path(raw_local_path).expanduser().resolve().is_relative_to(workspace_runtime_root)
                except Exception:
                    clear_unresolved_path = False
            if clear_unresolved_path:
                refreshed["local_path"] = ""
        refreshed_media_items.append(refreshed)
    media_items = refreshed_media_items
    local_media_items = [item for item in media_items if str(item.get("local_path") or "").strip()]
    if requires_local_media and not local_media_items:
        raise ValueError("browser-agent 发布需要至少一个本地文件 media_items[].local_path")
    local_file_count = len(local_media_items) if requires_local_media else 0
    cover_path, cover_slots = _resolve_authoritative_publication_cover_contract(
        request_payload,
        platform=platform,
        requested_media_path=requested_media_path,
    )
    copy_material = dict(request_payload.get("copy_material") or {}) if isinstance(request_payload.get("copy_material"), dict) else {}
    copy_material["cover_path"] = cover_path
    copy_material["cover_slots"] = cover_slots
    runtime_platform_specific_overrides = _build_runtime_publication_platform_specific_overrides(
        platform=platform,
        collection=request_payload.get("collection"),
        cover_path=cover_path,
        cover_slots=cover_slots,
        platform_specific_overrides=request_payload.get("platform_specific_overrides"),
    )
    payload = {
        "task_id": attempt.id,
        "attempt_id": attempt.id,
        "content_id": str(attempt.content_id or ""),
        "platform": attempt.platform,
        "profile_id": _sanitize_profile_id(
            metadata.get("browser_profile_id"),
            fallback=attempt.platform or "default",
        ),
        "session_binding": (
            metadata.get("session_binding")
            if isinstance(metadata.get("session_binding"), dict)
            else build_publication_browser_session_binding(
                platform=attempt.platform,
                creator_profile_id=metadata.get("creator_profile_id"),
                browser_profile_id=metadata.get("browser_profile_id"),
                credential_ref=metadata.get("credential_ref"),
                account_label=metadata.get("account_label"),
                browser_binding=metadata.get("browser_binding"),
            )
        ),
        "content": {
            "title": str(request_payload.get("title") or ""),
            "body": str(request_payload.get("body") or ""),
            "content_kind": str(request_payload.get("content_kind") or attempt.content_kind or "video"),
            "hashtags": list(request_payload.get("hashtags") or []),
            "display_hashtags": list(request_payload.get("display_hashtags") or []),
            "structured_tags": list(request_payload.get("structured_tags") or []),
            "native_topics": list(request_payload.get("native_topics") or []),
            "category": request_payload.get("category"),
            "collection": request_payload.get("collection"),
            "cover_path": cover_path,
            "cover_slots": cover_slots,
            "declaration": request_payload.get("declaration"),
            "copy_material": copy_material,
            "visibility_or_publish_mode": request_payload.get("visibility_or_publish_mode"),
            "scheduled_publish_at": request_payload.get("scheduled_publish_at"),
            "ui_control_semantics": request_payload.get("ui_control_semantics") or {},
            "platform_specific_overrides": runtime_platform_specific_overrides,
            "publication_content_signature": request_payload.get("publication_content_signature"),
            "publication_plan_signature": request_payload.get("publication_plan_signature"),
            "publication_recovery_state": request_payload.get("publication_recovery_state") or {},
            "publication_capability": request_payload.get("publication_capability") or {},
            "validation_contract": request_payload.get("validation_contract") or BROWSER_AGENT_PUBLICATION_RUN_CONTRACT,
            "publish_media_source": {
                "provider": "local_file" if requires_local_media else "link_only",
                "mode": "platform_native_upload" if requires_local_media else "link_only",
                "requires_public_url": False,
                "local_file_count": local_file_count,
            },
            "media_urls": list(request_payload.get("media_urls") or []),
            "media_items": media_items,
            "metadata": metadata,
        },
    }
    reconcile_callback_url = _build_publication_reconcile_callback_url()
    if reconcile_callback_url:
        payload["reconcile_callback_url"] = reconcile_callback_url
    return payload


def _build_publication_reconcile_callback_url() -> str:
    settings = get_settings()
    base_url = str(
        getattr(settings, "publication_reconcile_callback_base_url", "") or ""
    ).strip().rstrip("/")
    if not base_url:
        raw_port = str(os.getenv("ROUGHCUT_API_PORT") or "").strip()
        try:
            port = max(1, int(raw_port)) if raw_port else 38471
        except ValueError:
            port = 38471
        base_url = f"http://127.0.0.1:{port}"
    return f"{base_url}/api/v1/intelligent-copy/publication/reconcile-task"


def _build_runtime_publication_platform_specific_overrides(
    *,
    platform: str,
    collection: Any,
    cover_path: Any,
    cover_slots: Any = None,
    platform_specific_overrides: Any,
) -> dict[str, Any]:
    overrides = dict(platform_specific_overrides or {}) if isinstance(platform_specific_overrides, dict) else {}
    normalized_platform = str(platform or "").strip().lower()
    recovery_flags = {
        "verification_only_current_page",
        "repair_only_current_page",
        "prepublish_only_current_page",
        "prepare_only_current_page",
        "fresh_start_platform_tab",
    }
    is_safe_runtime_mode = any(bool(overrides.get(flag)) for flag in recovery_flags) or bool(
        overrides.get("stop_before_final_publish")
    )
    collection_management = (
        dict(overrides.get("collection_management"))
        if isinstance(overrides.get("collection_management"), dict)
        else {}
    )
    collection_management_target = str(
        collection_management.get("selected_collection_name")
        or collection_management.get("target_collection_name")
        or collection_management.get("collection_name")
        or ""
    ).strip()
    has_explicit_collection = (
        bool(collection)
        or bool(collection_management_target)
        or str(overrides.get("collection_policy") or "").strip()
        or bool(overrides.get("skip_collection_select"))
    )
    if (
        is_safe_runtime_mode
        and platform_requires_explicit_collection_policy(normalized_platform)
        and not has_explicit_collection
    ):
        overrides["collection_policy"] = "skip"
        overrides["skip_collection_select"] = True
    has_explicit_cover = (
        bool(str(cover_path or "").strip())
        or any(
            isinstance(item, dict) and str(item.get("cover_path") or "").strip()
            for item in (cover_slots or [])
        )
        or str(overrides.get("cover_policy") or "").strip()
        or bool(overrides.get("skip_cover_upload"))
    )
    if (
        is_safe_runtime_mode
        and platform_requires_custom_cover_policy(normalized_platform)
        and not has_explicit_cover
    ):
        overrides["cover_policy"] = "platform_default"
        overrides["skip_cover_upload"] = True
    return overrides


def _coerce_publication_topic_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            [
                str(item).strip().lstrip("#")
                for item in value
                if str(item).strip().lstrip("#")
            ]
        )
    )[:20]


def _resolve_publication_collection_target(
    *,
    platform: str,
    collection: Any,
    platform_specific_overrides: Any,
) -> dict[str, str] | None:
    normalized_collection = collection if isinstance(collection, dict) else _normalize_collection_option({"collection": collection})
    if normalized_collection:
        return normalized_collection
    overrides = (
        dict(platform_specific_overrides)
        if isinstance(platform_specific_overrides, dict)
        else {}
    )
    collection_management = (
        dict(overrides.get("collection_management"))
        if isinstance(overrides.get("collection_management"), dict)
        else {}
    )
    collection_name = str(
        collection_management.get("selected_collection_name")
        or collection_management.get("target_collection_name")
        or collection_management.get("collection_name")
        or ""
    ).strip()
    if not collection_name:
        return None
    return {"name": collection_name[:160]}


def _normalize_publication_plan_platform_specific_overrides(
    *,
    platform: str,
    collection: Any,
    platform_specific_overrides: Any,
) -> dict[str, Any]:
    overrides = (
        dict(platform_specific_overrides)
        if isinstance(platform_specific_overrides, dict)
        else {}
    )
    normalized_collection = _resolve_publication_collection_target(
        platform=platform,
        collection=collection,
        platform_specific_overrides=overrides,
    )
    collection_policy = str(overrides.get("collection_policy") or "").strip().lower()
    explicit_skip = bool(overrides.get("skip_collection_select"))
    if normalized_collection and (explicit_skip or collection_policy == "skip"):
        overrides.pop("skip_collection_select", None)
        if collection_policy == "skip":
            overrides.pop("collection_policy", None)
    return overrides


def _resolve_publication_native_topics(
    *,
    package: dict[str, Any],
    publish_options: dict[str, Any],
    platform_specific_overrides: Any,
) -> list[str]:
    option_topics = _coerce_publication_topic_list(publish_options.get("native_topics"))
    if option_topics:
        return option_topics
    package_topics = _coerce_publication_topic_list(package.get("native_topics"))
    if package_topics:
        return package_topics
    overrides = (
        dict(platform_specific_overrides)
        if isinstance(platform_specific_overrides, dict)
        else {}
    )
    topic_plan = (
        dict(overrides.get("topic_selection_plan"))
        if isinstance(overrides.get("topic_selection_plan"), dict)
        else {}
    )
    return _coerce_publication_topic_list(topic_plan.get("requested_topics"))


def _normalize_publication_platform_options(value: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw_options = value if isinstance(value, dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_platform, raw_value in raw_options.items():
        platform = normalize_publication_platform(raw_platform)
        if not platform or not isinstance(raw_value, dict):
            continue
        option: dict[str, Any] = {}
        scheduled_publish_at = _normalize_scheduled_publish_at(raw_value.get("scheduled_publish_at"))
        if scheduled_publish_at:
            option["scheduled_publish_at"] = scheduled_publish_at
        collection = _normalize_collection_option(raw_value)
        if collection:
            option["collection"] = collection
        category = str(raw_value.get("category") or "").strip()
        if category:
            option["category"] = category[:120]
        native_topics = _coerce_publication_topic_list(raw_value.get("native_topics"))
        if native_topics:
            option["native_topics"] = native_topics
        visibility_or_publish_mode = str(raw_value.get("visibility_or_publish_mode") or "").strip()
        if visibility_or_publish_mode:
            option["visibility_or_publish_mode"] = visibility_or_publish_mode[:80]
        platform_specific_overrides = raw_value.get("platform_specific_overrides")
        if isinstance(platform_specific_overrides, dict):
            option["platform_specific_overrides"] = platform_specific_overrides
            if "native_topics" not in option:
                override_native_topics = _coerce_publication_topic_list(platform_specific_overrides.get("native_topics"))
                if override_native_topics:
                    option["native_topics"] = override_native_topics
                else:
                    topic_plan = platform_specific_overrides.get("topic_selection_plan")
                    if isinstance(topic_plan, dict):
                        requested_topics = _coerce_publication_topic_list(topic_plan.get("requested_topics"))
                        if requested_topics:
                            option["native_topics"] = requested_topics
        live_publish_preflight = raw_value.get("live_publish_preflight")
        if not isinstance(live_publish_preflight, dict) and isinstance(platform_specific_overrides, dict):
            live_publish_preflight = platform_specific_overrides.get("live_publish_preflight")
        if isinstance(live_publish_preflight, dict):
            option["live_publish_preflight"] = live_publish_preflight
        normalized[platform] = option
    return normalized


def _package_publish_option(package: dict[str, Any], key: str) -> Any:
    if not isinstance(package, dict):
        return None
    value = package.get(key)
    if value is None and key == "collection":
        return _normalize_collection_option(package)
    return value


def _publication_preflight_block_reason(platform: str, publish_options: dict[str, Any]) -> str:
    preflight = publish_options.get("live_publish_preflight") if isinstance(publish_options.get("live_publish_preflight"), dict) else {}
    if not preflight:
        return ""
    status = str(preflight.get("status") or "").strip().lower()
    missing = [str(item).strip() for item in (preflight.get("missing_required_surfaces") or []) if str(item).strip()]
    if status not in {"blocked", "missing_required_surfaces"} and not missing:
        return ""
    summary = str(preflight.get("summary") or "").strip()
    if not summary and missing:
        summary = "缺少发布页关键参数面：" + "、".join(missing[:8])
    return f"{platform_label(platform)} 发布前验证未通过：{summary or '页面关键参数未验证完整。'}"


def _should_recover_with_reasoning() -> bool:
    settings = get_settings()
    provider = str(getattr(settings, "active_reasoning_provider", "") or "").strip().lower()
    if not provider:
        return False
    if provider == "openai":
        return bool(settings.openai_api_key or settings.openai_api_key_helper)
    if provider == "anthropic":
        return bool(settings.anthropic_api_key)
    if provider == "minimax":
        return bool(settings.minimax_api_key)
    if provider == "ollama":
        return bool(settings.ollama_base_url)
    return False


def _should_auto_recover_publication_failure(
    attempt: PublicationAttempt,
    *,
    mapped_status: str,
    diagnosis: dict[str, Any] | None,
) -> bool:
    if not PUBLICATION_LLM_AUTO_RECOVERY_ENABLED:
        return False
    if not isinstance(diagnosis, dict):
        return False
    if mapped_status not in {"failed", "needs_human"}:
        return False
    recovery_plan = diagnosis.get("recovery_plan") if isinstance(diagnosis, dict) else {}
    if isinstance(recovery_plan, dict) and bool(recovery_plan.get("duplicate_detected")):
        return False
    if isinstance(recovery_plan, dict) and recovery_plan.get("recovery_overrides"):
        if not str(diagnosis.get("action") or "").strip().lower() == "retry":
            # 除了明确指示 retry 外，保守不自动重试。
            return False
    if not bool(diagnosis.get("retryable")):
        return False
    action = str(diagnosis.get("action") or "").strip().lower()
    if action not in PUBLICATION_LLM_AUTO_RECOVERY_ACTIONS:
        return False
    resolution_source = str(diagnosis.get("resolution_source") or "llm").strip().lower()
    if resolution_source != "rule":
        if not _should_recover_with_reasoning():
            return False
        try:
            confidence = float(diagnosis.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < float(PUBLICATION_LLM_AUTO_RECOVERY_CONFIDENCE_THRESHOLD):
            return False
    return int(attempt.retry_count or 0) < int(attempt.max_retries or 0)


def _next_publication_retry_delay_seconds(retry_count: int) -> int:
    return min(900, 30 * (2 ** max(0, retry_count - 1)))


def _apply_publication_auto_recovery(
    attempt: PublicationAttempt,
    run: PublicationAttemptRun | None,
    *,
    now: datetime,
    diagnosis: dict[str, Any],
    mapped_status: str,
    context: dict[str, Any] | None = None,
) -> None:
    confidence = float(diagnosis.get("confidence") or 0.0)
    status_summary = _publication_status_summary(mapped_status, attempt.provider_status or "")
    resolution_source = str(diagnosis.get("resolution_source") or "llm").strip().lower() or "llm"
    plan_signature = ""
    request_payload = getattr(attempt, "request_payload", None)
    if isinstance(request_payload, dict):
        raw_signature = request_payload.get("publication_plan_signature")
        if isinstance(raw_signature, dict):
            plan_signature = str(raw_signature.get("value") or "").strip()
    attempt.retry_count = int(attempt.retry_count or 0) + 1
    attempt.status = "queued"
    attempt.run_status = "retry_scheduled"
    attempt.next_retry_at = now + timedelta(seconds=_next_publication_retry_delay_seconds(attempt.retry_count))
    attempt.operator_summary = (
        f"{attempt.operator_summary or status_summary}；"
        f"{'规则诊断' if resolution_source == 'rule' else 'LLM'} 建议自动恢复，置信度={confidence:.2f}，已安排第 {attempt.retry_count} 次重试。"
    )
    recovery_plan = diagnosis.get("recovery_plan")
    if not isinstance(recovery_plan, dict):
        recovery_plan = _build_recovery_signal_from_context(context or {}) or {}
    if not isinstance(recovery_plan, dict):
        recovery_plan = {}
    recovery_overrides = {}
    target_adapter = str(recovery_plan.get("target_adapter") or "").strip()
    target_execution_mode = str(recovery_plan.get("target_execution_mode") or "").strip()
    next_platform_overrides = {}
    target_platform_specific_overrides = recovery_plan.get("target_platform_specific_overrides")
    if isinstance(target_platform_specific_overrides, dict):
        next_platform_overrides.update(
            {
                str(key): value
                for key, value in target_platform_specific_overrides.items()
                if key is not None and isinstance(value, (str, int, float, bool))
            }
        )
    if isinstance(recovery_plan.get("recovery_overrides"), dict):
        recovery_plan_overrides = recovery_plan["recovery_overrides"]
        recovery_overrides.update({k: v for k, v in recovery_plan_overrides.items() if isinstance(v, bool) or isinstance(v, str)})
        raw_next_platform_overrides = recovery_plan_overrides.get("next_platform_specific_overrides")
        if isinstance(raw_next_platform_overrides, dict):
            next_platform_overrides.update(
                {str(key): value for key, value in raw_next_platform_overrides.items() if key is not None and isinstance(value, (str, int, float, bool))}
            )
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    recovery_state = _apply_publication_recovery_memory(
        attempt,
        context=(context or {}),
        diagnosis=diagnosis,
    )
    if isinstance(request_payload, dict):
        raw_platform_overrides = request_payload.get("platform_specific_overrides")
        if not isinstance(raw_platform_overrides, dict):
            raw_platform_overrides = {}
        merged_overrides = dict(raw_platform_overrides)
        if next_platform_overrides:
            merged_overrides.update(next_platform_overrides)
        if isinstance(recovery_overrides, dict) and recovery_overrides:
            merged_overrides.update(recovery_overrides)
        if target_adapter:
            attempt.adapter = _normalize_publication_adapter(target_adapter)
        if target_execution_mode:
            attempt.execution_mode = target_execution_mode
        request_payload["platform_specific_overrides"] = merged_overrides
        recovery_state["resolution_source"] = resolution_source
        if not recovery_state.get("plan_signature"):
            recovery_state["plan_signature"] = plan_signature
            recovery_state["platform"] = str(getattr(attempt, "platform", "") or "").strip()
        recovery_state["updated_at"] = now.isoformat()
        recovery_state["latest_retry_count"] = attempt.retry_count
        recovery_state["latest_recovery_resolution"] = {
            "mapped_status": mapped_status,
            "status": str(attempt.status).strip(),
            "resolution_source": resolution_source,
            "confidence": confidence,
        }
        recovery_state["recovery_plan"] = recovery_plan
        request_payload["publication_recovery_state"] = recovery_state
        attempt.request_payload = request_payload
    attempt.provider_task_id = None
    attempt.provider_execution_id = None
    if run is not None:
        run.status = "retry_scheduled"
        run.phase = "submit"
        run.heartbeat_at = now
        run.provider_task_id = None
        run.provider_execution_id = None
        run.provider_status = attempt.provider_status
        run.error_message = attempt.error_message
        run.completed_at = now


def _extract_route_snapshot(raw_task: dict[str, Any]) -> dict[str, Any]:
    route = raw_task.get("route") or raw_task.get("navigation") or {}
    if not isinstance(route, dict):
        return {}
    snapshot: dict[str, Any] = {}
    for key in ("url", "title", "origin", "status", "path", "hash"):
        value = str(route.get(key) or "").strip()
        if value:
            snapshot[key] = value[:300]
    return snapshot


def _coerce_visual_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    artifact_path = str(payload.get("artifact_path") or "").strip()
    if not artifact_path:
        return {}
    normalized: dict[str, Any] = {
        "artifact_path": artifact_path[:400],
        "capture_type": str(payload.get("capture_type") or "").strip()[:64] or "screenshot",
        "mime_type": str(payload.get("mime_type") or "").strip()[:64] or "image/png",
        "sha256": str(payload.get("sha256") or "").strip()[:96],
        "captured_at": str(payload.get("captured_at") or "").strip()[:64],
        "platform": str(payload.get("platform") or "").strip()[:64],
        "phase": str(payload.get("phase") or "").strip()[:96],
        "route_url": str(payload.get("route_url") or "").strip()[:400],
        "route_title": str(payload.get("route_title") or "").strip()[:200],
    }
    for key in ("byte_size", "width", "height"):
        try:
            value = int(payload.get(key) or 0)
        except Exception:
            value = 0
        if value > 0:
            normalized[key] = value
    return normalized


def _extract_visual_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    direct = _coerce_visual_evidence(payload.get("visual_evidence"))
    if direct:
        return direct
    progress = payload.get("progress")
    if isinstance(progress, dict):
        from_progress = _coerce_visual_evidence(progress.get("visual_evidence"))
        if from_progress:
            return from_progress
    result = payload.get("result")
    if isinstance(result, dict):
        from_result = _coerce_visual_evidence(result.get("visual_evidence"))
        if from_result:
            return from_result
    return {}


def _compact_blockers(raw_task: dict[str, Any]) -> list[dict[str, Any]]:
    blockers = []
    raw_blockers = raw_task.get("blockers")
    if isinstance(raw_blockers, list):
        for item in raw_blockers[:8]:
            if isinstance(item, dict):
                blockers.append({k: str(v).strip()[:220] for k, v in item.items() if v not in (None, "")})
            else:
                value = str(item).strip()
                if value:
                    blockers.append({"message": value[:220]})
    return blockers


def _coerce_publication_recovery_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    history_raw = value.get("failure_history")
    history = {}
    if isinstance(history_raw, dict):
        for signature, entry in history_raw.items():
            if not isinstance(entry, dict):
                continue
            history[str(signature)] = {
                "attempt_count": int(entry.get("attempt_count") or 0),
                "first_seen": str(entry.get("first_seen") or "").strip(),
                "last_seen": str(entry.get("last_seen") or "").strip(),
                "platform": str(entry.get("platform") or "").strip(),
                "code": str(entry.get("code") or "").strip(),
                "failure_signal_count": int(entry.get("failure_signal_count") or 0),
            }
    return {
        "schema_version": int(value.get("schema_version") or PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION),
        "plan_signature": str(value.get("plan_signature") or "").strip(),
        "failure_history": history,
        "adaptations": list(value.get("adaptations") or [])[:12],
        "carry_over_from_attempt_id": str(value.get("carry_over_from_attempt_id") or "").strip(),
        "reused_attempt_count": int(value.get("reused_attempt_count") or 0),
    }


def _build_publication_failure_signature(context: dict[str, Any]) -> str:
    platform = str(context.get("platform") or "").strip().lower()
    error_code = str((context.get("error") or {}).get("code") or "").strip()
    recovery_code = str((context.get("recovery") or {}).get("code") or "").strip()
    audit = context.get("audit") if isinstance(context.get("audit"), dict) else {}
    required_reupload = [str(item).strip() for item in (audit.get("required_reupload") or []) if str(item).strip()]
    required_unverified = [str(item).strip() for item in (audit.get("required_unverified") or []) if str(item).strip()]
    failure_marker = error_code or recovery_code or ""
    if not failure_marker:
        all_failures = sorted(set(required_reupload + required_unverified))
        if all_failures:
            failure_marker = f"need_fix:{'|'.join(all_failures)}"
    if not failure_marker:
        failure_marker = "unknown"
    return f"{platform}:{failure_marker}"


def _adaptive_recovery_overrides_for_context(*, context: dict[str, Any], base_plan: dict[str, Any] | None, error_code: str, diagnosis_action: str) -> dict[str, Any]:
    recovery_overrides: dict[str, Any] = {}
    if isinstance(base_plan, dict):
        existing = base_plan.get("recovery_overrides")
        if isinstance(existing, dict):
            recovery_overrides.update(existing)
    if _is_pre_publish_upload_pending_context(context) or _is_media_upload_not_applied_context(context):
        recovery_overrides["clear_draft_context"] = False
        recovery_overrides["force_publish_page_refresh"] = True
        return recovery_overrides
    if _is_route_auth_required_context(context):
        recovery_overrides["clear_draft_context"] = False
        recovery_overrides["force_publish_page_refresh"] = False
        return recovery_overrides
    if _should_preserve_post_repair_context(context) or _has_unbound_receipt_target(context):
        recovery_overrides["clear_draft_context"] = False
        recovery_overrides["force_publish_page_refresh"] = True
        return recovery_overrides
    request_recovery_state = _coerce_publication_recovery_state(context.get("request_recovery_state"))
    failure_history = request_recovery_state.get("failure_history")
    if not isinstance(failure_history, dict):
        failure_history = {}
    signature = _build_publication_failure_signature(context)
    past_count = int((failure_history.get(signature) or {}).get("attempt_count") or 0) if signature else 0
    audit = context.get("audit") if isinstance(context.get("audit"), dict) else {}
    draft_reset_candidate = _is_platform_draft_reset_recoverable_status(
        str(context.get("mapped_status") or context.get("status") or ""),
        error_code,
    ) or any(
        str(item).strip()
        for item in [
            *(audit.get("required_reupload") or []),
            *(audit.get("required_unverified") or []),
            audit.get("notes") or "",
        ]
        if item is not None
    )
    if error_code and draft_reset_candidate and str(diagnosis_action).strip().lower() == "retry":
        if past_count >= 1:
            recovery_overrides["clear_draft_context"] = True
            recovery_overrides["force_publish_page_refresh"] = True
        if past_count >= PUBLICATION_RECOVERY_REPEAT_LIMIT - 1:
            recovery_overrides["recovery_mode"] = "draft_reset"
    return recovery_overrides


def _apply_publication_recovery_memory(attempt: PublicationAttempt, *, context: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    request_payload = getattr(attempt, "request_payload", None)
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    state = _coerce_publication_recovery_state(request_payload.get("publication_recovery_state"))
    recovery_context = context.get("recovery")
    if not isinstance(recovery_context, dict):
        recovery_context = {}
    state["schema_version"] = PUBLICATION_RECOVERY_STATE_SCHEMA_VERSION
    state["plan_signature"] = str(
        context.get("recovery_plan_signature")
        or recovery_context.get("plan_signature")
        or state.get("plan_signature")
        or ""
    ).strip()
    failure_history = dict(state.get("failure_history") or {})
    signature = _build_publication_failure_signature(context)
    entry = failure_history.get(signature)
    if not isinstance(entry, dict):
        entry = {}
    now = _utc_now().isoformat()
    entry["attempt_count"] = int(entry.get("attempt_count") or 0) + 1
    entry["platform"] = str(context.get("platform") or "").strip()
    entry["code"] = str((context.get("error") or {}).get("code") or context.get("error_code") or "").strip()
    if not entry.get("first_seen"):
        entry["first_seen"] = now
    entry["last_seen"] = now
    entry["failure_signal_count"] = int(entry.get("failure_signal_count") or 0)
    audit = context.get("audit") if isinstance(context.get("audit"), dict) else {}
    failed_points = [str(item).strip() for item in (audit.get("required_reupload") or []) + (audit.get("required_unverified") or []) if str(item).strip()]
    entry["failure_signal_count"] = max(entry["failure_signal_count"], len(failed_points))
    failure_history[signature] = entry
    sorted_entries = sorted(
        failure_history.items(),
        key=lambda item: str(item[1].get("last_seen") or ""),
        reverse=True,
    )
    state["failure_history"] = {signature: entry for signature, entry in sorted_entries[:PUBLICATION_RECOVERY_ADAPTIVE_HISTORY_LIMIT]}
    adaptations = list(state.get("adaptations") or [])
    if isinstance(diagnosis, dict):
        adaptation = {
            "timestamp": now,
            "code": str((context.get("error") or {}).get("code") or signature).strip(),
            "action": str(diagnosis.get("action") or "").strip(),
            "severity": str(diagnosis.get("severity") or "").strip(),
            "reason": str(diagnosis.get("rationale") or "").strip()[:180],
        }
        adaptations.append(adaptation)
    state["adaptations"] = adaptations[-12:]
    state["latest_failure_signature"] = signature
    return state


def _coerce_recovery_plan(raw_recovery: Any) -> dict[str, Any] | None:
    if not isinstance(raw_recovery, dict):
        return None
    recovery_overrides = raw_recovery.get("recovery_overrides")
    if not isinstance(recovery_overrides, dict):
        recovery_overrides = {}
    normalized_overrides: dict[str, Any] = {}
    clear_draft = bool(recovery_overrides.get("clear_draft_context"))
    force_refresh = bool(recovery_overrides.get("force_publish_page_refresh"))
    recovery_mode = str(recovery_overrides.get("recovery_mode") or "").strip().lower()
    target_adapter = str(recovery_overrides.get("target_adapter") or raw_recovery.get("target_adapter") or "").strip()
    target_execution_mode = str(recovery_overrides.get("target_execution_mode") or raw_recovery.get("target_execution_mode") or "").strip()
    target_platform_specific_overrides = recovery_overrides.get("target_platform_specific_overrides")
    if not isinstance(target_platform_specific_overrides, dict):
        target_platform_specific_overrides = raw_recovery.get("target_platform_specific_overrides")
    if not isinstance(target_platform_specific_overrides, dict):
        target_platform_specific_overrides = {}
    if clear_draft or force_refresh or recovery_mode:
        normalized_overrides["clear_draft_context"] = clear_draft
        normalized_overrides["force_publish_page_refresh"] = force_refresh
        if recovery_mode:
            normalized_overrides["recovery_mode"] = recovery_mode
    for key in (
        "verification_only_current_page",
        "repair_only_current_page",
        "prepublish_only_current_page",
        "prepare_only_current_page",
        "fresh_start_platform_tab",
        "verify_media_upload",
        "wait_for_publish_confirmation",
    ):
        if isinstance(recovery_overrides.get(key), bool):
            normalized_overrides[key] = bool(recovery_overrides.get(key))
    if target_adapter:
        normalized_overrides["target_adapter"] = _normalize_publication_adapter(target_adapter)
    if target_execution_mode:
        normalized_overrides["target_execution_mode"] = target_execution_mode
    if target_platform_specific_overrides:
        normalized_overrides["target_platform_specific_overrides"] = {
            str(key): value
            for key, value in target_platform_specific_overrides.items()
            if key is not None and isinstance(value, (str, int, float, bool))
        }
    next_platform_overrides = recovery_overrides.get("next_platform_specific_overrides")
    if isinstance(next_platform_overrides, dict):
        normalized_overrides["next_platform_specific_overrides"] = {
            str(key): value
            for key, value in next_platform_overrides.items()
            if key is not None and isinstance(value, (str, int, float, bool))
        }
    raw_blockers = raw_recovery.get("blockers")
    blockers: list[dict[str, Any]] = []
    if isinstance(raw_blockers, list):
        for item in raw_blockers[:8]:
            if isinstance(item, dict):
                blockers.append({k: str(v).strip()[:220] for k, v in item.items() if v is not None and str(v).strip()})
            else:
                value = str(item).strip()
                if value:
                    blockers.append({"message": value[:220]})
    normalized = {
        "code": str(raw_recovery.get("code") or "").strip(),
        "reason": str(raw_recovery.get("reason") or "").strip(),
        "duplicate_detected": bool(raw_recovery.get("duplicate_detected")),
        "recovery_overrides": normalized_overrides,
        "blockers": blockers,
        "route": _extract_route_snapshot(raw_recovery),
        "action_history": raw_recovery.get("action_history") if isinstance(raw_recovery.get("action_history"), list) else [],
        "evidence": raw_recovery.get("evidence") if isinstance(raw_recovery.get("evidence"), dict) else {},
        "visual_evidence": _extract_visual_evidence(raw_recovery),
    }
    return normalized


def _build_recovery_signal_from_context(context: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(context.get("recovery"), dict):
        return None
    return _coerce_recovery_plan(context["recovery"])


def _extract_recovery_signal_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    nested = payload.get("recovery")
    if isinstance(nested, dict):
        normalized = _coerce_recovery_plan(nested)
        if isinstance(normalized, dict):
            return normalized
    flattened_keys = {
        "code",
        "reason",
        "duplicate_detected",
        "target_adapter",
        "target_execution_mode",
        "target_platform_specific_overrides",
        "recovery_overrides",
        "blockers",
        "route",
        "action_history",
        "evidence",
        "visual_evidence",
        "suggestion",
    }
    flattened = {
        key: payload.get(key)
        for key in flattened_keys
        if key in payload
    }
    if not flattened:
        return None
    return _coerce_recovery_plan(flattened)


_POST_REPAIR_NON_DRAFT_RESET_FIELDS = {"upload_ready", "receipt"}


def _coerce_pre_publish_repair(payload: Any) -> dict[str, Any]:
    return payload if isinstance(payload, dict) else {}


def _coerce_repair_evidence(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, bool] = {}
    for key, value in payload.items():
        name = str(key or "").strip()
        if not name:
            continue
        normalized[name] = bool(value)
    return normalized


def _remaining_repair_blockers(context: dict[str, Any]) -> set[str]:
    audit = context.get("audit") if isinstance(context.get("audit"), dict) else {}
    return {
        str(item).strip()
        for item in [
            *(audit.get("required_reupload") or []),
            *(audit.get("required_unverified") or []),
        ]
        if str(item).strip()
    }


def _is_auth_required_code(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    return any(normalized.endswith(suffix) for suffix in _PUBLICATION_AUTH_REQUIRED_ERROR_SUFFIXES)


def _is_route_auth_required_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    error = context.get("error") if isinstance(context.get("error"), dict) else {}
    recovery = context.get("recovery") if isinstance(context.get("recovery"), dict) else {}
    return _is_auth_required_code(error.get("code")) or _is_auth_required_code(recovery.get("code"))


def _is_pre_publish_upload_pending_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    error = context.get("error") if isinstance(context.get("error"), dict) else {}
    recovery = context.get("recovery") if isinstance(context.get("recovery"), dict) else {}
    error_code = str(error.get("code") or "").strip().lower()
    recovery_code = str(recovery.get("code") or "").strip().lower()
    if not (error_code.endswith("_pre_publish_upload_pending") or recovery_code.endswith("_pre_publish_upload_pending")):
        return False
    remaining = _remaining_repair_blockers(context)
    return bool(remaining) and remaining.issubset(_POST_REPAIR_NON_DRAFT_RESET_FIELDS)


def _is_media_upload_not_applied_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    error = context.get("error") if isinstance(context.get("error"), dict) else {}
    recovery = context.get("recovery") if isinstance(context.get("recovery"), dict) else {}
    error_code = str(error.get("code") or "").strip().lower()
    recovery_code = str(recovery.get("code") or "").strip().lower()
    if not (error_code.endswith("_media_upload_failed") or recovery_code.endswith("_media_upload_failed")):
        return False
    error_details = error.get("details") if isinstance(error.get("details"), dict) else {}
    failure_reason = str(error_details.get("failure_reason") or "").strip().lower()
    if failure_reason == "upload_not_applied":
        return True
    error_message = str(error.get("message") or "").strip().lower()
    return "upload_not_applied" in error_message


_PUBLISH_RECEIPT_PENDING_ERROR_CODES = {
    "publication_public_url_missing",
    "publication_signature_missing",
    "publication_signature_fields_missing",
    "publication_schedule_receipt_missing",
    "publication_request_fields_snapshot_missing",
    "publication_request_field_snapshot_untrusted",
    "publication_response_payload_untrusted",
    "publication_submitted_response_payload_missing",
    "publication_submitted_response_payload_empty_snapshot",
}


def _is_publish_receipt_pending_context(context: dict[str, Any]) -> bool:
    if not isinstance(context, dict):
        return False
    error = context.get("error") if isinstance(context.get("error"), dict) else {}
    recovery = context.get("recovery") if isinstance(context.get("recovery"), dict) else {}
    for value in (error.get("code"), recovery.get("code")):
        normalized = str(value or "").strip().lower()
        if normalized in _PUBLISH_RECEIPT_PENDING_ERROR_CODES:
            return True
    return False


def _has_pre_publish_repair_progress(context: dict[str, Any]) -> bool:
    repair = _coerce_pre_publish_repair(context.get("pre_publish_repair"))
    if not repair or not repair.get("attempted"):
        return False
    repair_evidence = _coerce_repair_evidence(context.get("repair_evidence"))
    if any(repair_evidence.values()):
        return True
    before_required = [str(item).strip() for item in (repair.get("before_required_unverified") or []) if str(item).strip()]
    after_required = [str(item).strip() for item in (repair.get("after_required_unverified") or []) if str(item).strip()]
    if before_required and len(after_required) < len(before_required):
        return True
    actions = repair.get("actions")
    return isinstance(actions, list) and bool(actions)


def _should_preserve_post_repair_context(context: dict[str, Any]) -> bool:
    if not _has_pre_publish_repair_progress(context):
        return False
    remaining = _remaining_repair_blockers(context)
    return bool(remaining) and remaining.issubset(_POST_REPAIR_NON_DRAFT_RESET_FIELDS)


def _extract_receipt_binding_context(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    def _looks_like_invalid_douyin_manage_card_binding(raw: Any) -> bool:
        if not isinstance(raw, dict):
            return False
        if str(raw.get("receipt_binding_source") or "").strip() != "douyin_manage_card":
            return False
        manage_card = raw.get("douyin_manage_card") if isinstance(raw.get("douyin_manage_card"), dict) else {}
        text = str(manage_card.get("text") or "").strip()
        if not text:
            return False
        action_block_count = len(re.findall(r"(?:继续编辑|编辑作品)\s+设置权限\s+作品置顶\s+删除作品", text))
        published_at_count = len(re.findall(r"\d{4}年\d{2}月\d{2}日\s*\d{2}:\d{2}", text))
        duration_count = len(re.findall(r"\b\d{2}:\d{2}\b", text))
        management_shell_noise = bool(re.search(r"高清发布|首页|活动管理|内容管理|作品管理|合集管理|互动管理|数据中心|变现中心|创作中心|通知|网址|抖音", text))
        return management_shell_noise and (
            action_block_count > 1
            or published_at_count > 1
            or duration_count > 2
        )

    def _coerce_binding(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        has_target_bound = isinstance(raw.get("receipt_target_bound"), bool)
        receipt_like = bool(raw.get("receipt_like"))
        binding_source = str(raw.get("receipt_binding_source") or "").strip()
        post_publish_surface = str(raw.get("post_publish_surface") or "").strip()
        if not (has_target_bound or receipt_like or binding_source or post_publish_surface):
            return {}
        normalized: dict[str, Any] = {
            "receipt_like": receipt_like,
            "receipt_binding_source": binding_source,
            "post_publish_surface": post_publish_surface,
        }
        binding_payload = {
            key: value
            for key, value in {
                "douyin_manage_card": raw.get("douyin_manage_card"),
                "xiaohongshu_note_manager_card": raw.get("xiaohongshu_note_manager_card"),
                "toutiao_manage_card": raw.get("toutiao_manage_card"),
            }.items()
            if isinstance(value, dict)
        }
        if binding_payload:
            normalized["receipt_binding_payload"] = binding_payload
        for key in ("youtube_editor_video_id", "youtube_receipt_video_id"):
            value = str(raw.get(key) or "").strip()
            if value:
                normalized[key] = value
        if has_target_bound:
            normalized["receipt_target_bound"] = bool(raw.get("receipt_target_bound"))
            if normalized["receipt_target_bound"] and _looks_like_invalid_douyin_manage_card_binding(raw):
                normalized["receipt_target_bound"] = False
                normalized["receipt_binding_source"] = "unbound_manage_receipt"
        return normalized

    def _extract_from_container(container: Any) -> dict[str, Any]:
        if not isinstance(container, dict):
            return {}
        candidates: list[dict[str, Any]] = []
        platform_extras = container.get("platform_extras")
        if isinstance(platform_extras, dict):
            candidates.append(platform_extras)
        for key in ("material_integrity", "publication_audit", "post_click_integrity", "final_publish"):
            nested = container.get(key)
            if isinstance(nested, dict):
                candidates.append(nested)
                nested_extras = nested.get("platform_extras")
                if isinstance(nested_extras, dict):
                    candidates.append(nested_extras)
        for candidate in candidates:
            binding = _coerce_binding(candidate)
            if binding:
                return binding
        return {}

    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    for candidate in (payload, result_payload, task_result, task_progress, task_payload):
        binding = _extract_from_container(candidate)
        if binding:
            return binding
        timeout_progress = candidate.get("timeout_progress") if isinstance(candidate, dict) and isinstance(candidate.get("timeout_progress"), dict) else {}
        binding = _extract_from_container(timeout_progress)
        if binding:
            return binding
    return {}


def _derive_receipt_binding_fallback_id(binding: dict[str, Any]) -> str:
    if not isinstance(binding, dict):
        return ""
    if binding.get("receipt_target_bound") is not True or not bool(binding.get("receipt_like")):
        return ""
    marker_payload: dict[str, Any] = {
        "receipt_binding_source": str(binding.get("receipt_binding_source") or "").strip(),
        "post_publish_surface": str(binding.get("post_publish_surface") or "").strip(),
    }
    for key in ("youtube_editor_video_id", "youtube_receipt_video_id"):
        value = str(binding.get(key) or "").strip()
        if value:
            marker_payload[key] = value
    if isinstance(binding.get("receipt_binding_payload"), dict):
        marker_payload["receipt_binding_payload"] = binding.get("receipt_binding_payload")
    if not any(str(value or "").strip() for value in marker_payload.values() if not isinstance(value, dict)) and "receipt_binding_payload" not in marker_payload:
        return ""
    blob = json.dumps(marker_payload, ensure_ascii=False, sort_keys=True)
    return f"receipt-binding:{hashlib.sha256(blob.encode('utf-8')).hexdigest()[:24]}"


def _has_unbound_receipt_target(context: dict[str, Any]) -> bool:
    binding = context.get("receipt_binding") if isinstance(context.get("receipt_binding"), dict) else {}
    if not binding:
        return False
    return bool(binding.get("receipt_like")) and binding.get("receipt_target_bound") is False


def _has_bound_receipt_target(context: dict[str, Any]) -> bool:
    binding = context.get("receipt_binding") if isinstance(context.get("receipt_binding"), dict) else {}
    if not binding:
        return False
    if not bool(binding.get("receipt_like")) or binding.get("receipt_target_bound") is not True:
        return False
    post_publish_surface = str(binding.get("post_publish_surface") or "").strip().lower()
    return post_publish_surface.endswith("_receipt")


def _has_bound_receipt_verification_success(
    *,
    raw_status: str,
    context: dict[str, Any],
    audit: dict[str, Any] | None,
) -> bool:
    normalized_status = str(raw_status or "").strip().lower().replace("-", "_")
    if normalized_status not in {"verified", "published"}:
        return False
    if not _has_bound_receipt_target(context):
        return False
    if isinstance(audit, dict) and audit.get("verified") is False:
        return False
    if normalized_status == "published" and isinstance(audit, dict) and audit.get("verified") is not True:
        # Legacy browser-agent payloads may surface a bound receipt as `published`
        # instead of `verified`. Only trust that downgrade when structured audit
        # still confirms the publish result.
        return False
    return True


def _has_verified_stop_before_final_publish_success(
    *,
    raw_status: str,
    result: dict[str, Any],
    audit: dict[str, Any] | None,
) -> bool:
    if str(raw_status or "").strip().lower().replace("-", "_") != "verified":
        return False
    final_publish = result.get("final_publish") if isinstance(result.get("final_publish"), dict) else {}
    if not isinstance(final_publish, dict) or final_publish.get("stop_before_final_publish") is not True:
        return False
    if isinstance(audit, dict) and audit.get("verified") is False:
        return False
    return True


def _derive_recovery_diagnosis_from_context(context: dict[str, Any]) -> dict[str, Any] | None:
    recovery = context.get("recovery") if isinstance(context.get("recovery"), dict) else {}
    error = context.get("error") if isinstance(context.get("error"), dict) else {}
    audit = context.get("audit") if isinstance(context.get("audit"), dict) else {}

    def _as_rule_diagnosis(payload: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(payload, dict):
            return None
        diagnostic = dict(payload)
        diagnostic["resolution_source"] = "rule"
        return diagnostic

    def _has_material_recovery_signal() -> bool:
        if recovery:
            return True
        if str(error.get("code") or "").strip() or str(error.get("message") or "").strip():
            return True
        if any(str(item).strip() for item in (audit.get("required_unverified") or []) if str(item).strip()):
            return True
        if any(str(item).strip() for item in (audit.get("required_reupload") or []) if str(item).strip()):
            return True
        blockers = context.get("blockers") or []
        if isinstance(blockers, list):
            for item in blockers:
                if isinstance(item, dict):
                    if any(str(value).strip() for value in item.values() if value is not None):
                        return True
                elif str(item).strip():
                    return True
        return False

    if _has_unbound_receipt_target(context):
        binding = context.get("receipt_binding") if isinstance(context.get("receipt_binding"), dict) else {}
        binding_source = str(binding.get("receipt_binding_source") or "").strip() or "unbound_receipt"
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["保持当前发布后现场，刷新管理页或成功页后重新绑定本次作品回执，不要清稿或补发。"],
            "confidence": 0.97,
            "evidence": [binding_source, str(binding.get("post_publish_surface") or "").strip() or "receipt_like"],
            "rationale": "平台已出现发布后回执信号，但尚未唯一绑定到本次作品；清稿或补发会放大重复发布风险。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {"clear_draft_context": False, "force_publish_page_refresh": True},
            },
        })

    if _has_bound_receipt_target(context):
        if not _has_material_recovery_signal():
            return None
        binding = context.get("receipt_binding") if isinstance(context.get("receipt_binding"), dict) else {}
        binding_source = str(binding.get("receipt_binding_source") or "").strip() or "bound_receipt"
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["已完成发布后回执唯一绑定；如仍有字段审计噪音，请人工核对后结束本次恢复，不要继续自动清稿或补发。"],
            "confidence": 0.98,
            "evidence": [binding_source, str(binding.get("post_publish_surface") or "").strip() or "receipt_like"],
            "rationale": "当前任务已经把发布后回执唯一绑定到目标作品，继续按字段审计失败自动重试只会重复读取现场并放大重复发布风险。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {"clear_draft_context": False, "force_publish_page_refresh": False},
            },
        })

    if _is_route_auth_required_context(context):
        auth_code = str((error.get("code") or recovery.get("code") or "route_auth_required")).strip()
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["补齐账号会话后再发：检查登录态、扫码状态与二次验证弹窗，不要清稿重来。"],
            "confidence": 0.99,
            "evidence": [auth_code],
            "rationale": "当前失败首先发生在登录/会话路由，清稿或自动重试无法恢复账号态，且可能放大重复提交风险。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": False,
                },
            },
        })

    if _is_media_upload_not_applied_context(context):
        upload_code = str((error.get("code") or recovery.get("code") or "media_upload_failed")).strip()
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["保持当前发布页现场，刷新后重新核验媒体上传是否真正挂载到页面，不要清稿重来。"],
            "confidence": 0.96,
            "evidence": [upload_code, "upload_not_applied", "upload_ready"],
            "rationale": "上传动作已触发，但平台页面没有真正进入可继续编辑/发布的媒体已挂载状态；应保留现场刷新并复核上传，而不是清稿重试。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                },
            },
        })

    if not recovery:
        return None

    code = str(recovery.get("code") or "").strip()
    error_code = str(error.get("code") or "").strip()
    error_message = str(error.get("message") or "").strip()
    blockers = context.get("blockers") or []
    duplicate_detected = bool(recovery.get("duplicate_detected"))
    if code.endswith("draft_clear_failed") or error_code.endswith("draft_clear_failed"):
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["不要继续自动清理草稿，先核对平台当前草稿态与实际发布结果。"],
            "confidence": 0.98,
            "evidence": [code or error_code or "draft_clear_failed"],
            "rationale": "草稿清理动作本身失败，继续自动清稿会放大错误并污染恢复链路。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {"clear_draft_context": False, "force_publish_page_refresh": False},
            },
        })
    if duplicate_detected:
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["检测到疑似重复发布信号，需要人工确认是否已发布。"],
            "confidence": 0.99,
            "evidence": [str(code or "duplicate_publish_detected")],
            "rationale": "检测到平台疑似重复发布信号，避免二次发布。",
            "recovery_plan": {
                "duplicate_detected": True,
                "recovery_overrides": {"clear_draft_context": False, "force_publish_page_refresh": False},
            },
        })
    retriable_route_codes = {
        "_material_integrity_route_not_ready",
        "_material_integrity_failed",
        "_final_publish_route_not_ready",
        "_final_publish_unconfirmed",
        "_upload_prompt_only",
    }
    if error_code in {"platform_tab_not_found", "platform_publish_entry_missing", "platform_tab_autocreate_disabled"}:
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["先确认对应平台发布页已在可复用 profile 打开并可用。"],
            "confidence": 0.99,
            "evidence": [error_code],
            "rationale": "当前失败与页面入口/会话绑定相关，需要补齐页面环境。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {},
            },
        })
    if _should_preserve_post_repair_context(context):
        remaining = sorted(_remaining_repair_blockers(context))
        if "upload_ready" in remaining:
            next_steps = ["保持当前发布页现场，等待素材上传完成后刷新验证，不要清稿重来。"]
            rationale = "字段级自动修复已完成，剩余阻塞是上传未就绪；清稿会丢失已修现场。"
        else:
            next_steps = ["保持当前发布页现场，重新读取发布回执并核对目标作品绑定，不要清稿重来。"]
            rationale = "字段级自动修复已完成，剩余阻塞是发布回执确认；清稿会破坏已修现场。"
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": next_steps,
            "confidence": 0.95,
            "evidence": [code or error_code or "post_repair_structural_blocker", *remaining],
            "rationale": rationale,
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                },
            },
        })
    if _is_pre_publish_upload_pending_context(context):
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["保持当前发布页现场，等待素材上传完成后刷新验证，不要清稿重来。"],
            "confidence": 0.95,
            "evidence": [code or error_code or "pre_publish_upload_pending", "upload_ready"],
            "rationale": "预发布字段已通过，当前仅剩素材上传未就绪；应保留现场等待上传完成，而不是清稿重试。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": True,
                },
            },
        })
    content_plan_suffixes = (
        "_content_plan_mismatch",
        "_material_integrity_failed",
        "_pre_publish_material_integrity_failed",
        "_post_publish_content_plan_mismatch",
        "_receipt_content_plan_mismatch",
        "_scheduled_receipt_content_plan_mismatch",
        "_publish_content_plan_mismatch",
        "publication_audit_unverified",
        "publication_signature_missing",
        "publication_signature_fields_missing",
        "publication_signature_mismatch",
        "publication_signature_fields_mismatch",
        "publication_public_url_missing",
        "publication_schedule_receipt_missing",
    )
    if any((code or error_code).endswith(suffix) for suffix in content_plan_suffixes) or error_code in {"publication_audit_unverified"}:
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["清理草稿上下文并刷新发布页后重试，避免继承旧草稿。"],
            "confidence": 0.93,
            "evidence": [code or error_code or "publication_audit_unverified"],
            "rationale": "检测到发布内容核验未通过，先清理草稿上下文可避免脏草稿污染。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {"clear_draft_context": True, "force_publish_page_refresh": True},
            },
        })
    for suffix in retriable_route_codes:
        if code.endswith(suffix) or (error_code and error_code.endswith(suffix)):
            return _as_rule_diagnosis({
                "severity": "medium",
                "action": "retry",
                "retryable": True,
                "next_steps": ["先清理草稿上下文并刷新发布页后重试。"],
                "confidence": 0.9,
                "evidence": [code or error_code],
                "rationale": "检测到发布页态不稳定信号，允许通过清理草稿重试。",
                "recovery_plan": {
                    "duplicate_detected": False,
                    "recovery_overrides": {
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                },
            },
        })
    if _is_auth_required_code(code or error_code):
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["补齐账号会话后再发：检查登录态与二次验证弹窗。"],
            "confidence": 0.98,
            "evidence": [code or error_code],
            "rationale": "检测到登录/会话异常，重试可能重复提交。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": False,
                    "force_publish_page_refresh": False,
                },
            },
        })
    if error_message and _looks_like_external_media_path(error_message):
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["媒体路径异常时需重新解析本地素材后重试。"],
            "confidence": 0.82,
            "evidence": [code or error_code or "media_path_error"],
            "rationale": "当前报错更像素材读取链路问题，保守重试。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {
                    "clear_draft_context": True,
                    "force_publish_page_refresh": True,
                },
            },
        })
    if "duplicate" in (code or "").lower() or "duplicate" in (error_code or "").lower():
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["检测到重复发布信号，需要人工确认是否已发布。"],
            "confidence": 0.99,
            "evidence": [code or error_code],
            "rationale": "重复发布风险高，先人工核实避免二次投放。",
            "recovery_plan": {
                "duplicate_detected": True,
                "recovery_overrides": {"clear_draft_context": False, "force_publish_page_refresh": False},
            },
        })
    if "草稿" in error_message or "草稿" in code or "草稿" in error_code or "upload" in error_message.lower() or "上传" in error_message:
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": ["先清理编辑态草稿后重试，避免复用脏态。"],
            "confidence": 0.88,
            "evidence": [code or error_code or "draft_upload_signal"],
            "rationale": "检测到编辑/上传异常，清理草稿更容易恢复。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {"clear_draft_context": True, "force_publish_page_refresh": True},
            },
        })
    route_code = str(recovery.get("code") or "").strip()
    if _is_auth_required_code(route_code) or route_code == "platform_tab_not_found":
        return _as_rule_diagnosis({
            "severity": "high",
            "action": "manual_check",
            "retryable": False,
            "next_steps": ["补齐账号会话后重试。"],
            "confidence": 0.96,
            "evidence": [route_code],
            "rationale": "检测到登录/会话异常，需要先人工恢复账号会话。",
            "recovery_plan": {
                "duplicate_detected": False,
                "recovery_overrides": {},
            },
        })
    recovery_overrides = recovery.get("recovery_overrides")
    if isinstance(recovery_overrides, dict) and any(
        isinstance(recovery_overrides.get(key), bool) and recovery_overrides.get(key) for key in ("clear_draft_context", "force_publish_page_refresh")
    ):
        clear_draft = bool(recovery_overrides.get("clear_draft_context"))
        force_refresh = bool(recovery_overrides.get("force_publish_page_refresh"))
        verify_media_upload = bool(recovery_overrides.get("verify_media_upload"))
        wait_for_publish_confirmation = bool(recovery_overrides.get("wait_for_publish_confirmation"))
        if clear_draft and force_refresh:
            next_steps = ["应用恢复上下文，清理草稿并刷新发布页后重试。"]
            rationale = "检测到可恢复的卡死/草稿脏态信号，建议清理后重试。"
        elif force_refresh and (verify_media_upload or wait_for_publish_confirmation):
            next_steps = ["应用恢复上下文，保留当前发布页现场，核验上传/发布进度并刷新页面后继续验证。"]
            rationale = "检测到可等待的上传或回执阶段，优先保留现场继续核验，避免清稿破坏已修状态。"
        elif force_refresh:
            next_steps = ["应用恢复上下文，保留当前发布页现场并刷新页面后重试。"]
            rationale = "检测到可恢复的页面态不稳定信号，优先刷新现场后继续验证。"
        else:
            next_steps = ["应用恢复上下文后重试。"]
            rationale = "检测到可恢复的流程信号，按恢复上下文继续尝试。"
        return _as_rule_diagnosis({
            "severity": "medium",
            "action": "retry",
            "retryable": True,
            "next_steps": next_steps,
            "confidence": 0.93,
            "evidence": [route_code],
            "rationale": rationale,
            "recovery_plan": _coerce_recovery_plan(recovery),
        })
    return None


def _extract_publication_failure_context(attempt: PublicationAttempt, raw_status: str, task: dict[str, Any], *, response_payload: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    error = task.get("error") if isinstance(task.get("error"), dict) else {}
    error_details = error.get("details")
    if isinstance(error_details, str):
        try:
            parsed_error_details = json.loads(error_details)
        except Exception:
            parsed_error_details = None
        error_details = parsed_error_details if isinstance(parsed_error_details, dict) else {}
    audit = result.get("publication_audit") if isinstance(result.get("publication_audit"), dict) else {}
    recovery = _extract_recovery_signal_payload(result) or _extract_recovery_signal_payload(task)
    visual_evidence = _extract_visual_evidence(result) or _extract_visual_evidence(task)
    final_publish = result.get("final_publish") if isinstance(result.get("final_publish"), dict) else {}
    pre_publish_repair = final_publish.get("pre_publish_repair") if isinstance(final_publish.get("pre_publish_repair"), dict) else {}
    field_snapshot = _extract_publication_field_snapshot(result) or _extract_publication_field_snapshot(task)
    repair_evidence = field_snapshot.get("repair_evidence") if isinstance(field_snapshot.get("repair_evidence"), dict) else {}
    receipt_binding = _extract_receipt_binding_context(result) or _extract_receipt_binding_context(task)
    request_payload = getattr(attempt, "request_payload", None)
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    recovery_state = _coerce_publication_recovery_state(request_payload.get("publication_recovery_state"))
    request_plan_signature = request_payload.get("publication_plan_signature")
    request_signature_value = ""
    if isinstance(request_plan_signature, dict):
        request_signature_value = str(request_plan_signature.get("value") or "").strip()
    context = {
        "attempt_id": str(getattr(attempt, "id", "") or ""),
        "platform": str(getattr(attempt, "platform", "") or ""),
        "platform_label": platform_label(getattr(attempt, "platform", "")),
        "mapped_status": str(getattr(attempt, "status", "")),
        "raw_status": str(raw_status),
        "error": {
            "code": str(error.get("code") or task.get("error_code") or "").strip(),
            "message": str(error.get("message") or task.get("error_message") or "").strip(),
            "details": error_details if isinstance(error_details, dict) else {},
        },
        "route": _extract_route_snapshot(task),
        "blockers": _compact_blockers(task),
        "action_history": result.get("actions") if isinstance(result.get("actions"), list) else (task.get("actions") if isinstance(task.get("actions"), list) else []),
        "audit": {
            "verified": bool(audit.get("verified")) if isinstance(audit, dict) else None,
            "required_unverified": [
                str(item).strip() for item in (audit.get("required_unverified") or []) if str(item).strip()
            ] if isinstance(audit, dict) else [],
            "required_reupload": [
                str(item).strip() for item in (audit.get("required_reupload") or []) if str(item).strip()
            ] if isinstance(audit, dict) else [],
            "notes": str(audit.get("notes") or "").strip(),
        },
        "pre_publish_repair": pre_publish_repair,
        "repair_evidence": repair_evidence,
        "visual_evidence": visual_evidence,
        "receipt_binding": receipt_binding,
        "recovery": recovery,
        "recovery_plan_signature": request_signature_value,
        "request_recovery_state": recovery_state,
        "response_excerpt": {
            "platform": str((response_payload.get("platform") or "").strip()) if isinstance(response_payload, dict) else "",
        },
    }
    context["failure_signature"] = _build_publication_failure_signature(context)
    return context


def _coerce_recovery_diagnosis(raw_payload: Any) -> dict[str, Any] | None:
    if not isinstance(raw_payload, dict):
        return None
    diagnosis = dict(raw_payload)
    if not all(str(diagnosis.get(key) or "").strip() for key in PUBLICATION_LLM_RECOVERY_REQUIRED_FIELDS):
        return None
    diagnosis["action"] = str(diagnosis.get("action") or "manual_check").strip()[:64]
    confidence_raw = diagnosis.get("confidence")
    try:
        confidence = float(confidence_raw)
    except Exception:
        confidence = 0.0
    diagnosis["confidence"] = max(0.0, min(1.0, confidence))
    next_steps = diagnosis.get("next_steps")
    if not isinstance(next_steps, list) or not next_steps:
        return None
    diagnosis["next_steps"] = [str(item).strip() for item in next_steps[:5] if str(item).strip()]
    if not diagnosis["next_steps"]:
        return None
    diagnosis["severity"] = str(diagnosis.get("severity") or "medium").strip()[:24] or "medium"
    evidence = diagnosis.get("evidence")
    if isinstance(evidence, list):
        diagnosis["evidence"] = [str(item).strip() for item in evidence[:8] if str(item).strip()]
    else:
        diagnosis["evidence"] = []
    rationale = str(diagnosis.get("rationale") or "").strip()
    diagnosis["rationale"] = rationale[:320]
    recovery_plan = _coerce_recovery_plan(diagnosis.get("recovery_plan"))
    if isinstance(recovery_plan, dict):
        diagnosis["recovery_plan"] = recovery_plan
    return diagnosis


async def _analyze_publication_failure_with_llm(
    attempt: PublicationAttempt,
    raw_status: str,
    task: dict[str, Any],
    *,
    response_payload: dict[str, Any],
) -> dict[str, Any] | None:
    context = _extract_publication_failure_context(attempt, raw_status, task, response_payload=response_payload)
    deterministic_diagnosis = _derive_recovery_diagnosis_from_context(context)
    if deterministic_diagnosis is not None:
        recovery_plan = deterministic_diagnosis.get("recovery_plan")
        if isinstance(recovery_plan, dict):
            recovery_plan["recovery_overrides"] = _adaptive_recovery_overrides_for_context(
                context=context,
                base_plan=recovery_plan,
                error_code=str((context.get("error") or {}).get("code") or context.get("failure_signature") or ""),
                diagnosis_action=str(deterministic_diagnosis.get("action") or "").strip(),
            )
        deterministic_diagnosis.setdefault("resolution_source", "rule")
        return deterministic_diagnosis
    if not _should_recover_with_reasoning():
        return None
    prompt = {
        "task": "你是发布异常恢复助手，只允许输出 JSON。",
        "goal": "给出对当前平台发布失败/需人工介入的可执行恢复建议。",
        "schema": {
            "severity": "low|medium|high",
            "action": "retry|manual_check|requeue|re_auth|adjust_route|verify_media|ask_user",
            "retryable": True,
            "next_steps": ["步骤1", "步骤2"],
            "confidence": 0.0,
            "evidence": ["可复用字段"],
            "rationale": "一句话说明",
            "target_adapter": "可选，重试时切换适配器（如 browser_agent / x_link_share）",
            "target_execution_mode": "可选，重试时切换执行模式（如 video / link_share / browser_agent）",
            "target_platform_specific_overrides": {"可选覆盖": True},
            "recovery_plan": {
                "duplicate_detected": False,
                "clear_draft_context": False,
                "force_publish_page_refresh": False,
                "recovery_overrides": {},
                "next_platform_specific_overrides": {},
                "reason": "可选的恢复建议说明",
            },
        },
        "context": context,
    }
    try:
        response = await asyncio.wait_for(
            get_reasoning_provider().complete(
                [
                    Message(role="system", content="你是发布故障诊断助手。仅输出合法 JSON，不输出解释。"),
                    Message(role="user", content=json.dumps(prompt, ensure_ascii=False)),
                ],
                temperature=0.15,
                max_tokens=1100,
                json_mode=True,
            ),
            timeout=PUBLICATION_LLM_RECOVERY_TIMEOUT_SEC,
        )
        raw = json.loads(extract_json_text(response.content))
        diagnosis = _coerce_recovery_diagnosis(raw)
        if isinstance(diagnosis, dict):
            diagnosis.setdefault("resolution_source", "llm")
        return diagnosis
    except Exception:
        return None


def _build_publication_recovery_summary(diagnosis: dict[str, Any]) -> str:
    next_steps = diagnosis.get("next_steps") or []
    confidence = float(diagnosis.get("confidence") or 0.0)
    summary_source = str(diagnosis.get("resolution_source") or "llm").strip().lower()
    summary_label = "规则诊断" if summary_source == "rule" else "LLM 异常诊断"
    lines = [
        f"{summary_label}：",
        f"行动={diagnosis.get('action')}，置信度={confidence:.2f}，建议程度={diagnosis.get('severity')}",
    ]
    for item in next_steps[:4]:
        lines.append(f"- {str(item).strip()}")
    if diagnosis.get("rationale"):
        lines.append(f"依据：{str(diagnosis.get('rationale')).strip()}")
    text = "\n".join(lines)
    return text if len(text) <= PUBLICATION_LLM_MAX_SUMMARY_LENGTH else text[:PUBLICATION_LLM_MAX_SUMMARY_LENGTH]


def _append_publication_recovery_comment(attempt: PublicationAttempt, *, diagnosis: dict[str, Any]) -> None:
    recovery_text = _build_publication_recovery_summary(diagnosis)
    attempt.operator_summary = (
        f"{attempt.operator_summary or _publication_status_summary(attempt.status, attempt.provider_status or '')}；{recovery_text}"
    )
    if attempt.error_message:
        attempt.error_message = (
            f"{attempt.error_message}\n\n{recovery_text}"
        )
    else:
        attempt.error_message = recovery_text


def _normalize_scheduled_publish_at(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$", text):
        return text
    parsed = _parse_datetime(text)
    if parsed is not None:
        return parsed.isoformat()
    return text[:64]


def _normalize_collection_option(value: dict[str, Any]) -> dict[str, str] | None:
    raw_collection = value.get("collection")
    if isinstance(raw_collection, dict):
        collection_id = str(raw_collection.get("id") or raw_collection.get("collection_id") or "").strip()
        collection_name = str(raw_collection.get("name") or raw_collection.get("title") or raw_collection.get("label") or "").strip()
    else:
        collection_id = str(value.get("collection_id") or "").strip()
        collection_name = str(value.get("collection_name") or raw_collection or "").strip()
    if not collection_id and not collection_name:
        return None
    collection: dict[str, str] = {}
    if collection_id:
        collection["id"] = collection_id[:160]
    if collection_name:
        collection["name"] = collection_name[:160]
    return collection


def map_browser_agent_publication_status(raw_status: Any) -> str:
    status = str(raw_status or "").strip().lower().replace("-", "_")
    if status in {"published", "draft_created", "scheduled_pending"}:
        return status
    if status in {"queued", "submitted", "created", "pending"}:
        return "submitted"
    if status in {"running", "processing", "uploading", "publishing", "reconciling"}:
        return "processing"
    if status in BROWSER_AGENT_HUMAN_STATUSES:
        return "needs_human"
    if status in BROWSER_AGENT_RETRYABLE_STATUSES or status in BROWSER_AGENT_FAILED_STATUSES:
        return "failed"
    return "failed" if status else "processing"


async def _apply_browser_agent_task_state(
    attempt: PublicationAttempt,
    run: PublicationAttemptRun | None,
    task: dict[str, Any],
    *,
    response_payload: dict[str, Any],
) -> None:
    now = _utc_now()
    raw_status = str(task.get("status") or task.get("state") or "").strip()
    mapped_status = map_browser_agent_publication_status(raw_status)
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    error = task.get("error") if isinstance(task.get("error"), dict) else {}
    audit = result.get("publication_audit") if isinstance(result.get("publication_audit"), dict) else {}
    context = _extract_publication_failure_context(attempt, raw_status=raw_status, task=task, response_payload=response_payload)
    bound_receipt_verification_success = _has_bound_receipt_verification_success(
        raw_status=raw_status,
        context=context,
        audit=audit if isinstance(audit, dict) else None,
    )
    stop_before_verification_success = _has_verified_stop_before_final_publish_success(
        raw_status=raw_status,
        result=result,
        audit=audit if isinstance(audit, dict) else None,
    )
    if bound_receipt_verification_success:
        mapped_status = "published"
    elif stop_before_verification_success:
        mapped_status = "draft_created"
    request_payload = getattr(attempt, "request_payload", None)
    request_payload = request_payload if isinstance(request_payload, dict) else {}
    request_content_signature = _extract_publication_content_signature(request_payload)
    result_content_signature = _extract_publication_content_signature(result)
    request_signature_fields = _extract_publication_signature_fields(request_payload)
    result_signature_fields = _extract_publication_signature_fields(result)
    if not result_signature_fields:
        result_signature_fields = _extract_publication_signature_fields(task)
    if not result_signature_fields:
        result_signature_fields = _extract_publication_field_snapshot(result)
    if not result_signature_fields:
        result_signature_fields = _extract_publication_field_snapshot(task)
    structured_success_evidence_present = bool(
        audit
        or result_content_signature
        or result_signature_fields
        or raw_status.strip().lower().replace("-", "_") == "verified"
        or isinstance(result.get("material_integrity"), dict)
        or isinstance(result.get("final_publish"), dict)
    )
    strict_success_verification = (
        str(getattr(attempt, "platform", "") or "").strip().lower() in STABLE_PUBLICATION_PLATFORM_SET
        and str(_normalize_publication_adapter(getattr(attempt, "adapter", ""))) != X_LINK_SHARE_PUBLICATION_ADAPTER
        and structured_success_evidence_present
    )
    request_scheduled_publish_at = str(request_payload.get("scheduled_publish_at") or "").strip()
    audit_failures = [
        str(item).strip()
        for item in (audit.get("required_unverified") or [])
        if str(item).strip()
    ] if isinstance(audit, dict) else []
    audit_reupload_failures = [
        str(item).strip()
        for item in (audit.get("required_reupload") or [])
        if str(item).strip()
    ] if isinstance(audit, dict) else []
    strict_audit_required = (
        str(getattr(attempt, "platform", "") or "").strip().lower() in STABLE_PUBLICATION_PLATFORMS
        and structured_success_evidence_present
    )
    if mapped_status in PUBLICATION_SUCCESS_STATUSES and (
        (strict_audit_required and not isinstance(audit, dict))
        or (audit and (audit.get("verified") is False or audit_failures or audit_reupload_failures))
    ):
        missing_details = (
            (["publication_audit_missing"] if strict_audit_required and not isinstance(audit, dict) else [])
            + audit_failures
            + audit_reupload_failures
        )
        mapped_status = "needs_human"
        error = {
            "code": "publication_audit_unverified",
            "message": "browser-agent 读到平台回执，但发布物料审计未通过："
            + ("、".join(missing_details) if missing_details else "unknown"),
        }

    attempt.provider_status = raw_status or attempt.provider_status
    attempt.provider_task_id = str(task.get("task_id") or task.get("id") or attempt.provider_task_id or "").strip() or None
    attempt.provider_execution_id = str(task.get("execution_id") or task.get("run_id") or attempt.provider_execution_id or "").strip() or None
    attempt.response_payload = response_payload
    if mapped_status == "published":
        attempt.published_at = _parse_datetime(task.get("published_at") or result.get("published_at")) or now
    if mapped_status == "scheduled_pending":
        attempt.scheduled_at = _parse_datetime(task.get("scheduled_publish_at") or result.get("scheduled_publish_at")) or attempt.scheduled_at
    external_post_id = str(result.get("post_id") or task.get("post_id") or "").strip()
    if external_post_id:
        attempt.external_post_id = external_post_id
    external_receipt_id = str(result.get("receipt_id") or task.get("receipt_id") or "").strip()
    if not external_receipt_id and _has_bound_receipt_target(context):
        binding = context.get("receipt_binding") if isinstance(context.get("receipt_binding"), dict) else {}
        external_receipt_id = _derive_receipt_binding_fallback_id(binding)
    if external_receipt_id:
        attempt.external_receipt_id = external_receipt_id
    public_url = _first_public_url(
        result,
        task,
        result.get("final_publish") if isinstance(result.get("final_publish"), dict) else {},
    )
    if public_url:
        attempt.external_url = public_url
    if strict_success_verification and not bound_receipt_verification_success:
        if mapped_status == "published":
            if not public_url:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_public_url_missing",
                    "message": "平台反馈为发布成功，但未读到可公开访问链接；请核对发布结果。",
                }
            elif not result_content_signature and request_content_signature:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_signature_missing",
                    "message": "平台反馈为发布成功，但未返回内容签名；请核验发布是否读回了发布计划。",
                }
            elif request_signature_fields and not result_signature_fields:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_signature_fields_missing",
                    "message": "平台反馈为发布成功，但未返回签名字段；请核对发布页是否按计划落地。",
                }
            elif request_content_signature and result_content_signature and request_content_signature != result_content_signature:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_signature_mismatch",
                    "message": "平台回执内容签名与发布计划不一致；请避免草稿污染后重新发起。",
                }
            elif request_signature_fields and request_signature_fields != result_signature_fields:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_signature_fields_mismatch",
                    "message": "平台回执签名字段与发布计划字段不一致；请避免草稿污染后重试。",
                }
            elif request_scheduled_publish_at and not attempt.scheduled_at:
                mapped_status = "needs_human"
                error = {
                    "code": "publication_schedule_receipt_missing",
                    "message": "发布成功反馈，但未读到预约时间回执；请核对发布时间是否已写入。",
                }
        elif mapped_status == "scheduled_pending" and request_scheduled_publish_at and not attempt.scheduled_at:
            mapped_status = "needs_human"
            error = {
                "code": "publication_schedule_receipt_missing",
                "message": "发布反馈为预约中，但未读到预约时间回执；请确认发布页是否真正落定。",
            }
    attempt.status = mapped_status
    attempt.run_status = mapped_status
    error_code = str(error.get("code") or task.get("error_code") or raw_status or "").strip()
    error_message = str(error.get("message") or task.get("error_message") or "").strip()
    auto_recovered = False
    if mapped_status in {"failed", "needs_human"}:
        attempt.error_code = error_code or mapped_status
        attempt.error_message = error_message or _publication_status_summary(mapped_status, raw_status)
        diagnosis = await _analyze_publication_failure_with_llm(
            attempt,
            raw_status=raw_status,
            task=task,
            response_payload=response_payload,
        )
        if diagnosis:
            _append_publication_recovery_comment(attempt, diagnosis=diagnosis)
            if _should_auto_recover_publication_failure(
                attempt,
                mapped_status=mapped_status,
                diagnosis=diagnosis,
            ):
                _apply_publication_auto_recovery(
                    attempt,
                    run,
                    now=now,
                    diagnosis=diagnosis,
                    mapped_status=mapped_status,
                    context=context,
                )
                auto_recovered = True
        if not auto_recovered:
            attempt.run_status = mapped_status
            attempt.operator_summary = _publication_status_summary(mapped_status, raw_status)
            attempt.next_retry_at = None
    elif mapped_status in {"submitted", "processing", "published", "draft_created", "scheduled_pending"}:
        attempt.error_code = None
        attempt.error_message = None
        if bound_receipt_verification_success:
            attempt.operator_summary = "已通过发布后回执绑定确认本次作品。"
        elif stop_before_verification_success:
            attempt.operator_summary = "已完成发布前验证，并安全停在最终发布前。"
        else:
            attempt.operator_summary = _publication_status_summary(mapped_status, raw_status)

    if run is not None and not auto_recovered:
        run.status = mapped_status
        run.phase = "reconcile" if mapped_status in {"submitted", "processing"} else "completed"
        run.heartbeat_at = now
        run.provider_task_id = attempt.provider_task_id
        run.provider_execution_id = attempt.provider_execution_id
        run.provider_status = attempt.provider_status
        run.result_json = response_payload
        run.error_message = attempt.error_message
        if mapped_status in PUBLICATION_TERMINAL_STATUSES or mapped_status == "scheduled_pending":
            run.completed_at = now


def _mark_publication_attempt_failed(
    attempt: PublicationAttempt,
    run: PublicationAttemptRun | None,
    *,
    code: str,
    message: str,
    retryable: bool,
) -> None:
    now = _utc_now()
    can_retry = retryable and int(attempt.retry_count or 0) < int(attempt.max_retries or 0)
    attempt.error_code = code
    attempt.error_message = message
    if can_retry:
        attempt.retry_count = int(attempt.retry_count or 0) + 1
        attempt.status = "queued"
        attempt.run_status = "retry_scheduled"
        attempt.next_retry_at = now + timedelta(seconds=min(900, 30 * (2 ** max(0, attempt.retry_count - 1))))
        adapter_label = _publication_adapter_display_name(attempt.adapter)
        attempt.operator_summary = f"{adapter_label} 暂不可用，已安排第 {attempt.retry_count} 次重试。"
        run_status = "retry_scheduled"
    else:
        attempt.status = "failed"
        attempt.run_status = "failed"
        attempt.operator_summary = f"发布失败：{message}"
        run_status = "failed"
    if run is not None:
        run.status = run_status
        run.phase = "submit"
        run.heartbeat_at = now
        run.completed_at = now
        run.error_message = message


async def _latest_publication_run(session: AsyncSession, attempt_id: str) -> PublicationAttemptRun | None:
    result = await session.execute(
        select(PublicationAttemptRun)
        .where(PublicationAttemptRun.attempt_id == attempt_id)
        .order_by(PublicationAttemptRun.created_at.desc(), PublicationAttemptRun.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _browser_agent_request_json(
    method: str,
    path: str,
    *,
    base_url: str,
    auth_token: str = "",
    json_payload: dict[str, Any] | None = None,
    http_client: Any | None = None,
    request_timeout_sec: int = 60,
) -> dict[str, Any]:
    normalized_base_url = str(base_url or "").strip().rstrip("/")
    if not normalized_base_url:
        raise RuntimeError("publication_browser_agent_base_url is empty")
    headers: dict[str, str] = {}
    token = str(auth_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{normalized_base_url}{path}"
    if http_client is not None:
        if method.upper() == "POST":
            response = await http_client.post(url, json=json_payload or {}, headers=headers)
        else:
            response = await http_client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"result": payload}
    timeout = httpx.Timeout(float(max(5, request_timeout_sec)), connect=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        if method.upper() == "POST":
            response = await client.post(url, json=json_payload or {}, headers=headers)
        else:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"result": payload}


def _extract_browser_agent_task(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("task", "data", "result"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict) and (value.get("status") or value.get("state") or value.get("task_id") or value.get("id")):
            return value
    return payload if isinstance(payload, dict) else {}


def _first_public_url(*payloads: dict[str, Any]) -> str | None:
    for payload in payloads:
        for key in ("public_url", "post_url", "url", "external_url"):
            value = str(payload.get(key) or "").strip()
            if value and _looks_like_public_publication_url(value):
                return value
    return None


def _looks_like_public_publication_url(value: str) -> bool:
    text = value.strip().lower()
    if not text.startswith(("http://", "https://")):
        return False
    backstage_tokens = ("creator", "studio", "manager", "admin", "dashboard", "publish", "draft")
    return not any(token in text for token in backstage_tokens)


def _extract_publication_content_signature(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    signature_payload = (
        payload.get("publication_content_signature")
        or payload.get("content_signature")
        or payload.get("publication_plan_signature")
    )
    if isinstance(signature_payload, dict):
        return str(signature_payload.get("value") or "").strip()
    return str(signature_payload or "").strip()


def _extract_publication_dedupe_signature(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    signature_payload = payload.get("publication_dedupe_signature")
    if isinstance(signature_payload, dict):
        return str(signature_payload.get("value") or "").strip()
    if isinstance(signature_payload, str) and signature_payload.strip():
        return signature_payload.strip()

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    capability = payload.get("publication_capability") if isinstance(payload.get("publication_capability"), dict) else {}
    signature_fields = _extract_publication_signature_fields(payload)
    media_items = [item for item in (payload.get("media_items") or []) if isinstance(item, dict)]
    media_path = ""
    for item in media_items:
        media_path = str(item.get("local_path") or "").strip()
        if media_path:
            break
    if not media_path:
        media_urls = [str(item).strip() for item in (payload.get("media_urls") or []) if str(item).strip()]
        media_path = media_urls[0] if media_urls else ""
    dedupe_signature = _build_publication_dedupe_signature_payload(
        platform=str(
            payload.get("platform")
            or capability.get("platform")
            or metadata.get("platform")
            or signature_fields.get("platform")
            or ""
        ).strip(),
        adapter=str(
            payload.get("adapter")
            or capability.get("adapter")
            or metadata.get("adapter")
            or ""
        ).strip(),
        creator_profile_id=str(metadata.get("creator_profile_id") or "").strip(),
        browser_profile_id=str(metadata.get("browser_profile_id") or "").strip(),
        credential_id=str(metadata.get("credential_id") or "").strip(),
        credential_ref=str(metadata.get("credential_ref") or "").strip(),
        account_label=str(metadata.get("account_label") or "").strip(),
        content_kind=str(payload.get("content_kind") or "").strip(),
        media_path=media_path,
        title=str(payload.get("title") or "").strip(),
        body=str(payload.get("body") or "").strip(),
        tags=[str(item).strip() for item in (payload.get("hashtags") or []) if str(item).strip()],
    )
    return str(dedupe_signature.get("value") or "").strip()


def _extract_publication_logical_signature(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    signature_payload = payload.get("publication_logical_signature")
    if isinstance(signature_payload, dict):
        return str(signature_payload.get("value") or "").strip()
    if isinstance(signature_payload, str) and signature_payload.strip():
        return signature_payload.strip()

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    capability = payload.get("publication_capability") if isinstance(payload.get("publication_capability"), dict) else {}
    signature_fields = _extract_publication_signature_fields(payload)
    media_items = [item for item in (payload.get("media_items") or []) if isinstance(item, dict)]
    media_path = ""
    for item in media_items:
        media_path = str(item.get("local_path") or "").strip()
        if media_path:
            break
    if not media_path:
        media_urls = [str(item).strip() for item in (payload.get("media_urls") or []) if str(item).strip()]
        media_path = media_urls[0] if media_urls else ""
    logical_signature = _build_publication_logical_signature_payload(
        platform=str(
            payload.get("platform")
            or capability.get("platform")
            or metadata.get("platform")
            or signature_fields.get("platform")
            or ""
        ).strip(),
        content_kind=str(payload.get("content_kind") or "").strip(),
        media_path=media_path,
        title=str(payload.get("title") or "").strip(),
        body=str(payload.get("body") or "").strip(),
        tags=[str(item).strip() for item in (payload.get("hashtags") or []) if str(item).strip()],
    )
    return str(logical_signature.get("value") or "").strip()


def _extract_publication_signature_fields(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    signature_payload = (
        payload.get("publication_content_signature")
        or payload.get("content_signature")
        or payload.get("publication_plan_signature")
    )
    if isinstance(signature_payload, dict):
        fields = signature_payload.get("fields")
        if isinstance(fields, dict):
            return fields
    return {}


def _extract_publication_field_snapshot(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    task_payload = _extract_browser_agent_task(payload)
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    if (
        isinstance(task_payload, dict)
        and task_payload
        and not bool(task_result)
        and not bool(task_payload.get("error"))
        and not bool(task_progress)
        and not payload.get("publication_field_snapshot")
        and not payload.get("result")
        and not payload.get("error")
    ):
        return {}

    def _coerce_snapshot_value(raw_value: Any) -> Any:
        if raw_value is None:
            return None
        if isinstance(raw_value, (list, tuple)):
            return [_coerce_snapshot_value(item) for item in raw_value]
        if isinstance(raw_value, dict):
            if "actual" in raw_value and raw_value["actual"] is not None:
                return _coerce_snapshot_value(raw_value["actual"])
            if "value" in raw_value and raw_value["value"] is not None:
                return _coerce_snapshot_value(raw_value["value"])
            if "expected" in raw_value and raw_value["expected"] is not None:
                return _coerce_snapshot_value(raw_value["expected"])
            return {str(k).strip(): _coerce_snapshot_value(v) for k, v in raw_value.items() if isinstance(k, str) and k.strip()}
        return raw_value

    def _normalize_schedule_snapshot_value(raw_value: Any) -> Any:
        text = str(raw_value or "").strip()
        if not text:
            return None
        if "T" in text:
            return text
        if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", text):
            return text.replace(" ", "T")
        return text

    def _extract_material_integrity_payload(container: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(container, dict):
            return {}
        material_integrity = container.get("material_integrity")
        if isinstance(material_integrity, dict) and material_integrity:
            return material_integrity
        actions = container.get("actions")
        if isinstance(actions, list):
            for item in reversed(actions):
                if not isinstance(item, dict):
                    continue
                if not isinstance(item.get("fields"), dict):
                    continue
                kind = str(item.get("kind") or "").strip().lower()
                if "material_integrity" not in kind:
                    continue
                return {
                    "fields": item.get("fields"),
                    "failures": item.get("failures"),
                    "platform": item.get("platform"),
                    "verified": item.get("verified"),
                }
        return {}

    def _extract_from_material_integrity(container: dict[str, Any] | None) -> dict[str, Any]:
        material_integrity = _extract_material_integrity_payload(container)
        fields = material_integrity.get("fields") if isinstance(material_integrity.get("fields"), dict) else {}
        if not fields:
            return {}
        snapshot: dict[str, Any] = {}
        title_field = fields.get("title") if isinstance(fields.get("title"), dict) else {}
        body_field = fields.get("body") if isinstance(fields.get("body"), dict) else {}
        tags_field = fields.get("tags") if isinstance(fields.get("tags"), dict) else {}
        schedule_field = fields.get("schedule") if isinstance(fields.get("schedule"), dict) else {}
        collection_field = fields.get("collection") if isinstance(fields.get("collection"), dict) else {}
        declaration_field = fields.get("declaration") if isinstance(fields.get("declaration"), dict) else {}
        title_value = str(title_field.get("actual") if title_field.get("actual") is not None else title_field.get("expected") or "").strip()
        body_value = str(body_field.get("actual") if body_field.get("actual") is not None else body_field.get("expected") or "").strip()
        tags_value = tags_field.get("actual")
        if not isinstance(tags_value, list) or not tags_value:
            tags_value = tags_field.get("expected") if isinstance(tags_field.get("expected"), list) else []
        if title_value:
            snapshot["title"] = title_value
        if body_value:
            snapshot["body"] = body_value
        if tags_value:
            normalized_tags = [str(tag).strip() for tag in tags_value if str(tag or "").strip()]
            if normalized_tags:
                snapshot["hashtags"] = normalized_tags
                snapshot["structured_tags"] = list(normalized_tags)
                snapshot["display_hashtags"] = [
                    tag if tag.startswith("#") else f"#{tag}"
                    for tag in normalized_tags
                ]
        schedule_value = _normalize_schedule_snapshot_value(
            schedule_field.get("actual") if schedule_field.get("actual") is not None else schedule_field.get("expected")
        )
        if schedule_value:
            snapshot["scheduled_publish_at"] = schedule_value
        collection_value = _coerce_snapshot_value(
            collection_field.get("actual") if collection_field.get("actual") is not None else collection_field.get("expected")
        )
        if collection_value not in (None, "", [], {}):
            snapshot["collection"] = collection_value
        declaration_value = str(
            declaration_field.get("actual") if declaration_field.get("actual") is not None else declaration_field.get("expected") or ""
        ).strip()
        if declaration_value:
            snapshot["declaration"] = declaration_value
        platform_value = str(material_integrity.get("platform") or container.get("platform") or "").strip()
        if platform_value:
            snapshot["platform"] = platform_value
        return snapshot

    def _extract_from_dict(container: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(container, dict):
            return {}
        candidates: list[tuple[int, dict[str, Any]]] = []

        def _push_candidate(snapshot: dict[str, Any] | None, priority: int) -> None:
            if not isinstance(snapshot, dict) or not snapshot:
                return
            candidates.append((priority, snapshot))

        explicit_snapshot = container.get("publication_field_snapshot")
        if isinstance(explicit_snapshot, dict) and explicit_snapshot:
            _push_candidate(
                {
                    str(key).strip(): _coerce_snapshot_value(value)
                    for key, value in explicit_snapshot.items()
                    if str(key).strip()
                },
                1,
            )
        direct_fields = container.get("fields") if isinstance(container.get("fields"), dict) else {}
        if isinstance(direct_fields, dict) and direct_fields:
            _push_candidate(
                {str(key).strip(): _coerce_snapshot_value(value) for key, value in direct_fields.items() if str(key).strip()},
                2,
            )
        integrity_fields = _extract_from_material_integrity(container)
        if integrity_fields:
            _push_candidate(integrity_fields, 5)
        audit_payload = container.get("publication_audit") if isinstance(container.get("publication_audit"), dict) else {}
        checklist = audit_payload.get("checklist") if isinstance(audit_payload.get("checklist"), dict) else {}
        if checklist:
            _push_candidate(
                {
                    str(key).strip(): _coerce_snapshot_value(value)
                    for key, value in checklist.items()
                    if str(key).strip()
                },
                3,
            )
        details = container.get("details") if isinstance(container.get("details"), dict) else {}
        if isinstance(details, dict):
            for stage in ("after", "before"):
                stage_payload = details.get(stage)
                if isinstance(stage_payload, dict):
                    stage_fields = stage_payload.get("fields")
                    if isinstance(stage_fields, dict) and stage_fields:
                        _push_candidate(
                            {
                                str(key).strip(): _coerce_snapshot_value(value)
                                for key, value in stage_fields.items()
                                if str(key).strip()
                            },
                            4 if stage == "after" else 3,
                        )
        timeout_progress = container.get("timeout_progress") if isinstance(container.get("timeout_progress"), dict) else {}
        if timeout_progress:
            timeout_snapshot = _extract_from_dict(timeout_progress)
            if timeout_snapshot:
                _push_candidate(timeout_snapshot, 6)
        if not candidates:
            return {}

        def _candidate_score(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
            priority, snapshot = item
            field_count = len([key for key, value in snapshot.items() if value not in (None, "", [], {})])
            has_schedule = int(bool(snapshot.get("scheduled_publish_at")))
            has_body = int(bool(snapshot.get("body")))
            has_tags = int(bool(snapshot.get("hashtags") or snapshot.get("display_hashtags") or snapshot.get("structured_tags")))
            return (field_count, has_schedule, has_body + has_tags, priority)

        return max(candidates, key=_candidate_score)[1]

    top_candidates: list[tuple[int, dict[str, Any]]] = []

    def _push_top(snapshot: dict[str, Any] | None, priority: int) -> None:
        if isinstance(snapshot, dict) and snapshot:
            top_candidates.append((priority, snapshot))

    _push_top(_extract_from_dict(payload), 1)
    error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    if isinstance(error_payload, dict):
        _push_top(_extract_from_dict(error_payload), 2)
    _push_top(_extract_from_dict(task_progress), 6)
    _push_top(_extract_from_dict(task_result), 5)
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    if isinstance(result_payload, dict):
        _push_top(_extract_from_dict(result_payload), 4)
    _push_top(_extract_from_dict(task_payload), 3)
    if not top_candidates:
        return {}

    def _top_score(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        priority, snapshot = item
        field_count = len([key for key, value in snapshot.items() if value not in (None, "", [], {})])
        has_schedule = int(bool(snapshot.get("scheduled_publish_at")))
        has_body = int(bool(snapshot.get("body")))
        has_tags = int(bool(snapshot.get("hashtags") or snapshot.get("display_hashtags") or snapshot.get("structured_tags")))
        return (field_count, has_schedule, has_body + has_tags, priority)

    return max(top_candidates, key=_top_score)[1]


def _publication_status_summary(mapped_status: str, raw_status: str) -> str:
    platform_status = f"（平台状态：{raw_status}）" if raw_status else ""
    if mapped_status == "published":
        return f"已发布并完成公开状态对账{platform_status}。"
    if mapped_status == "scheduled_pending":
        return f"已预约发布，尚未公开{platform_status}。"
    if mapped_status == "draft_created":
        return f"已创建平台草稿，需要人工确认公开{platform_status}。"
    if mapped_status == "needs_human":
        return f"需要人工介入{platform_status}。"
    if mapped_status == "processing":
        return f"发布执行中{platform_status}。"
    if mapped_status == "submitted":
        return f"任务已提交，等待执行{platform_status}。"
    return f"发布失败{platform_status}。"


def _build_publication_content_signature_payload(
    *,
    platform: str,
    title: str,
    body: str,
    tags: list[str],
    native_topics: list[str],
    collection: dict[str, str] | None,
    category: str | None,
    visibility_or_publish_mode: str | None,
    scheduled_publish_at: str | None,
    declaration: str | None,
    cover_path: str | None,
    cover_slots: list[dict[str, Any]] | None,
    media_path: str,
) -> dict[str, Any]:
    content_fields = {
        "platform": platform,
        "title": title,
        "body": body,
        "tags": tags[:24],
        "native_topics": native_topics[:16],
        "collection": collection,
        "category": category,
        "visibility_or_publish_mode": visibility_or_publish_mode,
        "scheduled_publish_at": scheduled_publish_at,
        "declaration": declaration,
        "cover_path": cover_path,
        "cover_slots": [dict(item) for item in (cover_slots or []) if isinstance(item, dict)],
        "media_path": media_path,
    }
    return {
        "version": 1,
        "value": hashlib.sha256(
            json.dumps(content_fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "fields": content_fields,
    }


def _normalize_publication_dedupe_media_path(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        candidate = Path(raw).expanduser()
        if candidate.exists():
            candidate = candidate.resolve()
        raw = str(candidate)
    except (OSError, RuntimeError, ValueError):
        raw = str(value or "").strip()
    return re.sub(r"[\\/]+", "/", raw).lower()


def _build_publication_dedupe_signature_payload(
    *,
    platform: str,
    adapter: str,
    creator_profile_id: str | None,
    browser_profile_id: str | None,
    credential_id: str | None,
    credential_ref: str | None,
    account_label: str | None,
    content_kind: str | None,
    media_path: str | None,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    normalized_media_path = _normalize_publication_dedupe_media_path(media_path)
    normalized_tags = [
        str(item).strip().lstrip("#")
        for item in (tags or [])
        if str(item).strip()
    ]
    dedupe_fields = {
        "platform": str(platform or "").strip().lower(),
        "adapter": str(adapter or "").strip().lower(),
        "creator_profile_id": str(creator_profile_id or "").strip(),
        "browser_profile_id": str(browser_profile_id or "").strip(),
        "credential_ref": str(credential_ref or "").strip(),
        "account_label": str(account_label or "").strip(),
        "content_kind": str(content_kind or "").strip().lower(),
        "media_path": normalized_media_path,
    }
    if not normalized_media_path:
        dedupe_fields.update(
            {
                "title": re.sub(r"\s+", " ", str(title or "")).strip(),
                "body": re.sub(r"\s+", " ", str(body or "")).strip(),
                "tags": sorted(normalized_tags),
            }
        )
    return {
        "version": 1,
        "value": hashlib.sha256(
            json.dumps(dedupe_fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "fields": dedupe_fields,
    }


def _build_publication_logical_signature_payload(
    *,
    platform: str,
    content_kind: str | None,
    media_path: str | None,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    normalized_media_path = _normalize_publication_dedupe_media_path(media_path)
    normalized_tags = sorted(
        {
            str(item).strip().lstrip("#")
            for item in (tags or [])
            if str(item).strip()
        }
    )
    logical_fields = {
        "platform": str(platform or "").strip().lower(),
        "content_kind": str(content_kind or "").strip().lower(),
    }
    if normalized_media_path:
        logical_fields["media_path"] = normalized_media_path
    else:
        logical_fields.update(
            {
                "title": re.sub(r"\s+", " ", str(title or "")).strip(),
                "body": re.sub(r"\s+", " ", str(body or "")).strip(),
                "tags": normalized_tags,
            }
        )
    return {
        "version": 1,
        "value": hashlib.sha256(
            json.dumps(logical_fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "fields": logical_fields,
    }


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=DEFAULT_PUBLICATION_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _build_request_payload(*, plan: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    tags = [str(item).strip().lstrip("#") for item in (target.get("tags") or []) if str(item).strip()]
    native_topics = _coerce_publication_topic_list(target.get("native_topics"))
    raw_media_path = str(plan.get("media_path") or "").strip()
    raw_source_media_path = str(plan.get("source_media_path") or "").strip()
    resolved_media_path = resolve_publication_local_media_path(raw_media_path)
    media_path = str(resolved_media_path) if resolved_media_path else ""
    platform = str(target.get("platform") or "").strip().lower()
    requires_local_media = PLATFORM_LOCAL_MEDIA_REQUIRED.get(platform, True)
    adapter = _normalize_publication_adapter(target.get("adapter"))
    platform_specific_overrides = target.get("platform_specific_overrides")
    if not isinstance(platform_specific_overrides, dict):
        platform_specific_overrides = {}
    x_share_link = str(
        platform_specific_overrides.get("x_share_link")
        or platform_specific_overrides.get("x_share_url")
        or ""
    ).strip()
    raw_body = str(target.get("body") or "").strip()
    x_link_share = platform == "x" and bool(x_share_link) and adapter == X_LINK_SHARE_PUBLICATION_ADAPTER
    body = (
        (f"{raw_body}\n{x_share_link}" if raw_body else x_share_link)
        if x_link_share
        else raw_body
    )
    title = str(target.get("title") or "").strip()
    default_declaration = platform_default_declaration(platform)
    collection = target.get("collection") if isinstance(target.get("collection"), dict) else None
    collection_name = str(target.get("collection_name") or "").strip()
    if collection is None and collection_name:
        collection = {"name": collection_name}
    scheduled_publish_at = str(target.get("scheduled_publish_at") or "").strip() or None
    visibility_or_publish_mode = str(target.get("visibility_or_publish_mode") or "").strip() or None
    if platform == "youtube":
        visibility_or_publish_mode = _normalize_youtube_visibility_or_publish_mode(
            visibility_or_publish_mode,
            scheduled_publish_at=scheduled_publish_at,
        )
    category = _sanitize_publication_target_category(platform, target.get("category"))
    content_kind = str(target.get("content_kind") or "video").strip().lower() or "video"
    declaration = str(target.get("declaration") or default_declaration).strip() or None
    cover_path, cover_slots = _resolve_authoritative_publication_cover_contract(
        target,
        platform=platform,
        requested_media_path=raw_source_media_path or raw_media_path,
    )
    publication_plan_signature_source = {
        "platform": platform,
        "adapter": adapter,
        "title": title,
        "body": body,
        "tags": tags,
        "native_topics": native_topics,
        "collection": collection,
        "category": category,
        "visibility_or_publish_mode": visibility_or_publish_mode,
        "scheduled_publish_at": scheduled_publish_at,
        "cover_path": cover_path,
        "cover_slots": cover_slots,
        "declaration": declaration,
        "x_share_link": x_share_link if x_link_share else None,
        "media_path": media_path,
    }
    publication_plan_signature = {
        "version": 1,
        "value": hashlib.sha256(
            json.dumps(publication_plan_signature_source, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "fields": publication_plan_signature_source,
    }
    publication_content_signature = _build_publication_content_signature_payload(
        platform=platform,
        title=title,
        body=body,
        tags=tags,
        native_topics=native_topics,
        collection=collection,
        category=category,
        visibility_or_publish_mode=visibility_or_publish_mode,
        scheduled_publish_at=scheduled_publish_at,
        declaration=declaration,
        cover_path=cover_path,
        cover_slots=cover_slots,
        media_path=media_path,
    )
    publication_dedupe_signature = _build_publication_dedupe_signature_payload(
        platform=platform,
        adapter=adapter,
        creator_profile_id=str(plan.get("creator_profile_id") or ""),
        browser_profile_id=str(
            target.get("browser_profile_id")
            or target.get("credential_ref")
            or target.get("account_label")
            or target.get("platform")
            or ""
        ),
        credential_id=str(target.get("credential_id") or ""),
        credential_ref=str(target.get("credential_ref") or ""),
        account_label=str(target.get("account_label") or ""),
        content_kind=content_kind,
        media_path=media_path,
        title=title,
        body=body,
        tags=tags,
    )
    publication_logical_signature = _build_publication_logical_signature_payload(
        platform=platform,
        content_kind=content_kind,
        media_path=media_path,
        title=title,
        body=body,
        tags=tags,
    )
    session_binding = build_publication_browser_session_binding(
        platform=platform,
        creator_profile_id=plan.get("creator_profile_id"),
        browser_profile_id=(
            target.get("browser_profile_id")
            or target.get("credential_ref")
            or target.get("account_label")
            or target.get("platform")
        ),
        credential_ref=target.get("credential_ref"),
        account_label=target.get("account_label"),
        browser_binding=target.get("browser_binding"),
        allowed_route_contexts=target.get("allowed_route_contexts"),
    )
    return {
        "title": title,
        "body": (
            body
            if body
            else (f"转发内容：{x_share_link}" if platform == "x" and x_link_share and adapter == X_LINK_SHARE_PUBLICATION_ADAPTER else "")
        ),
        "declaration": declaration,
        "content_kind": content_kind,
        "hashtags": tags,
        "display_hashtags": [f"#{tag}" for tag in tags],
        "structured_tags": tags,
        "native_topics": native_topics,
        "category": category,
        "collection": collection,
        "cover_path": cover_path,
        "cover_slots": cover_slots,
        "copy_material": (
            {
                **(target.get("copy_material") if isinstance(target.get("copy_material"), dict) else {}),
                "cover_path": cover_path,
                "cover_slots": cover_slots,
            }
        ),
        "visibility_or_publish_mode": visibility_or_publish_mode,
        "scheduled_publish_at": scheduled_publish_at,
        "ui_control_semantics": {
            "schedule_publish": bool(scheduled_publish_at),
            "collection_select": bool(collection),
        },
        "platform_specific_overrides": target.get("platform_specific_overrides") or {},
        "media_items": [
            {
                "kind": "video",
                "local_path": media_path,
                "source_url": None,
                "uploaded_url": None,
                "mime_type": "video/mp4",
            }
        ]
        if media_path and requires_local_media and not x_link_share
        else [],
        "media_urls": [media_path] if media_path and requires_local_media and not x_link_share else [],
        "publication_plan_signature": publication_plan_signature,
        "publication_content_signature": publication_content_signature,
        "publication_dedupe_signature": publication_dedupe_signature,
        "publication_logical_signature": publication_logical_signature,
        "metadata": {
            "adapter": _normalize_publication_adapter(target.get("adapter")),
            "browser_profile_id": str(
                target.get("browser_profile_id")
                or target.get("credential_ref")
                or target.get("account_label")
                or target.get("platform")
                or ""
            ),
            "credential_id": str(target.get("credential_id") or ""),
            "credential_ref": str(target.get("credential_ref") or ""),
            "account_label": str(target.get("account_label") or ""),
            "browser_binding": target.get("browser_binding") if isinstance(target.get("browser_binding"), dict) else {},
            "session_binding": session_binding,
            "creator_profile_id": str(plan.get("creator_profile_id") or ""),
            "creator_profile_name": str(plan.get("creator_profile_name") or ""),
            "publication_guard": plan.get("publication_guard") or {},
            "requested_media_path": raw_source_media_path or raw_media_path or None,
            "resolved_media_path": media_path or None,
            "requested_cover_path": str(cover_path or "").strip() or None,
            "media_path_unreadable": bool(raw_media_path and not media_path and requires_local_media and not x_link_share),
        },
        "publication_capability": {
            "adapter": _normalize_publication_adapter(target.get("adapter")),
            "platform": str(target.get("platform") or ""),
            "requires_local_media": requires_local_media,
            "supports_scheduled_publish": platform_supports_scheduled_publish(platform),
            "supports_collection_select": platform_requires_explicit_collection_policy(platform),
            "publish_entry_url": platform_publish_entry_url(platform),
            "draft_resume_policy": platform_draft_resume_policy(platform),
            "cover_asset_policy": platform_cover_asset_policy(platform),
            "cover_project_mode": platform_cover_project_mode(platform),
            "allow_field_edits_while_processing": platform_allows_field_edits_while_processing(platform),
            "stop_when_current_page_already_correct": platform_stop_when_current_page_already_correct(platform),
            "upload_processing_blocks_final_publish_only": platform_upload_processing_blocks_final_publish_only(platform),
            "publish_projects": platform_publish_projects(platform),
        },
        "validation_contract": _resolve_publication_adapter_publication_contract(target.get("adapter")),
    }


def _extract_publication_plan_signature(request_payload: dict[str, Any] | None) -> str:
    if not isinstance(request_payload, dict):
        return ""
    raw_signature = request_payload.get("publication_plan_signature")
    if not isinstance(raw_signature, dict):
        return ""
    return str(raw_signature.get("value") or "").strip()


def _sanitize_profile_id(value: Any, *, fallback: str) -> str:
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or fallback or "default").strip()).strip("-")
    return base[:128] or fallback or "default"


def _resolve_render_media_path(render_output: Any | None) -> Path | None:
    if render_output is None:
        return None
    raw = str(getattr(render_output, "output_path", "") or "").strip()
    if not raw:
        return None
    return resolve_publication_local_media_path(raw)


def resolve_publication_local_media_path(raw_path: Any) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    try:
        if path.exists() and path.is_file():
            return path.resolve()
    except OSError:
        pass

    normalized = raw.replace("\\", "/")
    runtime_prefix = "/app/data/"
    if normalized.startswith(runtime_prefix):
        workspace_root = Path(__file__).resolve().parents[2]
        mapped = workspace_root / "data" / "runtime" / normalized[len(runtime_prefix):].lstrip("/")
        if mapped.exists() and mapped.is_file():
            return mapped.resolve()

    if _looks_like_external_media_path(raw):
        return _materialize_publication_media_file(raw)
    return None


def _publication_media_runtime_root() -> Path:
    settings = get_settings()
    base_root = Path(getattr(settings, "output_root", Path(__file__).resolve().parents[2] / "data" / "runtime")).expanduser()
    return base_root / "publication-media"


def _materialized_publication_media_target(raw_path: str) -> Path:
    normalized = re.sub(r"[\\/]+", "/", str(raw_path or "").strip())
    file_name = Path(normalized).name or "publication-media.bin"
    stem = Path(file_name).stem or "publication-media"
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-") or "publication-media"
    digest = hashlib.sha1(normalized.casefold().encode("utf-8", errors="ignore")).hexdigest()[:16]
    target_dir = _publication_media_runtime_root() / f"{digest}-{safe_stem[:48]}"
    return target_dir / file_name


def _should_copy_publication_media(source_path: Path, target_path: Path) -> bool:
    if not target_path.exists():
        return True
    try:
        source_stat = source_path.stat()
        target_stat = target_path.stat()
    except OSError:
        return True
    return (
        source_stat.st_size != target_stat.st_size
        or int(source_stat.st_mtime) != int(target_stat.st_mtime)
    )


def _materialize_publication_media_file(raw_path: str) -> Path | None:
    normalized = str(raw_path or "").strip()
    if not normalized:
        return None
    target_path = _materialized_publication_media_target(normalized)
    if target_path.exists() and target_path.is_file():
        return target_path.resolve()
    source_path = Path(normalized).expanduser()
    try:
        if not source_path.exists() or not source_path.is_file():
            return None
    except OSError:
        return None
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if _should_copy_publication_media(source_path, target_path):
        shutil.copy2(source_path, target_path)
    if target_path.exists() and target_path.is_file():
        return target_path.resolve()
    return None


def _browser_agent_task_missing(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code == 404:
        return True
    text = str(exc or "").strip().lower()
    if not text:
        return False
    return "/tasks/" in text and "404" in text and "not found" in text


def _looks_like_external_media_path(raw: str) -> bool:
    text = str(raw or "").strip()
    if not text:
        return False
    return text.startswith("\\\\") or text.startswith("//")


def _normalize_platform_packages(packaging: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = packaging if isinstance(packaging, dict) else {}
    platform_root = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else raw
    packages: dict[str, dict[str, Any]] = {}
    if isinstance(raw.get("platforms"), list):
        for item in raw.get("platforms") or []:
            if not isinstance(item, dict):
                continue
            platform = normalize_publication_platform(item.get("key") or item.get("platform") or item.get("label"))
            if not platform:
                continue
            packages[platform] = dict(item)
        return packages
    if not isinstance(platform_root, dict):
        return packages
    for key, value in platform_root.items():
        platform = normalize_publication_platform(key)
        if not platform or not isinstance(value, dict):
            continue
        packages[platform] = dict(value)
    return packages


def _normalize_publication_title_audit_by_platform(packaging: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    raw = packaging if isinstance(packaging, dict) else {}
    title_audit = raw.get("title_audit") if isinstance(raw.get("title_audit"), dict) else {}
    audit_platforms = title_audit.get("platforms") if isinstance(title_audit.get("platforms"), dict) else {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in audit_platforms.items():
        platform = normalize_publication_platform(key)
        if not platform or not isinstance(value, dict):
            continue
        normalized[platform] = dict(value)
    return normalized


def _publication_title_audit_block_reason(platform: str, platform_audit: dict[str, Any]) -> str:
    if not isinstance(platform_audit, dict):
        return ""
    status = str(
        (
            platform_audit.get("summary")
            if isinstance(platform_audit.get("summary"), dict)
            else {}
        ).get("status")
        or platform_audit.get("status")
        or ""
    ).strip().lower()
    if status != "error":
        return ""
    issues = platform_audit.get("issues") if isinstance(platform_audit.get("issues"), list) else []
    detail = next((str(item.get("message") or "").strip() for item in issues if isinstance(item, dict) and str(item.get("message") or "").strip()), "")
    if not detail:
        detail = "标题审核存在硬错误。"
    return f"{platform_label(platform)} 标题审核未通过，已跳过：{detail}"


def _package_has_publish_copy(package: dict[str, Any]) -> bool:
    return bool(_package_primary_title(package) or str(package.get("description") or package.get("body") or "").strip())


def _package_primary_title(package: dict[str, Any]) -> str:
    titles = package.get("titles")
    if isinstance(titles, list):
        for title in titles:
            text = str(title or "").strip()
            if text:
                return text
    return str(package.get("primary_title") or package.get("title") or "").strip()


def _publication_title_hard_limit(platform: str, platform_audit: dict[str, Any] | None = None) -> int | None:
    rules = (
        platform_audit.get("rules")
        if isinstance(platform_audit, dict) and isinstance(platform_audit.get("rules"), dict)
        else {}
    )
    raw_limit = rules.get("hard_max_chars")
    try:
        if raw_limit is not None:
            limit = int(raw_limit)
            if limit > 0:
                return limit
    except (TypeError, ValueError):
        pass
    if normalize_publication_platform(platform) == "xiaohongshu":
        return 20
    return None


def _publication_title_display_units(text: str) -> int:
    raw_units = 0.0
    for char in str(text or ""):
        if unicodedata.east_asian_width(char) in {"W", "F"}:
            raw_units += 1.0
        elif ord(char) < 128:
            raw_units += 0.5
        else:
            raw_units += 1.0
    return int(math.ceil(raw_units))


def _truncate_publication_title(text: str, max_chars: int | None) -> str:
    if not isinstance(max_chars, int) or max_chars <= 0:
        return str(text or "").strip()
    sanitized = re.sub(r"\s+", " ", str(text or "")).strip().rstrip(" ，。；：!！?？")
    if len(sanitized) <= max_chars:
        return sanitized
    if _publication_title_hard_limit("xiaohongshu") == max_chars:
        return sanitized[:max_chars].rstrip(" ，。；：!！?？")
    if not sanitized or _publication_title_display_units(sanitized) <= max_chars:
        return sanitized
    current_units = 0.0
    truncated_chars: list[str] = []
    for char in sanitized:
        char_units = 0.5 if ord(char) < 128 and unicodedata.east_asian_width(char) not in {"W", "F"} else 1.0
        if math.ceil(current_units + char_units) > max_chars:
            break
        truncated_chars.append(char)
        current_units += char_units
    return "".join(truncated_chars).rstrip(" ，。；：!！?？")


def _semantic_fingerprint(
    *,
    job_id: str,
    platform: str,
    adapter: str,
    title: str,
    body: str,
    tags: list[str] | None = None,
    collection_name: str | None = None,
    scheduled_publish_at: str | None = None,
    media_path: str,
) -> str:
    normalized_tags = [str(item).strip() for item in (tags or []) if str(item).strip()]
    blob = json.dumps(
        {
            "job_id": job_id,
            "platform": platform,
            "adapter": adapter,
            "title": re.sub(r"\s+", " ", title).strip(),
            "body": re.sub(r"\s+", " ", body).strip(),
            "tags": sorted(normalized_tags),
            "collection_name": str(collection_name or "").strip(),
            "scheduled_publish_at": str(scheduled_publish_at or "").strip(),
            "media_path": media_path,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _platform_sort_key(platform: str) -> int:
    keys = list(SUPPORTED_PUBLICATION_PLATFORMS)
    try:
        return keys.index(platform)
    except ValueError:
        return len(keys)
