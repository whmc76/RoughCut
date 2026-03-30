from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from roughcut.pipeline.orchestrator import get_orchestrator_lock_snapshot
from roughcut.runtime_health import build_readiness_payload

router = APIRouter(prefix="/control", tags=["control"])

_REPO_ROOT = Path(__file__).resolve().parents[3]
_STOP_SCRIPT = _REPO_ROOT / "start_roughcut.ps1"


class StopServicesIn(BaseModel):
    stop_docker: bool = False


def _pick_shell() -> str:
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        raise RuntimeError("Neither pwsh nor powershell is available")
    return shell


def _has_process(substring: str) -> bool:
    try:
        if os.name == "nt":
            shell = _pick_shell()
            script = (
                "$needle = @'\n"
                f"{substring}\n"
                "'@;"
                " $proc = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | "
                "Where-Object { $_.CommandLine -and $_.CommandLine.Contains($needle) } | "
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


async def build_service_status(*, api_running: bool) -> dict[str, object]:
    containers = _running_container_names()
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
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "services": {
            "api": api_running,
            "telegram_agent": _has_process("telegram-agent"),
            "orchestrator": _has_process("roughcut.cli orchestrator --poll-interval"),
            "media_worker": _has_process(
                "celery -A roughcut.pipeline.celery_app:celery_app worker --queues=media_queue"
            ),
            "llm_worker": _has_process(
                "celery -A roughcut.pipeline.celery_app:celery_app worker --queues=llm_queue"
            ),
            "postgres": _has_container(containers, "roughcut-postgres"),
            "redis": _has_container(containers, "roughcut-redis"),
        },
        "runtime": {
            "readiness_status": readiness.get("status", "unknown"),
            "readiness_checks": readiness.get("checks", {}),
            "orchestrator_lock": orchestrator_lock,
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
