from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify render-failure signal consistency inside a golden/batch report directory."
    )
    parser.add_argument("--report-dir", type=Path, required=True, help="Directory containing batch_report.json.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _job_failure_signals(batch_report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in list(batch_report.get("jobs") or []):
        if not isinstance(job, dict):
            continue
        diagnostics = job.get("render_diagnostics") if isinstance(job.get("render_diagnostics"), dict) else {}
        render_step = diagnostics.get("render_step") if isinstance(diagnostics.get("render_step"), dict) else {}
        avatar_result = diagnostics.get("avatar_result") if isinstance(diagnostics.get("avatar_result"), dict) else {}
        render_failed = str(render_step.get("status") or "").strip().lower() == "failed"
        avatar_degraded = str(avatar_result.get("status") or "").strip().lower() == "degraded"
        if not render_failed and not avatar_degraded:
            continue
        rows.append(
            {
                "job_id": str(job.get("job_id") or ""),
                "source_name": str(job.get("source_name") or ""),
                "render_failed": render_failed,
                "render_reason": str(render_step.get("reason") or ""),
                "render_issue_codes": list(render_step.get("issue_codes") or []),
                "avatar_degraded": avatar_degraded,
                "avatar_reason": str(avatar_result.get("reason") or ""),
                "avatar_reason_category": str(avatar_result.get("reason_category") or ""),
            }
        )
    return rows


def _scorecard_render_fail_job_ids(scorecard: dict[str, Any]) -> list[str]:
    job_ids: list[str] = []
    for job in list(scorecard.get("jobs") or []):
        if not isinstance(job, dict):
            continue
        stages = list(job.get("live_stage_scores") or [])
        render_stage = next(
            (
                item
                for item in stages
                if isinstance(item, dict) and str(item.get("stage") or "").strip() == "render"
            ),
            None,
        )
        if render_stage and str(render_stage.get("status") or "").strip().lower() == "fail":
            job_id = str(job.get("job_id") or "").strip()
            if job_id:
                job_ids.append(job_id)
    return job_ids


def _audit_snapshot_job_ids(report_dir: Path) -> list[str]:
    audit_dir = report_dir / "audit_packs"
    if not audit_dir.exists():
        return []
    job_ids: list[str] = []
    for path in sorted(audit_dir.glob("*.snapshot.json")):
        try:
            payload = _load_json(path)
        except Exception:
            continue
        job = payload.get("job") if isinstance(payload.get("job"), dict) else {}
        job_id = str(job.get("id") or "").strip()
        if job_id:
            job_ids.append(job_id)
    return job_ids


def verify_render_failure_signal_consistency(report_dir: Path) -> dict[str, Any]:
    batch_report_path = report_dir / "batch_report.json"
    scorecard_path = report_dir / "detailed_output_scorecard.json"
    batch_report = _load_json(batch_report_path)
    scorecard = _load_json(scorecard_path) if scorecard_path.exists() else {}

    job_signals = _job_failure_signals(batch_report)
    job_failed_ids = [item["job_id"] for item in job_signals if item.get("render_failed")]
    summary = batch_report.get("render_diagnostics_summary") if isinstance(batch_report.get("render_diagnostics_summary"), dict) else {}
    summary_failed_ids = [str(item) for item in list(summary.get("failed_render_job_ids") or []) if str(item).strip()]
    live_readiness = batch_report.get("live_readiness") if isinstance(batch_report.get("live_readiness"), dict) else {}
    live_checks = live_readiness.get("checks") if isinstance(live_readiness.get("checks"), dict) else {}
    render_end_state = live_checks.get("render_end_state_stability") if isinstance(live_checks.get("render_end_state_stability"), dict) else {}
    live_failed_ids = [str(item) for item in list(render_end_state.get("failed_render_job_ids") or []) if str(item).strip()]
    scorecard_live = scorecard.get("live_readiness") if isinstance(scorecard.get("live_readiness"), dict) else {}
    scorecard_has_failed_checks_field = "failed_checks" in scorecard_live
    scorecard_failed_checks = [str(item) for item in list(scorecard_live.get("failed_checks") or []) if str(item).strip()]
    scorecard_render_fail_ids = _scorecard_render_fail_job_ids(scorecard)
    audit_snapshot_ids = _audit_snapshot_job_ids(report_dir)

    checks = {
        "batch_summary_matches_job_failures": sorted(summary_failed_ids) == sorted(job_failed_ids),
        "live_readiness_matches_job_failures": sorted(live_failed_ids) == sorted(job_failed_ids),
        "scorecard_failed_checks_mentions_render_gate": (
            ("render_end_state_stability" in scorecard_failed_checks)
            if job_failed_ids and scorecard_has_failed_checks_field
            else True
        ),
        "scorecard_render_stage_matches_job_failures": sorted(scorecard_render_fail_ids) == sorted(job_failed_ids),
        "audit_snapshots_cover_failed_jobs": all(job_id in audit_snapshot_ids for job_id in job_failed_ids),
    }

    return {
        "report_dir": str(report_dir),
        "job_failure_signals": job_signals,
        "batch_render_diagnostics_summary_failed_job_ids": summary_failed_ids,
        "live_readiness_failed_render_job_ids": live_failed_ids,
        "scorecard_failed_checks": scorecard_failed_checks,
        "scorecard_render_fail_job_ids": scorecard_render_fail_ids,
        "audit_snapshot_job_ids": audit_snapshot_ids,
        "checks": checks,
        "ok": all(bool(value) for value in checks.values()),
    }


def _render_text(result: dict[str, Any]) -> str:
    lines = [f"report_dir={result.get('report_dir')}", f"ok={str(bool(result.get('ok'))).lower()}"]
    for item in list(result.get("job_failure_signals") or []):
        lines.append(
            "job="
            f"{item.get('job_id')} source={item.get('source_name')} "
            f"render_failed={item.get('render_failed')} render_reason={item.get('render_reason')} "
            f"avatar_degraded={item.get('avatar_degraded')} avatar_reason={item.get('avatar_reason')}"
        )
    for key, value in dict(result.get("checks") or {}).items():
        lines.append(f"{key}={str(bool(value)).lower()}")
    return "\n".join(lines)


def main() -> int:
    args = parse_args()
    result = verify_render_failure_signal_consistency(args.report_dir)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_render_text(result))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
