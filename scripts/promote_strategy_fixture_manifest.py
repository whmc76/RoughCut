from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.build_strategy_fixture_execution_plan import _job_strategy_type


PROMOTION_TAG = "real_world_fixture"


def promote_strategy_fixture_manifest(
    manifest: dict[str, Any],
    *,
    case_ids: list[str] | None = None,
    strategy_types: list[str] | None = None,
    require_real_render_ready: bool = True,
) -> dict[str, Any]:
    selected_case_ids = {str(item or "").strip() for item in list(case_ids or []) if str(item or "").strip()}
    selected_strategy_types = {str(item or "").strip() for item in list(strategy_types or []) if str(item or "").strip()}
    real_ready = {
        str(item or "").strip()
        for item in list(manifest.get("real_render_ready_strategy_types") or [])
        if str(item or "").strip()
    }
    jobs = [dict(item) for item in list(manifest.get("jobs") or []) if isinstance(item, dict)]
    promoted_case_ids: list[str] = []
    skipped: list[dict[str, str]] = []
    for job in jobs:
        case_id = str(job.get("case_id") or "").strip()
        strategy_type = _job_strategy_type(job)
        selected = True
        if selected_case_ids or selected_strategy_types:
            selected = case_id in selected_case_ids or strategy_type in selected_strategy_types
        if not selected:
            continue
        if require_real_render_ready and strategy_type not in real_ready:
            skipped.append(
                {
                    "case_id": case_id,
                    "strategy_type": strategy_type,
                    "reason": "strategy_not_real_render_ready",
                }
            )
            continue
        tags = _string_list(job.get("tags"))
        if PROMOTION_TAG not in tags:
            tags.append(PROMOTION_TAG)
        job["tags"] = tags
        promoted_case_ids.append(case_id)
    output = dict(manifest)
    output["jobs"] = jobs
    output["promotion"] = {
        "tag": PROMOTION_TAG,
        "promoted_case_ids": promoted_case_ids,
        "skipped": skipped,
        "require_real_render_ready": bool(require_real_render_ready),
    }
    return output


def _string_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        values = [values] if str(values or "").strip() else []
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _parse_csv_values(values: list[str]) -> list[str]:
    parsed: list[str] = []
    for value in values:
        parsed.extend(part.strip() for part in str(value or "").split(",") if part.strip())
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote validated strategy fixture manifest rows to real_world_fixture.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[], help="Case id to promote. May be repeated.")
    parser.add_argument("--strategy", action="append", default=[], help="Strategy type to promote. May be repeated or comma-separated.")
    parser.add_argument(
        "--allow-not-real-render-ready",
        action="store_true",
        help="Allow promotion even if the manifest strategy is not listed in real_render_ready_strategy_types.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    promoted = promote_strategy_fixture_manifest(
        manifest,
        case_ids=_parse_csv_values(args.case_id),
        strategy_types=_parse_csv_values(args.strategy),
        require_real_render_ready=not bool(args.allow_not_real_render_ready),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(promoted, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    skipped = list((promoted.get("promotion") or {}).get("skipped") or [])
    promoted_case_ids = list((promoted.get("promotion") or {}).get("promoted_case_ids") or [])
    print(json.dumps(promoted.get("promotion"), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if promoted_case_ids and not skipped else 1


if __name__ == "__main__":
    raise SystemExit(main())
