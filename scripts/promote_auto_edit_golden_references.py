from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.run_auto_edit_recovery_golden_set import SUPPORTED_REQUIRED_CHECKS


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _validate_manifest_required_checks(manifest: dict[str, Any]) -> None:
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("manifest must contain jobs array")
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            continue
        case_id = str(raw_job.get("case_id") or raw_job.get("id") or "").strip() or "<unknown>"
        required_checks = [
            str(item or "").strip()
            for item in list(raw_job.get("required_checks") or [])
            if str(item or "").strip()
        ]
        unsupported = [check for check in required_checks if check not in SUPPORTED_REQUIRED_CHECKS]
        if unsupported:
            raise ValueError(
                f"manifest case {case_id} has unsupported required_checks: {', '.join(unsupported)}"
            )


def _normalize_case_ids(values: list[str] | None) -> list[str]:
    return [str(value or "").strip() for value in list(values or []) if str(value or "").strip()]


def _refresh_candidate_map(
    batch_report: dict[str, Any],
    *,
    case_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    selected_case_ids = set(_normalize_case_ids(case_ids))
    candidates: dict[str, dict[str, Any]] = {}
    raw_candidates = [dict(item) for item in list(batch_report.get("reference_refresh_candidates") or []) if isinstance(item, dict)]
    evaluation_snapshots = {
        str(case_id): dict(payload or {})
        for case_id, payload in dict(batch_report.get("evaluation_risk_snapshots") or {}).items()
        if str(case_id).strip() and isinstance(payload, dict)
    }
    for candidate in raw_candidates:
        case_id = str(candidate.get("case_id") or "").strip()
        if not case_id:
            continue
        if selected_case_ids and case_id not in selected_case_ids:
            continue
        payload = dict(candidate)
        payload["evaluation_risk_snapshot"] = dict(evaluation_snapshots.get(case_id) or {})
        candidates[case_id] = payload
    if selected_case_ids:
        missing = sorted(selected_case_ids - set(candidates))
        if missing:
            raise ValueError(f"requested case_id(s) missing from reference_refresh_candidates: {', '.join(missing)}")
    if not candidates:
        raise ValueError("no reference_refresh_candidates found in batch report")
    return candidates


def _refreshed_risk_hints(
    existing: dict[str, Any] | None,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    hints = dict(existing or {})
    fresh_source = str(candidate.get("fresh_source") or "").strip()
    if fresh_source:
        hints["reference_expected_source"] = fresh_source
    fresh_high_risk_cut_count = int(candidate.get("fresh_high_risk_cut_count") or 0)
    if fresh_high_risk_cut_count > 0:
        hints["reference_high_risk_cut_count"] = fresh_high_risk_cut_count
    else:
        hints.pop("reference_high_risk_cut_count", None)
    hints["reference_manual_confirm_candidate_count"] = int(candidate.get("fresh_manual_confirm_count") or 0)
    hints["reference_auto_apply_candidate_count"] = int(candidate.get("fresh_auto_apply_candidate_count") or 0)
    fresh_multimodal_pending_count = int(candidate.get("fresh_multimodal_pending_count") or 0)
    if fresh_multimodal_pending_count > 0:
        hints["reference_multimodal_pending_count"] = fresh_multimodal_pending_count
    else:
        hints.pop("reference_multimodal_pending_count", None)
    hints["reference_rule_auto_apply_cut_count"] = int(candidate.get("fresh_rule_auto_apply_cut_count") or 0)
    fresh_snapshot = dict(candidate.get("evaluation_risk_snapshot") or {})
    fresh_risk_summary = dict(candidate.get("fresh_candidate_risk_summary") or fresh_snapshot.get("candidate_risk_summary") or {})
    if fresh_risk_summary:
        hints["reference_candidate_risk_summary"] = fresh_risk_summary
    else:
        hints.pop("reference_candidate_risk_summary", None)
    fresh_risk_levels = dict(candidate.get("fresh_risk_levels") or fresh_snapshot.get("risk_levels") or {})
    if fresh_risk_levels:
        hints["reference_risk_levels"] = fresh_risk_levels
    else:
        hints.pop("reference_risk_levels", None)
    return hints


def promote_manifest_references(
    manifest: dict[str, Any],
    batch_report: dict[str, Any],
    *,
    case_ids: list[str] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    _validate_manifest_required_checks(manifest)
    jobs = manifest.get("jobs")
    if not isinstance(jobs, list):
        raise ValueError("manifest must contain jobs array")
    candidate_map = _refresh_candidate_map(batch_report, case_ids=case_ids)
    refreshed_jobs: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    seen_reference_job_ids: set[str] = set()
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            refreshed_jobs.append(raw_job)
            continue
        case_id = str(raw_job.get("case_id") or raw_job.get("id") or "").strip()
        candidate = candidate_map.get(case_id)
        updated_job = dict(raw_job)
        if candidate is not None:
            required_checks = {
                str(item or "").strip().lower()
                for item in list(updated_job.get("required_checks") or [])
                if str(item or "").strip()
            }
            semantics_anchor = "manual_editor_apply_semantics" in required_checks
            previous_reference_job_id = str(updated_job.get("reference_job_id") or "").strip()
            evaluation_job_id = str(candidate.get("evaluation_job_id") or "").strip()
            if not evaluation_job_id:
                raise ValueError(f"refresh candidate for {case_id} is missing evaluation_job_id")
            if semantics_anchor:
                updated_job["reference_risk_job_id"] = evaluation_job_id
            else:
                updated_job["reference_job_id"] = evaluation_job_id
                updated_job.pop("reference_risk_job_id", None)
            updated_job["risk_hints"] = _refreshed_risk_hints(
                updated_job.get("risk_hints") if isinstance(updated_job.get("risk_hints"), dict) else {},
                candidate,
            )
            updates.append(
                {
                    "case_id": case_id,
                    "previous_reference_job_id": previous_reference_job_id,
                    "new_reference_job_id": previous_reference_job_id if semantics_anchor else evaluation_job_id,
                    "new_reference_risk_job_id": evaluation_job_id if semantics_anchor else None,
                    "reference_expected_source": updated_job["risk_hints"].get("reference_expected_source"),
                    "reference_manual_confirm_candidate_count": updated_job["risk_hints"].get("reference_manual_confirm_candidate_count"),
                    "reference_auto_apply_candidate_count": updated_job["risk_hints"].get("reference_auto_apply_candidate_count"),
                    "reference_rule_auto_apply_cut_count": updated_job["risk_hints"].get("reference_rule_auto_apply_cut_count"),
                }
            )
        reference_job_id = str(updated_job.get("reference_job_id") or "").strip()
        if reference_job_id:
            if reference_job_id in seen_reference_job_ids:
                raise ValueError(f"duplicate reference_job_id after refresh: {reference_job_id}")
            seen_reference_job_ids.add(reference_job_id)
        refreshed_jobs.append(updated_job)
    missing_case_ids = sorted(set(candidate_map) - {str(item.get("case_id") or item.get("id") or "").strip() for item in refreshed_jobs if isinstance(item, dict)})
    if missing_case_ids:
        raise ValueError(f"refresh candidate case_id(s) not found in manifest: {', '.join(missing_case_ids)}")
    refreshed_manifest = dict(manifest)
    refreshed_manifest["jobs"] = refreshed_jobs
    _validate_manifest_required_checks(refreshed_manifest)
    return refreshed_manifest, updates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote golden reference jobs from reference_refresh_candidates in a batch report.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-report", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[], help="Optional case_id to promote; repeatable")
    parser.add_argument("--output", type=Path, help="Optional output path for refreshed manifest JSON")
    parser.add_argument("--apply", action="store_true", help="Overwrite the input manifest in place")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = _load_json(args.manifest)
    batch_report = _load_json(args.batch_report)
    refreshed_manifest, updates = promote_manifest_references(
        manifest,
        batch_report,
        case_ids=list(args.case_id or []),
    )

    output_path = args.output
    if args.apply:
        output_path = args.manifest
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(refreshed_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "manifest": str(args.manifest),
                "batch_report": str(args.batch_report),
                "updated_case_count": len(updates),
                "updates": updates,
                "output_path": str(output_path) if output_path is not None else None,
                "applied": bool(args.apply),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
