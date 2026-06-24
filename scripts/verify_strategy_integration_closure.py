from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.verify_strategy_fixture_coverage import (
    DEFAULT_REQUIRED_STRATEGIES,
    load_batch_report,
    verify_strategy_fixture_coverage,
)
from scripts.verify_strategy_real_render_fixtures import verify_strategy_real_render_fixtures


STRATEGY_INTEGRATION_CLOSURE_SCHEMA = "strategy_integration_closure.v1"


def verify_strategy_integration_closure(
    *,
    content_profile_report: dict[str, Any],
    event_render_report: dict[str, Any],
    real_render_reports: list[dict[str, Any]] | None = None,
    required_strategies: list[str] | tuple[str, ...] = DEFAULT_REQUIRED_STRATEGIES,
) -> dict[str, Any]:
    strategy_coverage = verify_strategy_fixture_coverage(
        content_profile_report,
        required_strategies=required_strategies,
    )
    content_required_checks = _required_checks_summary(content_profile_report)
    render_required_checks = _required_checks_summary(event_render_report)
    narrative_preview = _required_check_status_from_rows(
        content_profile_report,
        "strategy_review_preview_evidence",
        expected_strategy_type="narrative_assembly",
    )
    narrative_preview_media = _required_check_status_from_rows(
        content_profile_report,
        "strategy_review_preview_media_evidence",
        expected_strategy_type="narrative_assembly",
    )
    event_boundary = _required_check_status_from_rows(
        event_render_report,
        "strategy_boundary_samples",
        expected_strategy_type="event_highlight",
    )
    generated_checks = {
        "strategy_pipeline_coverage": strategy_coverage,
        "content_profile_required_checks": content_required_checks,
        "narrative_review_preview_evidence": narrative_preview,
        "narrative_review_preview_media_evidence": narrative_preview_media,
        "event_highlight_render_required_checks": render_required_checks,
        "event_highlight_boundary_samples": event_boundary,
    }
    failed_generated_checks = [
        name
        for name, payload in generated_checks.items()
        if not bool(payload.get("ok") if name == "strategy_pipeline_coverage" else payload.get("passed"))
    ]
    generated_closure_ok = not failed_generated_checks
    real_render_fixture_coverage = verify_strategy_real_render_fixtures(
        list(real_render_reports or []),
        required_strategies=required_strategies,
    )
    real_media_preview_validation = (
        real_render_fixture_coverage.get("media_backed_preview_validation")
        if isinstance(real_render_fixture_coverage.get("media_backed_preview_validation"), dict)
        else {}
    )
    real_render_fixture_coverage_ok = bool(real_render_fixture_coverage.get("ok"))
    real_media_preview_validation_ok = bool(real_media_preview_validation.get("ok"))
    completion_ready = bool(
        generated_closure_ok
        and real_render_fixture_coverage_ok
        and real_media_preview_validation_ok
    )
    return {
        "schema": STRATEGY_INTEGRATION_CLOSURE_SCHEMA,
        "ok": generated_closure_ok,
        "completion_ready": completion_ready,
        "generated_closure_ok": generated_closure_ok,
        "real_render_fixture_coverage_ok": real_render_fixture_coverage_ok,
        "real_media_backed_preview_validation_ok": real_media_preview_validation_ok,
        "failed_generated_checks": failed_generated_checks,
        "checks": generated_checks,
        "real_render_fixture_coverage": real_render_fixture_coverage,
        "remaining_open_items": [
            item
            for item in [
                None if real_render_fixture_coverage_ok else "real_world_render_fixture_per_strategy",
                None
                if real_media_preview_validation_ok
                else "real_world_media_backed_storyboard_timeline_preview_validation",
            ]
            if item
        ],
    }


def _required_checks_summary(batch_report: dict[str, Any]) -> dict[str, Any]:
    summary = (
        dict(batch_report.get("required_checks") or {})
        if isinstance(batch_report.get("required_checks"), dict)
        else {}
    )
    total = int(summary.get("required_checks_total") or 0)
    failed = int(summary.get("required_checks_contract_failed") or 0)
    case_failed = int(summary.get("required_checks_case_failed") or 0)
    passed = total > 0 and failed == 0 and case_failed == 0
    return {
        "passed": passed,
        "required_checks_total": total,
        "required_checks_contract_failed": failed,
        "required_checks_case_failed": case_failed,
        "required_checks_failed_case_ids": _string_list(summary.get("required_checks_failed_case_ids")),
        "required_checks_contract_pass_rate": float(summary.get("required_checks_contract_pass_rate") or 0.0),
    }


def _required_check_status_from_rows(
    batch_report: dict[str, Any],
    check_name: str,
    *,
    expected_strategy_type: str,
) -> dict[str, Any]:
    for row in [item for item in list(batch_report.get("golden_case_rows") or []) if isinstance(item, dict)]:
        if expected_strategy_type not in _row_expected_strategy_types(row):
            continue
        statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
        status = statuses.get(check_name) if isinstance(statuses.get(check_name), dict) else {}
        if not status:
            continue
        payload = dict(status)
        payload["case_id"] = str(row.get("case_id") or "")
        payload["passed"] = bool(status.get("passed"))
        return payload
    return {
        "passed": False,
        "case_id": "",
        "detail": f"missing {check_name} status for strategy:{expected_strategy_type}",
        "missing_reasons": [f"missing_{check_name}"],
    }


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
    values.update(_string_list(risk_hints.get("expected_strategy_types")))
    statuses = row.get("required_check_statuses") if isinstance(row.get("required_check_statuses"), dict) else {}
    for status in [item for item in statuses.values() if isinstance(item, dict)]:
        values.update(_string_list(status.get("expected_strategy_types")))
    return values


def _string_list(values: Any) -> list[str]:
    return [str(item or "").strip() for item in list(values or []) if str(item or "").strip()]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify generated strategy integration closure evidence from golden reports."
    )
    parser.add_argument(
        "--content-profile-report",
        required=True,
        type=Path,
        help="Path to the five-strategy content_profile batch_report.json or report directory.",
    )
    parser.add_argument(
        "--event-render-report",
        required=True,
        type=Path,
        help="Path to the event_highlight render batch_report.json or report directory.",
    )
    parser.add_argument(
        "--real-render-report",
        action="append",
        default=[],
        type=Path,
        help="Optional real-world strategy render batch_report.json or report directory. May be repeated.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = verify_strategy_integration_closure(
        content_profile_report=load_batch_report(args.content_profile_report),
        event_render_report=load_batch_report(args.event_render_report),
        real_render_reports=[load_batch_report(path) for path in args.real_render_report],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
