from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from roughcut.pipeline.celery_app import celery_app
from roughcut.pipeline.steps import run_step_sync

logger = logging.getLogger(__name__)


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
                current_task_id = (step.metadata_ or {}).get("task_id")
                if task_id and current_task_id and current_task_id != task_id:
                    return False
                step.status = status
                now = datetime.now(timezone.utc)
                if status == "running":
                    step.started_at = now
                elif status in ("done", "failed", "cancelled"):
                    step.finished_at = now
                elapsed_seconds = None
                if step.started_at:
                    elapsed_seconds = max(0.0, ((step.finished_at or now) - step.started_at).total_seconds())
                step.metadata_ = {
                    **(step.metadata_ or {}),
                    "updated_at": now.isoformat(),
                    **({"elapsed_seconds": round(elapsed_seconds, 3)} if elapsed_seconds is not None else {}),
                }
                if error:
                    step.error_message = error
                elif status in ("running", "done"):
                    step.error_message = None
                await session.commit()
                return True
            return False

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


def _run_task_step(task, job_id: str, step_name: str, *, retry_countdown: int):
    task_id = task.request.id
    if not _update_step_status(job_id, step_name, "running", task_id=task_id):
        return {"ignored": True}

    started = time.perf_counter()
    logger.info("step started step=%s job=%s task_id=%s", step_name, job_id, task_id)
    try:
        result = run_step_sync(step_name, job_id)
        elapsed = time.perf_counter() - started
        _update_step_status(job_id, step_name, "done", task_id=task_id)
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
        elapsed = time.perf_counter() - started
        _update_step_status(job_id, step_name, "failed", str(exc), task_id=task_id)
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
