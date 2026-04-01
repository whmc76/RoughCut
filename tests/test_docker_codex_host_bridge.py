from __future__ import annotations

from pathlib import Path

import yaml


def _load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_runtime_compose_exposes_codex_host_bridge_env():
    compose = _load_yaml("docker-compose.runtime.yml")
    env = compose["services"]["api"]["environment"]

    assert "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL" in env
    assert "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN" in env


def test_start_script_knows_how_to_start_codex_host_bridge():
    script_text = Path("start_roughcut.ps1").read_text(encoding="utf-8")

    assert "scripts\\codex_host_bridge.py" in script_text
    assert "codex-host-bridge.env" in script_text
    assert "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL" in script_text


def test_refresh_session_loads_codex_host_bridge_env_file():
    script_text = Path("scripts/run-roughcut-docker-refresh-session.ps1").read_text(encoding="utf-8")

    assert "codex-host-bridge.env" in script_text
    assert "ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN" in script_text
