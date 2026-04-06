"""
Orchestrator: single-process loop that reads job_steps and advances the state machine.
State in DB, Celery only executes individual steps.

 Pipeline: probe → extract_audio → transcribe → subtitle_postprocess
        → glossary_review → subtitle_translation → content_profile → summary_review → ai_director
        → avatar_commentary → edit_plan → render → final_review → platform_package
"""
from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import text

from roughcut.config import get_settings
from roughcut.db.models import Artifact, Job, JobStep, RenderOutput, SubtitleCorrection, SubtitleItem, Timeline
from roughcut.db.session import get_session_factory
from roughcut.pipeline.quality import QUALITY_ARTIFACT_TYPE, assess_job_quality
from roughcut.review.evidence_types import (
    ARTIFACT_TYPE_CONTENT_PROFILE_OCR,
    ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE,
    ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE,
)
from roughcut.storage.runtime_cleanup import cleanup_job_runtime_files

logger = logging.getLogger(__name__)

# Step sequence and which Celery queue/task to dispatch to
PIPELINE_STEPS = [
    "probe",
    "extract_audio",
    "transcribe",
    "subtitle_postprocess",
    "glossary_review",
    "subtitle_translation",
    "content_profile",
    "summary_review",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "final_review",
    "platform_package",
]

STEP_TASK_MAP = {
    "probe": "roughcut.pipeline.tasks.media_probe",
    "extract_audio": "roughcut.pipeline.tasks.media_extract_audio",
    "transcribe": "roughcut.pipeline.tasks.llm_transcribe",
    "subtitle_postprocess": "roughcut.pipeline.tasks.llm_subtitle_postprocess",
    "subtitle_translation": "roughcut.pipeline.tasks.llm_subtitle_translation",
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
    "subtitle_translation": "llm_queue",
    "content_profile": "llm_queue",
    "glossary_review": "llm_queue",
    "ai_director": "llm_queue",
    "avatar_commentary": "llm_queue",
    "edit_plan": "media_queue",
    "render": "media_queue",
    "platform_package": "llm_queue",
}

MAX_ATTEMPTS = 3
_GPU_SENSITIVE_STEPS = {"transcribe", "avatar_commentary", "render"}
_QUALITY_RERUN_STEPS = {
    "subtitle_postprocess",
    "glossary_review",
    "subtitle_translation",
    "content_profile",
    "ai_director",
    "avatar_commentary",
    "edit_plan",
    "render",
    "final_review",
    "platform_package",
}
_REVIEW_ROUND_STEPS = {"summary_review", "glossary_review", "final_review"}
_ORCHESTRATOR_ADVISORY_LOCK_KEY = 22032026


class _SingleActiveOrchestratorLease:
    def __init__(self) -> None:
        self._engine = None
        self._conn = None

    async def try_acquire(self) -> bool:
        if self._conn is not None:
            return True
        if not _supports_postgres_orchestrator_lock():
            return True

        settings = get_settings()
        engine = create_async_engine(
            settings.database_url,
            echo=False,
            poolclass=NullPool,
        )
        conn = None
        try:
            conn = await engine.connect()
            acquired = bool(
                (
                    await conn.execute(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": _ORCHESTRATOR_ADVISORY_LOCK_KEY},
                    )
                ).scalar()
            )
            if not acquired:
                await conn.close()
                await engine.dispose()
                return False
            self._engine = engine
            self._conn = conn
            return True
        except Exception:
            if conn is not None:
                await conn.close()
            await engine.dispose()
            raise

    async def release(self) -> None:
        if self._conn is None:
            return
        try:
            await self._conn.execute(
                text("SELECT pg_advisory_unlock(:lock_key)"),
                {"lock_key": _ORCHESTRATOR_ADVISORY_LOCK_KEY},
            )
        except Exception:
            logger.warning("Failed to release orchestrator advisory lock", exc_info=True)
        finally:
            await self._conn.close()
            await self._engine.dispose()
            self._conn = None
            self._engine = None


def _supports_postgres_orchestrator_lock() -> bool:
    scheme = str(get_settings().database_url or "").split(":", 1)[0].lower()
    return scheme in {"postgresql", "postgresql+asyncpg", "postgres"}


