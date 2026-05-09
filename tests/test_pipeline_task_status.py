from __future__ import annotations

import uuid
import asyncio
import time
import warnings
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import roughcut.db.session as db_session
from roughcut.db.models import Job, JobStep
from roughcut.db.session import Base
from roughcut.pipeline import steps
from roughcut.pipeline import tasks


@pytest.fixture()
def task_status_session_factory(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async def _setup() -> None:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

        asyncio.run(_setup())
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(db_session, "get_session_factory", lambda: session_factory)
        yield session_factory
    finally:
        asyncio.run(engine.dispose())


def test_update_step_status_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._update_step_status(missing_job_id, "transcribe", "running", task_id="stale-task")


def test_update_step_retry_waiting_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._update_step_retry_waiting(
        missing_job_id,
        "transcribe",
        "GPU busy",
        countdown=30,
        task_id="stale-task",
    )


def test_finalize_ignored_dispatched_step_ignores_missing_job(task_status_session_factory):
    missing_job_id = str(uuid.uuid4())

    assert not tasks._finalize_ignored_dispatched_step(missing_job_id, "transcribe", task_id="stale-task")


def test_task_status_helpers_ignore_invalid_job_ids(task_status_session_factory):
    assert not tasks._update_step_status("not-a-uuid", "transcribe", "running", task_id="stale-task")
    assert not tasks._update_step_retry_waiting(
        "not-a-uuid",
        "transcribe",
        "GPU busy",
        countdown=30,
        task_id="stale-task",
    )
    assert not tasks._finalize_ignored_dispatched_step("not-a-uuid", "transcribe", task_id="stale-task")


def test_done_transition_is_idempotent_for_same_task_id() -> None:
    assert tasks._can_transition_step(
        job_status="processing",
        step_status="done",
        target_status="done",
        current_task_id="",
        last_task_id="task-1",
        task_id="task-1",
    )


def test_blocking_step_heartbeat_updates_running_step(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))

        assert steps._write_blocking_step_heartbeat(
            step_id=step_id,
            detail="still splitting subtitles",
            progress=0.55,
        )

        refreshed = asyncio.run(_load_step())
        assert refreshed.metadata_["detail"] == "still splitting subtitles"
        assert refreshed.metadata_["progress"] == 0.55
        assert refreshed.metadata_["updated_at"]
    finally:
        asyncio.run(engine.dispose())


def test_blocking_step_heartbeat_context_writes_immediately(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat-context.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))
        step = asyncio.run(_load_step())

        with steps._maintain_blocking_step_heartbeat(
            step,
            detail="saving subtitles",
            progress=0.82,
        ):
            deadline = time.monotonic() + 2.0
            refreshed = asyncio.run(_load_step())
            while refreshed.metadata_["detail"] != "saving subtitles" and time.monotonic() < deadline:
                time.sleep(0.05)
                refreshed = asyncio.run(_load_step())

            assert refreshed.metadata_["detail"] == "saving subtitles"
            assert refreshed.metadata_["progress"] == 0.82
            assert refreshed.metadata_["updated_at"]
    finally:
        asyncio.run(engine.dispose())


def test_blocking_step_heartbeat_writes_from_running_event_loop(tmp_path, monkeypatch):
    db_path = (tmp_path / "heartbeat-running-loop.db").as_posix()
    database_url = f"sqlite+aiosqlite:///{db_path}"
    engine = create_async_engine(database_url)
    job_id = uuid.uuid4()
    step_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            session.add(
                Job(
                    id=job_id,
                    source_path="source.mp4",
                    source_name="source.mp4",
                    status="processing",
                )
            )
            session.add(
                JobStep(
                    id=step_id,
                    job_id=job_id,
                    step_name="subtitle_postprocess",
                    status="running",
                    metadata_={"detail": "old", "progress": 0.1},
                )
            )
            await session.commit()

    async def _load_step() -> JobStep:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            step = await session.get(JobStep, step_id)
            assert step is not None
            return step

    async def _write_inside_running_loop() -> bool:
        return steps._write_blocking_step_heartbeat(
            step_id=step_id,
            detail="running loop heartbeat",
            progress=0.66,
        )

    try:
        asyncio.run(_setup())
        monkeypatch.setattr(steps, "get_settings", lambda: SimpleNamespace(database_url=database_url))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert asyncio.run(_write_inside_running_loop())

        assert not any("was never awaited" in str(item.message) for item in caught)
        refreshed = asyncio.run(_load_step())
        assert refreshed.metadata_["detail"] == "running loop heartbeat"
        assert refreshed.metadata_["progress"] == 0.66
    finally:
        asyncio.run(engine.dispose())
