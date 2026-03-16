from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest


@pytest.mark.asyncio
async def test_tick_respects_retry_wait_until_before_redispatch(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[str] = []

    async def fake_dispatch(step, session):
        dispatched.append(step.step_name)

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)

    job_id = uuid.uuid4()
    wait_until = datetime.now(timezone.utc) + timedelta(minutes=3)
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/demo.mp4",
                source_name="demo.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(
            JobStep(
                job_id=job_id,
                step_name="transcribe",
                status="pending",
                metadata_={"retry_wait_until": wait_until.timestamp()},
            )
        )
        await session.commit()

    await orchestrator_mod.tick()

    assert "transcribe" not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "资源等待中" in str((step.metadata_ or {}).get("detail") or "")


@pytest.mark.asyncio
async def test_tick_defers_gpu_sensitive_step_when_dispatch_gpu_guard_blocks(monkeypatch, db_engine):
    import roughcut.pipeline.orchestrator as orchestrator_mod
    import roughcut.watcher.folder_watcher as watcher_mod
    from roughcut.db.models import Job, JobStep
    from roughcut.db.session import get_session_factory

    async def no_watch_duty():
        return {"roots_total": 0, "scan_started": 0, "auto_merged_jobs": 0, "auto_enqueued_jobs": 0, "idle_slots": 0}

    async def no_op(*args, **kwargs):
        return None

    async def ready_true(*args, **kwargs):
        return True

    async def zero(*args, **kwargs):
        return 0

    dispatched: list[str] = []

    async def fake_dispatch(step, session):
        dispatched.append(step.step_name)

    monkeypatch.setattr(watcher_mod, "run_watch_root_auto_duty", no_watch_duty)
    monkeypatch.setattr(orchestrator_mod, "_ensure_job_steps", no_op)
    monkeypatch.setattr(orchestrator_mod, "_update_job_statuses", no_op)
    monkeypatch.setattr(orchestrator_mod, "_is_step_ready", ready_true)
    monkeypatch.setattr(orchestrator_mod, "_dispatch_step", fake_dispatch)
    monkeypatch.setattr(orchestrator_mod, "_count_running_gpu_steps", zero)
    monkeypatch.setattr(
        orchestrator_mod,
        "_gpu_dispatch_wait_reason",
        lambda step_name, *, running_gpu_steps: "检测到外部 GPU 占用，当前步骤延后派发。" if step_name == "transcribe" else None,
    )

    job_id = uuid.uuid4()
    factory = get_session_factory()
    async with factory() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/gpu.mp4",
                source_name="gpu.mp4",
                status="pending",
                language="zh-CN",
            )
        )
        session.add(JobStep(job_id=job_id, step_name="transcribe", status="pending"))
        await session.commit()

    await orchestrator_mod.tick()

    assert "transcribe" not in dispatched

    async with factory() as session:
        step = (
            await session.execute(
                orchestrator_mod.select(JobStep).where(JobStep.job_id == job_id, JobStep.step_name == "transcribe")
            )
        ).scalar_one()
        assert step.status == "pending"
        assert "外部 GPU 占用" in str((step.metadata_ or {}).get("detail") or "")