async def get_orchestrator_lock_snapshot() -> dict[str, object]:
    if not _supports_postgres_orchestrator_lock():
        return {
            "status": "unsupported",
            "leader_active": None,
            "detail": "Current database backend does not support PostgreSQL advisory locks.",
        }

    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        poolclass=NullPool,
    )
    try:
        async with engine.connect() as conn:
            acquired = bool(
                (
                    await conn.execute(
                        text("SELECT pg_try_advisory_lock(:lock_key)"),
                        {"lock_key": _ORCHESTRATOR_ADVISORY_LOCK_KEY},
                    )
                ).scalar()
            )
            if acquired:
                await conn.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": _ORCHESTRATOR_ADVISORY_LOCK_KEY},
                )
                return {
                    "status": "free",
                    "leader_active": False,
                    "detail": "No active orchestrator lock holder detected.",
                }
            return {
                "status": "held",
                "leader_active": True,
                "detail": "An active orchestrator currently holds the single-active lock.",
            }
    except Exception as exc:
        return {
            "status": "unknown",
            "leader_active": None,
            "detail": str(exc),
        }
    finally:
        await engine.dispose()


async def tick() -> None:
    """Single orchestrator tick: find ready steps and dispatch them."""
    try:
        from roughcut.runtime_preflight import ensure_runtime_services_ready

        await ensure_runtime_services_ready(reason="orchestrator_tick")
    except Exception:
        logger.exception("Runtime preflight failed")

    factory = get_session_factory()
    async with factory() as session:
        jobs_result = await session.execute(
            select(Job).where(Job.status.notin_(["cancelled", "failed", "done"]))
        )
        for job in jobs_result.scalars().all():
            await _ensure_job_steps(job, session)

        try:
            from roughcut.watcher.folder_watcher import run_watch_root_auto_duty

            duty_summary = await run_watch_root_auto_duty()
            if any(int(duty_summary.get(key) or 0) > 0 for key in ("scan_started", "auto_merged_jobs", "auto_enqueued_jobs")):
                logger.info(
                    "watch duty tick roots=%s scan_started=%s auto_merged_jobs=%s auto_enqueued_jobs=%s idle_slots=%s",
                    duty_summary.get("roots_total"),
                    duty_summary.get("scan_started"),
                    duty_summary.get("auto_merged_jobs"),
                    duty_summary.get("auto_enqueued_jobs"),
                    duty_summary.get("idle_slots"),
                )
        except Exception:
            logger.exception("Watch auto duty tick failed")

        await _recover_stale_running_steps(session)
        running_gpu_steps = await _count_running_gpu_steps(session)

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
            retry_wait_remaining = _step_retry_wait_remaining(step)
            if retry_wait_remaining > 0:
                _set_step_waiting_metadata(
                    step,
                    detail=f"资源等待中，约 {retry_wait_remaining}s 后自动重试。",
                    retry_after_sec=retry_wait_remaining,
                )
                continue

            ready = await _is_step_ready(step, session)
            if not ready:
                continue

            gpu_wait_reason = _gpu_dispatch_wait_reason(step.step_name, running_gpu_steps=running_gpu_steps)
            if gpu_wait_reason:
                _set_step_waiting_metadata(step, detail=gpu_wait_reason)
                continue

            await _dispatch_step(step, session)
            if _step_requires_local_gpu_for_dispatch(step.step_name):
                running_gpu_steps += 1

        # Check for failed jobs (all steps failed)
        await _update_job_statuses(session)
        await session.commit()


def _step_retry_wait_remaining(step: JobStep) -> int:
    metadata = step.metadata_ or {}
    retry_wait_until = metadata.get("retry_wait_until")
    if retry_wait_until in (None, "", 0):
        return 0
    try:
        wait_until = float(retry_wait_until)
    except (TypeError, ValueError):
        return 0
    remaining = wait_until - datetime.now(timezone.utc).timestamp()
    return max(0, int(math.ceil(remaining)))


async def _count_running_gpu_steps(session) -> int:
    result = await session.execute(
        select(JobStep.step_name)
        .join(Job, Job.id == JobStep.job_id)
        .where(
            JobStep.status == "running",
            JobStep.step_name.in_(sorted(_GPU_SENSITIVE_STEPS)),
            Job.status.notin_(["cancelled", "failed", "done"]),
        )
    )
    running_step_names = [str(step_name or "").strip().lower() for step_name in result.scalars().all()]
    return sum(1 for step_name in running_step_names if _step_requires_local_gpu_for_dispatch(step_name))


