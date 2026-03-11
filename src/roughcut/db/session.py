from __future__ import annotations

from collections.abc import AsyncGenerator

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
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            poolclass=NullPool,
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
        yield session
