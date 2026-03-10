"""
Orchestrator: single-process loop that reads job_steps and advances the state machine.
State in DB, Celery only executes individual steps.

Pipeline: probe → extract_audio → transcribe → subtitle_postprocess → glossary_review → edit_plan → render
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from fastcut.db.models import Job, JobStep
from fastcut.db.session import get_session_factory

logger = logging.getLogger(__name__)

# Step sequence and which Celery queue/task to dispatch to
PIPELINE_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "glossary_review",
    "edit_plan",
    "render",
]

STEP_TASK_MAP = {
    "probe": "fastcut.pipeline.tasks.media_probe",
    "extract_audio": "fastcut.pipeline.tasks.media_extract_audio",
    "transcribe": "fastcut.pipeline.tasks.llm_transcribe",
    "subtitle_postprocess": "fastcut.pipeline.tasks.llm_subtitle_postprocess",
    "glossary_review": "fastcut.pipeline.tasks.llm_glossary_review",
    "edit_plan": "fastcut.pipeline.tasks.media_edit_plan",
    "render": "fastcut.pipeline.tasks.media_render",
}

STEP_QUEUES = {
    "probe": "media_queue",
    "extract_audio": "media_queue",
    "transcribe": "llm_queue",
    "subtitle_postprocess": "llm_queue",
    "glossary_review": "llm_queue",
    "edit_plan": "media_queue",
    "render": "media_queue",
}

MAX_ATTEMPTS = 3


async def tick() -> None:
    """Single orchestrator tick: find ready steps and dispatch them."""
    factory = get_session_factory()
    async with factory() as session:
        # Find all pending steps
        result = await session.execute(
            select(JobStep)
            .join(Job, Job.id == JobStep.job_id)
            .where(
                JobStep.status == "pending",
                JobStep.attempt < MAX_ATTEMPTS,
                Job.status.notin_(["cancelled", "failed"]),
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


async def _is_step_ready(step: JobStep, session) -> bool:
    """Check if all prerequisite steps are done."""
    step_idx = PIPELINE_STEPS.index(step.step_name)
    if step_idx == 0:
        return True  # First step is always ready

    prev_step_name = PIPELINE_STEPS[step_idx - 1]
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
    from fastcut.pipeline.celery_app import celery_app

    task_name = STEP_TASK_MAP[step.step_name]
    queue = STEP_QUEUES[step.step_name]
    job_id = str(step.job_id)

    # Mark as dispatched (running will be set by worker)
    step.status = "running"
    step.started_at = datetime.now(timezone.utc)
    step.attempt += 1

    # Send to Celery
    celery_app.send_task(task_name, args=[job_id], queue=queue)
    logger.info(f"Dispatched {step.step_name} for job {job_id} → {queue}")

    # Update parent job status
    job = await session.get(Job, step.job_id)
    if job and job.status == "pending":
        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)


async def _update_job_statuses(session) -> None:
    """Mark jobs as done or failed based on their steps."""
    result = await session.execute(
        select(Job).where(Job.status == "processing")
    )
    jobs = result.scalars().all()

    for job in jobs:
        steps_result = await session.execute(
            select(JobStep).where(JobStep.job_id == job.id)
        )
        steps = steps_result.scalars().all()
        step_map = {s.step_name: s for s in steps}

        # All steps done = job done
        if all(s.status == "done" for s in steps):
            job.status = "done"
            job.updated_at = datetime.now(timezone.utc)
            logger.info(f"Job {job.id} completed")
            continue

        # Any step failed with max attempts = job failed
        failed_steps = [s for s in steps if s.status == "failed" and s.attempt >= MAX_ATTEMPTS]
        if failed_steps:
            job.status = "failed"
            job.error_message = f"Step {failed_steps[0].step_name} failed after {MAX_ATTEMPTS} attempts"
            job.updated_at = datetime.now(timezone.utc)
            logger.error(f"Job {job.id} failed: {job.error_message}")


async def run_orchestrator(poll_interval: float = 5.0) -> None:
    """Main orchestrator loop."""
    logger.info("Orchestrator started, polling every %.1fs", poll_interval)
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
