from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import httpx
from redis import Redis

from roughcut.config import get_settings

logger = logging.getLogger(__name__)

_TARGET_LOCK = threading.RLock()
_IDLE_TIMERS: dict[str, threading.Timer] = {}
_LOCAL_LEASE_COUNTS: dict[str, int] = {}


@dataclass(frozen=True)
class _ManagedDockerTarget:
    key: str
    compose_file: str
    env_file: str
    services: tuple[str, ...]
    base_urls: tuple[str, ...]
    probe_kind: str


def hold_managed_gpu_services(*, required_urls: Iterable[str], reason: str = ""):
    return _ManagedGPUServiceLease(tuple(required_urls), reason=reason)


@asynccontextmanager
async def hold_managed_gpu_services_async(*, required_urls: Iterable[str], reason: str = ""):
    lease = _ManagedGPUServiceLease(tuple(required_urls), reason=reason)
    await asyncio.to_thread(lease.__enter__)
    try:
        yield
    finally:
        await asyncio.to_thread(lease.__exit__, None, None, None)


class _ManagedGPUServiceLease:
    def __init__(self, required_urls: tuple[str, ...], *, reason: str = "") -> None:
        self.required_urls = required_urls
        self.reason = reason
        self._targets: list[_ManagedDockerTarget] = []

    def __enter__(self):
        targets = _resolve_required_targets(self.required_urls)
        acquired: list[_ManagedDockerTarget] = []
        try:
            for target in targets:
                _acquire_target_lease(target=target, reason=self.reason)
                acquired.append(target)
        except Exception:
            for target in reversed(acquired):
                _release_target_lease(target=target, reason=f"{self.reason}:rollback")
            raise
        self._targets = acquired
        return self

    def __exit__(self, exc_type, exc, tb):
        for target in reversed(self._targets):
            _release_target_lease(target=target, reason=self.reason)
        self._targets = []
        return False


def _resolve_required_targets(required_urls: Iterable[str]) -> list[_ManagedDockerTarget]:
    settings = get_settings()
    normalized_required = {_normalize_base_url(url) for url in required_urls}
    normalized_required.discard("")
    if not normalized_required:
        return []

    candidates = [target for target in _build_target_configs(settings) if _target_matches(target, normalized_required)]
    unique: list[_ManagedDockerTarget] = []
    seen: set[str] = set()
    for target in candidates:
        if target.key not in seen:
            seen.add(target.key)
            unique.append(target)
    return unique


def _build_target_configs(settings) -> list[_ManagedDockerTarget]:
    return [
        _ManagedDockerTarget(
            key="heygem",
            compose_file=str(getattr(settings, "heygem_docker_compose_file", "E:/WorkSpace/heygem/docker-compose.yml") or ""),
            env_file=str(getattr(settings, "heygem_docker_env_file", "E:/WorkSpace/heygem/.env") or ""),
            services=_parse_services(getattr(settings, "heygem_docker_services", "heygem")),
            base_urls=(_normalize_base_url(getattr(settings, "avatar_api_base_url", "")),),
            probe_kind="heygem_preview",
        ),
        _ManagedDockerTarget(
            key="indextts2",
            compose_file=str(getattr(settings, "indextts2_docker_compose_file", "E:/WorkSpace/indextts2-service/docker-compose.yml") or ""),
            env_file=str(getattr(settings, "indextts2_docker_env_file", "E:/WorkSpace/indextts2-service/.env") or ""),
            services=_parse_services(getattr(settings, "indextts2_docker_services", "indextts2")),
            base_urls=(
                _normalize_base_url(getattr(settings, "voice_clone_api_base_url", "")),
                _normalize_base_url(getattr(settings, "avatar_training_api_base_url", "")),
            ),
            probe_kind="health_json",
        ),
        _ManagedDockerTarget(
            key="qwen_asr",
            compose_file=str(getattr(settings, "qwen_asr_docker_compose_file", "") or ""),
            env_file=str(getattr(settings, "qwen_asr_docker_env_file", "") or ""),
            services=_parse_services(getattr(settings, "qwen_asr_docker_services", "qwen-asr")),
            base_urls=(_normalize_base_url(getattr(settings, "qwen_asr_api_base_url", "")),),
            probe_kind="health_json",
        ),
    ]


def _parse_services(value: object) -> tuple[str, ...]:
    parts = [part.strip() for part in str(value or "").split(",")]
    return tuple(part for part in parts if part)


def _target_matches(target: _ManagedDockerTarget, normalized_required: set[str]) -> bool:
    target_urls = {base for base in target.base_urls if base}
    return bool(target_urls & normalized_required)


