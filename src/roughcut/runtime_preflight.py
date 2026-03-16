from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import time
from pathlib import Path

from roughcut.config import get_settings
from roughcut.docker_gpu_guard import hold_managed_gpu_services_async

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
        await _ensure_managed_service_urls_ready(reason=reason or "runtime_preflight")
        _last_preflight_at = time.monotonic()


def _ensure_core_compose_services_started() -> None:
    compose_file = Path("docker-compose.yml")
    if shutil.which("docker") is None or not compose_file.exists():
        return

    required_services = ("postgres", "redis", "minio")
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


async def _ensure_managed_service_urls_ready(*, reason: str) -> None:
    for url in _managed_service_urls():
        try:
            async with hold_managed_gpu_services_async(required_urls=[url], reason=reason):
                pass
        except Exception as exc:
            logger.warning("runtime preflight failed to ensure managed service %s: %s", url, exc)


def _managed_service_urls() -> list[str]:
    settings = get_settings()
    urls: list[str] = []

    if str(getattr(settings, "transcription_provider", "") or "").strip().lower() == "qwen_asr":
        urls.append(str(getattr(settings, "qwen_asr_api_base_url", "") or "").strip())
    if str(getattr(settings, "avatar_provider", "") or "").strip().lower() == "heygem":
        urls.append(str(getattr(settings, "avatar_api_base_url", "") or "").strip())
    if str(getattr(settings, "voice_provider", "") or "").strip().lower() == "indextts2":
        urls.append(str(getattr(settings, "voice_clone_api_base_url", "") or "").strip())

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped
