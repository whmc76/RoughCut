from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from typing import Iterable

from sqlalchemy import select

from roughcut.db.models import Job, JobStep
from roughcut.db.session import get_session_factory
from roughcut.pipeline.orchestrator import _reset_job_for_quality_rerun
from roughcut.pipeline.steps import run_step_sync
from roughcut.pipeline.tasks import _apply_job_runtime_snapshot, _update_step_status

RERUN_STEPS = ["avatar_commentary", "edit_plan", "render", "final_review", "platform_package"]
EXECUTE_STEPS = ["avatar_commentary", "edit_plan", "render"]


async def _reset_jobs(job_ids: Iterable[str], *, issue_codes: list[str]) -> list[str]:
    factory = get_session_factory()
    reset_ids: list[str] = []
    async with factory() as session:
        for job_id_text in job_ids:
            job_id = uuid.UUID(job_id_text)
            job = await session.get(Job, job_id)
            if job is None:
                continue
            steps = (await session.execute(select(JobStep).where(JobStep.job_id == job.id))).scalars().all()
            await _reset_job_for_quality_rerun(
                session,
                job,
                steps,
                rerun_steps=RERUN_STEPS,
                issue_codes=issue_codes,
            )
            reset_ids.append(job_id_text)
        await session.commit()
    return reset_ids


def _run_single_step(job_id: str, step: str) -> dict:
    task_id = f"manual-{step}"
    if not _update_step_status(job_id, step, "running", task_id=task_id):
        raise RuntimeError(f"cannot transition {step} to running")
    _apply_job_runtime_snapshot(job_id)
    try:
        result = run_step_sync(step, job_id)
    except Exception as exc:
        _update_step_status(job_id, step, "failed", str(exc), task_id=task_id)
        raise
    if not _update_step_status(job_id, step, "done", task_id=task_id):
        raise RuntimeError(f"cannot transition {step} to done")
    return result


def _run_job(job_id: str) -> dict:
    step_results: dict[str, dict] = {}
    for step in EXECUTE_STEPS:
        step_results[step] = _run_single_step(job_id, step)
        print(json.dumps({"job_id": job_id, "step": step, "result": step_results[step]}, ensure_ascii=False), flush=True)
    return step_results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", action="append", dest="job_ids", required=True)
    parser.add_argument("--issue-code", action="append", dest="issue_codes", default=["manual_avatar_rerun_batch"])
    args = parser.parse_args()

    reset_ids = asyncio.run(_reset_jobs(args.job_ids, issue_codes=args.issue_codes))
    print(json.dumps({"reset_jobs": reset_ids}, ensure_ascii=False), flush=True)

    results: dict[str, dict] = {}
    failures: dict[str, str] = {}
    for job_id in reset_ids:
        try:
            results[job_id] = _run_job(job_id)
        except Exception as exc:  # pragma: no cover - operational path
            failures[job_id] = str(exc)
            print(json.dumps({"job_id": job_id, "error": str(exc)}, ensure_ascii=False), flush=True)

    print(
        json.dumps(
            {
                "completed_jobs": sorted(results.keys()),
                "failed_jobs": failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