def _acquire_target_lease(*, target: _ManagedDockerTarget, reason: str) -> None:
    with _TARGET_LOCK:
        _cancel_idle_timer_locked(target.key)
        _increment_lease_count(target.key)
    try:
        _ensure_target_started(target=target, reason=reason)
    except Exception:
        with _TARGET_LOCK:
            _decrement_lease_count(target.key)
        raise


def _release_target_lease(*, target: _ManagedDockerTarget, reason: str) -> None:
    with _TARGET_LOCK:
        remaining = _decrement_lease_count(target.key)
        _write_float_key(target.key, "last_release_at", time.time())
        if remaining <= 0:
            _schedule_idle_stop_locked(target=target, reason=reason)


def _ensure_target_started(*, target: _ManagedDockerTarget, reason: str) -> None:
    if not _target_management_supported(target):
        return
    if _target_ready(target):
        return
    lock_acquired, token = _acquire_operation_lock(target.key, timeout_sec=20)
    try:
        if _target_ready(target):
            return
        logger.info(
            "starting managed gpu target=%s services=%s reason=%s",
            target.key,
            ",".join(target.services),
            reason or "-",
        )
        _run_compose_command(target, "up", "-d", *target.services)
        _wait_until_target_ready(target)
    finally:
        if lock_acquired:
            _release_operation_lock(target.key, token)


def _schedule_idle_stop_locked(*, target: _ManagedDockerTarget, reason: str) -> None:
    _cancel_idle_timer_locked(target.key)
    delay = max(15, _idle_timeout_seconds(target.key))
    timer = threading.Timer(delay, _stop_target_if_idle, kwargs={"target": target, "reason": reason})
    timer.daemon = True
    timer.name = f"roughcut-gpu-guard-{target.key}"
    _IDLE_TIMERS[target.key] = timer
    timer.start()


def _cancel_idle_timer_locked(target_key: str) -> None:
    timer = _IDLE_TIMERS.pop(target_key, None)
    if timer is not None:
        timer.cancel()


def _stop_target_if_idle(*, target: _ManagedDockerTarget, reason: str) -> None:
    if not _target_management_supported(target):
        return
    if _current_lease_count(target.key) > 0:
        return
    last_release_at = _read_float_key(target.key, "last_release_at", default=0.0)
    if last_release_at <= 0:
        return
    idle_for = time.time() - last_release_at
    if idle_for + 0.25 < _idle_timeout_seconds(target.key):
        return
    lock_acquired, token = _acquire_operation_lock(target.key, timeout_sec=20)
    if not lock_acquired:
        return
    try:
        if _current_lease_count(target.key) > 0:
            return
        logger.info(
            "stopping managed gpu target=%s services=%s idle_for=%.1fs reason=%s",
            target.key,
            ",".join(target.services),
            idle_for,
            reason or "-",
        )
        _run_compose_command(target, "stop", *target.services)
    finally:
        _release_operation_lock(target.key, token)


def _target_management_supported(target: _ManagedDockerTarget) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "docker_gpu_guard_enabled", True)):
        return False
    if not bool(getattr(settings, f"{target.key}_docker_guard_enabled", target.key != "qwen_asr")):
        return False
    if shutil.which("docker") is None:
        return False
    if not target.services:
        return False
    compose_file = _resolve_path(target.compose_file)
    return compose_file is not None and compose_file.exists()


def _target_ready(target: _ManagedDockerTarget) -> bool:
    base_urls = [url for url in target.base_urls if url]
    if not base_urls:
        return True
    return all(_probe_service_health(base_url, probe_kind=target.probe_kind) for base_url in base_urls)


def _wait_until_target_ready(target: _ManagedDockerTarget) -> None:
    deadline = time.monotonic() + 240.0
    while time.monotonic() < deadline:
        if _target_ready(target):
            return
        time.sleep(2.0)
    raise RuntimeError(f"managed gpu target {target.key} did not become ready")


def _probe_service_health(base_url: str, *, probe_kind: str) -> bool:
    timeout = httpx.Timeout(4.0, connect=1.5)
    if probe_kind == "heygem_preview":
        for path in ("/easy/query?code=healthcheck", "/v1/easy/query?code=healthcheck", "/query?code=healthcheck"):
            try:
                response = httpx.get(f"{base_url}{path}", timeout=timeout)
                if response.status_code < 500:
                    return True
            except Exception:
                continue
        return False

    for method, path in (("GET", "/health"), ("GET", "/healthz"), ("POST", "/v1/health")):
        try:
            response = httpx.request(method, f"{base_url}{path}", timeout=timeout)
        except Exception:
            continue
        if response.status_code >= 400:
            continue
        try:
            payload = response.json()
        except Exception:
            return True
        if str(payload.get("status") or "").lower() in {"ok", "healthy", "ready"}:
            return True
        if response.status_code < 300:
            return True
    return False


