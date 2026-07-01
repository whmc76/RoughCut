from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token


def open_publication_entry_url(
    url: str,
    *,
    browser_binding: dict[str, Any] | None = None,
    allow_host_bridge: bool = True,
) -> dict[str, Any]:
    normalized_url = _normalize_http_url(url)
    binding = browser_binding if isinstance(browser_binding, dict) else {}
    if allow_host_bridge and _should_delegate_to_host_bridge():
        return _open_publication_entry_via_host_bridge(normalized_url, browser_binding=binding)

    browser = str(binding.get("browser") or "").strip().lower()
    user_data_dir = str(binding.get("user_data_dir") or "").strip()
    profile_directory = str(binding.get("profile_directory") or "").strip()

    if browser in {"chrome", "edge"} and user_data_dir and profile_directory:
        executable = _find_chromium_executable(browser)
        if executable:
            try:
                _spawn_chromium_profile_window(
                    executable=executable,
                    user_data_dir=user_data_dir,
                    profile_directory=profile_directory,
                    url=normalized_url,
                )
                return {
                    "opened": True,
                    "url": normalized_url,
                    "browser": browser,
                    "used_binding": True,
                    "mode": "browser_profile",
                    "message": "已使用创作者绑定浏览器 profile 打开发布页。",
                }
            except OSError:
                pass

    _open_with_default_browser(normalized_url)
    return {
        "opened": True,
        "url": normalized_url,
        "browser": browser or None,
        "used_binding": False,
        "mode": "default_browser",
        "message": "未找到可直接复用的本机浏览器 profile，已使用系统默认浏览器打开。",
    }


def _normalize_http_url(url: str) -> str:
    normalized_url = str(url or "").strip()
    parsed = urlparse(normalized_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("发布页地址必须是有效的 http(s) URL。")
    return normalized_url


def _should_delegate_to_host_bridge() -> bool:
    return os.name != "nt" and Path("/.dockerenv").exists()


def _open_publication_entry_via_host_bridge(
    url: str,
    *,
    browser_binding: dict[str, Any],
) -> dict[str, Any]:
    bridge_url = resolve_codex_proxy_sibling_url("/v1/host/open-publication-entry")
    if not bridge_url:
        raise RuntimeError("宿主机浏览器桥接未配置，无法从容器打开发布页。")
    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = httpx.post(
        bridge_url,
        json={
            "url": url,
            "browser_binding": browser_binding,
        },
        headers=headers,
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("宿主机浏览器桥接返回了无效响应。")
    payload.setdefault("opened", True)
    payload.setdefault("url", url)
    payload["launch_source"] = "codex_host_bridge"
    return payload


def _find_chromium_executable(browser: str) -> str:
    candidates: list[Path] = []
    if os.name == "nt":
        local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
        program_files = [Path(value) for value in (
            os.environ.get("PROGRAMFILES", ""),
            os.environ.get("PROGRAMFILES(X86)", ""),
        ) if value]
        if browser == "chrome":
            candidates.extend([
                local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
                *[root / "Google" / "Chrome" / "Application" / "chrome.exe" for root in program_files],
            ])
        elif browser == "edge":
            candidates.extend([
                local_app_data / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                *[root / "Microsoft" / "Edge" / "Application" / "msedge.exe" for root in program_files],
            ])
    elif sys.platform == "darwin":
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
            if browser == "chrome"
            else [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")]
        )
    else:
        executable_name = "google-chrome" if browser == "chrome" else "microsoft-edge"
        return executable_name

    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return ""


def _spawn_chromium_profile_window(
    *,
    executable: str,
    user_data_dir: str,
    profile_directory: str,
    url: str,
) -> None:
    subprocess.Popen(
        [
            executable,
            f"--user-data-dir={user_data_dir}",
            f"--profile-directory={profile_directory}",
            "--new-window",
            url,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _open_with_default_browser(url: str) -> None:
    if os.name == "nt":
        os.startfile(url)
        return
    webbrowser.open(url, new=1, autoraise=True)
