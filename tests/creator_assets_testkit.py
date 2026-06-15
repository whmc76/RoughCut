from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from roughcut.api.creator_assets import router
from roughcut.db.session import Base, get_session


@pytest.fixture()
def creator_assets_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[tuple[TestClient, async_sessionmaker[AsyncSession]], None, None]:
    db_path = (tmp_path / "creator-assets.db").as_posix()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup() -> None:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    monkeypatch.setenv("ROUGHCUT_OUTPUT_DIR", (tmp_path / "runtime-output").as_posix())

    async def _override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = _override_session

    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        asyncio.run(engine.dispose())
