from __future__ import annotations

import asyncio
import functools
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_run_task_step_ignores_stale_message_for_cancelled_job(db_engine, monkeypatch):
    import roughcut.pipeline.tasks as tasks_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/cancelled.mp4",
                source_name="cancelled.mp4",
                status="cancelled",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="render",
                status="cancelled",
                started_at=now,
                finished_at=now,
                metadata_={"task_id": "stale-task", "updated_at": now.isoformat()},
            )
        )
        await session.commit()

    called: list[str] = []

    def _unexpected_run(*args, **kwargs):
        called.append("run")
        raise AssertionError("stale cancelled step should not execute")

    monkeypatch.setattr(tasks_mod, "run_step_sync", _unexpected_run)

    fake_task = SimpleNamespace(request=SimpleNamespace(id="stale-task", retries=0))
    result = await asyncio.to_thread(
        functools.partial(tasks_mod._run_task_step, fake_task, str(job_id), "render", retry_countdown=30)
    )

    assert result == {"ignored": True}
    assert called == []

    async with factory() as session:
        step = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "render")
            )
        ).scalar_one()
        assert step.status == "cancelled"


@pytest.mark.asyncio
async def test_run_task_step_ignores_late_writeback_after_job_is_cancelled(db_engine, monkeypatch):
    import roughcut.pipeline.tasks as tasks_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/late-cancel.mp4",
                source_name="late-cancel.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="render",
                status="pending",
                metadata_={"updated_at": now.isoformat()},
            )
        )
        await session.commit()

    def _simulate_cancel_during_execution(*args, **kwargs):
        del args, kwargs

        async def _cancel_now():
            async with factory() as session:
                job = await session.get(Job, job_id)
                step = (
                    await session.execute(
                        select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "render")
                    )
                ).scalar_one()
                job.status = "cancelled"
                step.status = "cancelled"
                step.finished_at = datetime.now(timezone.utc)
                step.metadata_ = {
                    **(step.metadata_ or {}),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                await session.commit()

        asyncio.run(_cancel_now())
        return {"ok": True}

    monkeypatch.setattr(tasks_mod, "run_step_sync", _simulate_cancel_during_execution)

    fake_task = SimpleNamespace(request=SimpleNamespace(id="active-task", retries=0))
    result = await asyncio.to_thread(
        functools.partial(tasks_mod._run_task_step, fake_task, str(job_id), "render", retry_countdown=30)
    )

    assert result == {"ignored": True, "late_writeback": True}

    async with factory() as session:
        step = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "render")
            )
        ).scalar_one()
        assert step.status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_job_clears_stale_task_ids_from_step_metadata(client):
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    job_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/cancel-api.mp4",
                source_name="cancel-api.mp4",
                status="processing",
                language="zh-CN",
            )
        )
        session.add_all(
            [
                JobStep(
                    job_id=job_id,
                    step_name="render",
                    status="running",
                    started_at=now,
                    metadata_={
                        "task_id": "running-task",
                        "queue": "media_queue",
                        "retry_wait_until": now.timestamp() + 30,
                    },
                ),
                JobStep(
                    job_id=job_id,
                    step_name="platform_package",
                    status="pending",
                    metadata_={"task_id": "queued-task", "queue": "llm_queue"},
                ),
            ]
        )
        await session.commit()

    response = await client.post(f"/api/v1/jobs/{job_id}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"

    async with get_session_factory()() as session:
        steps = (
            await session.execute(
                select(JobStep).where(JobStep.job_id == job_id)
            )
        ).scalars().all()
        step_map = {step.step_name: step for step in steps}

        render_step = step_map["render"]
        assert render_step.status == "cancelled"
        assert "task_id" not in (render_step.metadata_ or {})
        assert render_step.metadata_["last_task_id"] == "running-task"
        assert render_step.metadata_["detail"] == "任务已取消，后续流程停止。"

        package_step = step_map["platform_package"]
        assert package_step.status == "skipped"
        assert "task_id" not in (package_step.metadata_ or {})
        assert package_step.metadata_["last_task_id"] == "queued-task"
