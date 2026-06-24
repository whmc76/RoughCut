from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, close_all_sessions, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from roughcut.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_engine_loop_id = None
_session_factory = None
_worker_mode = False  # Set True in Celery workers to always create fresh engines


def set_worker_mode(enabled: bool = True) -> None:
    """Call this in Celery worker initialization to disable engine caching."""
    global _worker_mode
    _worker_mode = enabled


def get_engine():
    global _engine, _engine_loop_id, _session_factory
    loop_id = _current_loop_id()
    if _worker_mode or _engine is None or _engine_loop_id != loop_id:
        _engine = _create_engine()
        _engine_loop_id = loop_id
        _session_factory = None
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _worker_mode or _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def reset_session_state() -> None:
    global _engine, _engine_loop_id, _session_factory
    engine = _engine
    _engine = None
    _engine_loop_id = None
    _session_factory = None
    await close_all_sessions()
    if engine is not None:
        await engine.dispose()


def reset_session_state_sync() -> None:
    global _engine, _engine_loop_id, _session_factory
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(reset_session_state())
        return
    # Callers should use the async variant when already inside an event loop.
    _engine = None
    _engine_loop_id = None
    _session_factory = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def _uses_sqlite(database_url: str) -> bool:
    try:
        return make_url(database_url).drivername.startswith("sqlite")
    except Exception:
        return str(database_url or "").lower().startswith("sqlite")


def _current_loop_id() -> int | None:
    try:
        return id(asyncio.get_running_loop())
    except RuntimeError:
        return None


def _create_engine():
    settings = get_settings()
    # SQLAlchemy's asyncpg pool can retain loop-bound connections after dev
    # reloads or worker handoffs. Use short-lived connections for workers,
    # Windows local runs, and Docker dev when DB_USE_NULL_POOL=true.
    if _worker_mode or os.name == "nt" or settings.db_use_null_pool:
        return create_async_engine(
            settings.database_url,
            echo=False,
            poolclass=NullPool,
        )
    if _uses_sqlite(settings.database_url):
        return create_async_engine(
            settings.database_url,
            echo=False,
        )
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_sec,
        pool_recycle=settings.db_pool_recycle_sec,
    )
