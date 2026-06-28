from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.config import get_settings  # noqa: E402

try:
    from scripts.run_minimax_publication_cdp_smoke import _run_backend_contract_smoke  # noqa: E402
    from scripts.run_publication_preflight import _resolve_requested_platforms, _run_checks  # noqa: E402
except ModuleNotFoundError:
    from run_minimax_publication_cdp_smoke import _run_backend_contract_smoke  # noqa: E402
    from run_publication_preflight import _resolve_requested_platforms, _run_checks  # noqa: E402


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _normalize_publication_adapter(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_")


def _normalize_publication_execution_mode(value: Any) -> str:
    return str(value or "browser_agent").strip().lower().replace("-", "_") or "browser_agent"


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _coerce_visual_evidence(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    artifact_path = _normalize(payload.get("artifact_path"))
    capture_type = _normalize(payload.get("capture_type"))
    phase = _normalize(payload.get("phase"))
    mime_type = _normalize(payload.get("mime_type"))
    if not any([artifact_path, capture_type, phase, mime_type]):
        return {}
    result: dict[str, Any] = {}
    if artifact_path:
        result["artifact_path"] = artifact_path
    if capture_type:
        result["capture_type"] = capture_type
    if phase:
        result["phase"] = phase
    if mime_type:
        result["mime_type"] = mime_type
    return result


def _coerce_creator_sessions(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    sessions: dict[str, Any] = {}
    for raw_platform, value in payload.items():
        platform = _normalize(raw_platform).lower().replace("_", "-")
        if not platform or not isinstance(value, dict):
            continue
        route = value.get("route") if isinstance(value.get("route"), dict) else {}
        item = {
            "platform": platform,
            "ready": bool(value.get("ready")),
            "status": _normalize(value.get("status")).lower(),
            "code": _normalize(value.get("code")),
            "message": _normalize(value.get("message")),
            "verification_reason": _normalize(value.get("verification_reason")).lower(),
            "route": {
                "url": _normalize(route.get("url")),
                "title": _normalize(route.get("title")),
            },
            "visual_evidence": _coerce_visual_evidence(value.get("visual_evidence")),
        }
        sessions[platform] = item
    return sessions


def _coerce_probe_inventory(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"checked": False, "status": "skipped", "platforms": {}, "failures": []}
    raw_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    platforms: dict[str, Any] = {}
    for raw_platform, value in raw_platforms.items():
        platform = _normalize(raw_platform).lower().replace("_", "-")
        if not platform or not isinstance(value, dict):
            continue
        route = value.get("route") if isinstance(value.get("route"), dict) else {}
        platforms[platform] = {
            "status": _normalize(value.get("status")).lower(),
            "message": _normalize(value.get("message")),
            "route": {
                "url": _normalize(route.get("url")),
                "title": _normalize(route.get("title")),
            },
            "visual_evidence": _coerce_visual_evidence(value.get("visual_evidence")),
            "warnings": [str(item).strip() for item in (value.get("warnings") or []) if str(item).strip()],
        }
    return {
        "checked": bool(payload.get("checked")) if "checked" in payload else bool(platforms),
        "status": _normalize(payload.get("status")),
        "generated_at": _normalize(payload.get("generated_at")),
        "probe_id": _normalize(payload.get("probe_id")),
        "platforms": platforms,
        "failures": [str(item).strip() for item in (payload.get("failures") or []) if str(item).strip()],
    }


def _coerce_packaging_preflight(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"checked": False, "status": "skipped", "platform_checks": {}, "failures": []}
    raw_platform_checks = payload.get("platform_checks") if isinstance(payload.get("platform_checks"), dict) else {}
    platform_checks: dict[str, Any] = {}
    for raw_platform, value in raw_platform_checks.items():
        platform = _normalize(raw_platform).lower().replace("_", "-")
        if not platform or not isinstance(value, dict):
            continue
        item: dict[str, Any] = {
            "status": _normalize(value.get("status")).lower(),
            "message": _normalize(value.get("message")),
        }
        login_url = _normalize(value.get("login_url"))
        if login_url:
            item["login_url"] = login_url
        missing_required_surfaces = [
            str(entry).strip()
            for entry in (value.get("missing_required_surfaces") or [])
            if str(entry).strip()
        ]
        if missing_required_surfaces:
            item["missing_required_surfaces"] = missing_required_surfaces
        blocking_reasons = [str(entry).strip() for entry in (value.get("blocking_reasons") or []) if str(entry).strip()]
        if blocking_reasons:
            item["blocking_reasons"] = blocking_reasons
        platform_checks[platform] = item
    return {
        "checked": bool(payload.get("checked")) if "checked" in payload else bool(platform_checks),
        "status": _normalize(payload.get("status")).lower(),
        "material_json_path": _normalize(payload.get("material_json_path")),
        "platform_packaging_path": _normalize(payload.get("platform_packaging_path")),
        "source": _normalize(payload.get("source")),
        "platform_checks": platform_checks,
        "manual_handoff_targets": list(payload.get("manual_handoff_targets") or []),
        "failures": [str(item).strip() for item in (payload.get("failures") or []) if str(item).strip()],
    }


async def _run_live_release_gate(
    *,
    browser_agent_base_url: str,
    auth_token: str,
    cdp_url: str,
    platforms: list[str],
    target_profile_ids: list[str],
    allow_anonymous_profile: bool = False,
    timeout: int,
    require_tabs: bool,
    material_json: str = "",
    platform_packaging: str = "",
) -> dict[str, Any]:
    if not allow_anonymous_profile and not target_profile_ids:
        return {
            "generated_at": _now(),
            "ready": False,
            "agent_ready": {
                "ready": False,
                "code": "missing_profile_id",
                "message": "发布前置检查默认禁止匿名 profile，需通过 --target-profile-id 指定 fas 账号 profile。"
                " 如必须临时验证，可加 --allow-anonymous-profile。",
            },
            "cdp": {
                "connected": False,
                "tab_count": 0,
                "platform_checks": {},
            },
            "platform_checks": {},
            "requirements": {"require_tabs": require_tabs},
            "failures": ["未提供 --target-profile-id，发布前置检查已拒绝执行。"],
        }
    result = await _run_checks(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=auth_token,
        cdp_url=cdp_url,
        platforms=platforms,
        target_profile_ids=target_profile_ids,
        request_timeout_sec=timeout,
        material_json=material_json,
        platform_packaging=platform_packaging,
    )

    failures: list[str] = []
    failures.extend([str(item).strip() for item in (result.get("failures") or []) if str(item).strip()])
    packaging = _coerce_packaging_preflight(result.get("packaging"))
    live_publish_platforms = [
        _normalize(item).lower().replace("_", "-")
        for item in (result.get("request", {}).get("live_publish_platforms") or [])
        if _normalize(item).lower().replace("_", "-")
    ]
    if not bool(result.get("agent_ready", {}).get("ready")):
        failures.append(
            f"发布服务未就绪: {result.get('agent_ready', {}).get('code')} - {result.get('agent_ready', {}).get('message')}"
        )
    if not bool(result.get("cdp", {}).get("connected")):
        failures.append("CDP 未连接或不可用")
    if require_tabs:
        platform_checks = result.get("cdp", {}).get("platform_checks") or {}
        missing = [
            platform
            for platform in live_publish_platforms
            if (platform_checks.get(platform) or {}).get("status") != "found"
        ]
        if missing:
            failures.append(f"缺少目标平台发布页标签: {', '.join(missing)}")

    return {
        "generated_at": _now(),
        "ready": (
            bool(result.get("agent_ready", {}).get("ready"))
            and bool(result.get("cdp", {}).get("connected"))
            and not failures
        ),
        "agent_ready": {
            "ready": bool(result.get("agent_ready", {}).get("ready")),
            "code": str(result.get("agent_ready", {}).get("code") or ""),
            "message": str(result.get("agent_ready", {}).get("message") or ""),
        },
        "creator_sessions": _coerce_creator_sessions(result.get("agent_ready", {}).get("health", {}).get("creator_sessions")),
        "probe_inventory": _coerce_probe_inventory(result.get("probe_inventory")),
        "packaging": packaging,
        "cdp": result.get("cdp") or {},
        "platform_checks": result.get("cdp", {}).get("platform_checks") or {},
        "requirements": {"require_tabs": require_tabs},
        "failures": failures,
    }


def _evaluate_failure(
    release_check: dict[str, Any],
    backend_smoke: dict[str, Any],
    skip_backend_smoke: bool,
    *,
    contract_success_status: str,
) -> list[str]:
    failures = list(release_check.get("failures") or [])
    if not skip_backend_smoke:
        backend_status = str(backend_smoke.get("status") or "").strip().lower()
        plan_status = str(backend_smoke.get("plan_status") or "").strip().lower()
        plan_blocked_reasons = [
            str(item).strip()
            for item in (backend_smoke.get("plan_blocked_reasons") or [])
            if str(item).strip()
        ]
        if backend_status == "manual_handoff":
            failures.append("发布计划要求人工接管，未达到自动一键发布条件")
        elif backend_status == "blocked":
            failures.extend(plan_blocked_reasons[:5] or ["发布计划未达到 publish_ready"])
        elif backend_status != "passed":
            if plan_status == "manual_handoff" or bool(backend_smoke.get("plan_manual_handoff_ready")):
                failures.append("发布计划要求人工接管，未达到自动一键发布条件")
            elif plan_status == "blocked":
                failures.extend(plan_blocked_reasons[:5] or ["发布计划未达到 publish_ready"])
            else:
                failures.append("后端发布合同烟测未通过")
        elif not bool(backend_smoke.get("plan_publish_ready")):
            failures.extend(plan_blocked_reasons[:5] or ["发布计划未达到 publish_ready"])
        elif not backend_smoke.get("created_attempts"):
            failures.append("后端未产出 publication attempt")
        else:
            attempt_statuses = backend_smoke.get("attempt_statuses") or {}
            for platform, status in attempt_statuses.items():
                if str(status or "").strip() != contract_success_status:
                    failures.append(
                        f"后端合同烟测平台 {platform} 的状态不是预期 {contract_success_status}: {str(status or '').strip() or 'unknown'}"
                    )
    return failures


def _append_release_gate_recommendation(
    recommendations: list[dict[str, Any]],
    seen: set[tuple[str, str, tuple[str, ...], bool]],
    *,
    platform: str = "",
    issue: str,
    operations: list[str],
    auto_remediable: bool,
) -> None:
    normalized_platform = _normalize(platform).lower().replace("_", "-")
    normalized_operations = tuple(
        item for item in [str(value).strip() for value in (operations or [])] if item
    )
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


def _parse_platforms_from_failure_text(text: str) -> list[str]:
    normalized = _normalize(text)
    if not normalized:
        return []
    if ":" in normalized:
        head, _ = normalized.split(":", 1)
        head = _normalize(head).lower().replace("_", "-")
        if head:
            return [head]
    if "缺少目标平台发布页标签" in normalized and ":" in normalized:
        _, tail = normalized.split(":", 1)
        return [
            _normalize(item).lower().replace("_", "-")
            for item in tail.split(",")
            if _normalize(item)
        ]
    return []


def _derive_release_gate_summary_status(
    release_check: dict[str, Any],
    backend_smoke: dict[str, Any],
    *,
    skip_backend_smoke: bool,
    failures: list[str],
) -> str:
    if not failures:
        return "passed"
    if not skip_backend_smoke:
        backend_status = _normalize(backend_smoke.get("status")).lower()
        if backend_status in {"manual_handoff", "blocked"}:
            return backend_status
        plan_status = _normalize(backend_smoke.get("plan_status")).lower()
        if plan_status in {"manual_handoff", "blocked"}:
            return plan_status
    if release_check.get("failures"):
        return "failed"
    return "failed"


def _build_release_gate_recommendations(
    release_check: dict[str, Any],
    backend_smoke: dict[str, Any],
    *,
    skip_backend_smoke: bool,
    requested_platforms: list[str],
) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, tuple[str, ...], bool]] = set()
    normalized_platforms = [
        _normalize(item).lower().replace("_", "-") for item in (requested_platforms or []) if _normalize(item)
    ]

    agent_ready = release_check.get("agent_ready") or {}
    agent_code = _normalize(agent_ready.get("code")).lower()
    if agent_code == "missing_profile_id":
        _append_release_gate_recommendation(
            recommendations,
            seen,
            issue="profile_requirement_failed",
            operations=["bind_target_profile", "rerun_release_gate"],
            auto_remediable=False,
        )

    for failure in [str(item).strip() for item in (release_check.get("failures") or []) if str(item).strip()]:
        lowered = failure.lower()
        if "范围不匹配" in failure or "覆盖范围" in failure or "仅覆盖平台" in failure:
            parsed_platforms = _parse_platforms_from_failure_text(failure) or normalized_platforms
            for platform in parsed_platforms or [""]:
                _append_release_gate_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="platform_scope_mismatch",
                    operations=["regenerate_platform_material", "restrict_requested_platforms"],
                    auto_remediable=True,
                )
        if "browser-agent" in lowered or "cdp" in lowered:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                issue="browser_session_not_ready",
                operations=["restore_browser_agent", "restore_cdp_session", "rerun_release_gate"],
                auto_remediable=False,
            )
        if "缺少目标平台发布页标签" in failure or "tab" in lowered:
            parsed_platforms = _parse_platforms_from_failure_text(failure) or normalized_platforms
            for platform in parsed_platforms or [""]:
                _append_release_gate_recommendation(
                    recommendations,
                    seen,
                    platform=platform,
                    issue="missing_publish_tab",
                    operations=["open_publish_tab", "rerun_release_gate"],
                    auto_remediable=False,
                )

    if skip_backend_smoke:
        return recommendations

    backend_status = _normalize(backend_smoke.get("status")).lower()
    plan_status = _normalize(backend_smoke.get("plan_status")).lower()
    plan_blocked_reasons = [
        str(item).strip()
        for item in (backend_smoke.get("plan_blocked_reasons") or [])
        if str(item).strip()
    ]
    plan_targets = [
        _normalize(item).lower().replace("_", "-")
        for item in (backend_smoke.get("plan_targets") or [])
        if _normalize(item)
    ]
    candidate_platforms = plan_targets or normalized_platforms

    if backend_status == "manual_handoff" or plan_status == "manual_handoff":
        for platform in candidate_platforms or [""]:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                platform=platform,
                issue="manual_handoff_required",
                operations=["open_manual_login", "continue_manual_publish"],
                auto_remediable=False,
            )
        return recommendations

    if backend_status == "blocked" or plan_status == "blocked":
        for platform in candidate_platforms or [""]:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                platform=platform,
                issue="plan_blocked",
                operations=["repair_material_contract", "rerun_backend_smoke"],
                auto_remediable=True,
            )
        return recommendations

    if backend_status not in {"", "passed"}:
        _append_release_gate_recommendation(
            recommendations,
            seen,
            issue="backend_contract_smoke_failed",
            operations=["inspect_publication_plan", "repair_submit_worker_chain", "rerun_backend_smoke"],
            auto_remediable=True,
        )
        return recommendations

    if not bool(backend_smoke.get("plan_publish_ready")):
        for platform in candidate_platforms or [""]:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                platform=platform,
                issue="plan_blocked",
                operations=["repair_material_contract", "rerun_backend_smoke"],
                auto_remediable=True,
            )
        return recommendations

    if not backend_smoke.get("created_attempts"):
        _append_release_gate_recommendation(
            recommendations,
            seen,
            issue="backend_contract_attempt_missing",
            operations=["inspect_publication_plan", "repair_submit_worker_chain", "rerun_backend_smoke"],
            auto_remediable=True,
        )
        return recommendations

    attempt_statuses = backend_smoke.get("attempt_statuses") or {}
    for platform, status in attempt_statuses.items():
        normalized_status = _normalize(status)
        if normalized_status and normalized_status not in {"draft_created", "published", "scheduled_pending"}:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                platform=platform,
                issue="backend_contract_status_mismatch",
                operations=["verify_attempt_contract", "rerun_backend_smoke"],
                auto_remediable=True,
            )
    if plan_blocked_reasons and not recommendations:
        for platform in candidate_platforms or [""]:
            _append_release_gate_recommendation(
                recommendations,
                seen,
                platform=platform,
                issue="plan_blocked",
                operations=["repair_material_contract", "rerun_backend_smoke"],
                auto_remediable=True,
            )
    return recommendations


