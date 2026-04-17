from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
        for code in list(item.get("issue_codes") or []):
            normalized = str(code).strip()
            if normalized and normalized not in codes:
                codes.append(normalized)
    return codes


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
        output_path = str(job.get("output_path") or "").strip()
        false_success = bool(
            job.get("status") == "done"
            and (not output_path or float(job.get("output_duration_sec") or 0.0) <= 0.0 or stage_failures)
        )
        if false_success and source_name:
            false_success_jobs.append(source_name)
        if (job.get("status") != "done" or false_success or stage_failures) and source_name:
            p0_blocker_jobs.append(source_name)
        for code in collect_job_issue_codes(job):
            issue_code_counts[code] = issue_code_counts.get(code, 0) + 1

    evaluated_count = len(evaluated_jobs)
    successful_jobs = sum(1 for job in evaluated_jobs if str(job.get("status") or "") == "done")
    success_rate = (successful_jobs / evaluated_count) if evaluated_count else 0.0
    quality_scores = [float(job.get("quality_score")) for job in evaluated_jobs if job.get("quality_score") is not None]
    average_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else None
    failure_reasons: list[str] = []
    warning_reasons: list[str] = []
    checks = {
        "stable_runs": {
            "passed": False,
            "actual": 0,
            "required": required_stable_runs,
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
            "passed": all(bool(collect_job_issue_codes(job)) for job in evaluated_jobs if str(job.get("status") or "") != "done"),
            "actual": sum(1 for job in evaluated_jobs if collect_job_issue_codes(job)),
            "required": sum(1 for job in evaluated_jobs if str(job.get("status") or "") != "done"),
        },
    }
    if not golden_source_names:
        warning_reasons.append("未显式提供 golden jobs，当前按本次 batch 全量样本评估")

    historical_runs = [*(previous_summaries or []), summary]
    stable_run_count = 0
    for candidate in reversed(historical_runs):
        candidate_jobs = [dict(item) for item in list(candidate.get("jobs") or []) if isinstance(item, dict)]
        if golden_set:
            candidate_jobs = [job for job in candidate_jobs if str(job.get("source_name") or "").strip() in golden_set]
        if not candidate_jobs:
            break
        candidate_success_rate = sum(1 for job in candidate_jobs if str(job.get("status") or "") == "done") / len(candidate_jobs)
        candidate_quality_scores = [float(job.get("quality_score")) for job in candidate_jobs if job.get("quality_score") is not None]
        candidate_avg_quality = (sum(candidate_quality_scores) / len(candidate_quality_scores)) if candidate_quality_scores else None
        candidate_false_success = any(
            str(job.get("status") or "") == "done"
            and (
                not str(job.get("output_path") or "").strip()
                or float(job.get("output_duration_sec") or 0.0) <= 0.0
                or any(isinstance(item, dict) and item.get("status") == "fail" for item in list(job.get("live_stage_validations") or []))
            )
            for job in candidate_jobs
        )
        candidate_p0 = any(
            str(job.get("status") or "") != "done"
            or candidate_false_success
            or any(isinstance(item, dict) and item.get("status") == "fail" for item in list(job.get("live_stage_validations") or []))
            for job in candidate_jobs
        )
        if (
            candidate_success_rate >= required_success_rate
            and candidate_avg_quality is not None
            and candidate_avg_quality >= required_average_quality
            and not candidate_false_success
            and not candidate_p0
        ):
            stable_run_count += 1
            continue
        break
    checks["stable_runs"]["actual"] = stable_run_count
    checks["stable_runs"]["passed"] = stable_run_count >= required_stable_runs

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
        required_stable_runs=required_stable_runs,
    )


def load_live_readiness_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path else _default_batch_report_path()
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
