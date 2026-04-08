from __future__ import annotations

from pathlib import Path

import yaml
import json


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
    assert 'Write-Host "Docker live source sync is active for this runtime."' in script_text


def test_start_script_avoids_reusing_runtime_api_port_for_local_mode():
    script_text = Path("start_roughcut.ps1").read_text(encoding="utf-8")

    assert 'Resolve-ContainerMappedPort -ContainerName "roughcut-api-1" -ContainerPort 8000' in script_text
    assert 'Docker runtime API is already listening on port $runtimeApiPort; local API will use a different port.' in script_text


def test_batch_help_describes_local_first_entrypoint():
    script_text = Path("start_roughcut.bat").read_text(encoding="utf-8")
    usage_text = script_text.split(":usage", 1)[1]

    assert "One-click local development launcher" in usage_text
    assert "Start local API / orchestrator / workers against local code" in usage_text
    assert "Start explicit containerized runtime mode" in usage_text
    assert "Start recommended Docker runtime with live source sync" not in usage_text
    assert "runtime-auto-watch" not in usage_text
    assert "full-auto-watch" not in usage_text


def test_readme_describes_local_first_development_flow():
    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert "现在推荐的日常开发路径是：本地 Python + 本地前端 + 必要时只起 `infra`" in readme_text
    assert "`start_roughcut.bat` 作为默认开发入口" in readme_text
    assert "`runtime/full` 仍保留，但属于显式容器模式" in readme_text
    assert "Docker 更适合基础依赖、部署验证和显式容器化运行" in readme_text
    assert "runtime-auto-watch" not in readme_text
    assert "full-auto-watch" not in readme_text


def test_bootstrap_and_docs_prefer_qwen3_asr_over_local_asr_defaults():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))
    script_text = Path("start_roughcut.ps1").read_text(encoding="utf-8")
    readme_text = Path("README.md").read_text(encoding="utf-8")

    assert package_json["scripts"]["bootstrap"] == "uv sync --extra dev && pnpm install"
    assert '--extra", "local-asr"' not in script_text
    assert ".[dev,local-asr]" not in script_text
    assert "用 `uv sync --extra dev` 安装默认 Python 依赖" in readme_text
    assert "如果你明确要在宿主机里启用 `funasr` / `faster-whisper`" in readme_text
    assert "TRANSCRIPTION_PROVIDER=qwen3_asr" in readme_text
    assert "离线本地依赖可选 `funasr + sensevoice-small` 或 `faster_whisper`" in readme_text


def test_package_scripts_demote_ambiguous_docker_up_aliases():
    package_json = json.loads(Path("package.json").read_text(encoding="utf-8"))

    assert package_json["scripts"]["docker:up"] == "pnpm docker:infra:up"
    assert package_json["scripts"]["docker:down"] == "pnpm docker:infra:down"
    assert package_json["scripts"]["docker:runtime:up"] == "pwsh -NoProfile -File start_roughcut.ps1 -Mode runtime"
    assert package_json["scripts"]["docker:auto:up"] == "pwsh -NoProfile -File start_roughcut.ps1 -Mode full"


def test_docker_compose_defaults_do_not_enable_local_asr():
    runtime_compose = Path("docker-compose.runtime.yml").read_text(encoding="utf-8")
    base_compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-}' in runtime_compose
    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-}' in base_compose
    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-""}' not in runtime_compose
    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-""}' not in base_compose
    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-local-asr}' not in runtime_compose
    assert '${ROUGHCUT_DOCKER_PYTHON_EXTRAS:-local-asr}' not in base_compose
