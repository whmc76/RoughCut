from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.verify_strategy_fixture_coverage import DEFAULT_REQUIRED_STRATEGIES, load_batch_report


REAL_RENDER_FIXTURE_SCHEMA = "strategy_real_render_fixtures.v1"


def verify_strategy_real_render_fixtures(
    batch_reports: list[dict[str, Any]],
    *,
    required_strategies: list[str] | tuple[str, ...] = DEFAULT_REQUIRED_STRATEGIES,
) -> dict[str, Any]:
    required = [str(item or "").strip() for item in required_strategies if str(item or "").strip()]
    evidence_by_strategy: dict[str, list[dict[str, Any]]] = {strategy: [] for strategy in required}
    media_preview_evidence: list[dict[str, Any]] = []
    rejected_media_preview_cases: list[dict[str, Any]] = []
    rejected_generated_case_ids: list[str] = []
    rejected_incomplete_cases: list[dict[str, Any]] = []
    for report_index, batch_report in enumerate(batch_reports):
        jobs_by_id = {
            str(job.get("job_id") or "").strip(): job
            for job in list(batch_report.get("jobs") or [])
            if isinstance(job, dict) and str(job.get("job_id") or "").strip()
        }
        report_path = str(batch_report.get("__source_report_path") or "")
        for row in [item for item in list(batch_report.get("golden_case_rows") or []) if isinstance(item, dict)]:
            expected = _row_expected_strategy_types(row)
            if not expected:
                continue
            tags = {str(tag or "").strip() for tag in list(row.get("tags") or []) if str(tag or "").strip()}
            case_id = str(row.get("case_id") or "").strip()
            if "generated_fixture" in tags:
                if case_id:
                    rejected_generated_case_ids.append(case_id)
                continue
            if "strategy_candidate" in tags and "real_world_fixture" not in tags:
                rejected_incomplete_cases.append(
                    {
                        "case_id": case_id,
                        "job_id": str(row.get("evaluation_job_id") or row.get("job_id") or "").strip(),
                        "strategy_types": sorted(expected),
                        "reasons": ["unpromoted_strategy_candidate"],
                    }
                )
                continue
            job_id = str(row.get("evaluation_job_id") or row.get("job_id") or "").strip()
            job = jobs_by_id.get(job_id, {})
            candidate = _real_render_fixture_candidate(
                row=row,
                job=job,
                report_index=report_index,
                report_path=report_path,
            )
            if not candidate["accepted"]:
                rejected_incomplete_cases.append(
                    {
                        "case_id": case_id,
                        "job_id": job_id,
                        "strategy_types": sorted(expected),
                        "reasons": candidate["reasons"],
                    }
                )
                continue
            evidence = {
                "case_id": case_id,
                "job_id": job_id,
                "source_name": str(row.get("source_name") or job.get("source_name") or ""),
                "output_path": str(job.get("output_path") or row.get("output_path") or ""),
                "output_duration_sec": float(job.get("output_duration_sec") or row.get("output_duration_sec") or 0.0),
                "status": str(row.get("status") or job.get("status") or ""),
                "report_index": report_index,
                "report_path": report_path,
            }
            for strategy in sorted(expected):
                if strategy in evidence_by_strategy:
                    evidence_by_strategy[strategy].append(evidence)
            if "narrative_assembly" in expected:
                preview_candidate = _real_media_backed_preview_candidate(row)
                if preview_candidate["accepted"]:
                    media_preview_evidence.append(
                        {
                            **evidence,
                            "source_media_count": preview_candidate["source_media_count"],
                            "readable_media_count": preview_candidate["readable_media_count"],
                            "media_backed_segment_count": preview_candidate["media_backed_segment_count"],
                        }
                    )
                else:
                    rejected_media_preview_cases.append(
                        {
                            "case_id": case_id,
                            "job_id": job_id,
                            "reasons": preview_candidate["reasons"],
                        }
                    )
    covered = sorted(strategy for strategy, items in evidence_by_strategy.items() if items)
    missing = [strategy for strategy in required if not evidence_by_strategy.get(strategy)]
    media_preview_required = "narrative_assembly" in set(required)
    media_preview_ok = bool(media_preview_evidence) if media_preview_required else True
    return {
        "schema": REAL_RENDER_FIXTURE_SCHEMA,
        "ok": not missing,
        "required_strategy_types": required,
        "covered_strategy_types": covered,
        "missing_strategy_types": missing,
        "evidence_by_strategy": evidence_by_strategy,
        "media_backed_preview_validation": {
            "required": media_preview_required,
            "ok": media_preview_ok,
            "strategy_type": "narrative_assembly",
            "evidence": media_preview_evidence,
            "rejected_cases": rejected_media_preview_cases,
        },
        "rejected_generated_case_ids": sorted(set(rejected_generated_case_ids)),
        "rejected_incomplete_cases": rejected_incomplete_cases,
    }


