from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.db.models import Job, JobStep
from roughcut.db.session import Base
from roughcut.pipeline import steps


@pytest.mark.asyncio
async def test_warm_manual_editor_preview_assets_times_out_and_degrades(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"video")
    job_id = uuid.uuid4()

    @asynccontextmanager
    async def fake_heartbeat(*args, **kwargs):
        yield

    async def fake_wait_for(awaitable, timeout):
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise TimeoutError

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        monkeypatch.setattr(
            steps,
            "get_settings",
            lambda: SimpleNamespace(manual_editor_preview_runtime_timeout_sec=45),
        )
        monkeypatch.setattr(steps, "_maintain_step_heartbeat", fake_heartbeat)
        monkeypatch.setattr(steps.asyncio, "wait_for", fake_wait_for)

        async with session_factory() as session:
            job = Job(
                id=job_id,
                source_path=source_path.as_posix(),
                source_name=source_path.name,
                status="processing",
                job_flow_mode="smart_assist",
            )
            step = JobStep(
                job_id=job_id,
                step_name="edit_plan",
                status="running",
                metadata_={},
            )
            session.add_all([job, step])
            await session.commit()

            payload = await steps._warm_manual_editor_preview_assets_for_job(
                session,
                job=job,
                step=step,
                duration_sec=42.0,
                content_profile={},
            )

            assert payload is None

            refreshed = (await session.execute(select(JobStep).where(JobStep.id == step.id))).scalar_one()
            metadata = dict(refreshed.metadata_ or {})
            assert metadata.get("progress") == 0.96
            assert metadata.get("manual_editor_preview_assets", {}).get("stage") == "timeout"
            assert "runtime_budget_sec" not in metadata
            assert "runtime_budget_started_at" not in metadata
            assert "预生成超时" in str(metadata.get("detail") or "")
    finally:
        await engine.dispose()
