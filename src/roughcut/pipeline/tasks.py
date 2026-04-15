from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone

from roughcut.config import apply_in_memory_runtime_overrides, get_settings, normalize_transcription_provider_name
from roughcut.pipeline.celery_app import celery_app
from roughcut.pipeline.steps import run_step_sync
from roughcut.telegram.executors import execute_agent_preset

logger = logging.getLogger(__name__)
_GPU_INTENSIVE_STEPS = {"transcribe", "avatar_commentary", "render"}
_GPU_ERROR_TOKENS = ("cuda", "cudnn", "cublas", "gpu", "nvidia", "hip")
_GPU_PRESSURE_TOKENS = (
    "out of memory",
    "not enough memory",
    "memory access",
    "device busy",
    "resource busy",
    "busy",
    "unavailable",
    "insufficient",
    "alloc",
)
_ACTIVE_JOB_STATUSES = {"pending", "processing"}
_TERMINAL_JOB_STATUSES = {"done", "failed", "cancelled", "needs_review"}


def _reset_db_session_state() -> None:
    import roughcut.db.session as _sess

    engine = getattr(_sess, "_engine", None)
    if engine is not None:
        try:
            asyncio.run(engine.dispose())
        except Exception:
            pass
    _sess._engine = None
    _sess._session_factory = None


def _coerce_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _can_transition_step(
    *,
    job_status: str,
    step_status: str,
    target_status: str,
    current_task_id: str | None,
    last_task_id: str | None,
    task_id: str | None,
) -> bool:
    normalized_job_status = str(job_status or "").strip().lower()
    normalized_step_status = str(step_status or "").strip().lower()
    current_task = str(current_task_id or "").strip()
    last_task = str(last_task_id or "").strip()
    incoming_task = str(task_id or "").strip()

    if target_status == "running":
        if normalized_job_status not in _ACTIVE_JOB_STATUSES:
            return False
        if current_task and incoming_task and current_task != incoming_task:
            return False
        if normalized_step_status == "pending":
            if incoming_task and last_task and incoming_task == last_task:
                return False
            return True
        if normalized_step_status == "running" and current_task and incoming_task and current_task == incoming_task:
            return True
        if normalized_step_status == "failed" and incoming_task and last_task and incoming_task == last_task:
            return True
        return False

    if normalized_job_status in _TERMINAL_JOB_STATUSES and target_status != "cancelled":
        return False
    if normalized_step_status != "running":
        return False
    if incoming_task and current_task and current_task != incoming_task:
        return False
    return True


def _finalize_step_metadata(
    metadata: dict,
    *,
    status: str,
    current_task_id: str | None,
    task_id: str | None,
) -> dict:
    updated = dict(metadata)
    if status == "running":
        if task_id:
            updated["task_id"] = task_id
        return updated

    last_task_id = str(task_id or current_task_id or "").strip()
    updated.pop("task_id", None)
    updated.pop("retry_wait_until", None)
    updated.pop("retry_after_sec", None)
    if last_task_id:
        updated["last_task_id"] = last_task_id
    return updated


def _update_step_status(
    job_id: str,
    step_name: str,
    status: str,
    error: str | None = None,
    *,
    task_id: str | None = None,
) -> bool:
    """Update job step status in DB (sync)."""
    import asyncio
    from sqlalchemy import select
    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory

    _reset_db_session_state()

    async def _update():
        from roughcut.db.models import Job
        import uuid
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            if step:
                metadata = dict(step.metadata_ or {})
                current_task_id = metadata.get("task_id")
                last_task_id = metadata.get("last_task_id")
                if not _can_transition_step(
                    job_status=str(job.status or ""),
                    step_status=str(step.status or ""),
                    target_status=status,
                    current_task_id=str(current_task_id or ""),
                    last_task_id=str(last_task_id or ""),
                    task_id=str(task_id or ""),
                ):
                    return False
                step.status = status
                now = datetime.now(timezone.utc)
                if status == "running":
                    step.started_at = now
                elif status in ("done", "failed", "cancelled"):
                    step.finished_at = now
                elapsed_seconds = None
                if step.started_at:
                    start_time = _coerce_utc(step.started_at)
                    end_time = _coerce_utc(step.finished_at) if step.finished_at is not None else now
                    elapsed_seconds = max(0.0, (end_time - start_time).total_seconds())
                step.metadata_ = _finalize_step_metadata(
                    {
                        **(step.metadata_ or {}),
                        "updated_at": now.isoformat(),
                        **({"worker_started_at": now.isoformat()} if status == "running" else {}),
                        **({"elapsed_seconds": round(elapsed_seconds, 3)} if elapsed_seconds is not None else {}),
                    },
                    status=status,
                    current_task_id=str(current_task_id or ""),
                    task_id=str(task_id or ""),
                )
                if error:
                    step.error_message = error
                elif status in ("running", "done"):
                    step.error_message = None
                await session.commit()
                return True
            return False

    return bool(asyncio.run(_update()))


