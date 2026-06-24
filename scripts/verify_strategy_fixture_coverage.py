from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_REQUIRED_STRATEGIES = (
    "information_density",
    "step_demonstration",
    "experience_and_mood",
    "event_highlight",
    "narrative_assembly",
)


def load_batch_report(path: Path) -> dict[str, Any]:
    report_path = path / "batch_report.json" if path.is_dir() else path
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"batch report must be a JSON object: {report_path}")
    return payload


def extract_strategy_pipeline_coverage(batch_report: dict[str, Any]) -> dict[str, Any]:
    existing = (
        batch_report.get("strategy_pipeline_coverage")
        if isinstance(batch_report.get("strategy_pipeline_coverage"), dict)
        else {}
    )
    if existing:
        return {
            "evaluated_case_count": int(existing.get("evaluated_case_count") or 0),
            "declared_strategy_types": _string_list(existing.get("declared_strategy_types")),
            "covered_strategy_types": _string_list(existing.get("covered_strategy_types")),
            "missing_strategy_types": _string_list(existing.get("missing_strategy_types")),
            "failed_case_ids": _string_list(existing.get("failed_case_ids")),
            "observed_strategy_types": _string_list(existing.get("observed_strategy_types")),
            "source": "strategy_pipeline_coverage",
        }

    declared: set[str] = set()
    covered: set[str] = set()
    missing: set[str] = set()
    observed: set[str] = set()
    failed_case_ids: list[str] = []
    evaluated_case_count = 0
    for row in [dict(item) for item in list(batch_report.get("golden_case_rows") or []) if isinstance(item, dict)]:
        expected = _expected_strategy_types_from_case_row(row)
        statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
        status = statuses.get("strategy_pipeline_coverage") if isinstance(statuses.get("strategy_pipeline_coverage"), dict) else {}
        if status:
            expected.update(_string_list(status.get("expected_strategy_types")))
            row_observed = set(_string_list(status.get("observed_strategy_types")))
            row_missing = set(_string_list(status.get("missing_strategy_types")))
            row_passed = bool(status.get("passed"))
        else:
            row_observed = set()
            row_missing = set(expected)
            row_passed = not expected
        if not expected and not status:
            continue
        evaluated_case_count += 1
        declared.update(expected)
        observed.update(row_observed)
        matched = expected.intersection(row_observed)
        covered.update(matched)
        missing.update(row_missing or (expected - matched))
        if not row_passed or (expected and expected - matched):
            case_id = str(row.get("case_id") or "").strip()
            if case_id:
                failed_case_ids.append(case_id)

    for job in [dict(item) for item in list(batch_report.get("jobs") or []) if isinstance(item, dict)]:
        observed.update(_strategy_types_from_payload(job.get("content_profile")))
        render_diagnostics = job.get("render_diagnostics") if isinstance(job.get("render_diagnostics"), dict) else {}
        observed.update(_strategy_types_from_payload(render_diagnostics.get("strategy_render_validation")))

    return {
        "evaluated_case_count": evaluated_case_count,
        "declared_strategy_types": sorted(declared),
        "covered_strategy_types": sorted(covered),
        "missing_strategy_types": sorted(missing),
        "failed_case_ids": failed_case_ids,
        "observed_strategy_types": sorted(observed),
        "source": "derived",
    }


def verify_strategy_fixture_coverage(
    batch_report: dict[str, Any],
    *,
    required_strategies: list[str] | tuple[str, ...] = DEFAULT_REQUIRED_STRATEGIES,
) -> dict[str, Any]:
    coverage = extract_strategy_pipeline_coverage(batch_report)
    covered = {
        str(item or "").strip()
        for item in list(coverage.get("covered_strategy_types") or [])
        if str(item or "").strip()
    }
    declared = {
        str(item or "").strip()
        for item in list(coverage.get("declared_strategy_types") or [])
        if str(item or "").strip()
    }
    failed_case_ids = [
        str(item or "").strip()
        for item in list(coverage.get("failed_case_ids") or [])
        if str(item or "").strip()
    ]
    required = [str(item or "").strip() for item in required_strategies if str(item or "").strip()]
    missing = [strategy for strategy in required if strategy not in covered]
    undeclared = [strategy for strategy in required if strategy not in declared]
    passed = not missing and not failed_case_ids and int(coverage.get("evaluated_case_count") or 0) > 0
    return {
        "ok": passed,
        "required_strategy_types": required,
        "declared_strategy_types": sorted(declared),
        "covered_strategy_types": sorted(covered),
        "missing_strategy_types": missing,
        "undeclared_strategy_types": undeclared,
        "failed_case_ids": failed_case_ids,
        "observed_strategy_types": _string_list(coverage.get("observed_strategy_types")),
        "evaluated_case_count": int(coverage.get("evaluated_case_count") or 0),
        "coverage_source": str(coverage.get("source") or ""),
    }


def _string_list(values: Any) -> list[str]:
    return [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]


def _expected_strategy_types_from_case_row(row: dict[str, Any]) -> set[str]:
    expected = {
        str(tag).split(":", 1)[1].strip()
        for tag in list(row.get("tags") or [])
        if str(tag).strip().startswith("strategy:") and str(tag).split(":", 1)[1].strip()
    }
    risk_hints = row.get("risk_hints") if isinstance(row.get("risk_hints"), dict) else {}
    for key in ("expected_strategy_type", "strategy_type"):
        value = str(risk_hints.get(key) or "").strip()
        if value:
            expected.add(value)
    expected.update(_string_list(risk_hints.get("expected_strategy_types")))
    return expected


def _strategy_types_from_payload(payload: Any) -> set[str]:
    data = payload if isinstance(payload, dict) else {}
    if not data:
        return set()
    found: set[str] = set()
    candidates: list[dict[str, Any]] = [data]
    for key in ("capability_orchestration", "pipeline_plan", "strategy_review_context", "strategy_review_gates"):
        value = data.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in list(candidates):
        gates = candidate.get("strategy_review_gates") if isinstance(candidate.get("strategy_review_gates"), dict) else {}
        plan = gates.get("pipeline_plan") if isinstance(gates.get("pipeline_plan"), dict) else {}
        if plan:
            candidates.append(plan)
        nested_plan = candidate.get("pipeline_plan") if isinstance(candidate.get("pipeline_plan"), dict) else {}
        if nested_plan:
            candidates.append(nested_plan)
    for candidate in candidates:
        strategy_type = str(candidate.get("strategy_type") or "").strip()
        if strategy_type:
            found.add(strategy_type)
    return found


def _parse_required_strategies(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed or list(DEFAULT_REQUIRED_STRATEGIES)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that a golden batch report covers the required strategy fixture set."
    )
    parser.add_argument(
        "report",
        type=Path,
        help="Path to batch_report.json or a report directory containing batch_report.json.",
    )
    parser.add_argument(
        "--required-strategy",
        action="append",
        default=[],
        help="Required strategy type. May be repeated or comma-separated. Defaults to the full strategy registry.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify_strategy_fixture_coverage(
        load_batch_report(args.report),
        required_strategies=_parse_required_strategies(args.required_strategy),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
