from __future__ import annotations

import asyncio

from redis import Redis
from sqlalchemy import text

from roughcut.config import get_settings
from roughcut.db.session import get_engine


async def _check_database_ready() -> tuple[bool, str]:
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def _check_redis_ready() -> tuple[bool, str]:
    settings = get_settings()

    def _ping() -> None:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        try:
            client.ping()
        finally:
            client.close()

    try:
        await asyncio.to_thread(_ping)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def _check_storage_ready() -> tuple[bool, str]:
    from roughcut.storage.s3 import get_storage

    def _ensure_storage_root() -> None:
        storage = get_storage()
        storage.ensure_bucket()

    try:
        await asyncio.to_thread(_ensure_storage_root)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


async def build_readiness_payload() -> dict:
    checks: dict[str, dict[str, str]] = {}
    ready = True

    for name, probe in (
        ("database", _check_database_ready),
        ("redis", _check_redis_ready),
        ("storage", _check_storage_ready),
    ):
        ok, detail = await probe()
        checks[name] = {
            "status": "ok" if ok else "failed",
            "detail": detail,
        }
        ready = ready and ok

    return {
        "status": "ready" if ready else "degraded",
        "checks": checks,
    }
