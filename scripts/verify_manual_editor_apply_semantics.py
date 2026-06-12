from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.run_auto_edit_recovery_golden_set import (
    GoldenJobCase,
    inspect_manual_editor_apply_semantics,
    load_golden_job_manifest,
    select_golden_job_cases,
)

_MANUAL_EDITOR_APPLY_SEMANTICS_CHECK = "manual_editor_apply_semantics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify manual-editor apply semantics on real anchor jobs without mutating the jobs."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs" / "golden-jobs" / "auto-edit-recovery-golden-slice.v1.json",
        help="Golden job manifest JSON.",
    )
    parser.add_argument(
        "--case-id",
        dest="case_ids",
        action="append",
        default=[],
        help="Optional case_id filter. Repeat to inspect multiple explicit cases.",
    )
    parser.add_argument(
        "--tag",
        dest="tags",
        action="append",
        default=[],
        help="Optional tag filter. Defaults to manual_editor anchors when omitted.",
    )
    parser.add_argument(
        "--allow-no-managed-cuts",
        action="store_true",
        help="Do not fail when selected cases contain no frontend-managed auto cuts.",
    )
    parser.add_argument(
        "--job-id",
        default="",
        help="Inspect one explicit real job id without requiring a manifest case.",
    )
    parser.add_argument(
        "--source-name",
        default="",
        help="Inspect the latest real job by source name without requiring a manifest case.",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON.")
    return parser.parse_args()


async def _run_cases(
    cases: list[GoldenJobCase],
    *,
    explicit_job_id: str = "",
    explicit_source_name: str = "",
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    normalized_job_id = str(explicit_job_id or "").strip()
    normalized_source_name = str(explicit_source_name or "").strip()
    if normalized_job_id or normalized_source_name:
        explicit_case = GoldenJobCase(
            case_id="direct_job_inspection",
            scenario="direct manual-editor apply semantics inspection",
        )
        try:
            results.append(
                await inspect_manual_editor_apply_semantics(
                    explicit_case,
                    job_id=normalized_job_id,
                    source_name=normalized_source_name,
                )
            )
        except Exception as exc:
            results.append(
                {
                    "case_id": explicit_case.case_id,
                    "source_name": normalized_source_name,
                    "job_id": normalized_job_id,
                    "managed_auto_cut_count": 0,
                    "ok": False,
                    "error": str(exc),
                }
            )
        return results
    for case in cases:
        try:
            results.append(await inspect_manual_editor_apply_semantics(case))
        except Exception as exc:
            results.append(
                {
                    "case_id": case.case_id,
                    "source_name": case.source_name,
                    "job_id": case.reference_job_id,
                    "managed_auto_cut_count": 0,
                    "ok": False,
                    "error": str(exc),
                }
            )
    return results


def _default_apply_semantics_cases(cases: list[GoldenJobCase]) -> list[GoldenJobCase]:
    return [
        case
        for case in list(cases or [])
        if _MANUAL_EDITOR_APPLY_SEMANTICS_CHECK in {str(item or "").strip() for item in list(case.required_checks or [])}
    ]


def main() -> int:
    args = parse_args()
    direct_job_mode = bool(str(args.job_id or "").strip() or str(args.source_name or "").strip())
    if direct_job_mode and (args.case_ids or args.tags):
        raise SystemExit("--job-id/--source-name cannot be combined with --case-id/--tag")
    manifest_cases = load_golden_job_manifest(args.manifest)
    if direct_job_mode:
        cases: list[GoldenJobCase] = []
    elif args.case_ids or args.tags:
        selected_tags = list(args.tags or ["manual_editor"])
        cases = select_golden_job_cases(
            manifest_cases,
            case_ids=list(args.case_ids or []),
            tags=selected_tags,
        )
    else:
        cases = _default_apply_semantics_cases(manifest_cases)
    results = asyncio.run(
        _run_cases(
            cases,
            explicit_job_id=str(args.job_id or ""),
            explicit_source_name=str(args.source_name or ""),
        )
    )
    managed_case_count = sum(1 for item in results if int(item.get("managed_auto_cut_count") or 0) > 0)
    failing_cases = [item for item in results if not bool(item.get("ok"))]
    if args.json:
        print(
            json.dumps(
                {
                    "manifest": str(args.manifest.resolve()),
                    "case_count": len(results),
                    "managed_case_count": managed_case_count,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for item in results:
            status = "PASS" if bool(item.get("ok")) else "FAIL"
            print(
                f"[{status}] {item.get('case_id')} source={item.get('source_name')} "
                f"managed_auto_cut_count={item.get('managed_auto_cut_count')}"
            )
            if item.get("error"):
                print(f"  error: {item['error']}")
                continue
            print(
                "  roundtrip_matches_editorial="
                f"{item.get('roundtrip_matches_editorial')} "
                f"session_baseline_matches_restored={item.get('session_baseline_matches_restored')} "
                f"change_scope={item.get('change_scope')} "
                f"timeline_changed={item.get('timeline_changed')}"
            )
    if failing_cases:
        return 1
    if managed_case_count <= 0 and not args.allow_no_managed_cuts:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
