from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from roughcut.db.models import Artifact, Job, RenderOutput
from roughcut.db.session import get_session_factory


REPORT_SCHEMA = "strategy_real_render_reference_report.v1"


def build_reference_report(
    *,
    manifest: dict[str, Any],
    job_records: dict[str, dict[str, Any]],
    report_path: str = "",
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    jobs: list[dict[str, Any]] = []
    for case in [item for item in list(manifest.get("jobs") or []) if isinstance(item, dict)]:
        case_id = str(case.get("case_id") or "").strip()
        reference_job_id = str(case.get("reference_job_id") or case.get("job_id") or "").strip()
        tags = _string_list(case.get("tags"))
        if not reference_job_id or "real_world_fixture" not in tags:
            continue
        record = job_records.get(reference_job_id)
        if not record:
            continue
        strategy_types = _strategy_types_for_case(case)
        output_path = str(record.get("output_path") or "").strip()
        duration = _float_value(record.get("output_duration_sec"))
        pipeline_status = _strategy_pipeline_status(
            expected_strategy_types=sorted(strategy_types),
            observed_strategy_types=_string_list(record.get("observed_strategy_types")),
        )
        required_checks = _string_list(case.get("required_checks")) or ["strategy_pipeline_coverage"]
        required_statuses: dict[str, Any] = {"strategy_pipeline_coverage": pipeline_status}
        passed = bool(pipeline_status.get("passed")) and bool(output_path) and duration > 0
        row = {
            "case_id": case_id,
            "scenario": str(case.get("scenario") or "").strip(),
            "reference_job_id": reference_job_id,
            "evaluation_job_id": reference_job_id,
            "source_name": str(record.get("source_name") or "").strip(),
            "status": "done" if passed else "failed",
            "tags": tags,
            "risk_hints": case.get("risk_hints") if isinstance(case.get("risk_hints"), dict) else {},
            "required_checks": required_checks,
            "required_check_statuses": required_statuses,
            "required_checks_passed": passed,
            "required_checks_failed": [] if passed else [name for name, status in required_statuses.items() if not status.get("passed")],
            "output_path": output_path,
            "output_duration_sec": duration,
            "notes": "Reference render evidence from existing promoted real_world_fixture job.",
        }
        rows.append(row)
        jobs.append(
            {
                "job_id": reference_job_id,
                "source_name": row["source_name"],
                "status": "done" if passed else "failed",
                "output_path": output_path,
                "output_duration_sec": duration,
                "quality_score": 1.0 if passed else 0.0,
                "quality_grade": "A" if passed else "E",
                "notes": ["reference render evidence"],
            }
        )
    failed_rows = [row for row in rows if not bool(row.get("required_checks_passed"))]
    required_total = sum(len(_string_list(row.get("required_checks"))) for row in rows)
    return {
        "schema": REPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "golden_manifest": str(manifest.get("__manifest_path") or ""),
        "report_path": report_path,
        "job_count": len(jobs),
        "success_count": len(jobs) - len(failed_rows),
        "failed_count": len(failed_rows),
        "jobs": jobs,
        "golden_case_rows": rows,
        "required_checks": {
            "total_cases": len(rows),
            "cases_with_checks": len(rows),
            "required_checks_case_passed": len(rows) - len(failed_rows),
            "required_checks_case_failed": len(failed_rows),
            "required_checks_failed_case_ids": [str(row.get("case_id") or "") for row in failed_rows],
            "required_checks_total": required_total,
            "required_checks_contract_passed": required_total - len(failed_rows),
            "required_checks_contract_failed": len(failed_rows),
            "required_checks_contract_pass_rate": 1.0 if required_total and not failed_rows else 0.0,
        },
    }


def manifest_from_candidate_summary(
    summary: dict[str, Any],
    *,
    required_strategies: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    selected = summary.get("selected_candidates") if isinstance(summary.get("selected_candidates"), dict) else {}
    required = [str(item or "").strip() for item in list(required_strategies or []) if str(item or "").strip()]
    if not required:
        required = [str(item or "").strip() for item in list(summary.get("required_strategy_types") or []) if str(item or "").strip()]
    jobs: list[dict[str, Any]] = []
    for strategy in required:
        for candidate in [item for item in list(selected.get(strategy) or []) if isinstance(item, dict)]:
            readiness = candidate.get("real_render_readiness") if isinstance(candidate.get("real_render_readiness"), dict) else {}
            if not bool(readiness.get("ready")):
                continue
            case = candidate.get("golden_manifest_case") if isinstance(candidate.get("golden_manifest_case"), dict) else {}
            tags = _string_list(case.get("tags"))
            if "real_world_fixture" not in tags:
                tags.append("real_world_fixture")
            if "reference_evidence_only" not in tags:
                tags.append("reference_evidence_only")
            jobs.append(
                {
                    **case,
                    "reference_job_id": str(candidate.get("job_id") or case.get("reference_job_id") or "").strip(),
                    "tags": tags,
                    "risk_hints": {
                        **(case.get("risk_hints") if isinstance(case.get("risk_hints"), dict) else {}),
                        "expected_strategy_type": strategy,
                    },
                    "notes": "Reference-only real render evidence from candidate summary; not replay-safe fixture input.",
                }
            )
            break
    return {
        "schema": "strategy_reference_evidence_manifest.v1",
        "jobs": jobs,
        "required_strategy_types": required,
        "source_summary_schema": str(summary.get("schema") or ""),
    }


async def load_reference_job_records(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    reference_ids = [
        str(case.get("reference_job_id") or case.get("job_id") or "").strip()
        for case in list(manifest.get("jobs") or [])
        if isinstance(case, dict)
    ]
    job_ids = [uuid.UUID(item) for item in reference_ids if item]
    if not job_ids:
        return {}
    session_factory = get_session_factory()
    records: dict[str, dict[str, Any]] = {}
    async with session_factory() as session:
        jobs = (
            await session.execute(
                select(Job)
                .options(selectinload(Job.render_outputs))
                .where(Job.id.in_(job_ids))
            )
        ).scalars().all()
        for job in jobs:
            output = _select_done_render_output(list(getattr(job, "render_outputs", []) or []))
            output_path = str(getattr(output, "output_path", "") or "").strip() if output is not None else ""
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.desc(), Artifact.id.desc())
                )
            ).scalars().all()
            records[str(job.id)] = {
                "source_name": str(getattr(job, "source_name", "") or ""),
                "output_path": output_path,
                "output_duration_sec": _probe_duration_sec(output_path),
                "observed_strategy_types": _observed_strategy_types_from_artifacts(artifacts),
            }
    return records


