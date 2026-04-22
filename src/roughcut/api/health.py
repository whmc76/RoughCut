from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request

from roughcut.pipeline.orchestrator import get_orchestrator_lock_snapshot
from roughcut.runtime_health import build_readiness_payload
from roughcut.runtime_preflight import get_managed_service_snapshots
from roughcut.watcher.folder_watcher import get_watch_root_auto_duty_snapshot

router = APIRouter(prefix="/health", tags=["health"])


async def build_health_detail(request: Request) -> dict[str, object]:
    readiness = await build_readiness_payload()
    orchestrator_lock = await get_orchestrator_lock_snapshot()
    managed_services = await get_managed_service_snapshots()
    watch_automation = await get_watch_root_auto_duty_snapshot()

    managed_failed = any(str(item.get("status") or "") != "ok" for item in managed_services)
    degraded = readiness.get("status") != "ready" or managed_failed

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "status": "degraded" if degraded else "ok",
        "api_version": getattr(request.app, "version", "0.1.5"),
        "readiness": readiness,
        "orchestrator_lock": orchestrator_lock,
        "managed_services": managed_services,
        "watch_automation": watch_automation,
    }


@router.get("/detail")
async def health_detail(request: Request):
    return await build_health_detail(request)
