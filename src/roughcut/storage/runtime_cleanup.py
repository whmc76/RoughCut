from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Iterable

from roughcut.config import get_settings
from roughcut.providers.avatar.heygem import _detect_shared_root
from roughcut.storage.s3 import get_storage, job_key


def cleanup_job_runtime_files(
    job_id: str,
    *,
    artifacts: Iterable[Any] | None = None,
    render_outputs: Iterable[Any] | None = None,
    purge_deliverables: bool,
) -> None:
    settings = get_settings()
    storage = get_storage()

    if bool(getattr(settings, "cleanup_job_storage_on_terminal", True)):
        storage.delete_prefix(job_key(job_id, "").rstrip("/"))

    if bool(getattr(settings, "cleanup_render_debug_on_terminal", True)):
        _cleanup_render_debug_dirs(job_id)

    payloads: list[Any] = []
    for artifact in artifacts or []:
        storage_path = str(getattr(artifact, "storage_path", "") or "").strip()
        if purge_deliverables:
            _delete_path_like(storage_path)
        payloads.append(getattr(artifact, "data_json", None))

    for render_output in render_outputs or []:
        if purge_deliverables:
            _delete_path_like(str(getattr(render_output, "output_path", "") or "").strip())

    if bool(getattr(settings, "cleanup_heygem_temp_on_terminal", True)):
        for payload in payloads:
            for candidate in _collect_payload_paths(payload):
                _delete_heygem_temp_path(candidate)


def _cleanup_render_debug_dirs(job_id: str) -> None:
    debug_root = Path(str(get_settings().render_debug_dir or "")).expanduser()
    if not debug_root.exists():
        return
    prefix = f"{job_id}_"
    for candidate in debug_root.glob(f"{prefix}*"):
        shutil.rmtree(candidate, ignore_errors=True)


def _collect_payload_paths(payload: Any) -> set[str]:
    paths: set[str] = set()
    if isinstance(payload, dict):
        for value in payload.values():
            paths.update(_collect_payload_paths(value))
    elif isinstance(payload, list):
        for value in payload:
            paths.update(_collect_payload_paths(value))
    elif isinstance(payload, str):
        candidate = payload.strip()
        if _looks_like_path(candidate):
            paths.add(candidate)
    return paths


def _looks_like_path(value: str) -> bool:
    if not value:
        return False
    if value.startswith("/code/data/"):
        return True
    path = Path(value)
    if path.is_absolute():
        return True
    return False


def _delete_path_like(value: str) -> None:
    path = _resolve_path_like(value)
    if path is None or not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return
    path.unlink(missing_ok=True)


def _delete_heygem_temp_path(value: str) -> None:
    path = _resolve_path_like(value)
    shared_root = _detect_shared_root()
    if path is None or shared_root is None or not path.exists():
        return
    shared_root = shared_root.resolve()
    try:
        resolved = path.resolve()
        resolved.relative_to(shared_root)
    except Exception:
        return

    protected_roots = (
        shared_root / "avatar",
        shared_root / "voice",
    )
    if any(_is_relative_to(resolved, protected_root.resolve()) for protected_root in protected_roots if protected_root.exists()):
        return

    allowed_roots = (
        shared_root / "temp",
        shared_root / "result",
        shared_root / "inputs" / "audio",
        shared_root / "inputs" / "video",
    )
    if not any(_is_relative_to(resolved, allowed_root.resolve()) for allowed_root in allowed_roots if allowed_root.exists()):
        return

    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
    else:
        resolved.unlink(missing_ok=True)


def _resolve_path_like(value: str) -> Path | None:
    if not value:
        return None
    if value.startswith("/code/data/"):
        shared_root = _detect_shared_root()
        if shared_root is None:
            return None
        suffix = value.removeprefix("/code/data/").replace("/", "\\")
        return (shared_root / suffix).resolve()
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return None


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
