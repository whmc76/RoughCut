from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from pathlib import Path

from roughcut.config import normalize_transcription_provider_name
from roughcut.config import get_settings
from roughcut.docker_gpu_guard import _probe_service_health
from roughcut.docker_gpu_guard import adopt_running_idle_managed_gpu_services

logger = logging.getLogger(__name__)

_PREFLIGHT_INTERVAL_SEC = 30.0
_last_preflight_at = 0.0
_preflight_lock = asyncio.Lock()


async def ensure_runtime_services_ready(*, force: bool = False, reason: str = "") -> None:
    global _last_preflight_at

    now = time.monotonic()
    if not force and (now - _last_preflight_at) < _PREFLIGHT_INTERVAL_SEC:
        return

    async with _preflight_lock:
        now = time.monotonic()
        if not force and (now - _last_preflight_at) < _PREFLIGHT_INTERVAL_SEC:
            return

        await asyncio.to_thread(_ensure_core_compose_services_started)
        await asyncio.to_thread(adopt_running_idle_managed_gpu_services, reason=reason or "runtime_preflight_adopt")
        _last_preflight_at = time.monotonic()


def _ensure_core_compose_services_started() -> None:
    settings = get_settings()
    if not bool(getattr(settings, "runtime_preflight_docker_enabled", False)):
        return

    compose_file = Path("docker-compose.yml")
    if shutil.which("docker") is None or not compose_file.exists():
        return

    required_services = ("postgres", "redis")
    running = _list_running_compose_services(compose_file)
    missing = [service for service in required_services if service not in running]
    if not missing:
        return

    logger.info("runtime preflight starting core docker services=%s", ",".join(missing))
    _run_compose(compose_file, "up", "-d", *required_services)


def _list_running_compose_services(compose_file: Path) -> set[str]:
    command = ["docker", "compose", "-f", str(compose_file), "ps", "--services", "--status", "running"]
    result = subprocess.run(
        command,
        cwd=str(compose_file.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-1000:]
        logger.warning("runtime preflight unable to inspect core docker services: %s", detail)
        return set()
    return {line.strip() for line in (result.stdout or "").splitlines() if line.strip()}


def _run_compose(compose_file: Path, *args: str) -> None:
    command = ["docker", "compose", "-f", str(compose_file), *args]
    result = subprocess.run(
        command,
        cwd=str(compose_file.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-1000:]
        raise RuntimeError(f"docker compose {' '.join(args)} failed: {detail}")


def _managed_service_targets() -> list[dict[str, object]]:
    settings = get_settings()
    targets: list[dict[str, object]] = []

    transcription_provider = normalize_transcription_provider_name(getattr(settings, "transcription_provider", ""))
    if transcription_provider == "local_http_asr":
        targets.append(
            {
                "name": "local_http_asr",
                "kind": "asr",
                "url": str(getattr(settings, "local_asr_api_base_url", "") or "").strip(),
                "probe_kind": "health_json",
                **_service_management_config(settings, target_key="local_asr"),
            }
        )
    targets.append(
        {
            "name": "cosyvoice3_tts",
            "kind": "tts",
            "url": str(getattr(settings, "cosyvoice3_tts_api_base_url", "") or "").strip(),
            "probe_kind": "health_json",
            **_service_management_config(settings, target_key="cosyvoice3_tts"),
        }
    )
    targets.append(
        {
            "name": "moss_tts_local",
            "kind": "tts",
            "url": str(getattr(settings, "moss_tts_local_api_base_url", "") or "").strip(),
            "probe_kind": "health_json",
            **_service_management_config(settings, target_key="moss_tts_local"),
        }
    )
    if str(getattr(settings, "avatar_provider", "") or "").strip().lower() == "heygem":
        targets.append(
            {
                "name": "heygem",
                "kind": "avatar",
                "url": str(getattr(settings, "avatar_api_base_url", "") or "").strip(),
                "probe_kind": "heygem_preview",
                **_service_management_config(settings, target_key="heygem"),
            }
        )
    if str(getattr(settings, "voice_provider", "") or "").strip().lower() == "indextts2":
        targets.append(
            {
                "name": "indextts2",
                "kind": "voice_clone",
                "url": str(getattr(settings, "voice_clone_api_base_url", "") or "").strip(),
                "probe_kind": "health_json",
                **_service_management_config(settings, target_key="indextts2"),
            }
        )

    deduped: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for target in targets:
        key = (str(target["name"]), str(target["url"]))
        if not target["url"] or key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _service_management_config(settings: object, *, target_key: str) -> dict[str, object]:
    guard_enabled = bool(getattr(settings, "docker_gpu_guard_enabled", False)) and bool(
        getattr(settings, f"{target_key}_docker_guard_enabled", True)
    )
    default_idle_timeout = int(getattr(settings, "docker_gpu_guard_idle_timeout_sec", 900) or 900)
    idle_timeout = max(
        1,
        int(getattr(settings, f"{target_key}_docker_idle_timeout_sec", default_idle_timeout) or default_idle_timeout),
    )
    return {
        "target_key": target_key,
        "compose_file": str(getattr(settings, f"{target_key}_docker_compose_file", "") or "").strip(),
        "env_file": str(getattr(settings, f"{target_key}_docker_env_file", "") or "").strip(),
        "services": str(getattr(settings, f"{target_key}_docker_services", "") or "").strip(),
        "guard_enabled": guard_enabled,
        "auto_release_enabled": guard_enabled,
        "idle_timeout_sec": idle_timeout,
    }


async def get_managed_service_snapshots() -> list[dict[str, str | bool | int]]:
    snapshots: list[dict[str, str | bool | int]] = []
    for target in _managed_service_targets():
        healthy = await asyncio.to_thread(
            _probe_service_health,
            str(target["url"]),
            probe_kind=str(target["probe_kind"]),
        )
        snapshots.append(
            {
                "name": target["name"],
                "url": target["url"],
                "kind": target["kind"],
                "status": "ok" if healthy else "failed",
                "enabled": True,
                "target_key": target["target_key"],
                "compose_file": target["compose_file"],
                "env_file": target["env_file"],
                "services": target["services"],
                "guard_enabled": target["guard_enabled"],
                "auto_release_enabled": target["auto_release_enabled"],
                "idle_timeout_sec": target["idle_timeout_sec"],
            }
        )
    return snapshots
