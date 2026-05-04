from __future__ import annotations

import os
from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from roughcut.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_session_factory = None
_worker_mode = False  # Set True in Celery workers to always create fresh engines


def set_worker_mode(enabled: bool = True) -> None:
    """Call this in Celery worker initialization to disable engine caching."""
    global _worker_mode
    _worker_mode = enabled


def get_engine():
    global _engine
    if _worker_mode or _engine is None:
        settings = get_settings()
        # SQLAlchemy's asyncpg pool can reuse an in-flight connection under the
        # Windows proactor loop in this app. Keep Windows/worker processes on
        # short-lived connections; non-Windows API deployments use a bounded pool.
        if _worker_mode or os.name == "nt":
            _engine = create_async_engine(
                settings.database_url,
                echo=False,
                poolclass=NullPool,
            )
        elif _uses_sqlite(settings.database_url):
            _engine = create_async_engine(
                settings.database_url,
                echo=False,
            )
        else:
            _engine = create_async_engine(
                settings.database_url,
                echo=False,
                pool_size=settings.db_pool_size,
                max_overflow=settings.db_max_overflow,
                pool_timeout=settings.db_pool_timeout_sec,
                pool_recycle=settings.db_pool_recycle_sec,
            )
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
