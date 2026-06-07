from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import httpx

from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token


def open_in_file_manager(target_path: str | Path) -> None:
    raw_target = _normalize_target_path(target_path)
    if _should_delegate_to_host_bridge():
        bridge_target = raw_target if _should_preserve_raw_host_path(raw_target) else str(Path(raw_target).resolve())
        _open_in_file_manager_via_host_bridge(bridge_target)
        return
    resolved = Path(raw_target).resolve()
    if os.name == "nt":
        if resolved.is_file():
            subprocess.Popen(["explorer", "/select,", str(resolved)])
        else:
            os.startfile(str(resolved))
        return
    open_path = resolved.parent if resolved.is_file() else resolved
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(open_path)])
        return
    subprocess.Popen(["xdg-open", str(open_path)])


def can_open_in_file_manager(target_path: str | Path) -> bool:
    raw_target = _normalize_target_path(target_path)
    if not raw_target:
        return False
    candidate = Path(raw_target).expanduser()
    try:
        if candidate.exists():
            return True
    except OSError:
        pass
    if _should_delegate_to_host_bridge() and (_should_preserve_raw_host_path(raw_target) or _looks_like_runtime_mount_path(raw_target)):
        return True
    return False


def describe_file_manager_target(target_path: str | Path) -> tuple[str, str]:
    raw_target = _normalize_target_path(target_path)
    candidate = Path(raw_target).expanduser()
    try:
        if candidate.exists():
            resolved = candidate.resolve()
            return str(resolved), "file" if resolved.is_file() else "folder"
    except OSError:
        pass
    return raw_target, _infer_target_kind(raw_target)


def _should_delegate_to_host_bridge() -> bool:
    return os.name != "nt" and Path("/.dockerenv").exists()


def _open_in_file_manager_via_host_bridge(target_path: str) -> None:
    url = resolve_codex_proxy_sibling_url("/v1/host/open-path")
    if not url:
        raise RuntimeError("宿主机文件管理器桥接未配置。")
    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.post(
        url,
        json={"path": target_path},
        headers=headers,
        timeout=10,
    )
    response.raise_for_status()


def _normalize_target_path(target_path: str | Path) -> str:
    return str(target_path or "").strip().strip('"')


def _should_preserve_raw_host_path(raw_target: str) -> bool:
    return _looks_like_windows_host_path(raw_target)


def _looks_like_windows_host_path(raw_target: str) -> bool:
    normalized = str(raw_target or "").strip()
    if normalized.startswith(("\\\\", "//")):
        return True
    return len(normalized) >= 3 and normalized[1:3] in {":\\", ":/"}


def _looks_like_runtime_mount_path(raw_target: str) -> bool:
    normalized = str(raw_target or "").strip().replace("\\", "/")
    return normalized.startswith("/app/data/")


def _infer_target_kind(raw_target: str) -> str:
    name = Path(str(raw_target or "").rstrip("\\/")).name
    if "." in name:
        return "file"
    return "folder"
