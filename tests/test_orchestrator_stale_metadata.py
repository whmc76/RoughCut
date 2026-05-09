from __future__ import annotations

from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.db.models import Artifact, Job, JobStep
from roughcut.db.session import Base
from roughcut.pipeline import orchestrator
from roughcut.pipeline.orchestrator import (
    _CeleryTaskPresenceSnapshot,
    _extract_broker_message_task_id,
    _lost_task_recovery_detail,
    _step_last_heartbeat_at,
    _step_worker_started_at,
)


def test_stale_worker_started_at_before_dispatch_is_ignored() -> None:
    dispatched = datetime(2026, 4, 26, 1, 0, tzinfo=timezone.utc)
    step = JobStep(
        step_name="edit_plan",
        status="running",
        started_at=dispatched,
        metadata_={
            "dispatched_at": dispatched.isoformat(),
            "worker_started_at": (dispatched - timedelta(hours=1)).isoformat(),
            "updated_at": dispatched.isoformat(),
        },
    )

    assert _step_worker_started_at(step) is None
    assert _step_last_heartbeat_at(step) == dispatched


def test_worker_started_at_after_dispatch_is_runtime_heartbeat() -> None:
    dispatched = datetime(2026, 4, 26, 1, 0, tzinfo=timezone.utc)
    worker_started = dispatched + timedelta(seconds=10)
    step = JobStep(
        step_name="edit_plan",
        status="running",
        started_at=dispatched,
        metadata_={
            "dispatched_at": dispatched.isoformat(),
            "worker_started_at": worker_started.isoformat(),
            "updated_at": dispatched.isoformat(),
        },
    )

    assert _step_worker_started_at(step) == worker_started
    assert _step_last_heartbeat_at(step) == worker_started


def test_lost_task_recovery_detects_unacked_only_task() -> None:
    step = JobStep(
        step_name="content_profile",
        status="running",
        metadata_={"task_id": "task-1"},
    )
    snapshot = _CeleryTaskPresenceSnapshot(
        unacked_task_ids=frozenset({"task-1"}),
        worker_available=True,
        broker_available=True,
    )

    result = _lost_task_recovery_detail(step, snapshot=snapshot)

    assert result is not None
    assert result[0] == "unacked"


def test_lost_task_recovery_keeps_worker_active_task() -> None:
    step = JobStep(
        step_name="content_profile",
        status="running",
        metadata_={"task_id": "task-1"},
    )
    snapshot = _CeleryTaskPresenceSnapshot(
        worker_task_ids=frozenset({"task-1"}),
        worker_available=True,
        broker_available=True,
    )

    assert _lost_task_recovery_detail(step, snapshot=snapshot) is None


def test_extract_broker_message_task_id_from_unacked_payload() -> None:
    raw = (
        '[{"headers": {"id": "task-1"}, '
        '"properties": {"correlation_id": "task-1"}}, "", "llm_queue"]'
    )

    assert _extract_broker_message_task_id(raw) == "task-1"


@pytest.mark.asyncio
async def test_recover_stale_running_step_when_task_only_unacked(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        stale_at = datetime.now(timezone.utc) - timedelta(seconds=130)
        job_id = uuid.uuid4()
        task_id = "task-unacked-only"

        monkeypatch.setattr(orchestrator, "get_settings", lambda: SimpleNamespace(
            step_stale_recovery_enabled=True,
            step_lost_task_recovery_enabled=True,
            step_heartbeat_interval_sec=20,
            step_lost_task_grace_sec=120,
            step_dispatch_lost_task_grace_sec=300,
            step_stale_timeout_sec=900,
            step_dispatch_stale_timeout_sec=3600,
            render_step_stale_timeout_sec=5400,
        ))
        monkeypatch.setattr(orchestrator, "_collect_celery_task_presence_snapshot", lambda: _CeleryTaskPresenceSnapshot(
            unacked_task_ids=frozenset({task_id}),
            worker_count=1,
            worker_available=True,
            broker_available=True,
        ))

        async with session_factory() as session:
            job = Job(
                id=job_id,
                source_path="source.mp4",
                source_name="source.mp4",
                status="processing",
            )
            step = JobStep(
                job_id=job_id,
                step_name="content_profile",
                status="running",
                attempt=1,
                started_at=stale_at,
                metadata_={
                    "task_id": task_id,
                    "dispatched_at": stale_at.isoformat(),
                    "worker_started_at": stale_at.isoformat(),
                    "updated_at": stale_at.isoformat(),
                    "progress": 0.55,
                },
            )
            session.add_all([job, step])
            await session.commit()

            await orchestrator._recover_stale_running_steps(session)
            await session.commit()

            refreshed = await session.get(JobStep, step.id)
            assert refreshed is not None
            assert refreshed.status == "pending"
            assert refreshed.started_at is None
            assert refreshed.finished_at is None
            assert refreshed.error_message is None
            assert refreshed.metadata_["last_task_id"] == task_id
            assert refreshed.metadata_["recovery_presence"] == "unacked"
            assert "unacked" in refreshed.metadata_["detail"]

            artifact_count = (
                await session.execute(
                    select(Artifact).where(
                        Artifact.job_id == job_id,
                        Artifact.artifact_type == "stuck_step_diagnostic",
                    )
                )
            ).scalars().all()
            assert len(artifact_count) == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_recover_running_step_with_completed_progress_marks_done(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        stale_at = datetime.now(timezone.utc) - timedelta(seconds=180)
        job_id = uuid.uuid4()
        task_id = "task-completed-progress"

        monkeypatch.setattr(orchestrator, "get_settings", lambda: SimpleNamespace(
            step_stale_recovery_enabled=True,
            step_lost_task_recovery_enabled=True,
            step_heartbeat_interval_sec=20,
            step_lost_task_grace_sec=120,
            step_dispatch_lost_task_grace_sec=300,
            step_stale_timeout_sec=900,
            step_dispatch_stale_timeout_sec=3600,
            render_step_stale_timeout_sec=5400,
        ))

        async with session_factory() as session:
            job = Job(
                id=job_id,
                source_path="source.mp4",
                source_name="source.mp4",
                status="processing",
            )
            step = JobStep(
                job_id=job_id,
                step_name="subtitle_postprocess",
                status="running",
                attempt=1,
                started_at=stale_at,
                metadata_={
                    "task_id": task_id,
                    "dispatched_at": stale_at.isoformat(),
                    "worker_started_at": stale_at.isoformat(),
                    "updated_at": stale_at.isoformat(),
                    "progress": 1.0,
                    "detail": "字幕后处理完成",
                },
            )
            session.add_all([job, step])
            await session.commit()

            await orchestrator._recover_stale_running_steps(session)
            await session.commit()

            refreshed = await session.get(JobStep, step.id)
            assert refreshed is not None
            assert refreshed.status == "done"
            assert refreshed.finished_at is not None
            assert refreshed.error_message is None
            assert refreshed.metadata_["last_task_id"] == task_id
            assert "task_id" not in refreshed.metadata_
    finally:
        await engine.dispose()
