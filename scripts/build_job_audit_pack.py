from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from export_job_audit_snapshot import DEFAULT_KEYWORDS, export_snapshot


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a reusable RoughCut audit pack markdown from a job snapshot."
    )
    parser.add_argument("--job-id", help="Optional RoughCut job UUID. If set, snapshot will be exported first.")
    parser.add_argument(
        "--snapshot-json",
        type=Path,
        help="Existing snapshot JSON from export_job_audit_snapshot.py. Required when --job-id is omitted.",
    )
    parser.add_argument(
        "--confirm-json",
        type=Path,
        help="Optional manual confirmation payload JSON to embed in the audit pack.",
    )
    parser.add_argument(
        "--locate-root",
        action="append",
        default=[],
        help="Optional source roots used when exporting snapshot with --job-id.",
    )
    parser.add_argument(
        "--output-md",
        type=Path,
        default=ROOT / "output" / "job-audit-pack.md",
        help="Where to write the markdown audit pack.",
    )
    parser.add_argument(
        "--snapshot-output-json",
        type=Path,
        default=ROOT / "output" / "job-audit-pack.snapshot.json",
        help="Where to write the snapshot when --job-id is provided.",
    )
    return parser.parse_args()


def _load_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


async def _resolve_snapshot(args: argparse.Namespace) -> dict[str, Any]:
    if args.job_id:
        export_args = argparse.Namespace(
            job_id=args.job_id,
            keywords=list(DEFAULT_KEYWORDS),
            locate_root=list(args.locate_root or []),
            output_json=args.snapshot_output_json,
        )
        return await export_snapshot(export_args)
    if not args.snapshot_json:
        raise RuntimeError("Either --job-id or --snapshot-json is required.")
    return _load_json(args.snapshot_json)


def _render_list(items: list[str], empty_text: str) -> str:
    if not items:
        return f"- {empty_text}"
    return "\n".join(f"- {item}" for item in items)


def _render_step_status(snapshot: dict[str, Any]) -> str:
    rows = snapshot.get("step_status") or []
    if not rows:
        return "- 无 step 状态"
    return "\n".join(
        f"- `{row.get('step_name')}`: `{row.get('status')}`"
        + (f" | {row.get('detail')}" if row.get("detail") else "")
        for row in rows
    )


def _render_hits(snapshot: dict[str, Any], key: str, empty_text: str) -> str:
    rows = snapshot.get(key) or []
    if not rows:
        return f"- {empty_text}"
    return "\n".join(
        f"- `{row.get('start_time'):.2f}s - {row.get('end_time'):.2f}s` {row.get('text')}"
        for row in rows[:10]
    )


def _render_confirm_payload(confirm_payload: dict[str, Any]) -> str:
    if not confirm_payload:
        return "_未提供人工确认 payload_"
    return "```json\n" + json.dumps(confirm_payload, ensure_ascii=False, indent=2) + "\n```"


def build_markdown(snapshot: dict[str, Any], confirm_payload: dict[str, Any]) -> str:
    job = snapshot.get("job") or {}
    artifact_summary = ((snapshot.get("artifacts") or {}).get("active_profile_summary") or {})
    artifact_counts = ((snapshot.get("artifacts") or {}).get("counts") or {})
    heuristics = snapshot.get("heuristics") or {}
    issues = list(heuristics.get("issues") or [])
    located_paths = list(job.get("located_paths") or [])

    checklist_items = []
    if artifact_counts.get("content_profile_final", 0) <= 0:
        checklist_items.append("先完成人工确认并写回 `content_profile_final`。")
    if any(step.get("step_name") == "final_review" and step.get("status") != "done" for step in snapshot.get("step_status") or []):
        checklist_items.append("继续推进 `edit_plan / render / final_review / platform_package`。")
    if issues:
        checklist_items.append("优先处理自动审核识别出的阻塞项，再继续下游生产。")
    if not checklist_items:
        checklist_items.append("当前摘要审核已闭环，可按现有 final profile 继续后续成片链路。")

    md = f"""# RoughCut 审核包

## 1. 任务信息

- `job_id`: `{job.get("id", "")}`
- `source_name`: `{job.get("source_name", "")}`
- `job_status`: `{job.get("status", "")}`
- `source_path`: `{job.get("source_path", "")}`
- 共享盘定位:
{_render_list(located_paths, "未定位到原片路径")}

## 2. 当前摘要主体

- active profile: `{(snapshot.get("artifacts") or {}).get("active_profile_type", "")}`
- `subject_brand`: `{artifact_summary.get("subject_brand", "")}`
- `subject_model`: `{artifact_summary.get("subject_model", "")}`
- `subject_type`: `{artifact_summary.get("subject_type", "")}`
- `summary`: {artifact_summary.get("summary", "")}
- `hook_line`: {artifact_summary.get("hook_line", "")}

## 3. 工件与步骤状态

- artifact counts: `{json.dumps(artifact_counts, ensure_ascii=False)}`
- step status:
{_render_step_status(snapshot)}

## 4. 原始证据命中

### Transcript 命中
{_render_hits(snapshot, "transcript_hits", "无 transcript 命中")}

### Subtitle 命中
{_render_hits(snapshot, "subtitle_hits", "无 subtitle 命中")}

## 5. 自动审核结论

### Heuristics
{_render_list(issues, "当前没有启发式阻塞")}

### 当前执行清单
{_render_list(checklist_items, "无后续动作")}

## 6. 人工确认 Payload

{_render_confirm_payload(confirm_payload)}
"""
    return md


def main() -> None:
    args = parse_args()
    snapshot = asyncio.run(_resolve_snapshot(args))
    confirm_payload = _load_json(args.confirm_json)
    markdown = build_markdown(snapshot, confirm_payload)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(markdown, encoding="utf-8")
    print(
        json.dumps(
            {
                "job_id": (snapshot.get("job") or {}).get("id") or args.job_id or "",
                "output_md": str(args.output_md),
                "snapshot_source": str(args.snapshot_json or args.snapshot_output_json),
                "confirm_json": str(args.confirm_json) if args.confirm_json else "",
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
