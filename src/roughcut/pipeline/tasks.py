from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from roughcut.pipeline.celery_app import celery_app
from roughcut.pipeline.steps import run_step_sync


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


def _update_step_status(job_id: str, step_name: str, status: str, error: str | None = None):
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
                step.status = status
                if status == "running":
                    step.started_at = datetime.now(timezone.utc)
                elif status in ("done", "failed"):
                    step.finished_at = datetime.now(timezone.utc)
                if error:
                    step.error_message = error
                    step.attempt += 1
                await session.commit()

    asyncio.run(_update())


@celery_app.task(name="roughcut.pipeline.tasks.media_probe", bind=True, max_retries=3)
def media_probe(self, job_id: str):
    _update_step_status(job_id, "probe", "running")
    try:
        result = run_step_sync("probe", job_id)
        _update_step_status(job_id, "probe", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "probe", "failed", str(exc))
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.media_extract_audio", bind=True, max_retries=3)
def media_extract_audio(self, job_id: str):
    _update_step_status(job_id, "extract_audio", "running")
    try:
        result = run_step_sync("extract_audio", job_id)
        _update_step_status(job_id, "extract_audio", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "extract_audio", "failed", str(exc))
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_transcribe", bind=True, max_retries=3)
def llm_transcribe(self, job_id: str):
    _update_step_status(job_id, "transcribe", "running")
    try:
        result = run_step_sync("transcribe", job_id)
        _update_step_status(job_id, "transcribe", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "transcribe", "failed", str(exc))
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="roughcut.pipeline.tasks.llm_subtitle_postprocess", bind=True, max_retries=3)
def llm_subtitle_postprocess(self, job_id: str):
    _update_step_status(job_id, "subtitle_postprocess", "running")
    try:
        result = run_step_sync("subtitle_postprocess", job_id)
        _update_step_status(job_id, "subtitle_postprocess", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "subtitle_postprocess", "failed", str(exc))
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.llm_content_profile", bind=True, max_retries=3)
def llm_content_profile(self, job_id: str):
    _update_step_status(job_id, "content_profile", "running")
    try:
        result = run_step_sync("content_profile", job_id)
        _update_step_status(job_id, "content_profile", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "content_profile", "failed", str(exc))
        raise self.retry(exc=exc, countdown=15)


@celery_app.task(name="roughcut.pipeline.tasks.llm_glossary_review", bind=True, max_retries=3)
def llm_glossary_review(self, job_id: str):
    _update_step_status(job_id, "glossary_review", "running")
    try:
        result = run_step_sync("glossary_review", job_id)
        _update_step_status(job_id, "glossary_review", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "glossary_review", "failed", str(exc))
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.media_edit_plan", bind=True, max_retries=3)
def media_edit_plan(self, job_id: str):
    _update_step_status(job_id, "edit_plan", "running")
    try:
        result = run_step_sync("edit_plan", job_id)
        _update_step_status(job_id, "edit_plan", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "edit_plan", "failed", str(exc))
        raise self.retry(exc=exc, countdown=10)


@celery_app.task(name="roughcut.pipeline.tasks.media_render", bind=True, max_retries=2)
def media_render(self, job_id: str):
    _update_step_status(job_id, "render", "running")
    try:
        result = run_step_sync("render", job_id)
        _update_step_status(job_id, "render", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "render", "failed", str(exc))
        raise self.retry(exc=exc, countdown=30)


@celery_app.task(name="roughcut.pipeline.tasks.llm_platform_package", bind=True, max_retries=2)
def llm_platform_package(self, job_id: str):
    _update_step_status(job_id, "platform_package", "running")
    try:
        result = run_step_sync("platform_package", job_id)
        _update_step_status(job_id, "platform_package", "done")
        return result
    except Exception as exc:
        _update_step_status(job_id, "platform_package", "failed", str(exc))
        raise self.retry(exc=exc, countdown=20)
