from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from roughcut.pipeline.render_diagnostics import (
    classify_avatar_runtime_reason_category,
    normalize_render_step_summary_for_reporting,
)
from roughcut.pipeline.rerun_actions import MANUAL_REVIEW_ONLY_ISSUES


DEFAULT_REQUIRED_STRATEGY_TYPES = (
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
)


@dataclass
class BatchLiveReadiness:
    status: str
    summary: str
    gate_passed: bool
    ready_for_live_dry_run: bool
    checks: dict[str, Any]
    failure_reasons: list[str]
    warning_reasons: list[str]
    issue_code_counts: dict[str, int]
    false_success_jobs: list[str]
    p0_blocker_jobs: list[str]
    golden_source_names: list[str]
    evaluated_job_count: int
    golden_job_count: int
    stable_run_count: int
    required_stable_runs: int


def collect_job_issue_codes(job: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for code in list(job.get("quality_issue_codes") or []):
        normalized = str(code).strip()
        if normalized and normalized not in codes:
            codes.append(normalized)
    for item in list(job.get("live_stage_validations") or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("status") or "").strip().lower() == "skipped":
            continue
        for code in list(item.get("issue_codes") or []):
            normalized = str(code).strip()
            if normalized and normalized not in codes:
                codes.append(normalized)
    return codes


def _is_blocking_quality_issue_code(code: str) -> bool:
    normalized = str(code or "").strip()
    if not normalized:
        return False
    return (
        normalized.endswith("_blocking")
        or normalized in MANUAL_REVIEW_ONLY_ISSUES
        or normalized
        in {
            "missing_subtitles",
            "missing_content_profile",
            "missing_canonical_transcript_layer",
            "subtitle_terms_pending",
            "transcript_correction_fidelity_blocking",
        }
    )


def _blocking_quality_issue_job_ids(evaluated_jobs: list[dict[str, Any]]) -> tuple[list[str], dict[str, int]]:
    job_ids: list[str] = []
    issue_counts: dict[str, int] = {}
    for job in evaluated_jobs:
        blocking_codes = [code for code in collect_job_issue_codes(job) if _is_blocking_quality_issue_code(code)]
        if not blocking_codes:
            continue
        identifier = str(job.get("job_id") or job.get("source_name") or "").strip()
        if identifier:
            job_ids.append(identifier)
        for code in blocking_codes:
            issue_counts[code] = issue_counts.get(code, 0) + 1
    return job_ids, issue_counts


def _resolve_required_stable_runs(summary: dict[str, Any], configured_required_stable_runs: int) -> int:
    stop_after = str(summary.get("stop_after") or "").strip().lower()
    if stop_after:
        return 1
    return max(1, int(configured_required_stable_runs))


def _extract_required_checks_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    payload = summary.get("required_checks")
    if not isinstance(payload, dict):
        case_rows = [dict(item) for item in list(summary.get("golden_case_rows") or []) if isinstance(item, dict)]
        if not case_rows:
            return None
        rows_with_checks = [
            row
            for row in case_rows
            if any(str(item).strip() for item in list(row.get("required_checks") or []))
        ]
        if not rows_with_checks:
            return None
        required_checks_total = sum(
            len([item for item in list(row.get("required_checks") or []) if str(item).strip()])
            for row in rows_with_checks
        )
        failed_case_ids = [
            str(row.get("case_id") or "").strip()
            for row in rows_with_checks
            if bool(list(row.get("required_checks_failed") or []))
        ]
        required_checks_case_passed = sum(
            1
            for row in rows_with_checks
            if not bool(list(row.get("required_checks_failed") or []))
        )
        required_checks_contract_passed = sum(
            1
            for row in rows_with_checks
            for check in list(row.get("required_checks") or [])
            if str(check).strip()
            and str(check).strip()
            not in {
                str(item).strip()
                for item in list(row.get("required_checks_failed") or [])
                if str(item).strip()
            }
        )
        required_checks_contract_failed = max(0, required_checks_total - required_checks_contract_passed)
        return {
            "required_checks_total": required_checks_total,
            "required_checks_contract_passed": required_checks_contract_passed,
            "required_checks_contract_failed": required_checks_contract_failed,
            "required_checks_case_passed": required_checks_case_passed,
            "required_checks_case_failed": len(failed_case_ids),
            "required_checks_contract_pass_rate": (
                float(required_checks_contract_passed) / float(required_checks_total) if required_checks_total else 1.0
            ),
            "required_checks_failed_case_ids": [item for item in failed_case_ids if item],
        }
    try:
        total_required = int(payload.get("required_checks_total") or 0)
    except (TypeError, ValueError):
        return None
    if total_required <= 0:
        return None
    pass_rate = payload.get("required_checks_contract_pass_rate")
    passed_cases = int(payload.get("required_checks_case_passed") or 0)
    failed_cases = int(payload.get("required_checks_case_failed") or 0)
    contract_failed = int(payload.get("required_checks_contract_failed") or 0)
    contract_passed = int(payload.get("required_checks_contract_passed") or 0)
    return {
        "required_checks_total": total_required,
        "required_checks_contract_passed": contract_passed,
        "required_checks_contract_failed": contract_failed,
        "required_checks_case_passed": passed_cases,
        "required_checks_case_failed": failed_cases,
        "required_checks_contract_pass_rate": float(pass_rate) if isinstance(pass_rate, (int, float)) else None,
        "required_checks_failed_case_ids": list(payload.get("required_checks_failed_case_ids") or []),
    }


def _required_checks_gate_passed(summary: dict[str, Any]) -> bool:
    required_summary = _extract_required_checks_summary(summary)
    if required_summary is None:
        return True
    if required_summary["required_checks_contract_passed"] < 0:
        return True
    return required_summary["required_checks_contract_failed"] == 0 and required_summary["required_checks_case_failed"] == 0


def _required_checks_stable_passes(candidate: dict[str, Any]) -> bool:
    required_summary = _extract_required_checks_summary(candidate)
    if required_summary is None:
        return True
    return required_summary["required_checks_contract_failed"] == 0 and required_summary["required_checks_case_failed"] == 0


def _extract_manual_editor_apply_semantics_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    fallback_summary: dict[str, Any] | None = None
    case_rows = [dict(item) for item in list(summary.get("golden_case_rows") or []) if isinstance(item, dict)]
    if case_rows:
        eligible_rows = [
            row
            for row in case_rows
            if "manual_editor_apply_semantics"
            in {
                str(item).strip()
                for item in list(row.get("required_checks") or [])
                if str(item).strip()
            }
        ]
        if eligible_rows:
            failed_case_ids = [
                str(row.get("case_id") or "").strip()
                for row in eligible_rows
                if not bool(row.get("manual_editor_apply_semantics_ok"))
            ]
            total_cases = len(eligible_rows)
            passed_case_count = total_cases - len(failed_case_ids)
            fallback_summary = {
                "total_cases": total_cases,
                "passed_case_count": passed_case_count,
                "failed_case_count": len(failed_case_ids),
                "failed_case_ids": [item for item in failed_case_ids if item],
                "pass_rate": float(passed_case_count) / float(total_cases) if total_cases else 1.0,
            }

    payload = summary.get("manual_editor_apply_semantics_summary")
    if isinstance(payload, dict):
        try:
            total_cases = int(payload.get("total_cases") or 0)
            failed_cases = int(payload.get("failed_case_count") or 0)
            passed_cases = int(payload.get("passed_case_count") or 0)
        except (TypeError, ValueError):
            return None
        if total_cases <= 0:
            return None
        result = {
            "total_cases": total_cases,
            "passed_case_count": passed_cases,
            "failed_case_count": failed_cases,
            "failed_case_ids": [str(item) for item in list(payload.get("failed_case_ids") or []) if str(item).strip()],
            "pass_rate": float(payload.get("pass_rate") or 0.0),
        }
        if fallback_summary is not None:
            for key in (
                "total_cases",
                "passed_case_count",
                "failed_case_count",
                "failed_case_ids",
                "pass_rate",
            ):
                fallback_value = fallback_summary.get(key)
                current_value = result.get(key)
                if fallback_value != current_value:
                    result[key] = fallback_value
        return result

    return fallback_summary


def _manual_editor_apply_semantics_gate_passed(summary: dict[str, Any]) -> bool:
    semantics_summary = _extract_manual_editor_apply_semantics_summary(summary)
    if semantics_summary is None:
        return True
    return semantics_summary["failed_case_count"] == 0


def _manual_editor_apply_semantics_stable_passes(candidate: dict[str, Any]) -> bool:
    semantics_summary = _extract_manual_editor_apply_semantics_summary(candidate)
    if semantics_summary is None:
        return True
    return semantics_summary["failed_case_count"] == 0


def _extract_strategy_pipeline_coverage_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    payload = summary.get("strategy_pipeline_coverage")
    if not isinstance(payload, dict):
        case_rows = [dict(item) for item in list(summary.get("golden_case_rows") or []) if isinstance(item, dict)]
        declared: set[str] = set()
        covered: set[str] = set()
        missing: set[str] = set()
        failed_case_ids: list[str] = []
        evaluated_case_count = 0
        for row in case_rows:
            statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
            status = (
                statuses.get("strategy_pipeline_coverage")
                if isinstance(statuses.get("strategy_pipeline_coverage"), dict)
                else {}
            )
            if not status:
                continue
            expected = {
                str(item or "").strip()
                for item in list(status.get("expected_strategy_types") or [])
                if str(item or "").strip()
            }
            observed = {
                str(item or "").strip()
                for item in list(status.get("observed_strategy_types") or [])
                if str(item or "").strip()
            }
            row_missing = {
                str(item or "").strip()
                for item in list(status.get("missing_strategy_types") or [])
                if str(item or "").strip()
            }
            evaluated_case_count += 1
            declared.update(expected)
            covered.update(expected.intersection(observed))
            missing.update(row_missing or (expected - observed))
            if not bool(status.get("passed")):
                case_id = str(row.get("case_id") or "").strip()
                if case_id:
                    failed_case_ids.append(case_id)
        if evaluated_case_count <= 0:
            return None
        default_missing = [
            strategy
            for strategy in DEFAULT_REQUIRED_STRATEGY_TYPES
            if strategy not in covered
        ]
        missing = set([*default_missing, *missing])
        return {
            "evaluated_case_count": evaluated_case_count,
            "declared_strategy_types": sorted(declared),
            "covered_strategy_types": sorted(covered),
            "missing_strategy_types": sorted(missing),
            "failed_case_ids": failed_case_ids,
        }
    evaluated_case_count = int(payload.get("evaluated_case_count") or 0)
    declared = [
        str(item or "").strip()
        for item in list(payload.get("declared_strategy_types") or [])
        if str(item or "").strip()
    ]
    covered = [
        str(item or "").strip()
        for item in list(payload.get("covered_strategy_types") or [])
        if str(item or "").strip()
    ]
    explicit_missing = [
        str(item or "").strip()
        for item in list(payload.get("missing_strategy_types") or [])
        if str(item or "").strip()
    ]
    missing = [
        strategy
        for strategy in DEFAULT_REQUIRED_STRATEGY_TYPES
        if strategy not in set(covered)
    ]
    missing = list(dict.fromkeys([*missing, *explicit_missing]))
    return {
        "evaluated_case_count": evaluated_case_count,
        "declared_strategy_types": declared,
        "covered_strategy_types": covered,
        "missing_strategy_types": missing,
        "failed_case_ids": [
            str(item or "").strip()
            for item in list(payload.get("failed_case_ids") or [])
            if str(item or "").strip()
        ],
    }


def _strategy_pipeline_coverage_gate_passed(summary: dict[str, Any]) -> bool:
    coverage_summary = _extract_strategy_pipeline_coverage_summary(summary)
    if coverage_summary is None:
        return True
    return (
        int(coverage_summary.get("evaluated_case_count") or 0) > 0
        and not coverage_summary.get("missing_strategy_types")
        and not coverage_summary.get("failed_case_ids")
    )


def _strategy_pipeline_coverage_stable_passes(candidate: dict[str, Any]) -> bool:
    return _strategy_pipeline_coverage_gate_passed(candidate)


def _int_count_map(value: Any) -> dict[str, int]:
    return {
        str(key): int(count)
        for key, count in dict(value or {}).items()
        if str(key).strip()
    }


def _increment_count(counts: dict[str, int], key: str) -> None:
    normalized = str(key or "").strip()
    if not normalized:
        return
    counts[normalized] = counts.get(normalized, 0) + 1


def _extract_render_diagnostics_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    payload = summary.get("render_diagnostics_summary")
    if isinstance(payload, dict):
        try:
            evaluated_jobs = int(payload.get("evaluated_job_count") or 0)
            failed_render_jobs = int(payload.get("failed_render_job_count") or 0)
            avatar_degraded_jobs = int(payload.get("avatar_degraded_job_count") or 0)
            strategy_validation_evaluated_jobs = int(payload.get("strategy_validation_evaluated_job_count") or 0)
            strategy_validation_blocking_jobs = int(payload.get("strategy_validation_blocking_job_count") or 0)
        except (TypeError, ValueError):
            return None
        if evaluated_jobs <= 0:
            return None
        result = {
            "evaluated_job_count": evaluated_jobs,
            "failed_render_job_count": failed_render_jobs,
            "failed_render_job_ids": [str(item) for item in list(payload.get("failed_render_job_ids") or []) if str(item).strip()],
            "failed_render_reasons": {
                str(key): int(value)
                for key, value in dict(payload.get("failed_render_reasons") or {}).items()
                if str(key).strip()
            },
            "cover_degraded_job_count": 0,
            "cover_degraded_job_ids": [],
            "cover_degraded_reasons": {},
            "avatar_degraded_job_count": avatar_degraded_jobs,
            "avatar_degraded_job_ids": [str(item) for item in list(payload.get("avatar_degraded_job_ids") or []) if str(item).strip()],
            "avatar_degraded_reasons": {
                str(key): int(value)
                for key, value in dict(payload.get("avatar_degraded_reasons") or {}).items()
                if str(key).strip()
            },
            "avatar_degraded_reason_categories": {
                str(key): int(value)
                for key, value in dict(payload.get("avatar_degraded_reason_categories") or {}).items()
                if str(key).strip()
            },
            "strategy_validation_evaluated_job_count": strategy_validation_evaluated_jobs,
            "strategy_validation_blocking_job_count": strategy_validation_blocking_jobs,
            "strategy_validation_blocking_job_ids": [
                str(item)
                for item in list(payload.get("strategy_validation_blocking_job_ids") or [])
                if str(item).strip()
            ],
            "strategy_validation_blocking_reasons": _int_count_map(
                payload.get("strategy_validation_blocking_reasons")
            ),
            "strategy_validation_strategy_types": _int_count_map(
                payload.get("strategy_validation_strategy_types")
            ),
            "strategy_validation_review_gates": _int_count_map(
                payload.get("strategy_validation_review_gates")
            ),
        }
        jobs_fallback_summary = _extract_render_diagnostics_summary({"jobs": summary.get("jobs") or []})
        if jobs_fallback_summary is not None:
            for key in (
                "evaluated_job_count",
                "failed_render_job_count",
                "failed_render_job_ids",
                "failed_render_reasons",
                "avatar_degraded_job_count",
                "avatar_degraded_job_ids",
                "avatar_degraded_reasons",
                "avatar_degraded_reason_categories",
                "strategy_validation_evaluated_job_count",
                "strategy_validation_blocking_job_count",
                "strategy_validation_blocking_job_ids",
                "strategy_validation_blocking_reasons",
                "strategy_validation_strategy_types",
                "strategy_validation_review_gates",
            ):
                fallback_value = jobs_fallback_summary.get(key)
                current_value = result.get(key)
                if fallback_value != current_value:
                    result[key] = jobs_fallback_summary.get(key)
        return result

    jobs = [dict(item) for item in list(summary.get("jobs") or []) if isinstance(item, dict)]
    if not jobs:
        return None
    failed_render_job_ids: list[str] = []
    avatar_degraded_job_ids: list[str] = []
    failed_render_reasons: dict[str, int] = {}
    avatar_degraded_reasons: dict[str, int] = {}
    avatar_degraded_reason_categories: dict[str, int] = {}
    strategy_validation_blocking_job_ids: list[str] = []
    strategy_validation_blocking_reasons: dict[str, int] = {}
    strategy_validation_strategy_types: dict[str, int] = {}
    strategy_validation_review_gates: dict[str, int] = {}
    strategy_validation_evaluated_job_count = 0
    evaluated_job_count = 0
    for job in jobs:
        diagnostics = job.get("render_diagnostics") if isinstance(job.get("render_diagnostics"), dict) else {}
        diagnostics = _normalize_legacy_render_diagnostics(diagnostics)
        render_step = diagnostics.get("render_step") if isinstance(diagnostics.get("render_step"), dict) else {}
        avatar_result = diagnostics.get("avatar_result") if isinstance(diagnostics.get("avatar_result"), dict) else {}
        strategy_render_validation = (
            diagnostics.get("strategy_render_validation")
            if isinstance(diagnostics.get("strategy_render_validation"), dict)
            else {}
        )
        if not render_step and not avatar_result and not strategy_render_validation:
            continue
        evaluated_job_count += 1
        job_id = str(job.get("job_id") or job.get("source_name") or "").strip()
        if strategy_render_validation:
            strategy_validation_evaluated_job_count += 1
            _increment_count(
                strategy_validation_strategy_types,
                str(strategy_render_validation.get("strategy_type") or "").strip(),
            )
            for gate in list(strategy_render_validation.get("review_gates") or []):
                _increment_count(strategy_validation_review_gates, str(gate).strip())
            validation_status = str(strategy_render_validation.get("status") or "").strip().lower()
            if bool(strategy_render_validation.get("blocking")) or validation_status == "blocking":
                if job_id:
                    strategy_validation_blocking_job_ids.append(job_id)
                blocking_reasons = [
                    str(item).strip()
                    for item in list(strategy_render_validation.get("blocking_reasons") or [])
                    if str(item).strip()
                ]
                if not blocking_reasons:
                    blocking_reasons = [
                        str(strategy_render_validation.get("reason") or "strategy_render_validation_blocked").strip()
                    ]
                for reason in blocking_reasons:
                    _increment_count(strategy_validation_blocking_reasons, reason)
        if str(render_step.get("status") or "").strip().lower() == "failed" and job_id:
            failed_render_job_ids.append(job_id)
            reason = str(render_step.get("reason") or "").strip()
            if reason:
                failed_render_reasons[reason] = failed_render_reasons.get(reason, 0) + 1
        if str(avatar_result.get("status") or "").strip().lower() == "degraded" and job_id:
            avatar_degraded_job_ids.append(job_id)
            reason = str(avatar_result.get("reason") or "").strip()
            if reason:
                avatar_degraded_reasons[reason] = avatar_degraded_reasons.get(reason, 0) + 1
                category = str(avatar_result.get("reason_category") or "").strip()
                if category:
                    avatar_degraded_reason_categories[category] = avatar_degraded_reason_categories.get(category, 0) + 1
    if evaluated_job_count <= 0:
        return None
    return {
        "evaluated_job_count": evaluated_job_count,
        "failed_render_job_count": len(failed_render_job_ids),
        "failed_render_job_ids": failed_render_job_ids,
        "failed_render_reasons": failed_render_reasons,
        "cover_degraded_job_count": 0,
        "cover_degraded_job_ids": [],
        "cover_degraded_reasons": {},
        "avatar_degraded_job_count": len(avatar_degraded_job_ids),
        "avatar_degraded_job_ids": avatar_degraded_job_ids,
        "avatar_degraded_reasons": avatar_degraded_reasons,
        "avatar_degraded_reason_categories": avatar_degraded_reason_categories,
        "strategy_validation_evaluated_job_count": strategy_validation_evaluated_job_count,
        "strategy_validation_blocking_job_count": len(strategy_validation_blocking_job_ids),
        "strategy_validation_blocking_job_ids": strategy_validation_blocking_job_ids,
        "strategy_validation_blocking_reasons": strategy_validation_blocking_reasons,
        "strategy_validation_strategy_types": strategy_validation_strategy_types,
        "strategy_validation_review_gates": strategy_validation_review_gates,
    }


def _normalize_legacy_render_diagnostics(diagnostics: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(diagnostics or {}) if isinstance(diagnostics, dict) else {}
    strategy_render_validation = (
        dict(payload.get("strategy_render_validation") or {})
        if isinstance(payload.get("strategy_render_validation"), dict)
        else {}
    )
    if strategy_render_validation:
        strategy_render_validation["review_gates"] = [
            str(item).strip()
            for item in list(strategy_render_validation.get("review_gates") or [])
            if str(item).strip()
        ]
        strategy_render_validation["blocking_reasons"] = [
            str(item).strip()
            for item in list(strategy_render_validation.get("blocking_reasons") or [])
            if str(item).strip()
        ]
        payload["strategy_render_validation"] = strategy_render_validation

    avatar_result = dict(payload.get("avatar_result") or {}) if isinstance(payload.get("avatar_result"), dict) else {}
    if avatar_result:
        reason = str(avatar_result.get("reason") or "").strip().lower()
        if reason and not str(avatar_result.get("reason_category") or "").strip():
            reason_category = classify_avatar_runtime_reason_category(reason)
            if reason_category:
                avatar_result["reason_category"] = reason_category
        payload["avatar_result"] = avatar_result

    render_step = dict(payload.get("render_step") or {}) if isinstance(payload.get("render_step"), dict) else {}
    if render_step:
        payload["render_step"] = normalize_render_step_summary_for_reporting(render_step)
    return payload


def _render_diagnostics_gate_passed(summary: dict[str, Any]) -> bool:
    render_summary = _extract_render_diagnostics_summary(summary)
    if render_summary is None:
        return True
    return (
        render_summary["failed_render_job_count"] == 0
        and int(render_summary.get("strategy_validation_blocking_job_count") or 0) == 0
    )


def _render_diagnostics_stable_passes(candidate: dict[str, Any]) -> bool:
    render_summary = _extract_render_diagnostics_summary(candidate)
    if render_summary is None:
        return True
    return render_summary["failed_render_job_count"] == 0


def _extract_risk_alignment_summary(summary: dict[str, Any]) -> dict[str, Any] | None:
    case_rows = [dict(item) for item in list(summary.get("golden_case_rows") or []) if isinstance(item, dict)]

    fallback_summary: dict[str, Any] | None = None
    if case_rows:
        mismatch_case_ids: list[str] = []
        mismatch_code_counts: dict[str, int] = {}
        reference_high_risk_case_count = 0
        reproduced_case_count = 0
        for row in case_rows:
            risk_alignment = row.get("risk_alignment") if isinstance(row.get("risk_alignment"), dict) else {}
            reference_high_risk_cut_count = int(risk_alignment.get("reference_high_risk_cut_count") or 0)
            mismatch_codes = [str(item).strip() for item in list(risk_alignment.get("mismatch_codes") or []) if str(item).strip()]
            if mismatch_codes:
                case_id = str(row.get("case_id") or "").strip()
                if case_id:
                    mismatch_case_ids.append(case_id)
            for code in mismatch_codes:
                mismatch_code_counts[code] = mismatch_code_counts.get(code, 0) + 1
            if reference_high_risk_cut_count > 0:
                reference_high_risk_case_count += 1
                if bool(risk_alignment.get("high_risk_reproduced")):
                    reproduced_case_count += 1
        if reference_high_risk_case_count > 0 or mismatch_code_counts:
            fallback_summary = {
                "reference_high_risk_case_count": reference_high_risk_case_count,
                "reproduced_case_count": reproduced_case_count,
                "unreproduced_case_count": max(0, reference_high_risk_case_count - reproduced_case_count),
                "mismatch_case_ids": mismatch_case_ids,
                "mismatch_code_counts": mismatch_code_counts,
            }

    payload = summary.get("risk_alignment_summary")
    if isinstance(payload, dict):
        mismatch_code_counts = {
            str(key): int(value)
            for key, value in dict(payload.get("mismatch_code_counts") or {}).items()
            if str(key).strip()
        }
        mismatch_case_ids = [str(item) for item in list(payload.get("mismatch_case_ids") or []) if str(item).strip()]
        try:
            reference_high_risk_case_count = int(payload.get("reference_high_risk_case_count") or 0)
            reproduced_case_count = int(payload.get("reproduced_case_count") or 0)
            unreproduced_case_count = int(payload.get("unreproduced_case_count") or 0)
        except (TypeError, ValueError):
            return None
        result = {
            "reference_high_risk_case_count": reference_high_risk_case_count,
            "reproduced_case_count": reproduced_case_count,
            "unreproduced_case_count": unreproduced_case_count,
            "mismatch_case_ids": mismatch_case_ids,
            "mismatch_code_counts": mismatch_code_counts,
        }
        if fallback_summary is not None:
            for key in (
                "reference_high_risk_case_count",
                "reproduced_case_count",
                "unreproduced_case_count",
                "mismatch_case_ids",
                "mismatch_code_counts",
            ):
                fallback_value = fallback_summary.get(key)
                current_value = result.get(key)
                if fallback_value != current_value:
                    result[key] = fallback_value
        return result
    return fallback_summary


def _risk_alignment_gate_passed(summary: dict[str, Any]) -> bool:
    risk_summary = _extract_risk_alignment_summary(summary)
    if risk_summary is None:
        return True
    return int((risk_summary.get("mismatch_code_counts") or {}).get("reference_risk_contract_incomplete") or 0) == 0


def _risk_alignment_stable_passes(candidate: dict[str, Any]) -> bool:
    return _risk_alignment_gate_passed(candidate)


def build_live_readiness_summary(
    summary: dict[str, Any],
    *,
    golden_source_names: list[str] | None = None,
    previous_summaries: list[dict[str, Any]] | None = None,
    required_success_rate: float = 0.9,
    required_average_quality: float = 80.0,
    required_stable_runs: int = 3,
) -> BatchLiveReadiness:
    jobs = [dict(item) for item in list(summary.get("jobs") or []) if isinstance(item, dict)]
    effective_required_stable_runs = _resolve_required_stable_runs(summary, required_stable_runs)
    golden_source_names = [str(item).strip() for item in list(golden_source_names or []) if str(item).strip()]
    golden_set = set(golden_source_names)
    evaluated_jobs = [job for job in jobs if not golden_set or str(job.get("source_name") or "").strip() in golden_set]
    issue_code_counts: dict[str, int] = {}
    false_success_jobs: list[str] = []
    p0_blocker_jobs: list[str] = []

    for job in evaluated_jobs:
        source_name = str(job.get("source_name") or "").strip()
        stage_validations = list(job.get("live_stage_validations") or [])
        stage_failures = [item for item in stage_validations if isinstance(item, dict) and item.get("status") == "fail"]
        run_status = str(job.get("status") or "").strip().lower()
        output_path = str(job.get("output_path") or "").strip()
        false_success = bool(
            run_status == "done"
            and (not output_path or float(job.get("output_duration_sec") or 0.0) <= 0.0 or stage_failures)
        )
        if false_success and source_name:
            false_success_jobs.append(source_name)
        if (run_status == "failed" or false_success or stage_failures) and source_name:
            p0_blocker_jobs.append(source_name)
        for code in collect_job_issue_codes(job):
            issue_code_counts[code] = issue_code_counts.get(code, 0) + 1
    blocking_quality_issue_job_ids, blocking_quality_issue_counts = _blocking_quality_issue_job_ids(evaluated_jobs)

    evaluated_count = len(evaluated_jobs)
    successful_jobs = sum(
        1 for job in evaluated_jobs if str(job.get("status") or "").strip().lower() in {"done", "partial"}
    )
    success_rate = (successful_jobs / evaluated_count) if evaluated_count else 0.0
    quality_scores = [float(job.get("quality_score")) for job in evaluated_jobs if job.get("quality_score") is not None]
    average_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else None
    failure_reasons: list[str] = []
    warning_reasons: list[str] = []
    checks = {
        "stable_runs": {
            "passed": False,
            "actual": 0,
            "required": effective_required_stable_runs,
        },
        "golden_success_rate": {
            "passed": evaluated_count > 0 and success_rate >= required_success_rate,
            "actual": round(success_rate, 3),
            "required": required_success_rate,
        },
        "average_quality_score": {
            "passed": average_quality is not None and average_quality >= required_average_quality,
            "actual": None if average_quality is None else round(average_quality, 2),
            "required": required_average_quality,
        },
        "p0_blockers": {
            "passed": len(p0_blocker_jobs) == 0,
            "actual": len(p0_blocker_jobs),
            "required": 0,
        },
        "false_successes": {
            "passed": len(false_success_jobs) == 0,
            "actual": len(false_success_jobs),
            "required": 0,
        },
        "issue_code_coverage": {
            "passed": all(
                bool(collect_job_issue_codes(job))
                for job in evaluated_jobs
                if str(job.get("status") or "").strip().lower() == "failed"
            ),
            "actual": sum(1 for job in evaluated_jobs if collect_job_issue_codes(job)),
            "required": sum(
                1 for job in evaluated_jobs if str(job.get("status") or "").strip().lower() == "failed"
            ),
        },
        "blocking_quality_issues": {
            "passed": len(blocking_quality_issue_job_ids) == 0,
            "actual": len(blocking_quality_issue_job_ids),
            "required": 0,
            "job_ids": list(blocking_quality_issue_job_ids),
            "issue_code_counts": dict(sorted(blocking_quality_issue_counts.items(), key=lambda item: (-item[1], item[0]))),
        },
    }
    required_checks_summary = _extract_required_checks_summary(summary)
    if required_checks_summary is not None:
        checks["required_checks_contract"] = {
            "passed": _required_checks_gate_passed(summary),
            "actual": required_checks_summary["required_checks_contract_pass_rate"],
            "required": 1.0,
            "failed_required_checks": required_checks_summary["required_checks_contract_failed"],
            "required_checks_total": required_checks_summary["required_checks_total"],
            "failed_required_case_count": required_checks_summary["required_checks_case_failed"],
            "failed_required_case_ids": list(required_checks_summary["required_checks_failed_case_ids"]),
        }
    semantics_summary = _extract_manual_editor_apply_semantics_summary(summary)
    if semantics_summary is not None:
        checks["manual_editor_apply_semantics_contract"] = {
            "passed": _manual_editor_apply_semantics_gate_passed(summary),
            "actual": semantics_summary["pass_rate"],
            "required": 1.0,
            "total_cases": semantics_summary["total_cases"],
            "failed_case_count": semantics_summary["failed_case_count"],
            "failed_case_ids": list(semantics_summary["failed_case_ids"]),
        }
    strategy_coverage_summary = _extract_strategy_pipeline_coverage_summary(summary)
    if strategy_coverage_summary is not None:
        checks["strategy_pipeline_coverage"] = {
            "passed": _strategy_pipeline_coverage_gate_passed(summary),
            "actual": len(strategy_coverage_summary["covered_strategy_types"]),
            "required": len(DEFAULT_REQUIRED_STRATEGY_TYPES),
            "evaluated_case_count": strategy_coverage_summary["evaluated_case_count"],
            "declared_strategy_types": list(strategy_coverage_summary["declared_strategy_types"]),
            "covered_strategy_types": list(strategy_coverage_summary["covered_strategy_types"]),
            "missing_strategy_types": list(strategy_coverage_summary["missing_strategy_types"]),
            "failed_case_ids": list(strategy_coverage_summary["failed_case_ids"]),
        }
    render_summary = _extract_render_diagnostics_summary(summary)
    if render_summary is not None:
        render_blocking_count = (
            render_summary["failed_render_job_count"]
            + int(render_summary.get("strategy_validation_blocking_job_count") or 0)
        )
        checks["render_end_state_stability"] = {
            "passed": _render_diagnostics_gate_passed(summary),
            "actual": render_blocking_count,
            "required": 0,
            "evaluated_job_count": render_summary["evaluated_job_count"],
            "failed_render_job_count": render_summary["failed_render_job_count"],
            "failed_render_job_ids": list(render_summary["failed_render_job_ids"]),
            "failed_render_reasons": dict(render_summary.get("failed_render_reasons") or {}),
            "cover_degraded_job_count": render_summary["cover_degraded_job_count"],
            "cover_degraded_job_ids": list(render_summary["cover_degraded_job_ids"]),
            "cover_degraded_reasons": dict(render_summary.get("cover_degraded_reasons") or {}),
            "avatar_degraded_job_count": render_summary["avatar_degraded_job_count"],
            "avatar_degraded_job_ids": list(render_summary["avatar_degraded_job_ids"]),
            "avatar_degraded_reasons": dict(render_summary.get("avatar_degraded_reasons") or {}),
            "avatar_degraded_reason_categories": dict(render_summary.get("avatar_degraded_reason_categories") or {}),
            "strategy_validation_evaluated_job_count": int(
                render_summary.get("strategy_validation_evaluated_job_count") or 0
            ),
            "strategy_validation_blocking_job_count": int(
                render_summary.get("strategy_validation_blocking_job_count") or 0
            ),
            "strategy_validation_blocking_job_ids": list(
                render_summary.get("strategy_validation_blocking_job_ids") or []
            ),
            "strategy_validation_blocking_reasons": dict(
                render_summary.get("strategy_validation_blocking_reasons") or {}
            ),
            "strategy_validation_strategy_types": dict(
                render_summary.get("strategy_validation_strategy_types") or {}
            ),
            "strategy_validation_review_gates": dict(
                render_summary.get("strategy_validation_review_gates") or {}
            ),
        }
    risk_alignment_summary = _extract_risk_alignment_summary(summary)
    if risk_alignment_summary is not None:
        mismatch_code_counts = dict(risk_alignment_summary.get("mismatch_code_counts") or {})
        reference_contract_incomplete_count = int(mismatch_code_counts.get("reference_risk_contract_incomplete") or 0)
        checks["risk_alignment_contract"] = {
            "passed": _risk_alignment_gate_passed(summary),
            "actual": reference_contract_incomplete_count,
            "required": 0,
            "reference_high_risk_case_count": risk_alignment_summary["reference_high_risk_case_count"],
            "reproduced_case_count": risk_alignment_summary["reproduced_case_count"],
            "unreproduced_case_count": risk_alignment_summary["unreproduced_case_count"],
            "mismatch_case_ids": list(risk_alignment_summary.get("mismatch_case_ids") or []),
            "mismatch_code_counts": mismatch_code_counts,
        }
    if not golden_source_names:
        warning_reasons.append("未显式提供 golden jobs，当前按本次 batch 全量样本评估")
    if render_summary is not None and render_summary["avatar_degraded_job_count"] > 0:
        warning_reasons.append(f"存在数字人降级 job：{render_summary['avatar_degraded_job_count']} 个")

    historical_runs = [*(previous_summaries or []), summary]
    stable_run_count = 0
    for candidate in reversed(historical_runs):
        candidate_jobs = [dict(item) for item in list(candidate.get("jobs") or []) if isinstance(item, dict)]
        if golden_set:
            candidate_jobs = [job for job in candidate_jobs if str(job.get("source_name") or "").strip() in golden_set]
        if not candidate_jobs:
            break
        candidate_success_rate = sum(
            1
            for job in candidate_jobs
            if str(job.get("status") or "").strip().lower() in {"done", "partial"}
        ) / len(candidate_jobs)
        candidate_quality_scores = [float(job.get("quality_score")) for job in candidate_jobs if job.get("quality_score") is not None]
        candidate_avg_quality = (sum(candidate_quality_scores) / len(candidate_quality_scores)) if candidate_quality_scores else None
        candidate_false_success = any(
            str(job.get("status") or "").strip().lower() == "done"
            and (
                not str(job.get("output_path") or "").strip()
                or float(job.get("output_duration_sec") or 0.0) <= 0.0
                or any(isinstance(item, dict) and item.get("status") == "fail" for item in list(job.get("live_stage_validations") or []))
            )
            for job in candidate_jobs
        )
        candidate_p0 = any(
            str(job.get("status") or "").strip().lower() == "failed"
            or candidate_false_success
            or any(isinstance(item, dict) and item.get("status") == "fail" for item in list(job.get("live_stage_validations") or []))
            for job in candidate_jobs
        )
        candidate_checks_ok = _required_checks_stable_passes(candidate)
        candidate_manual_editor_ok = _manual_editor_apply_semantics_stable_passes(candidate)
        candidate_strategy_coverage_ok = _strategy_pipeline_coverage_stable_passes(candidate)
        candidate_render_ok = _render_diagnostics_stable_passes(candidate)
        candidate_risk_alignment_ok = _risk_alignment_stable_passes(candidate)
        candidate_blocking_quality_jobs, _ = _blocking_quality_issue_job_ids(candidate_jobs)
        if (
            candidate_success_rate >= required_success_rate
            and candidate_avg_quality is not None
            and candidate_avg_quality >= required_average_quality
            and not candidate_false_success
            and not candidate_p0
            and candidate_checks_ok
            and candidate_manual_editor_ok
            and candidate_strategy_coverage_ok
            and candidate_render_ok
            and candidate_risk_alignment_ok
            and not candidate_blocking_quality_jobs
        ):
            stable_run_count += 1
            continue
        break
    checks["stable_runs"]["actual"] = stable_run_count
    checks["stable_runs"]["passed"] = stable_run_count >= effective_required_stable_runs

    for name, check in checks.items():
        if not check["passed"]:
            if name == "stable_runs":
                failure_reasons.append(f"连续稳定批次不足：{check['actual']}/{check['required']}")
            elif name == "golden_success_rate":
                failure_reasons.append(f"golden success rate 不足：{check['actual']:.0%} < {check['required']:.0%}")
            elif name == "average_quality_score":
                actual = "n/a" if check["actual"] is None else f"{float(check['actual']):.1f}"
                failure_reasons.append(f"平均质量分不足：{actual} < {float(check['required']):.1f}")
            elif name == "p0_blockers":
                failure_reasons.append(f"P0 blocker 未清零：{check['actual']} 个")
            elif name == "false_successes":
                failure_reasons.append(f"存在假成功 job：{check['actual']} 个")
            elif name == "issue_code_coverage":
                failure_reasons.append("存在失败 job 缺少 issue code 归因")
            elif name == "blocking_quality_issues":
                failure_reasons.append(f"存在 blocking quality issues：{check.get('actual', 0)} 个 job")
            elif name == "required_checks_contract":
                failure_reasons.append(
                    f"required_checks 未通过：failed_required_checks={check.get('failed_required_checks', 0)}，"
                    f"failed_cases={check.get('failed_required_case_count', 0)}"
                )
            elif name == "manual_editor_apply_semantics_contract":
                failure_reasons.append(
                    f"manual_editor_apply_semantics 未通过：failed_cases={check.get('failed_case_count', 0)}"
                )
            elif name == "strategy_pipeline_coverage":
                failure_reasons.append(
                    "策略 fixture 覆盖未完成：missing="
                    + ",".join(list(check.get("missing_strategy_types") or []))
                )
            elif name == "render_end_state_stability":
                failure_reasons.append(
                    "render 终态稳定性未通过："
                    f"failed_render_jobs={check.get('failed_render_job_count', 0)}，"
                    f"strategy_validation_blocking_jobs={check.get('strategy_validation_blocking_job_count', 0)}"
                )
            elif name == "risk_alignment_contract":
                failure_reasons.append(
                    f"reference 风险合同未对齐：reference_risk_contract_incomplete={check.get('actual', 0)}"
                )

    gate_passed = not failure_reasons
    return BatchLiveReadiness(
        status="pass" if gate_passed else "fail",
        summary="满足 live dry run 准入门槛" if gate_passed else "未满足 live dry run 准入门槛",
        gate_passed=gate_passed,
        ready_for_live_dry_run=gate_passed,
        checks=checks,
        failure_reasons=failure_reasons,
        warning_reasons=warning_reasons,
        issue_code_counts=dict(sorted(issue_code_counts.items(), key=lambda item: (-item[1], item[0]))),
        false_success_jobs=sorted(false_success_jobs),
        p0_blocker_jobs=sorted(p0_blocker_jobs),
        golden_source_names=golden_source_names,
        evaluated_job_count=evaluated_count,
        golden_job_count=len(golden_source_names) if golden_source_names else evaluated_count,
        stable_run_count=stable_run_count,
        required_stable_runs=effective_required_stable_runs,
    )


def load_live_readiness_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path else _default_batch_report_path()
    progress_path = path.with_name("batch_progress.json")
    snapshot: dict[str, Any] = {
        "status": "unknown",
        "gate_passed": False,
        "summary": "尚无 live readiness 报告",
        "stable_run_count": 0,
        "required_stable_runs": 3,
        "failure_reasons": [],
        "warning_reasons": [],
        "report_file": str(path),
        "report_created_at": None,
        "detail": "",
    }
    if not path.exists():
        if progress_path.exists():
            progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
            current = progress_payload.get("current") if isinstance(progress_payload.get("current"), dict) else {}
            current_source_name = str(current.get("source_name") or "").strip()
            completed_job_count = int(progress_payload.get("completed_job_count") or 0)
            summary = f"batch 运行中，已完成 {completed_job_count} 个 job"
            if current_source_name:
                summary += f"，当前：{current_source_name}"
            snapshot.update(
                {
                    "status": str(progress_payload.get("status") or "running"),
                    "summary": summary,
                    "report_created_at": progress_payload.get("created_at"),
                    "detail": "",
                    "progress_file": str(progress_path),
                }
            )
            return snapshot
        snapshot["detail"] = "batch_report.json not found"
        return snapshot

    payload = json.loads(path.read_text(encoding="utf-8"))
    live_readiness = payload.get("live_readiness")
    if not isinstance(live_readiness, dict):
        snapshot["report_created_at"] = payload.get("created_at")
        snapshot["detail"] = "live_readiness missing from batch report"
        return snapshot

    snapshot.update(
        {
            "status": str(live_readiness.get("status") or "unknown"),
            "gate_passed": bool(live_readiness.get("gate_passed")),
            "summary": str(live_readiness.get("summary") or ""),
            "stable_run_count": int(live_readiness.get("stable_run_count") or 0),
            "required_stable_runs": int(live_readiness.get("required_stable_runs") or 0),
            "failure_reasons": [str(item) for item in list(live_readiness.get("failure_reasons") or []) if str(item).strip()],
            "warning_reasons": [str(item) for item in list(live_readiness.get("warning_reasons") or []) if str(item).strip()],
            "golden_job_count": int(live_readiness.get("golden_job_count") or 0),
            "evaluated_job_count": int(live_readiness.get("evaluated_job_count") or 0),
            "report_created_at": payload.get("created_at"),
            "detail": "",
        }
    )
    return snapshot


def _default_batch_report_path() -> Path:
    return _repo_root() / "output" / "test" / "fullchain-batch" / "batch_report.json"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]
