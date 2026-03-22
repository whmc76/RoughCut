from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use a per-process SQLite file for tests to avoid collisions between parallel pytest processes.
TEST_DB_FILE = Path(tempfile.gettempdir()) / f"roughcut-test-{os.getpid()}.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE.as_posix()}"

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")


@pytest.fixture(autouse=True)
def isolate_runtime_override_file(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod
    import roughcut.review.content_profile_review_stats as review_stats_mod

    override_file = tmp_path / "roughcut_config.json"
    output_dir = tmp_path / "output"
    stats_file = tmp_path / "content_profile_review_stats.json"

    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("TELEGRAM_AGENT_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_AGENT_CLAUDE_ENABLED", "false")
    monkeypatch.setattr(config_api, "_CONFIG_FILE", override_file)
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", override_file)
    monkeypatch.setattr(review_stats_mod, "_STATS_FILE", stats_file)
    config_mod._settings = None
    yield
    config_mod._settings = None


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    from roughcut.db.session import Base

    TEST_DB_FILE.unlink(missing_ok=True)
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    TEST_DB_FILE.unlink(missing_ok=True)


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_engine) -> AsyncGenerator[AsyncClient, None]:
    from roughcut.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
