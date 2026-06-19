from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from roughcut.publication_duplicate_audit import (  # noqa: E402
    audit_duplicate_publications,
    build_duplicate_history_gate_report,
)
from roughcut.publication_platform_matrix import platform_manual_handoff_only  # noqa: E402
from roughcut.review import intelligent_copy as intelligent_copy_review  # noqa: E402


STABLE_PUBLICATION_PLATFORMS = [
    "douyin",
    "xiaohongshu",
    "bilibili",
    "kuaishou",
    "toutiao",
    "youtube",
]
STRICT_VERIFICATION_STATUS = {
    "published",
    "scheduled_pending",
}
def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _normalize_platforms(raw_platforms: list[str]) -> list[str]:
    platforms: list[str] = []
    for item in (raw_platforms or []):
        normalized = _normalize(item).lower().replace("_", "-")
        if normalized and normalized not in platforms:
            platforms.append(normalized)
    return platforms


def _parse_expected_statuses(raw: str) -> set[str]:
    items = {item.strip().lower() for item in (raw or "").split(",")}
    statuses = {item for item in items if item}
    return statuses or set(STRICT_VERIFICATION_STATUS)


def _is_stable_platform(platform: str) -> bool:
    return _normalize(platform).lower() in STABLE_PUBLICATION_PLATFORMS