def _run_compose_command(target: _ManagedDockerTarget, *compose_args: str) -> None:
    compose_file = _resolve_path(target.compose_file)
    if compose_file is None:
        raise RuntimeError(f"compose file missing for target {target.key}")
    command = ["docker", "compose"]
    env_file = _resolve_path(target.env_file)
    if env_file is not None and env_file.exists():
        command.extend(["--env-file", str(env_file)])
    command.extend(["-f", str(compose_file)])
    command.extend(compose_args)
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
        detail = (result.stderr or result.stdout or "").strip()[-2000:]
        raise RuntimeError(f"docker compose {' '.join(compose_args)} failed for {target.key}: {detail}")


def _resolve_path(raw_value: str) -> Path | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _normalize_base_url(raw_url: object) -> str:
    parsed = urlparse(str(raw_url or "").strip())
    if not parsed.scheme or not parsed.hostname:
        return ""
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return f"{parsed.scheme}://{parsed.hostname.lower()}:{port}"


def _idle_timeout_seconds(target_key: str) -> int:
    settings = get_settings()
    default_value = int(getattr(settings, "docker_gpu_guard_idle_timeout_sec", 900) or 900)
    return max(15, int(getattr(settings, f"{target_key}_docker_idle_timeout_sec", default_value) or default_value))


def _get_redis_client() -> Redis | None:
    settings = get_settings()
    try:
        client = Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        return client
    except Exception:
        return None


def _lease_key(target_key: str) -> str:
    return f"roughcut:docker_gpu_guard:{target_key}:lease_count"


def _meta_key(target_key: str, name: str) -> str:
    return f"roughcut:docker_gpu_guard:{target_key}:{name}"


def _increment_lease_count(target_key: str) -> int:
    client = _get_redis_client()
    if client is None:
        _LOCAL_LEASE_COUNTS[target_key] = _LOCAL_LEASE_COUNTS.get(target_key, 0) + 1
        return _LOCAL_LEASE_COUNTS[target_key]
    return int(client.incr(_lease_key(target_key)))


def _decrement_lease_count(target_key: str) -> int:
    client = _get_redis_client()
    if client is None:
        _LOCAL_LEASE_COUNTS[target_key] = max(0, _LOCAL_LEASE_COUNTS.get(target_key, 0) - 1)
        return _LOCAL_LEASE_COUNTS[target_key]
    remaining = int(client.decr(_lease_key(target_key)))
    if remaining >= 0:
        return remaining
    client.set(_lease_key(target_key), 0)
    return 0


def _current_lease_count(target_key: str) -> int:
    client = _get_redis_client()
    if client is None:
        return max(0, _LOCAL_LEASE_COUNTS.get(target_key, 0))
    try:
        return max(0, int(client.get(_lease_key(target_key)) or 0))
    except Exception:
        return 0


def _write_float_key(target_key: str, name: str, value: float) -> None:
    client = _get_redis_client()
    if client is None:
        return
    try:
        client.set(_meta_key(target_key, name), f"{float(value):.6f}")
    except Exception:
        return


def _read_float_key(target_key: str, name: str, *, default: float) -> float:
    client = _get_redis_client()
    if client is None:
        return default
    try:
        return float(client.get(_meta_key(target_key, name)) or default)
    except Exception:
        return default


def _acquire_operation_lock(target_key: str, *, timeout_sec: int) -> tuple[bool, str]:
    token = f"{time.time_ns()}-{threading.get_ident()}"
    client = _get_redis_client()
    if client is None:
        return True, token
    deadline = time.monotonic() + max(3, timeout_sec)
    lock_key = _meta_key(target_key, "op_lock")
    while time.monotonic() < deadline:
        try:
            if client.set(lock_key, token, nx=True, ex=max(10, timeout_sec)):
                return True, token
        except Exception:
            return False, token
        time.sleep(0.25)
    return False, token


def _release_operation_lock(target_key: str, token: str) -> None:
    client = _get_redis_client()
    if client is None:
        return
    lock_key = _meta_key(target_key, "op_lock")
    try:
        if client.get(lock_key) == token:
            client.delete(lock_key)
    except Exception:
        return
