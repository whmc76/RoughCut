from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, field_validator

from roughcut.pipeline.live_readiness import load_live_readiness_snapshot
from roughcut.pipeline.orchestrator import get_orchestrator_lock_snapshot
from roughcut.runtime_health import build_readiness_payload
from roughcut.telegram.review_notification_service import (
    build_review_notification_snapshot,
    drop_review_notification,
    drop_review_notifications,
    get_review_notification_store,
    requeue_review_notification,
    requeue_review_notifications,
)

router = APIRouter(prefix="/control", tags=["control"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STOP_SCRIPT = _REPO_ROOT / "start_roughcut.ps1"


class StopServicesIn(BaseModel):
    stop_docker: bool = False


class ReviewNotificationActionIn(BaseModel):
    notification_id: str

    @field_validator("notification_id")
    @classmethod
    def _validate_notification_id(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("notification_id is required")
        return normalized


class ReviewNotificationBatchActionIn(BaseModel):
    notification_ids: list[str]

    @field_validator("notification_ids")
    @classmethod
    def _validate_notification_ids(cls, value: list[str]) -> list[str]:
        normalized = [str(item or "").strip() for item in value if str(item or "").strip()]
        if not normalized:
            raise ValueError("notification_ids is required")
        return normalized


def _pick_shell() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("Neither pwsh nor powershell is available")
    return shell


def _has_process(substring: str) -> bool:
    try:
        if os.name == "nt":
            shell = _pick_shell()
            current_pid = os.getpid()
            script = (
                "$needle = @'\n"
                f"{substring}\n"
                "'@;"
                " $proc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
                f"Where-Object {{ $_.ProcessId -ne {current_pid} -and $_.CommandLine -and $_.CommandLine.Contains($needle) }} | "
                "Select-Object -First 1;"
                " if ($null -ne $proc) { '1' }"
            )
            result = subprocess.run(
                [shell, "-NoProfile", "-Command", script],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return result.returncode == 0 and result.stdout.strip() == "1"

        result = subprocess.run(
            ["ps", "-eo", "command="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        if result.returncode != 0:
            return False
        return any(substring in line for line in result.stdout.splitlines())
    except Exception:
        return False


def _running_compose_service_names() -> set[str]:
    containers = _running_container_names()
    services: set[str] = set()
    for service in ("orchestrator", "worker-media", "worker-llm"):
        if _has_compose_container(containers, service):
            services.add(service)
    return services


def _has_compose_container(containers: set[str], service_name: str) -> bool:
    pattern = re.compile(rf"(^|.*-){re.escape(service_name)}-\d+$")
    return any(pattern.search(container) for container in containers)


def _running_container_names() -> set[str]:
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return set()
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _has_container(containers: set[str], name: str) -> bool:
    return any(container == name or container.startswith(f"{name}-") for container in containers)


def _service_status_from_runtime(
    *,
    compose_services: set[str],
    service_name: str,
    process_needle: str,
    celery_queue: str | None = None,
) -> bool:
    if service_name in compose_services:
        return True
    if compose_services:
        return False
    if celery_queue and celery_queue in _running_celery_queues():
        return True
    return _has_process(process_needle)


def _running_celery_queues() -> set[str]:
    try:
        from roughcut.pipeline.celery_app import celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        payload = inspector.active_queues() or {}
    except Exception:
        return set()

    queues: set[str] = set()
    for worker_queues in payload.values():
        for queue_entry in worker_queues or []:
            name = str((queue_entry or {}).get("name") or "").strip()
            if name:
                queues.add(name)
    return queues


async def build_service_status(*, api_running: bool) -> dict[str, object]:
    containers = _running_container_names()
    compose_services = _running_compose_service_names()
    try:
        readiness = await build_readiness_payload()
    except Exception as exc:
        readiness = {
            "status": "unknown",
            "checks": {},
            "detail": str(exc),
        }
    try:
        orchestrator_lock = await get_orchestrator_lock_snapshot()
    except Exception as exc:
        orchestrator_lock = {
            "status": "unknown",
            "leader_active": None,
            "detail": str(exc),
        }
    try:
        review_notifications = build_review_notification_snapshot(limit=10)
    except Exception as exc:
        review_notifications = {
            "summary": {"total": 0, "pending": 0, "due_now": 0, "failed": 0, "delivered": 0},
            "items": [],
            "detail": str(exc),
        }
    try:
        live_readiness = load_live_readiness_snapshot()
    except Exception as exc:
        live_readiness = {
            "status": "unknown",
            "gate_passed": False,
            "summary": "live readiness unavailable",
            "stable_run_count": 0,
            "required_stable_runs": 3,
            "failure_reasons": [],
            "warning_reasons": [],
            "detail": str(exc),
        }
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": {
            "api": api_running,
            "telegram_agent": _has_process("telegram-agent"),
            "orchestrator": _service_status_from_runtime(
                compose_services=compose_services,
                service_name="orchestrator",
                process_needle="roughcut.cli orchestrator --poll-interval",
            )
            or bool(orchestrator_lock.get("leader_active")),
            "media_worker": _service_status_from_runtime(
                compose_services=compose_services,
                service_name="worker-media",
                process_needle="celery -A roughcut.pipeline.celery_app:celery_app worker --queues=media_queue",
                celery_queue="media_queue",
            ),
            "llm_worker": _service_status_from_runtime(
                compose_services=compose_services,
                service_name="worker-llm",
                process_needle="celery -A roughcut.pipeline.celery_app:celery_app worker --queues=llm_queue",
                celery_queue="llm_queue",
            ),
            "postgres": _has_container(containers, "roughcut-postgres")
            or readiness.get("checks", {}).get("database", {}).get("status") == "ok",
            "redis": _has_container(containers, "roughcut-redis")
            or readiness.get("checks", {}).get("redis", {}).get("status") == "ok",
        },
        "runtime": {
            "readiness_status": readiness.get("status", "unknown"),
            "readiness_checks": readiness.get("checks", {}),
            "orchestrator_lock": orchestrator_lock,
            "review_notifications": review_notifications,
            "live_readiness": live_readiness,
        },
    }


def _launch_stop_script(*, stop_docker: bool) -> None:
    if not _STOP_SCRIPT.exists():
        raise RuntimeError(f"Stop script not found: {_STOP_SCRIPT}")

    shell = _pick_shell()

    command = f"Start-Sleep -Seconds 1; & '{_STOP_SCRIPT}' -StopOnly"
    if stop_docker:
        command += " -StopDocker"

    subprocess.Popen(
        [
            shell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=str(_REPO_ROOT),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@router.post("/stop", status_code=status.HTTP_202_ACCEPTED)
async def stop_services(body: StopServicesIn):
    try:
        _launch_stop_script(stop_docker=body.stop_docker)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {
        "status": "scheduled",
        "stop_docker": body.stop_docker,
        "message": "Stop command scheduled. The dashboard may disconnect shortly.",
    }


@router.get("/status")
async def service_status():
    return await build_service_status(api_running=True)


@router.get("/review-notifications")
async def review_notification_status(
    status: list[str] | None = Query(default=None),
    job_id: str = "",
    kind: str = "",
    limit: int = 20,
):
    try:
        return build_review_notification_snapshot(
            statuses=status or None,
            job_id=job_id,
            kind=kind,
            limit=limit,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/review-notifications/requeue")
async def requeue_review_notification_route(body: ReviewNotificationActionIn):
    try:
        record = requeue_review_notification(body.notification_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Review notification not found: {body.notification_id}")
    return {
        "status": "requeued",
        "notification": {
            "notification_id": record.notification_id,
            "kind": record.kind,
            "job_id": record.job_id,
            "status": record.status,
            "attempt_count": record.attempt_count,
            "next_attempt_at": record.next_attempt_at,
            "last_error": record.last_error,
            "force_full_review": record.force_full_review,
            "updated_at": record.updated_at,
        },
    }


@router.post("/review-notifications/drop")
async def drop_review_notification_route(body: ReviewNotificationActionIn):
    store = get_review_notification_store()
    try:
        try:
            existing = store.get(body.notification_id, strict=True)
        except TypeError:
            existing = store.get(body.notification_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not existing:
        raise HTTPException(status_code=404, detail=f"Review notification not found: {body.notification_id}")
    try:
        deleted = drop_review_notification(body.notification_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Review notification not found: {body.notification_id}")
    return {
        "status": "dropped",
        "notification_id": body.notification_id,
    }


@router.post("/review-notifications/requeue-batch")
async def requeue_review_notifications_route(body: ReviewNotificationBatchActionIn):
    try:
        records = requeue_review_notifications(body.notification_ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "requeued",
        "count": len(records),
        "notification_ids": [item.notification_id for item in records],
    }


@router.post("/review-notifications/drop-batch")
async def drop_review_notifications_route(body: ReviewNotificationBatchActionIn):
    try:
        notification_ids = drop_review_notifications(body.notification_ids)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "dropped",
        "count": len(notification_ids),
        "notification_ids": notification_ids,
    }
