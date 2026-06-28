from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from roughcut.api.jobs import router
from roughcut.db.models import Job
from roughcut.db.session import Base, get_session


def test_delete_job_with_family_removes_hidden_duplicate_queue_attempts(tmp_path):
    db_path = (tmp_path / "job-delete-family.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    target_id = uuid.uuid4()
    duplicate_id = uuid.uuid4()
    other_workflow_id = uuid.uuid4()

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            shared = {
                "source_path": "E:/watch/MAXACE 美杜莎4 顶配次顶配开箱.mp4",
                "source_name": "MAXACE 美杜莎4 顶配次顶配开箱.mp4",
                "file_hash": "maxace-medusa4-hash",
                "status": "cancelled",
                "workflow_template": "edc_tactical",
                "output_dir": "E:/output",
                "job_flow_mode": "auto",
                "workflow_mode": "standard_edit",
                "enhancement_modes": [],
                "platform_targets_json": [],
                "language": "zh-CN",
            }
            session.add(Job(id=target_id, **shared))
            session.add(Job(id=duplicate_id, **shared))
            session.add(Job(id=other_workflow_id, **{**shared, "workflow_template": "intelligent_publish"}))
            await session.commit()

    asyncio.run(_setup())

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _override_session

    try:
        with TestClient(app) as client:
            response = client.delete(f"/jobs/{target_id}?include_family=true")

        assert response.status_code == 204

        async def _remaining_ids() -> set[uuid.UUID]:
            async with session_factory() as session:
                result = await session.execute(select(Job.id))
                return set(result.scalars())

        assert asyncio.run(_remaining_ids()) == {other_workflow_id}
    finally:
        asyncio.run(engine.dispose())