def _step_stale_timeout_seconds(step_name: str) -> int:
    settings = get_settings()
    if step_name == "render":
        return max(600, int(getattr(settings, "render_step_stale_timeout_sec", 5400) or 5400))
    return max(300, int(getattr(settings, "step_stale_timeout_sec", 900) or 900))


def _step_last_heartbeat_at(step: JobStep) -> datetime | None:
    metadata = step.metadata_ or {}
    updated_at = metadata.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        try:
            return _coerce_utc(datetime.fromisoformat(updated_at))
        except ValueError:
            return None
    return _coerce_utc(step.started_at) if step.started_at is not None else None


async def _recover_stale_running_steps(session) -> None:
    settings = get_settings()
    if not bool(getattr(settings, "step_stale_recovery_enabled", True)):
        return

    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(JobStep)
        .join(Job, Job.id == JobStep.job_id)
        .where(
            JobStep.status == "running",
            Job.status.notin_(["cancelled", "failed", "done"]),
        )
    )
    stale_steps = result.scalars().all()
    for step in stale_steps:
        last_heartbeat_at = _step_last_heartbeat_at(step)
        if last_heartbeat_at is None:
            continue
        stale_after = _step_stale_timeout_seconds(step.step_name)
        if (now - last_heartbeat_at).total_seconds() < stale_after:
            continue

        from roughcut.recovery import stuck_step_recovery as stuck_step_recovery_mod

        job = await session.get(Job, step.job_id)
        if job is not None:
            await stuck_step_recovery_mod.record_stuck_step_diagnostic(
                session,
                job,
                step,
                stale_after_sec=stale_after,
                applied_action="reset_to_pending",
                now=now,
            )
        metadata = dict(step.metadata_ or {})
        previous_task_id = metadata.pop("task_id", None)
        metadata.pop("retry_wait_until", None)
        metadata.pop("retry_after_sec", None)
        metadata["detail"] = f"检测到步骤心跳超时({stale_after}s)，调度器已自动回收并重新入队。"
        metadata["updated_at"] = now.isoformat()
        if step.step_name == "render":
            metadata["progress"] = 0.0
            render_outputs_result = await session.execute(
                select(RenderOutput).where(RenderOutput.job_id == step.job_id, RenderOutput.status == "running")
            )
            for render_output in render_outputs_result.scalars().all():
                render_output.status = "failed"

        step.status = "pending"
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        step.metadata_ = metadata

        job = await session.get(Job, step.job_id)
        if job is not None and job.status != "needs_review":
            job.status = "processing"
            job.error_message = None
            job.updated_at = now

        logger.warning(
            "Recovered stale running step job=%s step=%s previous_task_id=%s stale_after=%ss",
            step.job_id,
            step.step_name,
            previous_task_id,
            stale_after,
        )


def _gpu_dispatch_wait_reason(step_name: str, *, running_gpu_steps: int) -> str | None:
    if not _step_requires_local_gpu_for_dispatch(step_name):
        return None
    if running_gpu_steps > 0:
        return "检测到 RoughCut 仍有 GPU 步骤运行，当前步骤等待空闲后再派发。"
    try:
        from roughcut.pipeline.tasks import _probe_local_gpu_pressure

        busy_reason = _probe_local_gpu_pressure(step_name)
    except Exception:
        return None
    if not busy_reason:
        return None
    return f"{busy_reason} 调度器暂不派发新的 GPU 任务。"