def _update_step_retry_waiting(
    job_id: str,
    step_name: str,
    detail: str,
    *,
    countdown: int,
    task_id: str | None = None,
) -> bool:
    import asyncio
    import uuid
    from sqlalchemy import select
    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory

    _reset_db_session_state()

    async def _update():
        from roughcut.db.models import Job

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            if step is None:
                return False
            metadata = dict(step.metadata_ or {})
            current_task_id = metadata.get("task_id")
            last_task_id = metadata.get("last_task_id")
            if not _can_transition_step(
                job_status=str(job.status or ""),
                step_status=str(step.status or ""),
                target_status="pending",
                current_task_id=str(current_task_id or ""),
                last_task_id=str(last_task_id or ""),
                task_id=str(task_id or ""),
            ):
                return False
            now = datetime.now(timezone.utc)
            step.status = "pending"
            step.started_at = None
            step.finished_at = None
            step.error_message = None
            step.metadata_ = {
                **(step.metadata_ or {}),
                "detail": detail,
                "retry_after_sec": countdown,
                "retry_wait_until": (now.timestamp() + countdown),
                "updated_at": now.isoformat(),
            }
            await session.commit()
            return True

    return bool(asyncio.run(_update()))


def _finalize_ignored_dispatched_step(
    job_id: str,
    step_name: str,
    *,
    task_id: str | None = None,
) -> bool:
    import asyncio
    import uuid
    from sqlalchemy import select
    from roughcut.db.models import JobStep
    from roughcut.db.session import get_session_factory

    _reset_db_session_state()

    async def _update():
        from roughcut.db.models import Job

        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            result = await session.execute(
                select(JobStep).where(JobStep.job_id == job.id, JobStep.step_name == step_name)
            )
            step = result.scalar_one_or_none()
            if step is None:
                return False
            metadata = dict(step.metadata_ or {})
            current_task_id = str(metadata.get("task_id") or "").strip()
            incoming_task_id = str(task_id or "").strip()
            if current_task_id and incoming_task_id and current_task_id != incoming_task_id:
                return False

            normalized_job_status = str(job.status or "").strip().lower()
            if normalized_job_status in {"failed", "cancelled"}:
                target_status = "cancelled"
                detail = "任务到达时作业已终止，当前步骤已停止。"
            elif normalized_job_status in {"done", "needs_review"}:
                progress = float(metadata.get("progress") or 0.0)
                target_status = "done" if progress >= 1.0 else "skipped"
                detail = (
                    "任务到达时作业已完成，当前步骤无需继续执行。"
                    if target_status == "skipped"
                    else str(metadata.get("detail") or "").strip() or "步骤已完成。"
                )
            else:
                return False

            now = datetime.now(timezone.utc)
            step.status = target_status
            step.finished_at = now
            step.error_message = None
            step.metadata_ = _finalize_step_metadata(
                {
                    **metadata,
                    "detail": detail,
                    "updated_at": now.isoformat(),
                },
                status=target_status,
                current_task_id=current_task_id,
                task_id=incoming_task_id,
            )
            await session.commit()
            return True

    return bool(asyncio.run(_update()))


