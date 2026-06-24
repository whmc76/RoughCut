from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.build_strategy_replay_fixture_manifest import DEFAULT_OUTPUT_DIR
from scripts.verify_strategy_fixture_coverage import load_batch_report
from scripts.verify_strategy_real_render_fixtures import verify_strategy_real_render_fixtures


STRATEGY_FIXTURE_EXECUTION_PLAN_SCHEMA = "strategy_fixture_execution_plan.v1"
DEFAULT_CONTENT_PROFILE_REPORT_ROOT = "output/test/strategy-candidate-golden"
DEFAULT_RENDER_REPORT_ROOT = "output/test/strategy-candidate-render-golden"
GENERATED_CONTENT_PROFILE_REPORT = "output/test/strategy-replay-golden/20260624-124208/batch_report.json"
GENERATED_EVENT_RENDER_REPORT = "output/test/strategy-replay-render-golden/20260624-130307/batch_report.json"
RUNTIME_PREFLIGHT_COMMAND = (
    "uv run python scripts/check_strategy_fixture_runtime_preflight.py"
    " --output output/test/strategy-fixture-runtime-preflight.json"
)
REFERENCE_REPORT_PATH = "output/test/strategy-real-render-reference-report/batch_report.json"
PROMOTED_MANIFEST_PATH = "output/test/strategy-fixture-candidates.promoted.manifest.v1.json"


