from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two live batch runs and generate a retrospective report.")
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, default=None)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sibling_json(report_path: Path, name: str) -> dict[str, Any]:
    return _load_json(report_path.with_name(name))


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _job_map(batch_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in batch_report.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or "").strip()
        if source_name:
            result[source_name] = item
    return result


def _pollution_map(audit_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in audit_report.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or "").strip()
        if source_name:
            result[source_name] = item
    return result


def _scorecard_map(scorecard_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in scorecard_report.get("jobs") or []:
        if not isinstance(item, dict):
            continue
        source_name = str(item.get("source_name") or "").strip()
        if source_name:
            result[source_name] = item
    return result


def _aggregate_dimension_map(scorecard_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in scorecard_report.get("aggregate_dimension_scores") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("dimension") or "").strip()
        if name:
            result[name] = item
    return result


def _compare_status(before: str, after: str) -> str:
    normalized_before = str(before or "").strip().lower()
    normalized_after = str(after or "").strip().lower()
    if normalized_before == normalized_after:
        return "unchanged"
    if normalized_before != "done" and normalized_after == "done":
        return "improved"
    if normalized_before == "done" and normalized_after != "done":
        return "regressed"
    return "changed"


def _compare_manual_review(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_flag = bool(before.get("manual_review_required"))
    after_flag = bool(after.get("manual_review_required"))
    if before_flag == after_flag:
        return "unchanged"
    if before_flag and not after_flag:
        return "improved"
    if not before_flag and after_flag:
        return "regressed"
    return "changed"


def _aggregate_summary(batch_report: dict[str, Any], audit_report: dict[str, Any], scorecard_report: dict[str, Any]) -> dict[str, Any]:
    jobs = [item for item in batch_report.get("jobs") or [] if isinstance(item, dict)]
    audit_jobs = [item for item in audit_report.get("jobs") or [] if isinstance(item, dict)]
    dimensions = _aggregate_dimension_map(scorecard_report)
    return {
        "job_count": len(jobs),
        "success_count": int(batch_report.get("success_count") or 0),
        "failed_count": int(batch_report.get("failed_count") or 0),
        "manual_review_required_count": sum(1 for item in audit_jobs if bool(item.get("manual_review_required"))),
        "critical_pollution_count": sum(1 for item in audit_jobs if str(item.get("severity") or "") == "critical"),
        "overall_video_quality": _safe_float((dimensions.get("overall_video_quality") or {}).get("score")),
        "subtitle_quality": _safe_float((dimensions.get("subtitle_quality") or {}).get("score")),
        "multi_platform_package": _safe_float((dimensions.get("multi_platform_package") or {}).get("score")),
        "avatar": _safe_float((dimensions.get("avatar") or {}).get("score")),
        "ai_effects": _safe_float((dimensions.get("ai_effects") or {}).get("score")),
        "subtitle_effects": _safe_float((dimensions.get("subtitle_effects") or {}).get("score")),
        "editing": _safe_float((dimensions.get("editing") or {}).get("score")),
    }


def build_comparison(
    *,
    baseline_report_path: Path,
    candidate_report_path: Path,
) -> dict[str, Any]:
    baseline_batch = _load_json(baseline_report_path)
    candidate_batch = _load_json(candidate_report_path)
    baseline_audit = _sibling_json(baseline_report_path, "subtitle_pollution_audit.json")
    candidate_audit = _sibling_json(candidate_report_path, "subtitle_pollution_audit.json")
    baseline_scorecard = _sibling_json(baseline_report_path, "detailed_output_scorecard.json")
    candidate_scorecard = _sibling_json(candidate_report_path, "detailed_output_scorecard.json")

    baseline_jobs = _job_map(baseline_batch)
    candidate_jobs = _job_map(candidate_batch)
    baseline_pollution = _pollution_map(baseline_audit)
    candidate_pollution = _pollution_map(candidate_audit)
    baseline_scorecards = _scorecard_map(baseline_scorecard)
    candidate_scorecards = _scorecard_map(candidate_scorecard)

    all_sources = []
    for source_name in [*baseline_jobs.keys(), *candidate_jobs.keys()]:
        if source_name not in all_sources:
            all_sources.append(source_name)

    per_source: list[dict[str, Any]] = []
    for source_name in all_sources:
        before_job = baseline_jobs.get(source_name, {})
        after_job = candidate_jobs.get(source_name, {})
        before_pollution = baseline_pollution.get(source_name, {})
        after_pollution = candidate_pollution.get(source_name, {})
        before_scorecard = baseline_scorecards.get(source_name, {})
        after_scorecard = candidate_scorecards.get(source_name, {})

        per_source.append(
            {
                "source_name": source_name,
                "status_before": str(before_job.get("status") or ""),
                "status_after": str(after_job.get("status") or ""),
                "status_change": _compare_status(before_job.get("status"), after_job.get("status")),
                "quality_score_before": _safe_float(before_job.get("quality_score")),
                "quality_score_after": _safe_float(after_job.get("quality_score")),
                "quality_issue_codes_before": list(before_job.get("quality_issue_codes") or []),
                "quality_issue_codes_after": list(after_job.get("quality_issue_codes") or []),
                "manual_review_required_before": bool(before_pollution.get("manual_review_required")),
                "manual_review_required_after": bool(after_pollution.get("manual_review_required")),
                "manual_review_change": _compare_manual_review(before_pollution, after_pollution),
                "pollution_severity_before": str(before_pollution.get("severity") or ""),
                "pollution_severity_after": str(after_pollution.get("severity") or ""),
                "blocking_count_before": int(before_pollution.get("blocking_count") or 0),
                "blocking_count_after": int(after_pollution.get("blocking_count") or 0),
                "warning_count_before": int(before_pollution.get("warning_count") or 0),
                "warning_count_after": int(after_pollution.get("warning_count") or 0),
                "subtitle_quality_before": _safe_float((before_scorecard.get("subtitle_quality") or {}).get("score")),
                "subtitle_quality_after": _safe_float((after_scorecard.get("subtitle_quality") or {}).get("score")),
                "editing_before": _safe_float((before_scorecard.get("editing") or {}).get("score")),
                "editing_after": _safe_float((after_scorecard.get("editing") or {}).get("score")),
            }
        )

    baseline_summary = _aggregate_summary(baseline_batch, baseline_audit, baseline_scorecard)
    candidate_summary = _aggregate_summary(candidate_batch, candidate_audit, candidate_scorecard)

    return {
        "baseline_report": str(baseline_report_path),
        "candidate_report": str(candidate_report_path),
        "baseline_summary": baseline_summary,
        "candidate_summary": candidate_summary,
        "per_source": per_source,
    }


def _render_delta(before: float | None, after: float | None) -> str:
    if before is None and after is None:
        return "-"
    if before is None:
        return f"n/a -> {after}"
    if after is None:
        return f"{before} -> n/a"
    delta = round(after - before, 1)
    sign = "+" if delta > 0 else ""
    return f"{before} -> {after} ({sign}{delta})"


def render_markdown(report: dict[str, Any]) -> str:
    baseline = report.get("baseline_summary") or {}
    candidate = report.get("candidate_summary") or {}
    lines = [
        "# Live Batch Retrospective",
        "",
        f"- baseline_report: {report.get('baseline_report') or ''}",
        f"- candidate_report: {report.get('candidate_report') or ''}",
        "",
        "## Aggregate",
        "",
        f"- success_count: {baseline.get('success_count')} -> {candidate.get('success_count')}",
        f"- failed_count: {baseline.get('failed_count')} -> {candidate.get('failed_count')}",
        f"- manual_review_required_count: {baseline.get('manual_review_required_count')} -> {candidate.get('manual_review_required_count')}",
        f"- critical_pollution_count: {baseline.get('critical_pollution_count')} -> {candidate.get('critical_pollution_count')}",
        f"- overall_video_quality: {_render_delta(_safe_float(baseline.get('overall_video_quality')), _safe_float(candidate.get('overall_video_quality')))}",
        f"- subtitle_quality: {_render_delta(_safe_float(baseline.get('subtitle_quality')), _safe_float(candidate.get('subtitle_quality')))}",
        f"- multi_platform_package: {_render_delta(_safe_float(baseline.get('multi_platform_package')), _safe_float(candidate.get('multi_platform_package')))}",
        f"- avatar: {_render_delta(_safe_float(baseline.get('avatar')), _safe_float(candidate.get('avatar')))}",
        f"- ai_effects: {_render_delta(_safe_float(baseline.get('ai_effects')), _safe_float(candidate.get('ai_effects')))}",
        f"- subtitle_effects: {_render_delta(_safe_float(baseline.get('subtitle_effects')), _safe_float(candidate.get('subtitle_effects')))}",
        f"- editing: {_render_delta(_safe_float(baseline.get('editing')), _safe_float(candidate.get('editing')))}",
        "",
        "## Per Source",
        "",
    ]

    for item in report.get("per_source") or []:
        lines.extend(
            [
                f"### {item.get('source_name') or ''}",
                "",
                f"- status: {item.get('status_before')} -> {item.get('status_after')} ({item.get('status_change')})",
                f"- quality_score: {_render_delta(_safe_float(item.get('quality_score_before')), _safe_float(item.get('quality_score_after')))}",
                f"- manual_review_required: {str(bool(item.get('manual_review_required_before'))).lower()} -> {str(bool(item.get('manual_review_required_after'))).lower()} ({item.get('manual_review_change')})",
                f"- pollution_severity: {item.get('pollution_severity_before')} -> {item.get('pollution_severity_after')}",
                f"- blocking_count: {item.get('blocking_count_before')} -> {item.get('blocking_count_after')}",
                f"- warning_count: {item.get('warning_count_before')} -> {item.get('warning_count_after')}",
                f"- subtitle_quality: {_render_delta(_safe_float(item.get('subtitle_quality_before')), _safe_float(item.get('subtitle_quality_after')))}",
                f"- editing: {_render_delta(_safe_float(item.get('editing_before')), _safe_float(item.get('editing_after')))}",
                f"- issue_codes_before: {', '.join(item.get('quality_issue_codes_before') or []) or '-'}",
                f"- issue_codes_after: {', '.join(item.get('quality_issue_codes_after') or []) or '-'}",
                "",
            ]
        )

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    args = parse_args()
    report = build_comparison(
        baseline_report_path=args.baseline_report.resolve(),
        candidate_report_path=args.candidate_report.resolve(),
    )

    output_json = args.output_json or args.candidate_report.with_name("live_batch_retrospective.json")
    output_md = args.output_md or args.candidate_report.with_name("live_batch_retrospective.md")
    output_json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "output_json": str(output_json),
                "output_md": str(output_md),
                "per_source_count": len(report.get("per_source") or []),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