def _summarize_result(result) -> str:
    if isinstance(result, dict):
        parts: list[str] = []
        for key, value in sorted(result.items()):
            if isinstance(value, (str, int, float, bool)) or value is None:
                parts.append(f"{key}={value}")
            elif isinstance(value, list):
                parts.append(f"{key}[{len(value)}]")
            elif isinstance(value, dict):
                parts.append(f"{key}{{{len(value)}}}")
            else:
                parts.append(f"{key}={type(value).__name__}")
        return ", ".join(parts[:12])
    return str(result)


def _is_gpu_pressure_error(exc: Exception) -> bool:
    message = str(exc or "").lower()
    if not message:
        return False
    if "device or resource busy" in message:
        return True
    has_gpu_signal = any(token in message for token in _GPU_ERROR_TOKENS)
    has_pressure_signal = any(token in message for token in _GPU_PRESSURE_TOKENS)
    return has_gpu_signal and has_pressure_signal


def _is_gpu_sensitive_step(step_name: str) -> bool:
    return _step_requires_local_gpu(step_name)


def _step_requires_local_gpu(step_name: str) -> bool:
    normalized = str(step_name or "").strip().lower()
    if normalized == "render":
        return True
    if normalized == "transcribe":
        settings = get_settings()
        provider = normalize_transcription_provider_name(getattr(settings, "transcription_provider", ""))
        if provider != "faster_whisper":
            return False
        return _local_gpu_available_or_expected()
    return False


def _local_gpu_available_or_expected() -> bool:
    try:
        import ctranslate2

        if int(ctranslate2.get_cuda_device_count() or 0) > 0:
            return True
    except Exception:
        pass

    docker_gpus = str(os.getenv("ROUGHCUT_DOCKER_GPUS", "") or "").strip().lower()
    if docker_gpus and docker_gpus not in {"none", "void", "off", "false", "0", "no"}:
        return True

    visible_devices = str(os.getenv("NVIDIA_VISIBLE_DEVICES", "") or "").strip().lower()
    if visible_devices and visible_devices not in {"none", "void", "off", "false", "0", "no"}:
        return True

    return False


def _compute_retry_countdown(task) -> int:
    settings = get_settings()
    base_delay = max(15, int(getattr(settings, "gpu_retry_base_delay_sec", 90)))
    max_delay = max(base_delay, int(getattr(settings, "gpu_retry_max_delay_sec", 900)))
    retries = int(getattr(task.request, "retries", 0) or 0)
    return min(max_delay, base_delay * (2 ** retries))


def _memory_pressure_guard_enabled(step_name: str) -> bool:
    settings = get_settings()
    transcription_provider = normalize_transcription_provider_name(getattr(settings, "transcription_provider", ""))
    if step_name == "transcribe" and transcription_provider == "qwen3_asr":
        return False
    if step_name == "render":
        # Render may rely on an external managed GPU service like HeyGem.
        # Those containers keep large VRAM reservations even while idle, so
        # a memory-based local guard would block render forever.
        return False
    return True


