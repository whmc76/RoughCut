from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from sqlalchemy import select

from roughcut.db.models import Job, JobStep, Timeline
from roughcut.db.session import get_session_factory
from roughcut.pipeline.live_readiness import build_live_readiness_summary
from scripts.build_batch_output_scorecard import build_scorecard, render_markdown as render_scorecard_markdown
from scripts.run_auto_edit_recovery_golden_set import (
    _write_audit_pack_for_job,
    load_golden_job_manifest,
    prepare_golden_job,
    select_golden_job_cases,
    summarize_render_diagnostics,
)
from scripts.run_fullchain_batch import render_markdown, run_job
from scripts.verify_render_failure_signal_consistency import verify_render_failure_signal_consistency


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture one controlled real render failure sample through the existing golden/batch chain."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "docs" / "golden-jobs" / "auto-edit-recovery-golden-slice.v1.json",
    )
    parser.add_argument("--case-id", default="noc_mt34_short_done")
    parser.add_argument(
        "--failure-mode",
        choices=("render_ffprobe_failed",),
        default="render_ffprobe_failed",
    )
    parser.add_argument(
        "--report-dir",
        type=Path,
        default=ROOT / "output" / "test" / "auto-edit-recovery-golden" / "controlled-render-failure",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _controlled_non_media_path() -> Path:
    return (ROOT / "docs" / "agent-doc-index.md").resolve()


def _inject_controlled_failure(render_plan: dict[str, Any], *, failure_mode: str) -> dict[str, Any]:
    payload = dict(render_plan or {})
    if failure_mode == "render_ffprobe_failed":
        payload["intro"] = {
            "path": str(_controlled_non_media_path()),
            "source": "controlled_failure_sample",
            "style": "controlled_invalid_non_media_intro",
        }
        payload["outro"] = None
        payload["insert"] = None
    return payload


async def _mutate_job_for_controlled_failure(*, job_id: str, failure_mode: str) -> dict[str, Any]:
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            raise RuntimeError(f"job not found: {job_id}")
        render_plan_timeline = (
            await session.execute(
                select(Timeline)
                .where(Timeline.job_id == job.id, Timeline.timeline_type == "render_plan")
                .order_by(Timeline.version.desc(), Timeline.created_at.desc())
            )
        ).scalars().first()
        if render_plan_timeline is None or not isinstance(render_plan_timeline.data_json, dict):
            raise RuntimeError(f"render_plan timeline missing for job {job_id}")

        mutated_render_plan = _inject_controlled_failure(render_plan_timeline.data_json, failure_mode=failure_mode)
        session.add(
            Timeline(
                job_id=job.id,
                version=int(render_plan_timeline.version or 0) + 1,
                timeline_type="render_plan",
                data_json=mutated_render_plan,
                otio_data=render_plan_timeline.otio_data,
            )
        )

        steps = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name.in_(["render", "final_review", "platform_package"]))
            )
        ).scalars().all()
        for step in steps:
            step.status = "pending"
            step.error_message = None
            step.started_at = None
            step.finished_at = None
            metadata = dict(step.metadata_ or {})
            metadata.pop("sync_runner_terminal_failure", None)
            metadata["detail"] = f"controlled_failure_reset:{failure_mode}"
            step.metadata_ = metadata

        job.status = "processing"
        job.error_message = None
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()
        return {
            "job_id": job_id,
            "render_plan_version": int(render_plan_timeline.version or 0) + 1,
            "failure_mode": failure_mode,
            "controlled_path": str(_controlled_non_media_path()),
        }


def main() -> int:
    args = parse_args()
    cases = select_golden_job_cases(load_golden_job_manifest(args.manifest), case_ids=[args.case_id], tags=[])
    case = cases[0]
    prepared = asyncio.run(
        prepare_golden_job(
            case,
            default_workflow_template="edc_tactical",
            default_language="zh-CN",
            locate_roots=[],
        )
    )

    pre_render_report = run_job(prepared.job_id, prepared.item, stop_after="edit_plan")
    mutation = asyncio.run(
        _mutate_job_for_controlled_failure(job_id=prepared.job_id, failure_mode=args.failure_mode)
    )
    failed_report = run_job(prepared.job_id, prepared.item)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = args.report_dir / timestamp
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": str(args.manifest.resolve()),
        "source_dir": str(prepared.item.path.parent),
        "channel_profile": "golden_controlled_failure",
        "language": getattr(prepared.item, "language", None) or "zh-CN",
        "output_dir": str(run_dir),
        "stop_after": None,
        "enhancement_modes": [],
        "job_count": 1,
        "success_count": 0,
        "partial_count": 0,
        "failed_count": 1 if failed_report.status == "failed" else 0,
        "jobs": [asdict(failed_report)],
        "golden_cases": [
            {
                **asdict(prepared.case),
                "evaluation_job_id": prepared.job_id,
                "evaluation_mode": prepared.mode,
            }
        ],
        "controlled_failure": {
            "pre_render_report": asdict(pre_render_report),
            "mutation": mutation,
        },
    }
    summary["render_diagnostics_summary"] = summarize_render_diagnostics([failed_report])
    summary["live_readiness"] = asdict(
        build_live_readiness_summary(
            summary,
            golden_source_names=[failed_report.source_name] if failed_report.source_name else [],
            previous_summaries=[],
        )
    )

    batch_report_path = run_dir / "batch_report.json"
    scorecard = asyncio.run(build_scorecard(summary))
    scorecard["batch_report"] = str(batch_report_path)
    scorecard_path = run_dir / "detailed_output_scorecard.json"
    scorecard_md_path = run_dir / "detailed_output_scorecard.md"
    batch_md_path = run_dir / "batch_report.md"

    audit_dir = run_dir / "audit_packs"
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = asyncio.run(
        _write_audit_pack_for_job(report=failed_report, audit_dir=audit_dir, locate_roots=[])
    )

    summary["output_dir"] = str(run_dir)
    batch_report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    scorecard_path.write_text(json.dumps(scorecard, ensure_ascii=False, indent=2), encoding="utf-8")
    scorecard_md_path.write_text(render_scorecard_markdown(scorecard, batch_report_path), encoding="utf-8")
    batch_md_path.write_text(render_markdown(summary), encoding="utf-8")

    verification = verify_render_failure_signal_consistency(run_dir)
    verification_path = run_dir / "failure_signal_verification.json"
    verification_path.write_text(json.dumps(verification, ensure_ascii=False, indent=2), encoding="utf-8")

    result = {
        "run_dir": str(run_dir),
        "audit_pack": str(audit_path),
        "verification_path": str(verification_path),
        "verification": verification,
        "controlled_failure": summary["controlled_failure"],
        "final_report": asdict(failed_report),
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if verification.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
