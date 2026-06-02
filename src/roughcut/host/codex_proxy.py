from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse, urlunparse


_PROXY_URL_ENV = "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL"
_PROXY_TOKEN_ENV = "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN"


def resolve_codex_proxy_url() -> str:
    explicit = str(os.getenv(_PROXY_URL_ENV, "") or "").strip()
    if explicit:
        return _normalize_codex_proxy_url_for_runtime(explicit)
    from_file = _read_bridge_env_value(_PROXY_URL_ENV)
    if from_file:
        return _normalize_codex_proxy_url_for_runtime(from_file)
    return _normalize_codex_proxy_url_for_runtime("http://host.docker.internal:38695/v1/codex/exec")


def resolve_codex_proxy_token() -> str:
    explicit = str(os.getenv(_PROXY_TOKEN_ENV, "") or "").strip()
    if explicit:
        return explicit
    return _read_bridge_env_value(_PROXY_TOKEN_ENV)


def resolve_codex_proxy_sibling_url(path: str) -> str:
    proxy_url = resolve_codex_proxy_url()
    if proxy_url.endswith("/v1/codex/exec"):
        return f"{proxy_url[:-len('/v1/codex/exec')]}{path}"
    return ""


def _normalize_codex_proxy_url_for_runtime(raw_url: str) -> str:
    normalized = str(raw_url or "").strip()
    if not normalized:
        return ""
    try:
        parsed = urlparse(normalized)
    except Exception:
        return normalized
    if parsed.hostname and parsed.hostname.lower() == "host.docker.internal" and _prefer_localhost_bridge_runtime():
        netloc_host = "127.0.0.1"
        if parsed.port:
            netloc_host = f"{netloc_host}:{parsed.port}"
        parsed = parsed._replace(netloc=netloc_host)
        return urlunparse(parsed)
    return normalized


def _prefer_localhost_bridge_runtime() -> bool:
    if os.name == "nt":
        return True
    if str(os.getenv("ROUGHCUT_CODEX_PROXY_PREFER_LOCALHOST", "") or "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def _read_bridge_env_value(name: str) -> str:
    for path in _bridge_env_paths():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        for index, line in enumerate(lines):
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip() == name:
                cleaned = value.strip()
                if cleaned:
                    return cleaned
                if name == _PROXY_TOKEN_ENV:
                    for next_line in lines[index + 1 :]:
                        next_value = next_line.strip()
                        if next_value and "=" not in next_value:
                            return next_value
                        if "=" in next_value:
                            break
    return ""


def _bridge_env_paths() -> list[Path]:
    paths: list[Path] = []
    explicit = str(os.getenv("ROUGHCUT_CODEX_HOST_BRIDGE_ENV_FILE", "") or "").strip()
    if explicit:
        paths.append(Path(explicit))
    paths.extend(
        [
            Path("/app/logs/codex-host-bridge.env"),
            Path("logs/codex-host-bridge.env"),
        ]
    )
    return paths
