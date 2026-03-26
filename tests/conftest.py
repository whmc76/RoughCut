from __future__ import annotations

import asyncio
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use a per-process SQLite file for tests to avoid collisions between parallel pytest processes.
TEST_DB_FILE = Path(tempfile.gettempdir()) / f"roughcut-test-{os.getpid()}.db"
TEST_DB_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE.as_posix()}"

os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost:9000")


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


@pytest.fixture(autouse=True)
def isolate_runtime_override_file(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod
    import roughcut.db.models  # noqa: F401
    import roughcut.db.session as db_session_mod
    from roughcut.db.session import Base
    import roughcut.review.content_profile_review_stats as review_stats_mod

    override_file = tmp_path / "roughcut_config.json"
    output_dir = tmp_path / "output"
    stats_file = tmp_path / "content_profile_review_stats.json"
    sync_engine = create_engine(TEST_DB_URL.replace("sqlite+aiosqlite:///", "sqlite:///"), future=True)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    with sqlite3.connect(TEST_DB_FILE) as conn:
        for table in ("app_settings", "config_profiles", "packaging_assets"):
            try:
                conn.execute(f"DELETE FROM {table}")
            except sqlite3.OperationalError:
                pass
        conn.commit()

    monkeypatch.setattr(config_api, "_CONFIG_FILE", override_file)
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", override_file)
    monkeypatch.setattr(review_stats_mod, "_STATS_FILE", stats_file)
    config_mod._session_secret_overrides.clear()
    config_mod._settings = config_mod.Settings(
        _env_file=None,
        output_dir=str(output_dir),
        telegram_agent_enabled=False,
        telegram_agent_claude_enabled=False,
    )
    yield
    config_mod._session_secret_overrides.clear()
    config_mod._settings = None
    if db_session_mod._engine is not None:
        asyncio.run(db_session_mod._engine.dispose())
    db_session_mod._engine = None
    db_session_mod._session_factory = None


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    import roughcut.db.models  # noqa: F401
    from roughcut.db.session import Base

    _safe_unlink(TEST_DB_FILE)
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()
    _safe_unlink(TEST_DB_FILE)


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