def _split_platforms(platforms: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    stable: list[str] = []
    x_platforms: list[str] = []
    manual_handoff: list[str] = []
    unsupported: list[str] = []
    for platform in platforms:
        if platform == "x":
            if platform not in x_platforms:
                x_platforms.append(platform)
        elif platform_manual_handoff_only(platform):
            if platform not in manual_handoff:
                manual_handoff.append(platform)
        elif _is_stable_platform(platform):
            if platform not in stable:
                stable.append(platform)
        else:
            if platform not in unsupported:
                unsupported.append(platform)
    return stable, x_platforms, manual_handoff, unsupported


def _coerce_overrides(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    else:
        values = [str(raw).strip()]
    resolved: list[str] = []
    for value in values:
        if not value:
            continue
        if "," in value:
            resolved.extend(part.strip() for part in value.split(",") if part.strip())
        else:
            resolved.append(value)
    return resolved


def _normalize_override_map(raw: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in (raw or []):
        normalized = _normalize(item)
        if not normalized or "=" not in normalized:
            continue
        key, value = normalized.split("=", 1)
        key = _normalize(key).lower().replace("_", "-")
        value = _normalize(value)
        if key and value:
            mapping[key] = value
    return mapping


def _merge_overrides(
    base: list[str],
    overrides: dict[str, str] | None,
    *,
    ensure_platforms: set[str],
) -> list[str]:
    merged = dict(_normalize_override_map(base))
    for platform, value in (overrides or {}).items():
        platform_key = _normalize(platform).lower().replace("_", "-")
        normalized_value = _normalize(value)
        if platform_key in ensure_platforms and normalized_value:
            merged[platform_key] = normalized_value
    return [f"{platform}={value}" for platform, value in merged.items() if platform and value]


async def _run_script(
    script_path: Path,
    args: list[str],
    *,
    timeout: int = 120,
    structured_output_path: Path | None = None,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script_path),
        *args,
        cwd=str(ROOT_DIR),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    raw_out: bytes = b""
    raw_err: bytes = b""
    try:
        raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=max(1, timeout))
    except asyncio.TimeoutError:
        output_ready = bool(structured_output_path and structured_output_path.is_file())
        if not output_ready:
            raise
        process.terminate()
        try:
            raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=15)
        except asyncio.TimeoutError:
            process.kill()
            raw_out, raw_err = await asyncio.wait_for(process.communicate(), timeout=15)
    return process.returncode, (raw_out or b"").decode("utf-8", errors="replace"), (raw_err or b"").decode("utf-8", errors="replace")


def _load_json_if_exists(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _coalesce_report_mitigation(report: dict[str, Any], *, phase: str) -> tuple[list[str], dict[str, list[str]]]:
    mitigation_steps: list[str] = []
    playbook: dict[str, list[str]] = {}
    failures = [str(item or "").strip() for item in (report.get("failures") or []) if str(item or "").strip()]
    verification_recommendations = report.get("publication_verification", {}).get("recommendations") or []
    for failure in failures:
        lowered = failure.lower()
        is_platform_scope_mismatch = "范围不匹配" in failure or "覆盖范围" in failure or "仅覆盖平台" in failure
        if is_platform_scope_mismatch:
            mitigation_steps.append("检测到目标平台超出本期物料合同覆盖范围，请重生成该平台物料或缩小发布平台范围后再发。")
            playbook.setdefault("platform_scope", []).append("重新生成目标平台物料，或仅对当前已覆盖平台执行发布。")
            continue
        if "重复" in failure or "duplicate" in failure.lower():
            mitigation_steps.append("检测到重复发布痕迹，请核对去重策略后再发。")
            playbook.setdefault("duplicate_guard", []).append("确认同素材未开启重复发布；必要时启用 --allow-republish。")
        if "草稿" in failure or "draft" in failure.lower():
            mitigation_steps.append("检测到草稿态/残留 draft 征兆，建议先清理草稿后重发。")
            playbook.setdefault("draft_cleanup", []).append("保持平台参数 clear_draft_context=true，运行成功后清理本地垃圾草稿。")
        if "profile" in lowered:
            mitigation_steps.append("检测到 profile/账号绑定问题，请使用 --target-profile-id 显式绑定 fas profile。")
            playbook.setdefault("profile_binding", []).append("预检与正式发布都必须带 --target-profile-id。")
        if "字段" in failure or "field" in lowered:
            mitigation_steps.append("检测到字段签名/字段一致性异常，先核对 packaging 与发布文案输入。")
            playbook.setdefault("field_contract", []).append("优先修复平台物料模板与计划字段，再重跑 preflight。")
        if (
            "关键参数面" in failure
            or "门禁" in failure
            or "发布文案" in failure
            or "物料" in failure
            or "publish_ready" in lowered
            or "material_contract" in lowered
        ):
            mitigation_steps.append("检测到发布前物料/门禁阻断，先补齐 packaging、live_publish_preflight 与缺失字段，再重跑 preflight。")
            playbook.setdefault("preflight_contract", []).append("优先修复 platform-packaging、live_publish_preflight 与缺失物料字段，再重跑 preflight。")
        if "browser-agent" in lowered or "cdp" in lowered or "tab" in lowered or "标签" in failure:
            mitigation_steps.append("检测到浏览器会话或发布页标签问题，先恢复 CDP/标签会话后再重跑 preflight。")
            playbook.setdefault("browser_session", []).append("确认 browser-agent、CDP 与目标平台发布页标签可用后再重试。")
        if "attempt" in lowered and ("未产出" in failure or "not produce" in lowered):
            mitigation_steps.append("检测到后端合同烟测未产出 attempt，先检查计划生成与 worker 提交链路。")
            playbook.setdefault("backend_contract", []).append("先修复 build_publication_plan、submit_publication_attempts 与 worker 提交链路，再重跑 release gate。")

    for item in verification_recommendations:
        issue = str(item.get("issue") or "").strip()
        operations = [str(op or "").strip() for op in (item.get("operations") or []) if str(op or "").strip()]
        if issue and operations:
            playbook.setdefault(issue, []).extend(operations)
            mitigation_steps.append(f"{issue}: {', '.join(operations)}")
    if failures and not mitigation_steps:
        if phase == "preflight":
            mitigation_steps.append("预检未通过，先修复环境或物料合同后再重跑 preflight。")
            playbook.setdefault("preflight_contract", []).append("优先核对 platform-packaging、browser-agent/CDP 与目标平台标签，再重跑 preflight。")
        elif phase == "release_gate":
            mitigation_steps.append("release gate 未通过，先修复后端合同烟测或平台准入条件后再重跑。")
            playbook.setdefault("release_gate", []).append("优先核对 build_publication_plan、backend smoke 与 live gate，再重跑 release gate。")
        else:
            mitigation_steps.append("正式发布核验未通过，先按失败摘要修复后再重跑。")
            playbook.setdefault("real_release", []).append("优先核对 real_release failures 与 publication_verification recommendations。")
    # 去重
    for key, values in playbook.items():
        playbook[key] = sorted({value for value in values if value})
    mitigation_steps = sorted({value for value in mitigation_steps if value})
    return mitigation_steps, playbook


def _collect_autopilot_mitigation(cycle_reports: list[dict[str, Any]]) -> dict[str, list[str] | dict[str, list[str]]]:
    steps: list[str] = []
    playbook: dict[str, list[str]] = {}
    for item in cycle_reports or []:
        if not isinstance(item, dict):
            continue
        mitigation = item.get("mitigation")
        if not isinstance(mitigation, dict):
            continue
        for step in mitigation.get("steps") or []:
            text = str(step).strip()
            if text:
                steps.append(text)
        raw_playbook = mitigation.get("playbook") or {}
        if not isinstance(raw_playbook, dict):
            continue
        for key, values in raw_playbook.items():
            if not str(key).strip():
                continue
            bucket = playbook.setdefault(str(key).strip(), [])
            if not isinstance(values, list):
                continue
            for value in values:
                text = str(value).strip()
                if text:
                    bucket.append(text)
    for key, values in playbook.items():
        playbook[key] = sorted({value for value in values if value})
    return {
        "steps": sorted({value for value in steps if value}),
        "playbook": playbook,
    }


def _normalize_status_signature(status: str) -> str:
    return _normalize(status).lower()


def _extract_verification_issues(
    real_report: dict[str, Any],
    *,
    strict_platforms: set[str],
    expected_statuses: set[str],
) -> list[str]:
    issues: list[str] = []
    verification = real_report.get("publication_verification") or {}
    verification_scope = _normalize(verification.get("scope")).lower()
    verification_summary_status = _normalize(verification.get("summary_status")).lower()
    backend_smoke_status = _normalize(verification.get("backend_smoke_status") or real_report.get("backend_contract_smoke", {}).get("status")).lower()
    platform_summaries = verification.get("platform_summaries") or []
    if not isinstance(platform_summaries, list):
        platform_summaries = []
    summary_by_platform = { _normalize(item.get("platform")).lower(): item for item in platform_summaries if isinstance(item, dict) }
    recommendation_issues_by_platform: dict[str, set[str]] = {}
    global_recommendation_issues: set[str] = set()
    raw_recommendations = verification.get("recommendations") or []
    if isinstance(raw_recommendations, list):
        for recommendation in raw_recommendations:
            if not isinstance(recommendation, dict):
                continue
            platform = _normalize(recommendation.get("platform")).lower()
            issue = _normalize(recommendation.get("issue")).lower()
            if not issue:
                continue
            if not platform:
                global_recommendation_issues.add(issue)
                continue
            recommendation_issues_by_platform.setdefault(platform, set()).add(issue)
    duplicate_gate = real_report.get("duplicate_history_gate") or {}
    duplicate_gate_failed_platforms = {
        _normalize(item).lower()
        for item in (duplicate_gate.get("platforms") or [])
        if _normalize(item)
    } if _normalize(duplicate_gate.get("status")).lower() == "failed" else set()

    for platform in sorted(strict_platforms):
        normalized_platform = _normalize(platform).lower()
        summary = summary_by_platform.get(normalized_platform)
        if not summary:
            platform_gate_issues = recommendation_issues_by_platform.get(normalized_platform) or set()
            gate_preempted = (
                normalized_platform in duplicate_gate_failed_platforms
                or any(
                    issue in {"browser_agent_not_ready", "browser_session_not_ready", "profile_requirement_failed"}
                    or issue.endswith("_not_ready")
                    or issue.endswith("_session_unverified")
                    or issue.endswith("_session_auth_required")
                    or issue.endswith("_platform_unsupported")
                    for issue in global_recommendation_issues
                )
                or any(
                    issue in {"duplicate_history_gate_failed", "manual_handoff_required", "plan_blocked", "material_gate_failed"}
                    or "duplicate" in issue
                    or "manual_handoff" in issue
                    or issue.endswith("_blocked")
                    or issue.endswith("_unavailable")
                    or issue.endswith("_prerequisite_missing")
                    for issue in platform_gate_issues
                )
            )
            if gate_preempted:
                continue
            summary_optional_release_gate = (
                verification_scope == "release_gate"
                and verification_summary_status == "passed"
                and backend_smoke_status == "passed"
                and _normalize(real_report.get("status")).lower() in {"passed", "success"}
            )
            if summary_optional_release_gate:
                continue
            issues.append(f"{normalized_platform}: 未产出平台级核验摘要，拒绝发布通过。")
            continue

        status = _normalize_status_signature(str(summary.get("status")))
        strict_contract_verified = bool(summary.get("strict_contract_verified"))
        duplicate_detected = bool(summary.get("duplicate_detected"))
        if status and status not in expected_statuses:
            issues.append(f"{normalized_platform}: 发布状态不符（{status}），预期 {', '.join(sorted(expected_statuses))}。")

        if strict_contract_verified and not duplicate_detected:
            continue

        if not bool(summary.get("signature_match")):
            issues.append(f"{normalized_platform}: 签名匹配失败（expected={summary.get('expected_signature')}, actual={summary.get('actual_signature') or summary.get('response_signature') or summary.get('run_signature')})。")
        if not bool(summary.get("field_match")):
            issues.append(f"{normalized_platform}: 字段级回执与计划不一致。")
        if summary.get("request_payload_fields_match") is False:
            issues.append(f"{normalized_platform}: 请求 payload 与发布计划字段不一致。")
        if summary.get("request_payload_plan_match") is False:
            issues.append(f"{normalized_platform}: payload 与计划字段快照对账失败。")
        if summary.get("request_snapshot_plan_match") is False:
            issues.append(f"{normalized_platform}: 发布页字段快照与计划字段不一致。")
        if summary.get("status") == "published" and not _normalize(summary.get("public_url")):
            issues.append(f"{normalized_platform}: 发布成功但未回传公开链接。")
        if summary.get("request_fields_snapshot_trusted") is False:
            issues.append(f"{normalized_platform}: 发布页字段快照来源不可信（request_fields_snapshot_trusted=false）。")
        if summary.get("request_contract_ready") is False:
            issues.append(f"{normalized_platform}: 发布合同基线缺失（request_contract_ready=false）。")
        expected_fields = summary.get("requested_fields")
        actual_fields = summary.get("actual_fields")
        if isinstance(expected_fields, dict) and expected_fields:
            expected_count = len(expected_fields)
            actual_count = len(actual_fields) if isinstance(actual_fields, dict) else 0
            if actual_count == 0:
                issues.append(f"{normalized_platform}: 未采集到实际回写字段快照，疑似仍为草稿或测试态。")
            elif actual_count < expected_count:
                issues.append(
                    f"{normalized_platform}: 回填字段数量不足（actual={actual_count}, expected={expected_count}）。"
                )
        if summary.get("strict_contract_verified") is False:
            issues.append(f"{normalized_platform}: 严格合同核验未通过，不允许采信为发布成功。")
        if bool(summary.get("duplicate_detected")):
            issues.append(f"{normalized_platform}: 检测到重复发布迹象。")
        mismatches = summary.get("request_field_verification") or summary.get("request_field_mismatch_fields") or []
        if mismatches:
            mismatch_fields = [str(item.get("field") if isinstance(item, dict) else item).strip() for item in mismatches]
            mismatch_fields = [item for item in mismatch_fields if item]
            if mismatch_fields:
                issues.append(f"{normalized_platform}: 关键字段差异 -> {', '.join(mismatch_fields[:8])}")

        if summary.get("error_code"):
            issues.append(f"{normalized_platform}: 报错码 {summary.get('error_code')}")

    stale_draft_platforms = {
        _normalize(item).lower()
        for item in (real_report.get("stale_draft_platforms") or [])
        if _normalize(item)
        and not (
            isinstance(summary_by_platform.get(_normalize(item).lower()), dict)
            and bool(summary_by_platform.get(_normalize(item).lower(), {}).get("strict_contract_verified"))
            and not bool(summary_by_platform.get(_normalize(item).lower(), {}).get("duplicate_detected"))
        )
    }
    for platform in sorted(stale_draft_platforms):
        issues.append(f"{platform}: 当前会话存在旧草稿残留，未清理前不允许直接发布。")

    if real_report.get("status") not in {"passed", "success"}:
        for item in real_report.get("failures") or []:
            text = str(item).strip()
            if text and text not in issues:
                issues.append(text)
    return sorted(set(issues))


def _flatten_platforms(platforms: list[str]) -> list[str]:
    return sorted({_normalize(item).lower() for item in platforms if _normalize(item)})


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


def _iter_autopilot_report_evidence_sources(report: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[int] = set()

    def visit(candidate: Any) -> None:
        if not isinstance(candidate, dict):
            return
        marker = id(candidate)
        if marker in seen:
            return
        seen.add(marker)
        sources.append(candidate)
        direct_report = candidate.get("report")
        if isinstance(direct_report, dict):
            visit(direct_report)
        for execution_key in ("execution", "executions"):
            execution_items = candidate.get(execution_key) or []
            if not isinstance(execution_items, list):
                continue
            for item in execution_items:
                if not isinstance(item, dict):
                    continue
                visit(item)
                nested_report = item.get("report")
                if isinstance(nested_report, dict):
                    visit(nested_report)

    visit(report)
    return sources


def _extract_creator_session_visual_evidence_by_platform(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    visual_by_platform: dict[str, dict[str, Any]] = {}
    for source_report in _iter_autopilot_report_evidence_sources(report):
        sources = [
            source_report.get("creator_sessions"),
            ((source_report.get("live_gate") or {}).get("creator_sessions") if isinstance(source_report.get("live_gate"), dict) else {}),
            ((source_report.get("agent_ready", {}).get("health", {}).get("creator_sessions")) if isinstance(source_report.get("agent_ready"), dict) else {}),
            ((source_report.get("publication_verification") or {}).get("creator_sessions") if isinstance(source_report.get("publication_verification"), dict) else {}),
        ]
        for source in sources:
            if not isinstance(source, dict):
                continue
            for raw_platform, item in source.items():
                platform = _normalize(raw_platform).lower()
                if not platform or not isinstance(item, dict):
                    continue
                visual = _coerce_visual_evidence(item.get("visual_evidence"))
                if visual:
                    visual_by_platform[platform] = visual
        embedded = (
            (source_report.get("publication_verification") or {}).get("creator_session_visual_evidence_by_platform")
            if isinstance(source_report.get("publication_verification"), dict)
            else {}
        )
        if isinstance(embedded, dict):
            for raw_platform, payload in embedded.items():
                platform = _normalize(raw_platform).lower()
                visual = _coerce_visual_evidence(payload)
                if platform and visual:
                    visual_by_platform[platform] = visual
    return visual_by_platform


def _extract_probe_inventory_visual_evidence_by_platform(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    visual_by_platform: dict[str, dict[str, Any]] = {}
    for source_report in _iter_autopilot_report_evidence_sources(report):
        sources = []
        probe_inventory = source_report.get("probe_inventory")
        if isinstance(probe_inventory, dict):
            sources.append(probe_inventory.get("platforms"))
        live_gate = source_report.get("live_gate")
        if isinstance(live_gate, dict):
            sources.append((live_gate.get("probe_inventory") or {}).get("platforms") if isinstance(live_gate.get("probe_inventory"), dict) else {})
            sources.append(live_gate.get("platform_checks"))
        cdp = source_report.get("cdp")
        if isinstance(cdp, dict):
            sources.append(cdp.get("platform_checks"))
        for source in sources:
            if not isinstance(source, dict):
                continue
            for raw_platform, item in source.items():
                platform = _normalize(raw_platform).lower()
                if not platform or not isinstance(item, dict):
                    continue
                visual = _coerce_visual_evidence(item.get("visual_evidence"))
                if visual:
                    visual_by_platform[platform] = visual
        embedded = (
            (source_report.get("publication_verification") or {}).get("probe_inventory_visual_evidence_by_platform")
            if isinstance(source_report.get("publication_verification"), dict)
            else {}
        )
        if isinstance(embedded, dict):
            for raw_platform, payload in embedded.items():
                platform = _normalize(raw_platform).lower()
                visual = _coerce_visual_evidence(payload)
                if platform and visual:
                    visual_by_platform[platform] = visual
    return visual_by_platform


def _build_autopilot_verification_digest(real_report: dict[str, Any]) -> dict[str, Any]:
    verification = real_report.get("publication_verification") or {}
    platform_summaries = verification.get("platform_summaries") or []
    if not isinstance(platform_summaries, list):
        platform_summaries = []
    recommendations = verification.get("recommendations") or []
    if not isinstance(recommendations, list):
        recommendations = []
    recovery_index = verification.get("recovery_index") or {}
    if not isinstance(recovery_index, dict):
        recovery_index = {}
    summary_status = _normalize(verification.get("summary_status")).lower()

    normalized_summaries = [
        item for item in platform_summaries
        if isinstance(item, dict) and _normalize(item.get("platform"))
    ]
    strict_contract_verified_platforms = sorted(
        {
            _normalize(item.get("platform")).lower()
            for item in normalized_summaries
            if bool(item.get("strict_contract_verified"))
        }
    )
    duplicate_detected_platforms = sorted(
        {
            _normalize(item.get("platform")).lower()
            for item in normalized_summaries
            if bool(item.get("duplicate_detected"))
        }
    )
    receipt_target_unbound_platforms = sorted(
        {
            _normalize(item.get("platform")).lower()
            for item in normalized_summaries
            if bool(item.get("receipt_target_unbound"))
        }
    )
    verified_stop_before_final_publish_platforms = sorted(
        {
            _normalize(item.get("platform")).lower()
            for item in normalized_summaries
            if bool(item.get("verified_stop_before_final_publish"))
        }
    )
    receipt_binding_ids = {
        _normalize(item.get("platform")).lower(): _normalize(item.get("receipt_binding_id"))
        for item in normalized_summaries
        if _normalize(item.get("receipt_binding_id"))
    }
    public_urls = {
        _normalize(item.get("platform")).lower(): _normalize(item.get("public_url"))
        for item in normalized_summaries
        if _normalize(item.get("public_url"))
    }
    visual_evidence_by_platform = {
        _normalize(item.get("platform")).lower(): dict(item.get("visual_evidence"))
        for item in normalized_summaries
        if isinstance(item.get("visual_evidence"), dict) and _normalize(item.get("platform"))
    }
    creator_session_visual_evidence_by_platform = _extract_creator_session_visual_evidence_by_platform(real_report)
    probe_inventory_visual_evidence_by_platform = _extract_probe_inventory_visual_evidence_by_platform(real_report)
    digest: dict[str, Any] = {
        "strict_contract_verified_platforms": strict_contract_verified_platforms,
        "duplicate_detected_platforms": duplicate_detected_platforms,
        "receipt_target_unbound_platforms": receipt_target_unbound_platforms,
        "verified_stop_before_final_publish_platforms": verified_stop_before_final_publish_platforms,
        "receipt_binding_ids": receipt_binding_ids,
        "public_urls": public_urls,
        "visual_evidence_by_platform": visual_evidence_by_platform,
        "creator_session_visual_evidence_by_platform": creator_session_visual_evidence_by_platform,
        "probe_inventory_visual_evidence_by_platform": probe_inventory_visual_evidence_by_platform,
        "platform_summaries": [
            {
                "platform": _normalize(item.get("platform")).lower(),
                "status": _normalize(item.get("status")),
                "public_url": _normalize(item.get("public_url")),
                "strict_contract_verified": bool(item.get("strict_contract_verified")),
                "duplicate_detected": bool(item.get("duplicate_detected")),
                "receipt_binding_id": _normalize(item.get("receipt_binding_id")),
                "receipt_target_unbound": bool(item.get("receipt_target_unbound")),
                "verified_stop_before_final_publish": bool(item.get("verified_stop_before_final_publish")),
                "visual_evidence": dict(item.get("visual_evidence")) if isinstance(item.get("visual_evidence"), dict) else {},
            }
            for item in normalized_summaries
        ],
    }
    if summary_status:
        digest["summary_status"] = summary_status
    if recommendations:
        digest["recommendations"] = [dict(item) for item in recommendations if isinstance(item, dict)]
    if recovery_index:
        digest["recovery_index"] = dict(recovery_index)
    return digest


def _collect_autopilot_verification_report(cycle_reports: list[dict[str, Any]]) -> dict[str, Any]:
    summary_by_platform: dict[str, dict[str, Any]] = {}
    recommendations: list[dict[str, Any]] = []
    recommendation_signatures: set[str] = set()
    stale_draft_platforms: set[str] = set()
    failures: list[str] = []
    failure_signatures: set[str] = set()
    overall_status = "passed"
    summary_status = "passed"
    aggregated_issue_counts: dict[str, int] = {}
    aggregated_platform_counts: dict[str, int] = {}
    aggregated_auto_recoverable_recommendations = 0
    aggregated_manual_required_recommendations = 0
    creator_session_visual_evidence_by_platform: dict[str, dict[str, Any]] = {}
    probe_inventory_visual_evidence_by_platform: dict[str, dict[str, Any]] = {}

    for item in cycle_reports or []:
        if not isinstance(item, dict):
            continue
        creator_session_visual_evidence_by_platform.update(_extract_creator_session_visual_evidence_by_platform(item))
        probe_inventory_visual_evidence_by_platform.update(_extract_probe_inventory_visual_evidence_by_platform(item))
        report = item.get("report")
        if not isinstance(report, dict):
            continue
        if _normalize(report.get("status")).lower() not in {"", "passed", "success"}:
            overall_status = "failed"
        verification = report.get("publication_verification") or {}
        if isinstance(verification, dict):
            verification_summary_status = _normalize(verification.get("summary_status")).lower()
            if verification_summary_status in {"manual_handoff", "blocked", "failed"}:
                if verification_summary_status == "failed" or summary_status == "passed":
                    summary_status = verification_summary_status
                elif verification_summary_status == "blocked" and summary_status != "failed":
                    summary_status = "blocked"
                elif verification_summary_status == "manual_handoff" and summary_status not in {"failed", "blocked"}:
                    summary_status = "manual_handoff"
            platform_summaries = verification.get("platform_summaries") or []
            if isinstance(platform_summaries, list):
                for summary in platform_summaries:
                    if not isinstance(summary, dict):
                        continue
                    platform = _normalize(summary.get("platform")).lower()
                    if not platform:
                        continue
                    # Keep the latest stage summary for each platform.
                    summary_by_platform[platform] = dict(summary)
            raw_recommendations = verification.get("recommendations") or []
            if isinstance(raw_recommendations, list):
                for recommendation in raw_recommendations:
                    if not isinstance(recommendation, dict):
                        continue
                    signature = json.dumps(recommendation, ensure_ascii=True, sort_keys=True, default=str)
                    if signature in recommendation_signatures:
                        continue
                    recommendation_signatures.add(signature)
                    recommendations.append(dict(recommendation))
            raw_recovery_index = verification.get("recovery_index") or {}
            if isinstance(raw_recovery_index, dict):
                issue_counts = raw_recovery_index.get("issue_counts") or {}
                if isinstance(issue_counts, dict):
                    for key, value in issue_counts.items():
                        normalized_key = _normalize(key)
                        if not normalized_key:
                            continue
                        try:
                            count = int(value)
                        except Exception:
                            count = 0
                        if count > 0:
                            aggregated_issue_counts[normalized_key] = int(aggregated_issue_counts.get(normalized_key) or 0) + count
                platform_counts = raw_recovery_index.get("platform_counts") or {}
                if isinstance(platform_counts, dict):
                    for key, value in platform_counts.items():
                        normalized_key = _normalize(key).lower().replace("_", "-")
                        if not normalized_key:
                            continue
                        try:
                            count = int(value)
                        except Exception:
                            count = 0
                        if count > 0:
                            aggregated_platform_counts[normalized_key] = int(aggregated_platform_counts.get(normalized_key) or 0) + count
                try:
                    aggregated_auto_recoverable_recommendations += int(
                        raw_recovery_index.get("auto_recoverable_recommendations") or 0
                    )
                except Exception:
                    pass
                try:
                    aggregated_manual_required_recommendations += int(
                        raw_recovery_index.get("manual_required_recommendations") or 0
                    )
                except Exception:
                    pass
        if summary_status == "passed":
            raw_report_status = _normalize(report.get("status")).lower()
            report_failures = [str(item).strip() for item in (report.get("failures") or []) if str(item).strip()]
            verification_has_summary = bool(
                isinstance(verification, dict)
                and _normalize(verification.get("summary_status")).lower()
            )
            if report_failures and (raw_report_status in {"failed", "blocked"} or not verification_has_summary):
                summary_status = "failed"
        for platform in (report.get("stale_draft_platforms") or []):
            normalized_platform = _normalize(platform).lower()
            if normalized_platform:
                stale_draft_platforms.add(normalized_platform)
        for failure in (report.get("failures") or []):
            normalized_failure = _normalize(failure)
            if not normalized_failure or normalized_failure in failure_signatures:
                continue
            failure_signatures.add(normalized_failure)
            failures.append(normalized_failure)

    aggregated_verification: dict[str, Any] = {
        "platform_summaries": [
            summary_by_platform[platform]
            for platform in sorted(summary_by_platform)
        ]
    }
    if summary_status:
        aggregated_verification["summary_status"] = summary_status
    if recommendations:
        aggregated_verification["recommendations"] = recommendations
    if creator_session_visual_evidence_by_platform:
        aggregated_verification["creator_session_visual_evidence_by_platform"] = creator_session_visual_evidence_by_platform
    if probe_inventory_visual_evidence_by_platform:
        aggregated_verification["probe_inventory_visual_evidence_by_platform"] = probe_inventory_visual_evidence_by_platform
    recovery_index = {
        "issue_counts": aggregated_issue_counts,
        "platform_counts": aggregated_platform_counts,
        "auto_recoverable_recommendations": aggregated_auto_recoverable_recommendations,
        "manual_required_recommendations": aggregated_manual_required_recommendations,
    }
    if any(
        [
            aggregated_issue_counts,
            aggregated_platform_counts,
            aggregated_auto_recoverable_recommendations,
            aggregated_manual_required_recommendations,
        ]
    ):
        aggregated_verification["recovery_index"] = recovery_index

    aggregated_report: dict[str, Any] = {
        "status": overall_status,
        "publication_verification": aggregated_verification,
    }
    if stale_draft_platforms:
        aggregated_report["stale_draft_platforms"] = sorted(stale_draft_platforms)
    if failures:
        aggregated_report["failures"] = failures
    return aggregated_report


def _is_transient_preflight_fail(failures: list[str]) -> bool:
    if not failures:
        return False
    transient_markers = [
        "cdp",
        "browser-agent",
        "连接",
        "超时",
        "temp",
        "暂时",
    ]
    for item in failures:
        lowered = item.lower()
        if any(marker in lowered for marker in transient_markers):
            return True
    return False


def _load_json_payload(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, list):
        return {"platforms": payload}
    if isinstance(payload, dict):
        return payload
    return None


def _resolve_material_json_path(*, material_json: str, platform_packaging: str) -> Path | None:
    explicit = Path(_normalize(material_json)) if _normalize(material_json) else None
    if explicit and explicit.is_file():
        return explicit
    packaging_path = Path(_normalize(platform_packaging)) if _normalize(platform_packaging) else None
    if packaging_path and packaging_path.is_file():
        sibling = packaging_path.with_name("smart-copy.json")
        if sibling.is_file():
            return sibling
        smart_copy_dir = packaging_path.parent / "smart-copy" / "smart-copy.json"
        if smart_copy_dir.is_file():
            return smart_copy_dir
    return None


def _resolve_material_payload_paths(*, material_json: str, platform_packaging: str) -> tuple[Path | None, Path | None]:
    smart_copy_path = _resolve_material_json_path(
        material_json=material_json,
        platform_packaging=platform_packaging,
    )
    packaging_path = Path(_normalize(platform_packaging)) if _normalize(platform_packaging) else None
    if not (packaging_path and packaging_path.is_file()):
        packaging_path = None
        if smart_copy_path is not None:
            sibling = smart_copy_path.with_name("platform-packaging.json")
            if sibling.is_file():
                packaging_path = sibling
    if smart_copy_path is None and packaging_path is not None:
        sibling = packaging_path.with_name("smart-copy.json")
        if sibling.is_file():
            smart_copy_path = sibling
        else:
            nested = packaging_path.parent / "smart-copy" / "smart-copy.json"
            if nested.is_file():
                smart_copy_path = nested
    return smart_copy_path, packaging_path


def _load_material_payload_bundle(*, material_json: str, platform_packaging: str) -> tuple[dict[str, Any] | None, dict[str, str]]:
    smart_copy_path, packaging_path = _resolve_material_payload_paths(
        material_json=material_json,
        platform_packaging=platform_packaging,
    )
    smart_copy_payload = _load_json_payload(smart_copy_path) if smart_copy_path is not None else None
    packaging_payload = _load_json_payload(packaging_path) if packaging_path is not None else None
    sources = {
        "smart_copy_path": str(smart_copy_path) if smart_copy_path is not None else "",
        "platform_packaging_path": str(packaging_path) if packaging_path is not None else "",
        "source_path": str(smart_copy_path or packaging_path or ""),
    }
    if not isinstance(smart_copy_payload, dict) and not isinstance(packaging_payload, dict):
        return None, sources
    merged: dict[str, Any] = {}
    if isinstance(smart_copy_payload, dict):
        merged.update(smart_copy_payload)
        if isinstance(smart_copy_payload.get("platforms"), list):
            merged["material_platforms"] = [
                dict(item)
                for item in smart_copy_payload.get("platforms")
                if isinstance(item, dict)
            ]
    if isinstance(packaging_payload, dict):
        for key in (
            "highlights",
            "fact_sheet",
            "title_audit",
            "platform_scope",
            "platforms",
            "material_dir",
            "markdown_path",
            "platform_packaging_json_path",
        ):
            if key in packaging_payload:
                merged[key] = packaging_payload[key]
    return merged, sources


def _resolve_base_platform_packaging_path(*, explicit_platform_packaging: str, material_sources: dict[str, Any] | None) -> str:
    explicit = _normalize(explicit_platform_packaging)
    if explicit:
        explicit_path = Path(explicit)
        if explicit_path.is_file():
            return str(explicit_path)
    if isinstance(material_sources, dict):
        derived = _normalize(material_sources.get("platform_packaging_path"))
        if derived:
            return derived
    return explicit


def _rebase_material_contract_scope(
    *,
    contract: dict[str, Any],
    target_platforms: list[str],
) -> dict[str, Any]:
    platform_contracts = contract.get("platforms") if isinstance(contract.get("platforms"), dict) else {}
    covered_platforms = sorted(
        {
            _normalize(platform).lower().replace("_", "-")
            for platform in platform_contracts.keys()
            if _normalize(platform)
        }
    )
    requested_platforms = [
        _normalize(platform).lower().replace("_", "-")
        for platform in (target_platforms or [])
        if _normalize(platform)
    ]
    requested_platforms = list(dict.fromkeys(requested_platforms))
    if not requested_platforms:
        return dict(contract)
    missing_requested_platforms = [
        platform for platform in requested_platforms if platform not in set(covered_platforms)
    ]
    rebased = dict(contract)
    rebased["platform_scope"] = {
        "requested_platforms": requested_platforms,
        "covered_platforms": covered_platforms,
        "missing_requested_platforms": missing_requested_platforms,
    }
    if missing_requested_platforms:
        covered_text = ", ".join(covered_platforms) if covered_platforms else "无"
        rebased["status"] = "failed"
        rebased["basic_publish_ready"] = False
        rebased["one_click_publish_ready"] = False
        rebased["blocking_reasons"] = [
            f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {covered_text}"
            for platform in missing_requested_platforms
        ]
    return rebased


def _resolve_material_gate_contract(
    *,
    material_payload: dict[str, Any],
    target_platforms: list[str],
) -> dict[str, Any]:
    platform_items = (
        material_payload.get("material_platforms")
        if isinstance(material_payload.get("material_platforms"), list)
        else material_payload.get("platforms")
        if isinstance(material_payload.get("platforms"), list)
        else []
    )
    material_platforms = [dict(item) for item in platform_items if isinstance(item, dict)]
    if material_platforms and target_platforms:
        return intelligent_copy_review._build_material_contract(
            material_platforms,
            requested_platforms=target_platforms,
        )
    contract = material_payload.get("material_contract")
    if isinstance(contract, dict):
        return _rebase_material_contract_scope(
            contract=contract,
            target_platforms=target_platforms,
        )
    if target_platforms and material_platforms:
        return intelligent_copy_review._build_material_contract(
            material_platforms,
            requested_platforms=target_platforms,
        )
    return {}


def _material_gate_report(*, material_payload: dict[str, Any] | None, target_platforms: list[str], source_path: str) -> dict[str, Any]:
    normalized_platforms = sorted({_normalize(item).lower().replace("_", "-") for item in (target_platforms or []) if _normalize(item)})
    report: dict[str, Any] = {
        "source_path": source_path,
        "status": "failed",
        "one_click_publish_ready": False,
        "manual_handoff_ready": False,
        "manual_handoff_targets": [],
        "platforms": normalized_platforms,
        "failures": [],
        "recommendations": [],
        "recovery_index": {
            "issue_counts": {},
            "platform_counts": {},
            "auto_recoverable_recommendations": 0,
            "manual_required_recommendations": 0,
        },
    }
    if not isinstance(material_payload, dict):
        report["failures"] = ["未找到可机读的 smart-copy.json 物料合同，禁止进入一键发布。"]
        return report
    contract = _resolve_material_gate_contract(
        material_payload=material_payload,
        target_platforms=normalized_platforms,
    )
    if not contract:
        report["failures"] = ["物料结果缺少 material_contract，禁止进入一键发布。"]
        return report
    report["contract"] = contract
    platform_contracts = contract.get("platforms") if isinstance(contract.get("platforms"), dict) else {}
    platform_scope = contract.get("platform_scope") if isinstance(contract.get("platform_scope"), dict) else {}
    covered_platforms = {
        _normalize(item).lower().replace("_", "-")
        for item in (platform_scope.get("covered_platforms") or [])
        if _normalize(item)
    }
    requested_scope = {
        _normalize(item).lower().replace("_", "-")
        for item in (platform_scope.get("requested_platforms") or [])
        if _normalize(item)
    }
    missing_requested_scope = {
        _normalize(item).lower().replace("_", "-")
        for item in (platform_scope.get("missing_requested_platforms") or [])
        if _normalize(item)
    }
    failures: list[str] = []
    manual_handoff_targets: list[dict[str, Any]] = []
    auto_publish_targets: list[str] = []
    recommendations: list[dict[str, Any]] = []
    issue_counts: dict[str, int] = {}
    platform_counts: dict[str, int] = {}
    for platform in normalized_platforms:
        entry = platform_contracts.get(platform) if isinstance(platform_contracts.get(platform), dict) else {}
        if not entry:
            issue = "material_gate_failed"
            operations = ["repair_material_contract", "rerun_material_gate"]
            if platform in missing_requested_scope or (requested_scope and platform not in requested_scope):
                available = ", ".join(sorted(covered_platforms or platform_contracts.keys()))
                failures.append(
                    f"{platform}: 不在本期物料生成范围内。当前仅覆盖平台 -> {available or '无'}"
                )
                issue = "platform_scope_mismatch"
                operations = ["regenerate_platform_material", "restrict_requested_platforms"]
            else:
                failures.append(f"{platform}: smart-copy 结果缺少该平台物料合同。")
            recommendations.append(
                {
                    "platform": platform,
                    "issue": issue,
                    "operations": operations,
                    "auto_remediable": True,
                }
            )
            issue_counts[issue] = int(issue_counts.get(issue) or 0) + 1
            platform_counts[platform] = 1
            continue
        entry_status = _normalize(entry.get("status")).lower()
        if bool(entry.get("manual_handoff_only")) or entry_status == "manual_handoff":
            manual_handoff_targets.append(
                {
                    "platform": platform,
                    "label": str(entry.get("label") or platform),
                    "login_url": str(entry.get("manual_publish_entry_url") or "").strip(),
                }
            )
            continue
        auto_publish_targets.append(platform)
        entry_failures = [str(item).strip() for item in (entry.get("blocking_reasons") or []) if str(item).strip()]
        missing_fields = [str(item).strip() for item in (entry.get("missing_fields") or []) if str(item).strip()]
        entry_ready = (
            True
            if entry_status == "passed"
            else False
            if entry_status in {"failed", "blocked"}
            else False
            if entry_failures or missing_fields
            else bool(entry.get("one_click_publish_ready"))
        )
        if not entry_ready:
            issue = "material_gate_failed"
            operations = ["repair_material_contract", "rerun_material_gate"]
            if entry_failures:
                failures.extend(f"{platform}: {reason}" for reason in entry_failures)
            if missing_fields:
                failures.append(f"{platform}: 缺少一键发布必需物料 -> {', '.join(missing_fields)}")
            if not entry_failures and not missing_fields:
                failures.append(f"{platform}: {entry_status or 'one_click_publish_ready=false'}")
            recommendations.append(
                {
                    "platform": platform,
                    "issue": issue,
                    "operations": operations,
                    "auto_remediable": True,
                }
            )
            issue_counts[issue] = int(issue_counts.get(issue) or 0) + 1
            platform_counts[platform] = 1
    report["failures"] = sorted(set(failures))
    report["manual_handoff_targets"] = manual_handoff_targets
    report["manual_handoff_ready"] = bool(manual_handoff_targets)
    report["one_click_publish_ready"] = not report["failures"] and bool(auto_publish_targets)
    if recommendations:
        deduped_recommendations: list[dict[str, Any]] = []
        seen_recommendations: set[tuple[str, str]] = set()
        for item in recommendations:
            platform = _normalize(item.get("platform")).lower().replace("_", "-")
            issue = _normalize(item.get("issue"))
            if not platform or not issue:
                continue
            key = (platform, issue)
            if key in seen_recommendations:
                continue
            seen_recommendations.add(key)
            deduped_recommendations.append(item)
        report["recommendations"] = deduped_recommendations
        report["recovery_index"] = {
            "issue_counts": issue_counts,
            "platform_counts": {platform: 1 for platform in sorted(platform_counts)},
            "auto_recoverable_recommendations": len(deduped_recommendations),
            "manual_required_recommendations": 0,
        }
    if report["one_click_publish_ready"]:
        report["status"] = "passed"
    elif report["manual_handoff_ready"] and not report["failures"]:
        report["status"] = "manual_handoff"
    else:
        report["status"] = "failed"
    return report


def _build_terminal_gate_report(
    *,
    status: str,
    platforms: list[str],
    target_profile_ids: list[str],
    material_gate: dict[str, Any],
    duplicate_history_gate: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    manual_handoff_targets = list(material_gate.get("manual_handoff_targets") or [])
    failure_signatures = sorted(
        {
            *[str(item) for item in (material_gate.get("failures") or []) if str(item)],
            *[str(item) for item in (duplicate_history_gate.get("failures") or []) if str(item)],
        }
    )
    mitigation_steps, playbook = _coalesce_report_mitigation(
        {"failures": failure_signatures},
        phase="initial_gate",
    )
    if status == "manual_handoff" and manual_handoff_targets:
        mitigation_steps.append("存在人工接管平台，请打开对应登录页继续处理，不进入自动一键发布。")
        manual_entries = []
        for item in manual_handoff_targets:
            if not isinstance(item, dict):
                continue
            platform = str(item.get("platform") or "").strip()
            login_url = str(item.get("login_url") or "").strip()
            label = str(item.get("label") or platform).strip()
            if platform and login_url:
                manual_entries.append(f"{label} -> {login_url}")
            elif platform:
                manual_entries.append(label)
        if manual_entries:
            playbook.setdefault("manual_handoff", []).extend(manual_entries)
    for key, values in playbook.items():
        playbook[key] = sorted({str(value).strip() for value in values if str(value).strip()})
    mitigation_steps = sorted({str(value).strip() for value in mitigation_steps if str(value).strip()})
    verification_recommendations: list[dict[str, Any]] = []
    verification_recovery_index = {
        "issue_counts": {},
        "platform_counts": {},
        "auto_recoverable_recommendations": 0,
        "manual_required_recommendations": 0,
    }
    if duplicate_history_gate.get("status") == "failed":
        duplicate_platforms: set[str] = set()
        for group in (duplicate_history_gate.get("groups") or []):
            if not isinstance(group, dict):
                continue
            platform = _normalize(group.get("platform")).lower().replace("_", "-")
            if platform:
                duplicate_platforms.add(platform)
        if not duplicate_platforms:
            for item in duplicate_history_gate.get("failures") or []:
                text = _normalize(item)
                if ":" in text:
                    head, _ = text.split(":", 1)
                    platform = _normalize(head).lower().replace("_", "-")
                    if platform:
                        duplicate_platforms.add(platform)
        for platform in sorted(duplicate_platforms):
            verification_recommendations.append(
                {
                    "platform": platform,
                    "issue": "duplicate_history_gate_failed",
                    "operations": ["review_duplicate_history", "enable_allow_republish_if_intentional"],
                    "auto_remediable": False,
                }
            )
        if verification_recommendations:
            verification_recovery_index = {
                "issue_counts": {"duplicate_history_gate_failed": len(verification_recommendations)},
                "platform_counts": {
                    item["platform"]: 1 for item in verification_recommendations if _normalize(item.get("platform"))
                },
                "auto_recoverable_recommendations": 0,
                "manual_required_recommendations": len(verification_recommendations),
            }
    elif status == "manual_handoff" and manual_handoff_targets:
        verification_recommendations = [
            {
                "platform": _normalize(item.get("platform")).lower().replace("_", "-"),
                "issue": "manual_handoff_required",
                "operations": ["open_manual_login", "continue_manual_publish"],
                "auto_remediable": False,
            }
            for item in manual_handoff_targets
            if isinstance(item, dict) and _normalize(item.get("platform"))
        ]
        if verification_recommendations:
            verification_recovery_index = {
                "issue_counts": {"manual_handoff_required": len(verification_recommendations)},
                "platform_counts": {
                    item["platform"]: 1 for item in verification_recommendations if _normalize(item.get("platform"))
                },
                "auto_recoverable_recommendations": 0,
                "manual_required_recommendations": len(verification_recommendations),
            }
    elif material_gate.get("failures"):
        if isinstance(material_gate.get("recommendations"), list) and material_gate.get("recommendations"):
            verification_recommendations = [dict(item) for item in (material_gate.get("recommendations") or []) if isinstance(item, dict)]
            recovery_index = material_gate.get("recovery_index") if isinstance(material_gate.get("recovery_index"), dict) else {}
            verification_recovery_index = {
                "issue_counts": dict(recovery_index.get("issue_counts") or {}),
                "platform_counts": dict(recovery_index.get("platform_counts") or {}),
                "auto_recoverable_recommendations": int(recovery_index.get("auto_recoverable_recommendations") or len(verification_recommendations)),
                "manual_required_recommendations": int(recovery_index.get("manual_required_recommendations") or 0),
            }
        else:
            verification_recommendations = []
            issue_counts: dict[str, int] = {}
            platform_counts: dict[str, int] = {}
            for item in material_gate.get("failures") or []:
                text = _normalize(item)
                if ":" not in text:
                    continue
                head, _ = text.split(":", 1)
                platform = _normalize(head).lower().replace("_", "-")
                if not platform:
                    continue
                issue = "material_gate_failed"
                operations = ["repair_material_contract", "rerun_material_gate"]
                if "不在本期物料生成范围内" in text or "覆盖平台" in text or "范围不匹配" in text:
                    issue = "platform_scope_mismatch"
                    operations = ["regenerate_platform_material", "restrict_requested_platforms"]
                verification_recommendations.append(
                    {
                        "platform": platform,
                        "issue": issue,
                        "operations": operations,
                        "auto_remediable": True,
                    }
                )
                platform_counts[platform] = 1
                issue_counts[issue] = int(issue_counts.get(issue) or 0) + 1
            if verification_recommendations:
                verification_recovery_index = {
                    "issue_counts": issue_counts,
                    "platform_counts": {platform: 1 for platform in sorted(platform_counts)},
                    "auto_recoverable_recommendations": len(verification_recommendations),
                    "manual_required_recommendations": 0,
                }
    return {
        "generated_at": _now(),
        "status": status,
        "objective": "稳定平台闭环发布（稳定平台先行，x 链路后置）",
        "platforms": _flatten_platforms(platforms),
        "target_profile_ids": target_profile_ids,
        "material_gate": material_gate,
        "duplicate_history_gate": duplicate_history_gate,
        "manual_handoff_ready": bool(material_gate.get("manual_handoff_ready")),
        "manual_handoff_targets": manual_handoff_targets,
        "manual_handoff_platforms": [
            str(item.get("platform") or "").strip()
            for item in manual_handoff_targets
            if isinstance(item, dict) and str(item.get("platform") or "").strip()
        ],
        "failure_signatures": failure_signatures,
        "publication_verification": _build_autopilot_verification_digest(
            {
                "publication_verification": {
                    "platform_summaries": [],
                    "summary_status": (
                        "manual_handoff"
                        if status == "manual_handoff"
                        else "failed"
                        if duplicate_history_gate.get("status") == "failed" or material_gate.get("failures")
                        else _normalize(status).lower()
                    ),
                    "recommendations": verification_recommendations,
                    "recovery_index": verification_recovery_index,
                }
            }
        ),
        "mitigation": {
            "steps": mitigation_steps,
            "playbook": playbook,
        },
        "suggestions": mitigation_steps,
        "execution": [],
        "latest": {},
        "run_dir": str(run_dir),
    }


def _write_terminal_gate_report(
    *,
    final_report: dict[str, Any],
    report_path: Path,
) -> None:
    report_path.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")


def _derive_initial_gate_terminal_outcome(
    *,
    material_gate: dict[str, Any],
    duplicate_history_gate: dict[str, Any],
) -> tuple[str | None, int | None]:
    material_status = _normalize(material_gate.get("status")).lower()
    duplicate_status = _normalize(duplicate_history_gate.get("status")).lower()
    if duplicate_status == "failed":
        return "failed", 2
    if material_status == "manual_handoff":
        return "manual_handoff", 0
    if material_status != "passed":
        return "failed", 2
    return None, None


async def _duplicate_history_gate_report(
    *,
    material_payload: dict[str, Any] | None,
    media_path: str,
    target_platforms: list[str],
    target_profile_ids: list[str],
    allow_republish: bool,
) -> dict[str, Any]:
    return await build_duplicate_history_gate_report(
        material_payload=material_payload,
        media_path=media_path,
        target_platforms=target_platforms,
        target_profile_ids=target_profile_ids,
        allow_republish=allow_republish,
        allow_material_creator_profile_fallback=bool(target_profile_ids),
        limit=20,
        audit_fn=audit_duplicate_publications,
    )


def _inject_recovery_overrides_to_platform_packaging(
    payload: dict[str, Any],
    platform_overrides: dict[str, dict[str, bool]],
) -> tuple[dict[str, Any], bool]:
    if not payload or not platform_overrides:
        return payload, False

    normalized_overrides: dict[str, dict[str, bool]] = {}
    for platform, values in platform_overrides.items():
        normalized_platform = _normalize(platform).lower().replace("_", "-")
        if not normalized_platform or not isinstance(values, dict):
            continue
        normalized_overrides[normalized_platform] = {
            "clear_draft_context": bool(values.get("clear_draft_context")),
            "force_publish_page_refresh": bool(
                values.get("force_publish_page_release")
            ) or bool(values.get("force_publish_page_refresh")),
        }

    if not normalized_overrides:
        return payload, False

    changed = False
    normalized_payload = dict(payload)

    def _ensure_entry_overrides(entry: dict[str, Any], platform: str) -> bool:
        existing = entry.get("platform_specific_overrides")
        if not isinstance(existing, dict):
            existing = {}
        updated = dict(existing)
        override = normalized_overrides.get(platform, {})
        for key, value in override.items():
            if value and updated.get(key) is not True:
                updated[key] = True
        if updated == existing:
            return False
        entry["platform_specific_overrides"] = updated
        return True

    # Top-level `platforms` as dict (most common).
    top_platforms = normalized_payload.get("platforms")
    if isinstance(top_platforms, dict):
        for key, entry in list(top_platforms.items()):
            platform = _normalize(key).lower().replace("_", "-")
            if platform in normalized_overrides and isinstance(entry, dict):
                changed = _ensure_entry_overrides(entry, platform) or changed
                normalized_payload["platforms"][key] = entry
        if changed:
            return normalized_payload, True

    # Top-level `platforms` as list.
    if isinstance(top_platforms, list):
        matched: set[str] = set()
        updated_platforms: list[Any] = []
        for item in top_platforms:
            if not isinstance(item, dict):
                updated_platforms.append(item)
                continue
            key = _normalize(item.get("platform") or item.get("label") or item.get("name"))
            normalized_key = key.lower().replace("_", "-")
            if normalized_key in normalized_overrides:
                changed = _ensure_entry_overrides(item, normalized_key) or changed
                matched.add(normalized_key)
            updated_platforms.append(item)
        for platform, values in normalized_overrides.items():
            if platform in matched:
                continue
            if not (values.get("clear_draft_context") or values.get("force_publish_page_refresh")):
                continue
            updated_platforms.append(
                {
                    "platform": platform,
                    "platform_specific_overrides": {
                        "clear_draft_context": True,
                        "force_publish_page_refresh": True,
                    },
                }
            )
            changed = True
        if changed:
            normalized_payload["platforms"] = updated_platforms
            return normalized_payload, True

    # Fallback: assume root dict maps platform -> entry
    for key, entry in list(normalized_payload.items()):
        if key in {"platforms", "metadata", "version", "comment", "note"}:
            continue
        platform = _normalize(key).lower().replace("_", "-")
        if platform in normalized_overrides and isinstance(entry, dict):
            changed = _ensure_entry_overrides(entry, platform) or changed
            normalized_payload[key] = entry

    return normalized_payload, changed


def _build_stage_platform_packaging(
    *,
    base_packaging_path: str,
    overrides: dict[str, dict[str, bool]] | None,
    stage_prefix: str,
    run_dir: Path,
) -> str:
    if not base_packaging_path:
        return ""
    if not overrides:
        return base_packaging_path
    base_path = Path(_normalize(base_packaging_path))
    payload = _load_json_payload(base_path)
    if payload is None:
        return base_packaging_path
    patched_payload, changed = _inject_recovery_overrides_to_platform_packaging(payload, overrides)
    if not changed:
        return base_packaging_path
    target_path = run_dir / f"{stage_prefix}-platform-packaging.json"
    target_path.write_text(json.dumps(patched_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target_path)


def _derive_recovery_overrides_from_real_report(
    real_report: dict[str, Any],
) -> tuple[dict[str, dict[str, bool]], bool]:
    recommendations = real_report.get("publication_verification", {}).get("recommendations") or []
    platform_overrides: dict[str, dict[str, bool]] = {}
    has_duplicate_signal = False
    has_non_remediable_signal = False

    stale_draft_platforms = {
        _normalize(item).lower().replace("_", "-")
        for item in (real_report.get("stale_draft_platforms") or [])
        if _normalize(item)
    }
    for platform in sorted(stale_draft_platforms):
        platform_overrides[platform] = {
            "clear_draft_context": True,
            "force_publish_page_refresh": True,
        }

    for item in recommendations:
        if not isinstance(item, dict):
            continue
        platform = _normalize(item.get("platform")).lower().replace("_", "-")
        if not platform:
            continue
        issue = _normalize(item.get("issue")).lower()
        if "duplicate" in issue:
            has_duplicate_signal = True
            continue
        auto_remediable = item.get("auto_remediable")
        if auto_remediable is False:
            has_non_remediable_signal = True
            continue
        operations = [
            _normalize(op).lower() for op in (item.get("operations") or []) if _normalize(op)
        ]
        if not operations:
            if auto_remediable is False:
                has_non_remediable_signal = True
            continue
        override = platform_overrides.setdefault(platform, {"clear_draft_context": False, "force_publish_page_refresh": False})
        if "clear_draft_context" in operations:
            override["clear_draft_context"] = True
        if "force_publish_page_refresh" in operations:
            override["force_publish_page_refresh"] = True

    verification_summaries = real_report.get("publication_verification", {}).get("platform_summaries") or []
    for item in verification_summaries:
        if not isinstance(item, dict):
            continue
        platform = _normalize(item.get("platform")).lower().replace("_", "-")
        if not platform:
            continue
        error_code = _normalize(item.get("error_code")).lower()
        strict_reasons = _normalize(item.get("strict_contract_reasons") or [])
        if isinstance(strict_reasons, list):
            strict_reason_text = "|".join([_normalize(item) for item in strict_reasons if _normalize(item)])
        else:
            strict_reason_text = _normalize(strict_reasons)
        if "duplicate" in error_code or ("duplicate" in strict_reason_text.lower()):
            has_duplicate_signal = True
            continue
        if "missing_contract" in strict_reason_text.lower():
            has_non_remediable_signal = True
            continue

        mismatch_signal = (
            not bool(item.get("signature_match"))
            or not bool(item.get("field_match"))
            or item.get("request_payload_fields_match") is False
            or item.get("request_payload_plan_match") is False
            or item.get("request_snapshot_plan_match") is False
            or item.get("request_fields_snapshot_trusted") is False
            or not bool(item.get("strict_contract_verified"))
            or item.get("request_fields_snapshot_missing")
        )
        if mismatch_signal:
            platform_overrides.setdefault(platform, {
                "clear_draft_context": True,
                "force_publish_page_refresh": True,
            })
            platform_overrides[platform]["clear_draft_context"] = True
            platform_overrides[platform]["force_publish_page_refresh"] = True

    retryable = bool(platform_overrides) and not has_duplicate_signal and not has_non_remediable_signal
    # 仅在可恢复信号存在且无重复发布痕迹时允许自动重试。
    return platform_overrides, retryable


async def _run_preflight(
    *,
    platforms: list[str],
    target_profile_ids: list[str],
    browser_agent_base_url: str,
    auth_token: str,
    cdp_url: str,
    timeout: int,
    require_tabs: bool,
    allow_anonymous_profile: bool,
    output_path: Path,
    material_json: str,
    platform_packaging: str,
    ) -> tuple[int, dict[str, Any], int]:
    args = [
        "--browser-agent-base-url",
        browser_agent_base_url,
        "--cdp-url",
        cdp_url,
        "--auth-token",
        auth_token,
        "--output",
        str(output_path),
        "--timeout",
        str(timeout),
    ]
    if _normalize(material_json):
        args.extend(["--material-json", material_json])
    if _normalize(platform_packaging):
        args.extend(["--platform-packaging", platform_packaging])
    if require_tabs:
        args.append("--require-tabs")
    if allow_anonymous_profile:
        args.append("--allow-anonymous-profile")
    for item in platforms:
        args.extend(["--platform", item])
    for item in target_profile_ids:
        args.extend(["--target-profile-id", item])

    return_code, stdout, stderr = await _run_script(
        ROOT_DIR / "scripts" / "run_publication_preflight.py",
        args,
        timeout=max(30, timeout * 3),
        structured_output_path=output_path,
    )
    report = _load_json_if_exists(output_path)
    report["cli_stdout"] = stdout
    report["cli_stderr"] = stderr
    report["cli_returncode"] = int(return_code)
    return int(return_code), report, len(stdout) + len(stderr)


async def _run_release_gate(
    *,
    platforms: list[str],
    target_profile_ids: list[str],
    browser_agent_base_url: str,
    auth_token: str,
    cdp_url: str,
    timeout: int,
    require_tabs: bool,
    allow_anonymous_profile: bool,
    output_path: Path,
    skip_backend_smoke: bool,
    material_json: str,
    platform_packaging: str,
    ) -> tuple[int, dict[str, Any], int]:
    args = [
        "--browser-agent-base-url",
        browser_agent_base_url,
        "--cdp-url",
        cdp_url,
        "--auth-token",
        auth_token,
        "--output",
        str(output_path),
        "--timeout",
        str(timeout),
    ]
    if skip_backend_smoke:
        args.append("--skip-backend-smoke")
    if _normalize(material_json):
        args.extend(["--material-json", material_json])
    if _normalize(platform_packaging):
        args.extend(["--platform-packaging", platform_packaging])
    if require_tabs:
        args.append("--require-tabs")
    if allow_anonymous_profile:
        args.append("--allow-anonymous-profile")
    for item in platforms:
        args.extend(["--platform", item])
    for item in target_profile_ids:
        args.extend(["--target-profile-id", item])

    return_code, stdout, stderr = await _run_script(
        ROOT_DIR / "scripts" / "run_publication_release_gate.py",
        args,
        timeout=max(30, timeout * 2 + 30),
        structured_output_path=output_path,
    )
    report = _load_json_if_exists(output_path)
    report["cli_stdout"] = stdout
    report["cli_stderr"] = stderr
    report["cli_returncode"] = int(return_code)
    return int(return_code), report, len(stdout) + len(stderr)


async def _run_real_release(
    *,
    platforms: list[str],
    target_profile_ids: list[str],
    browser_agent_base_url: str,
    auth_token: str,
    cdp_url: str,
    timeout: int,
    poll_interval: int,
    max_wait_seconds: int,
    media_path: str,
    platform_packaging: str,
    x_share_link: str,
    x_mode: str,
    platform_adapters: list[str],
    platform_execution_modes: list[str],
    auto_recover: bool,
    auto_recover_codes: str,
    auto_recover_max_rounds: int,
    allow_anonymous_profile: bool,
    allow_republish: bool,
    require_tabs: bool,
    output_path: Path,
) -> tuple[int, dict[str, Any], int]:
    args = [
        "--browser-agent-base-url",
        browser_agent_base_url,
        "--cdp-url",
        cdp_url,
        "--auth-token",
        auth_token,
        "--media-path",
        media_path,
        "--timeout",
        str(timeout),
        "--poll-interval",
        str(poll_interval),
        "--max-wait-seconds",
        str(max_wait_seconds),
        "--platform-packaging",
        platform_packaging,
        "--x-mode",
        x_mode,
        "--x-share-link",
        x_share_link,
        "--output",
        str(output_path),
    ]
    if allow_anonymous_profile:
        args.append("--allow-anonymous-profile")
    if allow_republish:
        args.append("--allow-republish")
    if require_tabs:
        args.append("--require-tabs")
    if auto_recover:
        args.append("--auto-recover")
    else:
        args.append("--no-auto-recover")
    if auto_recover_codes:
        args.extend(["--auto-recover-codes", auto_recover_codes])
    if auto_recover_max_rounds:
        args.extend(["--auto-recover-max-rounds", str(max(1, int(auto_recover_max_rounds)))])
    for item in platform_adapters:
        args.extend(["--platform-adapter", item])
    for item in platform_execution_modes:
        args.extend(["--platform-execution-mode", item])
    for item in platforms:
        args.extend(["--platform", item])
    for item in target_profile_ids:
        args.extend(["--target-profile-id", item])

    return_code, stdout, stderr = await _run_script(
        ROOT_DIR / "scripts" / "run_publication_real_release_gate.py",
        args,
        timeout=max(90, max_wait_seconds + timeout + 60),
        structured_output_path=output_path,
    )
    report = _load_json_if_exists(output_path)
    if not report and int(return_code) != 0:
        report = _build_real_release_cli_failure_report(
            platforms=platforms,
            media_path=media_path,
            stdout=stdout,
            stderr=stderr,
        )
    report["cli_stdout"] = stdout
    report["cli_stderr"] = stderr
    report["cli_returncode"] = int(return_code)
    return int(return_code), report, len(stdout) + len(stderr)


def _build_real_release_cli_failure_report(
    *,
    platforms: list[str],
    media_path: str,
    stdout: str,
    stderr: str,
) -> dict[str, Any]:
    normalized_stdout = [str(line).strip() for line in str(stdout or "").splitlines() if str(line).strip()]
    normalized_stderr = [str(line).strip() for line in str(stderr or "").splitlines() if str(line).strip()]
    failure_lines = normalized_stdout + [line for line in normalized_stderr if line not in normalized_stdout]
    recommendations: list[dict[str, Any]] = []
    playbook: dict[str, list[str]] = {}
    issue = ""
    normalized_media_path = _normalize(media_path)
    if normalized_media_path and not Path(normalized_media_path).is_file():
        issue = "media_path_unavailable"
    for line in failure_lines:
        if issue:
            break
        if "素材文件不存在" in line or "请提供 --media-path" in line:
            issue = "media_path_unavailable"
            break
    if issue == "media_path_unavailable":
        canonical_failure = f"素材文件不存在或当前运行态不可读: {normalized_media_path or _normalize(media_path)}"
        failure_lines = [canonical_failure]
        for platform in _flatten_platforms(platforms):
            recommendations.append(
                {
                    "platform": platform,
                    "issue": issue,
                    "operations": ["materialize_local_media", "verify_media_path"],
                    "auto_remediable": True,
                }
            )
        playbook["media_path_unavailable"] = [
            "将真实发布素材同步到本机可读路径，再重跑 real_release/autopilot。",
            "核对 material/media_path 是否仍指向不可读的共享盘或临时路径。",
        ]
    if not failure_lines:
        failure_lines = ["real_release_gate 未返回结构化报告，且 CLI 提前失败。"]
    return {
        "status": "failed",
        "platforms": list(platforms),
        "media_path": _normalize(media_path),
        "failures": failure_lines,
        "mitigation": {
            "steps": sorted({step for steps in playbook.values() for step in steps if step}),
            "playbook": playbook,
        },
        "suggestions": sorted({step for steps in playbook.values() for step in steps if step}),
        "publication_verification": {
            "scope": "real_release",
            "summary_status": "failed",
            "recommendations": recommendations,
            "recovery_index": {
                "issue_counts": {issue: len(recommendations)} if issue else {},
                "platform_counts": {platform: 1 for platform in _flatten_platforms(platforms)} if recommendations else {},
                "auto_recoverable_recommendations": len(recommendations),
                "manual_required_recommendations": 0,
            },
            "platform_summaries": [],
        },
    }


async def _run_autopilot(args: argparse.Namespace) -> int:
    platforms = _normalize_platforms(args.platform or STABLE_PUBLICATION_PLATFORMS)
    target_profile_ids = [_normalize(item) for item in (args.target_profile_id or []) if _normalize(item)]
    if not target_profile_ids and not args.allow_anonymous_profile:
        print("Autopilot 默认禁止匿名 profile：请提供 --target-profile-id。")
        return 2

    stable_platforms, x_platforms, manual_handoff_platforms, unsupported_platforms = _split_platforms(platforms)
    if unsupported_platforms:
        print(f"不支持的平台：{', '.join(unsupported_platforms)}（当前只允许稳定平台 + x + 人工接管平台）")
        return 2

    base_output = Path(_normalize(args.output))
    if base_output.suffix:
        base_output = base_output.parent / base_output.stem
    base_output.mkdir(parents=True, exist_ok=True)
    run_id = _now().replace(":", "").replace("-", "")
    run_dir = base_output / f"run-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    final_report_path = run_dir / "autopilot_report.json"

    expected_statuses = _parse_expected_statuses(_normalize(args.expected_status))
    platform_adapters = _coerce_overrides(args.platform_adapter)
    platform_execution_modes = _coerce_overrides(args.platform_execution_mode)
    material_payload, material_sources = _load_material_payload_bundle(
        material_json=_normalize(getattr(args, "material_json", "")),
        platform_packaging=_normalize(args.platform_packaging),
    )
    duplicate_history_gate = await _duplicate_history_gate_report(
        material_payload=material_payload,
        media_path=_normalize(args.media_path),
        target_platforms=platforms,
        target_profile_ids=target_profile_ids,
        allow_republish=bool(args.allow_republish),
    )
    material_gate = _material_gate_report(
        material_payload=material_payload,
        target_platforms=platforms,
        source_path=str(material_sources.get("source_path") or ""),
    )
    material_gate["material_sources"] = material_sources
    terminal_status, terminal_exit_code = _derive_initial_gate_terminal_outcome(
        material_gate=material_gate,
        duplicate_history_gate=duplicate_history_gate,
    )
    if terminal_status:
        final_report = _build_terminal_gate_report(
            status=terminal_status,
            platforms=platforms,
            target_profile_ids=target_profile_ids,
            material_gate=material_gate,
            duplicate_history_gate=duplicate_history_gate,
            run_dir=run_dir,
        )
        final_report["manual_handoff_platforms"] = manual_handoff_platforms
        _write_terminal_gate_report(final_report=final_report, report_path=final_report_path)
        print(json.dumps(final_report, ensure_ascii=True, indent=2))
        print(f"status: {terminal_status} run_dir={run_dir}")
        for item in final_report["failure_signatures"]:
            print(f"- {item}")
        return int(terminal_exit_code or 0)

    # 默认策略：若传了 x 且未显式指定 adapter，按链接转发走 x_link_share，避免误走视频发布链路。
    # 默认策略：若启用 x 且未显式指定 adapter，按 x 模式自动回填默认适配器与执行模式。
    if "x" in x_platforms:
        normalized_x_mode = _normalize(args.x_mode)
        if normalized_x_mode == "video":
            default_adapter = "browser_agent"
            default_exec_mode = "video"
        else:
            default_adapter = "x_link_share"
            default_exec_mode = "link_share"
        has_x_adapter = any(
            item.lower().startswith("x=") for item in platform_adapters if _normalize(item)
        )
        if not has_x_adapter:
            platform_adapters = _merge_overrides(platform_adapters, {"x": default_adapter}, ensure_platforms={"x"})
        has_x_exec_mode = any(
            item.lower().startswith("x=") for item in platform_execution_modes if _normalize(item)
        )
        if not has_x_exec_mode:
            platform_execution_modes = _merge_overrides(
                platform_execution_modes,
                {"x": default_exec_mode},
                ensure_platforms={"x"},
            )

    retries_left = max(1, int(args.retry_cycles))
    iteration = 0
    cycle_reports: list[dict[str, Any]] = []
    all_known_failures: list[str] = []
    all_known_warnings: list[str] = []
    stable_stage_passed = False
    x_stage_passed = False
    stable_recovery_overrides: dict[str, dict[str, bool]] = {}
    x_recovery_overrides: dict[str, dict[str, bool]] = {}

    async def _run_stage(
        *,
        iteration_index: int,
        stage: str,
        stage_platforms: list[str],
        require_strict: bool,
        x_mode: str,
        stage_recovery_overrides: dict[str, dict[str, bool]] | None = None,
    ) -> dict[str, Any]:
        stage_prefix = f"{stage}-{run_id}-{iteration_index}"
        preflight_output = run_dir / f"{stage_prefix}-preflight.json"
        release_gate_output = run_dir / f"{stage_prefix}-release-gate.json"
        real_release_output = run_dir / f"{stage_prefix}-real-release.json"
        base_stage_packaging_path = _resolve_base_platform_packaging_path(
            explicit_platform_packaging=_normalize(args.platform_packaging),
            material_sources=material_sources,
        )
        packaging_path = _build_stage_platform_packaging(
            base_packaging_path=base_stage_packaging_path,
            overrides=stage_recovery_overrides,
            stage_prefix=stage_prefix,
            run_dir=run_dir,
        )

        result: dict[str, Any] = {
            "stage": stage,
            "iteration": iteration_index,
            "platforms": stage_platforms,
            "strict": bool(require_strict),
            "execution": [],
        }

        preflight_rc, preflight_report, _ = await _run_preflight(
            platforms=stage_platforms,
            target_profile_ids=target_profile_ids,
            browser_agent_base_url=_normalize(args.browser_agent_base_url),
            auth_token=_normalize(args.auth_token),
            cdp_url=_normalize(args.cdp_url),
            timeout=max(3, int(args.timeout)),
            require_tabs=bool(args.require_tabs),
            allow_anonymous_profile=bool(args.allow_anonymous_profile),
            output_path=preflight_output,
            material_json=_normalize(material_sources.get("smart_copy_path")),
            platform_packaging=packaging_path,
        )
        result["execution"].append(
            {
                "phase": "preflight",
                "status": "passed" if preflight_rc == 0 else "failed",
                "return_code": preflight_rc,
                "report": preflight_report,
            }
        )
        if preflight_rc != 0:
            preflight_failures: list[str] = [str(item).strip() for item in (preflight_report.get("failures") or []) if str(item).strip()]
            if not preflight_failures:
                readiness = preflight_report.get("agent_ready") or {}
                profile_reuse = preflight_report.get("profile_reuse") or {}
                if readiness:
                    code = _normalize(readiness.get("code"))
                    message = _normalize(readiness.get("message"))
                    if code and message:
                        preflight_failures.append(f"{code}: {message}")
                    elif message:
                        preflight_failures.append(message)
                    elif code:
                        preflight_failures.append(code)
                if profile_reuse.get("code"):
                    profile_reuse_code = _normalize(profile_reuse.get("code"))
                    profile_reuse_message = _normalize(profile_reuse.get("message"))
                    text = profile_reuse_code + (f": {profile_reuse_message}" if profile_reuse_message else "")
                    if text and text not in preflight_failures:
                        preflight_failures.append(text)
            mitigation_steps, playbook = _coalesce_report_mitigation(preflight_report, phase="preflight")
            return {
                "status": "failed",
                "summary_failures": preflight_failures,
                "retry_allowed": _is_transient_preflight_fail(preflight_failures),
                "execution": result["execution"],
                "mitigation": {"steps": mitigation_steps, "playbook": playbook},
                "report": preflight_report,
            }

        if not args.skip_release_gate:
            release_gate_rc, release_gate_report, _ = await _run_release_gate(
                platforms=stage_platforms,
                target_profile_ids=target_profile_ids,
                browser_agent_base_url=_normalize(args.browser_agent_base_url),
                auth_token=_normalize(args.auth_token),
                cdp_url=_normalize(args.cdp_url),
                timeout=max(3, int(args.timeout)),
                require_tabs=bool(args.require_tabs),
                allow_anonymous_profile=bool(args.allow_anonymous_profile),
                output_path=release_gate_output,
                skip_backend_smoke=bool(args.skip_backend_smoke),
                material_json=_normalize(getattr(args, "material_json", "")),
                platform_packaging=packaging_path,
            )
            result["execution"].append(
                {
                    "phase": "release_gate",
                    "status": "passed" if release_gate_rc == 0 else "failed",
                    "return_code": release_gate_rc,
                    "report": release_gate_report,
                }
            )
            if release_gate_rc != 0:
                release_gate_failures = [str(item).strip() for item in (release_gate_report.get("failures") or []) if str(item).strip()]
                mitigation_steps, playbook = _coalesce_report_mitigation(release_gate_report, phase="release_gate")
                return {
                    "status": "failed",
                    "summary_failures": release_gate_failures,
                    "retry_allowed": _is_transient_preflight_fail(release_gate_failures),
                    "execution": result["execution"],
                    "mitigation": {"steps": mitigation_steps, "playbook": playbook},
                    "report": release_gate_report,
                }

        real_rc, real_report, _ = await _run_real_release(
            platforms=stage_platforms,
            target_profile_ids=target_profile_ids,
            browser_agent_base_url=_normalize(args.browser_agent_base_url),
            auth_token=_normalize(args.auth_token),
            cdp_url=_normalize(args.cdp_url),
            timeout=max(3, int(args.timeout)),
            poll_interval=max(2, int(args.poll_interval)),
            max_wait_seconds=max(30, int(args.max_wait_seconds)),
            media_path=_normalize(args.media_path),
            platform_packaging=packaging_path,
            x_share_link=_normalize(args.x_share_link) or _normalize(args.x_share_url),
            x_mode=x_mode,
            platform_adapters=platform_adapters,
            platform_execution_modes=platform_execution_modes,
            auto_recover=bool(args.auto_recover),
            auto_recover_codes=_normalize(args.auto_recover_codes),
            auto_recover_max_rounds=max(1, int(args.auto_recover_max_rounds or 1)),
            allow_anonymous_profile=bool(args.allow_anonymous_profile),
            allow_republish=bool(args.allow_republish),
            require_tabs=bool(args.require_tabs),
            output_path=real_release_output,
        )
        result["execution"].append(
            {
                "phase": "real_release",
                "status": "passed" if real_rc == 0 else "failed",
                "return_code": real_rc,
                "report": real_report,
            }
        )

        strict_platforms = set(stage_platforms) if require_strict else set()
        strict_failures = _extract_verification_issues(
            real_report,
            strict_platforms=strict_platforms,
            expected_statuses=expected_statuses,
        )
        platform_recovery_overrides, retry_allowed_from_report = _derive_recovery_overrides_from_real_report(real_report)
        mitigation_steps, playbook = _coalesce_report_mitigation(real_report, phase="real_release")
        verification_summary = real_report.get("publication_verification") or {}
        verification_summary_status = _normalize(verification_summary.get("summary_status")).lower()
        stage_failures = [str(item) for item in strict_failures]
        stage_warnings: list[str] = []
        for item in real_report.get("failures") or []:
            text = str(item).strip()
            if not text:
                continue
            if real_rc != 0 or verification_summary_status in {"failed", "blocked", "manual_handoff"}:
                if text not in stage_failures:
                    stage_failures.append(text)
            elif text not in stage_warnings:
                stage_warnings.append(text)

        result.update(
            {
                "status": "passed" if real_rc == 0 and not stage_failures else "failed",
                "summary_failures": stage_failures,
                "warnings": stage_warnings,
                "retry_allowed": bool(retry_allowed_from_report),
                "report": real_report,
                "recovery_overrides": platform_recovery_overrides,
                "mitigation": {"steps": mitigation_steps, "playbook": playbook},
                "verification_failures": strict_failures,
            }
        )
        return result

    while iteration < retries_left:
        iteration += 1

        stage_records: list[dict[str, Any]] = []
        stable_ok = True
        if stable_platforms and not stable_stage_passed:
            stable_stage = await _run_stage(
                iteration_index=iteration,
                stage="stable-primary",
                stage_platforms=stable_platforms,
                require_strict=True,
                x_mode=_normalize(args.x_mode),
                stage_recovery_overrides=stable_recovery_overrides,
            )
            stable_stage["stage_order"] = 1
            stable_stage_passed = stable_stage.get("status") == "passed"
            if stable_stage.get("status") == "passed":
                stable_recovery_overrides = {}
            else:
                stable_recovery_overrides.update(stable_stage.get("recovery_overrides") or {})
            stage_records.append(stable_stage)
            cycle_reports.extend(stage_records)

            all_known_failures.extend(stable_stage.get("summary_failures") or [])
            all_known_warnings.extend(stable_stage.get("warnings") or [])
            if stable_stage.get("status") != "passed":
                stable_ok = False
        elif stable_platforms and stable_stage_passed:
            stable_ok = True

        if stable_ok and x_platforms:
            x_require_strict = not bool(stable_platforms)
            if (not x_stage_passed) or bool(args.auto_retry) or not stable_platforms:
                x_stage = await _run_stage(
                    iteration_index=iteration,
                    stage="x-post",
                    stage_platforms=x_platforms,
                    require_strict=x_require_strict,
                    x_mode=_normalize(args.x_mode),
                    stage_recovery_overrides=x_recovery_overrides,
                )
                x_stage["stage_order"] = 2 if stable_platforms else 1
                stage_records.append(x_stage)
                cycle_reports.append(x_stage)
                all_known_failures.extend(x_stage.get("summary_failures") or [])
                all_known_warnings.extend(x_stage.get("warnings") or [])
                x_stage_passed = x_stage.get("status") == "passed"
                if x_stage.get("status") == "passed":
                    x_recovery_overrides = {}
                else:
                    x_recovery_overrides.update(x_stage.get("recovery_overrides") or {})
            elif stable_platforms and x_stage_passed:
                # 前置已成功且 x 已成功，跳过后续迭代
                stable_ok = True

        stage_failures = [item for item in all_known_failures if item]
        if any(r.get("status") == "failed" for r in stage_records):
            if iteration < retries_left and args.auto_retry:
                failures = [str(item) for item in (all_known_failures[-100:] if all_known_failures else [])]
                stage_retry_allowed = any(bool(item.get("retry_allowed")) for item in stage_records if isinstance(item, dict))
                has_duplicate_signal = any(
                    ("重复" in item) or ("duplicate" in _normalize(item).lower())
                    for item in failures
                )
                if (
                    not has_duplicate_signal
                    and (
                        _is_transient_preflight_fail(failures)
                        or any("draft" in item.lower() for item in failures)
                        or stage_retry_allowed
                    )
                ):
                    await asyncio.sleep(max(2, int(args.retry_interval)))
                    all_known_failures = []
                    continue
            break
        else:
            break

    latest = cycle_reports[-1] if cycle_reports else {}
    final_status = (
        "passed"
        if latest.get("status") == "passed" and all((r.get("status") == "passed" for r in cycle_reports))
        else "failed"
    )

    verification_report = _collect_autopilot_verification_report(cycle_reports)
    aggregated_mitigation = _collect_autopilot_mitigation(cycle_reports)

    final_report = {
        "generated_at": _now(),
        "status": final_status,
        "objective": "稳定平台闭环发布（稳定平台先行，x 链路后置）",
        "iterations": iteration,
        "platforms": _flatten_platforms(platforms),
        "stable_platforms": stable_platforms,
        "x_platforms": x_platforms,
        "manual_handoff_platforms": manual_handoff_platforms,
        "expected_statuses": sorted(expected_statuses),
        "target_profile_ids": target_profile_ids,
        "run_dir": str(run_dir),
        "material_gate": material_gate,
        "duplicate_history_gate": duplicate_history_gate,
        "manual_handoff_ready": bool(material_gate.get("manual_handoff_ready")),
        "manual_handoff_targets": list(material_gate.get("manual_handoff_targets") or []),
        "retry_plan": {
            "max_retry_cycles": retries_left,
            "retry_interval": int(args.retry_interval),
            "auto_retry": bool(args.auto_retry),
            "skip_release_gate": bool(args.skip_release_gate),
        },
        "execution": cycle_reports,
        "latest": latest,
        "publication_verification": _build_autopilot_verification_digest(verification_report),
        "mitigation": aggregated_mitigation,
    }

    failure_signatures = sorted({item for item in all_known_failures if item})
    warning_signatures = sorted({item for item in all_known_warnings if item and item not in failure_signatures})
    final_report["failure_signatures"] = failure_signatures
    final_report["warning_signatures"] = warning_signatures
    final_report["suggestions"] = list(aggregated_mitigation.get("steps") or [])

    if final_report["failure_signatures"]:
        final_report["knowledge"] = {
            "timestamp": _now(),
            "platforms": _flatten_platforms(platforms),
            "target_profiles": target_profile_ids,
            "media_path": _normalize(args.media_path),
            "failures": final_report["failure_signatures"],
            "suggestions": final_report["suggestions"],
        }
        knowledge_path = Path(args.output).resolve().parent / "publication-autopilot-knowledge.json"
        try:
            history = []
            if knowledge_path.is_file():
                history = json.loads(knowledge_path.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            history.append(final_report["knowledge"])
            history = history[-50:]
            knowledge_path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
            final_report["knowledge"]["persisted_to"] = str(knowledge_path)
        except Exception as exc:
            final_report["knowledge"]["note"] = f"知识库写入失败：{exc}"

    final_report_path.write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final_report, ensure_ascii=True, indent=2))

    if final_status == "passed":
        print(f"status: passed run_dir={run_dir}")
        return 0
    print(f"status: failed run_dir={run_dir}")
    for item in failure_signatures:
        print(f"- {item}")
    return 2


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auto-run publication chain: preflight -> real publish gate, and collect discovery/recovery suggestions."
    )
    parser.add_argument("--platform", action="append", default=[], help="target platforms (repeatable).")
    parser.add_argument(
        "--target-profile-id",
        action="append",
        default=[],
        help="browser profile id to assert reuse for all platforms.",
    )
    parser.add_argument(
        "--allow-anonymous-profile",
        action="store_true",
        help="允许临时匿名执行（默认禁止）。",
    )
    parser.add_argument("--media-path", required=True, help="真实发布素材路径。")
    parser.add_argument(
        "--platform-packaging",
        required=True,
        help="平台发布物料 JSON 路径（请保证含六平台 packaging）。",
    )
    parser.add_argument(
        "--material-json",
        default="",
        help="smart-copy.json 路径；为空时会自动尝试从 platform-packaging 同目录探测。",
    )
    parser.add_argument("--x-share-link", default="", help="x 转链时的链接。")
    parser.add_argument("--x-share-url", default="", help="x 分享链接 alias。")
    parser.add_argument("--x-mode", default="link_share", choices=["link_share", "video"])
    parser.add_argument(
        "--platform-adapter",
        action="append",
        default=[],
        help="如有需要：platform=adapter 映射（可重复）。",
    )
    parser.add_argument(
        "--platform-execution-mode",
        action="append",
        default=[],
        help="如有需要：platform=mode 映射（可重复）。",
    )
    parser.add_argument("--expected-status", default="published,scheduled_pending", help="最终发布终态集合。")
    parser.add_argument("--skip-release-gate", action="store_true", help="临时跳过 release gate（不推荐，默认开启）。")
    parser.add_argument(
        "--skip-backend-smoke",
        action="store_true",
        help="release gate 跳过后端发布合同烟测（不推荐）。",
    )
    parser.add_argument("--browser-agent-base-url", default="", help="browser-agent base url.")
    parser.add_argument("--auth-token", default="", help="browser-agent bearer token.")
    parser.add_argument("--cdp-url", default="", help="CDP URL。")
    parser.add_argument("--timeout", type=int, default=12, help="preflight/real release request timeout.")
    parser.add_argument("--poll-interval", type=int, default=5, help="real release polling interval.")
    parser.add_argument("--max-wait-seconds", type=int, default=240, help="real release单轮最大等待秒数。")
    parser.add_argument(
        "--require-tabs",
        action="store_true",
        default=True,
        help="在预检与正式发布都要求平台页签存在（默认开启）。",
    )
    parser.add_argument(
        "--no-require-tabs",
        action="store_false",
        dest="require_tabs",
        help="临时关闭平台页签存在性校验。",
    )
    parser.add_argument(
        "--auto-recover",
        action="store_true",
        default=True,
        help="保持默认开启草稿清理与可恢复重试。"
    )
    parser.add_argument("--no-auto-recover", action="store_false", dest="auto_recover", help="禁用自动恢复。")
    parser.add_argument(
        "--auto-recover-codes",
        default="",
        help="覆盖可恢复错误码集合，逗号分隔；为空则使用默认集合。",
    )
    parser.add_argument("--auto-recover-max-rounds", type=int, default=4, help="单平台自动恢复最大轮数（默认4）。")
    parser.add_argument("--allow-republish", action="store_true", help="重复发布：仅在确认清理后打开。")
    parser.add_argument("--retry-cycles", type=int, default=1, help="预检/正式发布失败后重试轮次。")
    parser.add_argument("--retry-interval", type=int, default=8, help="重试间隔秒。")
    parser.add_argument("--auto-retry", action="store_true", help="允许在部分可恢复条件下自动重试。")
    parser.add_argument(
        "--output",
        default=str(ROOT_DIR / "artifacts" / "publication-autopilot"),
        help="输出目录/文件前缀。",
    )
    return parser.parse_args()


async def main() -> int:
    args = _parse_args()
    return await _run_autopilot(args)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