def _build_release_gate_recovery_index(recommendations: list[dict[str, Any]]) -> dict[str, Any]:
    issue_counts: dict[str, int] = {}
    platform_counts: dict[str, int] = {}
    for recommendation in recommendations:
        issue = _normalize(recommendation.get("issue"))
        platform = _normalize(recommendation.get("platform")).lower().replace("_", "-")
        if issue:
            issue_counts[issue] = int(issue_counts.get(issue) or 0) + 1
        if platform:
            platform_counts[platform] = int(platform_counts.get(platform) or 0) + 1
    return {
        "issue_counts": issue_counts,
        "platform_counts": platform_counts,
        "auto_recoverable_recommendations": len(
            [item for item in recommendations if bool(item.get("auto_remediable"))]
        ),
        "manual_required_recommendations": len(
            [item for item in recommendations if not bool(item.get("auto_remediable"))]
        ),
    }


def _build_release_gate_mitigation(
    failures: list[str],
    recommendations: list[dict[str, Any]],
    *,
    summary_status: str,
) -> dict[str, Any]:
    suggestion_map = {
        "profile_requirement_failed": "检测到 profile 绑定缺失，请显式指定 --target-profile-id 后重跑 release gate。",
        "browser_session_not_ready": "检测到 browser-agent/CDP 会话未就绪，请先恢复浏览器会话后再重跑 release gate。",
        "missing_publish_tab": "检测到目标平台发布页标签缺失，请先打开对应发布页后再重跑 release gate。",
        "platform_scope_mismatch": "检测到目标平台超出本期物料合同覆盖范围，请重生成该平台物料或缩小发布平台范围后再发。",
        "manual_handoff_required": "检测到发布计划要求人工接管，请打开登录页并转入人工发布。",
        "plan_blocked": "检测到发布计划或物料门禁阻断，请先修复 packaging、live_publish_preflight 与缺失字段。",
        "backend_contract_smoke_failed": "检测到后端发布合同烟测失败，请修复计划生成、提交或 worker 链路后再重跑。",
        "backend_contract_attempt_missing": "检测到后端未产出 publication attempt，请先修复计划生成与提交链路后再重跑。",
        "backend_contract_status_mismatch": "检测到后端合同 attempt 状态异常，请先核对 worker 回执合同后再重跑。",
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
            steps.append("检测到发布计划要求人工接管，请打开登录页并转入人工发布。")
            playbook.setdefault("manual_handoff_required", []).extend(["open_manual_login", "continue_manual_publish"])
        elif summary_status == "blocked":
            steps.append("检测到发布计划阻断，请先修复 packaging、live_publish_preflight 与缺失字段后再重跑 release gate。")
            playbook.setdefault("plan_blocked", []).extend(["repair_material_contract", "rerun_backend_smoke"])
        else:
            steps.append("release gate 未通过，请先修复环境、平台页签或后端合同烟测后再重跑。")
            playbook.setdefault("release_gate", []).extend(["inspect_live_gate", "inspect_backend_smoke", "rerun_release_gate"])
    for key, values in playbook.items():
        playbook[key] = sorted({value for value in values if value})
    return {
        "steps": sorted({item for item in steps if item}),
        "playbook": playbook,
    }


def _build_release_gate_publication_verification(
    release_check: dict[str, Any],
    backend_smoke: dict[str, Any],
    *,
    skip_backend_smoke: bool,
    requested_platforms: list[str],
    failures: list[str],
) -> dict[str, Any]:
    summary_status = _derive_release_gate_summary_status(
        release_check,
        backend_smoke,
        skip_backend_smoke=skip_backend_smoke,
        failures=failures,
    )
    recommendations = _build_release_gate_recommendations(
        release_check,
        backend_smoke,
        skip_backend_smoke=skip_backend_smoke,
        requested_platforms=requested_platforms,
    )
    creator_sessions = _coerce_creator_sessions(release_check.get("creator_sessions"))
    creator_session_visual_evidence = {
        platform: dict(item.get("visual_evidence"))
        for platform, item in creator_sessions.items()
        if isinstance(item.get("visual_evidence"), dict) and item.get("visual_evidence")
    }
    probe_inventory = _coerce_probe_inventory(release_check.get("probe_inventory"))
    probe_inventory_visual_evidence = {
        platform: dict(item.get("visual_evidence"))
        for platform, item in (probe_inventory.get("platforms") or {}).items()
        if isinstance(item, dict) and isinstance(item.get("visual_evidence"), dict) and item.get("visual_evidence")
    }
    return {
        "scope": "release_gate",
        "summary_status": summary_status,
        "live_gate_ready": bool(release_check.get("ready")),
        "backend_smoke_status": _normalize(backend_smoke.get("status")).lower() if not skip_backend_smoke else "skipped",
        "creator_sessions": creator_sessions,
        "creator_session_visual_evidence_by_platform": creator_session_visual_evidence,
        "probe_inventory": probe_inventory,
        "probe_inventory_visual_evidence_by_platform": probe_inventory_visual_evidence,
        "recommendations": recommendations,
        "recovery_index": _build_release_gate_recovery_index(recommendations),
    }


def _build_release_gate_report(
    *,
    browser_agent_base_url: str,
    cdp_url: str,
    platforms: list[str],
    target_profile_ids: list[str],
    publication_adapter: str,
    execution_mode: str,
    live_gate: dict[str, Any],
    backend_smoke: dict[str, Any],
    skip_backend_smoke: bool,
    expectation_report: dict[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    status = "passed" if not failures else "failed"
    publication_verification = _build_release_gate_publication_verification(
        live_gate,
        backend_smoke,
        skip_backend_smoke=skip_backend_smoke,
        requested_platforms=platforms,
        failures=failures,
    )
    mitigation = _build_release_gate_mitigation(
        failures,
        publication_verification.get("recommendations") or [],
        summary_status=_normalize(publication_verification.get("summary_status")).lower(),
    )
    return {
        "generated_at": _now(),
        "status": status,
        "browser_agent_base_url": browser_agent_base_url,
        "cdp_url": cdp_url,
        "platforms": platforms,
        "target_profile_ids": target_profile_ids,
        "publication_adapter": publication_adapter,
        "execution_mode": execution_mode,
        "live_gate": live_gate,
        "backend_contract_smoke": backend_smoke,
        "requirement_profile": expectation_report,
        "publication_verification": publication_verification,
        "mitigation": mitigation,
        "suggestions": list(mitigation.get("steps") or []),
        "failures": failures,
    }


def _format_expectation(*, skip_backend_smoke: bool, status_expectation: str, backend_smoke: dict[str, Any]) -> dict[str, Any]:
    return {
        "scope": "backend_contract_simulation",
        "skip_backend_smoke": bool(skip_backend_smoke),
        "contract_expectation": {
            "attempt_status": status_expectation,
            "backend_smoke_fake": bool(not skip_backend_smoke),
            "note": (
                "后端合同烟测使用的是录制回放型假 browser-agent，不会触发真实平台点击。"
                if not skip_backend_smoke
                else "未执行后端合同烟测。"
            ),
            "smoke_status": str(backend_smoke.get("status") or ""),
            "smoke_plan_targets": backend_smoke.get("plan_targets") or [],
        },
    }


async def main() -> int:
    settings = get_settings()

    parser = argparse.ArgumentParser(description="Run reusable release gate for publication readiness.")
    parser.add_argument("--platform", action="append", default=[], help="Target platform for publication check.")
    parser.add_argument(
        "--target-profile-id",
        action="append",
        default=[],
        help="browser profile id to assert profile reuse for.",
    )
    parser.add_argument(
        "--allow-anonymous-profile",
        action="store_true",
        help="允许未指定 --target-profile-id 执行发布准备检查（默认禁止）。",
    )
    parser.add_argument("--publication-adapter", default="browser_agent", help="publication adapter name for backend smoke profile.")
    parser.add_argument("--execution-mode", default="browser_agent", help="execution mode for fake contract attempts.")
    parser.add_argument("--browser-agent-base-url", default=_normalize(getattr(settings, "publication_browser_agent_base_url", ""))
                        .strip())
    parser.add_argument("--auth-token", default=_normalize(getattr(settings, "publication_browser_agent_auth_token", "")))
    parser.add_argument("--cdp-url", default=_normalize(getattr(settings, "publication_browser_cdp_url", "")))
    parser.add_argument("--timeout", type=int, default=12, help="request timeout seconds")
    parser.add_argument(
        "--output",
        default=str(ROOT_DIR / "artifacts" / "publication-release-gate.json"),
        help="optional json output path",
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
    parser.add_argument(
        "--skip-backend-smoke",
        action="store_true",
        help="skip backend contract smoke that validates publish task assembly/worker contract.",
    )
    parser.add_argument(
        "--material-json",
        default="",
        help="可选：smart-copy.json 路径；用于 backend smoke 推导真实 platform-packaging。",
    )
    parser.add_argument(
        "--platform-packaging",
        default="",
        help="可选：真实 platform-packaging.json 路径；backend smoke 优先使用该合同，而不是 fixture。",
    )
    parser.add_argument(
        "--fake-agent-status",
        default="draft_created",
        choices=["draft_created", "published", "scheduled_pending"],
        help="contract smoke expected terminal status from fake browser-agent.",
    )
    parser.add_argument(
        "--contract-success-status",
        default="draft_created",
        choices=["draft_created", "published", "scheduled_pending"],
        help="expected terminal status for each backend contract attempt.",
    )

    args = parser.parse_args()

    browser_agent_base_url = _normalize(args.browser_agent_base_url) or _normalize(
        getattr(settings, "publication_browser_agent_base_url", "")
    )
    publication_adapter = _normalize_publication_adapter(args.publication_adapter)
    execution_mode = _normalize_publication_execution_mode(args.execution_mode)
    cdp_url = _normalize(args.cdp_url) or _normalize(
        getattr(settings, "publication_browser_cdp_url", "http://127.0.0.1:9222")
    )

    platforms = _resolve_requested_platforms(
        args.platform,
        material_json=_normalize(args.material_json),
        platform_packaging=_normalize(args.platform_packaging),
    )
    target_profile_ids = [p for p in (_normalize(item) for item in args.target_profile_id) if p]
    if not target_profile_ids and not args.allow_anonymous_profile:
        # 与真实发布前置保持一致：默认不允许匿名 profile 进行发布链路验证。
        print("预检前置: 未提供 --target-profile-id。为避免匿名草稿与脏环境，默认不允许执行。")
        print("若必须进行临时匿名验证，请显式传入 --allow-anonymous-profile。")
        return 2

    live_gate = await _run_live_release_gate(
        browser_agent_base_url=browser_agent_base_url,
        auth_token=_normalize(args.auth_token),
        cdp_url=cdp_url,
        platforms=platforms,
        target_profile_ids=target_profile_ids,
        allow_anonymous_profile=bool(args.allow_anonymous_profile),
        timeout=max(3, int(args.timeout or 12)),
        require_tabs=args.require_tabs,
        material_json=_normalize(args.material_json),
        platform_packaging=_normalize(args.platform_packaging),
    )

    backend_smoke: dict[str, Any] = {"status": "skipped", "note": "backend smoke skipped by argument"}
    if not args.skip_backend_smoke:
        report_dir = Path(ROOT_DIR / "output" / "test" / "publication-release-gate")
        report_dir.mkdir(parents=True, exist_ok=True)
        backend_smoke = await _run_backend_contract_smoke(
            platforms,
            report_dir,
            args.fake_agent_status,
            publication_adapter=publication_adapter,
            execution_mode=execution_mode,
            material_json=_normalize(args.material_json),
            platform_packaging=_normalize(args.platform_packaging),
        )

    failures = _evaluate_failure(
        live_gate,
        backend_smoke,
        skip_backend_smoke=args.skip_backend_smoke,
        contract_success_status=_normalize(args.contract_success_status),
    )
    expectation_report = _format_expectation(
        skip_backend_smoke=args.skip_backend_smoke,
        status_expectation=_normalize(args.contract_success_status),
        backend_smoke=backend_smoke,
    )

    report = _build_release_gate_report(
        browser_agent_base_url=browser_agent_base_url,
        cdp_url=cdp_url,
        platforms=platforms,
        target_profile_ids=target_profile_ids,
        publication_adapter=publication_adapter,
        execution_mode=execution_mode,
        live_gate=live_gate,
        backend_smoke=backend_smoke,
        skip_backend_smoke=bool(args.skip_backend_smoke),
        expectation_report=expectation_report,
        failures=failures,
    )
    status = str(report.get("status") or "failed")

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[{_now()}] publication release gate status={status} output={output_path}")
    print(f"- live ready: {live_gate.get('ready')}")
    if not args.skip_backend_smoke:
        print(f"- backend smoke status: {backend_smoke.get('status')}")
    if failures:
        print("failures:")
        for item in failures:
            print(f"- {item}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
