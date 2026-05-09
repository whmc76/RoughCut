from types import SimpleNamespace

import pytest

from roughcut.config import Settings
from roughcut import runtime_preflight


def test_docker_autostart_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.runtime_preflight_docker_enabled is False
    assert settings.docker_gpu_guard_enabled is False
    assert settings.avatar_render_no_progress_timeout_sec == 0
    assert settings.local_asr_docker_guard_enabled is True
    assert settings.local_asr_docker_compose_file.endswith("docker-compose.qwen3-asr.yml")
    assert settings.local_asr_docker_services == "qwen3-asr"
    assert settings.cosyvoice3_tts_docker_guard_enabled is True
    assert settings.cosyvoice3_tts_docker_services == "cosyvoice3-tts"


def test_runtime_preflight_skips_compose_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_preflight, "get_settings", lambda: SimpleNamespace(runtime_preflight_docker_enabled=False))
    monkeypatch.setattr(runtime_preflight.shutil, "which", lambda name: "docker")

    def fail_run(*args, **kwargs):
        raise AssertionError("docker compose should not be called when runtime preflight Docker is disabled")

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fail_run)

    runtime_preflight._ensure_core_compose_services_started()


def test_managed_service_targets_include_lifecycle_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        transcription_provider="local_http_asr",
        local_asr_api_base_url="http://127.0.0.1:30080",
        local_asr_docker_compose_file="E:/WorkSpace/RoughCut/docker-compose.qwen3-asr.yml",
        local_asr_docker_env_file="",
        local_asr_docker_services="qwen3-asr",
        local_asr_docker_guard_enabled=True,
        local_asr_docker_idle_timeout_sec=120,
        cosyvoice3_tts_api_base_url="http://127.0.0.1:30180",
        cosyvoice3_tts_docker_compose_file="E:/WorkSpace/RoughCut/docker-compose.cosyvoice3.yml",
        cosyvoice3_tts_docker_env_file="",
        cosyvoice3_tts_docker_services="cosyvoice3-tts",
        cosyvoice3_tts_docker_guard_enabled=True,
        cosyvoice3_tts_docker_idle_timeout_sec=180,
        avatar_provider="",
        voice_provider="runninghub",
        docker_gpu_guard_enabled=True,
        docker_gpu_guard_idle_timeout_sec=900,
    )
    monkeypatch.setattr(runtime_preflight, "get_settings", lambda: settings)

    targets = {str(target["name"]): target for target in runtime_preflight._managed_service_targets()}

    assert targets["local_http_asr"]["kind"] == "asr"
    assert targets["local_http_asr"]["services"] == "qwen3-asr"
    assert targets["local_http_asr"]["guard_enabled"] is True
    assert targets["local_http_asr"]["auto_release_enabled"] is True
    assert targets["local_http_asr"]["idle_timeout_sec"] == 120
    assert targets["cosyvoice3_tts"]["kind"] == "tts"
    assert targets["cosyvoice3_tts"]["services"] == "cosyvoice3-tts"
    assert targets["cosyvoice3_tts"]["guard_enabled"] is True
    assert targets["cosyvoice3_tts"]["idle_timeout_sec"] == 180