def _select_done_render_output(outputs: list[RenderOutput]) -> RenderOutput | None:
    for output in sorted(outputs, key=lambda item: str(getattr(item, "created_at", "") or ""), reverse=True):
        output_path = str(getattr(output, "output_path", "") or "").strip()
        if str(getattr(output, "status", "") or "").strip().lower() == "done" and output_path and Path(output_path).exists():
            return output
    return None


def _observed_strategy_types_from_artifacts(artifacts: list[Artifact]) -> list[str]:
    observed: list[str] = []
    for artifact in artifacts:
        data = artifact.data_json if isinstance(artifact.data_json, dict) else {}
        for value in (
            data.get("strategy_type"),
            (data.get("capability_orchestration") or {}).get("strategy_type") if isinstance(data.get("capability_orchestration"), dict) else "",
            (data.get("pipeline_plan") or {}).get("strategy_type") if isinstance(data.get("pipeline_plan"), dict) else "",
            (data.get("strategy_review_context") or {}).get("strategy_type") if isinstance(data.get("strategy_review_context"), dict) else "",
        ):
            text = str(value or "").strip()
            if text and text not in observed:
                observed.append(text)
    return observed


def _strategy_pipeline_status(*, expected_strategy_types: list[str], observed_strategy_types: list[str]) -> dict[str, Any]:
    missing = [item for item in expected_strategy_types if item not in set(observed_strategy_types)]
    return {
        "passed": not missing,
        "detail": f"expected={','.join(expected_strategy_types) or 'none'} | observed={','.join(observed_strategy_types) or 'none'}",
        "expected_strategy_types": expected_strategy_types,
        "observed_strategy_types": observed_strategy_types,
        "missing_strategy_types": missing,
        "evidence": [
            {"source": "reference_job_artifacts", "strategy_type": item}
            for item in observed_strategy_types
        ],
    }


def _strategy_types_for_case(case: dict[str, Any]) -> set[str]:
    values = {
        str(tag).split(":", 1)[1].strip()
        for tag in _string_list(case.get("tags"))
        if str(tag).startswith("strategy:") and str(tag).split(":", 1)[1].strip()
    }
    risk_hints = case.get("risk_hints") if isinstance(case.get("risk_hints"), dict) else {}
    for key in ("expected_strategy_type", "strategy_type"):
        value = str(risk_hints.get(key) or "").strip()
        if value:
            values.add(value)
    return values


def _probe_duration_sec(path_text: str) -> float:
    path = Path(str(path_text or "").strip())
    if not path.exists() or not path.is_file():
        return 0.0
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode != 0:
        return 0.0
    try:
        payload = json.loads(result.stdout or "{}")
        return round(float((payload.get("format") or {}).get("duration") or 0.0), 3)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _float_value(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a verifier-readable report from promoted reference render jobs.")
    parser.add_argument("--manifest", type=Path, required=True, help="Promoted strategy fixture manifest.")
    parser.add_argument(
        "--candidate-summary",
        type=Path,
        default=None,
        help="Optional strategy fixture candidate summary; ready candidates are added as reference-only evidence.",
    )
    parser.add_argument(
        "--required-strategy",
        action="append",
        default=[],
        help="Strategy to include from candidate summary. May be repeated.",
    )
    parser.add_argument("--output", type=Path, required=True, help="Output batch_report.json path.")
    return parser.parse_args()


async def async_main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if args.candidate_summary:
        summary = json.loads(args.candidate_summary.read_text(encoding="utf-8"))
        reference_manifest = manifest_from_candidate_summary(
            summary,
            required_strategies=_parse_required_strategies(args.required_strategy),
        )
        manifest["jobs"] = list(manifest.get("jobs") or []) + list(reference_manifest.get("jobs") or [])
    manifest["__manifest_path"] = str(args.manifest)
    records = await load_reference_job_records(manifest)
    report = build_reference_report(manifest=manifest, job_records=records, report_path=str(args.output))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "job_count": report["job_count"],
        "success_count": report["success_count"],
        "failed_count": report["failed_count"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["failed_count"] == 0 and report["job_count"] > 0 else 1


def _parse_required_strategies(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed


if __name__ == "__main__":
    raise SystemExit(asyncio.run(async_main()))
