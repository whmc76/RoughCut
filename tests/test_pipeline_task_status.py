from __future__ import annotations

import uuid
import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import roughcut.db.session as db_session
from roughcut.db.session import Base
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