def _real_render_fixture_candidate(
    *,
    row: dict[str, Any],
    job: dict[str, Any],
    report_index: int,
    report_path: str,
) -> dict[str, Any]:
    del report_index, report_path
    reasons: list[str] = []
    output_path = str(job.get("output_path") or row.get("output_path") or "").strip()
    try:
        duration = float(job.get("output_duration_sec") or row.get("output_duration_sec") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    status = str(row.get("status") or job.get("status") or "").strip().lower()
    if not output_path:
        reasons.append("missing_output_path")
    if duration <= 0.0:
        reasons.append("missing_output_duration")
    if status not in {"done", "partial"}:
        reasons.append(f"non_passing_status={status or 'unknown'}")
    if not bool(row.get("required_checks_passed")):
        reasons.append("required_checks_not_passed")
    statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
    pipeline = statuses.get("strategy_pipeline_coverage") if isinstance(statuses.get("strategy_pipeline_coverage"), dict) else {}
    if not bool(pipeline.get("passed")):
        reasons.append("strategy_pipeline_coverage_not_passed")
    return {"accepted": not reasons, "reasons": reasons}


def _real_media_backed_preview_candidate(row: dict[str, Any]) -> dict[str, Any]:
    reasons: list[str] = []
    statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
    preview = (
        statuses.get("strategy_review_preview_media_evidence")
        if isinstance(statuses.get("strategy_review_preview_media_evidence"), dict)
        else {}
    )
    if not preview:
        reasons.append("missing_strategy_review_preview_media_evidence")
    elif not bool(preview.get("passed")):
        reasons.append("strategy_review_preview_media_evidence_not_passed")
    source_media_count = _int_value(preview.get("source_media_count"))
    readable_media_count = _int_value(preview.get("readable_media_count"))
    media_backed_segment_count = _int_value(preview.get("media_backed_segment_count"))
    if source_media_count <= 0:
        reasons.append("missing_source_media_evidence")
    if readable_media_count <= 0:
        reasons.append("missing_readable_media_evidence")
    if media_backed_segment_count <= 0:
        reasons.append("missing_media_backed_preview_segments")
    return {
        "accepted": not reasons,
        "reasons": reasons,
        "source_media_count": source_media_count,
        "readable_media_count": readable_media_count,
        "media_backed_segment_count": media_backed_segment_count,
    }


def _int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _row_expected_strategy_types(row: dict[str, Any]) -> set[str]:
    values = {
        str(tag).split(":", 1)[1].strip()
        for tag in list(row.get("tags") or [])
        if str(tag).strip().startswith("strategy:") and str(tag).split(":", 1)[1].strip()
    }
    risk_hints = row.get("risk_hints") if isinstance(row.get("risk_hints"), dict) else {}
    for key in ("expected_strategy_type", "strategy_type"):
        value = str(risk_hints.get(key) or "").strip()
        if value:
            values.add(value)
    values.update(str(item or "").strip() for item in list(risk_hints.get("expected_strategy_types") or []) if str(item or "").strip())
    statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
    for status in [item for item in statuses.values() if isinstance(item, dict)]:
        values.update(
            str(item or "").strip()
            for item in list(status.get("expected_strategy_types") or [])
            if str(item or "").strip()
        )
    return values


def _parse_required_strategies(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed or list(DEFAULT_REQUIRED_STRATEGIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify real-world render fixture coverage for strategy-specific pipelines."
    )
    parser.add_argument(
        "--report",
        action="append",
        required=True,
        type=Path,
        help="Path to batch_report.json or report directory. May be repeated.",
    )
    parser.add_argument(
        "--required-strategy",
        action="append",
        default=[],
        help="Required strategy type. May be repeated or comma-separated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    reports = []
    for path in args.report:
        payload = load_batch_report(path)
        payload["__source_report_path"] = str(path)
        reports.append(payload)
    result = verify_strategy_real_render_fixtures(
        reports,
        required_strategies=_parse_required_strategies(args.required_strategy),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
