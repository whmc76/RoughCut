"""
Orchestrator: single-process loop that reads job_steps and advances the state machine.
State in DB, Celery only executes individual steps.

Pipeline: probe → extract_audio → transcribe → subtitle_postprocess
        → glossary_review → ai_director → avatar_commentary → edit_plan → render → platform_package
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from roughcut.db.models import Job, JobStep
from roughcut.db.session import get_session_factory

logger = logging.getLogger(__name__)

# Step sequence and which Celery queue/task to dispatch to
PIPELINE_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "content_profile",
    "summary_review",
    "glossary_review",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "platform_package",
]

STEP_TASK_MAP = {
    "probe": "roughcut.pipeline.tasks.media_probe",
    "extract_audio": "roughcut.pipeline.tasks.media_extract_audio",
    "transcribe": "roughcut.pipeline.tasks.llm_transcribe",
    "subtitle_postprocess": "roughcut.pipeline.tasks.llm_subtitle_postprocess",
    "content_profile": "roughcut.pipeline.tasks.llm_content_profile",
    "glossary_review": "roughcut.pipeline.tasks.llm_glossary_review",
    "ai_director": "roughcut.pipeline.tasks.llm_ai_director",
    "avatar_commentary": "roughcut.pipeline.tasks.llm_avatar_commentary",
    "edit_plan": "roughcut.pipeline.tasks.media_edit_plan",
    "render": "roughcut.pipeline.tasks.media_render",
    "platform_package": "roughcut.pipeline.tasks.llm_platform_package",
}

STEP_QUEUES = {
    "probe": "media_queue",
    "extract_audio": "media_queue",
    "transcribe": "llm_queue",
    "subtitle_postprocess": "llm_queue",
    "content_profile": "llm_queue",
    "glossary_review": "llm_queue",
    "ai_director": "llm_queue",
    "avatar_commentary": "llm_queue",
    "edit_plan": "media_queue",
    "render": "media_queue",
    "platform_package": "llm_queue",
}

MAX_ATTEMPTS = 3


async def tick() -> None:
    """Single orchestrator tick: find ready steps and dispatch them."""
    factory = get_session_factory()
    async with factory() as session:
        jobs_result = await session.execute(
            select(Job).where(Job.status.notin_(["cancelled", "failed", "done"]))
        )
        for job in jobs_result.scalars().all():
            await _ensure_job_steps(job, session)

        # Find all pending steps
        result = await session.execute(
            select(JobStep)
            .join(Job, Job.id == JobStep.job_id)
            .where(
                JobStep.status == "pending",
                JobStep.attempt < MAX_ATTEMPTS,
                Job.status.notin_(["cancelled", "failed", "needs_review"]),
            )
        )
        pending_steps = result.scalars().all()

        for step in pending_steps:
            ready = await _is_step_ready(step, session)
            if ready:
                await _dispatch_step(step, session)

        # Check for failed jobs (all steps failed)
        await _update_job_statuses(session)
        await session.commit()


async def _recover_incomplete_jobs() -> None:
    """On orchestrator startup, re-queue interrupted or retryable steps."""
    factory = get_session_factory()
    async with factory() as session:
        result = await session.execute(
            select(Job).where(Job.status.notin_(["cancelled", "failed", "done"]))
        )
        jobs = result.scalars().all()
        now = datetime.now(timezone.utc)

        for job in jobs:
            steps_result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
            steps = steps_result.scalars().all()
            recovered = False

            for step in steps:
                if step.status == "running":
                    step.status = "pending"
                    step.started_at = None
                    step.finished_at = None
                    step.error_message = None
                    step.metadata_ = {
                        **(step.metadata_ or {}),
                        "detail": "服务重启后自动恢复，步骤重新入队。",
                        "updated_at": now.isoformat(),
                    }
                    recovered = True
                elif step.status == "failed" and step.attempt < MAX_ATTEMPTS:
                    step.status = "pending"
                    step.started_at = None
                    step.finished_at = None
                    step.error_message = None
                    step.metadata_ = {
                        **(step.metadata_ or {}),
                        "detail": "检测到可重试失败步骤，启动时已自动续跑。",
                        "updated_at": now.isoformat(),
                    }
                    recovered = True

            if recovered and job.status != "needs_review":
                job.status = "processing"
                job.error_message = None
                job.updated_at = now
                logger.info("Recovered incomplete job %s for auto-resume", job.id)

        await session.commit()


async def _is_step_ready(step: JobStep, session) -> bool:
    """Check if all prerequisite steps are done."""
    if step.step_name == "summary_review":
        return False

    step_idx = PIPELINE_STEPS.index(step.step_name)
    if step_idx == 0:
        return True  # First step is always ready

    existing_steps_result = await session.execute(
        select(JobStep.step_name).where(JobStep.job_id == step.job_id)
    )
    existing_step_names = {name for name in existing_steps_result.scalars().all()}
    prev_step_name = _find_previous_existing_step_name(step.step_name, existing_step_names)
    if prev_step_name is None:
        return True
    result = await session.execute(
        select(JobStep).where(
            JobStep.job_id == step.job_id,
            JobStep.step_name == prev_step_name,
        )
    )
    prev_step = result.scalar_one_or_none()
    return prev_step is not None and prev_step.status == "done"


async def _dispatch_step(step: JobStep, session) -> None:
    """Dispatch a step to the appropriate Celery queue."""
    from roughcut.pipeline.celery_app import celery_app

    task_name = STEP_TASK_MAP[step.step_name]
    queue = STEP_QUEUES[step.step_name]
    job_id = str(step.job_id)

    # Mark as dispatched (running will be set by worker)
    step.status = "running"
    step.started_at = datetime.now(timezone.utc)
    step.attempt += 1

    # Send to Celery
    async_result = celery_app.send_task(task_name, args=[job_id], queue=queue)
    step.metadata_ = {
        **(step.metadata_ or {}),
        "task_id": async_result.id,
        "queue": queue,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info(f"Dispatched {step.step_name} for job {job_id} → {queue}")

    # Update parent job status
    job = await session.get(Job, step.job_id)
    if job and job.status == "pending":
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)


async def _update_job_statuses(session) -> None:
    """Mark jobs as done or failed based on their steps."""
    result = await session.execute(
        select(Job).where(Job.status.in_(["processing", "needs_review"]))
    )
    jobs = result.scalars().all()

    for job in jobs:
        steps_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id)
        )
        steps = steps_result.scalars().all()
        step_map = {s.step_name: s for s in steps}
        ordered_existing_steps = [
            step_map[name]
            for name in PIPELINE_STEPS
            if name in step_map
        ]
        last_existing_step = ordered_existing_steps[-1] if ordered_existing_steps else None

        # All steps done = job done
        if all(s.status == "done" for s in steps):
            job.status = "done"
            job.error_message = None
            job.updated_at = datetime.now(timezone.utc)
            logger.info(f"Job {job.id} completed")
            continue

        if last_existing_step is not None and last_existing_step.status == "done":
            _reconcile_terminal_steps(job, ordered_existing_steps)
            job.status = "done"
            job.error_message = None
            job.updated_at = datetime.now(timezone.utc)
            logger.info(f"Job {job.id} reconciled to completed from terminal step {last_existing_step.step_name}")
            continue

        review_step = step_map.get("summary_review")
        draft_step = step_map.get("content_profile")
        if (
            draft_step is not None
            and draft_step.status == "done"
            and review_step is not None
            and review_step.status == "pending"
        ):
            job.status = "needs_review"
            job.updated_at = datetime.now(timezone.utc)
            continue

        # Any step failed with max attempts = job failed
        failed_steps = [s for s in steps if s.status == "failed" and s.attempt >= MAX_ATTEMPTS]
        if failed_steps:
            job.status = "failed"
            job.error_message = f"Step {failed_steps[0].step_name} failed after {MAX_ATTEMPTS} attempts"
            job.updated_at = datetime.now(timezone.utc)
            logger.error(f"Job {job.id} failed: {job.error_message}")


async def _ensure_job_steps(job: Job, session) -> None:
    result = await session.execute(select(JobStep).where(JobStep.job_id == job.id))
    existing_steps = result.scalars().all()
    existing_names = {step.step_name for step in existing_steps}
    missing_steps = [step_name for step_name in PIPELINE_STEPS if step_name not in existing_names]
    if not missing_steps:
        return
    for step_name in missing_steps:
        session.add(JobStep(job_id=job.id, step_name=step_name, status="pending"))
    logger.info("Backfilled missing steps for job %s: %s", job.id, ", ".join(missing_steps))


def _find_previous_existing_step_name(step_name: str, existing_step_names: set[str]) -> str | None:
    step_idx = PIPELINE_STEPS.index(step_name)
    for index in range(step_idx - 1, -1, -1):
        candidate = PIPELINE_STEPS[index]
        if candidate in existing_step_names:
            return candidate
    return None


def _reconcile_terminal_steps(job: Job, steps: list[JobStep]) -> None:
    now = datetime.now(timezone.utc)
    enabled_modes = set(getattr(job, "enhancement_modes", []) or [])
    for step in steps:
        if step.status == "done":
            step.error_message = None
            continue
        if step.step_name == "ai_director" and "ai_director" not in enabled_modes:
            step.status = "skipped"
        elif step.step_name == "avatar_commentary" and "avatar_commentary" not in enabled_modes:
            step.status = "skipped"
        elif float((step.metadata_ or {}).get("progress") or 0.0) >= 1.0 and step.status in {"pending", "running"}:
            step.status = "done"
        else:
            continue
        step.finished_at = step.finished_at or now
        step.error_message = None


async def run_orchestrator(poll_interval: float = 5.0) -> None:
    """Main orchestrator loop."""
    logger.info("Orchestrator started, polling every %.1fs", poll_interval)
    await _recover_incomplete_jobs()
    while True:
        try:
            await tick()
        except Exception:
            logger.exception("Orchestrator tick error")
        await asyncio.sleep(poll_interval)


def create_job_steps(job_id: uuid.UUID) -> list[JobStep]:
    """Create all pipeline steps for a new job."""
    return [
        JobStep(job_id=job_id, step_name=step_name, status="pending")
        for step_name in PIPELINE_STEPS
    ]