def _step_requires_local_gpu_for_dispatch(step_name: str) -> bool:
    try:
        from roughcut.pipeline.tasks import _step_requires_local_gpu

        return bool(_step_requires_local_gpu(step_name))
    except Exception:
        return step_name in _GPU_SENSITIVE_STEPS


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _set_step_waiting_metadata(
    step: JobStep,
    *,
    detail: str,
    retry_after_sec: int | None = None,
) -> None:
    metadata = dict(step.metadata_ or {})
    metadata["detail"] = detail
    metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    if retry_after_sec is not None:
        metadata["retry_after_sec"] = retry_after_sec
    step.metadata_ = metadata


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
                    last_heartbeat_at = _step_last_heartbeat_at(step)
                    if last_heartbeat_at is not None:
                        stale_after = _step_stale_timeout_seconds(step.step_name)
                        if (now - last_heartbeat_at).total_seconds() < stale_after:
                            continue
                    metadata = dict(step.metadata_ or {})
                    metadata.pop("task_id", None)
                    metadata.pop("retry_wait_until", None)
                    metadata.pop("retry_after_sec", None)
                    step.status = "pending"
                    step.started_at = None
                    step.finished_at = None
                    step.error_message = None
                    step.metadata_ = {
                        **metadata,
                        "detail": "服务重启后自动恢复，步骤重新入队。",
                        "updated_at": now.isoformat(),
                    }
                    recovered = True
                elif step.status == "failed" and step.attempt < MAX_ATTEMPTS:
                    metadata = dict(step.metadata_ or {})
                    metadata.pop("task_id", None)
                    metadata.pop("retry_wait_until", None)
                    metadata.pop("retry_after_sec", None)
                    step.status = "pending"
                    step.started_at = None
                    step.finished_at = None
                    step.error_message = None
                    step.metadata_ = {
                        **metadata,
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
    if step.step_name in {"summary_review", "final_review"}:
        return False

    step_idx = PIPELINE_STEPS.index(step.step_name)
    if step_idx == 0:
        return True  # First step is always ready

    existing_steps_result = await session.execute(
        select(JobStep).where(JobStep.job_id == step.job_id)
    )
    steps_by_name = {
        existing_step.step_name: existing_step
        for existing_step in existing_steps_result.scalars().all()
    }
    for prerequisite_name in PIPELINE_STEPS[:step_idx]:
        prerequisite = steps_by_name.get(prerequisite_name)
        if prerequisite is None:
            continue
        if prerequisite.status not in {"done", "skipped"}:
            return False
    return True


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
        await _reconcile_completed_render_step(session, job, step_map)
        ordered_existing_steps = [
            step_map[name]
            for name in PIPELINE_STEPS
            if name in step_map
        ]
        _reconcile_terminal_steps(job, ordered_existing_steps)
        last_existing_step = ordered_existing_steps[-1] if ordered_existing_steps else None

        done_candidate = all(s.status == "done" for s in steps) or (
            last_existing_step is not None and last_existing_step.status == "done"
        )
        if done_candidate:
            rerun_started = await _assess_and_maybe_rerun_job(session, job, steps)
            if rerun_started:
                continue
            job.status = "done"
            job.error_message = None
            job.updated_at = datetime.now(timezone.utc)
            await _cleanup_terminal_job_files(session, job, purge_deliverables=False)
            logger.info("Job %s completed", job.id)
            continue

        review_step = step_map.get("summary_review")
        draft_step = step_map.get("content_profile")
        final_review_step = step_map.get("final_review")
        render_step = step_map.get("render")
        if (
            draft_step is not None
            and draft_step.status == "done"
            and review_step is not None
            and review_step.status == "pending"
        ):
            job.status = "needs_review"
            job.updated_at = datetime.now(timezone.utc)
            continue
        if (
            render_step is not None
            and render_step.status == "done"
            and final_review_step is not None
            and final_review_step.status == "pending"
        ):
            job.status = "needs_review"
            job.updated_at = datetime.now(timezone.utc)
            continue

        # Any step failed with max attempts = job failed
        failed_steps = [s for s in steps if s.status == "failed" and s.attempt >= MAX_ATTEMPTS]
        if failed_steps:
            job.status = "failed"
            job.error_message = _build_job_failure_message(_latest_failed_step(steps), attempts=MAX_ATTEMPTS)
            job.updated_at = datetime.now(timezone.utc)
            await _cleanup_terminal_job_files(session, job, purge_deliverables=True)
            logger.error(f"Job {job.id} failed: {job.error_message}")


def _latest_failed_step(steps: list[JobStep]) -> JobStep | None:
    step_map = {step.step_name: step for step in steps}
    for step_name in reversed(PIPELINE_STEPS):
        step = step_map.get(step_name)
        if step is not None and step.status == "failed" and step.attempt >= MAX_ATTEMPTS:
            return step
    return None


def _build_job_failure_message(failed_step: JobStep | None, *, attempts: int) -> str:
    if failed_step is None:
        return f"任务失败：检测到失败步骤但未定位到具体步骤，已重试 {attempts} 次仍未恢复。"

    metadata = failed_step.metadata_ or {}
    details: list[str] = [str(failed_step.error_message or "").strip()]
    detail = str(metadata.get("detail") or "").strip()
    if detail:
        details.append(detail)
    recovery_summary = str(metadata.get("recovery_summary") or "").strip()
    if recovery_summary:
        details.append(f"恢复建议：{recovery_summary}")
    root_cause = str(metadata.get("recovery_root_cause") or "").strip()
    if root_cause:
        details.append(f"恢复根因：{root_cause}")

    cleaned = [item for item in details if item]
    if cleaned:
        return f"{failed_step.step_name} 步骤在最大重试（{attempts}）后仍失败：{'; '.join(cleaned)}"
    return f"{failed_step.step_name} 步骤在最大重试（{attempts}）后仍失败"


async def _cleanup_terminal_job_files(session, job: Job, *, purge_deliverables: bool) -> None:
    artifact_result = await session.execute(select(Artifact).where(Artifact.job_id == job.id))
    render_output_result = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job.id))
    cleanup_job_runtime_files(
        str(job.id),
        artifacts=artifact_result.scalars().all(),
        render_outputs=render_output_result.scalars().all(),
        purge_deliverables=purge_deliverables,
        preserve_storage_keys=[str(getattr(job, "source_path", "") or "").strip()],
    )