def _probe_local_gpu_pressure(step_name: str) -> str | None:
    settings = get_settings()
    if not bool(getattr(settings, "gpu_retry_enabled", True)):
        return None
    if not _is_gpu_sensitive_step(step_name):
        return None
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    try:
        result = subprocess.run(
            [
                nvidia_smi,
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            check=False,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    util_threshold = max(50, int(getattr(settings, "gpu_busy_utilization_threshold", 92)))
    memory_threshold = max(0.5, float(getattr(settings, "gpu_busy_memory_threshold", 0.92)))
    enforce_memory_guard = _memory_pressure_guard_enabled(step_name)
    for line in result.stdout.splitlines():
        values = [part.strip() for part in line.split(",")]
        if len(values) != 4:
            continue
        index_text, util_text, used_text, total_text = values
        try:
            util = int(float(util_text))
            used = float(used_text)
            total = max(1.0, float(total_text))
        except ValueError:
            continue
        memory_ratio = used / total
        if util >= util_threshold or (enforce_memory_guard and memory_ratio >= memory_threshold):
            return (
                f"检测到 GPU{index_text} 繁忙(util={util}%, mem={memory_ratio:.0%})，"
                "本步骤先等待后重试。"
            )
    return None


def _apply_job_runtime_snapshot(job_id: str) -> None:
    import asyncio
    import uuid

    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory

    _reset_db_session_state()

    async def _load_job_updates() -> dict:
        factory = get_session_factory()
        async with factory() as session:
            job = await session.get(Job, uuid.UUID(job_id))
            if job is None:
                return {}
            updates = dict(job.config_profile_snapshot_json or {})
            updates["default_job_workflow_mode"] = str(job.workflow_mode or updates.get("default_job_workflow_mode") or "")
            updates["default_job_enhancement_modes"] = list(job.enhancement_modes or updates.get("default_job_enhancement_modes") or [])
            return updates

    apply_in_memory_runtime_overrides(asyncio.run(_load_job_updates()))


def _run_task_step(task, job_id: str, step_name: str, *, retry_countdown: int):
    task_id = task.request.id
    if not _update_step_status(job_id, step_name, "running", task_id=task_id):
        normalized = _finalize_ignored_dispatched_step(job_id, step_name, task_id=task_id)
        logger.info(
            "step ignored before start step=%s job=%s task_id=%s normalized=%s",
            step_name,
            job_id,
            task_id,
            normalized,
        )
        return {"ignored": True}

    _apply_job_runtime_snapshot(job_id)

    started = time.perf_counter()
    logger.info("step started step=%s job=%s task_id=%s", step_name, job_id, task_id)
    local_gpu_wait_reason = _probe_local_gpu_pressure(step_name)
    if local_gpu_wait_reason:
        countdown = _compute_retry_countdown(task)
        if not _update_step_retry_waiting(job_id, step_name, local_gpu_wait_reason, countdown=countdown, task_id=task_id):
            logger.info("step gpu wait ignored step=%s job=%s task_id=%s", step_name, job_id, task_id)
            return {"ignored": True}
        logger.warning(
            "step waiting for gpu step=%s job=%s task_id=%s retry_in=%ss reason=%s",
            step_name,
            job_id,
            task_id,
            countdown,
            local_gpu_wait_reason,
        )
        raise task.retry(exc=RuntimeError(local_gpu_wait_reason), countdown=countdown)
    try:
        result = run_step_sync(step_name, job_id)
        elapsed = time.perf_counter() - started
        if not _update_step_status(job_id, step_name, "done", task_id=task_id):
            logger.warning(
                "step completion ignored after execution step=%s job=%s task_id=%s elapsed=%.2fs",
                step_name,
                job_id,
                task_id,
                elapsed,
            )
            return {"ignored": True, "late_writeback": True}
        logger.info(
            "step finished step=%s job=%s task_id=%s elapsed=%.2fs result=%s",
            step_name,
            job_id,
            task_id,
            elapsed,
            _summarize_result(result),
        )
        return result
    except Exception as exc:
        if _is_gpu_pressure_error(exc):
            countdown = _compute_retry_countdown(task)
            wait_detail = f"检测到 GPU/资源繁忙，{countdown}s 后自动重试：{exc}"
            if not _update_step_retry_waiting(job_id, step_name, wait_detail, countdown=countdown, task_id=task_id):
                logger.warning(
                    "step gpu retry ignored step=%s job=%s task_id=%s error=%s",
                    step_name,
                    job_id,
                    task_id,
                    exc,
                )
                return {"ignored": True, "late_writeback": True}
            logger.warning(
                "step retrying for gpu pressure step=%s job=%s task_id=%s retry_in=%ss error=%s",
                step_name,
                job_id,
                task_id,
                countdown,
                exc,
            )
            raise task.retry(exc=exc, countdown=countdown)
        elapsed = time.perf_counter() - started
        if not _update_step_status(job_id, step_name, "failed", str(exc), task_id=task_id):
            logger.warning(
                "step failure ignored after execution step=%s job=%s task_id=%s elapsed=%.2fs error=%s",
                step_name,
                job_id,
                task_id,
                elapsed,
                exc,
            )
            return {"ignored": True, "late_writeback": True}
        logger.exception(
            "step failed step=%s job=%s task_id=%s elapsed=%.2fs error=%s",
            step_name,
            job_id,
            task_id,
            elapsed,
            exc,
        )
        raise task.retry(exc=exc, countdown=retry_countdown)


@celery_app.task(name="roughcut.pipeline.tasks.media_probe", bind=True, max_retries=3)
def media_probe(self, job_id: str):
    return _run_task_step(self, job_id, "probe", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.media_extract_audio", bind=True, max_retries=3)
def media_extract_audio(self, job_id: str):
    return _run_task_step(self, job_id, "extract_audio", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_transcribe", bind=True, max_retries=3)
def llm_transcribe(self, job_id: str):
    return _run_task_step(self, job_id, "transcribe", retry_countdown=30)


@celery_app.task(name="roughcut.pipeline.tasks.llm_subtitle_postprocess", bind=True, max_retries=3)
def llm_subtitle_postprocess(self, job_id: str):
    return _run_task_step(self, job_id, "subtitle_postprocess", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_subtitle_term_resolution", bind=True, max_retries=3)
def llm_subtitle_term_resolution(self, job_id: str):
    return _run_task_step(self, job_id, "subtitle_term_resolution", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_subtitle_consistency_review", bind=True, max_retries=3)
def llm_subtitle_consistency_review(self, job_id: str):
    return _run_task_step(self, job_id, "subtitle_consistency_review", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_subtitle_translation", bind=True, max_retries=3)
def llm_subtitle_translation(self, job_id: str):
    return _run_task_step(self, job_id, "subtitle_translation", retry_countdown=15)


@celery_app.task(name="roughcut.pipeline.tasks.llm_content_profile", bind=True, max_retries=3)
def llm_content_profile(self, job_id: str):
    return _run_task_step(self, job_id, "content_profile", retry_countdown=15)


@celery_app.task(name="roughcut.pipeline.tasks.llm_glossary_review", bind=True, max_retries=3)
def llm_glossary_review(self, job_id: str):
    return _run_task_step(self, job_id, "glossary_review", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_ai_director", bind=True, max_retries=2)
def llm_ai_director(self, job_id: str):
    return _run_task_step(self, job_id, "ai_director", retry_countdown=20)


@celery_app.task(name="roughcut.pipeline.tasks.llm_avatar_commentary", bind=True, max_retries=2)
def llm_avatar_commentary(self, job_id: str):
    return _run_task_step(self, job_id, "avatar_commentary", retry_countdown=20)


@celery_app.task(name="roughcut.pipeline.tasks.media_edit_plan", bind=True, max_retries=3)
def media_edit_plan(self, job_id: str):
    return _run_task_step(self, job_id, "edit_plan", retry_countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.media_render", bind=True, max_retries=2)
def media_render(self, job_id: str):
    return _run_task_step(self, job_id, "render", retry_countdown=30)


@celery_app.task(name="roughcut.pipeline.tasks.llm_platform_package", bind=True, max_retries=2)
def llm_platform_package(self, job_id: str):
    return _run_task_step(self, job_id, "platform_package", retry_countdown=20)


@celery_app.task(name="roughcut.pipeline.tasks.agent_run_preset", bind=True, max_retries=0)
def agent_run_preset(
    self,
    *,
    task_id: str = "",
    chat_id: str = "",
    provider: str,
    preset: str,
    task_text: str,
    scope_path: str = "",
    job_id: str = "",
):
    logger.info(
        "agent task started task_id=%s provider=%s preset=%s scope=%s job=%s",
        self.request.id,
        provider,
        preset,
        scope_path,
        job_id,
    )
    started = time.perf_counter()
    try:
        result = execute_agent_preset(
            task_id=task_id or self.request.id,
            chat_id=chat_id,
            provider=provider,
            preset=preset,
            task_text=task_text,
            scope_path=scope_path,
            job_id=job_id,
        )
        elapsed = time.perf_counter() - started
        logger.info(
            "agent task finished task_id=%s provider=%s preset=%s elapsed=%.2fs",
            self.request.id,
            provider,
            preset,
            elapsed,
        )
        return result
    except Exception as exc:
        elapsed = time.perf_counter() - started
        logger.exception(
            "agent task failed task_id=%s provider=%s preset=%s elapsed=%.2fs error=%s",
            self.request.id,
            provider,
            preset,
            elapsed,
            exc,
        )
        raise
