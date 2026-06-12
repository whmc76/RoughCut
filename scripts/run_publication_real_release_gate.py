from __future__ import annotations

import argparse
import copy
import asyncio
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.config import get_settings  # noqa: E402
from roughcut.db.models import Job, PublicationAttempt  # noqa: E402
from roughcut.db.session import get_session_factory  # noqa: E402
from roughcut.publication import (
    build_publication_plan,
    check_publication_browser_agent_ready,
    STABLE_PUBLICATION_PLATFORM_SET,
    PUBLICATION_ACTIVE_STATUSES,
    PUBLICATION_SUCCESS_STATUSES,
    PUBLICATION_TERMINAL_STATUSES,
    _derive_receipt_binding_fallback_id,
    _is_platform_draft_reset_recoverable_status,
    normalize_publication_platform,
    normalize_publication_browser_binding,
    list_publication_attempts,
    publication_plan_is_publishable,
    resolve_publication_local_media_path,
    run_publication_worker_once,
    submit_publication_attempts,
    _sanitize_publication_target_category,
)  # noqa: E402
from roughcut.publication_duplicate_audit import build_duplicate_history_gate_report  # noqa: E402
from roughcut.publication_intelligence import generate_publication_scheme  # noqa: E402
from roughcut.publication_packaging import (  # noqa: E402
    derive_publication_cover_slots,
    extract_publication_packaging_scope,
    load_json_payload,
    normalize_publication_packaging_payload,
    publication_primary_cover_path,
    publication_packaging_entry_blocking_reasons,
    publication_packaging_entry_publish_ready,
    publication_packaging_payload_publish_ready,
    resolve_publication_packaging_input_paths,
)

LLM_DISCOVERY_TIMEOUT_SEC = 8
LLM_DISPATCH_MAX_TARGETS = 6

STRICT_STABLE_REQUEST_CONTRACT_FIELD_KEYS = {
    "platform",
    "adapter",
    "title",
    "body",
    "hashtags",
    "display_hashtags",
    "structured_tags",
    "media_urls",
    "copy_material",
    "cover_path",
    "cover_slots",
    "category",
    "declaration",
}

RECOVERY_BOOL_OVERRIDE_KEYS = {
    "clear_draft_context",
    "force_publish_page_refresh",
    "verification_only_current_page",
    "repair_only_current_page",
    "prepublish_only_current_page",
    "prepare_only_current_page",
    "fresh_start_platform_tab",
    "verify_media_upload",
    "wait_for_publish_confirmation",
}

try:
    from scripts.run_publication_preflight import _default_platforms, _run_checks  # noqa: E402
except ModuleNotFoundError:
    from run_publication_preflight import _default_platforms, _run_checks  # noqa: E402


def _normalize_mismatch_field(item: Any) -> str:
    if isinstance(item, dict):
        field = item.get("field")
    else:
        field = item
    return _normalize(field)


def _build_publication_failure_context(summary: dict[str, Any]) -> dict[str, Any]:
    signature_fields_expected = summary.get("expected_signature_fields") or {}
    signature_fields_actual = (
        summary.get("response_signature_fields")
        if isinstance(summary.get("response_signature_fields"), dict) and summary.get("response_signature_fields")
        else summary.get("run_signature_fields")
        if isinstance(summary.get("run_signature_fields"), dict) and summary.get("run_signature_fields")
        else summary.get("request_signature_fields")
        if isinstance(summary.get("request_signature_fields"), dict) and summary.get("request_signature_fields")
        else summary.get("actual_request_fields")
    )
    expected_request_fields = summary.get("expected_request_fields") or {}
    actual_request_fields = summary.get("actual_request_fields") or {}
    request_payload_field_mismatch_fields = [
        _normalize_mismatch_field(item)
        for item in (summary.get("request_payload_field_mismatch_fields") or [])
        if _normalize_mismatch_field(item)
    ]
    request_field_mismatch_fields = [
        _normalize_mismatch_field(item)
        for item in (summary.get("request_field_mismatch_fields") or summary.get("field_mismatches") or [])
        if _normalize_mismatch_field(item)
    ]
    request_plan_fill_gaps = summary.get("request_plan_fill_gaps") or []
    return {
        "platform": _normalize(summary.get("platform")),
        "status": _normalize(summary.get("status")),
        "expected_signature": _normalize(summary.get("expected_signature")),
        "actual_signature": _normalize(summary.get("actual_signature")),
        "signature_match_status": _normalize(summary.get("signature_match_status")),
        "signature_fields_match": bool(summary.get("signature_fields_match")),
        "signature_fields_available": bool(summary.get("signature_fields_available")),
        "signature_fields_expected": signature_fields_expected,
        "signature_fields_actual": signature_fields_actual,
        "field_match": bool(summary.get("field_match")),
        "request_payload_fields_match": bool(summary.get("request_payload_fields_match")),
        "request_contract_ready": bool(summary.get("request_contract_ready")),
        "request_fields_snapshot_trusted": bool(summary.get("request_fields_snapshot_trusted")),
        "request_snapshot_plan_match": bool(summary.get("request_snapshot_plan_match")),
        "request_payload_plan_match": bool(summary.get("request_payload_plan_match")),
        "duplicate_detected": bool(summary.get("duplicate_detected")),
        "error_code": _normalize(summary.get("error_code")),
        "runs_count": int(summary.get("runs_count") or 0),
        "request_fields_snapshot_source": _normalize(summary.get("actual_request_fields_snapshot_source")),
        "requested_fields": expected_request_fields,
        "actual_fields": actual_request_fields,
        "request_field_verification": _build_request_field_verification_report(expected_request_fields, actual_request_fields),
        "request_payload_field_mismatches": summary.get("request_payload_field_mismatches") or [],
        "field_mismatches": summary.get("field_mismatches") or [],
        "request_payload_field_mismatch_fields": request_payload_field_mismatch_fields,
        "request_field_mismatch_fields": request_field_mismatch_fields,
        "request_plan_fill_gaps": request_plan_fill_gaps,
        "strict_contract_reasons": summary.get("strict_contract_reasons") or [],
        "request_fields_snapshot_count": int(summary.get("request_fields_snapshot_count") or 0),
        "request_fields_expected_count": int(summary.get("request_fields_expected_count") or 0),
        "request_fields_actual_count": int(summary.get("request_fields_actual_count") or 0),
        "request_payload_field_mismatch_count": int(summary.get("request_payload_field_mismatch_count") or 0),
        "request_field_mismatch_count": int(summary.get("request_field_mismatch_count") or 0),
        "public_url": _normalize(summary.get("public_url")),
        "scheduled_at": _normalize(summary.get("scheduled_at")),
        "external_url": _normalize(summary.get("public_url")),
        "visual_evidence": _coerce_visual_evidence(summary.get("visual_evidence")),
    }


def _build_request_field_verification_report(expected: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(expected, dict):
        expected = {}
    if not isinstance(actual, dict):
        actual = {}
    expected_payload = _normalize_comparable_value(expected)
    actual_payload = _normalize_comparable_value(actual)
    if not isinstance(expected_payload, dict) or not isinstance(actual_payload, dict):
        return []
    verification_rows: list[dict[str, Any]] = []
    for key in sorted(set(expected_payload.keys()) | set(actual_payload.keys())):
        expected_value = expected_payload.get(key)
        actual_value = actual_payload.get(key)
        if expected_value == actual_value:
            continue
        verification_rows.append({
            "field": key,
            "expected": expected_value,
            "actual": actual_value,
            "match": expected_value == actual_value,
        })
    return verification_rows[:80]


def _build_publication_discovery_prompt(context: dict[str, Any]) -> str:
    failure_points = []
    mismatch_fields = [_normalize_mismatch_field(item) for item in context.get("request_payload_field_mismatches", []) if _normalize_mismatch_field(item)]
    if mismatch_fields:
        failure_points.append(f"请求字段差异: {', '.join(mismatch_fields[:12])}")
    field_verification = [_normalize_mismatch_field(item) for item in context.get("request_field_verification", []) if _normalize_mismatch_field(item)]
    if field_verification:
        failure_points.append(f"请求与实际字段逐项差异: {', '.join(field_verification[:12])}")
    mismatch_fields = [_normalize_mismatch_field(item) for item in context.get("field_mismatches", []) if _normalize_mismatch_field(item)]
    if mismatch_fields:
        failure_points.append(f"返回字段差异: {', '.join(mismatch_fields[:12])}")
    if context.get("error_code"):
        failure_points.append(f"错误码: {context.get('error_code')}")
    if context.get("request_payload_fields_match") is False:
        failure_points.append("请求 payload 与计划字段不一致（含 title/body/tags/declaration/media 等）")
    if context.get("field_match") is False:
        failure_points.append("发布平台回放字段与计划字段不一致（字段快照偏差）")
    if context.get("requested_fields"):
        failure_points.append(
            f"计划字段数={len(context.get('requested_fields') or {})}，已回填字段数={len(context.get('actual_fields') or {})}"
        )
    if context.get("request_snapshot_plan_match") is False:
        failure_points.append("发布页字段快照与计划字段不一致（严格校验失败）。")
    if context.get("request_payload_plan_match") is False:
        failure_points.append("请求 payload 与计划字段不一致（入参已污染）。")
    if context.get("request_contract_ready") is False:
        failure_points.append("未生成稳定平台 request_fields 合同基线，发布合同校验无法进行。")
    if context.get("request_fields_snapshot_source"):
        failure_points.append(f"字段快照来源={context.get('request_fields_snapshot_source')}")
    if context.get("strict_contract_reasons"):
        failure_points.append(
            "严格校验阻断原因=" + ",".join([item for item in context.get("strict_contract_reasons") or [] if item][:4])
        )
    if not failure_points:
        failure_points.append("未识别到明确字段差异。")
    return (
        f"发布平台={context.get('platform')}\n"
        f"状态={context.get('status')}\n"
        f"签名匹配={context.get('signature_match_status')}（expected={context.get('expected_signature')}, actual={context.get('actual_signature')}）\n"
        f"签名字段一致={context.get('signature_fields_match')}，字段快照可信={context.get('signature_fields_available')}，是否重复={context.get('duplicate_detected')}\n"
        f"public_url={context.get('public_url')}\n"
        f"字段异常={'; '.join(failure_points)}\n"
        "请给出可执行恢复动作，建议按：retry/adjust_route/manual_check/requeue/ask_user 分类，"
        "并附带是否需要 clear_draft_context、force_publish_page_refresh。"
        "如需切换适配器或执行模式，请返回 target_adapter、target_execution_mode。"
        "若建议在下一次重试中强化鲁棒性，可在 recovery_plan.recovery_overrides 中返回："
        "wait_for_publish_confirmation（布尔）、verify_media_upload（布尔）、capture_response_timeout_ms（毫秒）。"
)
from roughcut.publication_platform_matrix import platform_default_declaration


def _coerce_llm_discovery_result(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    action = str(raw.get("action") or "").strip().lower()
    if not action:
        return None
    confidence = raw.get("confidence")
    try:
        confidence_value = float(confidence)
    except Exception:
        confidence_value = 0.0
    if not (0.0 <= confidence_value <= 1.0):
        confidence_value = 0.0
    next_steps = [str(item).strip() for item in raw.get("next_steps") or [] if str(item).strip()]
    if not next_steps:
        rationale = str(raw.get("rationale") or "").strip()
        if rationale:
            next_steps = [rationale]
        else:
            next_steps = [f"执行 {action} 路径"]
    evidence = [str(item).strip() for item in raw.get("evidence") or [] if str(item).strip()]
    recovery_plan = raw.get("recovery_plan") or {}
    if not isinstance(recovery_plan, dict):
        recovery_plan = {}
    target_adapter = _normalize_publication_adapter(
        raw.get("target_adapter") if raw.get("target_adapter") else recovery_plan.get("target_adapter")
    )
    target_execution_mode = _normalize_publication_execution_mode(
        raw.get("target_execution_mode") if raw.get("target_execution_mode") else recovery_plan.get("target_execution_mode")
    )
    target_platform_overrides = recovery_plan.get("target_platform_specific_overrides") or raw.get("target_platform_specific_overrides")
    if not isinstance(target_platform_overrides, dict):
        target_platform_overrides = {}
    normalized_target_platform_overrides = {
        str(key): value for key, value in target_platform_overrides.items() if key is not None and isinstance(value, (str, int, float, bool))
    }
    return {
        "action": action,
        "severity": str(raw.get("severity") or "medium").strip() or "medium",
        "next_steps": next_steps[:5],
        "confidence": round(confidence_value, 4),
        "evidence": evidence[:12],
        "retryable": bool(raw.get("retryable")),
        "rationale": str(raw.get("rationale") or "").strip() or "LLM诊断未提供理由。",
        "target_adapter": target_adapter,
        "target_execution_mode": target_execution_mode,
        "target_platform_specific_overrides": normalized_target_platform_overrides,
        "recovery_plan": {
            "clear_draft_context": bool(
                (recovery_plan.get("clear_draft_context") if isinstance(recovery_plan, dict) else False)
            ),
            "force_publish_page_refresh": bool(
                (recovery_plan.get("force_publish_page_refresh") if isinstance(recovery_plan, dict) else False)
            ),
            "recovery_overrides": recovery_plan.get("recovery_overrides") or {},
        },
    }


def _merge_discovery_overrides(
    recovery_overrides: dict[str, Any],
    source: Any,
) -> dict[str, Any]:
    if not isinstance(source, dict):
        return recovery_overrides
    candidate = source.get("recovery_plan")
    if not isinstance(candidate, dict):
        candidate = source
    merged = dict(recovery_overrides)
    for key, value in candidate.items():
        normalized_key = _normalize(key)
        if not normalized_key:
            continue
        if isinstance(value, (bool, int, str, float)):
            merged[normalized_key] = value
    return merged


async def _discover_release_issue_with_llm(context: dict[str, Any]) -> dict[str, Any] | None:
    if not context.get("platform"):
        return None
    try:
        from roughcut.providers.factory import get_reasoning_provider  # noqa: PLC0415
        from roughcut.providers.reasoning.base import Message, extract_json_text  # noqa: PLC0415
    except Exception:
        return None
    try:
        provider = get_reasoning_provider()
    except Exception:
        return None
    if not provider:
        return None
    prompt_text = _build_publication_discovery_prompt(context)
    payload = {
        "task": "发布失败复盘：返回可执行建议 JSON，仅输出 JSON。",
        "expected_schema": {
            "severity": "low|medium|high",
            "action": "retry|adjust_route|manual_check|requeue|verify_media|re_auth|ask_user",
            "retryable": True,
            "next_steps": ["步骤1", "步骤2"],
            "confidence": 0.0,
            "evidence": ["字段1", "字段2"],
            "rationale": "一句话说明",
            "target_adapter": "可选，优先切换适配器（如 browser_agent / x_link_share）",
            "target_execution_mode": "可选，优先切换执行模式（如 browser_agent / video / link_share）",
            "target_platform_specific_overrides": {"可选覆盖": True},
            "recovery_plan": {
                "clear_draft_context": False,
                "force_publish_page_refresh": False,
                "recovery_overrides": {},
            },
        },
        "context": context,
    }
    try:
        response = await asyncio.wait_for(
            provider.complete(
                [
                    Message(role="system", content="你是发布故障复盘助手。只输出合法 JSON，不要解释。"),
                    Message(role="user", content=prompt_text + f"\n约束: {json.dumps(payload, ensure_ascii=False)}"),
                ],
                temperature=0.15,
                max_tokens=900,
                json_mode=True,
            ),
            timeout=LLM_DISCOVERY_TIMEOUT_SEC,
        )
        raw = json.loads(extract_json_text(response.content))
        return _coerce_llm_discovery_result(raw)
    except Exception:
        return None


def _is_discovery_target(summary: dict[str, Any]) -> bool:
    if not summary:
        return False
    status = _normalize(summary.get("status"))
    if status in {"published", "scheduled_pending"}:
        return False
    if status and status in {"failed", "needs_human"}:
        return True
    if status == "draft_created":
        return not summary.get("signature_match") or not bool(summary.get("field_match", True))
    if bool(summary.get("duplicate_detected")):
        return True
    if not summary.get("signature_match"):
        return True
    if not bool(summary.get("field_match", True)):
        return True
    if status in {"submitted", "processing", "publishing", "waiting_publish", "ready_to_publish"} and (
        bool(summary.get("request_fields_snapshot_missing"))
        or summary.get("request_fields_snapshot_trusted") is False
    ):
        return True
    if summary.get("error_code") not in {"", None}:
        return True
    return False

AUTO_RECOVERABLE_ERROR_CODES = {
    "publication_request_plan_content_fill_gaps",
    "publication_submitted_response_payload_empty_snapshot",
    "publication_content_mismatch",
    "publication_signature_missing",
    "publication_signature_mismatch",
    "publication_signature_fields_mismatch",
    "publication_signature_fields_missing",
    "publication_request_fields_snapshot_missing",
    "publication_request_field_snapshot_untrusted",
    "publication_response_payload_untrusted",
    "publication_submitted_response_payload_missing",
    "publication_public_url_missing",
    "publication_schedule_receipt_missing",
    "publication_request_payload_fields_mismatch",
    "youtube_material_integrity_failed",
    "bilibili_final_publish_unconfirmed",
    "kuaishou_final_publish_unconfirmed",
    "wechat_channels_final_publish_unconfirmed",
    "_final_publish_unconfirmed",
    "_material_integrity_failed",
    "_pre_publish_content_plan_mismatch",
    "_pre_publish_material_integrity_failed",
    "_content_plan_mismatch",
    "_post_publish_content_plan_mismatch",
    "_receipt_content_plan_mismatch",
    "_scheduled_receipt_content_plan_mismatch",
    "_publish_content_plan_mismatch",
    "toutiao_final_publish_unconfirmed",
    "x_final_publish_unconfirmed",
    "publication_audit_unverified",
    "publication_draft_created",
    "auth_expired",
    "captcha_required",
}
AUTO_RECOVERY_DRAFT_CLEAR_BLOCKED_REASONS = {
    "status_in_progress",
    "content_plan_fill_gaps_pending",
    "response_payload_unverified",
    "submitted_response_payload_unverified",
    "receipt_target_unbound",
    "pre_publish_upload_pending",
    "upload_not_applied",
    "route_auth_required",
}
REASON_BASED_RECOVERY_RULES: dict[str, dict[str, Any]] = {
    "draft_created_recoverable": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "稳定平台残留草稿，清理草稿上下文后重试。",
    },
    "draft_created_terminal": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": False,
        "description": "稳定平台停在草稿态未公开，先清理草稿并按规则重试。",
    },
    "request_payload_mismatch": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "发布请求与计划字段不一致，先清理草稿重建发布输入。",
    },
    "signature_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "签名缺失，需清理草稿后重放以重建有效回执。",
    },
    "signature_mismatch": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "签名不匹配，疑似旧草稿干扰，先清理草稿。",
    },
    "signature_fields_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "签名字段回执缺失，清理草稿后重试。",
    },
    "signature_fields_mismatch": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "签名字段不一致，清理草稿并重试。",
    },
    "active_status_stale": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "发布状态持续停留在活跃态过久，优先清理草稿并重试。",
    },
    "processing_snapshot_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "处理态缺少响应快照，疑似页面未建立稳定草稿状态。",
    },
    "plan_fill_gaps": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "计划关键字段未写回页面，先清理草稿上下文并重试。",
    },
    "plan_fields_mismatch": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "计划字段与发布页快照不匹配，疑似脏草稿污染。",
    },
    "published_no_public_url": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": False,
        "description": "已达终态但未返回公开链接，需人工核验并清理草稿。",
    },
    "field_snapshot_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "缺失字段快照无法确认写入，先清理草稿。",
    },
    "field_snapshot_untrusted": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "快照仅来自请求体，需从发布页回执确认后重试。",
    },
    "response_payload_unverified": {
        "operations": ["force_publish_page_refresh"],
        "auto_remediable": False,
        "description": "提交/处理态 response_payload 不可信，先核验平台发布结果与链接状态。",
    },
    "submitted_response_payload_unverified": {
        "operations": ["force_publish_page_refresh"],
        "auto_remediable": False,
        "description": "submitted 状态下 response_payload 缺失或不可信，需先核验平台侧发布结果。",
    },
    "receipt_target_unbound": {
        "operations": ["force_publish_page_refresh", "wait_for_publish_confirmation"],
        "auto_remediable": False,
        "description": "发布后回执尚未唯一绑定到本次作品，保留现场继续刷新并核对回执。",
    },
    "pre_publish_upload_pending": {
        "operations": ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": False,
        "description": "预发布字段已通过，当前仅剩素材上传未完成，保留现场等待上传完成后继续验证。",
    },
    "upload_not_applied": {
        "operations": ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": False,
        "description": "上传动作已触发，但页面没有真正接住媒体，保留现场刷新并重新核验上传挂载状态。",
    },
    "route_auth_required": {
        "operations": [],
        "auto_remediable": False,
        "description": "当前页面处于登录/鉴权路由，需先恢复账号会话，不要清理草稿或自动补发。",
    },
    "content_mismatch": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "内容字段不一致，清理草稿后重放同签名。",
    },
    "content_duplicate": {
        "operations": [],
        "auto_remediable": False,
        "description": "疑似重复发布，需人工核验去重策略后继续。",
    },
    "content_plan_fill_gaps": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "关键内容字段缺失，疑似草稿污染或回填失败。",
    },
    "content_plan_fill_gaps_pending": {
        "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": True,
        "capture_response_timeout_ms": 90000,
        "description": "发布中关键字段回填暂未回读，先清理草稿上下文并重试。",
    },
    "submitted_content_plan_fill_gaps_pending": {
        "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": True,
        "capture_response_timeout_ms": 90000,
        "description": "提交态出现关键字段回填待补全，先清理草稿上下文并重试。",
    },
    "submitted_response_payload_empty_snapshot": {
        "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": True,
        "capture_response_timeout_ms": 120000,
        "description": "提交态 response_payload 仅返回空关键字段快照，先清理草稿上下文并重试。",
    },
    "content_plan_fill_gaps_deferred": {
        "operations": [],
        "auto_remediable": False,
        "description": "发布终态仍缺少回填快照，使用签名与请求基线做兜底采信。",
    },
    "public_url_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": False,
        "description": "公开链接缺失，优先清理草稿上下文并刷新发布页后重试。",
    },
    "schedule_receipt_missing": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "预约回执缺失，清草稿并确认预约字段。",
    },
    "failed_recoverable": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "失败码可重试，清理草稿并重试。",
    },
    "needs_human_recoverable": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "进入需要人工介入态，先清理草稿再重试。",
    },
    "failed_unclassified_recoverable": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "终态失败未命中已知码，先清草稿再重试一次。",
    },
    "adapter_mismatch": {
        "operations": [],
        "auto_remediable": False,
        "description": "适配器配置不一致，建议重新构建计划。",
    },
    "strict_contract_failed": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "严格校验未通过，先清理草稿并强制重建。",
    },
    "status_in_progress": {
        "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
        "auto_remediable": False,
        "capture_response_timeout_ms": 70000,
        "description": "发布进行态未进终态，先刷新发布页确认状态与链接回执，再判断是否需要清理草稿。",
    },
    "missing_contract": {
        "operations": [],
        "auto_remediable": False,
        "description": "发布计划缺少 request_fields 合同基线，需修复发布前链路生成过程。",
    },
    "terminal_status:failed": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "终态失败且可重试，先清草稿再重试。",
    },
    "unknown": {
        "operations": ["clear_draft_context", "force_publish_page_refresh"],
        "auto_remediable": True,
        "description": "无法归类失败，尝试清草稿+刷新后重试，并记录到适配器记忆。",
    },
}

STRICT_VERIFICATION_PLATFORM_SET = {
    "douyin",
    "xiaohongshu",
    "bilibili",
    "kuaishou",
    "toutiao",
    "youtube",
}
STRICT_VERIFICATION_SUCCESS_STATUSES = {"published", "scheduled_pending"}
RELEASE_GATE_RECOVERY_MONITOR_STATUSES = {
    "submitted",
    "processing",
    "uploading",
    "uploading_media",
    "publishing",
    "ready_to_publish",
    "waiting_publish",
}
RECOVERY_KNOWLEDGE_BASE_VERSION = 1
RECOVERY_KNOWLEDGE_MAX_ENTRIES_PER_PLATFORM = 120
DEFAULT_RECOVERY_KNOWLEDGE_BASE_PATH = str(ROOT_DIR / "artifacts" / "publication-recovery-knowledge-base.json")
DEFAULT_ACTIVE_ATTEMPT_STALE_TTL_SECONDS = 900
PREPUBLICATION_DRAFT_CRITICAL_FIELDS = {
    "platform",
    "adapter",
    "title",
    "body",
    "hashtags",
    "display_hashtags",
    "structured_tags",
    "media_urls",
    "media_items_count",
    "copy_material",
    "cover_path",
    "cover_slots",
    "category",
    "declaration",
}
SUBMITTED_DRAFT_CRITICAL_FIELDS = {
    "title",
    "body",
    "hashtags",
    "display_hashtags",
    "structured_tags",
    "media_urls",
    "media_items_count",
    "copy_material",
    "cover_path",
    "cover_slots",
    "category",
    "declaration",
}


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _normalize_platform_options_payload(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_value, dict):
            continue
        key = _normalize(raw_key).lower().replace("_", "-")
        if key:
            normalized[key] = dict(raw_value)
    return normalized


def _is_release_in_progress_status(status: str) -> bool:
    normalized = _normalize(status).lower()
    return normalized in RELEASE_GATE_RECOVERY_MONITOR_STATUSES or normalized in PUBLICATION_ACTIVE_STATUSES


def _to_non_negative_int(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, parsed)


def _coerce_recovery_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = _normalize(value).lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "on", "enabled", "enable"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled", "disable"}:
        return False
    return default


def _coerce_recovery_timeout_ms(
    value: Any,
    *,
    default: int | None = None,
    min_ms: int = 15000,
    max_ms: int = 180000,
) -> int | None:
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return default
    if parsed <= 0:
        return default
    return max(min_ms, min(max_ms, parsed))


def _is_auto_recoverable_error_code(value: str, auto_recover_codes: set[str] | None) -> bool:
    normalized = _normalize(value).lower()
    if not normalized:
        return False
    codes = auto_recover_codes or set()
    if normalized in codes:
        return True
    return any(normalized.endswith(code) for code in codes if code.startswith("_"))


def _normalize_publication_adapter(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_")


def _normalize_publication_execution_mode(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_") or "browser_agent"


def _is_strict_verification_platform(platform: str) -> bool:
    return _normalize(platform).lower().replace("_", "-") in STRICT_VERIFICATION_PLATFORM_SET


def _coerce_recovery_knowledge_base(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {
            "version": RECOVERY_KNOWLEDGE_BASE_VERSION,
            "updated_at": _now(),
            "platforms": {},
            "prepublish_platforms": {},
            "entries": 0,
            "prepublish_entries": 0,
        }
    raw_version = int(raw.get("version") or RECOVERY_KNOWLEDGE_BASE_VERSION)
    platforms: dict[str, dict[str, dict[str, Any]]] = {}
    prepublish_platforms: dict[str, dict[str, dict[str, Any]]] = {}
    raw_platforms = raw.get("platforms")
    raw_prepublish_platforms = raw.get("prepublish_platforms")
    if isinstance(raw_platforms, dict):
        for platform, value in raw_platforms.items():
            platform_key = _normalize(platform).lower().replace("_", "-")
            if not platform_key or not isinstance(value, dict):
                continue
            clean_entries: dict[str, dict[str, Any]] = {}
            for signature, entry_raw in value.items():
                if not isinstance(entry_raw, dict):
                    continue
                signature_key = _normalize(signature)
                if not signature_key:
                    continue
                clean_entries[signature_key] = {
                    "count": max(0, int(entry_raw.get("count") or 0)),
                    "last_seen": _normalize(entry_raw.get("last_seen")) or _now(),
                    "created_at": _normalize(entry_raw.get("created_at")) or _now(),
                    "error_code": _normalize(entry_raw.get("error_code")),
                    "reason": _normalize(entry_raw.get("reason")),
                    "signature": _normalize(entry_raw.get("signature")),
                    "status": _normalize(entry_raw.get("status")),
                    "playbook_actions": [
                        _normalize(item)
                        for item in (entry_raw.get("playbook_actions") or [])
                        if _normalize(item)
                    ],
                    "discovery_recommendation": _normalize(entry_raw.get("discovery_recommendation")) if isinstance(
                        entry_raw.get("discovery_recommendation"), str
                    ) else entry_raw.get("discovery_recommendation"),
                    "discovery_actions": [
                        _normalize(item) for item in (entry_raw.get("discovery_actions") or []) if _normalize(item)
                    ][-6:]
                    if isinstance(entry_raw.get("discovery_actions"), list)
                    else [],
                    "verify_media_upload": _coerce_recovery_bool(entry_raw.get("verify_media_upload"), default=False),
                    "wait_for_publish_confirmation": _coerce_recovery_bool(
                        entry_raw.get("wait_for_publish_confirmation"), default=False
                    ),
                    "capture_response_timeout_ms": _coerce_recovery_timeout_ms(
                        entry_raw.get("capture_response_timeout_ms"), default=None, min_ms=15000, max_ms=180000
                    ),
                    "discovery_retryable": bool(entry_raw.get("discovery_retryable")),
                    "discovery_trigger": _normalize(entry_raw.get("discovery_trigger")),
                    "last_actions": list(entry_raw.get("last_actions") or [])[:6] if isinstance(entry_raw.get("last_actions"), list) else [],
                }
                for key in (
                    "verification_only_current_page",
                    "repair_only_current_page",
                    "prepublish_only_current_page",
                    "prepare_only_current_page",
                ):
                    clean_entries[signature_key][key] = _coerce_recovery_bool(entry_raw.get(key), default=False)
            platforms[platform_key] = clean_entries
    if isinstance(raw_prepublish_platforms, dict):
        for platform, value in raw_prepublish_platforms.items():
            platform_key = _normalize(platform).lower().replace("_", "-")
            if not platform_key or not isinstance(value, dict):
                continue
            clean_entries: dict[str, dict[str, Any]] = {}
            for signature, entry_raw in value.items():
                if not isinstance(entry_raw, dict):
                    continue
                signature_key = _normalize(signature)
                if not signature_key:
                    continue
                normalized_reasons = [
                    _normalize(item)
                    for item in (entry_raw.get("reasons") or entry_raw.get("prepublish_reasons") or [])
                    if _normalize(item)
                ]
                clean_entries[signature_key] = {
                    "count": max(0, int(entry_raw.get("count") or 0)),
                    "last_seen": _normalize(entry_raw.get("last_seen")) or _now(),
                    "created_at": _normalize(entry_raw.get("created_at")) or _now(),
                    "status": _normalize(entry_raw.get("status")),
                    "platform": platform_key,
                    "error_code": _normalize(entry_raw.get("error_code")),
                    "snapshot_source": _normalize(entry_raw.get("snapshot_source")),
                    "snapshot_count": _to_non_negative_int(entry_raw.get("snapshot_count")),
                    "signature": _normalize(entry_raw.get("signature")),
                    "signature_text": _normalize(entry_raw.get("signature_text")),
                    "reasons": sorted(set(normalized_reasons)),
                    "clear_draft_context": bool(entry_raw.get("clear_draft_context")),
                    "force_publish_page_refresh": bool(entry_raw.get("force_publish_page_refresh")),
                    "attempt_updated_at": _normalize(entry_raw.get("attempt_updated_at")),
                    "verify_media_upload": _coerce_recovery_bool(entry_raw.get("verify_media_upload"), default=False),
                    "wait_for_publish_confirmation": _coerce_recovery_bool(
                        entry_raw.get("wait_for_publish_confirmation"), default=False
                    ),
                    "capture_response_timeout_ms": _coerce_recovery_timeout_ms(
                        entry_raw.get("capture_response_timeout_ms"), default=None, min_ms=15000, max_ms=180000
                    ),
                }
                for key in (
                    "verification_only_current_page",
                    "repair_only_current_page",
                    "prepublish_only_current_page",
                    "prepare_only_current_page",
                ):
                    clean_entries[signature_key][key] = _coerce_recovery_bool(entry_raw.get(key), default=False)
            prepublish_platforms[platform_key] = clean_entries
    return {
        "version": raw_version or RECOVERY_KNOWLEDGE_BASE_VERSION,
        "updated_at": _normalize(raw.get("updated_at")) or _now(),
        "platforms": platforms,
        "prepublish_platforms": prepublish_platforms,
        "entries": int(raw.get("entries") or 0),
        "prepublish_entries": int(raw.get("prepublish_entries") or 0),
    }


def _normalize_reason_recovery_rule(reason: str) -> str:
    normalized_reason = _normalize(reason).lower()
    if not normalized_reason:
        return "unknown"
    return normalized_reason


def _derive_reason_recovery_plan(summary: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    if bool(summary.get("route_auth_required")):
        return (
            {
                "force_publish_page_refresh": False,
                "clear_draft_context": False,
                "wait_for_publish_confirmation": False,
                "verify_media_upload": False,
                "recovery_mode": _normalize(summary.get("error_code")) or "route_auth_required",
            },
            [],
            False,
        )
    if bool(summary.get("receipt_target_unbound")):
        return (
            {
                "force_publish_page_refresh": True,
                "clear_draft_context": False,
                "wait_for_publish_confirmation": True,
                "recovery_mode": _normalize(summary.get("error_code")) or "receipt_target_unbound",
            },
            ["force_publish_page_refresh", "wait_for_publish_confirmation"],
            False,
        )
    if bool(summary.get("pre_publish_upload_pending")):
        return (
            {
                "force_publish_page_refresh": True,
                "clear_draft_context": False,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
                "recovery_mode": _normalize(summary.get("error_code")) or "pre_publish_upload_pending",
            },
            ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
            False,
        )
    if bool(summary.get("upload_not_applied")):
        return (
            {
                "force_publish_page_refresh": True,
                "clear_draft_context": False,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
                "recovery_mode": _normalize(summary.get("error_code")) or "upload_not_applied",
            },
            ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
            False,
        )
    if bool(summary.get("post_repair_preserve_context")):
        operations = ["force_publish_page_refresh"]
        if "upload_ready" in {
            _normalize(item)
            for item in (summary.get("publication_audit") or {}).get("required_unverified", [])
            if _normalize(item)
        }:
            operations.extend(["verify_media_upload", "wait_for_publish_confirmation"])
        return (
            {
                "force_publish_page_refresh": True,
                "clear_draft_context": False,
                "recovery_mode": _normalize(summary.get("error_code")) or "post_repair_preserve_context",
            },
            operations,
            False,
        )
    reasons = [ _normalize_reason_recovery_rule(item) for item in (summary.get("strict_contract_reasons") or []) if _normalize_reason_recovery_rule(item)]
    if (
        _normalize(summary.get("status")).lower() == "submitted"
        and (
            "content_plan_fill_gaps_pending" in reasons
            or "content_plan_fill_gaps" in reasons
            or "response_payload_unverified" in reasons
            or "submitted_response_payload_unverified" in reasons
        )
        and "submitted_content_plan_fill_gaps_pending" not in reasons
    ):
        reasons = ["submitted_content_plan_fill_gaps_pending", *reasons]
    if not reasons:
        status = _normalize(summary.get("status")).lower()
        if status in PUBLICATION_TERMINAL_STATUSES:
            reasons = [f"terminal_status:{status or 'unknown'}"]
        else:
            reasons = ["unknown"]
    if not reasons:
        reasons = ["unknown"]
    merged_operations: list[str] = []
    overrides: dict[str, Any] = {}
    auto_remediable = True
    selected_reasons: list[str] = []
    for reason in reasons:
        matched_rules: dict[str, Any] = {}
        if reason in REASON_BASED_RECOVERY_RULES:
            matched_rules = REASON_BASED_RECOVERY_RULES.get(reason, {})
        else:
            for key, candidate in REASON_BASED_RECOVERY_RULES.items():
                if key and reason.startswith(key + ":"):
                    matched_rules = candidate
                    break
            else:
                matched_rules = REASON_BASED_RECOVERY_RULES.get("unknown", {})
        operations = {
            _normalize(item)
            for item in (matched_rules.get("operations") if isinstance(matched_rules.get("operations"), list) else [])
            if _normalize(item)
        }
        for operation in ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"]:
            if operation in operations:
                overrides[operation] = True
        reason_capture_timeout = _coerce_recovery_timeout_ms(
            matched_rules.get("capture_response_timeout_ms"),
            default=None,
            min_ms=15000,
            max_ms=180000,
        )
        if reason_capture_timeout is not None:
            overrides["capture_response_timeout_ms"] = reason_capture_timeout
        if matched_rules.get("auto_remediable") is False:
            auto_remediable = False
        selected_reasons.append(reason)
        merged_operations.extend([operation for operation in operations if operation not in merged_operations])
    if merged_operations:
        overrides["recovery_mode"] = _normalize(summary.get("error_code")) or "rulebook"
    return overrides, merged_operations, auto_remediable


def _load_recovery_knowledge_base(path: str) -> dict[str, Any]:
    if not _normalize(path):
        return _coerce_recovery_knowledge_base({})
    knowledge_base_path = Path(path)
    if not knowledge_base_path.exists():
        return _coerce_recovery_knowledge_base({})
    try:
        payload = json.loads(knowledge_base_path.read_text(encoding="utf-8"))
    except Exception:
        return _coerce_recovery_knowledge_base({})
    return _coerce_recovery_knowledge_base(payload)


def _persist_recovery_knowledge_base(path: str, knowledge_base: dict[str, Any]) -> None:
    if not _normalize(path):
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = _coerce_recovery_knowledge_base(knowledge_base)
    payload["updated_at"] = _now()
    total_entries = 0
    total_prepublish_entries = 0
    for entries in (payload.get("platforms") or {}).values():
        if isinstance(entries, dict):
            total_entries += len(entries)
    for entries in (payload.get("prepublish_platforms") or {}).values():
        if isinstance(entries, dict):
            total_prepublish_entries += len(entries)
    payload["entries"] = total_entries
    payload["prepublish_entries"] = total_prepublish_entries
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _prune_recovery_knowledge_entries(platform_entries: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    if not isinstance(platform_entries, dict):
        return {}
    sorted_entries = sorted(
        platform_entries.items(),
        key=lambda item: _normalize(item[1].get("last_seen")),
        reverse=True,
    )
    return {key: value for key, value in sorted_entries[:RECOVERY_KNOWLEDGE_MAX_ENTRIES_PER_PLATFORM]}


def _build_recovery_signature(platform: str, summary: dict[str, Any]) -> tuple[str, str]:
    platform_key = _normalize(platform).lower().replace("_", "-")
    status = _normalize(summary.get("status"))
    error_code = _normalize(summary.get("error_code"))
    requested_fields = summary.get("request_payload_field_mismatches")
    field_mismatches = summary.get("field_mismatches")
    issue_bits: list[str] = []
    if status:
        issue_bits.append(f"status={status}")
    if error_code:
        issue_bits.append(f"error={error_code}")
    if summary.get("duplicate_detected"):
        issue_bits.append("duplicate_detected")
    if isinstance(requested_fields, list) and requested_fields:
        mismatch_fields = ",".join(
            str(_normalize_mismatch_field(item) or "")
            for item in requested_fields
            if _normalize(_normalize_mismatch_field(item))
        )
        if mismatch_fields:
            issue_bits.append(f"request_mismatch={mismatch_fields}")
    snapshot_source = _normalize(summary.get("actual_request_fields_snapshot_source"))
    if snapshot_source:
        issue_bits.append(f"snapshot_source={snapshot_source}")
    if summary.get("request_fields_snapshot_trusted") is False:
        issue_bits.append("snapshot_untrusted")
    if summary.get("request_fields_snapshot_missing"):
        issue_bits.append("snapshot_missing")
    if isinstance(field_mismatches, list) and field_mismatches:
        mismatch_fields = ",".join(
            str(_normalize_mismatch_field(item) or "")
            for item in field_mismatches
            if _normalize(_normalize_mismatch_field(item))
        )
        if mismatch_fields:
            issue_bits.append(f"field_mismatch={mismatch_fields}")
    if summary.get("request_contract_ready") is False:
        issue_bits.append("request_contract_ready=false")
    if not _normalize(summary.get("public_url")):
        issue_bits.append("public_url_empty")
    if summary.get("scheduled_publish_at") and not summary.get("scheduled_at"):
        issue_bits.append("schedule_missing")
    signature_text = f"{platform_key}|{';'.join(issue_bits) if issue_bits else 'generic'}"
    signature_digest = hashlib.sha1(signature_text.encode("utf-8")).hexdigest()[:18]
    return signature_digest, signature_text


def _normalize_prepublish_reasons(value: Any) -> list[str]:
    return sorted(
        {
            item
            for item in [
                _normalize(item).lower()
                for item in (value or [])
                if _normalize(item)
            ]
            if item
        }
    )


POST_PUBLISH_PENDING_REASONS = {
    "status_in_progress",
    "content_plan_fill_gaps_pending",
    "submitted_content_plan_fill_gaps_pending",
    "submitted_response_payload_empty_snapshot",
    "submitted_response_payload_unverified",
    "response_payload_unverified",
    "submitted_snapshot_missing",
    "processing_snapshot_missing",
}

POST_PUBLISH_BLOCKING_REASONS = {
    "draft_created",
    "signature_missing",
    "signature_mismatch",
    "published_no_public_url",
    "content_plan_fill_gaps",
    "request_payload_mismatch",
    "request_payload_fields_mismatch",
    "missing_contract",
}


def _is_publish_receipt_pending_summary(summary: dict[str, Any]) -> bool:
    status = _normalize(summary.get("status")).lower()
    if status not in {"submitted", "processing", "publishing", "waiting_publish", "ready_to_publish"}:
        return False
    normalized_reasons = set(_normalize_prepublish_reasons(summary.get("strict_contract_reasons") or summary.get("reasons") or []))
    if not normalized_reasons or not (normalized_reasons & POST_PUBLISH_PENDING_REASONS):
        return False
    if any(reason.startswith("terminal_status:") for reason in normalized_reasons):
        return False
    if normalized_reasons & POST_PUBLISH_BLOCKING_REASONS:
        return False
    expected_signature = _normalize(summary.get("expected_signature"))
    actual_signature = _normalize(summary.get("actual_signature"))
    signature_match = bool(summary.get("signature_match"))
    request_payload_plan_match = summary.get("request_payload_plan_match")
    request_fields_snapshot_missing = bool(summary.get("request_fields_snapshot_missing"))
    request_fields_snapshot_trusted = bool(summary.get("request_fields_snapshot_trusted"))
    if expected_signature and actual_signature and expected_signature != actual_signature:
        return False
    inferred_pending_without_actual_signature = (
        expected_signature
        and not actual_signature
        and (
            signature_match
            or (
                request_payload_plan_match is not False
                and (request_fields_snapshot_missing or not request_fields_snapshot_trusted)
            )
        )
    )
    if expected_signature and not actual_signature and not inferred_pending_without_actual_signature:
        return False
    if expected_signature and actual_signature and expected_signature == actual_signature:
        signature_match = True
    if not signature_match:
        return False
    if summary.get("duplicate_detected"):
        return False
    if request_payload_plan_match is False:
        return False
    return True


def _should_suppress_draft_recovery_recommendation(issue: str, *, publish_receipt_pending: bool) -> bool:
    if not publish_receipt_pending:
        return False
    return issue in {
        "content_plan_fill_gaps_pending",
        "submitted_content_plan_fill_gaps_pending",
        "submitted_response_payload_empty_snapshot",
        "active_status_stale",
        "signature_fields_missing",
        "signature_fields_mismatch",
        "publication_request_fields_snapshot_missing",
        "publication_request_field_snapshot_untrusted",
        "content_plan_fill_gaps",
        "content_fields_mismatch",
    }


def _should_clear_draft_from_prepublish_reasons(
    *,
    status: str,
    reasons: list[str],
    publish_receipt_pending: bool,
    error_code: str = "",
    snapshot_source: str = "",
    post_repair_preserve_context: bool = False,
    receipt_target_unbound: bool = False,
    upload_not_applied: bool = False,
    route_auth_required: bool = False,
) -> bool:
    if route_auth_required:
        return False
    if upload_not_applied:
        return False
    if receipt_target_unbound:
        return False
    if post_repair_preserve_context:
        return False
    normalized_reasons = _normalize_prepublish_reasons(reasons)
    normalized_status = _normalize(status).lower()
    normalized_error_code = _normalize(error_code).lower()
    normalized_snapshot_source = _normalize(snapshot_source).lower()
    normalized_reason_set = set(normalized_reasons)
    response_snapshot_only_reasons = {
        "plan_fill_gaps",
        "plan_fields_mismatch",
        "content_plan_fill_gaps_pending",
        "content_plan_fill_gaps",
        "response_payload_unverified",
        "submitted_response_payload_unverified",
        "submitted_content_plan_fill_gaps_pending",
        "submitted_response_payload_empty_snapshot",
        "submitted_snapshot_missing",
        "processing_snapshot_missing",
        "status_in_progress",
        "active_status_stale",
    }
    response_snapshot_only_terminal_suffixes = {
        "_pre_publish_content_plan_mismatch",
        "_pre_publish_material_integrity_failed",
    }
    terminal_reasons = [reason for reason in normalized_reasons if reason.startswith("terminal_status:")]
    non_terminal_reasons = {
        reason
        for reason in normalized_reasons
        if not reason.startswith("terminal_status:") and not reason.startswith("draft_created")
    }
    has_terminal_or_draft_reason = any(
        reason.startswith("terminal_status") or reason.startswith("draft_created")
        for reason in normalized_reasons
    )
    weak_response_payload_terminal = bool(terminal_reasons) and all(
        any(reason.partition(":")[2].endswith(suffix) for suffix in response_snapshot_only_terminal_suffixes)
        for reason in terminal_reasons
    )
    has_only_weak_response_snapshot_reasons = bool(non_terminal_reasons) and non_terminal_reasons.issubset(
        response_snapshot_only_reasons
    )
    if normalized_snapshot_source == "request_payload" and normalized_status in {
        "processing",
        "submitted",
        "publishing",
        "waiting_publish",
        "ready_to_publish",
        "in_progress",
    }:
        return False
    if normalized_snapshot_source == "response_payload" and normalized_status in {
        "queued",
        "processing",
        "submitted",
        "publishing",
        "waiting_publish",
        "ready_to_publish",
        "in_progress",
    }:
        if (
            normalized_reason_set
            and normalized_reason_set.issubset(response_snapshot_only_reasons)
            and not publish_receipt_pending
            and not has_terminal_or_draft_reason
        ):
            return False
    if (
        normalized_snapshot_source == "response_payload"
        and normalized_status in {"failed", "needs_human"}
        and weak_response_payload_terminal
        and has_only_weak_response_snapshot_reasons
    ):
        return False
    if (
        normalized_status in {"failed", "needs_human"}
        and normalized_error_code
        and not _is_platform_draft_reset_recoverable_status(normalized_status, normalized_error_code)
    ):
        return False
    can_be_draft_recovery = {
        "draft_created",
        "signature_missing",
        "signature_mismatch",
        "published_no_public_url",
        "active_status_stale",
        "processing_snapshot_missing",
        "submitted_snapshot_missing",
        "submitted_content_plan_fill_gaps_pending",
        "submitted_response_payload_empty_snapshot",
        "content_plan_fill_gaps_pending",
        "content_plan_fill_gaps",
        "response_payload_unverified",
        "submitted_response_payload_unverified",
    }
    allow_recoverable_snapshot_issues = {
        "plan_fill_gaps",
        "plan_fields_mismatch",
    }
    for reason in normalized_reasons:
        if reason.startswith("terminal_status") or reason.startswith("draft_created"):
            if reason.startswith("draft_created"):
                return True
            terminal_error_code = normalized_error_code or reason.partition(":")[2]
            if _is_platform_draft_reset_recoverable_status(normalized_status, terminal_error_code):
                return True
            continue
        if publish_receipt_pending and reason in POST_PUBLISH_PENDING_REASONS:
            continue
        if reason in can_be_draft_recovery:
            return True
        if reason == "status_in_progress" and status in {"processing", "submitted"} and "active_status_stale" in normalized_reasons:
            return True
        if (
            reason in allow_recoverable_snapshot_issues
            and status not in {"submitted", "processing", "publishing", "waiting_publish", "ready_to_publish"}
        ):
            return True
    return False


def _runtime_context_recovery_flags(reasons: list[str]) -> dict[str, bool]:
    normalized_reasons = sorted(set(_normalize(reason).lower() for reason in (reasons or []) if _normalize(reason)))
    clear_draft_context = False
    for reason in normalized_reasons:
        if reason == "draft_created_stale":
            clear_draft_context = True
            break
        if reason.startswith("failure_context:"):
            failure_code = reason.partition(":")[2]
            if _is_platform_draft_reset_recoverable_status("needs_human", failure_code):
                clear_draft_context = True
                break
    return {
        "clear_draft_context": clear_draft_context,
        "force_publish_page_refresh": bool(normalized_reasons),
    }


def _build_prepublish_recovery_signature(platform: str, signal: dict[str, Any]) -> tuple[str, str]:
    platform_key = _normalize(platform).lower().replace("_", "-")
    status = _normalize(signal.get("status"))
    error_code = _normalize(signal.get("error_code"))
    updated_at = _normalize(signal.get("updated_at"))
    reasons = _normalize_prepublish_reasons(signal.get("reasons") or [])
    snapshot_source = _normalize(signal.get("snapshot_source"))
    snapshot_count = _to_non_negative_int(signal.get("snapshot_count") or 0)
    adapter = _normalize(signal.get("adapter"))
    issue_bits: list[str] = []
    if status:
        issue_bits.append(f"status={status}")
    if error_code:
        issue_bits.append(f"error={error_code}")
    if updated_at:
        issue_bits.append(f"updated_at={updated_at}")
    if adapter:
        issue_bits.append(f"adapter={adapter}")
    if reasons:
        issue_bits.append(f"reasons={','.join(reasons)}")
    if snapshot_source:
        issue_bits.append(f"snapshot_source={snapshot_source}")
    if snapshot_count:
        issue_bits.append(f"snapshot_count={snapshot_count}")
    signature_text = f"{platform_key}|{';'.join(issue_bits) if issue_bits else 'generic'}"
    signature_digest = hashlib.sha1(signature_text.encode("utf-8")).hexdigest()[:18]
    return signature_digest, signature_text


def _record_prepublish_recovery_signal(
    knowledge_base: dict[str, Any],
    *,
    platform: str,
    signal: dict[str, Any],
) -> tuple[str, dict[str, Any], int]:
    platform_key = _normalize(platform).lower().replace("_", "-")
    signature, signature_text = _build_prepublish_recovery_signature(platform_key, signal)
    prepublish_platforms = knowledge_base.setdefault("prepublish_platforms", {})
    entries = prepublish_platforms.setdefault(platform_key, {})
    existing = dict(entries.get(signature) or {})
    attempt_count = int(existing.get("count") or 0) + 1
    existing["count"] = attempt_count
    existing["last_seen"] = _now()
    if not existing.get("created_at"):
        existing["created_at"] = existing["last_seen"]
    existing["platform"] = platform_key
    existing["signature"] = signature
    existing["signature_text"] = signature_text
    existing["status"] = _normalize(signal.get("status"))
    existing["error_code"] = _normalize(signal.get("error_code"))
    existing["snapshot_source"] = _normalize(signal.get("snapshot_source"))
    existing["snapshot_count"] = _to_non_negative_int(signal.get("snapshot_count") or 0)
    existing["reasons"] = _normalize_prepublish_reasons(signal.get("reasons") or [])
    existing["adapter"] = _normalize(signal.get("adapter"))
    existing["attempt_updated_at"] = _normalize(signal.get("updated_at"))
    existing["clear_draft_context"] = bool(signal.get("clear_draft_context"))
    existing["force_publish_page_refresh"] = bool(signal.get("force_publish_page_refresh"))
    existing["verify_media_upload"] = _coerce_recovery_bool(signal.get("verify_media_upload"), default=False)
    existing["wait_for_publish_confirmation"] = _coerce_recovery_bool(signal.get("wait_for_publish_confirmation"), default=False)
    existing["verification_only_current_page"] = _coerce_recovery_bool(signal.get("verification_only_current_page"), default=False)
    existing["repair_only_current_page"] = _coerce_recovery_bool(signal.get("repair_only_current_page"), default=False)
    existing["prepublish_only_current_page"] = _coerce_recovery_bool(signal.get("prepublish_only_current_page"), default=False)
    existing["prepare_only_current_page"] = _coerce_recovery_bool(signal.get("prepare_only_current_page"), default=False)
    existing["capture_response_timeout_ms"] = _coerce_recovery_timeout_ms(
        signal.get("capture_response_timeout_ms"),
        default=None,
        min_ms=15000,
        max_ms=180000,
    )
    entries[signature] = existing
    entries = _prune_recovery_knowledge_entries(entries)
    prepublish_platforms[platform_key] = entries
    return signature, existing, attempt_count


def _record_recovery_signal(
    knowledge_base: dict[str, Any],
    *,
    platform: str,
    summary: dict[str, Any],
    status: str,
    discovery_signal: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], int]:
    platform_key = _normalize(platform).lower().replace("_", "-")
    signature, signature_text = _build_recovery_signature(platform_key, summary)
    platforms = knowledge_base.setdefault("platforms", {})
    entries = platforms.setdefault(platform_key, {})
    existing = dict(entries.get(signature) or {})
    attempt_count = int(existing.get("count") or 0) + 1
    existing["count"] = attempt_count
    existing["last_seen"] = _now()
    if not existing.get("created_at"):
        existing["created_at"] = existing["last_seen"]
    existing["error_code"] = _normalize(summary.get("error_code")) or _normalize(status)
    existing["reason"] = signature_text
    existing["signature"] = signature
    existing["status"] = _normalize(status)
    existing["platform"] = platform_key
    if summary.get("strict_contract_reasons"):
        existing["playbook_actions"] = [item for item in (summary.get("strict_contract_reasons") or []) if _normalize(item)]
    if isinstance(discovery_signal, dict):
        discovery_actions = [ _normalize(item) for item in discovery_signal.get("discovery_actions") or [] if _normalize(item)]
        if discovery_actions:
            existing["discovery_actions"] = discovery_actions[-6:]
        discovery_retryable = discovery_signal.get("discovery_retryable")
        if isinstance(discovery_retryable, bool):
            existing["discovery_retryable"] = discovery_retryable
        discovery_trigger = _normalize(discovery_signal.get("trigger"))
        if discovery_trigger:
            existing["discovery_trigger"] = discovery_trigger
        if discovery_signal.get("discovery_recommendation"):
            existing["discovery_recommendation"] = discovery_signal.get("discovery_recommendation")
        discovery_recommendation = discovery_signal.get("discovery_recommendation")
        if isinstance(discovery_recommendation, dict):
            recommendation_overrides = discovery_recommendation.get("recovery_overrides")
            if isinstance(recommendation_overrides, dict):
                existing.setdefault("recovery_overrides", {})
                for key, value in recommendation_overrides.items():
                    key_normalized = _normalize(key)
                    if key_normalized in RECOVERY_BOOL_OVERRIDE_KEYS:
                        existing["recovery_overrides"][key_normalized] = _coerce_recovery_bool(value, default=False)
                    elif key_normalized == "capture_response_timeout_ms":
                        timeout_value = _coerce_recovery_timeout_ms(
                            value,
                            default=None,
                            min_ms=15000,
                            max_ms=180000,
                        )
                        if timeout_value is not None:
                            existing["recovery_overrides"][key_normalized] = timeout_value
            recovery_plan = discovery_recommendation.get("recovery_plan")
            if isinstance(recovery_plan, dict):
                if isinstance(recovery_plan.get("recovery_overrides"), dict):
                    for key, value in recovery_plan.get("recovery_overrides").items():
                        key_normalized = _normalize(key)
                        if key_normalized in RECOVERY_BOOL_OVERRIDE_KEYS:
                            existing.setdefault("recovery_overrides", {})[key_normalized] = _coerce_recovery_bool(
                                value, default=False
                            )
                        elif key_normalized == "capture_response_timeout_ms":
                            timeout_value = _coerce_recovery_timeout_ms(
                                value,
                                default=None,
                                min_ms=15000,
                                max_ms=180000,
                            )
                            if timeout_value is not None:
                                existing.setdefault("recovery_overrides", {})[key_normalized] = timeout_value
                for key in {
                    "verification_only_current_page",
                    "repair_only_current_page",
                    "prepublish_only_current_page",
                    "prepare_only_current_page",
                    "verify_media_upload",
                    "wait_for_publish_confirmation",
                    "capture_response_timeout_ms",
                }:
                    if key in recovery_plan:
                        key_normalized = _normalize(key)
                        if key_normalized == "capture_response_timeout_ms":
                            timeout_value = _coerce_recovery_timeout_ms(
                                recovery_plan.get(key),
                                default=None,
                                min_ms=15000,
                                max_ms=180000,
                            )
                            if timeout_value is not None:
                                existing.setdefault("recovery_overrides", {})[key_normalized] = timeout_value
                        else:
                            existing.setdefault("recovery_overrides", {})[key_normalized] = _coerce_recovery_bool(
                                recovery_plan.get(key), default=False
                            )
    actions = list(existing.get("last_actions") or [])
    if status and status not in actions:
        actions.append(status)
    existing["last_actions"] = actions[-6:]
    entries[signature] = existing
    entries = _prune_recovery_knowledge_entries(entries)
    platforms[platform_key] = entries
    return signature, existing, attempt_count


def _adaptive_recovery_overrides(
    platform: str,
    *,
    attempt_count: int,
    summary: dict[str, Any] | None = None,
    default_trigger: str = "auto_recover",
) -> tuple[dict[str, Any], list[str]]:
    normalized_platform = _normalize(platform).lower().replace("_", "-")
    adaptive_reason: list[str] = []
    status = _normalize(summary.get("status")).lower() if isinstance(summary, dict) else ""
    error_code = _normalize(summary.get("error_code")).lower() if isinstance(summary, dict) else ""
    summary_reasons = {
        _normalize(reason)
        for reason in (summary.get("strict_contract_reasons") or [])
        if _normalize(reason)
    } if isinstance(summary, dict) else set()
    publish_receipt_pending = _is_publish_receipt_pending_summary(summary or {}) if isinstance(summary, dict) else False
    request_payload_plan_match = bool(summary.get("request_payload_plan_match")) if isinstance(summary, dict) else False
    request_fields_snapshot_trusted = bool(summary.get("request_fields_snapshot_trusted")) if isinstance(summary, dict) else False
    request_fields_snapshot_missing = bool(summary.get("request_fields_snapshot_missing")) if isinstance(summary, dict) else False
    receipt_target_unbound = bool(summary.get("receipt_target_unbound")) if isinstance(summary, dict) else False
    pre_publish_upload_pending = bool(summary.get("pre_publish_upload_pending")) if isinstance(summary, dict) else False
    upload_not_applied = bool(summary.get("upload_not_applied")) if isinstance(summary, dict) else False
    route_auth_required = bool(summary.get("route_auth_required")) if isinstance(summary, dict) else False
    summary_blocked_reasons = summary_reasons.intersection(AUTO_RECOVERY_DRAFT_CLEAR_BLOCKED_REASONS)
    is_in_progress = status in {
        "processing",
        "submitted",
        "publishing",
        "ready_to_publish",
        "waiting_publish",
        "uploading",
        "uploading_media",
    }
    is_in_progress_stale = is_in_progress and "active_status_stale" in summary_reasons
    has_fill_gaps_pending = "content_plan_fill_gaps_pending" in summary_reasons
    has_submitted_content_gap = "submitted_content_plan_fill_gaps_pending" in summary_reasons
    has_submitted_plan_gap = has_fill_gaps_pending or has_submitted_content_gap
    has_submitted_empty_snapshot = "submitted_response_payload_empty_snapshot" in summary_reasons
    has_status_blocked = "status_in_progress" in summary_reasons
    timeout_or_draft_clear_terminal = (
        status in {"needs_human", "failed"}
        and error_code in {"publication_task_timeout", "draft_clear_failed"}
    )
    pending_receipt_terminal = (
        timeout_or_draft_clear_terminal
        and request_payload_plan_match
        and (request_fields_snapshot_missing or not request_fields_snapshot_trusted)
    )
    if route_auth_required:
        adaptive_reason.append("当前页面停在登录/鉴权路由，需先恢复账号会话，不清理草稿、不自动重建页面。")
        return {
            "recovery_mode": _normalize(summary.get("error_code")) or "route_auth_required",
            "clear_draft_context": False,
            "force_publish_page_refresh": False,
            "verify_media_upload": False,
            "wait_for_publish_confirmation": False,
            "capture_response_timeout_ms": None,
        }, adaptive_reason
    if pre_publish_upload_pending:
        adaptive_reason.append("预发布字段已通过且仅剩素材上传未就绪，仅允许刷新、核验上传并等待，不清理草稿。")
        return {
            "recovery_mode": default_trigger,
            "clear_draft_context": False,
            "force_publish_page_refresh": True,
            "verify_media_upload": True,
            "wait_for_publish_confirmation": True,
            "capture_response_timeout_ms": None,
        }, adaptive_reason
    if upload_not_applied:
        adaptive_reason.append("上传动作已触发但页面未真正接住媒体，仅允许刷新、重新核验上传并等待，不清理草稿。")
        return {
            "recovery_mode": default_trigger,
            "clear_draft_context": False,
            "force_publish_page_refresh": True,
            "verify_media_upload": True,
            "wait_for_publish_confirmation": True,
            "capture_response_timeout_ms": None,
        }, adaptive_reason
    if receipt_target_unbound:
        adaptive_reason.append("发布后回执尚未唯一绑定到本次作品，仅允许刷新与等待，不清理草稿。")
        return {
            "recovery_mode": default_trigger,
            "clear_draft_context": False,
            "force_publish_page_refresh": True,
            "verify_media_upload": False,
            "wait_for_publish_confirmation": True,
            "capture_response_timeout_ms": None,
        }, adaptive_reason
    if publish_receipt_pending or pending_receipt_terminal:
        adaptive_reason.append("submitted/receipt pending should stay on the current page and rebind receipt before any draft reset.")
        return {
            "recovery_mode": "receipt_rebind",
            "clear_draft_context": False,
            "force_publish_page_refresh": True,
            "verification_only_current_page": True,
            "verify_media_upload": True,
            "wait_for_publish_confirmation": True,
            "capture_response_timeout_ms": max(90000, 45000 + max(0, attempt_count - 1) * 12000),
        }, adaptive_reason
    clear_draft_blocked = bool(summary_blocked_reasons)
    clear_draft_allowed = status in {"failed", "needs_human", "draft_created"} or not clear_draft_blocked
    has_submitted_snapshot_empty_gap = (
        has_submitted_empty_snapshot and status == "submitted"
    )
    if publish_receipt_pending:
        clear_draft_allowed = False
        adaptive_reason.append("提交/处理中仍属待回执场景，仅允许刷新与等待，不清理草稿。")
    if pending_receipt_terminal:
        clear_draft_allowed = False
        adaptive_reason.append("终态仅表现为超时/清稿失败且缺少可信回执，先保留现场并继续等待或刷新。")
    if has_status_blocked and is_in_progress:
        clear_draft_allowed = False
    if status == "submitted" and has_submitted_plan_gap and not publish_receipt_pending:
        clear_draft_allowed = True
    if status == "submitted" and has_submitted_empty_snapshot and not publish_receipt_pending:
        clear_draft_allowed = True
        adaptive_reason.append("提交态 response_payload 关键字段快照为空值，提升为草稿清理优先级。")
    if is_in_progress_stale and not publish_receipt_pending:
        clear_draft_allowed = True
        adaptive_reason.append("发布进行态已超过预期观测窗，放开草稿清理保护。")
    if has_status_blocked and attempt_count >= 2 and not publish_receipt_pending:
        clear_draft_allowed = True
        adaptive_reason.append("进行态阻断码重试 >=2，放开草稿清理保护。")
    if is_in_progress and has_fill_gaps_pending and attempt_count >= 2 and not publish_receipt_pending:
        clear_draft_allowed = True
    clear_draft = False
    if clear_draft_allowed:
        if has_submitted_snapshot_empty_gap and not publish_receipt_pending:
            clear_draft = True
            adaptive_reason.append("提交态 response_payload 关键字段快照为空值，优先清理草稿上下文。")
        else:
            clear_draft = attempt_count >= 3
        if is_in_progress_stale and attempt_count >= 2 and not publish_receipt_pending:
            clear_draft = True
            adaptive_reason.append("进行态持续观测超时，强制开启草稿清理。")
        elif has_status_blocked and attempt_count >= 2 and not publish_receipt_pending:
            clear_draft = True
            adaptive_reason.append("进行态阻断码重试后，尝试清理草稿上下文。")
        if status == "submitted" and has_submitted_plan_gap and attempt_count >= 2 and not publish_receipt_pending:
            clear_draft = True
            adaptive_reason.append("提交态回填待补全，提前尝试清理草稿上下文。")
        elif is_in_progress and has_fill_gaps_pending and attempt_count >= 2 and not publish_receipt_pending:
            clear_draft = True
            adaptive_reason.append("进行态关键字段回填未前移，提前尝试清理草稿上下文。")
    elif attempt_count >= 4 and not publish_receipt_pending and not pending_receipt_terminal:
        # 长时卡死且带有高阻断标记时，允许在第 4 轮放宽草稿清理保护。
        clear_draft = True
        adaptive_reason.append("历史同类失败>=4，放宽草稿清理阻塞。")
    elif has_fill_gaps_pending and attempt_count >= 3 and not publish_receipt_pending:
        # 针对“发布中回填待补全”这类场景，允许更早清理草稿上下文。
        clear_draft = True
        clear_draft_allowed = True
        adaptive_reason.append("发布进行态持续有回填待补全，尝试清理草稿上下文。")
    unstable_status = status in {"processing", "publishing", "waiting_publish", "ready_to_publish", "submitted", "in_progress"}
    verify_media_upload = (
        clear_draft_allowed
        or clear_draft
        or has_fill_gaps_pending
        or unstable_status
        or status in {"draft_created", "needs_human", "failed"}
        or attempt_count >= 2
    )
    wait_for_publish_confirmation = (
        has_fill_gaps_pending
        or unstable_status
        or status in {"draft_created", "needs_human", "failed"}
        or clear_draft
        or attempt_count >= 2
    )
    capture_response_timeout_ms = _coerce_recovery_timeout_ms(
        45000 + max(0, attempt_count - 1) * 12000,
        default=45000,
        min_ms=30000,
        max_ms=120000,
    ) or 45000
    if has_fill_gaps_pending:
        capture_response_timeout_ms = max(capture_response_timeout_ms, 90000)
    if has_submitted_snapshot_empty_gap:
        capture_response_timeout_ms = max(capture_response_timeout_ms, 120000)
    if unstable_status:
        capture_response_timeout_ms = max(capture_response_timeout_ms, 70000)
    if verify_media_upload:
        adaptive_reason.append("检测到疑似发布态异常，开启上传后复核 + 发布确认等待。")
    if wait_for_publish_confirmation:
        adaptive_reason.append("开启发布确认等待窗口，降低字段空值与伪成功回执风险。")
    force_refresh = attempt_count >= 2
    reset_mode: str | None = None
    if attempt_count >= 4 and clear_draft:
        reset_mode = "draft_reset"
        if "历史同类失败>=4，放宽草稿清理阻塞。" not in adaptive_reason:
            adaptive_reason.append("历史同类失败>=4，进入草稿重置。")
    elif attempt_count >= 3 and clear_draft:
        if not any("尝试清理草稿上下文" in item for item in adaptive_reason):
            adaptive_reason.append("历史同类失败>=3，尝试清理草稿上下文。")
    elif force_refresh:
        adaptive_reason.append("历史同类失败>=2，强制刷新发布页。")
    overrides = {
        "recovery_mode": default_trigger,
        "clear_draft_context": clear_draft,
        "force_publish_page_refresh": force_refresh,
        "verify_media_upload": verify_media_upload,
        "wait_for_publish_confirmation": wait_for_publish_confirmation,
        "capture_response_timeout_ms": capture_response_timeout_ms,
    }
    if reset_mode:
        overrides["recovery_mode"] = reset_mode
    return overrides, adaptive_reason


def _sanitize_recovery_overrides_for_summary(
    recovery_overrides: dict[str, Any],
    *,
    summary: dict[str, Any] | None,
    default_recovery_mode: str,
) -> tuple[dict[str, Any], list[str]]:
    normalized = dict(recovery_overrides or {})
    if not isinstance(summary, dict):
        return normalized, []
    status = _normalize(summary.get("status")).lower()
    error_code = _normalize(summary.get("error_code")).lower()
    publish_receipt_pending = _is_publish_receipt_pending_summary(summary)
    request_payload_plan_match = bool(summary.get("request_payload_plan_match"))
    request_fields_snapshot_trusted = bool(summary.get("request_fields_snapshot_trusted"))
    request_fields_snapshot_missing = bool(summary.get("request_fields_snapshot_missing"))
    pending_receipt_terminal = (
        status in {"needs_human", "failed"}
        and error_code in {"publication_task_timeout", "draft_clear_failed"}
        and request_payload_plan_match
        and (request_fields_snapshot_missing or not request_fields_snapshot_trusted)
    )
    reasons: list[str] = []
    if bool(summary.get("receipt_target_unbound")):
        if _coerce_recovery_bool(normalized.get("clear_draft_context"), default=False):
            normalized["clear_draft_context"] = False
        if _normalize(normalized.get("recovery_mode")) == "draft_reset":
            normalized["recovery_mode"] = default_recovery_mode
        normalized["force_publish_page_refresh"] = True
        normalized["wait_for_publish_confirmation"] = True
        reasons.append("发布后回执尚未唯一绑定到本次作品，忽略 clear_draft_context，保留现场继续刷新并核对回执。")
    if bool(summary.get("route_auth_required")):
        if _coerce_recovery_bool(normalized.get("clear_draft_context"), default=False):
            normalized["clear_draft_context"] = False
        normalized["force_publish_page_refresh"] = False
        normalized["verify_media_upload"] = False
        normalized["wait_for_publish_confirmation"] = False
        if _normalize(normalized.get("recovery_mode")) == "draft_reset":
            normalized["recovery_mode"] = default_recovery_mode
        reasons.append("当前页面停在登录/鉴权路由，忽略 clear_draft_context，需先恢复账号会话。")
    if bool(summary.get("post_repair_preserve_context")):
        if _coerce_recovery_bool(normalized.get("clear_draft_context"), default=False):
            normalized["clear_draft_context"] = False
        if _normalize(normalized.get("recovery_mode")) == "draft_reset":
            normalized["recovery_mode"] = default_recovery_mode
        normalized["force_publish_page_refresh"] = True
        reasons.append("预发布已完成字段级修复且仅剩结构性 blocker，忽略 clear_draft_context，保留现场继续刷新/等待。")
    if bool(summary.get("upload_not_applied")):
        if _coerce_recovery_bool(normalized.get("clear_draft_context"), default=False):
            normalized["clear_draft_context"] = False
        if _normalize(normalized.get("recovery_mode")) == "draft_reset":
            normalized["recovery_mode"] = default_recovery_mode
        normalized["force_publish_page_refresh"] = True
        normalized["verify_media_upload"] = True
        normalized["wait_for_publish_confirmation"] = True
        reasons.append("上传动作已触发但页面未真正接住媒体，忽略 clear_draft_context，保留现场继续刷新并复核上传。")
    if publish_receipt_pending or pending_receipt_terminal:
        if _coerce_recovery_bool(normalized.get("clear_draft_context"), default=False):
            normalized["clear_draft_context"] = False
            if _normalize(normalized.get("recovery_mode")) == "draft_reset":
                normalized["recovery_mode"] = default_recovery_mode
            reasons.append("待回执场景忽略 discovery/history 的 clear_draft_context，保留现场仅刷新与等待。")
    if publish_receipt_pending or pending_receipt_terminal:
        normalized["recovery_mode"] = "receipt_rebind"
        normalized["force_publish_page_refresh"] = True
        normalized["verification_only_current_page"] = True
        normalized["verify_media_upload"] = True
        normalized["wait_for_publish_confirmation"] = True
        reasons.append("submitted/receipt pending should switch to safe receipt_rebind on the current page instead of draft reset.")
    return normalized, reasons


def _summarize_recovery_knowledge_base(knowledge_base: dict[str, Any]) -> dict[str, Any]:
    platforms = knowledge_base.get("platforms")
    if not isinstance(platforms, dict):
        return {"version": RECOVERY_KNOWLEDGE_BASE_VERSION, "platforms": {}, "entries": 0, "prepublish_platforms": {}, "prepublish_entries": 0}
    prepublish_platforms = knowledge_base.get("prepublish_platforms")
    if not isinstance(prepublish_platforms, dict):
        prepublish_platforms = {}
    prepublish_entry_count = sum(
        len(entries) for entries in prepublish_platforms.values() if isinstance(entries, dict)
    )
    return {
        "version": int(knowledge_base.get("version") or RECOVERY_KNOWLEDGE_BASE_VERSION),
        "updated_at": _normalize(knowledge_base.get("updated_at")),
        "platform_count": len(platforms),
        "entries": sum(len(entries) for entries in platforms.values() if isinstance(entries, dict)),
        "prepublish_platform_count": len(prepublish_platforms),
        "prepublish_entries": prepublish_entry_count,
        "top_entries": {
            platform: [
                {
                    "signature": entry.get("signature") or key,
                    "count": int(entry.get("count") or 0),
                    "last_seen": _normalize(entry.get("last_seen")),
                    "error_code": _normalize(entry.get("error_code")),
                    "reason": _normalize(entry.get("reason")),
                    "playbook_actions": list(entry.get("playbook_actions") or [])[-6:] if isinstance(entry.get("playbook_actions"), list) else [],
                    "discovery_recommendation_action": _normalize((entry.get("discovery_recommendation") or {}).get("action"))
                    if isinstance(entry.get("discovery_recommendation"), dict)
                    else "",
                    "discovery_actions": list(entry.get("discovery_actions") or [])[-6:] if isinstance(entry.get("discovery_actions"), list) else [],
                    "discovery_retryable": bool(entry.get("discovery_retryable")),
                    "discovery_trigger": _normalize(entry.get("discovery_trigger")),
                    "verify_media_upload": bool(entry.get("verify_media_upload")),
                    "wait_for_publish_confirmation": bool(entry.get("wait_for_publish_confirmation")),
                    "verification_only_current_page": bool(entry.get("verification_only_current_page")),
                    "repair_only_current_page": bool(entry.get("repair_only_current_page")),
                    "prepublish_only_current_page": bool(entry.get("prepublish_only_current_page")),
                    "prepare_only_current_page": bool(entry.get("prepare_only_current_page")),
                    "capture_response_timeout_ms": _to_non_negative_int(entry.get("capture_response_timeout_ms")),
                }
                for key, entry in sorted(
                    entries.items(),
                    key=lambda item: int((item[1] or {}).get("count") or 0),
                    reverse=True,
                )[:3]
            ]
            for platform, entries in platforms.items()
            if isinstance(entries, dict)
        },
        "prepublish_top_entries": {
            platform: [
                {
                    "signature": entry.get("signature") or key,
                    "count": int(entry.get("count") or 0),
                    "last_seen": _normalize(entry.get("last_seen")),
                    "error_code": _normalize(entry.get("error_code")),
                    "signature_text": _normalize(entry.get("signature_text")),
                    "reasons": list(entry.get("reasons") or []),
                    "status": _normalize(entry.get("status")),
                    "snapshot_source": _normalize(entry.get("snapshot_source")),
                    "clear_draft_context": bool(entry.get("clear_draft_context")),
                    "force_publish_page_refresh": bool(entry.get("force_publish_page_refresh")),
                    "verify_media_upload": bool(entry.get("verify_media_upload")),
                    "wait_for_publish_confirmation": bool(entry.get("wait_for_publish_confirmation")),
                    "verification_only_current_page": bool(entry.get("verification_only_current_page")),
                    "repair_only_current_page": bool(entry.get("repair_only_current_page")),
                    "prepublish_only_current_page": bool(entry.get("prepublish_only_current_page")),
                    "prepare_only_current_page": bool(entry.get("prepare_only_current_page")),
                    "capture_response_timeout_ms": _to_non_negative_int(entry.get("capture_response_timeout_ms")),
                }
                for key, entry in sorted(
                    entries.items(),
                    key=lambda item: int((item[1] or {}).get("count") or 0),
                    reverse=True,
                )[:3]
            ]
            for platform, entries in prepublish_platforms.items()
            if isinstance(entries, dict)
        },
    }


def _canonical_media_path(media_path: str) -> str:
    normalized = _normalize(media_path)
    if not normalized:
        return ""
    try:
        return str(Path(normalized).resolve())
    except OSError:
        return normalized


def _suffix_for_release_gate(explicit_suffix: str = "", media_path: str = "") -> str:
    normalized = _normalize(explicit_suffix)
    if normalized:
        return normalized
    path = Path(_canonical_media_path(media_path))
    if not path.is_file():
        return ""
    try:
        file_stat = path.stat()
        signature = f"{path.name}|{int(file_stat.st_size)}|{int(file_stat.st_mtime)}"
        return hashlib.sha1(signature.encode("utf-8")).hexdigest()[:10]
    except OSError:
        return ""


def _coerce_text_list(value: Any, *, max_items: int = 48) -> list[str]:
    if isinstance(value, str):
        normalized = _normalize(value)
        if not normalized:
            return []
        return [_normalize(item) for item in normalized.split(",") if _normalize(item)][:max_items]
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            text = _normalize(item)
            if text:
                values.append(text)
        if not values:
            return []
        return values[:max_items]
    return []


def _coerce_request_payload_tags(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return []
    tags = _coerce_text_list(payload.get("hashtags"))
    if tags:
        return tags
    copy_material = payload.get("copy_material")
    if not isinstance(copy_material, dict):
        copy_material = {}
    return _coerce_text_list(copy_material.get("tags"))


def _coerce_packaging_collection(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        normalized_items = {
            str(key).strip(): (
                _normalize(item) if isinstance(item, str) or isinstance(item, (int, float, bool)) else item
            )
            for key, item in value.items()
            if str(key).strip()
        }
        return normalized_items or None
    if _normalize(value):
        return {"name": _normalize(value)}
    return None


def _merge_packaging_body_with_x_link_share(
    platform: str,
    body: str,
    *,
    x_share_link: str,
    x_link_share_mode: bool,
) -> str:
    normalized_platform = _normalize(platform).lower().replace("_", "-")
    normalized_body = _normalize(body)
    normalized_link = _normalize(x_share_link)
    if not (normalized_platform == "x" and x_link_share_mode and normalized_link):
        return normalized_body
    if not normalized_body:
        return normalized_link
    if normalized_link in normalized_body:
        return normalized_body
    return f"{normalized_body}\n{normalized_link}"


def _normalize_platform_packaging_payload(raw_packaging: Any) -> dict[str, dict[str, Any]]:
    packaging = normalize_publication_packaging_payload(raw_packaging)
    platforms = packaging.get("platforms") if isinstance(packaging, dict) and isinstance(packaging.get("platforms"), dict) else {}
    return {normalize_publication_platform(platform): dict(entry) for platform, entry in platforms.items() if isinstance(entry, dict)}


def _extract_platform_packaging_scope(raw_packaging: Any) -> dict[str, list[str]]:
    return extract_publication_packaging_scope(raw_packaging)


def _resolve_platform_packaging_input_path(path: str, material_json: str = "") -> Path | None:
    _material_json_path, packaging_path = resolve_publication_packaging_input_paths(
        material_json=material_json,
        platform_packaging=path,
    )
    return packaging_path


def _load_platform_packaging_payload(path: str, material_json: str = "") -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], list[str]]:
    packaging_path = _resolve_platform_packaging_input_path(path, material_json)
    normalized_path = _normalize(path)
    normalized_material_json = _normalize(material_json)
    if packaging_path is None and not normalized_path and not normalized_material_json:
        return {}, {}, []
    if packaging_path is None and normalized_path:
        candidate = Path(normalized_path)
        if not candidate.exists():
            return {}, {}, [f"发布文案文件不存在: {candidate}"]
        if not candidate.is_file():
            return {}, {}, [f"发布文案路径不是文件: {candidate}"]
        return {}, {}, [f"发布文案文件不可用: {candidate}"]
    if packaging_path is None and normalized_material_json:
        candidate = Path(normalized_material_json).with_name("platform-packaging.json")
        return {}, {}, [f"发布文案文件不存在: {candidate}"]
    if not packaging_path.exists():
        return {}, {}, [f"发布文案文件不存在: {packaging_path}"]
    if not packaging_path.is_file():
        return {}, {}, [f"发布文案路径不是文件: {packaging_path}"]
    payload = load_json_payload(packaging_path)
    if payload is None:
        try:
            json.loads(packaging_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            return {}, {}, [f"发布文案文件 JSON 解析失败: {exc}"]
        except Exception as exc:
            return {}, {}, [f"发布文案文件读取失败: {exc}"]
        return {}, {}, ["发布文案文件中未发现可用的平台文案数据"]
    try:
        normalized_packaging = _normalize_platform_packaging_payload(payload)
        platform_scope = _extract_platform_packaging_scope(payload)
    except json.JSONDecodeError as exc:
        return {}, {}, [f"发布文案文件 JSON 解析失败: {exc}"]
    except Exception as exc:
        return {}, {}, [f"发布文案文件读取失败: {exc}"]
    if not normalized_packaging:
        return {}, platform_scope, ["发布文案文件中未发现可用的平台文案数据"]
    return normalized_packaging, platform_scope, []


def _coerce_platform_packaging_entry(
    platform: str,
    entry: dict[str, Any] | None,
    *,
    fallback_title: str,
    fallback_description: str,
) -> dict[str, Any]:
    normalized_platform = _normalize(platform).lower().replace("_", "-")
    raw = entry or {}
    raw_title_values = raw.get("titles") if isinstance(raw.get("titles"), (list, tuple, set)) else None
    if not raw_title_values and isinstance(raw.get("title"), str):
        raw_title_values = [raw.get("title")]
    if not raw_title_values and isinstance(raw.get("primary_title"), str):
        raw_title_values = [raw.get("primary_title")]
    if isinstance(raw_title_values, (list, tuple, set)):
        parsed_title_values = []
        for item in raw_title_values:
            if isinstance(item, dict):
                parsed_title_values.append(_normalize(item.get("text")))
            else:
                parsed_title_values.append(_normalize(item))
        raw_title_values = [item for item in parsed_title_values if item]
    else:
        raw_title_values = []
    title = _normalize(raw.get("title")) or (
        _normalize(raw_title_values[0])
        if raw_title_values
        else ""
    )
    title_suffix = _normalize(fallback_title)
    fallback_title_tag = f"{title}{' [' + title_suffix + ']' if title_suffix and title_suffix not in title else ''}" if title else ""
    platform_title = title or title_suffix or fallback_title_tag or normalized_platform or "RoughCut发布素材"
    if normalized_platform == "youtube" and "youtube" not in platform_title.lower():
        platform_title = platform_title.replace(normalized_platform, "YouTube").replace("youtube", "YouTube")

    description = (
        _normalize(raw.get("description"))
        or _normalize(raw.get("body"))
        or _normalize(fallback_description)
        or f"RoughCut 正式发布素材：{platform_title}"
    )
    tags = _coerce_text_list(raw.get("tags")) or ["RoughCut", "发布", normalized_platform]
    collection_name = _normalize(raw.get("collection_name"))
    collection = raw.get("collection")
    if collection is None and collection_name:
        collection = {"name": collection_name}
    declaration = _normalize(raw.get("declaration") or raw.get("content_declaration"))
    if not declaration:
        declaration = platform_default_declaration(platform) or platform_default_declaration(normalized_platform)
    scheduled_publish_at = _normalize(raw.get("scheduled_publish_at"))
    visibility_override = _normalize(raw.get("visibility_or_publish_mode") or raw.get("visibility"))
    if not visibility_override:
        visibility_override = _normalize(raw.get("publish_mode"))
    if not visibility_override and normalized_platform == "youtube":
        visibility_override = "scheduled" if scheduled_publish_at else "public"
    category = _sanitize_publication_target_category(normalized_platform, _normalize(raw.get("category")))
    if not collection:
        collection = _coerce_packaging_collection(raw.get("collection"))
    claim_refs = raw.get("claim_refs")
    if claim_refs is None:
        claim_refs = raw.get("copy_refs")
    if not isinstance(claim_refs, (list, tuple, set)):
        claim_refs = []
    claim_refs = [str(item).strip() for item in claim_refs if str(item).strip()]
    cover_slots = derive_publication_cover_slots(raw)
    primary_cover_path = publication_primary_cover_path(raw)
    return {
        "titles": [platform_title]
        if not isinstance(raw.get("titles"), (list, tuple, set))
        else _coerce_text_list(raw.get("titles")) or [platform_title],
        "description": description,
        "tags": tags,
        "collection": collection,
        "category": category or None,
        "declaration": declaration or None,
        "cover_path": _normalize(primary_cover_path or raw.get("cover_path")),
        "cover_slots": cover_slots,
        "full_copy": _normalize(raw.get("full_copy")),
        "visibility_override": visibility_override,
        "visibility_or_publish_mode": visibility_override,
        "scheduled_publish_at": scheduled_publish_at,
        "platform_specific_overrides": dict(raw.get("platform_specific_overrides"))
        if isinstance(raw.get("platform_specific_overrides"), dict)
        else {},
        "copy_material": dict(raw.get("copy_material"))
        if isinstance(raw.get("copy_material"), dict)
        else {},
        "publish_ready": publication_packaging_entry_publish_ready(raw),
        "blocking_reasons": publication_packaging_entry_blocking_reasons(raw),
        "claim_refs": claim_refs,
        "copy_refs": claim_refs,
    }


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _now_dt() -> datetime:
    return datetime.now(ZoneInfo("Asia/Shanghai"))


def _record_is_recent(record_time: Any, now: datetime, *, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    if not isinstance(record_time, datetime):
        return False
    try:
        age_seconds = now.timestamp() - record_time.timestamp()
    except Exception:
        return False
    return age_seconds <= ttl_seconds


def _platforms(raw_platforms: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in raw_platforms:
        value = _normalize(item).lower().replace("_", "-")
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def _expected_statuses(raw_statuses: str) -> set[str]:
    status_list = [_normalize(item).lower() for item in _normalize(raw_statuses).split(",") if _normalize(item)]
    if not status_list:
        return {"published", "scheduled_pending"}
    return set(status_list)


def _looks_like_browser_profile_target(value: Any) -> bool:
    normalized = _normalize(value).lower()
    return normalized.startswith("browser-profile:") or normalized.startswith("browser-agent:")


def _collect_profile_requirements_violations(
    target_profile_ids: list[str],
    requested_platforms: list[str],
    *,
    allow_anonymous_profile: bool,
) -> list[str]:
    normalized_profiles = [_normalize(item) for item in (target_profile_ids or []) if _normalize(item)]
    if allow_anonymous_profile:
        return []
    if not normalized_profiles:
        normalized_platforms = [_normalize(item).lower().replace("_", "-") for item in (requested_platforms or []) if _normalize(item)]
        if not normalized_platforms:
            return []
        return [
            "真实发布前置：未检测到 --target-profile-id。稳定平台已开启禁止匿名执行，避免进入无状态/垃圾测试态。"
            "请使用 fas 账号创建的 profile 并通过 --target-profile-id 显式绑定。"
        ]
    return []


def _looks_like_public_url(value: Any) -> bool:
    text = _normalize(value).lower()
    if not (text.startswith("http://") or text.startswith("https://")):
        return False
    backstage_tokens = ("creator", "studio", "manager", "admin", "dashboard", "publish", "draft", "upload")
    return not any(token in text for token in backstage_tokens)


def _extract_publication_signature(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    raw_signature = payload.get("publication_content_signature")
    if raw_signature is None:
        raw_signature = payload.get("content_signature")
    if raw_signature is None:
        raw_signature = payload.get("publication_plan_signature")
    if isinstance(raw_signature, dict):
        return _normalize(raw_signature.get("value"))
    return _normalize(raw_signature)


def _extract_publication_signature_fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw_signature = payload.get("publication_content_signature")
    if not isinstance(raw_signature, dict):
        raw_signature = payload.get("publication_plan_signature")
    if not isinstance(raw_signature, dict):
        return {}
    raw_fields = raw_signature.get("fields")
    if not isinstance(raw_fields, dict):
        return {}
    return {
        str(key): _normalize_comparable_value(value)
        for key, value in raw_fields.items()
    }


def _extract_publication_field_snapshot(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
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
            if "actual" in raw_value and raw_value.get("actual") is not None:
                return _coerce_snapshot_value(raw_value.get("actual"))
            if "value" in raw_value and raw_value.get("value") is not None:
                return _coerce_snapshot_value(raw_value.get("value"))
            if "expected" in raw_value and raw_value.get("expected") is not None:
                return _coerce_snapshot_value(raw_value.get("expected"))
            return {
                str(key).strip(): _coerce_snapshot_value(item)
                for key, item in raw_value.items()
                if str(key).strip()
            }
        return raw_value

    def _coerce_publication_field_snapshot(raw_value: Any) -> dict[str, Any]:
        if not isinstance(raw_value, dict):
            return {}
        return {
            str(key).strip(): _coerce_snapshot_value(value)
            for key, value in raw_value.items()
            if str(key).strip()
        }

    def _normalize_schedule_snapshot_value(raw_value: Any) -> Any:
        text = _normalize(raw_value)
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
                kind = _normalize(item.get("kind")).lower()
                if "material_integrity" in kind:
                    synthesized = {
                        "fields": item.get("fields"),
                        "failures": item.get("failures"),
                        "platform": item.get("platform"),
                        "verified": item.get("verified"),
                    }
                    platform_extras = item.get("platform_extras")
                    if isinstance(platform_extras, dict) and platform_extras:
                        synthesized["platform_extras"] = platform_extras
                    return synthesized
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
        title_value = _normalize(title_field.get("actual") if title_field.get("actual") is not None else title_field.get("expected"))
        body_value = _normalize(body_field.get("actual") if body_field.get("actual") is not None else body_field.get("expected"))
        tags_value = tags_field.get("actual")
        if not isinstance(tags_value, list) or not tags_value:
            tags_value = tags_field.get("expected") if isinstance(tags_field.get("expected"), list) else []
        if title_value:
            snapshot["title"] = title_value
        if body_value:
            snapshot["body"] = body_value
        if tags_value:
            normalized_tags = [_normalize(tag) for tag in tags_value if _normalize(tag)]
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
        if _has_non_empty_plan_value(collection_value):
            snapshot["collection"] = collection_value
        declaration_value = _normalize(
            declaration_field.get("actual") if declaration_field.get("actual") is not None else declaration_field.get("expected")
        )
        if declaration_value:
            snapshot["declaration"] = declaration_value
        platform_value = _normalize(material_integrity.get("platform") or container.get("platform"))
        if platform_value:
            snapshot["platform"] = platform_value
        return snapshot

    def _extract_from_audit_checklist(container: Any) -> dict[str, Any]:
        if not isinstance(container, dict):
            return {}
        checklist = container.get("checklist")
        if not isinstance(checklist, dict) or not checklist:
            return {}
        return {
            str(key).strip(): _coerce_snapshot_value(value)
            for key, value in checklist.items()
            if str(key).strip()
        }

    def _extract_from_dict(container: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(container, dict):
            return {}
        candidates: list[tuple[int, dict[str, Any]]] = []

        def _push_candidate(snapshot: dict[str, Any] | None, priority: int) -> None:
            if isinstance(snapshot, dict) and snapshot:
                candidates.append((priority, snapshot))

        explicit_snapshot = _coerce_publication_field_snapshot(container.get("publication_field_snapshot"))
        _push_candidate(explicit_snapshot, 1)
        direct_fields = container.get("fields")
        if isinstance(direct_fields, dict) and direct_fields:
            _push_candidate(_coerce_publication_field_snapshot(direct_fields), 2)
        integrity_fields = _extract_from_material_integrity(container)
        _push_candidate(integrity_fields, 5)
        direct_audit_fields = _extract_from_audit_checklist(container.get("publication_audit"))
        _push_candidate(direct_audit_fields, 3)
        details = container.get("details")
        if isinstance(details, dict):
            for stage in ("after", "before"):
                stage_payload = details.get(stage)
                if isinstance(stage_payload, dict):
                    stage_fields = stage_payload.get("fields")
                    if isinstance(stage_fields, dict) and stage_fields:
                        _push_candidate(_coerce_publication_field_snapshot(stage_fields), 4 if stage == "after" else 3)
        timeout_progress = container.get("timeout_progress")
        if isinstance(timeout_progress, dict):
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

    _push_top(_coerce_publication_field_snapshot(payload.get("publication_field_snapshot")), 1)
    _push_top(_extract_from_dict(payload), 2)
    error_payload = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    _push_top(_extract_from_dict(error_payload), 3)
    _push_top(_extract_from_dict(task_progress), 7)
    _push_top(_extract_from_dict(task_result), 6)
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    _push_top(_extract_from_dict(result_payload), 5)
    _push_top(_extract_from_dict(task_payload), 4)
    _push_top(_extract_from_audit_checklist(result_payload.get("publication_audit")), 4)
    if not top_candidates:
        return _extract_request_payload_fields(payload)

    def _top_score(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int, int]:
        priority, snapshot = item
        field_count = len([key for key, value in snapshot.items() if value not in (None, "", [], {})])
        has_schedule = int(bool(snapshot.get("scheduled_publish_at")))
        has_body = int(bool(snapshot.get("body")))
        has_tags = int(bool(snapshot.get("hashtags") or snapshot.get("display_hashtags") or snapshot.get("structured_tags")))
        return (field_count, has_schedule, has_body + has_tags, priority)

    return max(top_candidates, key=_top_score)[1]


def _extract_publication_audit(payload: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(payload, dict):
        return {}, []
    raw_audit = payload.get("publication_audit") if isinstance(payload.get("publication_audit"), dict) else {}
    if not raw_audit:
        task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
        task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
        task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
        for candidate in (task_progress, task_result, task_payload):
            if isinstance(candidate.get("publication_audit"), dict):
                raw_audit = candidate.get("publication_audit")
                break
            timeout_progress = candidate.get("timeout_progress") if isinstance(candidate.get("timeout_progress"), dict) else {}
            if isinstance(timeout_progress.get("publication_audit"), dict):
                raw_audit = timeout_progress.get("publication_audit")
                break
            material_integrity = candidate.get("material_integrity") if isinstance(candidate.get("material_integrity"), dict) else {}
            if isinstance(material_integrity.get("fields"), dict) and material_integrity.get("fields"):
                raw_audit = {
                    "verified": bool(material_integrity.get("verified")),
                    "checklist": material_integrity.get("fields"),
                    "required_unverified": list(material_integrity.get("failures") or []),
                    "issues": list(material_integrity.get("failures") or []),
                    "summary": {
                        "status": "ok" if material_integrity.get("verified") else "error",
                    },
                }
                platform_extras = material_integrity.get("platform_extras")
                if isinstance(platform_extras, dict) and platform_extras:
                    raw_audit["platform_extras"] = platform_extras
                break
    if not raw_audit:
        return {}, []
    status = str(
        (
            raw_audit.get("summary")
            if isinstance(raw_audit.get("summary"), dict)
            else {}
        ).get("status")
        or raw_audit.get("status")
        or ""
    ).strip().lower()
    issues: list[str] = []
    if status == "error":
        for item in raw_audit.get("issues", []) if isinstance(raw_audit.get("issues"), list) else []:
            if isinstance(item, dict):
                message = _normalize(item.get("message"))
                if message:
                    issues.append(message)
            else:
                message = _normalize(item)
                if message:
                    issues.append(message)
    return raw_audit, issues


def _extract_material_integrity(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for candidate in (
        payload,
        task_progress,
        task_result,
        payload.get("result") if isinstance(payload.get("result"), dict) else {},
        task_payload,
    ):
        if isinstance(candidate, dict) and candidate:
            candidates.append(candidate)
        timeout_progress = candidate.get("timeout_progress") if isinstance(candidate, dict) and isinstance(candidate.get("timeout_progress"), dict) else {}
        if timeout_progress:
            candidates.append(timeout_progress)
    for candidate in candidates:
        material_integrity = candidate.get("material_integrity")
        if isinstance(material_integrity, dict) and material_integrity:
            return material_integrity
    return {}


def _coerce_visual_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    artifact_path = _normalize(payload.get("artifact_path"))
    if not artifact_path:
        return {}
    normalized: dict[str, Any] = {
        "artifact_path": artifact_path,
        "capture_type": _normalize(payload.get("capture_type")) or "screenshot",
        "mime_type": _normalize(payload.get("mime_type")) or "image/png",
        "sha256": _normalize(payload.get("sha256")),
        "captured_at": _normalize(payload.get("captured_at")),
        "platform": _normalize(payload.get("platform")),
        "phase": _normalize(payload.get("phase")),
        "route_url": _normalize(payload.get("route_url")),
        "route_title": _normalize(payload.get("route_title")),
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
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for candidate in (payload, result_payload, task_result, task_progress, task_payload):
        if isinstance(candidate, dict) and candidate:
            candidates.append(candidate)
        timeout_progress = candidate.get("timeout_progress") if isinstance(candidate, dict) and isinstance(candidate.get("timeout_progress"), dict) else {}
        if timeout_progress:
            candidates.append(timeout_progress)
    for candidate in candidates:
        visual_evidence = _coerce_visual_evidence(candidate.get("visual_evidence"))
        if visual_evidence:
            return visual_evidence
    return {}


def _extract_pre_publish_repair(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for candidate in (payload, result_payload, task_result, task_progress, task_payload):
        if isinstance(candidate, dict) and candidate:
            candidates.append(candidate)
        timeout_progress = candidate.get("timeout_progress") if isinstance(candidate, dict) and isinstance(candidate.get("timeout_progress"), dict) else {}
        if timeout_progress:
            candidates.append(timeout_progress)
    for candidate in candidates:
        final_publish = candidate.get("final_publish")
        if not isinstance(final_publish, dict):
            continue
        pre_publish_repair = final_publish.get("pre_publish_repair")
        if isinstance(pre_publish_repair, dict) and pre_publish_repair:
            return pre_publish_repair
    return {}


def _extract_final_publish(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    candidates: list[dict[str, Any]] = []
    for candidate in (payload, result_payload, task_result, task_progress, task_payload):
        if isinstance(candidate, dict) and candidate:
            candidates.append(candidate)
        timeout_progress = candidate.get("timeout_progress") if isinstance(candidate, dict) and isinstance(candidate.get("timeout_progress"), dict) else {}
        if timeout_progress:
            candidates.append(timeout_progress)
    for candidate in candidates:
        final_publish = candidate.get("final_publish")
        if isinstance(final_publish, dict) and final_publish:
            return final_publish
    return {}


_POST_REPAIR_NON_DRAFT_RESET_FIELDS = {"upload_ready", "receipt"}


def _coerce_repair_evidence(payload: Any) -> dict[str, bool]:
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, bool] = {}
    for key, value in payload.items():
        name = _normalize(key)
        if not name:
            continue
        normalized[name] = bool(value)
    return normalized


def _extract_receipt_binding(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    def _coerce_binding(raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        has_target_bound = isinstance(raw.get("receipt_target_bound"), bool)
        receipt_like = bool(raw.get("receipt_like"))
        binding_source = _normalize(raw.get("receipt_binding_source"))
        post_publish_surface = _normalize(raw.get("post_publish_surface"))
        if not (has_target_bound or receipt_like or binding_source or post_publish_surface):
            return {}
        normalized: dict[str, Any] = {
            "receipt_like": receipt_like,
            "receipt_binding_source": binding_source,
            "post_publish_surface": post_publish_surface,
        }
        if has_target_bound:
            normalized["receipt_target_bound"] = bool(raw.get("receipt_target_bound"))
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


def _extract_receipt_binding_id(payload: Any, receipt_binding: dict[str, Any] | None = None) -> str:
    candidates: list[dict[str, Any]] = []
    if isinstance(payload, dict):
        candidates.append(payload)
        result_payload = payload.get("result")
        if isinstance(result_payload, dict):
            candidates.append(result_payload)
        task_payload = payload.get("task")
        if isinstance(task_payload, dict):
            candidates.append(task_payload)
            task_result = task_payload.get("result")
            if isinstance(task_result, dict):
                candidates.append(task_result)
    for candidate in candidates:
        receipt_id = _normalize(candidate.get("receipt_id"))
        if receipt_id:
            return receipt_id
        external_receipt_id = _normalize(candidate.get("external_receipt_id"))
        if external_receipt_id:
            return external_receipt_id
    return _derive_receipt_binding_fallback_id(receipt_binding or {})


def _is_receipt_target_unbound(receipt_binding: dict[str, Any] | None) -> bool:
    if not isinstance(receipt_binding, dict) or not receipt_binding:
        return False
    return bool(receipt_binding.get("receipt_like")) and receipt_binding.get("receipt_target_bound") is False


def _has_pre_publish_repair_progress(
    *,
    pre_publish_repair: dict[str, Any],
    repair_evidence: dict[str, Any],
) -> bool:
    if not isinstance(pre_publish_repair, dict) or not pre_publish_repair.get("attempted"):
        return False
    normalized_evidence = _coerce_repair_evidence(repair_evidence)
    if any(normalized_evidence.values()):
        return True
    before_required = [_normalize(item) for item in (pre_publish_repair.get("before_required_unverified") or []) if _normalize(item)]
    after_required = [_normalize(item) for item in (pre_publish_repair.get("after_required_unverified") or []) if _normalize(item)]
    if before_required and len(after_required) < len(before_required):
        return True
    actions = pre_publish_repair.get("actions")
    return isinstance(actions, list) and bool(actions)


def _is_post_repair_structural_blocker_context(
    *,
    pre_publish_repair: dict[str, Any],
    repair_evidence: dict[str, Any],
    required_unverified: list[str] | None = None,
    required_reupload: list[str] | None = None,
) -> bool:
    if not _has_pre_publish_repair_progress(
        pre_publish_repair=pre_publish_repair,
        repair_evidence=repair_evidence,
    ):
        return False
    remaining = {
        _normalize(item)
        for item in [*(required_unverified or []), *(required_reupload or [])]
        if _normalize(item)
    }
    return bool(remaining) and remaining.issubset(_POST_REPAIR_NON_DRAFT_RESET_FIELDS)


def _is_pre_publish_upload_pending_summary(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    error_code = _normalize(summary.get("error_code")).lower()
    if not error_code.endswith("_pre_publish_upload_pending"):
        return False
    publication_audit = summary.get("publication_audit") if isinstance(summary.get("publication_audit"), dict) else {}
    remaining = {
        _normalize(item)
        for item in [
            *(publication_audit.get("required_unverified") or []),
            *(publication_audit.get("required_reupload") or []),
        ]
        if _normalize(item)
    }
    if bool(remaining):
        return remaining.issubset(_POST_REPAIR_NON_DRAFT_RESET_FIELDS)
    material_integrity = summary.get("material_integrity") if isinstance(summary.get("material_integrity"), dict) else {}
    return _is_material_integrity_pending(material_integrity)


def _extract_upload_failure_reason(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""

    def _coerce_details(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = None
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _from_container(container: dict[str, Any] | None) -> str:
        if not isinstance(container, dict):
            return ""
        error = container.get("error") if isinstance(container.get("error"), dict) else {}
        details = _coerce_details(error.get("details"))
        reason = _normalize(details.get("failure_reason")).lower()
        if reason:
            return reason
        return ""

    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    task_progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    task_result = task_payload.get("result") if isinstance(task_payload.get("result"), dict) else {}
    result_payload = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    for candidate in (payload, result_payload, task_result, task_progress, task_payload):
        reason = _from_container(candidate)
        if reason:
            return reason
    return ""


def _is_upload_not_applied_summary(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    error_code = _normalize(summary.get("error_code")).lower()
    if not error_code.endswith("_media_upload_failed"):
        return False
    return _normalize(summary.get("upload_failure_reason")).lower() == "upload_not_applied"


def _is_route_auth_required_summary(summary: dict[str, Any] | None) -> bool:
    if not isinstance(summary, dict):
        return False
    error_code = _normalize(summary.get("error_code")).lower()
    verification_reason = _normalize(summary.get("verification_reason")).lower()
    if error_code.endswith("_route_auth_required") or error_code.endswith("_final_publish_route_auth_required"):
        return True
    return verification_reason == "auth_required"


def _is_bound_receipt_verification_success(
    status: str,
    receipt_binding: dict[str, Any] | None,
    publication_audit: dict[str, Any] | None,
) -> bool:
    if _normalize(status).lower() not in {"verified", "published"}:
        return False
    if not isinstance(receipt_binding, dict):
        return False
    if not bool(receipt_binding.get("receipt_like")) or receipt_binding.get("receipt_target_bound") is not True:
        return False
    post_publish_surface = _normalize(receipt_binding.get("post_publish_surface")).lower()
    if not post_publish_surface.endswith("_receipt"):
        return False
    if isinstance(publication_audit, dict) and publication_audit.get("verified") is False:
        return False
    return True


def _is_verified_stop_before_final_publish_success(
    status: str,
    final_publish: dict[str, Any] | None,
    publication_audit: dict[str, Any] | None,
) -> bool:
    normalized_status = _normalize(status).lower()
    if normalized_status not in {"verified", "draft_created"}:
        return False
    if not isinstance(final_publish, dict) or final_publish.get("stop_before_final_publish") is not True:
        return False
    if isinstance(publication_audit, dict) and publication_audit.get("verified") is False:
        return False
    return True


def _should_apply_active_snapshot_strictness(
    status: str,
    *,
    expected_statuses: set[str] | None = None,
) -> bool:
    normalized_status = _normalize(status).lower()
    expected = {
        _normalize(item).lower()
        for item in (expected_statuses or set())
        if _normalize(item)
    }
    if normalized_status == "scheduled_pending" and normalized_status in expected:
        return False
    return _is_release_in_progress_status(normalized_status)


def _serialize_verification_platform_summary(item: dict[str, Any]) -> dict[str, Any]:
    platform = _normalize(item.get("platform"))
    return {
        "platform": platform,
        "attempt_id": _normalize(item.get("attempt_id")),
        "status": _normalize(item.get("status")),
        "signature_match_status": _normalize(item.get("signature_match_status")),
        "expected_signature": _normalize(item.get("expected_signature")),
        "actual_signature": _normalize(item.get("response_signature") or item.get("request_signature") or item.get("run_signature")),
        "signature_match": bool(item.get("signature_match")),
        "field_match": bool(item.get("field_match")),
        "request_fields_snapshot_trusted": bool(item.get("request_fields_snapshot_trusted")),
        "field_mismatches": item.get("field_mismatches") or [],
        "payload_field_mismatches": item.get("request_payload_field_mismatches") or [],
        "payload_fields_match": bool(item.get("request_payload_fields_match")),
        "request_payload_plan_match": bool(item.get("request_payload_plan_match")),
        "request_snapshot_plan_match": bool(item.get("request_snapshot_plan_match")),
        "request_field_verification": item.get("request_field_verification") or [],
        "request_payload_field_mismatch_count": int(item.get("request_payload_field_mismatch_count") or 0),
        "request_field_mismatch_count": int(item.get("request_field_mismatch_count") or 0),
        "request_plan_fill_gaps_count": int(len(item.get("request_plan_fill_gaps") or [])),
        "request_contract_ready": bool(item.get("request_contract_ready")),
        "request_payload_field_mismatch_fields": item.get("request_payload_field_mismatch_fields") or [],
        "request_field_mismatch_fields": item.get("request_field_mismatch_fields") or [],
        "strict_contract_reasons": item.get("strict_contract_reasons") or [],
        "request_fields_plan_fill_audit": item.get("request_fields_plan_fill_audit") or [],
        "request_fields_snapshot_count": item.get("request_fields_snapshot_count"),
        "request_fields_expected_count": item.get("request_fields_expected_count"),
        "request_fields_actual_count": item.get("request_fields_actual_count"),
        "requested_fields": item.get("expected_request_fields") or {},
        "actual_fields": item.get("actual_request_fields") or {},
        "actual_fields_source": _normalize(item.get("actual_request_fields_snapshot_source")),
        "request_plan_fill_gaps": item.get("request_plan_fill_gaps") or [],
        "request_payload_fields": item.get("request_payload_fields") or {},
        "strict_contract_verified": bool(item.get("strict_contract_verified")),
        "contract_verified": (
            bool(item.get("strict_contract_verified"))
            if _is_strict_verification_platform(platform)
            else (_normalize(item.get("status")) in STRICT_VERIFICATION_SUCCESS_STATUSES)
        ),
        "visual_evidence": _coerce_visual_evidence(item.get("visual_evidence")),
        "public_url": _normalize(item.get("public_url")),
        "error_code": _normalize(item.get("error_code")),
        "duplicate_detected": bool(item.get("duplicate_detected")),
        "receipt_binding_id": _normalize(item.get("receipt_binding_id")),
        "receipt_target_unbound": bool(item.get("receipt_target_unbound")),
        "verified_stop_before_final_publish": bool(item.get("verified_stop_before_final_publish")),
        "runs_count": int(item.get("runs_count") or 0),
    }


def _build_real_release_gate_plan_summary(
    *,
    publish_ready: bool,
    created_attempts: list[dict[str, Any]] | list[str] | None = None,
    plan_targets: list[str] | None = None,
    note: str = "",
) -> dict[str, Any]:
    normalized_targets = [
        _normalize(item).lower().replace("_", "-")
        for item in (plan_targets or [])
        if _normalize(item)
    ]
    normalized_targets = list(dict.fromkeys(normalized_targets))
    normalized_attempts = [str(item) for item in (created_attempts or []) if str(item)]
    payload = {
        "publish_ready": bool(publish_ready),
        "created_attempts": normalized_attempts,
        "plan_targets": normalized_targets,
    }
    if _normalize(note):
        payload["note"] = _normalize(note)
    return payload


def _build_partial_created_attempt_failures(
    platforms_for_batch: list[str],
    created_attempts: list[dict[str, Any]] | None,
    skipped_targets: list[dict[str, Any]] | None = None,
) -> list[str]:
    created_platforms = {
        _normalize(item.get("platform")).lower().replace("_", "-")
        for item in (created_attempts or [])
        if isinstance(item, dict) and _normalize(item.get("platform"))
    }
    skipped_by_platform = {
        _normalize(item.get("platform")).lower().replace("_", "-"): item
        for item in (skipped_targets or [])
        if isinstance(item, dict) and _normalize(item.get("platform"))
    }
    missing_created_platforms = [
        platform
        for platform in (platforms_for_batch or [])
        if platform not in created_platforms
    ]
    partial_failures: list[str] = []
    for platform in missing_created_platforms:
        skipped = skipped_by_platform.get(platform) or {}
        reason = _normalize(skipped.get("reason")).lower()
        if reason == "active_attempt_exists":
            active_status = _normalize(skipped.get("status")) or "unknown"
            run_status = _normalize(skipped.get("run_status")) or "unknown"
            attempt_id = _normalize(skipped.get("attempt_id"))
            error_code = _normalize(skipped.get("error_code"))
            detail = f"{platform}: 已存在活跃发布 attempt，当前批次未重新建任务（status={active_status}, run_status={run_status}"
            if attempt_id:
                detail += f", attempt_id={attempt_id}"
            if error_code:
                detail += f", error_code={error_code}"
            detail += "）"
            partial_failures.append(detail)
        elif reason == "terminal_success_exists":
            partial_failures.append(f"{platform}: 已存在成功发布记录，当前批次未重新建任务。")
        else:
            partial_failures.append(f"{platform}: 提交发布任务不完整，当前批次未创建 publication attempt。")
    return partial_failures


def _build_active_attempt_receipt_rebind_targets(
    plan: dict[str, Any],
    skipped_targets: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    skipped_active_platforms = {
        _normalize(item.get("platform")).lower().replace("_", "-")
        for item in (skipped_targets or [])
        if isinstance(item, dict) and _normalize(item.get("reason")).lower() == "active_attempt_exists"
    }
    if not skipped_active_platforms:
        return []
    targets = plan.get("targets") if isinstance(plan.get("targets"), list) else []
    recovery_targets: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        platform = _normalize(target.get("platform")).lower().replace("_", "-")
        if platform not in skipped_active_platforms:
            continue
        raw_overrides = target.get("platform_specific_overrides")
        if not isinstance(raw_overrides, dict):
            raw_overrides = {}
        target_recovery = dict(target)
        merged_overrides = _merge_recovery_target_platform_overrides(
            raw_overrides,
            {
                "recovery_mode": "receipt_rebind",
                "clear_draft_context": False,
                "force_publish_page_refresh": True,
                "verification_only_current_page": True,
                "verify_media_upload": True,
                "wait_for_publish_confirmation": True,
            },
            {},
        )
        merged_overrides["recovery_mode"] = "receipt_rebind"
        merged_overrides["clear_draft_context"] = False
        merged_overrides["force_publish_page_refresh"] = True
        merged_overrides["verification_only_current_page"] = True
        merged_overrides["verify_media_upload"] = True
        merged_overrides["wait_for_publish_confirmation"] = True
        target_recovery["platform_specific_overrides"] = merged_overrides
        recovery_targets.append(target_recovery)
    return recovery_targets


CONTENT_PLAN_FILL_GAP_PENDING_FIELDS = {
    "title",
    "body",
    "hashtags",
    "display_hashtags",
    "structured_tags",
    "scheduled_publish_at",
    "visibility_or_publish_mode",
    "ui_control_semantics",
}


def _is_material_integrity_pending(material_integrity: dict[str, Any]) -> bool:
    if not isinstance(material_integrity, dict) or not material_integrity:
        return False
    verification_state = _normalize(material_integrity.get("verification_state")).lower()
    verification_reason = _normalize(material_integrity.get("verification_reason")).lower()
    failures = {
        _normalize(item).lower()
        for item in (material_integrity.get("failures") or [])
        if _normalize(item)
    }
    route_ready_state = material_integrity.get("route_ready_state") if isinstance(material_integrity.get("route_ready_state"), dict) else {}
    upload_ready_field = material_integrity.get("fields", {}).get("upload_ready") if isinstance(material_integrity.get("fields"), dict) and isinstance(material_integrity.get("fields", {}).get("upload_ready"), dict) else {}
    upload_ready_verified = upload_ready_field.get("verified")
    if verification_state and verification_state != "ready":
        return True
    if verification_reason in {"upload_not_ready", "not_ready"}:
        return True
    if "upload_ready" in failures:
        return True
    if upload_ready_verified is False:
        return True
    if route_ready_state and route_ready_state.get("route_ready") is False:
        return True
    return False


def _has_upload_progress_pending_signal(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    task_payload = payload.get("task") if isinstance(payload.get("task"), dict) else {}
    progress = task_payload.get("progress") if isinstance(task_payload.get("progress"), dict) else {}
    actions = progress.get("actions") if isinstance(progress.get("actions"), list) else []
    for item in reversed(actions):
        if not isinstance(item, dict):
            continue
        kind = _normalize(item.get("kind")).lower()
        if "upload_ready_wait" not in kind:
            continue
        if item.get("ready") is False:
            return True
        last_state = item.get("last") if isinstance(item.get("last"), dict) else {}
        if last_state.get("busy") or last_state.get("ready") is False:
            return True
    visible_lines = progress.get("visible_lines") if isinstance(progress.get("visible_lines"), list) else []
    joined_lines = " ".join(_normalize(line) for line in visible_lines if _normalize(line))
    if not joined_lines:
        return False
    has_percent = re.search(r"\b\d{1,3}%\b", joined_lines) is not None
    has_upload_telemetry = any(token in joined_lines for token in ("已上传", "当前速度", "剩余时间", "上传过程中请不要删除/移动文件"))
    return bool(has_percent and has_upload_telemetry)


def _suppress_content_gap_fields_while_material_pending(
    items: list[dict[str, Any]],
    *,
    material_integrity_pending: bool,
) -> list[dict[str, Any]]:
    if not material_integrity_pending:
        return items
    suppressed: list[dict[str, Any]] = []
    for item in items:
        field_name = _normalize(_normalize_mismatch_field(item))
        if field_name.lower() in CONTENT_PLAN_FILL_GAP_PENDING_FIELDS:
            continue
        suppressed.append(item)
    return suppressed


NON_ECHOED_SNAPSHOT_BACKFILL_FIELDS = {
    "platform",
    "adapter",
    "content_kind",
    "media_urls",
    "media_items_count",
    "cover_path",
    "cover_slots",
    "copy_material",
}


def _merge_snapshot_with_request_payload_backfill(
    snapshot_fields: dict[str, Any],
    request_payload_fields: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(snapshot_fields, dict) or not snapshot_fields:
        return snapshot_fields if isinstance(snapshot_fields, dict) else {}
    if not isinstance(request_payload_fields, dict) or not request_payload_fields:
        return dict(snapshot_fields)
    merged = dict(snapshot_fields)
    for key in NON_ECHOED_SNAPSHOT_BACKFILL_FIELDS:
        normalized_key = _normalize(key)
        if not normalized_key:
            continue
        if _has_non_empty_plan_value(merged.get(normalized_key)):
            continue
        request_value = request_payload_fields.get(normalized_key)
        if not _has_non_empty_plan_value(request_value):
            continue
        merged[normalized_key] = request_value
    return merged


def _normalize_audit_flags(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _normalize(value).lower()
    return text in {"1", "true", "yes", "y", "on"}


def _collect_duplicate_flag(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if _normalize_audit_flags(payload.get("duplicate_detected")):
        return True
    if _normalize_audit_flags(payload.get("is_duplicate")):
        return True
    duplicate_hint = _normalize(payload.get("message"))
    if duplicate_hint and any(
        keyword in duplicate_hint
        for keyword in ("duplicate", "duplication", "重复发布", "重复投稿", "内容重复", "去重", "repost")
    ):
        return True
    if (
        isinstance(payload.get("publication_recovery"), dict)
        and _normalize_audit_flags(payload["publication_recovery"].get("duplicate_detected"))
    ):
        return True
    if isinstance(payload.get("recovery"), dict) and _normalize_audit_flags(payload["recovery"].get("duplicate_detected")):
        return True
    for key in ("reason", "summary", "error_code", "code"):
        item = payload.get(key)
        text = _normalize(item)
        if text and any(
            keyword in text
            for keyword in ("duplicate", "duplication", "重复", "重发", "重复发布", "内容重复", "repost")
        ):
            return True
    return False


def _collect_publication_runs(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    runs = payload.get("runs")
    if not isinstance(runs, list):
        return []
    return [item for item in runs if isinstance(item, dict)]


def _extract_audit_from_run(run_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(run_payload, dict):
        return {}
    if isinstance(run_payload.get("result"), dict):
        result = run_payload.get("result") or {}
        if isinstance(result.get("publication_audit"), dict):
            return result.get("publication_audit")
        if isinstance(result.get("publication_recovery"), dict) and isinstance(result["publication_recovery"].get("publication_audit"), dict):
            return result["publication_recovery"].get("publication_audit")
        if isinstance(result.get("final_publish"), dict) and isinstance(result["final_publish"].get("publication_audit"), dict):
            return result["final_publish"].get("publication_audit")
        metadata = result.get("metadata")
        if isinstance(metadata, dict) and isinstance(metadata.get("publication_audit"), dict):
            return metadata.get("publication_audit")
    return {}


def _normalize_comparable_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = _normalize(value)
        return text if text else None
    if isinstance(value, (list, tuple)):
        return [_normalize_comparable_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _normalize(key): _normalize_comparable_value(item)
            for key, item in value.items()
        }
    return _normalize(value)


def _build_expected_signature_fields(
    *,
    platform: str,
    title: str,
    body: str,
    tags: list[str],
    visibility_mode: str = "",
    scheduled_publish_at: str = "",
    declaration: str = "",
    cover_path: str = "",
    cover_slots: list[dict[str, Any]] | None = None,
    media_path: str = "",
    category: str = "",
    collection: Any | None = None,
) -> dict[str, Any]:
    payload_fields = {
        "platform": _normalize(platform),
        "title": _normalize(title),
        "body": _normalize(body),
        "tags": list(tags),
        "category": _normalize(category) or None,
        "collection": dict(collection) if isinstance(collection, dict) else _coerce_packaging_collection(collection),
        "visibility_or_publish_mode": _normalize(visibility_mode) or None,
        "scheduled_publish_at": _normalize(scheduled_publish_at) or None,
        "declaration": _normalize(declaration) or None,
        "cover_path": _normalize(cover_path) or None,
        "cover_slots": _normalize_comparable_value(cover_slots or []),
        "media_path": _normalize(media_path),
    }
    return {
        "fields": payload_fields,
        "value": hashlib.sha256(
            json.dumps(payload_fields, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _build_expected_request_fields(
    *,
    platform: str,
    platform_title: str,
    body: str,
    tags: list[str],
    visibility_mode: str = "",
    scheduled_publish_at: str = "",
    declaration: str = "",
    cover_path: str = "",
    cover_slots: list[dict[str, Any]] | None = None,
    media_path: str = "",
    adapter: str = "",
    category: str = "",
    collection: Any | None = None,
    platform_specific_overrides: dict[str, Any] | None = None,
    full_copy: str = "",
    copy_material: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_override = _normalize_plan_contract_overrides(platform_specific_overrides)
    topic_selection_plan = (
        dict(normalized_override.get("topic_selection_plan"))
        if isinstance(normalized_override.get("topic_selection_plan"), dict)
        else {}
    )
    requested_native_topics = [
        _normalize(item)
        for item in (topic_selection_plan.get("requested_topics") or normalized_override.get("native_topics") or [])
        if _normalize(item)
    ]
    normalized_collection = (
        dict(collection)
        if isinstance(collection, dict)
        else _coerce_packaging_collection(collection)
    )
    collection_management = (
        dict(normalized_override.get("collection_management"))
        if isinstance(normalized_override.get("collection_management"), dict)
        else {}
    )
    collection_management_target = _normalize(
        collection_management.get("selected_collection_name")
        or collection_management.get("target_collection_name")
        or collection_management.get("collection_name")
    )
    requires_local_media = not bool(normalized_override.get("x_share_link")) and bool(_normalize(media_path))
    expected_copy_material = dict(copy_material) if isinstance(copy_material, dict) else {}
    expected_copy_material.update({
        "body": _normalize(body),
        "tags": [_normalize(item) for item in tags if _normalize(item)],
        "titles": [platform_title],
        "full_copy": _normalize(full_copy),
        "cover_path": _normalize(cover_path) or None,
        "cover_slots": _normalize_comparable_value(cover_slots or []),
        "declaration": _normalize(declaration) or None,
        "primary_title": platform_title,
    })
    if "source" not in expected_copy_material:
        expected_copy_material["source"] = "platform_packaging"
    return {
        "platform": _normalize(platform),
        "adapter": _normalize_publication_adapter(adapter),
        "title": _normalize(platform_title),
        "body": _normalize(body),
        "declaration": _normalize(declaration) or None,
        "content_kind": "video",
        "hashtags": [_normalize(item) for item in tags if _normalize(item)],
        "display_hashtags": [f"#{_normalize(item)}" for item in tags if _normalize(item)],
        "structured_tags": [_normalize(item) for item in tags if _normalize(item)],
        "native_topics": requested_native_topics,
        "category": _normalize(category) or None,
        "collection": normalized_collection,
        "cover_path": _normalize(cover_path) or None,
        "cover_slots": _normalize_comparable_value(cover_slots or []),
        "copy_material": expected_copy_material,
        "visibility_or_publish_mode": _normalize(visibility_mode) or None,
        "scheduled_publish_at": _normalize(scheduled_publish_at) or None,
        "ui_control_semantics": {
            "schedule_publish": bool(_normalize(scheduled_publish_at)),
            "collection_select": bool(normalized_collection or collection_management_target),
        },
        "platform_specific_overrides": normalized_override,
        "media_urls": [_normalize(media_path)] if requires_local_media else [],
        "media_items_count": 1 if requires_local_media else 0,
    }


def _normalize_plan_contract_override_value(value: Any) -> Any:
    if isinstance(value, dict):
        normalized_dict = {
            _normalize(key): _normalize_plan_contract_override_value(item)
            for key, item in value.items()
            if _normalize(key)
        }
        return {key: item for key, item in normalized_dict.items() if item not in (None, "", [], {})}
    if isinstance(value, (list, tuple, set)):
        normalized_list = [_normalize_plan_contract_override_value(item) for item in value]
        return [item for item in normalized_list if item not in (None, "", [], {})]
    if isinstance(value, str):
        return _normalize(value) or None
    if isinstance(value, (bool, int, float)):
        return value
    return None


def _normalize_plan_contract_overrides(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    excluded_keys = {
        "field_groups",
        "option_groups",
        "operation_steps",
        "platform_warnings",
        "live_publish_preflight",
        "clear_draft_context",
        "force_publish_page_refresh",
        "ignore_publish_ready_gate",
        "force_republish",
        "force_republish_now",
        "allow_duplicate_publication",
        "verify_media_upload",
        "wait_for_publish_confirmation",
        "capture_response_timeout_ms",
    }
    payload = {
        key: value
        for key, value in payload.items()
        if _normalize(key) and _normalize(key) not in excluded_keys
    }
    normalized = _normalize_plan_contract_override_value(payload)
    return normalized if isinstance(normalized, dict) else {}


def _coerce_plan_contract_request_fields(
    payload: dict[str, Any],
    media_path: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    platform = _normalize(payload.get("platform")).lower().replace("_", "-")
    normalized = dict(payload)
    normalized["platform"] = platform
    normalized["platform_specific_overrides"] = _normalize_plan_contract_overrides(payload.get("platform_specific_overrides"))
    normalized_media_path = _normalize(media_path)
    if normalized_media_path and not normalized["platform_specific_overrides"].get("x_share_link"):
        normalized["media_urls"] = [normalized_media_path]
        normalized["media_items"] = [{"local_path": normalized_media_path}]
    return _extract_request_payload_fields(normalized)


def _build_plan_contract_checks(
    plan: dict[str, Any],
    batch_manifest: dict[str, dict[str, Any]],
    *,
    media_path: str,
    requested_platforms: list[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    failures: list[str] = []
    checks: list[dict[str, Any]] = []
    platform_targets: dict[str, dict[str, Any]] = {}
    for item in plan.get("targets", []):
        if not isinstance(item, dict):
            continue
        platform = _normalize(item.get("platform")).lower().replace("_", "-")
        if platform:
            platform_targets[platform] = item
    for platform in requested_platforms:
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        if not normalized_platform:
            continue
        target = platform_targets.get(normalized_platform, {})
        expected_entry = batch_manifest.get(normalized_platform) or {}
        expected_fields = expected_entry.get("request_fields") if isinstance(expected_entry.get("request_fields"), dict) else {}
        is_strict_platform = normalized_platform in STABLE_PUBLICATION_PLATFORM_SET or normalized_platform in STRICT_VERIFICATION_PLATFORM_SET
        if is_strict_platform and not expected_fields:
            failures.append(
                f"{normalized_platform} 计划预检：稳定平台未生成 request_fields 合同基线，无法执行严格字段核验。"
            )
            checks.append(
                {
                    "platform": normalized_platform,
                    "status": "missing_contract",
                    "request_field_mismatches": [
                        {
                            "field": "request_fields",
                            "expected": STRICT_STABLE_REQUEST_CONTRACT_FIELD_KEYS,
                            "actual": target,
                        }
                    ],
                    "expected_request_fields": {},
                    "actual_request_fields": _coerce_plan_contract_request_fields(target, media_path),
                    "request_contract_ready": False,
                }
            )
            continue
        if not target:
            failures.append(f"{normalized_platform} 计划预检：发布计划中缺少目标条目。")
            checks.append(
                {
                    "platform": normalized_platform,
                    "status": "missing_target",
                    "request_field_mismatches": [],
                    "expected_request_fields": expected_fields if isinstance(expected_fields, dict) else {},
                    "actual_request_fields": {},
                }
            )
            continue
        if not isinstance(expected_fields, dict):
            failures.append(f"{normalized_platform} 计划预检：缺少请求字段基线。")
            continue
        actual_fields = _coerce_plan_contract_request_fields(target, media_path)
        expected_fields = _enrich_plan_contract_expected_fields(expected_fields, actual_fields)
        request_field_mismatches = _build_field_differences(expected_fields, actual_fields, ignored_keys={"platform"})
        if request_field_mismatches:
            mismatch_fields = ", ".join(_normalize(_normalize_mismatch_field(item)) for item in request_field_mismatches[:4])
            failures.append(
                f"{normalized_platform} 计划预检：请求字段与发布计划不一致（{mismatch_fields or 'unknown'}）。"
            )
        checks.append(
            {
                "platform": normalized_platform,
                "status": "ok" if not request_field_mismatches else "mismatch",
                "request_field_mismatches": request_field_mismatches,
                "expected_request_fields": expected_fields,
                "actual_request_fields": actual_fields,
                "request_contract_ready": bool(expected_fields),
            }
        )
    return failures, checks


def _enrich_plan_contract_expected_fields(
    expected_fields: dict[str, Any],
    actual_fields: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(expected_fields, dict) or not isinstance(actual_fields, dict):
        return expected_fields if isinstance(expected_fields, dict) else {}
    enriched = copy.deepcopy(expected_fields)

    def _is_empty_contract_value(value: Any) -> bool:
        return value in (None, "", [], {})

    for key in ("category", "collection"):
        if _is_empty_contract_value(enriched.get(key)) and not _is_empty_contract_value(actual_fields.get(key)):
            enriched[key] = copy.deepcopy(actual_fields.get(key))

    expected_overrides = enriched.get("platform_specific_overrides")
    actual_overrides = actual_fields.get("platform_specific_overrides")
    if isinstance(actual_overrides, dict) and actual_overrides:
        merged_overrides = dict(expected_overrides) if isinstance(expected_overrides, dict) else {}
        for key, value in actual_overrides.items():
            if _normalize(key) and _is_empty_contract_value(merged_overrides.get(key)):
                merged_overrides[key] = copy.deepcopy(value)
        enriched["platform_specific_overrides"] = merged_overrides

    expected_semantics = enriched.get("ui_control_semantics")
    actual_semantics = actual_fields.get("ui_control_semantics")
    if isinstance(actual_semantics, dict) and actual_semantics:
        merged_semantics = dict(expected_semantics) if isinstance(expected_semantics, dict) else {}
        for key, value in actual_semantics.items():
            if _normalize(key) and _is_empty_contract_value(merged_semantics.get(key)) and value not in (None, "", [], {}):
                merged_semantics[key] = copy.deepcopy(value)
        enriched["ui_control_semantics"] = merged_semantics

    expected_native_topics = [
        _normalize(item)
        for item in (enriched.get("native_topics") or [])
        if _normalize(item)
    ]
    actual_native_topics = [
        _normalize(item)
        for item in (actual_fields.get("native_topics") or [])
        if _normalize(item)
    ]
    if not expected_native_topics and actual_native_topics:
        topic_selection_plan = (
            dict((enriched.get("platform_specific_overrides") or {}).get("topic_selection_plan"))
            if isinstance((enriched.get("platform_specific_overrides") or {}).get("topic_selection_plan"), dict)
            else {}
        )
        requested_topics = [
            _normalize(item)
            for item in (topic_selection_plan.get("requested_topics") or [])
            if _normalize(item)
        ]
        enriched["native_topics"] = requested_topics or actual_native_topics

    recomputed_collection_select = bool(enriched.get("collection"))
    enriched_overrides = enriched.get("platform_specific_overrides")
    if isinstance(enriched_overrides, dict):
        collection_management = (
            dict(enriched_overrides.get("collection_management"))
            if isinstance(enriched_overrides.get("collection_management"), dict)
            else {}
        )
        recomputed_collection_select = recomputed_collection_select or bool(
            _normalize(
                collection_management.get("selected_collection_name")
                or collection_management.get("target_collection_name")
                or collection_management.get("collection_name")
            )
        )
    merged_semantics = dict(enriched.get("ui_control_semantics") or {}) if isinstance(enriched.get("ui_control_semantics"), dict) else {}
    merged_semantics["collection_select"] = bool(
        merged_semantics.get("collection_select") or recomputed_collection_select
    )
    enriched["ui_control_semantics"] = merged_semantics

    return enriched


def _extract_request_payload_fields(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    tags = _coerce_request_payload_tags(payload)
    hashtags = _coerce_text_list(payload.get("hashtags")) or tags
    display_hashtags = _coerce_text_list(payload.get("display_hashtags"))
    if not display_hashtags and hashtags:
        display_hashtags = [f"#{item}" for item in hashtags if _normalize(item)]
    structured_tags = _coerce_text_list(payload.get("structured_tags")) or hashtags
    media_items = payload.get("media_items") or []
    media_paths: list[str] = []
    if isinstance(media_items, list):
        for item in media_items:
            if not isinstance(item, dict):
                continue
            local_path = _normalize(item.get("local_path"))
            if local_path:
                media_paths.append(local_path)
    media_urls = payload.get("media_urls") if isinstance(payload.get("media_urls"), list) else []
    normalized_media_urls = [_normalize(item) for item in media_urls if _normalize(item)]
    platform_specific_overrides = payload.get("platform_specific_overrides")
    if not isinstance(platform_specific_overrides, dict):
        platform_specific_overrides = {}
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    ui_control_semantics = payload.get("ui_control_semantics")
    if not isinstance(ui_control_semantics, dict):
        ui_control_semantics = {}
    copy_material = payload.get("copy_material")
    if isinstance(copy_material, dict):
        copy_material = dict(copy_material)
        copy_material_cover_path = publication_primary_cover_path(copy_material)
        copy_material_cover_slots = derive_publication_cover_slots(copy_material)
        if not copy_material_cover_path:
            copy_material_cover_path = publication_primary_cover_path(payload)
        if not copy_material_cover_slots:
            copy_material_cover_slots = derive_publication_cover_slots(payload)
        if copy_material_cover_path:
            copy_material["cover_path"] = copy_material_cover_path
        if copy_material_cover_slots:
            copy_material["cover_slots"] = _normalize_comparable_value(copy_material_cover_slots)
    else:
        copy_material = {}
    scheduled_publish_at = _normalize(payload.get("scheduled_publish_at")) or None
    collection = payload.get("collection") or None
    return {
        "platform": _normalize(payload.get("platform") or metadata.get("platform")),
        "adapter": _normalize_publication_adapter(payload.get("adapter") or metadata.get("adapter")),
        "title": _normalize(payload.get("title")),
        "body": _normalize(payload.get("body")),
        "declaration": _normalize(payload.get("declaration")) or None,
        "content_kind": _normalize(payload.get("content_kind")) or "video",
        "hashtags": hashtags,
        "display_hashtags": display_hashtags,
        "structured_tags": structured_tags,
        "native_topics": [_normalize(item) for item in (payload.get("native_topics") or []) if _normalize(item)],
        "category": _normalize(payload.get("category")) or None,
        "collection": collection,
        "cover_path": _normalize(payload.get("cover_path")) or None,
        "cover_slots": _normalize_comparable_value(derive_publication_cover_slots(payload)),
        "copy_material": copy_material,
        "visibility_or_publish_mode": _normalize(payload.get("visibility_or_publish_mode")) or None,
        "scheduled_publish_at": scheduled_publish_at,
        "ui_control_semantics": {
            "schedule_publish": bool(scheduled_publish_at or ui_control_semantics.get("schedule_publish")),
            "collection_select": bool(collection or ui_control_semantics.get("collection_select")),
        },
        "platform_specific_overrides": _normalize_plan_contract_overrides(platform_specific_overrides),
        "media_urls": normalized_media_urls,
        "media_items_count": len(media_paths),
    }


def _build_field_differences(
    expected: dict[str, Any],
    actual: dict[str, Any],
    ignored_keys: set[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_ignored = {_normalize(item).lower() for item in (ignored_keys or set()) if _normalize(item)}
    expected_payload = _normalize_comparable_value(expected)
    actual_payload = _normalize_comparable_value(actual)
    keys = (set(expected_payload.keys()) | set(actual_payload.keys())) - set(normalized_ignored)
    differences: list[dict[str, Any]] = []
    for key in sorted(keys):
        expected_value = expected_payload.get(key)
        actual_value = actual_payload.get(key)
        if key == "cover_slots":
            expected_missing = expected_value in (None, [], ())
            actual_missing = actual_value in (None, [], ())
            if expected_missing and actual_missing:
                continue
        if key == "scheduled_publish_at" and _scheduled_publish_values_match(expected_value, actual_value):
            continue
        if _normalize_comparable_value(expected_value) != _normalize_comparable_value(actual_value):
            differences.append(
                {
                    "field": key,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )
    return differences


def _scheduled_publish_values_match(expected: Any, actual: Any) -> bool:
    expected_text = _normalize(expected)
    actual_text = _normalize(actual)
    if not expected_text or not actual_text:
        return expected_text == actual_text
    expected_dt = _parse_plan_contract_datetime(expected_text)
    actual_dt = _parse_plan_contract_datetime(actual_text)
    if expected_dt is None or actual_dt is None:
        return expected_text == actual_text
    if expected_dt.tzinfo is None:
        expected_dt = expected_dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    if actual_dt.tzinfo is None:
        actual_dt = actual_dt.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return expected_dt.astimezone(timezone.utc) == actual_dt.astimezone(timezone.utc)


def _parse_plan_contract_datetime(value: Any) -> datetime | None:
    text = _normalize(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _has_non_empty_plan_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return bool(_normalize(value))
    if isinstance(value, (list, tuple, set)):
        return any(_has_non_empty_plan_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_non_empty_plan_value(item) for item in value.values())
    return bool(value)


def _build_request_plan_fill_gaps(
    expected: dict[str, Any],
    actual: dict[str, Any],
    *,
    critical_fields: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(expected, dict) or not isinstance(actual, dict):
        return []
    normalized_critical_fields = {
        _normalize(item).lower() for item in (critical_fields or set()) if _normalize(item)
    }
    expected_payload = _normalize_comparable_value(expected)
    actual_payload = _normalize_comparable_value(actual)
    if not isinstance(expected_payload, dict) or not isinstance(actual_payload, dict):
        return []
    gaps: list[dict[str, Any]] = []
    for key in normalized_critical_fields:
        expected_value = expected_payload.get(key)
        if not _has_non_empty_plan_value(expected_value):
            continue
        actual_value = actual_payload.get(key)
        if _has_non_empty_plan_value(actual_value):
            continue
        gaps.append(
            {
                "field": key,
                "expected": expected_value,
                "actual": actual_value,
            }
        )
    return gaps


def _suppress_request_plan_fill_gaps_with_non_required_audit_fields(
    request_plan_fill_gaps: list[dict[str, Any]] | None,
    publication_audit: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(request_plan_fill_gaps, list) or not request_plan_fill_gaps:
        return []
    checklist = (
        publication_audit.get("checklist")
        if isinstance(publication_audit, dict) and isinstance(publication_audit.get("checklist"), dict)
        else {}
    )
    non_required_fields = {
        _normalize(field).lower()
        for field, entry in checklist.items()
        if _normalize(field)
        and isinstance(entry, dict)
        and entry.get("required") is False
    }
    if not non_required_fields:
        return list(request_plan_fill_gaps)
    return [
        item
        for item in request_plan_fill_gaps
        if _normalize(item.get("field")).lower() not in non_required_fields
    ]


def _suppress_request_field_mismatches_with_non_required_audit_fields(
    request_field_mismatches: list[dict[str, Any]] | None,
    publication_audit: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(request_field_mismatches, list) or not request_field_mismatches:
        return []
    checklist = (
        publication_audit.get("checklist")
        if isinstance(publication_audit, dict) and isinstance(publication_audit.get("checklist"), dict)
        else {}
    )
    non_required_fields = {
        _normalize(field).lower()
        for field, entry in checklist.items()
        if _normalize(field)
        and isinstance(entry, dict)
        and entry.get("required") is False
    }
    if not non_required_fields:
        return list(request_field_mismatches)
    return [
        item
        for item in request_field_mismatches
        if _normalize(item.get("field")).lower() not in non_required_fields
    ]


def _should_require_public_url_for_strict_success(
    *,
    platform: str,
    status: str,
    bound_receipt_verification_success: bool,
    is_x_link_share: bool,
) -> bool:
    normalized_platform = _normalize(platform).lower().replace("_", "-")
    normalized_status = _normalize(status).lower()
    if normalized_status != "published":
        return False
    if is_x_link_share:
        return False
    if bound_receipt_verification_success:
        return False
    return normalized_platform in STRICT_VERIFICATION_PLATFORM_SET or normalized_platform in STABLE_PUBLICATION_PLATFORM_SET


def _is_response_snapshot_plan_empty(
    *,
    expected_request_fields: dict[str, Any],
    response_payload_snapshot: dict[str, Any],
    critical_fields: set[str] | None = None,
) -> bool:
    if (
        not isinstance(expected_request_fields, dict)
        or not isinstance(response_payload_snapshot, dict)
    ):
        return False
    normalized_expected = _normalize_comparable_value(expected_request_fields)
    normalized_response = _normalize_comparable_value(response_payload_snapshot)
    if not isinstance(normalized_expected, dict) or not isinstance(normalized_response, dict):
        return False
    normalized_critical = {
        _normalize(item).lower() for item in (critical_fields or set()) if _normalize(item)
    }
    if not normalized_critical:
        return False
    expected_has_non_empty = False
    response_has_non_empty = False
    for key in normalized_critical:
        expected_value = normalized_expected.get(key)
        if not _has_non_empty_plan_value(expected_value):
            continue
        expected_has_non_empty = True
        actual_value = normalized_response.get(key)
        if _has_non_empty_plan_value(actual_value):
            response_has_non_empty = True
            break
    return expected_has_non_empty and not response_has_non_empty


def _build_expected_platform_manifest(
    platforms: list[str],
    *,
    title: str,
    description: str,
    media_path: str,
    content_suffix: str = "",
    visibility_mode: str = "",
    x_share_link: str = "",
    x_link_share_mode: bool = False,
    platform_packaging: dict[str, dict[str, Any]] | None = None,
    platform_adapters: dict[str, str] | None = None,
    effective_platform_options: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    manifest: dict[str, dict[str, Any]] = {}
    normalized_packaging = platform_packaging or {}
    normalized_platform_options = _normalize_platform_options_payload(effective_platform_options)
    normalized_suffix = _normalize(content_suffix)
    source_title = _normalize(title) or _normalize(media_path) or "RoughCut发布素材"
    title_suffix = f"{source_title}{' [' + normalized_suffix + ']' if normalized_suffix else ''}"
    normalized_description = _normalize(description) or f"RoughCut 正式发布素材：{source_title}"
    normalized_x_share_link = _normalize(x_share_link)
    normalized_visibility = _normalize(visibility_mode)
    normalized_platform_adapters = {
        _normalize(key).lower().replace("_", "-"): _normalize_publication_adapter(value)
        for key, value in (platform_adapters or {}).items()
        if _normalize(key) and _normalize_publication_adapter(value)
    }
    for platform in platforms:
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        entry = normalized_packaging.get(normalized_platform) if isinstance(normalized_packaging.get(normalized_platform), dict) else {}
        normalized_entry = _coerce_platform_packaging_entry(
            normalized_platform,
            dict(entry),
            fallback_title=title_suffix,
            fallback_description=normalized_description,
        )
        platform_title = (normalized_entry.get("titles") or [])[0] if isinstance(normalized_entry.get("titles"), list) and (normalized_entry.get("titles") or []) else (
            f"{normalized_platform} · {title_suffix}" if normalized_platform != "youtube" else f"YouTube · {title_suffix}"
        )
        tags = normalized_entry.get("tags") if isinstance(normalized_entry.get("tags"), list) and normalized_entry.get("tags") else ["RoughCut", "发布", normalized_platform]
        declaration = _normalize(normalized_entry.get("declaration")) or platform_default_declaration(normalized_platform)
        body = _merge_packaging_body_with_x_link_share(
            normalized_platform,
            normalized_entry.get("description") or normalized_description,
            x_share_link=normalized_x_share_link,
            x_link_share_mode=x_link_share_mode,
        )
        category = _normalize(normalized_entry.get("category"))
        collection = normalized_entry.get("collection")
        cover_path = _normalize(normalized_entry.get("cover_path"))
        cover_slots = derive_publication_cover_slots(normalized_entry)
        scheduled_publish_at = _normalize(normalized_entry.get("scheduled_publish_at"))
        visibility_value = _normalize(normalized_entry.get("visibility_or_publish_mode")) or normalized_visibility
        option = normalized_platform_options.get(normalized_platform) if isinstance(normalized_platform_options.get(normalized_platform), dict) else {}
        option_visibility = _normalize(option.get("visibility_or_publish_mode") or option.get("visibility"))
        option_category = _sanitize_publication_target_category(
            normalized_platform,
            _normalize(option.get("category")),
        )
        option_collection = option.get("collection")
        option_declaration = _normalize(option.get("declaration"))
        option_schedule = _normalize(option.get("scheduled_publish_at"))
        if option_visibility:
            visibility_value = option_visibility
        if option_category:
            category = option_category
        if option_collection is not None:
            collection = option_collection
        if option_declaration:
            declaration = option_declaration
        if option_schedule:
            scheduled_publish_at = option_schedule
        platform_adapter = normalized_platform_adapters.get(
            normalized_platform,
            ("x_link_share" if platform == "x" and x_link_share_mode else "browser_agent"),
        )
        platform_overrides = (
            dict(normalized_entry.get("platform_specific_overrides"))
            if isinstance(normalized_entry.get("platform_specific_overrides"), dict)
            else {}
        )
        option_overrides = option.get("platform_specific_overrides")
        if isinstance(option_overrides, dict) and option_overrides:
            platform_overrides.update(option_overrides)
        if platform == "x" and x_link_share_mode and normalized_x_share_link:
            platform_overrides["x_share_link"] = normalized_x_share_link
        signature_payload = _build_expected_signature_fields(
            platform=platform,
            title=platform_title,
            body=body,
            tags=tags,
            visibility_mode=visibility_value,
            scheduled_publish_at=scheduled_publish_at,
            declaration=declaration,
            cover_path=cover_path,
            cover_slots=cover_slots,
            media_path=_normalize(media_path),
            category=category,
            collection=collection,
        )
        request_fields = _build_expected_request_fields(
            platform=platform,
            platform_title=platform_title,
            body=body,
            tags=tags,
            visibility_mode=visibility_value,
            scheduled_publish_at=scheduled_publish_at,
            declaration=declaration,
            cover_path=cover_path,
            cover_slots=cover_slots,
            media_path=_normalize(media_path),
            adapter=platform_adapter,
            category=category,
            collection=collection,
            platform_specific_overrides=platform_overrides,
            full_copy=normalized_entry.get("full_copy") or "",
            copy_material=normalized_entry.get("copy_material") if isinstance(normalized_entry.get("copy_material"), dict) else None,
        )
        manifest[normalized_platform] = {
            "platform": normalized_platform,
            "title": platform_title,
            "body": body,
            "tags": tags,
            "declaration": declaration or None,
            "visibility_or_publish_mode": visibility_value or None,
            "content_signature": signature_payload["value"],
            "signature_fields": signature_payload["fields"],
            "adapter": platform_adapter,
            "request_fields": request_fields,
        }
        if normalized_entry.get("publish_ready") is False:
            manifest[normalized_platform]["publish_ready"] = False
            if normalized_entry.get("blocking_reasons"):
                manifest[normalized_platform]["blocking_reasons"] = list(_coerce_text_list(normalized_entry.get("blocking_reasons")))
            else:
                manifest[normalized_platform]["blocking_reasons"] = [
                    "platform_packaging 标注为未就绪（publish_ready = false）。"
                ]
    return manifest


def _build_platform_recovery_recommendations(platform: str, summary: dict[str, Any], *, is_stable: bool) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    status = _normalize(summary.get("status")).lower()
    signature_match_status = _normalize(summary.get("signature_match_status"))
    signature_field_match = bool(summary.get("signature_fields_match"))
    signature_fields_available = bool(summary.get("signature_fields_available"))
    expected_signature_fields = summary.get("expected_signature_fields")
    strict_contract_reasons = _normalize_prepublish_reasons(summary.get("strict_contract_reasons"))
    strict_contract_status_in_progress = "status_in_progress" in strict_contract_reasons
    submitted_empty_snapshot = "submitted_response_payload_empty_snapshot" in strict_contract_reasons
    publish_receipt_pending = _is_publish_receipt_pending_summary(summary)
    post_repair_preserve_context = bool(summary.get("post_repair_preserve_context"))
    receipt_target_unbound = bool(summary.get("receipt_target_unbound"))
    pre_publish_upload_pending = bool(summary.get("pre_publish_upload_pending"))
    upload_not_applied = bool(summary.get("upload_not_applied"))
    route_auth_required = bool(summary.get("route_auth_required"))
    suppress_draft_recovery_noise = receipt_target_unbound or route_auth_required or upload_not_applied
    if route_auth_required:
        recommendations.append(
            {
                "platform": platform,
                "issue": "route_auth_required",
                "severity": "high",
                "auto_remediable": False,
                "operations": [],
                "actions": [
                    "当前页面停在登录或鉴权路由，现有发布现场不能继续自动推进。",
                    "先恢复账号会话、扫码或处理二次验证，再回到同一 profile 继续核验；不要清理草稿或补发。",
                ],
            }
        )
    submitted_snapshot_unverified = (
        status == "submitted"
        and (
            bool(summary.get("request_fields_snapshot_missing"))
            or summary.get("request_fields_snapshot_trusted") is False
            or summary.get("actual_request_fields_snapshot_source") == "request_payload"
        )
    )
    if receipt_target_unbound:
        recommendations.append(
            {
                "platform": platform,
                "issue": "receipt_target_unbound",
                "severity": "high",
                "auto_remediable": False,
                "operations": ["force_publish_page_refresh", "wait_for_publish_confirmation"],
                "actions": [
                    "发布后回执尚未唯一绑定到本次作品，当前终态不能采信为成功。",
                    "保留当前管理页或成功页现场，刷新并重新读取目标作品回执；不要清理草稿或补发。",
                ],
            }
        )
    if pre_publish_upload_pending:
        recommendations.append(
            {
                "platform": platform,
                "issue": "pre_publish_upload_pending",
                "severity": "high",
                "auto_remediable": False,
                "operations": ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "预发布字段已通过，当前仅剩素材上传未就绪。",
                    "保留当前发布页现场，继续核验上传进度并等待上传完成后重新验证；不要清理草稿或重建发布页。",
                ],
            }
        )
    if upload_not_applied:
        recommendations.append(
            {
                "platform": platform,
                "issue": "upload_not_applied",
                "severity": "high",
                "auto_remediable": False,
                "operations": ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "文件输入已触发，但页面没有真正进入媒体已挂载的可继续编辑状态。",
                    "保留当前发布页现场，刷新并重新核验上传入口是否真正接住媒体；不要清理草稿或重建发布页。",
                ],
            }
        )
    if post_repair_preserve_context:
        remaining = [
            _normalize(item)
            for item in ((summary.get("publication_audit") or {}).get("required_unverified") or [])
            if _normalize(item)
        ]
        operations = ["force_publish_page_refresh"]
        if "upload_ready" in remaining:
            operations.extend(["verify_media_upload", "wait_for_publish_confirmation"])
            actions = [
                "预发布字段已完成自动修复并重新校验，当前只剩素材上传未就绪。",
                "保留当前发布页现场，继续等待上传完成并刷新校验；不要清理草稿上下文。",
            ]
        else:
            actions = [
                "预发布字段已完成自动修复并重新校验，当前只剩发布回执/目标绑定类结构性阻塞。",
                "保留当前发布页现场，刷新并重新读取目标回执；不要清理草稿上下文。",
            ]
        recommendations.append(
            {
                "platform": platform,
                "issue": "post_repair_structural_blocker",
                "severity": "high",
                "auto_remediable": False,
                "operations": operations,
                "actions": actions,
            }
        )
    if summary.get("request_contract_ready") is False:
        recommendations.append(
            {
                "platform": platform,
                "issue": "missing_contract",
                "severity": "high",
                "auto_remediable": False,
                "operations": [],
                "actions": [
                    "发布计划未生成稳定平台 request_fields 合同基线，无法进行字段一致性校验。",
                    "修复 preflight 或 plan contract 生成链路，避免使用测试/脏草稿内容。",
                ],
            }
        )
    if submitted_snapshot_unverified and not submitted_empty_snapshot:
        untrusted_issue = (
            "submitted_response_payload_unverified"
            if bool(summary.get("request_fields_snapshot_missing"))
            else "response_payload_unverified"
        )
        untrusted_reason = (
            "提交态下 response_payload 未返回可采信字段快照，先强制刷新发布页核验页面与发布状态。"
            if bool(summary.get("request_fields_snapshot_missing"))
            else "提交态字段快照来源非 response_payload，请先核验发布页实际状态并刷新。"
        )
        recommendations.append(
            {
                "platform": platform,
                "issue": untrusted_issue,
                "severity": "high",
                "auto_remediable": False,
                "operations": ["force_publish_page_refresh"],
                "actions": [
                    untrusted_reason,
                    "核验发布目标平台是否真实已发布：优先查询发布详情页与最终链接。",
                    "仅在确认平台未发布后，视情况执行 clear_draft_context 后重试。",
                ],
            }
        )
    if publish_receipt_pending:
        recommendations.append(
            {
                "platform": platform,
                "issue": "publish_receipt_pending",
                "severity": "high",
                "auto_remediable": False,
                "operations": ["force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "已提交且签名匹配，但当前仍停留在发布确认/回执等待阶段。",
                    "优先刷新发布页、回读平台管理页或最终链接，确认是否已真正发布或进入审核。",
                    "仅在确认未发布且平台仍停留在旧草稿/脏态时，才执行 clear_draft_context。",
                ],
            }
        )
    if (
        status == "submitted"
        and "content_plan_fill_gaps_pending" in strict_contract_reasons
        and not _should_suppress_draft_recovery_recommendation(
            "content_plan_fill_gaps_pending",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "content_plan_fill_gaps_pending",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "检测到提交态字段回填仍待补全，疑似发布页面写入中断或草稿脏态。",
                    "先清理草稿上下文并刷新发布页，重跑素材上传与发布复核。",
                    f"建议设置发布确认等待时长为 {int(_coerce_recovery_timeout_ms(90000, default=90000, min_ms=15000, max_ms=180000) / 1000)} 秒。",
                ],
            }
        )
    if (
        status == "submitted"
        and "submitted_content_plan_fill_gaps_pending" in strict_contract_reasons
        and not _should_suppress_draft_recovery_recommendation(
            "submitted_content_plan_fill_gaps_pending",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "submitted_content_plan_fill_gaps_pending",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "检测到提交态字段回填仍待补全（含 submitted_ 前缀标记）。",
                    "先清理草稿上下文并刷新发布页，按同一签名重跑发布页状态采集与发布复核。",
                    f"建议设置发布确认等待时长为 {int(_coerce_recovery_timeout_ms(90000, default=90000, min_ms=15000, max_ms=180000) / 1000)} 秒。",
                ],
            }
        )
    if (
        status == "submitted"
        and "submitted_response_payload_empty_snapshot" in strict_contract_reasons
        and not _should_suppress_draft_recovery_recommendation(
            "submitted_response_payload_empty_snapshot",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "submitted_response_payload_empty_snapshot",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "提交态 response_payload 返回关键字段快照为空值，疑似页面回填失败或状态缓存未刷新。",
                    "先清理草稿上下文并刷新发布页，按同一签名重跑并核验最终链接。",
                    f"建议设置发布确认等待时长为 {int(_coerce_recovery_timeout_ms(120000, default=120000, min_ms=15000, max_ms=180000) / 1000)} 秒。",
                ],
            }
        )
    if (
        strict_contract_status_in_progress
        and "active_status_stale" in strict_contract_reasons
        and status not in {"draft_created", "failed", "needs_human"}
        and not _should_suppress_draft_recovery_recommendation(
            "active_status_stale",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "active_status_stale",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh", "verify_media_upload", "wait_for_publish_confirmation"],
                "actions": [
                    "发布进行态已超时未退出活跃阶段，说明页面写入或提交链路可能卡死。",
                    "先清理草稿上下文并强制刷新发布页，按同一签名重跑。",
                    f"建议设置发布确认等待时长为 {int(_coerce_recovery_timeout_ms(90000, default=90000, min_ms=15000, max_ms=180000) / 1000)} 秒。",
                ],
            }
        )
    if status in {"submitted", "processing", "publishing", "ready_to_publish", "waiting_publish", "uploading", "uploading_media"} and (
        bool(summary.get("request_fields_snapshot_missing"))
        or summary.get("request_fields_snapshot_trusted") is False
        or bool(summary.get("content_plan_fill_gaps_pending"))
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "status_in_progress",
                "severity": "high",
                "auto_remediable": False if "status_in_progress" not in strict_contract_reasons else True,
                "operations": ["force_publish_page_refresh"],
                "actions": [
                    "当前处于发布进行态，先刷新发布页并核验平台端是否真实生成链接/公开状态。",
                    "在确认未发布前，不清理草稿上下文；仅在确认未发布且链路卡死时再触发 clear_draft_context。",
                    "核验通过后再按发布闭环结果决定是否成功收口或继续重试。",
                ],
            }
        )
    if is_stable and status == "draft_created":
        recommendations.append(
            {
                "platform": platform,
                "issue": "publication_draft_created",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "稳定平台当前终态为草稿态，说明页面存在未公开草稿残留。",
                    "清空草稿上下文并强制刷新发布页，按同一素材签名重建发布流。",
                ],
            }
        )
    if (
        isinstance(expected_signature_fields, dict)
        and not signature_field_match
        and not suppress_draft_recovery_noise
        and not _should_suppress_draft_recovery_recommendation(
            "signature_fields_mismatch",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        actual_signature_fields = (
            summary.get("response_signature_fields")
            if isinstance(summary.get("response_signature_fields"), dict)
            and summary.get("response_signature_fields")
            else summary.get("run_signature_fields")
            if isinstance(summary.get("run_signature_fields"), dict)
            and summary.get("run_signature_fields")
            else summary.get("request_signature_fields")
            if isinstance(summary.get("request_signature_fields"), dict)
            and summary.get("request_signature_fields")
            else summary.get("actual_request_fields_snapshot")
            if isinstance(summary.get("actual_request_fields_snapshot"), dict)
            and summary.get("actual_request_fields_snapshot")
            else {}
        )
        if isinstance(actual_signature_fields, dict) and actual_signature_fields:
            mismatch_fields = sorted(
                {
                    key
                    for key in set(expected_signature_fields.keys()) | set(actual_signature_fields.keys())
                    if expected_signature_fields.get(key) != actual_signature_fields.get(key)
                }
            )
            issue = "signature_fields_mismatch"
            issue_desc = f"差异字段：{', '.join(mismatch_fields) if mismatch_fields else 'unknown'}"
            if not signature_fields_available:
                issue = "signature_fields_missing"
                issue_desc = "签名字段回执缺失，无法确认草稿一致性。"
            recommendations.append(
                {
                    "platform": platform,
                    "issue": issue,
                    "severity": "high",
                    "auto_remediable": True,
                    "operations": ["clear_draft_context", "force_publish_page_refresh"],
                    "actions": [
                        "对比 request/response 的 publication_*_signature.fields 与计划字段，确认是否有草稿残留。",
                        issue_desc,
                        "清空草稿上下文并强制刷新发布页重试。",
                    ],
                }
            )
        else:
            recommendations.append(
                {
                    "platform": platform,
                    "issue": "signature_fields_missing",
                    "severity": "high",
                    "auto_remediable": True,
                    "operations": ["clear_draft_context", "force_publish_page_refresh"],
                    "actions": [
                        "签名字段快照未回填，疑似草稿脏态导致回执不完整。",
                        "清空草稿上下文并强制刷新发布页重试。",
                    ],
                }
            )
    if (
        summary.get("request_fields_snapshot_missing")
        and not suppress_draft_recovery_noise
        and not submitted_snapshot_unverified
        and not _should_suppress_draft_recovery_recommendation(
            "publication_request_fields_snapshot_missing",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "publication_request_fields_snapshot_missing",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "缺失字段快照，无法确认实际发布页面是否使用了计划字段。",
                    f"字段快照来源：{_normalize(summary.get('actual_request_fields_snapshot_source')) or 'unknown'}",
                    "清理草稿并重试，确保发布页从签名计划重建输入。",
                ],
            }
        )
    if (
        summary.get("actual_request_fields_snapshot_source") == "request_payload"
        and not suppress_draft_recovery_noise
        and not submitted_snapshot_unverified
        and not _should_suppress_draft_recovery_recommendation(
            "publication_request_field_snapshot_untrusted",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "publication_request_field_snapshot_untrusted",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "字段快照来源来自请求体，不能直接证明发布页实际写入字段。",
                    "优先等待 response/run 层返回字段快照，否则阻断成功采信。",
                    "清理草稿上下文并重试，确认发布页按计划重建输入。",
                ],
            }
        )
    request_plan_fill_gaps = summary.get("request_plan_fill_gaps") if isinstance(summary.get("request_plan_fill_gaps"), list) else []
    if (
        is_stable
        and request_plan_fill_gaps
        and not suppress_draft_recovery_noise
        and not _should_suppress_draft_recovery_recommendation(
            "content_plan_fill_gaps",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommendations.append(
            {
                "platform": platform,
                "issue": "content_plan_fill_gaps",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "关键计划字段未在发布快照中回填或内容为空，疑似草稿污染。",
                    f"缺失关键字段：{', '.join(_normalize_mismatch_field(item) or 'unknown' for item in request_plan_fill_gaps)}",
                    "清空草稿上下文并强制刷新发布页重试。",
                ],
            }
        )
    field_deltas = summary.get("field_mismatches") if isinstance(summary.get("field_mismatches"), list) else []
    payload_deltas = (
        summary.get("request_payload_field_mismatches")
        if isinstance(summary.get("request_payload_field_mismatches"), list)
        else []
    )
    error_code = _normalize(summary.get("error_code"))
    if payload_deltas and not suppress_draft_recovery_noise:
        recommend_payload_fields = [_normalize_mismatch_field(item) for item in payload_deltas if _normalize(_normalize_mismatch_field(item))]
        recommendations.append(
            {
                "platform": platform,
                "issue": "publication_request_payload_fields_mismatch",
                "severity": "high",
                "auto_remediable": _is_auto_recoverable_error_code(
                    "publication_request_payload_fields_mismatch",
                    AUTO_RECOVERABLE_ERROR_CODES,
                ),
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "核对计划与实际提交请求字段；若存在差异需阻断本次发布成功采信。",
                    f"重点核对字段：{', '.join(recommend_payload_fields)}",
                    "清理当前 tab 草稿并清空发布上下文后重试。",
                ],
            }
        )
    if (
        field_deltas
        and not suppress_draft_recovery_noise
        and not _should_suppress_draft_recovery_recommendation(
            "content_fields_mismatch",
            publish_receipt_pending=publish_receipt_pending,
        )
    ):
        recommend_fields = [_normalize_mismatch_field(item) for item in field_deltas if _normalize(_normalize_mismatch_field(item))]
        recommendations.append(
            {
                "platform": platform,
                "issue": "content_fields_mismatch",
                "severity": "high",
                "auto_remediable": True,
                "operations": ["clear_draft_context", "force_publish_page_refresh"],
                "actions": [
                    "核对发布计划与实际请求载荷字段；差异字段一般来源于草稿污染或预设模板覆盖",
                    f"重点核对字段：{', '.join(recommend_fields)}",
                    "清理当前 tab 草稿并清空发布上下文后重试（需重放同一个素材签名）",
                ],
            }
        )
    if summary.get("duplicate_detected"):
        recommendations.append(
            {
                "platform": platform,
                "issue": "duplicate_detected",
                "severity": "high",
                "auto_remediable": False,
                "operations": [],
                "actions": [
                    "当前素材疑似重复发布，先停止自动重试，避免继续刷垃圾内容。",
                    "增加语义指纹去重约束，避免重复触发同内容发布",
                    "将同一素材在同一平台重复发布标记为人工确认",
                ],
            }
        )
    if summary.get("attempt_adapter") and summary.get("expected_adapter") and summary.get("attempt_adapter") != summary.get("expected_adapter"):
        recommendations.append(
            {
                "platform": platform,
                "issue": "adapter_mismatch",
                "severity": "high",
                "auto_remediable": False,
                "actions": [
                    "检查 creator profile 的 adapter 与发布计划中的 adapter 是否一致",
                    "必要时重新提交计划，固定平台适配器",
                ],
            }
        )
    if status == "published" and is_stable and not summary.get("public_url"):
        recommendations.append(
            {
                "platform": platform,
                "issue": "public_url_missing",
                "severity": "high",
                "auto_remediable": False,
                "actions": [
                    "重新读取 final_publish 回执，确认发布页是否真正发布",
                    "必要时清空草稿重试并强制刷新发布页",
                ],
            }
        )
    if status == "scheduled_pending" and summary.get("scheduled_publish_at") and not summary.get("scheduled_at"):
        recommendations.append(
            {
                "platform": platform,
                "issue": "schedule_receipt_missing",
                "severity": "medium",
                "auto_remediable": False,
                "actions": [
                    "在发布回执页确认预约时间是否生效",
                    "必要时重试并确认 timepicker 提交字段",
                ],
            }
        )
    if status in {"needs_human", "failed"} and error_code:
        recommendations.append(
            {
                "platform": platform,
                "issue": error_code,
                "severity": "high",
                "auto_remediable": _is_auto_recoverable_error_code(error_code, AUTO_RECOVERABLE_ERROR_CODES),
                "actions": [
                    "读取 publication_audit 与 run 日志，确认是否存在缺失声明/表单字段",
                    "先执行草稿清理再自动重试（脚本已支持）",
                    "若持续失败，转人工补填创建页并回填真实链接/预约信息",
                ],
            }
        )
    if status in {"published", "scheduled_pending"} and signature_match_status == "missing":
        recommendations.append(
            {
                "platform": platform,
                "issue": "signature_missing",
                "severity": "high",
                "auto_remediable": True,
                "actions": [
                    "补齐内容签名回执链路（request/result/publication_audit）",
                    "强制清草稿后以相同内容签名重发",
                ],
            }
        )
    elif signature_match_status == "unmatched":
        recommendations.append(
            {
                "platform": platform,
                "issue": "signature_mismatch",
                "severity": "high",
                "auto_remediable": True,
                "actions": [
                    "将该平台发布页现有草稿删除，避免旧字段污染新稿",
                    "按发布计划签名字段重建发布输入",
                ],
            }
        )
    if not recommendations:
        return []
    for item in recommendations:
        item.setdefault("attempt_id", _normalize(summary.get("attempt_id")))
    return recommendations


def _build_platform_packaging(
    platforms: list[str],
    *,
    content_suffix: str = "",
    title: str = "",
    description: str = "",
    media_path: str = "",
    platform_packaging: dict[str, dict[str, Any]] | None = None,
    allow_prepare_without_publish_ready: bool = False,
) -> dict[str, Any]:
    platforms_payload: dict[str, dict[str, Any]] = {}
    normalized_packaging = platform_packaging or {}
    suffix = _normalize(content_suffix)
    source_title = _normalize(title) or Path(media_path).stem or "RoughCut发布素材"
    title_suffix = f"{source_title}{' [' + suffix + ']' if suffix else ''}"
    fallback_description = _normalize(description) or f"RoughCut 正式发布素材：{source_title}"
    for platform in platforms:
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        entry = normalized_packaging.get(normalized_platform) if isinstance(normalized_packaging.get(normalized_platform), dict) else {}
        normalized_entry = _coerce_platform_packaging_entry(
            normalized_platform,
            dict(entry),
            fallback_title=title_suffix,
            fallback_description=fallback_description,
        )
        platform_title = (normalized_entry.get("titles") or [])[0] if isinstance(normalized_entry.get("titles"), list) and normalized_entry.get("titles") else (
            f"{normalized_platform} · {title_suffix}" if normalized_platform != "youtube" else f"YouTube · {title_suffix}"
        )
        platform_description = _normalize(normalized_entry.get("description") or fallback_description)
        tags = normalized_entry.get("tags") if isinstance(normalized_entry.get("tags"), list) and normalized_entry.get("tags") else ["RoughCut", "发布", normalized_platform]
        platform_payload: dict[str, Any] = {
            "platform": normalized_platform,
            "titles": [platform_title],
            "description": platform_description,
            "tags": tags,
            "cover_path": normalized_entry.get("cover_path"),
            "cover_slots": derive_publication_cover_slots(normalized_entry),
            "full_copy": normalized_entry.get("full_copy"),
            "copy_material": dict(normalized_entry.get("copy_material"))
            if isinstance(normalized_entry.get("copy_material"), dict)
            else {},
            "platform_specific_overrides": dict(normalized_entry.get("platform_specific_overrides"))
            if isinstance(normalized_entry.get("platform_specific_overrides"), dict)
            else {},
            "claim_refs": normalized_entry.get("claim_refs") if isinstance(normalized_entry.get("claim_refs"), list) else [],
            "copy_refs": normalized_entry.get("copy_refs"),
            "publish_ready": True,
        }
        category = _normalize(normalized_entry.get("category"))
        collection = normalized_entry.get("collection")
        declaration = _normalize(normalized_entry.get("declaration"))
        visibility_or_publish_mode = _normalize(normalized_entry.get("visibility_or_publish_mode"))
        scheduled_publish_at = _normalize(normalized_entry.get("scheduled_publish_at"))
        if category:
            platform_payload["category"] = category
        if collection is not None:
            platform_payload["collection"] = collection
        if declaration:
            platform_payload["declaration"] = declaration
        if visibility_or_publish_mode:
            platform_payload["visibility_or_publish_mode"] = visibility_or_publish_mode
        if scheduled_publish_at:
            platform_payload["scheduled_publish_at"] = scheduled_publish_at
        platforms_payload[normalized_platform] = platform_payload
        if normalized_entry.get("publish_ready") is False:
            blocking_reasons = list(_coerce_text_list(normalized_entry.get("blocking_reasons")))
            if allow_prepare_without_publish_ready:
                platforms_payload[normalized_platform]["reported_publish_ready"] = False
                if blocking_reasons:
                    platforms_payload[normalized_platform]["reported_blocking_reasons"] = blocking_reasons
                platform_payload.setdefault("platform_specific_overrides", {})
                platform_payload["platform_specific_overrides"]["allow_prepare_without_publish_ready"] = True
            else:
                platforms_payload[normalized_platform]["publish_ready"] = False
                if blocking_reasons:
                    platforms_payload[normalized_platform]["blocking_reasons"] = blocking_reasons
    packaging = {
        "publish_ready": True,
        "platforms": platforms_payload,
        "claim_ledger": [
            {
                "id": "c1",
                "claim_type": "identity",
                "text": "发布链路已通过复用条件检查。",
                "evidence": "publication real release gate fixture",
            }
        ],
    }
    packaging["publish_ready"] = publication_packaging_payload_publish_ready(packaging)
    if packaging["publish_ready"]:
        packaging["blocking_reasons"] = []
    return packaging


def _is_fresh_draft_prepare_mode(expected_statuses: set[str], visibility_mode: str = "") -> bool:
    normalized_statuses = {_normalize(item).lower() for item in (expected_statuses or set()) if _normalize(item)}
    normalized_visibility_mode = _normalize(visibility_mode).lower()
    if normalized_visibility_mode != "draft":
        return False
    if not normalized_statuses:
        return False
    return normalized_statuses.issubset({"draft_created", "processing"}) and "draft_created" in normalized_statuses


def _browser_agent_ready_target_platforms(
    *,
    effective_platforms: list[str],
    fresh_draft_prepare_mode: bool,
) -> list[str]:
    if fresh_draft_prepare_mode:
        # Fresh-draft preparation validates bridge/profile authority first and
        # lets the real publish task perform platform-local route recovery.
        return []
    return list(effective_platforms or [])


def _validate_authoritative_publication_browser_runtime(agent_ready: dict[str, Any]) -> list[str]:
    if not isinstance(agent_ready, dict):
        return ["browser-agent 运行态缺失，无法确认发布浏览器绑定。"]
    health = agent_ready.get("health") if isinstance(agent_ready.get("health"), dict) else {}
    binding = health.get("attached_profile_binding") if isinstance(health.get("attached_profile_binding"), dict) else {}
    transport = health.get("browser_transport") if isinstance(health.get("browser_transport"), dict) else {}
    failures: list[str] = []
    if _normalize(binding.get("browser")).lower() != "chrome":
        failures.append("当前发布运行态未绑定到 Google Chrome，拒绝继续发布测试。")
    if _normalize(transport.get("transport")).lower() != "chrome_extension_bridge":
        failures.append("当前发布运行态未走 chrome_extension_bridge，拒绝继续发布测试。")
    if not _normalize(binding.get("profile_id")):
        failures.append("当前发布运行态缺少 attached_profile_binding.profile_id，拒绝继续发布测试。")
    return failures


def _build_fresh_draft_prepare_live_check(agent_ready: dict[str, Any]) -> dict[str, Any]:
    health = agent_ready.get("health") if isinstance(agent_ready, dict) and isinstance(agent_ready.get("health"), dict) else {}
    transport = health.get("browser_transport") if isinstance(health.get("browser_transport"), dict) else {}
    normalized_cdp_status = _normalize(health.get("cdp_status")).lower()
    cdp_connected = (
        normalized_cdp_status in {"ok", "ready", "degraded"}
        and _normalize(transport.get("transport")).lower() == "chrome_extension_bridge"
    )
    return {
        "cdp": {
            "connected": bool(cdp_connected),
            "source": "browser_agent_healthz",
            "state": normalized_cdp_status,
        },
        "platform_checks": {},
    }


def _build_platform_options(
    platforms: list[str],
    *,
    visibility_mode: str = "",
    x_share_link: str = "",
    platform_packaging: dict[str, dict[str, Any]] | None = None,
    seed_platform_options: dict[str, dict[str, Any]] | None = None,
    stale_draft_platforms: set[str] | None = None,
    force_refresh_platforms: set[str] | None = None,
    platform_recovery_hints: dict[str, dict[str, Any]] | None = None,
    force_clear_stable_platforms: bool = False,
    allow_republish: bool = False,
    fresh_draft_prepare_mode: bool = False,
) -> dict[str, Any]:
    normalized_visibility = _normalize(visibility_mode).lower()
    normalized_x_share_link = _normalize(x_share_link)
    normalized_packaging = platform_packaging or {}
    normalized_seed_options = _normalize_platform_options_payload(seed_platform_options)
    stale_platform_set = {platform.strip().lower().replace("_", "-") for platform in (stale_draft_platforms or [])}
    refresh_platform_set = {platform.strip().lower().replace("_", "-") for platform in (force_refresh_platforms or [])}
    recovery_hint_map = {
        _normalize(platform).lower().replace("_", "-"): dict(hint or {})
        for platform, hint in (platform_recovery_hints or {}).items()
        if _normalize(platform)
    }
    options: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        platform_entry = normalized_packaging.get(normalized_platform) if isinstance(normalized_packaging.get(normalized_platform), dict) else {}
        platform_overrides: dict[str, Any] = {}
        requires_clear = normalized_platform in stale_platform_set
        requires_refresh = normalized_platform in refresh_platform_set
        if force_clear_stable_platforms and (
            normalized_platform in STABLE_PUBLICATION_PLATFORM_SET
            or normalized_platform in STRICT_VERIFICATION_PLATFORM_SET
        ):
            requires_clear = True
            requires_refresh = True
        if requires_clear or requires_refresh:
            platform_overrides.update(
                {
                    "clear_draft_context": bool(requires_clear),
                    "force_publish_page_refresh": True,
                }
            )
        package_preflight = platform_entry.get("live_publish_preflight")
        if not isinstance(package_preflight, dict):
            package_overrides = platform_entry.get("platform_specific_overrides")
            if isinstance(package_overrides, dict):
                package_preflight = package_overrides.get("live_publish_preflight")
        option: dict[str, Any] = dict(normalized_seed_options.get(normalized_platform) or {})
        if "live_publish_preflight" not in option:
            option["live_publish_preflight"] = (
                dict(package_preflight)
                if isinstance(package_preflight, dict)
                else {
                    "status": "passed",
                    "missing_required_surfaces": [],
                    "summary": "��ʵ����ǰ���Ž�ͨ����������·���ԣ���",
                }
            )
        platform_visibility = _normalize(platform_entry.get("visibility_override"))
        if not platform_visibility:
            platform_visibility = _normalize(platform_entry.get("visibility_or_publish_mode"))
        platform_category = _sanitize_publication_target_category(normalized_platform, _normalize(platform_entry.get("category")))
        platform_collection = platform_entry.get("collection")
        platform_declaration = _normalize(platform_entry.get("declaration"))
        platform_schedule = _normalize(platform_entry.get("scheduled_publish_at"))
        if platform_visibility:
            option["visibility_or_publish_mode"] = platform_visibility
        if normalized_visibility:
            option["visibility_or_publish_mode"] = normalized_visibility
        option_category = _sanitize_publication_target_category(
            normalized_platform,
            _normalize(option.get("category")),
        )
        if platform_category and not option_category:
            option["category"] = platform_category
        elif option_category:
            option["category"] = option_category
        if (
            platform_collection is not None
            and not option.get("collection")
            and not _normalize(option.get("collection_name"))
        ):
            option["collection"] = platform_collection
        if platform_declaration and not _normalize(option.get("declaration")):
            option["declaration"] = platform_declaration
        if platform_schedule and not _normalize(option.get("scheduled_publish_at")):
            option["scheduled_publish_at"] = platform_schedule
        package_overrides = platform_entry.get("platform_specific_overrides")
        if isinstance(option.get("platform_specific_overrides"), dict):
            platform_overrides.update(option.get("platform_specific_overrides") or {})
        if isinstance(package_overrides, dict) and package_overrides:
            for key, value in package_overrides.items():
                if key not in platform_overrides:
                    platform_overrides[key] = value
        if normalized_platform == "x" and normalized_x_share_link:
            platform_overrides["x_share_link"] = normalized_x_share_link
            platform_overrides["x_share_link"] = normalized_x_share_link
        if allow_republish:
            platform_overrides["force_republish"] = True
            platform_overrides["allow_duplicate_publication"] = True
        if fresh_draft_prepare_mode:
            platform_overrides.update(
                {
                    "fresh_start_platform_tab": True,
                    "clear_draft_context": False,
                    "force_publish_page_refresh": False,
                    "verification_only_current_page": False,
                    "repair_only_current_page": False,
                    "prepublish_only_current_page": False,
                    "prepare_only_current_page": False,
                    "stop_before_final_publish": False,
                    "verify_media_upload": False,
                    "wait_for_publish_confirmation": False,
                }
            )
        if fresh_draft_prepare_mode:
            for key in (
                "verification_only_current_page",
                "repair_only_current_page",
                "prepublish_only_current_page",
                "prepare_only_current_page",
                "stop_before_final_publish",
            ):
                platform_overrides[key] = False
        if platform_overrides:
            option["platform_specific_overrides"] = platform_overrides
        hint_overrides = None if fresh_draft_prepare_mode else recovery_hint_map.get(normalized_platform)
        if isinstance(hint_overrides, dict) and hint_overrides:
            if "platform_specific_overrides" not in option:
                option["platform_specific_overrides"] = {}
            option["platform_specific_overrides"].update(
                {
                    _normalize(key): value
                    for key, value in hint_overrides.items()
                    if _normalize(key) and isinstance(value, (bool, int, float, str))
                }
            )
        options[normalized_platform] = option
    return options


async def _resolve_scheme_platform_options(
    *,
    job: Job,
    render_output: Any,
    platform_packaging: dict[str, dict[str, Any]],
    creator_profile: dict[str, Any],
    requested_platforms: list[str],
    folder_path: str,
    force_probe: bool = False,
) -> dict[str, dict[str, Any]]:
    base_plan = build_publication_plan(
        job=job,
        render_output=render_output,
        platform_packaging=platform_packaging,
        creator_profile=creator_profile,
        requested_platforms=requested_platforms,
        platform_options=None,
        existing_attempts=[],
    )
    if not list(base_plan.get("targets") or []):
        return {}
    scheme = await generate_publication_scheme(
        plan=base_plan,
        creator_profile=creator_profile,
        folder_path=str(folder_path or ""),
        browser="chrome",
        force_probe=bool(force_probe),
    )
    return _normalize_platform_options_payload(scheme.get("platform_options"))


async def _collect_prepublish_draft_candidates(
    *,
    session: Any,
    media_path: str,
    platforms: list[str],
    expected_platform_manifest: dict[str, dict[str, Any]] | None = None,
    stale_active_ttl_seconds: int = DEFAULT_ACTIVE_ATTEMPT_STALE_TTL_SECONDS,
    include_draft_created: bool = True,
) -> dict[str, dict[str, Any]]:
    normalized_media = _normalize(media_path)
    normalized_media_path = _canonical_media_path(normalized_media)
    media_filters = list({
        value
        for value in (normalized_media, normalized_media_path)
        if value
    })
    normalized_platforms = [ _normalize(platform).replace("_", "-").lower() for platform in (platforms or []) if _normalize(platform)]
    if not normalized_platforms or not media_filters:
        return {}
    candidate_statuses = set(PUBLICATION_ACTIVE_STATUSES) | set(PUBLICATION_TERMINAL_STATUSES) | set(RELEASE_GATE_RECOVERY_MONITOR_STATUSES)
    if include_draft_created:
        candidate_statuses.add("draft_created")
    manifest_by_platform = expected_platform_manifest or {}
    statement = (
        select(
            PublicationAttempt.platform,
            PublicationAttempt.status,
            PublicationAttempt.updated_at,
            PublicationAttempt.request_payload,
            PublicationAttempt.response_payload,
            PublicationAttempt.error_code,
            PublicationAttempt.adapter,
            PublicationAttempt.external_url,
            PublicationAttempt.scheduled_at,
            PublicationAttempt.run_status,
            PublicationAttempt.provider_status,
        )
        .join(Job, PublicationAttempt.job_id == Job.id)
        .where(PublicationAttempt.platform.in_(normalized_platforms))
        .where(PublicationAttempt.status.in_(candidate_statuses))
        .where(Job.source_path.in_(media_filters))
        .order_by(PublicationAttempt.platform, PublicationAttempt.updated_at.desc())
    )
    rows = await session.execute(statement)
    now_ts = _now_dt()
    latest: dict[str, tuple[Any, ...]] = {}
    for row in rows.all():
        if not row or not row[0]:
            continue
        platform = _normalize(row[0]).replace("_", "-").lower()
        if platform not in latest:
            latest[platform] = row
    platform_candidates: dict[str, dict[str, Any]] = {}
    for platform, row in latest.items():
        status = _normalize(row[1]).lower()
        is_in_progress_status = _is_release_in_progress_status(status)
        attempt_time = row[2] if len(row) > 2 else None
        request_payload = row[3] if len(row) > 3 and isinstance(row[3], dict) else {}
        response_payload = row[4] if len(row) > 4 and isinstance(row[4], dict) else {}
        error_code = _normalize(row[5]) if len(row) > 5 else ""
        adapter = _normalize(row[6]) if len(row) > 6 else ""
        external_url = _normalize(row[7]) if len(row) > 7 else ""
        scheduled_at = _normalize(row[8]) if len(row) > 8 else ""
        run_status = _normalize(row[9]) if len(row) > 9 else ""
        provider_status = _normalize(row[10]) if len(row) > 10 else ""
        run_payloads = _collect_publication_runs({"response_payload": response_payload})
        latest_run = run_payloads[0] if run_payloads else {}
        run_result = latest_run.get("result") if isinstance(latest_run, dict) else {}
        response_material_integrity = _extract_material_integrity(response_payload)
        if not response_material_integrity:
            response_material_integrity = _extract_material_integrity(run_result)
        pre_publish_repair = _extract_pre_publish_repair(response_payload)
        if not pre_publish_repair:
            pre_publish_repair = _extract_pre_publish_repair(run_result)
        expected_entry = manifest_by_platform.get(platform) if isinstance(manifest_by_platform.get(platform), dict) else {}
        expected_request_fields = expected_entry.get("request_fields") if isinstance(expected_entry.get("request_fields"), dict) else {}
        expected_signature = _normalize(expected_entry.get("content_signature"))
        reasons: list[str] = []
        signature_field_values = [
            value
            for value in (
                _extract_publication_signature(response_payload),
                _extract_publication_signature(request_payload),
            )
            if value
        ]
        actual_signature = signature_field_values[0] if signature_field_values else ""
        snapshot_from_response = _extract_publication_field_snapshot(response_payload)
        snapshot_from_request = _extract_publication_field_snapshot(request_payload)
        snapshot_from_attempt = snapshot_from_response or snapshot_from_request
        if isinstance(snapshot_from_attempt, dict) and snapshot_from_attempt:
            snapshot_from_attempt = _merge_snapshot_with_request_payload_backfill(
                snapshot_from_attempt,
                expected_request_fields if isinstance(expected_request_fields, dict) else {},
            )
        material_integrity_pending = _is_material_integrity_pending(_extract_material_integrity(response_payload))
        if not material_integrity_pending:
            material_integrity_pending = _has_upload_progress_pending_signal(response_payload)
        snapshot_source = (
            "response_payload"
            if bool(snapshot_from_response)
            else "request_payload"
            if bool(snapshot_from_request)
            else ""
        )
        is_stable = _is_strict_verification_platform(platform)
        if status == "draft_created":
            reasons.append("draft_created")
        if is_in_progress_status:
            if not _record_is_recent(attempt_time, now_ts, ttl_seconds=stale_active_ttl_seconds):
                reasons.append("active_status_stale")
            elif (
                status in {"processing", "publishing", "waiting_publish", "ready_to_publish", "submitted"}
                and not bool(snapshot_from_response)
            ):
                reasons.append("submitted_snapshot_missing" if status == "submitted" else "processing_snapshot_missing")
        if status in PUBLICATION_SUCCESS_STATUSES and is_stable and not _looks_like_public_url(external_url):
            reasons.append("published_no_public_url")
        if is_stable and expected_request_fields:
            gaps = _build_request_plan_fill_gaps(
                expected_request_fields,
                snapshot_from_attempt if isinstance(snapshot_from_attempt, dict) else {},
                critical_fields=SUBMITTED_DRAFT_CRITICAL_FIELDS,
            )
            is_submitted_response_payload_snapshot_empty = (
                status == "submitted"
                and bool(snapshot_from_response)
                and _is_response_snapshot_plan_empty(
                    expected_request_fields=expected_request_fields,
                    response_payload_snapshot=snapshot_from_response,
                    critical_fields=SUBMITTED_DRAFT_CRITICAL_FIELDS,
                )
            )
            if is_submitted_response_payload_snapshot_empty:
                reasons.append("submitted_response_payload_empty_snapshot")
            elif gaps:
                gaps = _suppress_content_gap_fields_while_material_pending(
                    gaps,
                    material_integrity_pending=material_integrity_pending,
                )
            if gaps:
                reasons.append("plan_fill_gaps")
                if status == "submitted":
                    reasons.append("submitted_content_plan_fill_gaps_pending")
                reasons.append("content_plan_fill_gaps_pending")
        mismatches = _build_field_differences(expected_request_fields, snapshot_from_attempt if isinstance(snapshot_from_attempt, dict) else {})
        mismatches = _suppress_content_gap_fields_while_material_pending(
            mismatches,
            material_integrity_pending=material_integrity_pending,
        )
        if mismatches:
            reasons.append("plan_fields_mismatch")
        if expected_signature and actual_signature and actual_signature != expected_signature:
            reasons.append("signature_mismatch")
        if expected_signature and not actual_signature:
            reasons.append("signature_missing")
        if is_in_progress_status:
            reasons.append("status_in_progress")
        if not status:
            reasons.append("missing_status")
        if status in {"failed", "needs_human"}:
            if error_code:
                reasons.append(f"terminal_status:{error_code or status}")
            else:
                reasons.append(f"terminal_status:{status}")
        if not reasons:
            if adapter:
                if _normalize(expected_entry.get("adapter")) and adapter != _normalize(expected_entry.get("adapter")):
                    reasons.append("adapter_mismatch")
            if status in PUBLICATION_SUCCESS_STATUSES and run_status:
                reasons.append(f"success_status_with_run_{run_status}")
            if status in PUBLICATION_SUCCESS_STATUSES and provider_status:
                reasons.append(f"success_status_with_provider_{provider_status}")
            if status in PUBLICATION_SUCCESS_STATUSES and scheduled_at and not _normalize(request_payload.get("scheduled_publish_at")):
                reasons.append("scheduled_at_without_plan")
        if reasons:
            normalized_reasons = _normalize_prepublish_reasons(reasons)
            publish_receipt_pending = _is_publish_receipt_pending_summary(
                {
                    "status": status,
                    "reasons": normalized_reasons,
                    "expected_signature": expected_signature,
                    "actual_signature": actual_signature,
                    "signature_match": bool(expected_signature and actual_signature and expected_signature == actual_signature),
                    "request_payload_plan_match": True,
                    "duplicate_detected": False,
                }
            )
            clear_draft_context = _should_clear_draft_from_prepublish_reasons(
                status=status,
                reasons=normalized_reasons,
                publish_receipt_pending=publish_receipt_pending,
                error_code=error_code,
                snapshot_source=snapshot_source,
                receipt_target_unbound=bool(_is_receipt_target_unbound(_extract_receipt_binding(response_payload) or _extract_receipt_binding(run_result))),
                upload_not_applied=bool(
                    _is_upload_not_applied_summary(
                        {
                            "error_code": error_code,
                            "upload_failure_reason": _extract_upload_failure_reason(response_payload)
                            or _extract_upload_failure_reason(run_result),
                        }
                    )
                ),
                route_auth_required=bool(
                    _is_route_auth_required_summary(
                        {
                            "error_code": error_code,
                            "verification_reason": _normalize(
                                (response_material_integrity or {}).get("verification_reason")
                                if isinstance(response_material_integrity, dict)
                                else ""
                            ),
                        }
                    )
                ),
                post_repair_preserve_context=bool(
                    _is_post_repair_structural_blocker_context(
                        pre_publish_repair=pre_publish_repair,
                        repair_evidence=(
                            snapshot_from_attempt.get("repair_evidence")
                            if isinstance(snapshot_from_attempt, dict) and isinstance(snapshot_from_attempt.get("repair_evidence"), dict)
                            else {}
                        ),
                        required_unverified=list(response_material_integrity.get("failures") or []) if isinstance(response_material_integrity, dict) else [],
                        required_reupload=list(response_material_integrity.get("failures") or []) if isinstance(response_material_integrity, dict) else [],
                    )
                ),
            )
            verify_candidate_reasons = {
                "active_status_stale",
                "processing_snapshot_missing",
                "submitted_snapshot_missing",
                "submitted_content_plan_fill_gaps_pending",
                "submitted_response_payload_empty_snapshot",
                "content_plan_fill_gaps_pending",
                "content_plan_fill_gaps",
                "response_payload_unverified",
                "submitted_response_payload_unverified",
            }
            verification_enabled = _is_release_in_progress_status(status) or any(
                reason in verify_candidate_reasons for reason in normalized_reasons
            )
            verify_media_upload = bool(verification_enabled)
            wait_for_publish_confirmation = bool(verification_enabled)
            capture_response_timeout_ms = _coerce_recovery_timeout_ms(
                90000
                if any(
                    reason in {
                        "content_plan_fill_gaps_pending",
                        "content_plan_fill_gaps",
                        "response_payload_unverified",
                        "submitted_response_payload_unverified",
                        "submitted_content_plan_fill_gaps_pending",
                        "submitted_response_payload_empty_snapshot",
                    }
                    for reason in normalized_reasons
                )
                else 70000
                if verification_enabled
                else None,
                default=None,
                min_ms=30000,
                max_ms=180000,
            )
            attempt_time_text = ""
            if isinstance(attempt_time, datetime):
                attempt_time_text = attempt_time.isoformat()
            else:
                attempt_time_text = _normalize(attempt_time)
            prepublish_signal = {
                "platform": platform,
                "status": status,
                "adapter": adapter,
                "error_code": error_code,
                "updated_at": attempt_time_text,
                "snapshot_source": snapshot_source,
                "snapshot_count": len(snapshot_from_attempt) if isinstance(snapshot_from_attempt, dict) else 0,
                "reasons": normalized_reasons,
                "publish_receipt_pending": publish_receipt_pending,
                "verify_media_upload": verify_media_upload,
                "wait_for_publish_confirmation": wait_for_publish_confirmation,
                "capture_response_timeout_ms": capture_response_timeout_ms,
            }
            prepublish_signature, prepublish_signature_text = _build_prepublish_recovery_signature(platform, prepublish_signal)
            prepublish_signal["signature"] = prepublish_signature
            prepublish_signal["signature_text"] = prepublish_signature_text
            prepublish_signal["clear_draft_context"] = clear_draft_context
            prepublish_signal["force_publish_page_refresh"] = any(
                reason in {
                    "active_status_stale",
                    "processing_snapshot_missing",
                    "submitted_snapshot_missing",
                    "submitted_content_plan_fill_gaps_pending",
                    "submitted_response_payload_empty_snapshot",
                    "content_plan_fill_gaps_pending",
                    "content_plan_fill_gaps",
                    "response_payload_unverified",
                    "submitted_response_payload_unverified",
                }
                for reason in normalized_reasons
            )
            platform_candidates[platform] = prepublish_signal
    return platform_candidates


async def _platforms_with_recent_failure_context(
    *,
    session: Any,
    media_path: str,
    platforms: list[str],
    stale_active_ttl_seconds: int = DEFAULT_ACTIVE_ATTEMPT_STALE_TTL_SECONDS,
    include_draft_created: bool = True,
) -> tuple[set[str], dict[str, list[str]]]:
    normalized_media = _normalize(media_path)
    normalized_media_path = _canonical_media_path(normalized_media)
    media_filters = list({
        value
        for value in (normalized_media, normalized_media_path)
        if value
    })
    normalized_platforms = [ _normalize(platform).replace("_", "-").lower() for platform in (platforms or []) if _normalize(platform)]
    if not normalized_platforms or not media_filters:
        return set(), {}
    candidate_statuses = set(PUBLICATION_ACTIVE_STATUSES) | set(PUBLICATION_TERMINAL_STATUSES - PUBLICATION_SUCCESS_STATUSES)
    candidate_statuses.update(RELEASE_GATE_RECOVERY_MONITOR_STATUSES)
    if include_draft_created:
        candidate_statuses.add("draft_created")
    statement = (
        select(
            PublicationAttempt.platform,
            PublicationAttempt.status,
            PublicationAttempt.updated_at,
        )
        .join(Job, PublicationAttempt.job_id == Job.id)
        .where(PublicationAttempt.platform.in_(normalized_platforms))
        .where(PublicationAttempt.status.in_(candidate_statuses))
        .where(Job.source_path.in_(media_filters))
    )
    rows = await session.execute(statement)
    now_ts = _now_dt()
    stale_platforms: set[str] = set()
    context_reasons: dict[str, list[str]] = {}
    for item in rows.all():
        if not item or not item[0]:
            continue
        platform = _normalize(item[0]).replace("_", "-").lower()
        if not platform:
            continue
        status = _normalize(item[1]).lower() if len(item) > 1 else ""
        attempt_time = item[2] if len(item) > 2 else None
        if _is_release_in_progress_status(status):
            if not _record_is_recent(attempt_time, now_ts, ttl_seconds=stale_active_ttl_seconds):
                stale_platforms.add(platform)
                context_reasons.setdefault(platform, []).append(f"in_progress:{status or 'unknown'}")
                continue
            continue
        if status == "draft_created":
            if not _record_is_recent(attempt_time, now_ts, ttl_seconds=stale_active_ttl_seconds):
                stale_platforms.add(platform)
                context_reasons.setdefault(platform, []).append("draft_created_stale")
        else:
            stale_platforms.add(platform)
            context_reasons.setdefault(platform, []).append(f"failure_context:{status or 'unknown'}")
    context_reasons = {platform: sorted(set(reasons)) for platform, reasons in context_reasons.items()}
    return stale_platforms, context_reasons


def _build_creator_profile(
    platforms: list[str],
    profile_ids: list[str],
    *,
    publication_adapter: str,
    execution_mode: str,
    attached_profile_binding: dict[str, Any] | None = None,
    allow_anonymous_profile: bool = False,
    platform_adapters: dict[str, str] | None = None,
    platform_execution_modes: dict[str, str] | None = None,
    x_publication_adapter: str | None = None,
    x_execution_mode: str | None = None,
) -> dict[str, Any]:
    credentials = []
    normalized_profile_ids = [_normalize(item) for item in (profile_ids or []) if _normalize(item)]
    shared_creator_profile_id = ""
    if len(normalized_profile_ids) == 1 and not _looks_like_browser_profile_target(normalized_profile_ids[0]):
        shared_creator_profile_id = normalized_profile_ids[0]
    normalized_adapter = _normalize_publication_adapter(publication_adapter)
    normalized_execution_mode = _normalize_publication_execution_mode(execution_mode)
    normalized_platform_adapters = {
        _normalize(key).lower().replace("_", "-"): _normalize_publication_adapter(value)
        for key, value in (platform_adapters or {}).items()
        if _normalize(key) and _normalize_publication_adapter(value)
    }
    normalized_platform_execution_modes = {
        _normalize(key).lower().replace("_", "-"): _normalize_publication_execution_mode(value)
        for key, value in (platform_execution_modes or {}).items()
        if _normalize(key) and _normalize_publication_execution_mode(value)
    }
    normalized_x_publication_adapter = _normalize_publication_adapter(x_publication_adapter or normalized_adapter)
    normalized_x_execution_mode = _normalize_publication_execution_mode(x_execution_mode or normalized_execution_mode)
    normalized_attached_binding = normalize_publication_browser_binding(attached_profile_binding or {})
    attached_binding_profile_id = str(normalized_attached_binding.get("profile_id") or "").strip()
    for index, platform in enumerate(platforms):
        if len(profile_ids) == 1:
            profile_id = profile_ids[0]
        elif index < len(profile_ids):
            profile_id = profile_ids[index]
        else:
            if profile_ids:
                profile_id = profile_ids[-1]
            elif allow_anonymous_profile:
                profile_id = f"browser-agent:release-gate:{platform}"
            else:
                profile_id = ""
        browser_profile_id = profile_id if _looks_like_browser_profile_target(profile_id) else ""
        browser_binding: dict[str, Any] = {}
        if browser_profile_id:
            if attached_binding_profile_id and attached_binding_profile_id == browser_profile_id:
                browser_binding = dict(normalized_attached_binding)
            else:
                browser_binding = normalize_publication_browser_binding({"profile_id": browser_profile_id})
        platform_adapter = normalized_platform_adapters.get(platform, normalized_adapter)
        platform_execution_mode = normalized_platform_execution_modes.get(platform, normalized_execution_mode)
        if platform == "x" and x_publication_adapter:
            target_adapter = normalized_x_publication_adapter
            target_execution_mode = normalized_x_execution_mode
        else:
            target_adapter = platform_adapter
            target_execution_mode = platform_execution_mode
        credentials.append(
            {
                "id": f"release-gate-profile-{platform}",
                "platform": platform,
                "account_label": f"{platform} release-gate",
                "credential_ref": profile_id,
                "browser_profile_id": browser_profile_id,
                "browser_binding": browser_binding,
                "status": "logged_in",
                "enabled": True,
                "adapter": target_adapter,
                "execution_mode": target_execution_mode,
            }
        )
    if not shared_creator_profile_id and len(normalized_profile_ids) == 1 and _looks_like_browser_profile_target(normalized_profile_ids[0]):
        shared_creator_profile_id = f"release-gate::{normalized_profile_ids[0]}"
    return {
        "id": shared_creator_profile_id or "release-gate-profile",
        "display_name": "Publication Real Release Gate",
        "creator_profile": {
            "publishing": {
                "platform_credentials": credentials,
            }
        },
    }


def _latest_attempt_per_platform(attempts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    latest_ts: dict[str, datetime] = {}

    def _coerce_attempt_ts(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        text = _normalize(value)
        if not text:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            normalized = text.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)

    for attempt in attempts:
        platform = _normalize(attempt.get("platform")).lower().replace("_", "-")
        if not platform:
            continue
        candidate_ts = _coerce_attempt_ts(attempt.get("updated_at") or attempt.get("created_at"))
        existing_ts = latest_ts.get(platform)
        if existing_ts is None or candidate_ts > existing_ts:
            latest[platform] = attempt
            latest_ts[platform] = candidate_ts
    return latest


def _normalize_error_codes(raw_codes: str) -> set[str]:
    return {
        _normalize(code).lower()
        for code in _normalize(raw_codes).replace("，", ",").split(",")
        if _normalize(code)
    }


def _parse_platform_adapter_overrides(raw_overrides: list[str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for item in raw_overrides or []:
        text = _normalize(item)
        if not text:
            continue
        if "=" in text:
            platform, adapter = text.split("=", 1)
        elif ":" in text:
            platform, adapter = text.split(":", 1)
        else:
            continue
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        normalized_adapter = _normalize_publication_adapter(adapter)
        if normalized_platform and normalized_adapter:
            normalized[normalized_platform] = normalized_adapter
    return normalized


def _parse_platform_execution_mode_overrides(raw_overrides: list[str] | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for item in raw_overrides or []:
        text = _normalize(item)
        if not text:
            continue
        if "=" in text:
            platform, mode = text.split("=", 1)
        elif ":" in text:
            platform, mode = text.split(":", 1)
        else:
            continue
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        normalized_mode = _normalize_publication_execution_mode(mode)
        if normalized_platform and normalized_mode:
            normalized[normalized_platform] = normalized_mode
    return normalized


async def _published_platforms_for_media(
    *,
    session: Any,
    media_path: str,
    platforms: list[str],
    expected_platform_signatures: dict[str, str] | None = None,
    expected_platform_manifest: dict[str, dict[str, Any]] | None = None,
    include_draft_created: bool = False,
    dedupe_active_ttl_seconds: int = 0,
) -> set[str]:
    normalized_media = _normalize(media_path)
    normalized_platforms = [platform for platform in (_normalize(item).replace("_", "-").lower() for item in (platforms or [])) if platform]
    canonical_media = _canonical_media_path(normalized_media)
    media_path_values: set[str] = {normalized_media} if normalized_media else set()
    if canonical_media:
        media_path_values.add(canonical_media)
    if not media_path_values or not normalized_platforms:
        return set()
    try:
        media_path_filters = list(media_path_values)
    except TypeError:
        media_path_filters = [normalized_media]

    dedupe_statuses = {"published", "scheduled_pending"}
    if include_draft_created:
        dedupe_statuses.add("draft_created")
    candidate_statuses = dedupe_statuses | set(PUBLICATION_ACTIVE_STATUSES)
    candidate_statuses = sorted(candidate_statuses)
    rows = await session.execute(
        select(PublicationAttempt)
        .join(Job, PublicationAttempt.job_id == Job.id)
        .where(PublicationAttempt.platform.in_(normalized_platforms))
        .where(PublicationAttempt.status.in_(candidate_statuses))
        .where(Job.source_path.in_(media_path_filters))
    )
    attempts = rows.scalars().all()
    expected_signatures = {
        _normalize(platform): _normalize(signature)
        for platform, signature in (expected_platform_signatures or {}).items()
        if _normalize(platform) and _normalize(signature)
    }
    manifest_by_platform = expected_platform_manifest or {}
    published_platforms: set[str] = set()
    now_ts = _now_dt()
    for attempt in attempts:
        platform = _normalize(attempt.platform).lower().replace("_", "-")
        if not platform:
            continue
        status = _normalize(attempt.status).lower()
        request_payload = attempt.request_payload if isinstance(attempt.request_payload, dict) else {}
        response_payload = attempt.response_payload if isinstance(attempt.response_payload, dict) else {}
        attempt_signature = (
            _extract_publication_signature(request_payload)
            or _extract_publication_signature(response_payload)
        )
        if _is_release_in_progress_status(status):
            if not _record_is_recent(attempt.updated_at, now_ts, ttl_seconds=dedupe_active_ttl_seconds):
                continue
            published_platforms.add(platform)
            continue
        if status == "published" and platform != "x" and not _looks_like_public_url(attempt.external_url):
            continue
        if not expected_signatures:
            published_platforms.add(platform)
            continue
        expected_signature = expected_signatures.get(platform)
        if not expected_signature:
            published_platforms.add(platform)
            continue
        if _normalize(attempt_signature) != expected_signature:
            continue
        manifest_entry = manifest_by_platform.get(platform) if isinstance(manifest_by_platform.get(platform), dict) else {}
        expected_request_fields = (
            manifest_entry.get("request_fields")
            if isinstance(manifest_entry, dict) and isinstance(manifest_entry.get("request_fields"), dict)
            else {}
        )
        if _is_strict_verification_platform(platform) and not expected_request_fields:
            continue
        if not expected_request_fields:
            published_platforms.add(platform)
            continue
        run_payloads = _collect_publication_runs(attempt)
        latest_run = run_payloads[0] if run_payloads else {}
        run_result = latest_run.get("result") if isinstance(latest_run, dict) else {}
        snapshot_request_fields_from_response = _extract_publication_field_snapshot(response_payload)
        snapshot_request_fields_from_run = _extract_publication_field_snapshot(run_result)
        snapshot_request_fields_from_request = _extract_publication_field_snapshot(request_payload)
        snapshot_request_fields = (
            snapshot_request_fields_from_response
            or snapshot_request_fields_from_run
            or snapshot_request_fields_from_request
        )
        if isinstance(snapshot_request_fields, dict) and snapshot_request_fields:
            snapshot_request_fields = _merge_snapshot_with_request_payload_backfill(
                snapshot_request_fields,
                expected_request_fields,
            )
        snapshot_source = (
            "response_payload"
            if bool(snapshot_request_fields_from_response)
            else "run_result"
            if bool(snapshot_request_fields_from_run)
            else "request_payload"
            if bool(snapshot_request_fields)
            else ""
        )
        if snapshot_source != "response_payload" and snapshot_source != "run_result":
            continue
        if _build_field_differences(expected_request_fields, snapshot_request_fields):
            continue
        direct_audit, _ = _extract_publication_audit(response_payload)
        if not direct_audit:
            direct_audit, _ = _extract_publication_audit(request_payload)
        if not direct_audit:
            direct_audit, _ = _extract_publication_audit(run_result)
        if isinstance(direct_audit, dict) and direct_audit.get("verified") is False:
            continue
        if status == "scheduled_pending" and not _normalize(attempt.scheduled_at):
            continue
        published_platforms.add(platform)
    return published_platforms


def _evaluate_progress(
    all_attempts: list[dict[str, Any]],
    targets: list[str],
    *,
    expected_statuses: set[str],
    expected_platform_manifest: dict[str, dict[str, Any]] | None = None,
    auto_recover_codes: set[str] | None = None,
    recovery_quota_by_platform: dict[str, int] | None = None,
    max_recoveries_per_platform: int = 1,
    fresh_draft_prepare_mode: bool = False,
) -> tuple[str, list[str], list[dict[str, Any]], bool, list[str], list[str]]:
    latest = _latest_attempt_per_platform(all_attempts)
    failures: list[str] = []
    terminal_failure = False
    platform_summaries: list[dict[str, Any]] = []
    recoverable_platforms: list[str] = []
    recoverable_failures: list[str] = []
    platform_ready: dict[str, bool] = {}
    auto_codes = auto_recover_codes or set()
    quota = recovery_quota_by_platform or {}
    manifest_by_platform = expected_platform_manifest or {}

    hard_failures_seen: set[str] = set()
    recoverable_failures_seen: set[str] = set()

    def _record_failure(message: str, *, recoverable: bool = False) -> None:
        if recoverable:
            if message and message not in recoverable_failures_seen:
                recoverable_failures_seen.add(message)
                recoverable_failures.append(message)
        elif message and message not in hard_failures_seen:
            hard_failures_seen.add(message)
            failures.append(message)

    for platform in targets:
        attempt = latest.get(platform)
        if attempt is None:
            _record_failure(f"{platform} 未创建发布任务")
            terminal_failure = True
            continue
        status = _normalize(attempt.get("status")).lower()
        request_payload = attempt.get("request_payload") if isinstance(attempt.get("request_payload"), dict) else {}
        response_payload = attempt.get("response_payload") if isinstance(attempt.get("response_payload"), dict) else {}
        run_payloads = _collect_publication_runs(attempt)
        latest_run = run_payloads[0] if run_payloads else {}
        run_result = latest_run.get("result") if isinstance(latest_run, dict) else {}
        run_audit = _extract_audit_from_run(latest_run)
        direct_audit, audit_issues = _extract_publication_audit(response_payload)
        if not direct_audit:
            direct_audit, audit_issues = _extract_publication_audit(request_payload)
        if not direct_audit:
            direct_audit, audit_issues = _extract_publication_audit(run_audit)
        response_material_integrity = _extract_material_integrity(response_payload)
        if not response_material_integrity:
            response_material_integrity = _extract_material_integrity(run_result)
        final_publish = _extract_final_publish(response_payload)
        if not final_publish:
            final_publish = _extract_final_publish(run_result)
        pre_publish_repair = _extract_pre_publish_repair(response_payload)
        if not pre_publish_repair:
            pre_publish_repair = _extract_pre_publish_repair(run_result)
        receipt_binding = (
            _extract_receipt_binding(response_payload)
            or _extract_receipt_binding(run_result)
            or _extract_receipt_binding({"publication_audit": direct_audit, "material_integrity": response_material_integrity})
        )
        visual_evidence = (
            _extract_visual_evidence(response_payload)
            or _extract_visual_evidence(run_result)
            or _extract_visual_evidence(latest_run)
            or _extract_visual_evidence(request_payload)
        )
        material_integrity_pending = _is_material_integrity_pending(response_material_integrity)
        if not material_integrity_pending:
            material_integrity_pending = _has_upload_progress_pending_signal(response_payload) or _has_upload_progress_pending_signal(run_result)
        expected_entry = manifest_by_platform.get(platform) or {}
        expected_signature = _normalize(expected_entry.get("content_signature"))
        expected_adapter = _normalize(expected_entry.get("adapter"))
        expected_adapter = expected_adapter if expected_adapter else _normalize(attempt.get("adapter"))
        adapter = _normalize_publication_adapter(attempt.get("adapter"))
        is_stable = _is_strict_verification_platform(platform) and not fresh_draft_prepare_mode
        expected_request_fields = expected_entry.get("request_fields") if isinstance(expected_entry.get("request_fields"), dict) else {}
        request_contract_ready = bool(expected_request_fields) if is_stable else True
        actual_request_fields = _extract_request_payload_fields(request_payload)
        actual_request_fields["platform"] = platform
        if not actual_request_fields.get("adapter") and adapter:
            actual_request_fields["adapter"] = adapter
        request_payload_field_mismatches = (
            _build_field_differences(expected_request_fields, actual_request_fields, ignored_keys={"platform_specific_overrides"})
            if request_contract_ready
            else []
        )
        snapshot_request_fields_from_response = _extract_publication_field_snapshot(response_payload)
        snapshot_request_fields_from_run = _extract_publication_field_snapshot(run_result)
        snapshot_request_fields_from_request = _extract_publication_field_snapshot(request_payload)
        if _is_release_in_progress_status(status):
            snapshot_request_fields = (
                snapshot_request_fields_from_response
                or snapshot_request_fields_from_run
            )
        else:
            snapshot_request_fields = (
                snapshot_request_fields_from_response
                or snapshot_request_fields_from_run
                or snapshot_request_fields_from_request
            )
        if isinstance(snapshot_request_fields, dict) and snapshot_request_fields:
            snapshot_request_fields = _merge_snapshot_with_request_payload_backfill(
                snapshot_request_fields,
                actual_request_fields,
            )
        actual_request_fields_snapshot = snapshot_request_fields if isinstance(snapshot_request_fields, dict) else {}
        request_fields_snapshot_source = (
            "response_payload"
            if bool(snapshot_request_fields_from_response)
            else "run_result"
            if bool(snapshot_request_fields_from_run)
            else "request_payload"
            if bool(snapshot_request_fields)
            else ""
        )
        request_field_mismatches = (
            _build_field_differences(expected_request_fields, snapshot_request_fields)
            if request_contract_ready
            else []
        )
        request_field_mismatches = _suppress_content_gap_fields_while_material_pending(
            request_field_mismatches,
            material_integrity_pending=material_integrity_pending,
        )
        request_field_mismatches = _suppress_request_field_mismatches_with_non_required_audit_fields(
            request_field_mismatches,
            direct_audit if isinstance(direct_audit, dict) else {},
        )
        request_plan_fill_gaps = _build_request_plan_fill_gaps(
            expected_request_fields,
            actual_request_fields_snapshot,
            critical_fields=SUBMITTED_DRAFT_CRITICAL_FIELDS,
        ) if request_contract_ready else []
        request_plan_fill_gaps = _suppress_content_gap_fields_while_material_pending(
            request_plan_fill_gaps,
            material_integrity_pending=material_integrity_pending,
        )
        request_plan_fill_gaps = _suppress_request_plan_fill_gaps_with_non_required_audit_fields(
            request_plan_fill_gaps,
            direct_audit if isinstance(direct_audit, dict) else {},
        )
        request_fields_snapshot_missing = (
            bool(expected_request_fields)
            and bool(request_contract_ready)
            and not snapshot_request_fields
        )
        response_payload_empty_snapshot = (
            request_fields_snapshot_source == "response_payload"
            and _is_response_snapshot_plan_empty(
                expected_request_fields=expected_request_fields,
                response_payload_snapshot=snapshot_request_fields_from_response,
                critical_fields=SUBMITTED_DRAFT_CRITICAL_FIELDS,
            )
        )
        if material_integrity_pending and isinstance(actual_request_fields_snapshot, dict) and actual_request_fields_snapshot:
            response_payload_empty_snapshot = False
        submitted_response_payload_empty_snapshot = (
            status == "submitted" and response_payload_empty_snapshot
        )
        request_fields_snapshot_trusted = (
            request_fields_snapshot_source in {"response_payload", "run_result"}
            and not response_payload_empty_snapshot
        )
        expected_request_fields_count = len(expected_request_fields) if isinstance(expected_request_fields, dict) else 0
        actual_request_fields_count = len(actual_request_fields)
        snapshot_request_fields_count = len(actual_request_fields_snapshot)
        request_payload_plan_match = (
            request_contract_ready
            and not bool(request_payload_field_mismatches)
        )
        request_snapshot_plan_match = (
            request_contract_ready
            and not bool(request_plan_fill_gaps)
            and not request_fields_snapshot_missing
            and request_fields_snapshot_trusted
            and not bool(request_field_mismatches)
        )
        plan_fill_audit = [
            {
                "field": "expected_fields_count",
                "expected": expected_request_fields_count,
                "actual": actual_request_fields_count,
            },
            {
                "field": "snapshot_fields_count",
                "expected": expected_request_fields_count,
                "actual": snapshot_request_fields_count,
            },
            {
                "field": "snapshot_source",
                "expected": "response_payload|run_result",
                "actual": request_fields_snapshot_source,
            },
        ]
        strict_contract_reasons: list[str] = []
        if expected_adapter and adapter and adapter != expected_adapter:
            _record_failure(f"{platform} 适配器回传值异常，计划={expected_adapter}，实际={adapter}。")
            strict_contract_reasons.append("adapter_mismatch")
            terminal_failure = True
        if is_stable and not request_contract_ready:
            mismatch_reason = (
                f"{platform} 稳定发布缺少 request_fields 合同基线（manifest.request_fields 不存在）。"
            )
            _record_failure(mismatch_reason)
            strict_contract_reasons.append("missing_contract")
            terminal_failure = True
        request_payload_critical_mismatch_fields = {
            "title",
            "body",
            "hashtags",
            "display_hashtags",
            "structured_tags",
            "media_urls",
            "media_items_count",
            "copy_material",
            "cover_path",
            "cover_slots",
            "category",
            "declaration",
        }
        request_signature = _extract_publication_signature(request_payload)
        response_signature = _extract_publication_signature(response_payload)
        run_signature = _extract_publication_signature(run_result)
        actual_signature = response_signature or request_signature or run_signature
        expected_signature_fields = (
            expected_entry.get("signature_fields")
            if isinstance(expected_entry.get("signature_fields"), dict)
            else {}
        )
        request_signature_fields = _extract_publication_signature_fields(request_payload)
        response_signature_fields = _extract_publication_signature_fields(response_payload)
        run_signature_fields = _extract_publication_signature_fields(run_result)
        signature_field_values = [
            value
            for value in (response_signature_fields, run_signature_fields)
            if isinstance(value, dict) and value
        ]
        signature_fields_match = (
            not expected_signature_fields
            or (
                bool(signature_field_values)
                and all(item == expected_signature_fields for item in signature_field_values)
            )
        )
        duplicate_detected = (
            _collect_duplicate_flag(response_payload)
            or _collect_duplicate_flag(request_payload)
            or _collect_duplicate_flag(run_payloads[0] if isinstance(run_payloads, list) and run_payloads else {})
            or _collect_duplicate_flag(run_audit)
        )
        scheduled_publish_at = _normalize(
            (
                request_payload.get("scheduled_publish_at")
                if isinstance(request_payload.get("scheduled_publish_at"), str)
                else ""
            )
        )
        external_url = _normalize(attempt.get("external_url"))
        summary = {
            "platform": platform,
            "attempt_id": _normalize(attempt.get("id")),
            "status": status,
            "run_status": _normalize(attempt.get("run_status")).lower(),
            "provider_status": _normalize(attempt.get("provider_status")),
            "error_code": _normalize(attempt.get("error_code")),
            "provider_task_id": _normalize(attempt.get("provider_task_id")),
            "external_post_id": _normalize(attempt.get("external_post_id")),
            "external_url": external_url,
            "public_url": external_url,
            "scheduled_publish_at": scheduled_publish_at,
            "scheduled_at": _normalize(attempt.get("scheduled_at")),
            "attempt_adapter": adapter,
            "expected_adapter": expected_adapter,
            "request_signature": request_signature,
            "response_signature": response_signature,
            "run_signature": run_signature,
            "request_signature_fields": request_signature_fields,
            "response_signature_fields": response_signature_fields,
            "run_signature_fields": run_signature_fields,
            "expected_signature_fields": expected_signature_fields,
            "expected_signature": expected_signature,
            "manifest_signature_fields": expected_entry.get("signature_fields"),
            "expected_request_fields": expected_request_fields,
            "actual_request_fields": actual_request_fields_snapshot,
            "request_payload_fields": actual_request_fields,
            "request_payload_field_mismatches": request_payload_field_mismatches,
            "request_payload_fields_match": not bool(request_payload_field_mismatches),
            "request_payload_field_mismatch_fields": [
                _normalize(_normalize_mismatch_field(item))
                for item in request_payload_field_mismatches
                if _normalize(_normalize_mismatch_field(item))
            ],
            "actual_request_fields_snapshot": snapshot_request_fields,
            "actual_request_fields_snapshot_source": request_fields_snapshot_source,
            "request_plan_fill_gaps": request_plan_fill_gaps,
            "request_fields_snapshot_trusted": bool(request_fields_snapshot_trusted),
            "request_fields_snapshot_missing": request_fields_snapshot_missing,
            "request_contract_ready": bool(request_contract_ready),
            "request_fields_snapshot_count": snapshot_request_fields_count,
            "request_fields_expected_count": expected_request_fields_count,
            "request_fields_actual_count": actual_request_fields_count,
            "request_payload_plan_match": bool(request_payload_plan_match),
            "request_snapshot_plan_match": bool(request_snapshot_plan_match),
            "request_payload_field_mismatch_count": len(request_payload_field_mismatches),
            "request_field_mismatch_count": len(request_field_mismatches),
            "request_fields_plan_fill_audit": plan_fill_audit,
            "request_field_verification": [
                {
                    "field": _normalize_mismatch_field(item),
                    "expected": item.get("expected"),
                    "actual": item.get("actual"),
                    "match": False,
                }
                for item in request_field_mismatches
                if _normalize(_normalize_mismatch_field(item))
            ],
            "field_mismatches": request_field_mismatches,
            "field_match": not bool(request_field_mismatches),
            "request_field_mismatch_fields": [
                _normalize(_normalize_mismatch_field(item))
                for item in request_field_mismatches
                if _normalize(_normalize_mismatch_field(item))
            ],
            "signature_match": bool(expected_signature and actual_signature and actual_signature == expected_signature),
            "signature_fields_match": bool(signature_fields_match),
            "signature_fields_available": bool(signature_field_values),
            "signature_match_status": "match" if bool(actual_signature and expected_signature and actual_signature == expected_signature) else (
                "missing" if expected_signature and not actual_signature else (
                    "unmatched" if expected_signature and actual_signature and actual_signature != expected_signature else "n/a"
                )
            ),
            "publication_audit": direct_audit,
            "publication_audit_issues": audit_issues,
            "material_integrity": response_material_integrity,
            "material_integrity_pending": bool(material_integrity_pending),
            "verification_reason": (
                _normalize(response_material_integrity.get("verification_reason"))
                if isinstance(response_material_integrity, dict)
                else ""
            ),
            "upload_failure_reason": _extract_upload_failure_reason(response_payload) or _extract_upload_failure_reason(run_result),
            "pre_publish_repair": pre_publish_repair,
            "repair_evidence": snapshot_request_fields.get("repair_evidence") if isinstance(snapshot_request_fields, dict) and isinstance(snapshot_request_fields.get("repair_evidence"), dict) else {},
            "receipt_binding": receipt_binding,
            "receipt_binding_id": _extract_receipt_binding_id(response_payload, receipt_binding),
            "receipt_target_unbound": _is_receipt_target_unbound(receipt_binding),
            "visual_evidence": visual_evidence,
            "duplicate_detected": bool(duplicate_detected),
            "runs_count": len(run_payloads),
            "strict_contract_verified": False,
            "strict_contract_reasons": [],
            "verified_stop_before_final_publish": False,
        }
        summary["pre_publish_upload_pending"] = _is_pre_publish_upload_pending_summary(summary)
        summary["upload_not_applied"] = _is_upload_not_applied_summary(summary)
        summary["route_auth_required"] = _is_route_auth_required_summary(summary)
        summary["post_repair_preserve_context"] = _is_post_repair_structural_blocker_context(
            pre_publish_repair=summary.get("pre_publish_repair") if isinstance(summary.get("pre_publish_repair"), dict) else {},
            repair_evidence=summary.get("repair_evidence") if isinstance(summary.get("repair_evidence"), dict) else {},
            required_unverified=(
                direct_audit.get("required_unverified")
                if isinstance(direct_audit, dict) and isinstance(direct_audit.get("required_unverified"), list)
                else []
            ),
            required_reupload=(
                direct_audit.get("required_reupload")
                if isinstance(direct_audit, dict) and isinstance(direct_audit.get("required_reupload"), list)
                else []
            ),
        )
        bound_receipt_verification_success = _is_bound_receipt_verification_success(
            status,
            receipt_binding,
            direct_audit if isinstance(direct_audit, dict) else None,
        )
        verified_stop_before_final_publish_success = _is_verified_stop_before_final_publish_success(
            status,
            final_publish if isinstance(final_publish, dict) else None,
            direct_audit if isinstance(direct_audit, dict) else None,
        )
        summary["verified_stop_before_final_publish"] = bool(verified_stop_before_final_publish_success)
        platform_ready[platform] = False
        platform_summaries.append(summary)
        is_x_link_share = platform == "x" and expected_adapter == "x_link_share"
        require_public_url_for_success = False
        processing_snapshot_toleration = (
            _is_strict_verification_platform(platform)
            and status in {"processing", "submitted"}
            and bool(expected_request_fields)
            and request_payload_plan_match
            and expected_signature
            and expected_signature == actual_signature
        )
        success_signature_snapshot_toleration = (
            _is_strict_verification_platform(platform)
            and bool(expected_request_fields)
            and request_payload_plan_match
            and expected_signature
            and expected_signature == actual_signature
        )
        request_payload_critical_mismatch_fields = {
            "title",
            "body",
            "hashtags",
            "display_hashtags",
            "structured_tags",
            "media_urls",
            "media_items_count",
            "copy_material",
            "cover_path",
            "cover_slots",
            "category",
            "declaration",
        }
        if is_stable and _should_apply_active_snapshot_strictness(status, expected_statuses=expected_statuses) and expected_request_fields:
            active_payload_mismatch_fields = [
                _normalize(_normalize_mismatch_field(item))
                for item in request_payload_field_mismatches
                if _normalize(_normalize_mismatch_field(item)) in request_payload_critical_mismatch_fields
            ]
            if active_payload_mismatch_fields:
                mismatch_code = "publication_request_payload_fields_mismatch"
                mismatch_fields = ", ".join(active_payload_mismatch_fields[:4])
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 发布中关键字段与计划不一致（{mismatch_fields or mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    strict_contract_reasons.append("strict_contract_failed")
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 发布中关键字段与计划不一致（{mismatch_fields or mismatch_code}），阻断采信。")
                    strict_contract_reasons.append("request_payload_mismatch")
                    terminal_failure = True
            elif request_plan_fill_gaps:
                mismatch_fields = ", ".join(_normalize(_normalize_mismatch_field(item)) for item in request_plan_fill_gaps[:4])
                mismatch_code = "publication_request_plan_content_fill_gaps"
                if status == "submitted" and submitted_response_payload_empty_snapshot:
                    mismatch_code = "publication_submitted_response_payload_empty_snapshot"
                    mismatch_reason = (
                        f"{platform} 提交态 response_payload 关键字段快照为空值（{mismatch_code}），触发发布页核验与清稿候选恢复。"
                    )
                    _record_failure(mismatch_reason)
                    if "submitted_response_payload_empty_snapshot" not in strict_contract_reasons:
                        strict_contract_reasons.append("submitted_response_payload_empty_snapshot")
                    if status == "submitted":
                        strict_contract_reasons.append("submitted_content_plan_fill_gaps_pending")
                elif status == "submitted":
                    _record_failure(
                        f"{platform} 提交态关键字段持续未回填（{mismatch_fields or mismatch_code}），先等待平台真实回执与页面核验。",
                    )
                    strict_contract_reasons.append("submitted_content_plan_fill_gaps_pending")
                elif processing_snapshot_toleration:
                    if (
                        _is_auto_recoverable_error_code(mismatch_code, auto_codes)
                        and quota.get(platform, 0) < max_recoveries_per_platform
                        and len(run_payloads) >= 2
                    ):
                        _record_failure(
                            f"{platform} 发布中关键字段持续未回填（{mismatch_fields or mismatch_code}），持续超限后触发草稿清理重试。",
                            recoverable=True,
                        )
                        strict_contract_reasons.append("strict_contract_failed")
                        if platform not in recoverable_platforms:
                            recoverable_platforms.append(platform)
                    else:
                        _record_failure(
                            f"{platform} 发布中关键字段未完整回填（{mismatch_fields or mismatch_code}），暂不采信快照并继续观察。",
                        )
                        strict_contract_reasons.append("content_plan_fill_gaps_pending")
                elif _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 发布中关键字段未完整回填（{mismatch_fields or mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    strict_contract_reasons.append("strict_contract_failed")
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 发布中关键字段未完整回填，疑似草稿污染。")
                    strict_contract_reasons.append("content_plan_fill_gaps")
                    terminal_failure = True
                if status == "submitted" and request_fields_snapshot_missing:
                    mismatch_code = "publication_submitted_response_payload_missing"
                    mismatch_reason = (
                        f"{platform} 提交态 response_payload 未返回字段快照（{mismatch_code}），先核验平台发布结果。"
                    )
                    _record_failure(mismatch_reason)
                    strict_contract_reasons.append("submitted_response_payload_unverified")
                elif status == "submitted" and not request_fields_snapshot_trusted:
                    mismatch_code = "publication_response_payload_untrusted"
                    mismatch_reason = (
                        f"{platform} 提交态字段快照来源可信度不足（{mismatch_code}），需先核验发布页实际内容后再决定清稿。"
                    )
                    _record_failure(mismatch_reason)
                    strict_contract_reasons.append("response_payload_unverified")
            elif request_fields_snapshot_missing or not request_fields_snapshot_trusted:
                mismatch_code = "publication_request_fields_snapshot_missing"
                mismatch_code = (
                    "publication_request_field_snapshot_untrusted"
                    if not request_fields_snapshot_trusted
                    else "publication_request_fields_snapshot_missing"
                )
                mismatch_reason = (
                    f"{platform} 发布中字段快照异常（{mismatch_code}），疑似页面回填未完整返回，触发草稿清理重试。"
                )
                if processing_snapshot_toleration and (request_fields_snapshot_missing or not request_fields_snapshot_trusted):
                    if (
                        _is_auto_recoverable_error_code(mismatch_code, auto_codes)
                        and quota.get(platform, 0) < max_recoveries_per_platform
                        and len(run_payloads) >= 2
                    ):
                        _record_failure(mismatch_reason, recoverable=True)
                        strict_contract_reasons.append("strict_contract_failed")
                        if platform not in recoverable_platforms:
                            recoverable_platforms.append(platform)
                    else:
                        _record_failure(
                            f"{platform} 发布中字段快照暂未回填（{mismatch_code}），先以请求快照持续观测。",
                        )
                        if "content_plan_fill_gaps_pending" not in strict_contract_reasons:
                            strict_contract_reasons.append("content_plan_fill_gaps_pending")
                elif _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(mismatch_reason, recoverable=True)
                    strict_contract_reasons.append("strict_contract_failed")
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(mismatch_reason)
                    strict_contract_reasons.append(
                        "field_snapshot_untrusted"
                        if not request_fields_snapshot_trusted
                        else "field_snapshot_missing"
                    )
                    terminal_failure = True
        if is_stable and status == "draft_created" and not verified_stop_before_final_publish_success:
            mismatch_code = "publication_draft_created"
            if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                _record_failure(
                    f"{platform} 稳定平台停留在草稿态，疑似未清理旧草稿（{mismatch_code}），触发草稿清理重试。",
                    recoverable=True,
                )
                strict_contract_reasons.append("draft_created_recoverable")
                if platform not in recoverable_platforms:
                    recoverable_platforms.append(platform)
            else:
                _record_failure(f"{platform} 稳定平台终态为 draft_created，未公开发布。")
                strict_contract_reasons.append("draft_created_terminal")
                terminal_failure = True
        if status in PUBLICATION_SUCCESS_STATUSES and not verified_stop_before_final_publish_success:
            if is_stable and request_payload_field_mismatches:
                mismatch_code = "publication_request_payload_fields_mismatch"
                mismatch_fields = ", ".join(_normalize(_normalize_mismatch_field(item)) for item in request_payload_field_mismatches[:4])
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 发布请求 payload 与计划字段不一致（{mismatch_fields or mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 发布请求 payload 与计划字段不一致（{mismatch_fields or mismatch_code}）。")
                    strict_contract_reasons.append("request_payload_mismatch")
                    terminal_failure = True
            elif is_stable and request_plan_fill_gaps:
                mismatch_code = "publication_request_plan_content_fill_gaps"
                if success_signature_snapshot_toleration:
                    strict_contract_reasons.append("content_plan_fill_gaps_deferred")
                elif _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 发布关键字段回填缺失（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 发布关键字段未正确回填，拒绝采信发布成功。")
                    strict_contract_reasons.append("content_plan_fill_gaps")
                    terminal_failure = True
            elif is_stable and expected_signature and not actual_signature:
                mismatch_code = "publication_signature_missing"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布未回传签名（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(
                        f"{platform} 终态发布未回传签名，无法确认实际发布内容是否与发布计划一致。"
                    )
                    strict_contract_reasons.append("signature_missing")
                    terminal_failure = True
            elif is_stable and expected_signature and actual_signature != expected_signature:
                mismatch_code = "publication_signature_mismatch"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布内容签名与计划签名不一致（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(
                        f"{platform} 终态发布回传内容签名与计划签名不一致，疑似草稿污染。"
                    )
                    strict_contract_reasons.append("signature_mismatch")
                    terminal_failure = True
            elif is_stable and bool(expected_signature_fields) and not signature_field_values:
                if not bound_receipt_verification_success:
                    mismatch_code = "publication_signature_fields_missing"
                    if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                        _record_failure(
                            f"{platform} 终态发布缺少签名字段回执（{mismatch_code}），触发草稿清理重试。",
                            recoverable=True,
                        )
                        if platform not in recoverable_platforms:
                            recoverable_platforms.append(platform)
                    else:
                        _record_failure(f"{platform} 终态发布缺少签名字段回执，无法确认字段是否与发布计划一致。")
                        strict_contract_reasons.append("signature_fields_missing")
                        terminal_failure = True
            elif is_stable and request_fields_snapshot_missing:
                mismatch_code = "publication_request_fields_snapshot_missing"
                if success_signature_snapshot_toleration:
                    strict_contract_reasons.append("content_plan_fill_gaps_deferred")
                elif _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布缺失字段快照（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 终态发布缺失字段快照，无法确认实际发布内容是否被污染。")
                    strict_contract_reasons.append("field_snapshot_missing")
                    terminal_failure = True
            elif is_stable and expected_request_fields and not request_fields_snapshot_trusted:
                mismatch_code = "publication_request_field_snapshot_untrusted"
                if success_signature_snapshot_toleration:
                    strict_contract_reasons.append("content_plan_fill_gaps_deferred")
                elif _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布字段快照来源不可信（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 终态发布字段快照仅来自请求体，无法确认发布页实际填入字段。")
                    strict_contract_reasons.append("field_snapshot_untrusted")
                    terminal_failure = True
            elif is_stable and not signature_fields_match:
                mismatch_code = "publication_signature_fields_mismatch"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布签名字段与计划不一致（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 终态发布签名字段与计划不一致。")
                    strict_contract_reasons.append("signature_fields_mismatch")
                    terminal_failure = True
            elif is_stable and request_field_mismatches:
                mismatch_fields = ", ".join(_normalize(_normalize_mismatch_field(item)) for item in request_field_mismatches[:4])
                mismatch_code = "publication_content_mismatch"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布字段与计划不一致（{mismatch_fields}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 终态发布内容字段与计划不一致（{mismatch_fields}）。")
                    strict_contract_reasons.append("content_mismatch")
                    terminal_failure = True
            elif is_stable and bool(summary.get("receipt_target_unbound")):
                _record_failure(f"{platform} 发布后回执尚未唯一绑定到本次作品，拒绝采信该终态。")
                strict_contract_reasons.append("receipt_target_unbound")
                terminal_failure = True
            elif is_stable and isinstance(direct_audit, dict) and direct_audit.get("verified") is False:
                mismatch_code = "publication_audit_unverified"
                audit_issues = (
                    ", ".join(audit_issues[:4]) if isinstance(audit_issues, list) else ""
                )
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布内容审核未通过（{audit_issues or mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(
                        f"{platform} 终态发布内容审核未通过（{audit_issues or mismatch_code}），拒绝采信发布成功。"
                    )
                    strict_contract_reasons.append("audit_unverified")
                    terminal_failure = True
            if is_stable and duplicate_detected:
                _record_failure(f"{platform} 检测到疑似重复发布痕迹，已阻止该终态作为成功采信。")
                strict_contract_reasons.append("content_duplicate")
                terminal_failure = True
            require_public_url_for_success = _should_require_public_url_for_strict_success(
                platform=platform,
                status=status,
                bound_receipt_verification_success=bound_receipt_verification_success,
                is_x_link_share=is_x_link_share,
            )
            if require_public_url_for_success and not _looks_like_public_url(external_url):
                mismatch_code = "publication_public_url_missing"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 终态发布未回传可公开链接（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 发布成功但未回传可公开发布链接。")
                    strict_contract_reasons.append("public_url_missing")
                    terminal_failure = True
            if status == "scheduled_pending" and scheduled_publish_at and not _normalize(attempt.get("scheduled_at")):
                mismatch_code = "publication_schedule_receipt_missing"
                if _is_auto_recoverable_error_code(mismatch_code, auto_codes) and quota.get(platform, 0) < max_recoveries_per_platform:
                    _record_failure(
                        f"{platform} 预约状态回执缺失（{mismatch_code}），触发草稿清理重试。",
                        recoverable=True,
                    )
                    if platform not in recoverable_platforms:
                        recoverable_platforms.append(platform)
                else:
                    _record_failure(f"{platform} 进入已预约状态但未回读预约时间回执。")
                    strict_contract_reasons.append("schedule_receipt_missing")
                    terminal_failure = True
        error_code = _normalize(attempt.get("error_code"))
        is_recoverable_terminal = (
            (
                status == "needs_human"
                and _is_auto_recoverable_error_code(error_code, auto_codes)
                and quota.get(platform, 0) < max_recoveries_per_platform
            )
        or (
            status == "failed"
            and _is_auto_recoverable_error_code(error_code, auto_codes)
            and quota.get(platform, 0) < max_recoveries_per_platform
        )
        or (
            is_stable
            and status == "draft_created"
            and _is_auto_recoverable_error_code("publication_draft_created", auto_codes)
            and quota.get(platform, 0) < max_recoveries_per_platform
        )
        )
        stable_unknown_failed = (
            is_stable
            and status == "failed"
            and not _is_auto_recoverable_error_code(error_code, auto_codes)
            and quota.get(platform, 0) < max_recoveries_per_platform
        )
        if is_recoverable_terminal:
            if status == "failed":
                _record_failure(f"{platform} 进入失败态，触发自动草稿清理重试（{error_code}）。", recoverable=True)
                strict_contract_reasons.append("failed_recoverable")
            elif status == "needs_human":
                _record_failure(f"{platform} 停留在需要人工介入态，触发草稿清理重试（{error_code}）。", recoverable=True)
                strict_contract_reasons.append("needs_human_recoverable")
            if platform not in recoverable_platforms:
                recoverable_platforms.append(platform)
        elif stable_unknown_failed:
            _record_failure(
                f"{platform} 终态失败且未匹配已知重试码（{error_code or 'unknown'}），先清理草稿重试一次。",
                recoverable=True,
            )
            strict_contract_reasons.append("failed_unclassified_recoverable")
            if platform not in recoverable_platforms:
                recoverable_platforms.append(platform)
        elif (
            status in PUBLICATION_TERMINAL_STATUSES
            and status not in expected_statuses
            and not is_recoverable_terminal
            and not bound_receipt_verification_success
            and not verified_stop_before_final_publish_success
        ):
            _record_failure(f"{platform} 发布失败: {status}")
            strict_contract_reasons.append(f"terminal_status:{status}")
            terminal_failure = True
        elif (
            status not in expected_statuses
            and not bound_receipt_verification_success
            and not verified_stop_before_final_publish_success
        ):
            if fresh_draft_prepare_mode and _is_release_in_progress_status(status):
                pass
            elif (
                status == "submitted"
                and (
                    "content_plan_fill_gaps_pending" in strict_contract_reasons
                    or "submitted_content_plan_fill_gaps_pending" in strict_contract_reasons
                )
            ):
                _record_failure(f"{platform} 提交态关键字段回填待补全（{status}），继续等待平台回执与发布页核验。")
                strict_contract_reasons.append("submitted_content_plan_fill_gaps_pending")
            elif (
                status == "submitted"
                and (
                    "response_payload_unverified" in strict_contract_reasons
                    or "submitted_response_payload_unverified" in strict_contract_reasons
                    or "submitted_response_payload_empty_snapshot" in strict_contract_reasons
                )
            ):
                _record_failure(
                    f"{platform} 进入提交态但 response_payload 未核验完成，继续等待发布页核验结果。",
                )
            elif _is_release_in_progress_status(status):
                _record_failure(
                    f"{platform} 处于发布进行态（{status}），等待平台真实回执与链接回读完成后再进入终态判定。"
                )
                if strict_contract_reasons:
                    strict_contract_reasons.append("status_in_progress")
            else:
                _record_failure(f"{platform} 进入非预期状态: {status}")
                platform_ready[platform] = False
                strict_contract_reasons.append(f"unexpected_status:{status}")

        is_strict_ready_status = (
            bound_receipt_verification_success
            or verified_stop_before_final_publish_success
            or (fresh_draft_prepare_mode and (_is_release_in_progress_status(status) or status == "draft_created"))
            or (status in expected_statuses and (not _is_release_in_progress_status(status) or status == "scheduled_pending"))
        )
        request_snapshot_plan_match_for_ready = bool(request_snapshot_plan_match)
        if (
            is_stable
            and status in PUBLICATION_SUCCESS_STATUSES
            and request_contract_ready
            and request_payload_plan_match
            and expected_signature
            and actual_signature == expected_signature
            and (request_plan_fill_gaps or request_fields_snapshot_missing or not request_fields_snapshot_trusted)
            and "content_plan_fill_gaps_deferred" in strict_contract_reasons
        ):
            request_snapshot_plan_match_for_ready = True
        if is_strict_ready_status:
            stable_plan_field_check = (
                not is_stable
                or bound_receipt_verification_success
                or verified_stop_before_final_publish_success
                or (
                    bool(request_contract_ready)
                    and bool(request_payload_plan_match)
                    and bool(request_snapshot_plan_match_for_ready)
                )
            )
            stable_signature_check = (
                not is_stable
                or bound_receipt_verification_success
                or verified_stop_before_final_publish_success
                or (
                    (not bool(expected_signature) or actual_signature == expected_signature)
                    and (not bool(expected_signature_fields) or bool(signature_field_values))
                    and (not bool(expected_signature_fields) or signature_fields_match)
                )
            )
            stable_audit_verified = (
                not is_stable
                or not (is_stable and isinstance(direct_audit, dict) and direct_audit.get("verified") is False)
            )
            platform_ready[platform] = (
                not (expected_adapter and adapter and expected_adapter != adapter)
                and stable_plan_field_check
                and stable_signature_check
                and stable_audit_verified
                and (not (is_stable and status == "draft_created" and not verified_stop_before_final_publish_success))
                and (not (require_public_url_for_success and not _looks_like_public_url(external_url)))
                and (not (is_stable and status == "scheduled_pending" and scheduled_publish_at and not _normalize(attempt.get("scheduled_at"))))
                and (not is_stable or not duplicate_detected)
                and (not is_stable or request_contract_ready)
                and not _is_auto_recoverable_error_code(_normalize(attempt.get("error_code")), auto_codes)
            )
        if is_stable and is_strict_ready_status and not platform_ready.get(platform, False):
            strict_contract_reasons.append("strict_contract_failed")
        if strict_contract_reasons:
            summary["strict_contract_reasons"] = sorted(set(strict_contract_reasons))
        summary["strict_contract_verified"] = bool(platform_ready.get(platform, False))

    all_succeeded = bool(targets) and all(
        platform_ready.get(platform, False) for platform in targets
    )

    status = "failed" if terminal_failure else ("passed" if all_succeeded else "running")
    return status, failures, platform_summaries, terminal_failure, recoverable_platforms, recoverable_failures


def _build_publication_verification_payload(
    all_attempts: list[dict[str, Any]],
    *,
    expected_platforms: list[str],
    expected_statuses: set[str],
    expected_platform_manifest: dict[str, dict[str, Any]],
    fresh_draft_prepare_mode: bool = False,
) -> tuple[str, list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    status, failures, platform_summaries, _, _, _ = _evaluate_progress(
        all_attempts,
        targets=expected_platforms,
        expected_statuses=expected_statuses,
        expected_platform_manifest=expected_platform_manifest,
        fresh_draft_prepare_mode=fresh_draft_prepare_mode,
    )
    recommendations: list[dict[str, Any]] = []
    for summary in platform_summaries:
        platform = _normalize(summary.get("platform")).lower().replace("_", "-")
        if not platform:
            continue
        if (
            fresh_draft_prepare_mode
            and bool(summary.get("strict_contract_verified"))
            and _normalize(summary.get("status")).lower() in {"draft_created", "processing"}
        ):
            continue
        is_stable = _is_strict_verification_platform(platform) and not fresh_draft_prepare_mode
        recommendations.extend(_build_platform_recovery_recommendations(platform, summary, is_stable=is_stable))
    return status, failures, platform_summaries, recommendations


def _use_single_attempt_execution_mode(*, fresh_draft_prepare_mode: bool) -> bool:
    return bool(fresh_draft_prepare_mode)


def _should_reinvoke_publication_worker(*, single_attempt_execution_mode: bool, worker_invocation_count: int) -> bool:
    if not single_attempt_execution_mode:
        return True
    return worker_invocation_count <= 0


def _should_attempt_recovery_submission(*, single_attempt_execution_mode: bool) -> bool:
    return not single_attempt_execution_mode


def _build_release_gate_recovery_index(
    platform_summaries: list[dict[str, Any]],
    recommendations: list[dict[str, Any]],
    discovery_recommendations: list[dict[str, Any]] | None = None,
    recovery_signals: list[dict[str, Any]] | None = None,
    prepublish_recovery_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issue_counts: dict[str, int] = {}
    strict_reason_counts: dict[str, int] = {}
    operation_counts: dict[str, int] = {}
    discovery_action_counts: dict[str, int] = {}
    discovery_signal_count = 0
    discovery_retryable_count = 0
    discovery_trigger_counts: dict[str, int] = {}
    platform_issue_map: dict[str, list[str]] = {}
    signal_platform_counts: dict[str, int] = {}
    adaptive_reason_counts: dict[str, int] = {}
    signal_platform_last_attempt: dict[str, int] = {}
    prepublish_platform_counts: dict[str, int] = {}
    prepublish_reason_counts: dict[str, int] = {}
    prepublish_event_count = 0
    prepublish_clear_draft_count = 0
    prepublish_force_refresh_count = 0
    prepublish_verify_media_upload_count = 0
    prepublish_wait_confirmation_count = 0
    normalized_recovery_signals = recovery_signals or []
    normalized_discovery_recommendations = discovery_recommendations or []
    normalized_prepublish_recovery_events = prepublish_recovery_events or []
    for recommendation in recommendations:
        platform = _normalize(recommendation.get("platform"))
        issue = _normalize(recommendation.get("issue"))
        if platform:
            platform_issue_map.setdefault(platform, [])
            if issue and issue not in platform_issue_map[platform]:
                platform_issue_map[platform].append(issue)
        if issue:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        for operation in recommendation.get("operations") or []:
            normalized_operation = _normalize(operation)
            if normalized_operation:
                operation_counts[normalized_operation] = operation_counts.get(normalized_operation, 0) + 1
    for platform_summary in platform_summaries:
        platform = _normalize(platform_summary.get("platform"))
        if not platform:
            continue
        for item in platform_summary.get("strict_contract_reasons") or []:
            normalized_item = _normalize(item)
            if normalized_item:
                strict_reason_counts[normalized_item] = strict_reason_counts.get(normalized_item, 0) + 1
    for discovery_item in normalized_discovery_recommendations:
        action = _normalize(discovery_item.get("action"))
        if action:
            discovery_action_counts[action] = discovery_action_counts.get(action, 0) + 1
        platform = _normalize(discovery_item.get("platform"))
        if platform:
            discovery_signal_count += 1
        if bool(discovery_item.get("retryable")):
            discovery_retryable_count += 1
    stable_failures = [
        {
            "platform": platform,
            "issues": [
                item
                for item in (
                    platform_summary.get("strict_contract_reasons")
                    or platform_summary.get("request_field_mismatch_fields")
                    or platform_summary.get("request_payload_field_mismatch_fields")
                    or []
                )
                if _normalize(item)
            ],
            "attempt_status": _normalize(platform_summary.get("status")),
            "field_match": bool(platform_summary.get("field_match")),
            "signature_fields_match": bool(platform_summary.get("signature_fields_match")),
        }
        for platform_summary in platform_summaries
        for platform in [_normalize(platform_summary.get("platform"))]
        if platform and not bool(platform_summary.get("signature_match", False))
            and (platform_summary.get("field_match") is False or platform_summary.get("signature_fields_match") is False)
    ]
    for signal in normalized_recovery_signals:
        platform = _normalize(signal.get("platform"))
        if platform:
            signal_platform_counts[platform] = signal_platform_counts.get(platform, 0) + 1
            signal_platform_last_attempt[platform] = max(
                signal_platform_last_attempt.get(platform, 0),
                _to_non_negative_int(signal.get("attempt_round") or 0) or _to_non_negative_int(signal.get("kb_error_count") or 0),
            )
        trigger = _normalize(signal.get("trigger"))
        if trigger:
            discovery_trigger_counts[trigger] = discovery_trigger_counts.get(trigger, 0) + 1
        if signal.get("discovery_actions"):
            discovery_signal_count += 1
            for action in signal.get("discovery_actions") or []:
                normalized_action = _normalize(action)
                if normalized_action:
                    discovery_action_counts[f"signal:{normalized_action}"] = discovery_action_counts.get(
                        f"signal:{normalized_action}",
                        0,
                    ) + 1
        for reason in signal.get("adaptive_reasons") or []:
            normalized_reason = _normalize(reason)
            if normalized_reason:
                adaptive_reason_counts[normalized_reason] = adaptive_reason_counts.get(normalized_reason, 0) + 1
        if bool(signal.get("discovery_retryable")):
            discovery_retryable_count += 1
    for event in normalized_prepublish_recovery_events:
        platform = _normalize(event.get("platform"))
        if platform:
            prepublish_platform_counts[platform] = prepublish_platform_counts.get(platform, 0) + 1
        prepublish_event_count += 1
        if bool(event.get("clear_draft_context")):
            prepublish_clear_draft_count += 1
        if bool(event.get("force_publish_page_refresh")):
            prepublish_force_refresh_count += 1
        if bool(event.get("verify_media_upload")):
            prepublish_verify_media_upload_count += 1
        if bool(event.get("wait_for_publish_confirmation")):
            prepublish_wait_confirmation_count += 1
        for reason in event.get("reasons") or []:
            normalized_reason = _normalize(reason).lower()
            if normalized_reason:
                prepublish_reason_counts[normalized_reason] = prepublish_reason_counts.get(normalized_reason, 0) + 1
    return {
        "platform_issue_map": platform_issue_map,
        "issue_counts": issue_counts,
        "operation_counts": operation_counts,
        "strict_reason_counts": strict_reason_counts,
        "discovery_action_counts": discovery_action_counts,
        "discovery_signal_count": discovery_signal_count,
        "discovery_retryable_count": discovery_retryable_count,
        "discovery_trigger_counts": discovery_trigger_counts,
        "auto_recoverable_recommendations": len([item for item in recommendations if bool(item.get("auto_remediable"))]),
        "manual_required_recommendations": len([item for item in recommendations if not bool(item.get("auto_remediable"))]),
        "platform_stability_alerts": stable_failures,
        "recovery_signal_count": len(normalized_recovery_signals),
        "recovery_platform_counts": signal_platform_counts,
        "recovery_platform_last_attempt": signal_platform_last_attempt,
        "recovery_adaptive_reasons": adaptive_reason_counts,
        "prepublish_event_count": prepublish_event_count,
        "prepublish_platform_counts": prepublish_platform_counts,
        "prepublish_reason_counts": prepublish_reason_counts,
        "prepublish_clear_draft_count": prepublish_clear_draft_count,
        "prepublish_force_refresh_count": prepublish_force_refresh_count,
        "prepublish_verify_media_upload_count": prepublish_verify_media_upload_count,
        "prepublish_wait_confirmation_count": prepublish_wait_confirmation_count,
    }


def _build_terminal_gate_recommendations(
    *,
    note: str,
    failures: list[str] | None = None,
    duplicate_history_gate: dict[str, Any] | None = None,
    agent_ready: dict[str, Any] | None = None,
    live_check: dict[str, Any] | None = None,
    deduped_platforms: list[str] | None = None,
) -> list[dict[str, Any]]:
    normalized_note = _normalize(note).lower()
    normalized_failures = [str(item).strip() for item in (failures or []) if str(item).strip()]
    recommendations: list[dict[str, Any]] = []

    def _append(platform: str, issue: str, operations: list[str], *, auto_remediable: bool) -> None:
        recommendations.append(
            {
                "platform": _normalize(platform),
                "issue": issue,
                "operations": [str(item).strip() for item in operations if str(item).strip()],
                "auto_remediable": bool(auto_remediable),
            }
        )

    if normalized_note == "duplicate_history_gate_failed":
        groups = (duplicate_history_gate or {}).get("groups") or []
        seen_platforms: set[str] = set()
        if isinstance(groups, list):
            for item in groups:
                if not isinstance(item, dict):
                    continue
                platform = _normalize(item.get("platform")).lower().replace("_", "-")
                if not platform or platform in seen_platforms:
                    continue
                seen_platforms.add(platform)
                _append(
                    platform,
                    "duplicate_history_gate_failed",
                    ["review_duplicate_history", "enable_allow_republish_if_intentional"],
                    auto_remediable=False,
                )
        if not seen_platforms:
            for item in normalized_failures:
                candidate = _normalize(item.split(":", 1)[0]).lower().replace("_", "-")
                if candidate and candidate not in seen_platforms:
                    seen_platforms.add(candidate)
                    _append(
                        candidate,
                        "duplicate_history_gate_failed",
                        ["review_duplicate_history", "enable_allow_republish_if_intentional"],
                        auto_remediable=False,
                    )
        if not seen_platforms:
            _append(
                "",
                "duplicate_history_gate_failed",
                ["review_duplicate_history", "enable_allow_republish_if_intentional"],
                auto_remediable=False,
            )
    elif normalized_note == "preflight_failed":
        if not bool((agent_ready or {}).get("ready")):
            _append(
                "",
                "browser_agent_not_ready",
                ["restore_browser_agent", "rerun_preflight"],
                auto_remediable=True,
            )
        if not bool(((live_check or {}).get("cdp") or {}).get("connected")):
            _append(
                "",
                "cdp_unreachable",
                ["restore_cdp_session", "rerun_preflight"],
                auto_remediable=True,
            )
        missing_tabs: list[str] = []
        platform_checks = ((live_check or {}).get("cdp") or {}).get("platform_checks") or {}
        if isinstance(platform_checks, dict):
            missing_tabs = [
                _normalize(platform).lower().replace("_", "-")
                for platform, item in platform_checks.items()
                if _normalize(platform) and (item or {}).get("status") != "found"
            ]
        if not missing_tabs:
            for item in normalized_failures:
                if "缺少目标平台发布页标签" in item:
                    tail = item.split(":", 1)[-1]
                    missing_tabs.extend(
                        [
                            _normalize(part).lower().replace("_", "-")
                            for part in tail.split(",")
                            if _normalize(part)
                        ]
                    )
        for platform in sorted({item for item in missing_tabs if item}):
            _append(
                platform,
                "missing_publish_tab",
                ["open_required_publish_tabs", "rerun_preflight"],
                auto_remediable=True,
            )
    elif normalized_note == "deduped_before_publish":
        for platform in sorted({_normalize(item).lower().replace("_", "-") for item in (deduped_platforms or []) if _normalize(item)}):
            _append(
                platform,
                "deduped_before_publish",
                ["skip_publish", "review_existing_active_or_published_attempts"],
                auto_remediable=False,
            )
        if not recommendations:
            _append(
                "",
                "deduped_before_publish",
                ["skip_publish", "review_existing_active_or_published_attempts"],
                auto_remediable=False,
            )
    elif normalized_note == "missing_platform_packaging":
        _append(
            "",
            "missing_platform_packaging",
            ["regenerate_platform_packaging", "verify_platform_scope"],
            auto_remediable=True,
        )
    elif normalized_note == "profile_requirement_failed":
        _append(
            "",
            "profile_requirement_failed",
            ["bind_target_profile_id", "rerun_release_gate"],
            auto_remediable=False,
        )

    return recommendations


def _build_terminal_publication_verification(
    *,
    note: str,
    plan_contract_checks: list[dict[str, Any]] | None = None,
    platform_manifest: dict[str, Any] | None = None,
    failures: list[str] | None = None,
    duplicate_history_gate: dict[str, Any] | None = None,
    agent_ready: dict[str, Any] | None = None,
    live_check: dict[str, Any] | None = None,
    deduped_platforms: list[str] | None = None,
) -> dict[str, Any]:
    recommendations = _build_terminal_gate_recommendations(
        note=note,
        failures=failures,
        duplicate_history_gate=duplicate_history_gate,
        agent_ready=agent_ready,
        live_check=live_check,
        deduped_platforms=deduped_platforms,
    )
    recovery_index = _build_release_gate_recovery_index(
        platform_summaries=[],
        recommendations=recommendations,
        discovery_recommendations=[],
    )
    return {
        "platform_manifest": platform_manifest or {},
        "plan_contract_checks": plan_contract_checks or [],
        "note": note,
        "summary_status": "passed" if _normalize(note).lower() == "deduped_before_publish" else "failed",
        "platform_summaries": [],
        "recommendations": recommendations,
        "discovery_recommendations": [],
        "recovery_index": recovery_index,
    }


async def _build_release_gate_discovery_recommendations(
    platform_summaries: list[dict[str, Any]],
    *,
    max_targets: int = LLM_DISPATCH_MAX_TARGETS,
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    for summary in platform_summaries:
        if len(recommendations) >= max_targets:
            break
        if not _is_discovery_target(summary):
            continue
        context = _build_publication_failure_context(summary)
        discovery = await _discover_release_issue_with_llm(context)
        if not discovery:
            continue
        recommendations.append(
            {
                **discovery,
                "platform": _normalize(summary.get("platform")),
                "evidence": discovery.get("evidence") or [],
                "context_status": _normalize(summary.get("status")),
                "context_signature": _normalize(summary.get("actual_signature"))
                or _normalize(summary.get("expected_signature")),
                "context_source": _normalize(summary.get("actual_request_fields_snapshot_source")),
            }
        )
    return recommendations


def _extract_discovery_recovery_overrides(
    discovery: dict[str, Any] | None,
    summary: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str], bool, dict[str, Any]]:
    if not isinstance(discovery, dict):
        reason_overrides, reason_actions, reason_retryable = (
            _derive_reason_recovery_plan(summary or {})
            if isinstance(summary, dict)
            else ({}, [], False)
        )
        return reason_overrides, reason_actions, reason_retryable, {}
    actions = discovery.get("next_steps") if isinstance(discovery.get("next_steps"), list) else []
    normalized_actions = [_normalize(item) for item in actions if _normalize(item)]
    recovery_plan = discovery.get("recovery_plan") if isinstance(discovery.get("recovery_plan"), dict) else {}
    normalized_override: dict[str, Any] = {}
    recovery_target: dict[str, Any] = {}
    reason_parts: list[str] = []
    if bool(discovery.get("retryable")):
        reason_parts.append("LLM建议可重试")
    if bool(discovery.get("clear_draft_context")) or bool(recovery_plan.get("clear_draft_context")):
        normalized_override["clear_draft_context"] = True
        reason_parts.append("LLM建议清草稿上下文")
    if bool(discovery.get("force_publish_page_refresh")) or bool(recovery_plan.get("force_publish_page_refresh")):
        normalized_override["force_publish_page_refresh"] = True
        reason_parts.append("LLM建议强制刷新发布页")
    extra_overrides = recovery_plan.get("recovery_overrides") if isinstance(recovery_plan.get("recovery_overrides"), dict) else {}
    if isinstance(extra_overrides, dict):
        for key, value in extra_overrides.items():
            normalized_key = _normalize(key)
            if normalized_key in RECOVERY_BOOL_OVERRIDE_KEYS:
                normalized_override[normalized_key] = _coerce_recovery_bool(value, default=bool(normalized_override.get(normalized_key, False)))
            elif normalized_key == "capture_response_timeout_ms":
                timeout_value = _coerce_recovery_timeout_ms(
                    value,
                    default=None,
                    min_ms=15000,
                    max_ms=180000,
                )
                if timeout_value is not None:
                    normalized_override[normalized_key] = timeout_value
            else:
                if isinstance(value, (bool, int, str)):
                    normalized_override[normalized_key] = value
    if isinstance(summary, dict):
        reason_overrides, reason_actions, reason_retryable = _derive_reason_recovery_plan(summary)
        for key, value in reason_overrides.items():
            normalized_key = _normalize(key)
            if normalized_key in RECOVERY_BOOL_OVERRIDE_KEYS:
                normalized_override[normalized_key] = _coerce_recovery_bool(value, default=bool(normalized_override.get(normalized_key, False)))
            elif normalized_key == "capture_response_timeout_ms":
                timeout_value = _coerce_recovery_timeout_ms(
                    value,
                    default=None,
                    min_ms=15000,
                    max_ms=180000,
                )
                if timeout_value is not None:
                    normalized_override[normalized_key] = timeout_value
            elif normalized_key == "recovery_mode":
                existing_mode = _normalize(normalized_override.get(normalized_key))
                if not existing_mode or existing_mode in {"auto_recover", "draft_reset", "rulebook"}:
                    normalized_override[normalized_key] = value
            elif normalized_key not in normalized_override:
                normalized_override[normalized_key] = value
        normalized_actions = reason_actions + normalized_actions
        reason_retryable = bool(reason_retryable)
        retryable = bool(discovery.get("retryable")) or reason_retryable
    else:
        retryable = bool(discovery.get("retryable"))
    if reason_parts:
        normalized_override["reason_parts"] = reason_parts
    discovery_target_adapter = _normalize_publication_adapter(discovery.get("target_adapter") or recovery_plan.get("target_adapter"))
    if discovery_target_adapter:
        recovery_target["target_adapter"] = discovery_target_adapter
    discovery_target_execution_mode = _normalize_publication_execution_mode(
        discovery.get("target_execution_mode") or recovery_plan.get("target_execution_mode")
    )
    if discovery_target_execution_mode:
        recovery_target["target_execution_mode"] = discovery_target_execution_mode
    discovery_target_overrides = recovery_plan.get("target_platform_specific_overrides") or discovery.get("target_platform_specific_overrides")
    if isinstance(discovery_target_overrides, dict):
        normalized_target_overrides = {
            str(key): value
            for key, value in discovery_target_overrides.items()
            if key is not None and isinstance(value, (str, int, float, bool))
        }
        if normalized_target_overrides:
            recovery_target["target_platform_specific_overrides"] = normalized_target_overrides
    return normalized_override, normalized_actions, retryable, recovery_target


def _merge_recovery_target_platform_overrides(
    current_overrides: Any,
    recovery_overrides: Any,
    target_platform_specific_overrides: Any,
) -> dict[str, Any]:
    merged = dict(recovery_overrides or {}) if isinstance(recovery_overrides, dict) else {}
    if isinstance(target_platform_specific_overrides, dict):
        merged.update(target_platform_specific_overrides)
    if isinstance(current_overrides, dict):
        # The current recovery target is the most specific source of truth.
        # Adaptive/discovery overrides may fill gaps, but must not override an
        # explicitly requested safe recovery mode like receipt_rebind.
        merged.update(current_overrides)
    return merged


async def _run_real_publish_gate(
    browser_agent_base_url: str,
    auth_token: str,
    cdp_url: str,
    publication_adapter: str,
    execution_mode: str,
    media_path: str,
    platforms: list[str],
    target_profile_ids: list[str],
    timeout: int,
    poll_interval: int,
    max_wait_seconds: int,
    require_tabs: bool,
    expected_status: str,
    platform_adapters: dict[str, str] | None = None,
    platform_execution_modes: dict[str, str] | None = None,
    visibility_mode: str = "",
    x_share_link: str = "",
    allow_republish: bool = False,
    x_mode: str = "link_share",
    allow_anonymous_profile: bool = False,
    *,
    auto_recover_codes: set[str],
    max_recoveries_per_platform: int,
    content_suffix: str,
    platform_packaging: dict[str, dict[str, Any]] | None = None,
    platform_packaging_scope: dict[str, list[str]] | None = None,
    folder_path: str = "",
    recovery_knowledge_base_path: str = DEFAULT_RECOVERY_KNOWLEDGE_BASE_PATH,
    worker_call_timeout: int = 60,
) -> dict[str, Any]:
    post_x_status = "not_applicable"
    duplicate_history_gate: dict[str, Any] = {
        "status": "not_run",
        "failures": [],
        "allow_republish": bool(allow_republish),
    }
    expected_statuses = _expected_statuses(expected_status)
    normalized_x_mode = _normalize_publication_execution_mode(x_mode)
    if normalized_x_mode not in {"video", "link_share"}:
        normalized_x_mode = "link_share"
    normalized_platform_execution_modes = {
        _normalize(key).lower().replace("_", "-"): _normalize_publication_execution_mode(value)
        for key, value in (platform_execution_modes or {}).items()
        if _normalize(key) and _normalize_publication_execution_mode(value)
    }
    if normalized_platform_execution_modes.get("x") in {"video", "link_share"}:
        normalized_x_mode = normalized_platform_execution_modes.get("x")
    requested_platforms = list(platforms)
    effective_platforms = list(platforms)
    stale_draft_platforms: set[str] = set()
    stale_refresh_platforms: set[str] = set()
    prepublish_draft_signals: dict[str, dict[str, Any]] = {}
    prepublish_recovery_events: list[dict[str, Any]] = []
    deduped_platforms: list[str] = []
    all_plan_contract_checks: list[dict[str, Any]] = []
    recovery_knowledge_base = _load_recovery_knowledge_base(recovery_knowledge_base_path)
    normalized_media_for_dedupe = _canonical_media_path(media_path) or media_path
    normalized_packaging = platform_packaging or {}
    normalized_packaging_scope = platform_packaging_scope if isinstance(platform_packaging_scope, dict) else {}
    required_platform_packaging = {
        _normalize(platform).lower().replace("_", "-")
        for platform in requested_platforms
        if _normalize(platform)
    }
    missing_platform_packaging = sorted(
        {platform for platform in required_platform_packaging if platform not in normalized_packaging}
    )
    requested_packaging_scope = {
        _normalize(item).lower().replace("_", "-")
        for item in (normalized_packaging_scope.get("requested_platforms") or [])
        if _normalize(item)
    }
    profile_requirements_failures = _collect_profile_requirements_violations(
        target_profile_ids=target_profile_ids,
        requested_platforms=requested_platforms,
        allow_anonymous_profile=allow_anonymous_profile,
    )
    if profile_requirements_failures:
        _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)
        return {
            "generated_at": _now(),
            "status": "failed",
            "plan_contract_checks": all_plan_contract_checks,
            "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
            "expected_statuses": sorted(expected_statuses),
            "visibility_mode": _normalize(visibility_mode) or "public",
            "browser_agent_base_url": browser_agent_base_url,
            "cdp_url": cdp_url,
            "media_path": str(media_path),
            "platforms": effective_platforms,
                "requested_platforms": requested_platforms,
                "deduped_platforms": deduped_platforms,
                "stale_draft_platforms": sorted(stale_draft_platforms),
                "stale_refresh_platforms": sorted(stale_refresh_platforms),
                "prepublish_draft_signals": prepublish_draft_signals,
                "prepublish_recovery_events": prepublish_recovery_events,
            "post_x_status": post_x_status,
            "target_profile_ids": target_profile_ids,
            "agent_ready": {
                "ready": False,
                "code": "missing_profile_id",
                "message": profile_requirements_failures[0],
            },
            "live_check": {
                "cdp": {"connected": False},
                "platform_checks": {},
            },
"plan": _build_real_release_gate_plan_summary(
                publish_ready=False,
                note="profile_requirement_failed",
            ),
            "attempts": [],
            "executions": [],
            "recovery_signals": [],
            "recovery_events": [],
            "publication_verification": _build_terminal_publication_verification(
                note="profile_requirement_failed",
                plan_contract_checks=all_plan_contract_checks,
                failures=profile_requirements_failures,
            ),
            "failures": profile_requirements_failures,
            "job_id": None,
        }
    preflight_manifest = _build_expected_platform_manifest(
        requested_platforms,
        title=_normalize(Path(media_path).stem or "RoughCut发布素材"),
                description=f"RoughCut 正式发布素材：{_normalize(Path(media_path).stem or 'RoughCut发布素材')}",
                media_path=normalized_media_for_dedupe or media_path,
                content_suffix=content_suffix,
                visibility_mode=visibility_mode,
                x_share_link=x_share_link,
                x_link_share_mode=(normalized_x_mode != "video"),
                platform_packaging=normalized_packaging,
                platform_adapters=platform_adapters,
            )
    if missing_platform_packaging:
        _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)
        return {
            "generated_at": _now(),
            "status": "failed",
            "plan_contract_checks": all_plan_contract_checks,
            "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
            "expected_statuses": sorted(expected_statuses),
            "visibility_mode": _normalize(visibility_mode) or "public",
            "browser_agent_base_url": browser_agent_base_url,
            "cdp_url": cdp_url,
            "media_path": str(media_path),
            "platforms": effective_platforms,
            "requested_platforms": requested_platforms,
            "deduped_platforms": deduped_platforms,
            "stale_draft_platforms": sorted(stale_draft_platforms),
            "stale_refresh_platforms": sorted(stale_refresh_platforms),
            "prepublish_draft_signals": prepublish_draft_signals,
            "prepublish_recovery_events": prepublish_recovery_events,
            "post_x_status": post_x_status,
            "target_profile_ids": target_profile_ids,
            "agent_ready": {
                "ready": True,
                "code": "missing_platform_packaging",
                "message": "发布文案缺失，无法进行真实发布验收。",
            },
            "live_check": {
                "cdp": {"connected": False},
                "platform_checks": {},
            },
"plan": _build_real_release_gate_plan_summary(
                publish_ready=False,
                note="platform_packaging_missing",
            ),
            "publication_verification": _build_terminal_publication_verification(
                note="missing_platform_packaging",
                plan_contract_checks=all_plan_contract_checks,
                failures=(
                    [
                        *[
                            f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {', '.join(normalized_packaging_scope.get('covered_platforms') or sorted(normalized_packaging.keys()))}"
                            for platform in missing_platform_packaging
                            if platform not in requested_packaging_scope
                        ],
                        *(
                            [
                                f"发布文案缺失：未提供以下平台的发布文案: {', '.join(sorted(platform for platform in missing_platform_packaging if platform in requested_packaging_scope))}"
                            ]
                            if any(platform in requested_packaging_scope for platform in missing_platform_packaging)
                            else []
                        ),
                    ]
                    or [f"发布文案缺失：未提供以下平台的发布文案: {', '.join(missing_platform_packaging)}"]
                ),
            ),
            "duplicate_history_gate": duplicate_history_gate,
            "recovery_events": [],
            "recovery_signals": [],
            "attempts": [],
            "executions": [],
            "failures": [
                *[
                    f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {', '.join(normalized_packaging_scope.get('covered_platforms') or sorted(normalized_packaging.keys()))}"
                    for platform in missing_platform_packaging
                    if platform not in requested_packaging_scope
                ],
                *(
                    [
                        f"发布文案缺失：未提供以下平台的发布文案: {', '.join(sorted(platform for platform in missing_platform_packaging if platform in requested_packaging_scope))}"
                    ]
                    if any(platform in requested_packaging_scope for platform in missing_platform_packaging)
                    else []
                ),
            ]
            or [f"发布文案缺失：未提供以下平台的发布文案: {', '.join(missing_platform_packaging)}"],
            "job_id": None,
        }
    fresh_draft_prepare_mode = _is_fresh_draft_prepare_mode(expected_statuses, visibility_mode)
    duplicate_history_gate: dict[str, Any] = {
        "status": "skipped" if fresh_draft_prepare_mode else "not_run",
        "failures": [],
        "groups": [],
        "note": "fresh_draft_prepare_mode_skips_duplicate_history_gate" if fresh_draft_prepare_mode else "",
    }
    if not fresh_draft_prepare_mode:
        duplicate_history_gate = await build_duplicate_history_gate_report(
            material_payload=normalized_packaging,
            media_path=media_path,
            target_platforms=requested_platforms,
            target_profile_ids=target_profile_ids,
            allow_republish=allow_republish,
            allow_material_creator_profile_fallback=bool(target_profile_ids),
        )
        if duplicate_history_gate.get("status") == "failed":
            _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)
            return {
                "generated_at": _now(),
                "status": "failed",
                "plan_contract_checks": all_plan_contract_checks,
                "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
                "expected_statuses": sorted(expected_statuses),
                "visibility_mode": _normalize(visibility_mode) or "public",
                "browser_agent_base_url": browser_agent_base_url,
                "cdp_url": cdp_url,
                "media_path": str(media_path),
                "platforms": effective_platforms,
                "requested_platforms": requested_platforms,
                "deduped_platforms": deduped_platforms,
                "stale_draft_platforms": sorted(stale_draft_platforms),
                "stale_refresh_platforms": sorted(stale_refresh_platforms),
                "prepublish_draft_signals": prepublish_draft_signals,
                "prepublish_recovery_events": prepublish_recovery_events,
                "post_x_status": post_x_status,
                "target_profile_ids": target_profile_ids,
                "agent_ready": {
                    "ready": True,
                    "code": "duplicate_history_gate_failed",
                    "message": "命中历史重复发布风险，真实发布在入口处被阻断。",
                },
                "live_check": {
                    "cdp": {"connected": False},
                    "platform_checks": {},
                },
    "plan": _build_real_release_gate_plan_summary(
                    publish_ready=False,
                    note="duplicate_history_gate_failed",
                ),
                "publication_verification": _build_terminal_publication_verification(
                    note="duplicate_history_gate_failed",
                    plan_contract_checks=all_plan_contract_checks,
                    failures=list(duplicate_history_gate.get("failures") or []),
                    duplicate_history_gate=duplicate_history_gate,
                ),
                "duplicate_history_gate": duplicate_history_gate,
                "recovery_events": [],
                "recovery_signals": [],
                "attempts": [],
                "executions": [],
                "failures": list(duplicate_history_gate.get("failures") or []),
                "job_id": None,
            }
    preflight_expected_signatures = {
        platform: _normalize(entry.get("content_signature"))
        for platform, entry in preflight_manifest.items()
        if _normalize(platform) and _normalize(entry.get("content_signature"))
    }
    stale_active_ttl_seconds = max(180, int(max_wait_seconds))
    session_factory = get_session_factory()

    async with get_session_factory()() as dedupe_session:
        if not fresh_draft_prepare_mode:
            prepublish_draft_signals = await _collect_prepublish_draft_candidates(
                session=dedupe_session,
                media_path=media_path,
                platforms=effective_platforms,
                expected_platform_manifest=preflight_manifest,
                stale_active_ttl_seconds=stale_active_ttl_seconds,
            )
            for platform, signal in prepublish_draft_signals.items():
                prepublish_signature, prepublish_kb_entry, attempt_count = _record_prepublish_recovery_signal(
                    recovery_knowledge_base,
                    platform=platform,
                    signal=signal,
                )
                signal["signature"] = prepublish_signature
                signal["signature_text"] = _normalize(prepublish_kb_entry.get("signature_text"))
                signal["history_count"] = int(attempt_count or 0)
                signal["kb_count"] = int(prepublish_kb_entry.get("count") or 0)
                adaptive_reasons: list[str] = []
                if attempt_count > 1 and not bool(signal.get("force_publish_page_refresh")):
                    signal["force_publish_page_refresh"] = True
                    adaptive_reasons.append("prepublish_history_count>1")
                if bool(signal.get("clear_draft_context")):
                    stale_draft_platforms.add(platform)
                if bool(signal.get("force_publish_page_refresh")):
                    stale_refresh_platforms.add(platform)
                prepublish_recovery_events.append(
                    {
                        "timestamp": _now(),
                        "platform": platform,
                        "signature": prepublish_signature,
                        "signature_text": _normalize(prepublish_kb_entry.get("signature_text")),
                        "history_count": int(attempt_count or 0),
                        "attempt_count": int(prepublish_kb_entry.get("count") or 0),
                        "kb_entry_id": signal.get("signature") or prepublish_signature,
                        "reasons": list(signal.get("reasons") or []),
                        "error_code": _normalize(signal.get("error_code")),
                        "status": _normalize(signal.get("status")),
                        "snapshot_source": _normalize(signal.get("snapshot_source")),
                        "snapshot_count": _to_non_negative_int(signal.get("snapshot_count") or 0),
                        "clear_draft_context": bool(signal.get("clear_draft_context")),
                        "force_publish_page_refresh": bool(signal.get("force_publish_page_refresh")),
                        "verify_media_upload": bool(signal.get("verify_media_upload")),
                        "wait_for_publish_confirmation": bool(signal.get("wait_for_publish_confirmation")),
                        "capture_response_timeout_ms": _to_non_negative_int(signal.get("capture_response_timeout_ms")),
                        "adaptive_reasons": adaptive_reasons,
                    }
                )
            _stale_runtime_context_platforms, runtime_context_reasons = await _platforms_with_recent_failure_context(
                session=dedupe_session,
                media_path=media_path,
                platforms=effective_platforms,
                stale_active_ttl_seconds=stale_active_ttl_seconds,
            )
            stale_refresh_platforms.update(_stale_runtime_context_platforms)
            for _platform, _reasons in sorted(runtime_context_reasons.items()):
                runtime_flags = _runtime_context_recovery_flags(_reasons)
                if bool(runtime_flags.get("clear_draft_context")):
                    stale_draft_platforms.add(_platform)
                prepublish_recovery_events.append(
                    {
                        "timestamp": _now(),
                        "platform": _platform,
                        "signature": "",
                        "signature_text": "",
                        "history_count": 0,
                        "attempt_count": 0,
                        "kb_entry_id": "",
                        "reasons": [f"runtime_context:{item}" for item in sorted(set(_normalize(item) for item in _reasons if _normalize(item)))],
                        "error_code": "",
                        "status": "runtime_context",
                        "snapshot_source": "runtime_db",
                        "snapshot_count": 0,
                        "clear_draft_context": bool(runtime_flags.get("clear_draft_context")),
                        "force_publish_page_refresh": bool(runtime_flags.get("force_publish_page_refresh")),
                        "adaptive_reasons": [f"runtime_context_detected:{_platform}"],
                    }
                )
        prepublish_platform_recovery_hints: dict[str, dict[str, Any]] = {}
        for platform, signal in prepublish_draft_signals.items():
            platform_hint: dict[str, Any] = {
                "clear_draft_context": bool(signal.get("clear_draft_context")),
                "force_publish_page_refresh": bool(signal.get("force_publish_page_refresh")),
                "verify_media_upload": bool(signal.get("verify_media_upload")),
                "wait_for_publish_confirmation": bool(signal.get("wait_for_publish_confirmation")),
            }
            timeout = _to_non_negative_int(signal.get("capture_response_timeout_ms"))
            if timeout:
                platform_hint["capture_response_timeout_ms"] = timeout
            if any(platform_hint.values()):
                prepublish_platform_recovery_hints[platform] = {key: value for key, value in platform_hint.items() if _normalize(key) and value not in (0, "", False)}
        if not allow_republish and not fresh_draft_prepare_mode:
            dedupe_targets = [
                _platform
                for _platform in effective_platforms
                if _platform not in stale_draft_platforms
                and _platform not in stale_refresh_platforms
            ]
            deduped_platforms = sorted(
                await _published_platforms_for_media(
                    session=dedupe_session,
                    media_path=media_path,
                    platforms=dedupe_targets,
                    expected_platform_signatures=preflight_expected_signatures,
                    expected_platform_manifest=preflight_manifest,
                    dedupe_active_ttl_seconds=stale_active_ttl_seconds,
                )
            )
            effective_platforms = [platform for platform in requested_platforms if platform not in deduped_platforms]
    if not effective_platforms:
            _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)
            return {
                "generated_at": _now(),
                "status": "passed",
                "plan_contract_checks": all_plan_contract_checks,
                "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
                "expected_statuses": sorted(expected_statuses),
                "visibility_mode": _normalize(visibility_mode) or "public",
                "browser_agent_base_url": browser_agent_base_url,
                "cdp_url": cdp_url,
                "media_path": str(media_path),
                "platforms": effective_platforms,
                "requested_platforms": requested_platforms,
                "deduped_platforms": deduped_platforms,
                "stale_draft_platforms": sorted(stale_draft_platforms),
                "stale_refresh_platforms": sorted(stale_refresh_platforms),
                "prepublish_draft_signals": prepublish_draft_signals,
                "prepublish_recovery_events": prepublish_recovery_events,
                "post_x_status": post_x_status,
                "target_profile_ids": target_profile_ids,
                "agent_ready": {
                        "ready": True,
                        "code": "dedupe_only",
                        "message": "该素材在目标平台已存在已发布/已提交/处理中/预约状态结果，已按去重策略直接跳过。",
                    },
                "live_check": {
                    "cdp": {"connected": False},
                    "platform_checks": {},
                },
                "plan": _build_real_release_gate_plan_summary(
                    publish_ready=False,
                    note="deduped_before_publish",
                ),
                "publication_verification": _build_terminal_publication_verification(
                    note="deduped_before_publish",
                    plan_contract_checks=all_plan_contract_checks,
                    deduped_platforms=deduped_platforms,
                ),
                "recovery_signals": [],
                "attempts": [],
                "recovery_events": [],
                "executions": [],
                "failures": [],
                "job_id": None,
            }
    readiness_timeout = max(int(timeout or 0), 30)
    agent_ready = await check_publication_browser_agent_ready(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=auth_token,
        target_platforms=_browser_agent_ready_target_platforms(
            effective_platforms=effective_platforms,
            fresh_draft_prepare_mode=fresh_draft_prepare_mode,
        ),
        target_profile_ids=target_profile_ids,
        request_timeout_sec=readiness_timeout,
        require_live_publish=not fresh_draft_prepare_mode,
    )

    if fresh_draft_prepare_mode:
        live_check = _build_fresh_draft_prepare_live_check(agent_ready)
    else:
        live_check = await _run_checks(
            browser_agent_base_url=browser_agent_base_url,
            auth_token=auth_token,
            cdp_url=cdp_url,
            platforms=effective_platforms,
            target_profile_ids=target_profile_ids,
            request_timeout_sec=readiness_timeout,
        )

    preflight_failures: list[str] = []
    if not bool(agent_ready.get("ready")):
        preflight_failures.append(f"browser-agent 未就绪: {agent_ready.get('code')} {agent_ready.get('message')}")
    else:
        preflight_failures.extend(_validate_authoritative_publication_browser_runtime(agent_ready))
    if not bool(live_check.get("cdp", {}).get("connected")):
        preflight_failures.append("CDP 不可达")
    if require_tabs and not fresh_draft_prepare_mode:
        platform_checks = live_check.get("cdp", {}).get("platform_checks") or {}
        missing = [platform for platform, item in platform_checks.items() if (item or {}).get("status") != "found"]
        if missing:
            preflight_failures.append(f"缺少目标平台发布页标签: {', '.join(missing)}")
    if preflight_failures:
        _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)
        return {
            "generated_at": _now(),
            "status": "failed",
            "browser_agent_base_url": browser_agent_base_url,
            "cdp_url": cdp_url,
            "plan_contract_checks": all_plan_contract_checks,
            "media_path": str(media_path),
            "platforms": effective_platforms,
            "requested_platforms": requested_platforms,
            "deduped_platforms": deduped_platforms,
            "stale_draft_platforms": sorted(stale_draft_platforms),
            "stale_refresh_platforms": sorted(stale_refresh_platforms),
            "prepublish_draft_signals": prepublish_draft_signals,
            "prepublish_recovery_events": prepublish_recovery_events,
            "post_x_status": post_x_status,
            "target_profile_ids": target_profile_ids,
            "agent_ready": agent_ready,
            "live_check": live_check,
            "expected_statuses": sorted(expected_statuses),
            "failures": preflight_failures,
            "executions": [],
            "attempts": [],
            "recovery_signals": [],
            "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
            "publication_verification": _build_terminal_publication_verification(
                note="preflight_failed",
                plan_contract_checks=all_plan_contract_checks,
                failures=preflight_failures,
                agent_ready=agent_ready,
                live_check=live_check,
            ),
        }

    session_factory = get_session_factory()
    media_path_for_job = _canonical_media_path(media_path)
    if not media_path_for_job:
        media_path_for_job = media_path

    async with session_factory() as session:
        try:
            settings = get_settings()
            job = Job(
                source_path=str(media_path_for_job),
                source_name=Path(media_path).name,
                status="done",
                workflow_template="intelligent_publish",
                workflow_mode=_normalize(getattr(settings, "default_job_workflow_mode", "standard_edit")),
                language="zh-CN",
            )
            session.add(job)
            await session.flush()
            created_job_id = str(job.id)
            all_attempts: list[dict[str, Any]] = []
            all_recovery_events: list[dict[str, Any]] = []
            all_executions: list[dict[str, Any]] = []
            all_failures: list[str] = []
            all_created_attempts: list[str] = []
            all_expected_platform_manifests: list[dict[str, dict[str, Any]]] = []
            all_recovery_signals: list[dict[str, Any]] = []

            async def _run_batch(platforms_for_batch: list[str], use_x_adapter: bool) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]], list[str], list[dict[str, Any]], str]:
                if not platforms_for_batch:
                    return "passed", [], [], [], [], "skipped"
                x_adapter = "x_link_share" if use_x_adapter else ""
                batch_publication_adapter = x_adapter or publication_adapter
                batch_execution_mode = "link_share" if use_x_adapter else execution_mode
                x_effective_mode = normalized_x_mode if use_x_adapter else None
                canonical_media_for_batch = _canonical_media_path(media_path) or _normalize(media_path)
                platform_packaging = _build_platform_packaging(
                    platforms_for_batch,
                    content_suffix=content_suffix,
                    media_path=media_path,
                    platform_packaging=normalized_packaging,
                    allow_prepare_without_publish_ready=fresh_draft_prepare_mode,
                )
                creator_profile = _build_creator_profile(
                    platforms_for_batch,
                    target_profile_ids,
                    publication_adapter=batch_publication_adapter,
                    execution_mode=batch_execution_mode,
                    attached_profile_binding=agent_ready.get("attached_profile_binding") if isinstance(agent_ready, dict) else None,
                    allow_anonymous_profile=allow_anonymous_profile,
                    platform_adapters=platform_adapters,
                    platform_execution_modes=normalized_platform_execution_modes,
                    x_publication_adapter=batch_publication_adapter if use_x_adapter else None,
                    x_execution_mode=x_effective_mode,
                )
                scheme_platform_options = {}
                if not fresh_draft_prepare_mode:
                    scheme_platform_options = await _resolve_scheme_platform_options(
                        job=job,
                        render_output=SimpleNamespace(output_path=str(media_path)),
                        platform_packaging=platform_packaging,
                        creator_profile=creator_profile,
                        requested_platforms=platforms_for_batch,
                        folder_path=folder_path,
                        force_probe=bool(
                            set(platforms_for_batch)
                            & (
                                set(stale_draft_platforms)
                                | set(stale_refresh_platforms)
                                | set(prepublish_platform_recovery_hints.keys())
                            )
                        ),
                    )
                effective_platform_options = _build_platform_options(
                    platforms_for_batch,
                    visibility_mode=visibility_mode,
                    x_share_link=x_share_link,
                    platform_packaging=normalized_packaging,
                    seed_platform_options=scheme_platform_options,
                    stale_draft_platforms=stale_draft_platforms,
                    force_refresh_platforms=stale_refresh_platforms,
                    platform_recovery_hints=prepublish_platform_recovery_hints,
                    allow_republish=allow_republish,
                    fresh_draft_prepare_mode=fresh_draft_prepare_mode,
                )
                batch_manifest = _build_expected_platform_manifest(
                    platforms_for_batch,
                    title=_normalize(Path(media_path).stem or "RoughCut发布素材"),
                    description=f"RoughCut 正式发布素材：{_normalize(Path(media_path).stem or 'RoughCut发布素材')}",
                    media_path=canonical_media_for_batch or media_path,
                    content_suffix=content_suffix,
                    visibility_mode=visibility_mode,
                    x_share_link=x_share_link,
                    x_link_share_mode=use_x_adapter,
                    platform_packaging=normalized_packaging,
                    platform_adapters=platform_adapters,
                    effective_platform_options=effective_platform_options,
                )
                all_expected_platform_manifests.append(batch_manifest)
                plan = build_publication_plan(
                    job=job,
                    render_output=SimpleNamespace(output_path=str(media_path)),
                    platform_packaging=platform_packaging,
                    creator_profile=creator_profile,
                    requested_platforms=platforms_for_batch,
                    platform_options=effective_platform_options,
                    existing_attempts=[],
                )
                if not publication_plan_is_publishable(plan):
                    return (
                        "failed",
                        [],
                        [],
                        [f"发布计划不可执行: {item}" for item in (plan.get("blocked_reasons") or [])],
                        [],
                        "",
                    )
                plan_contract_failures, plan_contract_checks = _build_plan_contract_checks(
                    plan,
                    batch_manifest,
                    media_path=canonical_media_for_batch or media_path,
                    requested_platforms=platforms_for_batch,
                )
                all_plan_contract_checks.extend(plan_contract_checks)
                if plan_contract_failures:
                    return (
                        "failed",
                        [],
                        [],
                        plan_contract_failures,
                        [],
                        "preflight_contract_check",
                    )
                single_attempt_execution_mode = _use_single_attempt_execution_mode(
                    fresh_draft_prepare_mode=fresh_draft_prepare_mode
                )
                submit_result = await submit_publication_attempts(session, plan)
                created_attempts = submit_result.get("created_attempts") or []
                skipped_targets = [
                    item for item in (submit_result.get("skipped_targets") or [])
                    if isinstance(item, dict)
                ]
                active_rebind_targets = [] if single_attempt_execution_mode else _build_active_attempt_receipt_rebind_targets(
                    plan,
                    skipped_targets,
                )
                if active_rebind_targets:
                    active_rebind_plan = {**plan, "targets": active_rebind_targets}
                    active_rebind_submit = await submit_publication_attempts(session, active_rebind_plan)
                    active_rebind_created = [
                        item for item in (active_rebind_submit.get("created_attempts") or [])
                        if isinstance(item, dict)
                    ]
                    if active_rebind_created:
                        created_attempts.extend(active_rebind_created)
                    active_rebind_skipped = [
                        item for item in (active_rebind_submit.get("skipped_targets") or [])
                        if isinstance(item, dict)
                    ]
                    if active_rebind_skipped:
                        skipped_targets.extend(active_rebind_skipped)
                if not created_attempts:
                    return (
                        "failed",
                        [],
                        [],
                        ["提交发布任务失败：未创建 publication attempt"],
                        [],
                        "",
                    )
                partial_failures = _build_partial_created_attempt_failures(
                    platforms_for_batch,
                    created_attempts,
                    skipped_targets,
                )
                created_platforms_for_batch = [
                    _normalize(item.get("platform")).lower().replace("_", "-")
                    for item in created_attempts
                    if isinstance(item, dict) and _normalize(item.get("platform"))
                ]
                created_platforms_for_batch = [
                    platform
                    for platform in platforms_for_batch
                    if platform in created_platforms_for_batch
                ]
                if not created_platforms_for_batch:
                    return (
                        "failed",
                        [],
                        [],
                        partial_failures or ["提交发布任务失败：未创建 publication attempt"],
                        [],
                        "partial_attempt_creation",
                    )
                batch_created_attempt_ids = [item.get("id") for item in created_attempts]
                recovery_quota_by_platform: dict[str, int] = {}
                executions: list[dict[str, Any]] = []
                failures: list[str] = list(partial_failures)
                recoverable_failures: list[str] = []
                platform_state_fingerprint: dict[str, str] = {}
                platform_stagnant_rounds: dict[str, int] = {}
                platform_status_fingerprint: dict[str, str] = {}
                platform_status_stagnant_rounds: dict[str, int] = {}
                stagnant_platforms: set[str] = set()
                max_stagnant_rounds = max(3, int(max_wait_seconds) // 20)
                if max_stagnant_rounds < 4:
                    max_stagnant_rounds = 4
                worker_call_timeout_seconds = max(30, int(worker_call_timeout))
                worker_invocation_count = 0

                start_ts = datetime.now(ZoneInfo("Asia/Shanghai")).timestamp()
                deadline_ts = start_ts + max(30, int(max_wait_seconds))
                while datetime.now(ZoneInfo("Asia/Shanghai")).timestamp() < deadline_ts:
                    worker_timed_out = False
                    if _should_reinvoke_publication_worker(
                        single_attempt_execution_mode=single_attempt_execution_mode,
                        worker_invocation_count=worker_invocation_count,
                    ):
                        try:
                            worker_result = await asyncio.wait_for(
                                run_publication_worker_once(
                                    session,
                                    browser_agent_base_url=browser_agent_base_url,
                                    auth_token=auth_token,
                                    worker_id="publication-release-gate-real",
                                    limit=max(1, len(created_platforms_for_batch)),
                                    lease_seconds=max(60, int(timeout) * 5),
                                    request_timeout_sec=timeout,
                                    target_content_ids=[created_job_id],
                                ),
                                timeout=worker_call_timeout_seconds,
                            )
                            worker_invocation_count += 1
                        except asyncio.TimeoutError:
                            worker_timed_out = True
                            worker_timeout_msg = f"发布执行循环超时（{worker_call_timeout_seconds}s），平台={','.join(platforms_for_batch)}"
                            worker_result = {
                                "status": "timeout",
                                "code": "worker_call_timeout",
                                "message": f"发布执行循环超时（{worker_call_timeout_seconds}s）",
                            }
                            if auto_recover_codes and worker_timeout_msg not in recoverable_failures:
                                recoverable_failures.append(worker_timeout_msg)
                    else:
                        worker_result = {
                            "status": "observe_only",
                            "code": "single_attempt_observe_only",
                            "message": "fresh-draft/current-page 模式只允许一次 worker 触发，后续仅观察当前 attempt。",
                        }
                    await session.commit()
                    batch_attempts = await list_publication_attempts(session, job_id=created_job_id)
                    status, cycle_failures, platform_summaries, terminal_failed, recoverable_platforms, cycle_recoverable_failures = _evaluate_progress(
                        batch_attempts,
                        targets=created_platforms_for_batch,
                        expected_statuses=expected_statuses,
                        expected_platform_manifest=batch_manifest,
                        auto_recover_codes=auto_recover_codes,
                        recovery_quota_by_platform=recovery_quota_by_platform,
                        max_recoveries_per_platform=max_recoveries_per_platform,
                    )
                    executions.append(
                        {
                            "timestamp": _now(),
                            "worker_result": worker_result,
                            "platform_summaries": platform_summaries,
                            "status": status,
                        }
                    )
                    stagnant_platforms = set()
                    for item in platform_summaries:
                        platform = _normalize(item.get("platform")).lower().replace("_", "-")
                        item_status = _normalize(item.get("status"))
                        item_reasons = {
                            _normalize(reason)
                            for reason in (item.get("strict_contract_reasons") or [])
                            if _normalize(reason)
                        }
                        publish_receipt_pending = _is_publish_receipt_pending_summary(item)
                        previous_status_fingerprint = _normalize(platform_status_fingerprint.get(platform))
                        if _is_release_in_progress_status(item_status):
                            if not previous_status_fingerprint or previous_status_fingerprint != item_status:
                                platform_status_fingerprint[platform] = item_status
                                platform_status_stagnant_rounds[platform] = 1
                            else:
                                platform_status_stagnant_rounds[platform] = platform_status_stagnant_rounds.get(platform, 0) + 1
                        else:
                            platform_status_stagnant_rounds[platform] = 0
                        if (
                            item_status not in expected_statuses
                            and not publish_receipt_pending
                            and (
                                "content_plan_fill_gaps_pending" not in item_reasons
                                or platform_status_stagnant_rounds.get(platform, 0) >= max_stagnant_rounds
                            )
                            and platform_status_stagnant_rounds.get(platform, 0) >= max_stagnant_rounds
                        ):
                            stagnant_platforms.add(platform)
                            stall_msg = (
                                f"{platform} 长时间停留在状态 {item_status}（连续 {platform_status_stagnant_rounds.get(platform, 0)} 次未变化），触发草稿清理恢复。"
                            )
                            if auto_recover_codes and stall_msg not in recoverable_failures:
                                recoverable_failures.append(stall_msg)

                        state_fingerprint = "|".join(
                            [
                                item_status,
                                _normalize(item.get("run_status")),
                                _normalize(item.get("provider_status")),
                                _normalize(item.get("error_code")),
                            ]
                        )
                        previous_fingerprint = _normalize(platform_state_fingerprint.get(platform))
                        if _is_release_in_progress_status(item_status) and item_status not in expected_statuses:
                            if not previous_fingerprint or previous_fingerprint != state_fingerprint:
                                platform_state_fingerprint[platform] = state_fingerprint
                                platform_stagnant_rounds[platform] = 1
                            else:
                                platform_stagnant_rounds[platform] = platform_stagnant_rounds.get(platform, 0) + 1
                        else:
                            platform_stagnant_rounds[platform] = 0
                        if (
                            platform_stagnant_rounds.get(platform, 0) >= max_stagnant_rounds
                            and not publish_receipt_pending
                            and "content_plan_fill_gaps_pending" not in item_reasons
                        ):
                            stagnant_platforms.add(platform)
                            stall_msg = (
                                f"{platform} 长时间停留在状态 {item_status}（连续 {platform_stagnant_rounds.get(platform, 0)} 次未变化），触发草稿清理恢复。"
                            )
                            if auto_recover_codes and stall_msg not in recoverable_failures:
                                recoverable_failures.append(stall_msg)
                    if worker_timed_out:
                        for item in platform_summaries:
                            platform = _normalize(item.get("platform")).lower().replace("_", "-")
                            item_status = _normalize(item.get("status"))
                            if platform and item_status not in expected_statuses:
                                stagnant_platforms.add(platform)
                    failures.extend(cycle_failures)
                    if cycle_recoverable_failures:
                        recoverable_failures.extend(cycle_recoverable_failures)
                    if terminal_failed or status == "passed":
                        break
                    if (
                        _should_attempt_recovery_submission(
                            single_attempt_execution_mode=single_attempt_execution_mode
                        )
                        and auto_recover_codes
                        and (recoverable_platforms or stagnant_platforms)
                    ):
                        recoverable_platform_set = set(recoverable_platforms) | stagnant_platforms
                        recovery_targets = []
                        recovery_rounds: dict[str, int] = {}
                        recovery_target_triggers: dict[str, str] = {}
                        recovery_target_signatures: dict[str, str] = {}
                        recovery_target_summaries = { 
                            str(_normalize(item.get("platform")).lower().replace("_", "-")): item
                            for item in platform_summaries
                        }
                        for target in (plan.get("targets") or []):
                            platform = _normalize(target.get("platform")).lower().replace("_", "-")
                            if platform not in recoverable_platform_set:
                                continue
                            if recovery_quota_by_platform.get(platform, 0) >= max_recoveries_per_platform:
                                continue
                            round_no = recovery_quota_by_platform.get(platform, 0) + 1
                            target_summary = recovery_target_summaries.get(platform) or {}
                            discovery_recommendation = await _discover_release_issue_with_llm(
                                _build_publication_failure_context(target_summary)
                            )
                            discovery_overrides, discovery_actions, discovery_retryable, discovery_target = _extract_discovery_recovery_overrides(
                                discovery_recommendation,
                                target_summary,
                            )
                            recovery_overrides = dict(discovery_overrides)
                            target_adapter = _normalize_publication_adapter(discovery_target.get("target_adapter"))
                            target_execution_mode = _normalize_publication_execution_mode(discovery_target.get("target_execution_mode"))
                            target_rejection_reasons: list[str] = []
                            if target_adapter and platform != "x" and target_adapter != "browser_agent":
                                target_rejection_reasons.append(
                                    f"reject_target_adapter(platform={platform}):{target_adapter}->browser_agent"
                                )
                                target_adapter = "browser_agent"
                            if target_execution_mode == "link_share" and platform != "x":
                                target_rejection_reasons.append(
                                    f"reject_target_execution_mode(platform={platform}):link_share->browser_agent"
                                )
                                target_execution_mode = "browser_agent"
                            target_platform_specific_overrides = discovery_target.get("target_platform_specific_overrides")
                            if not isinstance(target_platform_specific_overrides, dict):
                                target_platform_specific_overrides = {}
                            raw_overrides = target.get("platform_specific_overrides")
                            if not isinstance(raw_overrides, dict):
                                raw_overrides = {}
                            trigger = "stalled" if platform in stagnant_platforms else "recoverable_failure"
                            adaptive_signature, knowledge_record, knowledge_count = _record_recovery_signal(
                                recovery_knowledge_base,
                                platform=platform,
                                summary=target_summary,
                                status=_normalize(target_summary.get("status") or target_summary.get("error_code") or "recovery"),
                                discovery_signal={
                                    "discovery_actions": discovery_actions,
                                    "discovery_retryable": bool(discovery_retryable),
                                    "trigger": _normalize(trigger),
                                    "discovery_recommendation": discovery_recommendation,
                                },
                            )
                            adaptive_count = max(round_no, int(knowledge_count))
                            adaptive_overrides, adaptive_reasons = _adaptive_recovery_overrides(
                                platform,
                                attempt_count=adaptive_count,
                                summary=target_summary,
                                default_trigger="auto_recover",
                            )
                            adaptive_reasons.extend(target_rejection_reasons)
                            recovery_overrides = {
                                **adaptive_overrides,
                            }
                            if discovery_overrides:
                                recovery_overrides = {
                                    **adaptive_overrides,
                                    **discovery_overrides,
                                }
                            kb_actions = [item for item in (knowledge_record.get("discovery_actions") or []) if _normalize(item)]
                            for kb_action in kb_actions:
                                normalized_kb_action = _normalize(kb_action)
                                if not normalized_kb_action:
                                    continue
                                if normalized_kb_action == "clear_draft_context":
                                    if _coerce_recovery_bool(adaptive_overrides.get("clear_draft_context"), default=False):
                                        recovery_overrides["clear_draft_context"] = True
                                        adaptive_reasons.append("history_kb: clear_draft_context")
                                elif normalized_kb_action == "force_publish_page_refresh":
                                    recovery_overrides["force_publish_page_refresh"] = True
                                    adaptive_reasons.append("history_kb: force_publish_page_refresh")
                            kb_history_recommendation = knowledge_record.get("discovery_recommendation")
                            if isinstance(kb_history_recommendation, dict):
                                recovery_overrides = _merge_discovery_overrides(recovery_overrides, kb_history_recommendation)
                                if (
                                    isinstance(discovery_recommendation, dict)
                                    and kb_history_recommendation.get("action")
                                    and not discovery_recommendation.get("action")
                                ):
                                    discovery_recommendation["action"] = _normalize(kb_history_recommendation.get("action"))
                            recovery_overrides, override_suppression_reasons = _sanitize_recovery_overrides_for_summary(
                                recovery_overrides,
                                summary=target_summary,
                                default_recovery_mode="auto_recover",
                            )
                            adaptive_reasons.extend(override_suppression_reasons)
                            recovery_recommendation = {
                                "attempt_round": round_no,
                                "source_status": _normalize(
                                    (recovery_target_summaries.get(platform) or {}).get("status")
                                ),
                                "error_code": _normalize((recovery_target_summaries.get(platform) or {}).get("error_code")),
                                "recovery_signature": adaptive_signature,
                                "kb_attempt_count": adaptive_count,
                                "kb_error_count": int(knowledge_record.get("count") or 0),
                                "adaptive_reasons": adaptive_reasons,
                                "discovery_actions": discovery_actions,
                                "discovery_retryable": bool(discovery_retryable),
                                "discovery_recommendation": discovery_recommendation,
                                "trigger": trigger,
                            }
                            recovery_target_triggers[platform] = trigger
                            if adaptive_reasons:
                                recovery_overrides["adaptive_reasons"] = adaptive_reasons
                            if isinstance(knowledge_record, dict):
                                knowledge_record["recovery_overrides"] = {
                                    key: value
                                    for key, value in dict(recovery_overrides).items()
                                    if _normalize(key)
                                    and (
                                        _normalize(key) in {
                                            "clear_draft_context",
                                            "force_publish_page_refresh",
                                            "verification_only_current_page",
                                            "repair_only_current_page",
                                            "prepublish_only_current_page",
                                            "prepare_only_current_page",
                                            "verify_media_upload",
                                            "wait_for_publish_confirmation",
                                            "capture_response_timeout_ms",
                                            "recovery_mode",
                                            "adaptive_reasons",
                                        }
                                        or str(key).startswith("reason")
                                    )
                                }
                                knowledge_record["verify_media_upload"] = _coerce_recovery_bool(
                                    knowledge_record["recovery_overrides"].get("verify_media_upload"), default=False
                                )
                                knowledge_record["wait_for_publish_confirmation"] = _coerce_recovery_bool(
                                    knowledge_record["recovery_overrides"].get("wait_for_publish_confirmation"), default=False
                                )
                                knowledge_record["capture_response_timeout_ms"] = _coerce_recovery_timeout_ms(
                                    knowledge_record["recovery_overrides"].get("capture_response_timeout_ms"),
                                    default=None,
                                    min_ms=15000,
                                    max_ms=180000,
                                )
                            recovery_target_signatures[platform] = adaptive_signature
                            all_recovery_signals.append(
                                {
                                    "timestamp": _now(),
                                    "platform": platform,
                                    "attempt_round": round_no,
                                    "recovery_signature": adaptive_signature,
                                    "status_hint": _normalize(target_summary.get("status") or target_summary.get("error_code") or "recovery"),
                                    "adaptive_reasons": adaptive_reasons,
                                    "trigger": recovery_recommendation.get("trigger", "auto_recover"),
                                    "kb_error_count": int(knowledge_record.get("count") or 0),
                                    "discovery_retryable": bool(discovery_retryable),
                                    "discovery_actions": discovery_actions,
                                    "recovery_overrides": recovery_overrides,
                                    "discovery_recommendation": discovery_recommendation,
                                }
                            )
                            target_recovery = dict(target)
                            target_recovery["platform_specific_overrides"] = _merge_recovery_target_platform_overrides(
                                raw_overrides,
                                recovery_overrides,
                                target_platform_specific_overrides,
                            )
                            target_recovery.setdefault("platform_specific_overrides", {})
                            target_recovery["platform_specific_overrides"]["next_platform_specific_overrides"] = {
                                "recovery_recommendation": recovery_recommendation,
                            }
                            if target_adapter:
                                target_recovery["adapter"] = target_adapter
                            if target_execution_mode:
                                target_recovery["execution_mode"] = target_execution_mode
                            recovery_targets.append(target_recovery)
                            recovery_rounds[platform] = round_no
                            recovery_quota_by_platform[platform] = recovery_quota_by_platform.get(platform, 0) + 1
                        recovery_plan = {**plan, "targets": recovery_targets}
                        if not recovery_targets:
                            await asyncio.sleep(max(2, int(poll_interval)))
                            continue
                        recovery_submit = await submit_publication_attempts(session, recovery_plan)
                        created_again = recovery_submit.get("created_attempts") or []
                        if created_again:
                            all_recovery_events.append(
                                {
                                    "timestamp": _now(),
                                    "recovered_platforms": [item.get("platform") for item in recovery_targets],
                                    "created_attempt_ids": [item.get("id") for item in created_again],
                                    "rounds": {
                                        item.get("platform"): recovery_rounds.get(
                                            _normalize(item.get("platform")).lower().replace("_", "-"),
                                            0,
                                        )
                                        for item in recovery_targets
                                    },
                                    "recommendations": [
                                        {
                                            "platform": item.get("platform"),
                                            "recovery_round": recovery_rounds.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                0,
                                            ),
                                            "recovery_signature": recovery_target_signatures.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                "",
                                            ),
                                            "trigger": recovery_target_triggers.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                "unknown",
                                            ),
                                        }
                                        for item in recovery_targets
                                    ],
                                }
                            )
                        else:
                            all_recovery_events.append(
                                {
                                    "timestamp": _now(),
                                    "recovered_platforms": [item.get("platform") for item in recovery_targets],
                                    "created_attempt_ids": [],
                                    "plan_status": _normalize(recovery_submit.get("status")),
                                    "error": (
                                        _normalize(recovery_submit.get("message"))
                                        or "恢复提交未创建 publication attempt"
                                    ),
                                    "rounds": {
                                        item.get("platform"): recovery_rounds.get(
                                            _normalize(item.get("platform")).lower().replace("_", "-"),
                                            0,
                                        )
                                        for item in recovery_targets
                                    },
                                    "recommendations": [
                                        {
                                            "platform": item.get("platform"),
                                            "recovery_round": recovery_rounds.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                0,
                                            ),
                                            "recovery_signature": recovery_target_signatures.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                "",
                                            ),
                                            "trigger": recovery_target_triggers.get(
                                                _normalize(item.get("platform")).lower().replace("_", "-"),
                                                "unknown",
                                            ),
                                        }
                                        for item in recovery_targets
                                    ],
                                }
                            )
                            failed_submit_msg = (
                                f"{','.join([item.get('platform') for item in recovery_targets])} 恢复提交未产生新的 attempt，"
                                f"请检查发布计划与 agent 可见字段是否变更（status={_normalize(recovery_submit.get('status'))}, "
                                f"message={_normalize(recovery_submit.get('message')) or '无额外错误信息'}）。"
                            )
                            if failed_submit_msg not in recoverable_failures:
                                recoverable_failures.append(failed_submit_msg)
                        await session.commit()
                    await asyncio.sleep(max(2, int(poll_interval)))

                if not failures:
                    batch_attempts = await list_publication_attempts(session, job_id=created_job_id)
                final_status, final_failures, final_platform_summaries, _, _, final_recoverable_failures = _evaluate_progress(
                    batch_attempts,
                    targets=created_platforms_for_batch,
                    expected_statuses=expected_statuses,
                    expected_platform_manifest=batch_manifest,
                    auto_recover_codes=auto_recover_codes,
                    recovery_quota_by_platform=recovery_quota_by_platform,
                    max_recoveries_per_platform=max_recoveries_per_platform,
                    fresh_draft_prepare_mode=fresh_draft_prepare_mode,
                )
                failures.extend(final_failures)
                if final_recoverable_failures:
                    recoverable_failures.extend(final_recoverable_failures)
                final_state = final_status
                if final_state != "passed":
                    elapsed = int(datetime.now(ZoneInfo("Asia/Shanghai")).timestamp() - start_ts)
                    strict_gap_points: list[str] = []
                    for summary in final_platform_summaries:
                        platform = _normalize(summary.get("platform")).lower().replace("_", "-")
                        if not platform:
                            continue
                        strict_reasons = [
                            _normalize(item)
                            for item in (summary.get("strict_contract_reasons") or [])
                            if _normalize(item)
                        ]
                        if strict_reasons:
                            strict_gap_points.append(
                                f"{platform}(状态={_normalize(summary.get('status')) or 'unknown'},原因={', '.join(sorted(set(strict_reasons)))})"
                            )
                        elif summary.get("strict_contract_verified") is False:
                            strict_gap_points.append(
                                f"{platform}(状态={_normalize(summary.get('status')) or 'unknown'},原因=strict_contract_verified=false)"
                            )
                    if strict_gap_points:
                        failures.append(
                            f"发布链路未达成严格一致性收口：{'; '.join(strict_gap_points)}"
                        )
                    if not final_failures:
                        failures.append(
                            f"发布网关超时（{elapsed}s）：未在 {int(max_wait_seconds)}s 内进入目标状态 {', '.join(sorted(expected_statuses))}"
                        )
                    final_state = "failed"
                else:
                    final_state = "passed"
                if final_state != "passed":
                    for item in recoverable_failures:
                        if item not in failures:
                            failures.append(item)
                return final_state, batch_attempts, executions, failures, batch_created_attempt_ids, platform_packaging.get("publish_ready", False)

            primary_platforms = [platform for platform in effective_platforms if platform != "x"]
            x_platforms = ["x"] if "x" in effective_platforms else []
            primary_status, primary_attempts, primary_executions, primary_failures, primary_created_attempt_ids, _ = await _run_batch(primary_platforms, use_x_adapter=False)
            all_attempts.extend(primary_attempts)
            all_executions.extend(primary_executions)
            all_failures.extend(primary_failures)
            all_created_attempts.extend(primary_created_attempt_ids)
            final_status = "passed"
            if primary_status != "passed":
                final_status = "failed"
            post_x_status = "not_executed"
            if final_status == "passed" and x_platforms:
                if normalized_x_mode != "video" and not x_share_link:
                    all_failures.append("x 转链模式启动时必须指定 --x-share-link 或 --x-share-url。")
                    post_x_status = "precondition_failed"
                else:
                    x_status, x_attempts, x_executions, x_failures, x_created_attempt_ids, _ = await _run_batch(x_platforms, use_x_adapter=(normalized_x_mode != "video"))
                    post_x_status = x_status
                    all_attempts.extend(x_attempts)
                    all_executions.extend(x_executions)
                    all_failures.extend(x_failures)
                    all_created_attempts.extend(x_created_attempt_ids)
            if final_status == "passed" and post_x_status != "not_executed" and post_x_status != "passed":
                all_failures.append("x post-check 未通过；主流程稳定平台发布通过不受影响。")
            strict_verification_platforms = (
                list(effective_platforms)
                if fresh_draft_prepare_mode
                else [platform for platform in effective_platforms if _is_strict_verification_platform(platform)]
            )
            if not strict_verification_platforms:
                strict_verification_platforms = list(effective_platforms)
            all_expected_manifest: dict[str, dict[str, Any]] = {}
            for manifest in all_expected_platform_manifests:
                all_expected_manifest.update(manifest)
            verification_status, verification_failures, final_platform_summaries, verification_recommendations = _build_publication_verification_payload(
                all_attempts,
                expected_platforms=strict_verification_platforms,
                expected_statuses=expected_statuses,
                expected_platform_manifest=all_expected_manifest,
                fresh_draft_prepare_mode=fresh_draft_prepare_mode,
            )
            discovery_recommendations = await _build_release_gate_discovery_recommendations(final_platform_summaries)
            strict_contract_ready_platforms = [
                _normalize(item.get("platform"))
                for item in final_platform_summaries
                if (
                    fresh_draft_prepare_mode
                    or _is_strict_verification_platform(_normalize(item.get("platform")))
                )
                and bool(item.get("strict_contract_verified"))
            ]
            strict_contract_verified_platforms = [
                platform for platform in strict_verification_platforms if platform in strict_contract_ready_platforms
            ]
            recovery_index = _build_release_gate_recovery_index(
                platform_summaries=final_platform_summaries,
                recommendations=verification_recommendations,
                discovery_recommendations=discovery_recommendations,
                recovery_signals=all_recovery_signals,
                prepublish_recovery_events=prepublish_recovery_events,
            )
            if verification_failures:
                for item in verification_failures:
                    if item not in all_failures:
                        all_failures.append(item)
            if final_status == "passed" and verification_status != "passed":
                final_status = verification_status

            strict_required_statuses = (
                sorted(set(expected_statuses) | {"processing"})
                if fresh_draft_prepare_mode
                else sorted(STRICT_VERIFICATION_SUCCESS_STATUSES)
            )
            strict_rule_text = (
                "fresh-draft 准备模式只要求进入平台新稿上传/编辑流；允许 draft_created 或 processing，不要求公开终态。"
                if fresh_draft_prepare_mode
                else "稳定平台需达到公开终态（published/scheduled_pending），计划字段与实际填充字段需逐项一致，且字段快照来源必须可信。"
            )
            final_report = {
                "generated_at": _now(),
                "status": final_status,
                "final_status": final_status,
                "publication_verification": {
                    "strict_platforms": strict_verification_platforms,
                    "strict_required_statuses": strict_required_statuses,
                    "strict_rule": strict_rule_text,
                    "discovery_recommendations": discovery_recommendations,
                    "plan_contract_checks": all_plan_contract_checks,
                    "platform_manifest": all_expected_manifest,
                    "summary_status": verification_status,
                    "strict_contract_platforms": strict_verification_platforms,
                    "contract_verified_platforms": [
                        _normalize(item.get("platform"))
                        for item in final_platform_summaries
                        if _normalize(item.get("platform"))
                        and (
                            fresh_draft_prepare_mode
                            or _is_strict_verification_platform(_normalize(item.get("platform")))
                        )
                        and bool(item.get("strict_contract_verified"))
                    ],
                    "strict_contract_verified_platforms": strict_contract_verified_platforms,
                    "strict_contract_passed": len(strict_contract_verified_platforms) == len(strict_verification_platforms),
                    "recovery_index": recovery_index,
                    "platform_summaries": [
                        _serialize_verification_platform_summary(item)
                        for item in final_platform_summaries
                    ],
                    "recommendations": verification_recommendations,
                },
                "expected_statuses": sorted(expected_statuses),
                "visibility_mode": _normalize(visibility_mode) or "public",
                "publication_adapter": _normalize_publication_adapter(publication_adapter),
                "execution_mode": _normalize_publication_execution_mode(execution_mode),
                "browser_agent_base_url": browser_agent_base_url,
                "cdp_url": cdp_url,
                "media_path": str(media_path),
                "platforms": effective_platforms,
                "requested_platforms": requested_platforms,
                "deduped_platforms": deduped_platforms,
                "stale_draft_platforms": sorted(stale_draft_platforms),
                "stale_refresh_platforms": sorted(stale_refresh_platforms),
                "prepublish_draft_signals": prepublish_draft_signals,
                "prepublish_recovery_events": prepublish_recovery_events,
                "post_x_status": post_x_status,
                "duplicate_history_gate": duplicate_history_gate,
                "target_profile_ids": target_profile_ids,
                "agent_ready": agent_ready,
                "live_check": live_check,
                "plan": _build_real_release_gate_plan_summary(
                    publish_ready=True,
                    created_attempts=all_created_attempts,
                    plan_targets=effective_platforms,
                ),
                "attempts": all_attempts,
                "prepublish_recovery_events": prepublish_recovery_events,
                "recovery_events": all_recovery_events,
                "recovery_signals": all_recovery_signals,
                "recovery_knowledge_base": _summarize_recovery_knowledge_base(recovery_knowledge_base),
                "plan_contract_checks": all_plan_contract_checks,
                "executions": all_executions,
                "failures": all_failures,
                "job_id": created_job_id,
            }
            return final_report
        finally:
            if session.in_transaction():
                await session.rollback()
            _persist_recovery_knowledge_base(recovery_knowledge_base_path, recovery_knowledge_base)


async def main() -> int:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Run reusable real publication execution gate.")
    parser.add_argument("--platform", action="append", default=[], help="target platform (repeatable).")
    parser.add_argument(
        "--target-profile-id",
        action="append",
        default=[],
        help="browser profile id to assert profile reuse for.",
    )
    parser.add_argument(
        "--allow-anonymous-profile",
        action="store_true",
        help="允许未指定 --target-profile-id 运行匿名真实发布（不推荐，默认禁止）。",
    )
    parser.add_argument("--publication-adapter", default="browser_agent", help="publication adapter name for release gate credentials.")
    parser.add_argument(
        "--execution-mode",
        default="browser_agent",
        help="execution mode used when creating publication run records.",
    )
    parser.add_argument("--browser-agent-base-url", default=_normalize(getattr(settings, "publication_browser_agent_base_url", "")))
    parser.add_argument("--auth-token", default=_normalize(getattr(settings, "publication_browser_agent_auth_token", "")))
    parser.add_argument("--cdp-url", default=_normalize(getattr(settings, "publication_browser_cdp_url", "http://127.0.0.1:9222")))
    parser.add_argument("--timeout", type=int, default=12, help="request timeout seconds")
    parser.add_argument(
        "--output",
        default=str(ROOT_DIR / "artifacts" / "publication-real-release-gate.json"),
        help="JSON output path",
    )
    parser.add_argument("--media-path", default="", help="local published media path (must exist).")
    parser.add_argument(
        "--require-tabs",
        action="store_true",
        default=True,
        dest="require_tabs",
        help="在预检与正式发布都要求平台页签存在（默认开启）。",
    )
    parser.add_argument(
        "--no-require-tabs",
        action="store_false",
        dest="require_tabs",
        help="临时关闭发布页签存在性要求。",
    )
    parser.add_argument(
        "--expected-status",
        default="published,scheduled_pending",
        help="expected final status per attempt, separated by comma if multiple.",
    )
    parser.add_argument(
        "--visibility-mode",
        default="",
        choices=["", "draft", "private", "unlisted"],
        help="publish mode for each target platform; default empty means public-like behavior.",
    )
    parser.add_argument(
        "--x-share-link",
        default="",
        help="x 发布时，追加到文本尾部的分享链接（仅 x 生效）",
    )
    parser.add_argument(
        "--x-share-url",
        default="",
        help="alias of --x-share-link.",
    )
    parser.add_argument(
        "--platform-packaging",
        default="",
        help="平台发布文案 JSON 文件（包含 platform_packaging payload 或 platforms 映射）。",
    )
    parser.add_argument(
        "--material-json",
        default="",
        help="可选：smart-copy.json 路径；未显式提供 platform-packaging 时会自动推导 sibling platform-packaging.json。",
    )
    parser.add_argument(
        "--x-mode",
        default="link_share",
        choices=["link_share", "video"],
        help="x 发布模式：link_share=转发链接（推荐），video=按长视频主流程发布（不建议）。",
    )
    parser.add_argument(
        "--platform-adapter",
        action="append",
        default=[],
        help="按平台指定适配器，例如：x=x_link_share 或 douyin=browser_agent。",
    )
    parser.add_argument(
        "--platform-execution-mode",
        action="append",
        default=[],
        help="按平台指定执行模式，例如：x=link_share 或 douyin=video。",
    )
    parser.add_argument(
        "--content-suffix",
        default="",
        help="内容标识后缀（空时按素材路径+版本号自动生成，保持跨次运行稳定）。",
    )
    parser.add_argument(
        "--allow-republish",
        action="store_true",
        help="强制绕过已发布/草稿/预约去重，允许重复发同一素材。",
    )
    parser.add_argument("--max-wait-seconds", type=int, default=240, help="max wait time for worker execution.")
    parser.add_argument(
        "--worker-call-timeout",
        type=int,
        default=60,
        help="单次发布 worker 调用超时（秒），超时会触发恢复候选。",
    )
    parser.add_argument("--poll-interval", type=int, default=5, help="seconds between each worker tick.")
    parser.add_argument(
        "--auto-recover",
        dest="auto_recover",
        action="store_true",
        default=True,
        help="Automatically requeue needs_human failures by supported error code (default on).",
    )
    parser.add_argument(
        "--no-auto-recover",
        dest="auto_recover",
        action="store_false",
        help="Disable auto recovery.",
    )
    parser.add_argument(
        "--auto-recover-codes",
        default=",".join(sorted(AUTO_RECOVERABLE_ERROR_CODES)),
        help="Comma-separated list of error_code values that are considered auto-recoverable.",
    )
    parser.add_argument(
        "--auto-recover-max-rounds",
        type=int,
        default=4,
        help="Max auto-recovery requeue rounds per platform in this run.",
    )
    parser.add_argument(
        "--recovery-knowledge-base",
        default=DEFAULT_RECOVERY_KNOWLEDGE_BASE_PATH,
        help="Recovery knowledge base json path for adaptive retry behavior.",
    )

    args = parser.parse_args()

    platforms = _platforms(args.platform) or _default_platforms()
    target_profile_ids = [_normalize(item) for item in (args.target_profile_id or []) if _normalize(item)]
    browser_agent_base_url = _normalize(args.browser_agent_base_url) or _normalize(
        getattr(settings, "publication_browser_agent_base_url", "")
    )
    publication_adapter = _normalize_publication_adapter(args.publication_adapter)
    execution_mode = _normalize_publication_execution_mode(args.execution_mode)
    cdp_url = _normalize(args.cdp_url) or _normalize(getattr(settings, "publication_browser_cdp_url", "http://127.0.0.1:9222"))
    media_path = _normalize(args.media_path)
    if not media_path:
        print("请提供 --media-path（真实发布执行必须有本地可读素材文件）。")
        return 2
    resolved_media_path = resolve_publication_local_media_path(media_path)
    if resolved_media_path is None:
        print(f"素材文件不存在: {media_path}")
        return 2
    media_path = str(resolved_media_path)
    platform_packaging, platform_packaging_scope, packaging_load_failures = _load_platform_packaging_payload(
        _normalize(args.platform_packaging),
        _normalize(getattr(args, "material_json", "")),
    )
    if packaging_load_failures:
        for item in packaging_load_failures:
            print(item)
        return 2
    platform_adapters = _parse_platform_adapter_overrides(args.platform_adapter or [])
    platform_execution_modes = _parse_platform_execution_mode_overrides(args.platform_execution_mode or [])
    folder_path = ""
    for raw_candidate in (_normalize(getattr(args, "material_json", "")), _normalize(args.platform_packaging)):
        if not raw_candidate:
            continue
        try:
            candidate_path = Path(raw_candidate).expanduser()
            folder_path = str((candidate_path.parent if candidate_path.suffix else candidate_path).resolve())
            break
        except OSError:
            continue

    report = await _run_real_publish_gate(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=_normalize(args.auth_token),
        cdp_url=cdp_url,
        publication_adapter=publication_adapter,
        execution_mode=execution_mode,
        media_path=media_path,
        platforms=platforms,
        target_profile_ids=target_profile_ids,
        timeout=max(3, int(args.timeout or 12)),
        poll_interval=max(2, int(args.poll_interval or 5)),
        max_wait_seconds=max(30, int(args.max_wait_seconds or 240)),
        require_tabs=args.require_tabs,
        expected_status=args.expected_status,
        platform_adapters=platform_adapters,
        platform_execution_modes=platform_execution_modes,
        visibility_mode=args.visibility_mode,
        x_share_link=_normalize(args.x_share_link) or _normalize(args.x_share_url),
        x_mode=_normalize_publication_execution_mode(args.x_mode),
        allow_anonymous_profile=bool(args.allow_anonymous_profile),
        allow_republish=args.allow_republish,
        content_suffix=_suffix_for_release_gate(_normalize(args.content_suffix), media_path),
        platform_packaging=platform_packaging,
        platform_packaging_scope=platform_packaging_scope,
        folder_path=folder_path,
        auto_recover_codes=_normalize_error_codes(args.auto_recover_codes) if args.auto_recover else set(),
        max_recoveries_per_platform=max(1, int(args.auto_recover_max_rounds or 1)),
        recovery_knowledge_base_path=_normalize(args.recovery_knowledge_base),
        worker_call_timeout=max(1, int(args.worker_call_timeout or 60)),
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[{_now()}] publication real release gate status={report.get('status')} output={output_path}")
    if report.get("status") == "passed":
        print("status: passed")
        return 0
    print("status: failed")
    for item in report.get("failures") or []:
        print(f"- {item}")
    return 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