async def _reconcile_completed_render_step(session, job: Job, step_map: dict[str, JobStep]) -> None:
    render_step = step_map.get("render")
    if render_step is None or render_step.status == "done":
        return

    render_output_result = await session.execute(
        select(RenderOutput)
        .where(RenderOutput.job_id == job.id, RenderOutput.status == "done")
        .order_by(RenderOutput.created_at.desc())
    )
    render_output = render_output_result.scalars().first()
    if render_output is None or not render_output.output_path:
        return

    render_step.status = "done"
    render_step.finished_at = render_step.finished_at or datetime.now(timezone.utc)
    render_step.error_message = None
    render_step.metadata_ = {
        **(render_step.metadata_ or {}),
        "detail": "检测到已完成渲染输出，调度器已自动收口 render 步骤。",
        "progress": 1.0,
        "output_path": render_output.output_path,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Job %s reconciled render step from completed render output", job.id)


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


async def _assess_and_maybe_rerun_job(session, job: Job, steps: list[JobStep]) -> bool:
    artifacts_result = await session.execute(
        select(Artifact).where(Artifact.job_id == job.id).order_by(Artifact.created_at.asc(), Artifact.id.asc())
    )
    artifacts = artifacts_result.scalars().all()
    subtitle_result = await session.execute(
        select(SubtitleItem).where(SubtitleItem.job_id == job.id).order_by(SubtitleItem.version.desc(), SubtitleItem.item_index.asc())
    )
    subtitle_items = subtitle_result.scalars().all()
    corrections_result = await session.execute(select(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
    corrections = corrections_result.scalars().all()

    assessment = assess_job_quality(
        job=job,
        steps=steps,
        artifacts=artifacts,
        subtitle_items=subtitle_items,
        corrections=corrections,
        completion_candidate=True,
    )
    previous_quality = _latest_quality_assessment(artifacts)
    previous_payload = previous_quality.data_json if previous_quality and isinstance(previous_quality.data_json, dict) else {}
    previous_count = int(previous_payload.get("auto_rerun_count") or 0)
    previous_history = list(previous_payload.get("auto_rerun_history") or [])
    recommended_steps = [
        str(step_name).strip()
        for step_name in assessment.get("recommended_rerun_steps") or []
        if str(step_name).strip() in _QUALITY_RERUN_STEPS
    ]
    recommended_step = recommended_steps[0] if recommended_steps else ""
    issue_codes = [str(code) for code in assessment.get("issue_codes") or [] if str(code).strip()]
    reason_signature = "|".join(sorted(issue_codes))

    settings = get_settings()
    should_rerun = (
        bool(getattr(settings, "quality_auto_rerun_enabled", True))
        and bool(assessment.get("auto_fixable"))
        and bool(recommended_steps)
        and float(assessment.get("score") or 0.0) < float(getattr(settings, "quality_auto_rerun_below_score", 75.0) or 75.0)
        and previous_count < int(getattr(settings, "quality_auto_rerun_max_attempts", 1) or 1)
        and not any(
            str(item.get("step") or "") == recommended_step and str(item.get("signature") or "") == reason_signature
            for item in previous_history
            if isinstance(item, dict)
        )
    )

    now = datetime.now(timezone.utc)
    history_entry = {
        "at": now.isoformat(),
        "step": recommended_step or None,
        "signature": reason_signature,
        "score": assessment.get("score"),
        "issue_codes": issue_codes,
    }
    payload = {
        **assessment,
        "assessed_at": now.isoformat(),
        "auto_rerun_count": previous_count,
        "auto_rerun_history": previous_history,
        "auto_rerun_triggered": False,
    }

    if should_rerun and recommended_steps:
        await _reset_job_for_quality_rerun(
            session,
            job,
            steps,
            rerun_steps=recommended_steps,
            issue_codes=issue_codes,
        )
        payload["auto_rerun_triggered"] = True
        payload["auto_rerun_count"] = previous_count + 1
        payload["auto_rerun_history"] = [*previous_history, history_entry]
        payload["auto_rerun_step"] = recommended_step
        payload["auto_rerun_steps"] = recommended_steps
        session.add(
            Artifact(
                job_id=job.id,
                artifact_type=QUALITY_ARTIFACT_TYPE,
                data_json=payload,
            )
        )
        logger.info(
            "Job %s scheduled automatic quality rerun from %s, score=%.1f issues=%s",
            job.id,
            recommended_step,
            float(assessment.get("score") or 0.0),
            ",".join(issue_codes),
        )
        return True

    if recommended_step and previous_count >= int(getattr(settings, "quality_auto_rerun_max_attempts", 1) or 1):
        payload["auto_rerun_skipped_reason"] = "max_attempts_reached"
    elif recommended_step and any(
        str(item.get("step") or "") == recommended_step and str(item.get("signature") or "") == reason_signature
        for item in previous_history
        if isinstance(item, dict)
    ):
        payload["auto_rerun_skipped_reason"] = "same_issue_already_retried"

    session.add(
        Artifact(
            job_id=job.id,
            artifact_type=QUALITY_ARTIFACT_TYPE,
            data_json=payload,
        )
    )
    return False


def _latest_quality_assessment(artifacts: list[Artifact]) -> Artifact | None:
    assessments = [artifact for artifact in artifacts if artifact.artifact_type == QUALITY_ARTIFACT_TYPE]
    if not assessments:
        return None
    return max(assessments, key=lambda artifact: (artifact.created_at, str(artifact.id)))


async def _reset_job_for_quality_rerun(
    session,
    job: Job,
    steps: list[JobStep],
    *,
    rerun_steps: list[str],
    issue_codes: list[str],
) -> None:
    rerun_step_set = set(rerun_steps)
    cleanup_artifact_types = _artifact_types_for_quality_rerun(rerun_step_set)

    if cleanup_artifact_types:
        artifact_result = await session.execute(
            select(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type.in_(sorted(cleanup_artifact_types)))
        )
        cleanup_artifacts = artifact_result.scalars().all()
        for artifact in cleanup_artifacts:
            _cleanup_artifact_files(artifact)
        await session.execute(
            delete(Artifact).where(Artifact.job_id == job.id, Artifact.artifact_type.in_(sorted(cleanup_artifact_types)))
        )

    if "render" in rerun_step_set:
        render_output_result = await session.execute(select(RenderOutput).where(RenderOutput.job_id == job.id))
        for output in render_output_result.scalars().all():
            if output.output_path:
                _unlink_local_path(output.output_path)
        await session.execute(delete(RenderOutput).where(RenderOutput.job_id == job.id))

    if "edit_plan" in rerun_step_set:
        await session.execute(delete(Timeline).where(Timeline.job_id == job.id))

    if "subtitle_postprocess" in rerun_step_set:
        await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))
        await session.execute(delete(SubtitleItem).where(SubtitleItem.job_id == job.id))
    elif "glossary_review" in rerun_step_set:
        await session.execute(delete(SubtitleCorrection).where(SubtitleCorrection.job_id == job.id))

    now = datetime.now(timezone.utc)
    reason_text = "、".join(issue_codes) if issue_codes else "quality_gate"
    first_step = next((step_name for step_name in PIPELINE_STEPS if step_name in rerun_step_set), "")
    for step in steps:
        if step.step_name not in rerun_step_set:
            continue
        previous_metadata = dict(step.metadata_ or {})
        step.status = "pending"
        step.attempt = 0
        step.started_at = None
        step.finished_at = None
        step.error_message = None
        detail = (
            f"质量评分触发自动改进重跑：{reason_text}"
            if step.step_name == first_step
            else "等待自动改进重跑链路继续。"
        )
        metadata = {
            "detail": detail,
            "updated_at": now.isoformat(),
        }
        if step.step_name in _REVIEW_ROUND_STEPS:
            metadata["review_round"] = _coerce_review_round(previous_metadata.get("review_round")) + 1
            metadata["telegram_review_notifications"] = {}
        step.metadata_ = metadata

    job.status = "processing"
    job.error_message = None
    job.updated_at = now


def _coerce_review_round(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 1
    return parsed if parsed > 0 else 1


def _artifact_types_for_quality_rerun(rerun_steps: set[str]) -> set[str]:
    artifact_types: set[str] = set()
    settings = get_settings()
    if "subtitle_translation" in rerun_steps:
        artifact_types.add("subtitle_translation")
    if "transcribe" in rerun_steps and bool(getattr(settings, "asr_evidence_enabled", False)):
        artifact_types.add(ARTIFACT_TYPE_TRANSCRIPT_EVIDENCE)
    if "content_profile" in rerun_steps:
        artifact_types.update({"content_profile", "content_profile_draft", "content_profile_final"})
        if bool(getattr(settings, "ocr_enabled", False)):
            artifact_types.add(ARTIFACT_TYPE_CONTENT_PROFILE_OCR)
        if bool(getattr(settings, "entity_graph_enabled", False)):
            artifact_types.add(ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE)
    elif "glossary_review" in rerun_steps and bool(getattr(settings, "entity_graph_enabled", False)):
        artifact_types.add(ARTIFACT_TYPE_ENTITY_RESOLUTION_TRACE)
    if "ai_director" in rerun_steps:
        artifact_types.add("ai_director_plan")
    if "avatar_commentary" in rerun_steps:
        artifact_types.add("avatar_commentary_plan")
    if "render" in rerun_steps:
        artifact_types.update({"render_outputs", "variant_timeline_bundle", QUALITY_ARTIFACT_TYPE})
    if "platform_package" in rerun_steps:
        artifact_types.add("platform_packaging_md")
    return artifact_types


def _cleanup_artifact_files(artifact: Artifact) -> None:
    if artifact.storage_path:
        _unlink_local_path(artifact.storage_path)
    if artifact.artifact_type == "render_outputs" and isinstance(artifact.data_json, dict):
        for path in _collect_local_paths(artifact.data_json):
            _unlink_local_path(path)


def _collect_local_paths(payload: object) -> set[str]:
    paths: set[str] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            paths.update(_collect_local_paths(value))
    elif isinstance(payload, list):
        for value in payload:
            paths.update(_collect_local_paths(value))
    elif isinstance(payload, str):
        candidate = payload.strip()
        if _looks_like_local_path(candidate):
            paths.add(candidate)
    return paths


def _looks_like_local_path(value: str) -> bool:
    if not value or "://" in value:
        return False
    if "\\" not in value and "/" not in value:
        return False
    suffix = Path(value).suffix.lower()
    return bool(suffix)


def _unlink_local_path(value: str) -> None:
    try:
        Path(value).unlink(missing_ok=True)
    except Exception:
        pass


async def run_orchestrator(poll_interval: float = 5.0) -> None:
    """Main orchestrator loop."""
    logger.info("Orchestrator started, polling every %.1fs", poll_interval)
    lease = _SingleActiveOrchestratorLease()
    waiting_for_lock = False
    recovered = False
    try:
        while True:
            try:
                has_lock = await lease.try_acquire()
            except Exception:
                logger.exception("Orchestrator lock acquisition error")
                await asyncio.sleep(poll_interval)
                continue

            if not has_lock:
                if not waiting_for_lock:
                    logger.warning("Another RoughCut orchestrator is active; waiting for single-active lock")
                    waiting_for_lock = True
                await asyncio.sleep(poll_interval)
                continue

            if waiting_for_lock:
                logger.info("Single-active orchestrator lock acquired")
                waiting_for_lock = False
            if not recovered:
                await _recover_incomplete_jobs()
                recovered = True
            try:
                await tick()
            except Exception:
                logger.exception("Orchestrator tick error")
            await asyncio.sleep(poll_interval)
    finally:
        await lease.release()


def create_job_steps(job_id: uuid.UUID) -> list[JobStep]:
    """Create all pipeline steps for a new job."""
    return [
        JobStep(job_id=job_id, step_name=step_name, status="pending")
        for step_name in PIPELINE_STEPS
    ]
