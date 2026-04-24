from __future__ import annotations

import argparse
import asyncio
import concurrent.futures
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from sqlalchemy import select

from roughcut.config import get_settings
from roughcut.db.models import Job
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import PIPELINE_STEPS, create_job_steps
from roughcut.pipeline.steps import run_step_sync
from run_fullchain_batch import (
    StepRun,
    auto_approve_final_review,
    auto_confirm_content_profile,
    collect_job_report,
    finalize_job,
    mark_step,
    read_step_detail,
)


def _configure_local_event_loop_policy() -> None:
    # asyncpg on Windows can emit Proactor InvalidStateError noise when this script
    # repeatedly opens and tears down short-lived event loops via asyncio.run().
    if sys.platform != "win32":
        return
    policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy_cls is None:
        return
    asyncio.set_event_loop_policy(policy_cls())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run two fresh full-chain RoughCut jobs in parallel.")
    parser.add_argument("--source", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--workflow-template", default="edc_tactical")
    parser.add_argument("--language", default="zh-CN")
    parser.add_argument("--parallel-jobs", type=int, default=2)
    return parser.parse_args()


def main() -> None:
    _configure_local_event_loop_policy()
    args = parse_args()
    sources = [Path(item).resolve() for item in args.source]
    for source in sources:
        if not source.exists():
            raise FileNotFoundError(str(source))
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = args.report_dir / run_id
    report_dir.mkdir(parents=True, exist_ok=True)

    reports: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.parallel_jobs)) as executor:
        futures = {
            executor.submit(
                run_source,
                source,
                output_dir=args.output_dir,
                workflow_template=args.workflow_template,
                language=args.language,
            ): source
            for source in sources
        }
        for future in concurrent.futures.as_completed(futures):
            source = futures[future]
            try:
                report = future.result()
                print(f"[done] {source.name} job={report['job_id']} status={report['status']}", flush=True)
            except Exception as exc:
                report = {
                    "job_id": "",
                    "source_name": source.name,
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
                print(f"[failed] {source.name}: {report['error']}", flush=True)
            reports.append(report)

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "reports": reports,
    }
    json_path = report_dir / "two_full_tasks_direct_report.json"
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"json": str(json_path)}, ensure_ascii=False, indent=2), flush=True)


def run_source(
    source: Path,
    *,
    output_dir: str,
    workflow_template: str,
    language: str,
) -> dict[str, Any]:
    job_id = asyncio.run(
        create_fresh_job(
            source,
            output_dir=output_dir,
            workflow_template=workflow_template,
            language=language,
        )
    )
    step_runs, status = run_full_chain(job_id)
    finalize_job(job_id, status)
    item = {"path": str(source), "source_name": source.name}
    report = asyncio.run(collect_job_report(job_id, item, step_runs, status))
    return asdict(report)


async def create_fresh_job(
    source: Path,
    *,
    output_dir: str,
    workflow_template: str,
    language: str,
) -> str:
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            source_path=str(source),
            source_name=source.name,
            status="pending",
            language=language,
            output_dir=output_dir,
            workflow_template=workflow_template,
            workflow_mode=str(getattr(settings, "default_job_workflow_mode", None) or "standard_edit"),
            enhancement_modes=list(getattr(settings, "default_job_enhancement_modes", None) or []),
            config_profile_snapshot_json={
                "llm_mode": settings.llm_mode,
                "llm_routing_mode": settings.llm_routing_mode,
                "reasoning_provider": settings.reasoning_provider,
                "reasoning_model": settings.reasoning_model,
                "transcription_provider": settings.transcription_provider,
                "transcription_model": settings.transcription_model,
                "transcription_dialect": settings.transcription_dialect,
            },
        )
        session.add(job)
        await session.flush()
        for step in create_job_steps(job.id):
            session.add(step)
        await session.commit()
        return str(job.id)


def run_full_chain(job_id: str) -> tuple[list[StepRun], str]:
    step_runs: list[StepRun] = []
    status = "done"
    for step_name in PIPELINE_STEPS:
        started = time.perf_counter()
        if step_name == "summary_review":
            auto_confirm_content_profile(job_id)
            step_runs.append(
                StepRun(step=step_name, status="done", elapsed_seconds=round(time.perf_counter() - started, 3), detail=read_step_detail(job_id, step_name))
            )
            continue
        if step_name == "final_review":
            auto_approve_final_review(job_id)
            step_runs.append(
                StepRun(step=step_name, status="done", elapsed_seconds=round(time.perf_counter() - started, 3), detail=read_step_detail(job_id, step_name))
            )
            continue
        mark_step(job_id, step_name, "running")
        try:
            run_step_sync(step_name, job_id)
            mark_step(job_id, step_name, "done")
            step_runs.append(
                StepRun(step=step_name, status="done", elapsed_seconds=round(time.perf_counter() - started, 3), detail=read_step_detail(job_id, step_name))
            )
        except Exception as exc:
            status = "failed"
            error_text = f"{type(exc).__name__}: {exc}"
            mark_step(job_id, step_name, "failed", error=error_text)
            step_runs.append(
                StepRun(step=step_name, status="failed", elapsed_seconds=round(time.perf_counter() - started, 3), error=error_text)
            )
            break
    return step_runs, status


if __name__ == "__main__":
    main()