def build_strategy_fixture_execution_plan(
    manifest: dict[str, Any],
    *,
    manifest_path: str,
    content_profile_report_root: str = DEFAULT_CONTENT_PROFILE_REPORT_ROOT,
    render_report_root: str = DEFAULT_RENDER_REPORT_ROOT,
    candidate_summary: dict[str, Any] | None = None,
    candidate_summary_path: str = "",
    real_render_reports: list[dict[str, Any]] | None = None,
    real_render_report_paths: list[str] | None = None,
    rejection_reports: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    required = _string_list(manifest.get("required_strategy_types"))
    manifest_real_ready = set(_string_list(manifest.get("real_render_ready_strategy_types")))
    report_real_ready = _real_render_report_ready_by_strategy(real_render_reports or [], required_strategies=required)
    real_ready = set(manifest_real_ready) | set(report_real_ready)
    reference_ready = _reference_evidence_ready_by_strategy(
        candidate_summary or {},
        required_strategies=[strategy for strategy in required if strategy not in real_ready],
    )
    effective_real_ready = set(real_ready) | set(reference_ready)
    jobs = [item for item in list(manifest.get("jobs") or []) if isinstance(item, dict)]
    jobs_by_strategy = {_job_strategy_type(job): job for job in jobs if _job_strategy_type(job)}
    rejected_cases = _collect_render_unsuitable_cases(rejection_reports or [])
    missing_manifest = [strategy for strategy in required if strategy not in jobs_by_strategy]
    strategy_plans = []
    for strategy in required:
        job = jobs_by_strategy.get(strategy, {})
        case_id = str(job.get("case_id") or "").strip()
        required_checks = _string_list(job.get("required_checks"))
        tags = _string_list(job.get("tags"))
        reference_evidence = reference_ready.get(strategy) or {}
        report_evidence = report_real_ready.get(strategy) or {}
        reference_evidence_ready = bool(reference_evidence)
        report_evidence_ready = bool(report_evidence)
        render_ready = strategy in effective_real_ready
        rejection = rejected_cases.get(case_id) if case_id else None
        render_unsuitable = bool(rejection)
        missing_manifest_case = not bool(job)
        needs_real_render_rerun = bool(job) and not render_ready and not render_unsuitable
        needs_replacement_fixture = not render_ready and (missing_manifest_case or (bool(job) and render_unsuitable))
        strategy_plans.append(
            {
                "strategy_type": strategy,
                "agent_lane": _agent_lane_for_strategy(strategy, needs_replacement_fixture=needs_replacement_fixture),
                "case_id": case_id,
                "reference_job_id": str(job.get("reference_job_id") or "").strip(),
                "source_status": _source_status(
                    job=job,
                    render_unsuitable=render_unsuitable,
                    reference_evidence_ready=reference_evidence_ready,
                    report_evidence_ready=report_evidence_ready,
                ),
                "real_render_ready": render_ready,
                "reference_evidence_ready": reference_evidence_ready,
                "reference_evidence": reference_evidence,
                "real_render_report_evidence_ready": report_evidence_ready,
                "real_render_report_evidence": report_evidence,
                "render_unsuitable": render_unsuitable,
                "render_unsuitable_evidence": rejection or {},
                "needs_replacement_fixture": needs_replacement_fixture,
                "required_checks": required_checks,
                "promotion_required_for_real_closure": (
                    not reference_evidence_ready
                    and not report_evidence_ready
                    and "strategy_candidate" in tags
                    and "real_world_fixture" not in tags
                ),
                "promotion_tag": "real_world_fixture",
                "promotion_command": _promotion_command(manifest_path=manifest_path, strategy=strategy)
                if (
                    render_ready
                    and not reference_evidence_ready
                    and not report_evidence_ready
                    and "strategy_candidate" in tags
                    and "real_world_fixture" not in tags
                )
                else "",
                "content_profile_smoke_command": _golden_command(
                    manifest_path=manifest_path,
                    case_id=case_id,
                    report_dir=f"{content_profile_report_root}/{strategy}",
                    stop_after="content_profile",
                )
                if case_id
                else "",
                "render_fixture_command": _golden_command(
                    manifest_path=manifest_path,
                    case_id=case_id,
                    report_dir=f"{render_report_root}/{strategy}",
                    stop_after="render",
                )
                if case_id and not render_unsuitable
                else "",
                "replacement_fixture_guidance": _replacement_fixture_guidance(strategy, rejection)
                if needs_replacement_fixture
                else "",
                "needs_real_render_rerun": needs_real_render_rerun,
                "runtime_preflight_required": needs_real_render_rerun,
                "runtime_preflight_command": RUNTIME_PREFLIGHT_COMMAND if needs_real_render_rerun else "",
                "blocking_checks_for_completion": _completion_blocking_checks(
                    strategy=strategy,
                    real_render_ready=render_ready,
                    required_checks=[] if report_evidence_ready else required_checks,
                    render_unsuitable=render_unsuitable and not render_ready,
                    missing_manifest_case=missing_manifest_case and not render_ready,
                ),
            }
        )
    real_missing = [item["strategy_type"] for item in strategy_plans if not item.get("real_render_ready")]
    real_reruns = [item["strategy_type"] for item in strategy_plans if item.get("needs_real_render_rerun")]
    replacement_needed = [item["strategy_type"] for item in strategy_plans if item.get("needs_replacement_fixture")]
    reference_report_command = _reference_report_command(
        candidate_summary_path=candidate_summary_path,
        reference_strategies=[strategy for strategy in required if strategy in reference_ready],
    )
    real_report_placeholders = _string_list(real_render_report_paths or []) or [REFERENCE_REPORT_PATH]
    real_report_placeholders.extend(
        f"{render_report_root}/{strategy}/<timestamp>/batch_report.json"
        for strategy in real_missing
        if f"{render_report_root}/{strategy}/<timestamp>/batch_report.json" not in real_report_placeholders
    )
    return {
        "schema": STRATEGY_FIXTURE_EXECUTION_PLAN_SCHEMA,
        "manifest_path": manifest_path,
        "manifest_schema": str(manifest.get("schema") or ""),
        "ok": not missing_manifest,
        "completion_ready": not missing_manifest and not real_missing,
        "required_strategy_types": required,
        "manifest_ready_strategy_types": [strategy for strategy in required if strategy in jobs_by_strategy],
        "missing_manifest_strategy_types": missing_manifest,
        "real_render_ready_strategy_types": sorted(manifest_real_ready),
        "real_render_report_ready_strategy_types": sorted(report_real_ready),
        "reference_evidence_ready_strategy_types": sorted(reference_ready),
        "effective_real_render_ready_strategy_types": sorted(effective_real_ready),
        "real_render_missing_strategy_types": real_missing,
        "real_render_rerun_strategy_types": real_reruns,
        "replacement_fixture_needed_strategy_types": replacement_needed,
        "render_unsuitable_case_ids": sorted(rejected_cases),
        "strategy_plans": strategy_plans,
        "coordination": {
            "run_mode": "one_strategy_per_agent_or_batch",
            "reason": "Real candidate runs can be long; avoid one full-manifest run when closing gaps.",
            "safe_parallelism": "Different strategy case_ids may run in separate workers if DB/job queue capacity is available.",
            "runtime_preflight": (
                "Run the local ASR /transcribe preflight before render reruns; health-only checks do not prove "
                "subtitle-alignment readiness."
            ),
            "candidate_replacement": (
                "If a selected case is marked render_unsuitable, do not rerun it for closure; export a new candidate "
                "or add a real fixture source that can pass render and subtitle-alignment evidence."
            ),
            "reference_render_evidence": (
                "Promoted rows that already have completed reference render outputs should use the reference report "
                "builder instead of rerendering long source media."
            ),
        },
        "verification_commands": {
            "runtime_preflight": RUNTIME_PREFLIGHT_COMMAND,
            "real_render_reference_report": reference_report_command,
            "real_render_fixture_coverage": _real_render_verifier_command(real_report_placeholders),
            "integration_closure": _integration_closure_command(real_report_placeholders),
        },
    }


def render_execution_plan_markdown(plan: dict[str, Any]) -> str:
    lines = [
        "# Strategy Fixture Execution Plan",
        "",
        f"- manifest: `{plan.get('manifest_path') or ''}`",
        f"- ok: `{str(bool(plan.get('ok'))).lower()}`",
        f"- completion_ready: `{str(bool(plan.get('completion_ready'))).lower()}`",
        f"- real_render_missing: `{', '.join(_string_list(plan.get('real_render_missing_strategy_types'))) or 'none'}`",
        f"- replacement_fixture_needed: `{', '.join(_string_list(plan.get('replacement_fixture_needed_strategy_types'))) or 'none'}`",
        "",
        "## Strategy Commands",
        "",
    ]
    for item in list(plan.get("strategy_plans") or []):
        if not isinstance(item, dict):
            continue
        lines.extend(
            [
                f"### {item.get('strategy_type')}",
                "",
                f"- agent_lane: `{item.get('agent_lane') or ''}`",
                f"- case_id: `{item.get('case_id') or ''}`",
                f"- real_render_ready: `{str(bool(item.get('real_render_ready'))).lower()}`",
                f"- reference_evidence_ready: `{str(bool(item.get('reference_evidence_ready'))).lower()}`",
                f"- render_unsuitable: `{str(bool(item.get('render_unsuitable'))).lower()}`",
                f"- needs_replacement_fixture: `{str(bool(item.get('needs_replacement_fixture'))).lower()}`",
                f"- needs_real_render_rerun: `{str(bool(item.get('needs_real_render_rerun'))).lower()}`",
                f"- runtime_preflight_required: `{str(bool(item.get('runtime_preflight_required'))).lower()}`",
                f"- runtime_preflight: `{item.get('runtime_preflight_command') or ''}`",
                f"- promotion_required_for_real_closure: `{str(bool(item.get('promotion_required_for_real_closure'))).lower()}`",
                f"- promotion_command: `{item.get('promotion_command') or ''}`",
                f"- replacement_fixture_guidance: `{item.get('replacement_fixture_guidance') or ''}`",
                f"- content_profile_smoke: `{item.get('content_profile_smoke_command') or ''}`",
                f"- render_fixture: `{item.get('render_fixture_command') or ''}`",
                f"- blocking_checks_for_completion: `{', '.join(_string_list(item.get('blocking_checks_for_completion'))) or 'none'}`",
                "",
            ]
        )
    verification = plan.get("verification_commands") if isinstance(plan.get("verification_commands"), dict) else {}
    lines.extend(
        [
            "## Final Verification",
            "",
            f"- runtime_preflight: `{verification.get('runtime_preflight') or ''}`",
            f"- real_render_reference_report: `{verification.get('real_render_reference_report') or ''}`",
            f"- real_render_fixture_coverage: `{verification.get('real_render_fixture_coverage') or ''}`",
            f"- integration_closure: `{verification.get('integration_closure') or ''}`",
            "",
        ]
    )
    return "\n".join(lines)


def _completion_blocking_checks(
    *,
    strategy: str,
    real_render_ready: bool,
    required_checks: list[str],
    render_unsuitable: bool = False,
    missing_manifest_case: bool = False,
) -> list[str]:
    checks: list[str] = []
    if render_unsuitable or missing_manifest_case:
        checks.append("replacement_fixture_required")
    if not real_render_ready:
        checks.append("real_render_fixture")
    checks.extend(item for item in required_checks if item != "strategy_pipeline_coverage")
    if (
        strategy == "narrative_assembly"
        and not real_render_ready
        and "strategy_review_preview_media_evidence" not in checks
    ):
        checks.append("strategy_review_preview_media_evidence")
    return checks


def _golden_command(*, manifest_path: str, case_id: str, report_dir: str, stop_after: str) -> str:
    return (
        "uv run python scripts/run_auto_edit_recovery_golden_set.py"
        f" --manifest {manifest_path}"
        f" --case-id {case_id}"
        f" --report-dir {report_dir}"
        f" --stop-after {stop_after}"
    )


def _promotion_command(*, manifest_path: str, strategy: str) -> str:
    return (
        "uv run python scripts/promote_strategy_fixture_manifest.py"
        f" --manifest {manifest_path}"
        f" --strategy {strategy}"
        " --output output/test/strategy-fixture-candidates.promoted.manifest.v1.json"
    )


def _reference_report_command(*, candidate_summary_path: str = "", reference_strategies: list[str] | None = None) -> str:
    command = (
        "uv run python scripts/build_strategy_real_render_reference_report.py"
        f" --manifest {PROMOTED_MANIFEST_PATH}"
    )
    if candidate_summary_path:
        command += f" --candidate-summary {candidate_summary_path}"
        for strategy in _string_list(reference_strategies or []):
            command += f" --required-strategy {strategy}"
    command += f" --output {REFERENCE_REPORT_PATH}"
    return command


def _real_render_verifier_command(real_reports: list[str]) -> str:
    if not real_reports:
        real_reports = ["<real-batch-report>"]
    report_args = " ".join(f"--report {path}" for path in real_reports)
    return f"uv run python scripts/verify_strategy_real_render_fixtures.py {report_args}"


def _integration_closure_command(real_reports: list[str]) -> str:
    report_args = " ".join(f"--real-render-report {path}" for path in real_reports) if real_reports else "--real-render-report <real-batch-report>"
    return (
        "uv run python scripts/verify_strategy_integration_closure.py"
        f" --content-profile-report {GENERATED_CONTENT_PROFILE_REPORT}"
        f" --event-render-report {GENERATED_EVENT_RENDER_REPORT}"
        f" {report_args}"
    )


def _job_strategy_type(job: dict[str, Any]) -> str:
    risk_hints = job.get("risk_hints") if isinstance(job.get("risk_hints"), dict) else {}
    for key in ("expected_strategy_type", "strategy_type"):
        value = str(risk_hints.get(key) or "").strip()
        if value:
            return value
    for tag in _string_list(job.get("tags")):
        if tag.startswith("strategy:"):
            return tag.split(":", 1)[1].strip()
    return ""


def _agent_lane_for_strategy(strategy: str, *, needs_replacement_fixture: bool = False) -> str:
    if needs_replacement_fixture:
        return "Fixture Candidate Agent"
    if strategy == "narrative_assembly":
        return "Narrative Preview Agent"
    if strategy in {"step_demonstration", "experience_and_mood"}:
        return "Render Fixture Agent"
    if strategy in {"information_density", "event_highlight"}:
        return "Closure Agent"
    return "Fixture Candidate Agent"


def _source_status(
    *,
    job: dict[str, Any],
    render_unsuitable: bool,
    reference_evidence_ready: bool = False,
    report_evidence_ready: bool = False,
) -> str:
    if report_evidence_ready:
        return "real_render_report_ready"
    if reference_evidence_ready:
        return "reference_evidence_ready"
    if not job:
        return "missing_manifest_case"
    if render_unsuitable:
        return "render_unsuitable_candidate"
    return "manifest_ready"


def _reference_evidence_ready_by_strategy(
    summary: dict[str, Any],
    *,
    required_strategies: list[str],
) -> dict[str, dict[str, Any]]:
    selected = summary.get("selected_candidates") if isinstance(summary.get("selected_candidates"), dict) else {}
    result: dict[str, dict[str, Any]] = {}
    for strategy in required_strategies:
        for candidate in [item for item in list(selected.get(strategy) or []) if isinstance(item, dict)]:
            readiness = candidate.get("real_render_readiness") if isinstance(candidate.get("real_render_readiness"), dict) else {}
            if not bool(readiness.get("ready")):
                continue
            case = candidate.get("golden_manifest_case") if isinstance(candidate.get("golden_manifest_case"), dict) else {}
            result[strategy] = {
                "case_id": str(case.get("case_id") or "").strip(),
                "reference_job_id": str(candidate.get("job_id") or case.get("reference_job_id") or "").strip(),
                "source_name": str(candidate.get("source_name") or case.get("source_name") or "").strip(),
                "reason_codes": _string_list(readiness.get("reason_codes")),
                "notes": "Reference-only real render evidence; not replay-safe fixture input.",
            }
            break
    return result


def _real_render_report_ready_by_strategy(
    reports: list[dict[str, Any]],
    *,
    required_strategies: list[str],
) -> dict[str, dict[str, Any]]:
    if not reports:
        return {}
    coverage = verify_strategy_real_render_fixtures(reports, required_strategies=required_strategies)
    evidence_by_strategy = (
        coverage.get("evidence_by_strategy")
        if isinstance(coverage.get("evidence_by_strategy"), dict)
        else {}
    )
    result: dict[str, dict[str, Any]] = {}
    for strategy in required_strategies:
        items = [item for item in list(evidence_by_strategy.get(strategy) or []) if isinstance(item, dict)]
        if not items:
            continue
        first = items[0]
        result[strategy] = {
            "case_id": str(first.get("case_id") or "").strip(),
            "reference_job_id": str(first.get("job_id") or "").strip(),
            "source_name": str(first.get("source_name") or "").strip(),
            "output_path": str(first.get("output_path") or "").strip(),
            "output_duration_sec": first.get("output_duration_sec"),
            "status": str(first.get("status") or "").strip(),
        }
    return result


def _replacement_fixture_guidance(strategy: str, rejection: dict[str, Any] | None) -> str:
    reason = str((rejection or {}).get("reason") or "").strip()
    if strategy == "step_demonstration":
        return (
            "Find or create a real tutorial/screen-recording fixture with readable operation steps and speech that "
            f"ASR can align; current candidate rejected because {reason or 'render alignment did not pass'}."
        )
    if strategy == "experience_and_mood":
        return (
            "Find a real travel/food/vlog-style fixture with completed render output and mood/experience signals; "
            f"current candidate rejected because {reason or 'render evidence did not pass'}."
        )
    if strategy == "narrative_assembly":
        return (
            "Find or build a real multi-material narrative fixture that renders and has media-backed storyboard/"
            f"timeline preview evidence; current candidate rejected because {reason or 'render or preview evidence did not pass'}."
        )
    return f"Find a replacement real fixture; current candidate rejected because {reason or 'render evidence did not pass'}."


def _collect_render_unsuitable_cases(reports: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    rejected: dict[str, dict[str, Any]] = {}
    for report in reports:
        for row in _report_case_rows(report):
            case_id = str(row.get("case_id") or "").strip()
            if not case_id:
                continue
            evidence = _render_unsuitable_evidence(row)
            if evidence:
                rejected[case_id] = evidence
    return rejected


def _report_case_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("golden_case_rows")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    rows = report.get("jobs")
    if isinstance(rows, list):
        return [item for item in rows if isinstance(item, dict)]
    return []


def _render_unsuitable_evidence(row: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("status") or "").strip().lower()
    if status not in {"failed", "error"}:
        return {}
    text = json.dumps(row, ensure_ascii=False, sort_keys=True)
    reason = ""
    reason_codes: list[str] = []
    required_failed = _string_list(row.get("required_checks_failed"))
    if any(item.startswith("strategy_") for item in required_failed):
        reason = "strategy_required_checks_failed"
        reason_codes.append("strategy_required_checks_failed")
    if "unexpected_strategy_type" in text:
        reason_codes.append("unexpected_strategy_type")
    if "render_subtitle_asr_alignment_blocked" in text:
        reason = reason or "render_subtitle_asr_alignment_blocked"
        reason_codes.append("render_subtitle_asr_alignment_blocked")
    if "rendered_audio_asr_alignment_unstable" in text:
        reason = reason or "rendered_audio_asr_alignment_unstable"
        reason_codes.append("rendered_audio_asr_alignment_unstable")
    if not reason_codes:
        return {}
    return {
        "case_id": str(row.get("case_id") or "").strip(),
        "job_id": str(row.get("job_id") or row.get("evaluation_job_id") or "").strip(),
        "source_name": str(row.get("source_name") or "").strip(),
        "status": status,
        "reason": reason,
        "reason_codes": sorted(set(reason_codes)),
        "required_checks_failed": required_failed,
    }


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a per-strategy execution plan for real strategy fixture closure.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR.parent / "strategy-fixture-candidates.manifest.v1.json",
        help="Candidate golden manifest generated by export_strategy_fixture_candidates.py --manifest-output.",
    )
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--markdown-output", type=Path, default=None, help="Optional Markdown output path.")
    parser.add_argument("--content-profile-report-root", default=DEFAULT_CONTENT_PROFILE_REPORT_ROOT)
    parser.add_argument("--render-report-root", default=DEFAULT_RENDER_REPORT_ROOT)
    parser.add_argument(
        "--candidate-summary",
        type=Path,
        default=None,
        help="Optional export_strategy_fixture_candidates.py JSON; ready rows become reference-only evidence.",
    )
    parser.add_argument(
        "--real-render-report",
        action="append",
        default=[],
        type=Path,
        help="Optional real-world strategy render batch_report.json or report directory. May be repeated.",
    )
    parser.add_argument(
        "--rejection-report",
        action="append",
        default=[],
        type=Path,
        help="Failed render batch_report.json whose case should be marked render-unsuitable in the plan.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    candidate_summary = json.loads(args.candidate_summary.read_text(encoding="utf-8")) if args.candidate_summary else None
    real_render_reports = [load_batch_report(path) for path in list(args.real_render_report or [])]
    rejection_reports = [json.loads(path.read_text(encoding="utf-8")) for path in list(args.rejection_report or [])]
    plan = build_strategy_fixture_execution_plan(
        manifest,
        manifest_path=str(args.manifest),
        content_profile_report_root=args.content_profile_report_root,
        render_report_root=args.render_report_root,
        candidate_summary=candidate_summary,
        candidate_summary_path=str(args.candidate_summary) if args.candidate_summary else "",
        real_render_reports=real_render_reports,
        real_render_report_paths=[str(path) for path in list(args.real_render_report or [])],
        rejection_reports=rejection_reports,
    )
    text = json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_execution_plan_markdown(plan), encoding="utf-8")
    return 0 if plan.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
