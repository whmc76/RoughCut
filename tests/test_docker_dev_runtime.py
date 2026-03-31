from __future__ import annotations

from pathlib import Path

import yaml


def _load_yaml(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_dev_compose_enables_live_source_sync_for_runtime_services():
    compose = _load_yaml("docker-compose.dev.yml")
    services = compose["services"]

    api = services["api"]
    assert api["environment"]["PYTHONPATH"] == "/app/src"
    assert "./src:/app/src" in api["volumes"]
    assert "./frontend/dist:/app/frontend/dist" in api["volumes"]
    assert "--reload" in api["command"]

    orchestrator = services["orchestrator"]
    assert orchestrator["environment"]["PYTHONPATH"] == "/app/src"
    assert "/app/src" in orchestrator["command"][-1]

    worker_media = services["worker-media"]
    assert worker_media["environment"]["PYTHONPATH"] == "/app/src"
    assert "/app/src" in worker_media["command"][-1]

    worker_llm = services["worker-llm"]
    assert worker_llm["environment"]["PYTHONPATH"] == "/app/src"
    assert "/app/src" in worker_llm["command"][-1]

    frontend_watch = services["frontend-watch"]
    command = " ".join(frontend_watch["command"])
    assert "pnpm install --frozen-lockfile" in command
    assert "pnpm --dir frontend build --watch" in command


def test_start_script_uses_dev_overlay_for_runtime_and_full_modes():
    script_text = Path("start_roughcut.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $RepoRoot "docker-compose.dev.yml"' in script_text
    assert '$files += $DevComposeFile' in script_text
    assert 'Write-Host "Docker live sync is built into runtime/full mode."' in script_text


def test_batch_help_describes_live_sync_instead_of_workspace_refresh():
    script_text = Path("start_roughcut.bat").read_text(encoding="utf-8")

    assert "live source sync" in script_text
    assert "auto-refresh Docker runtime" not in script_text
