from types import SimpleNamespace

import pytest

from roughcut.config import Settings
from roughcut import docker_gpu_guard, runtime_preflight


def test_docker_autostart_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.runtime_preflight_docker_enabled is False
    assert settings.docker_gpu_guard_enabled is True
    assert settings.avatar_render_no_progress_timeout_sec == 0
    assert settings.local_asr_docker_guard_enabled is True
    assert settings.local_asr_docker_compose_file.endswith("docker-compose.asr-matrix.yml")
    assert settings.local_asr_docker_services == "qwen3-asr"
    assert settings.local_asr_docker_idle_timeout_sec == 10
    assert settings.cosyvoice3_tts_docker_guard_enabled is True
    assert settings.cosyvoice3_tts_docker_services == "cosyvoice3-tts"
    assert settings.cosyvoice3_tts_docker_idle_timeout_sec == 10
    assert settings.moss_tts_local_docker_guard_enabled is True
    assert settings.moss_tts_local_docker_compose_file.endswith("docker-compose.moss-tts-local.yml")
    assert settings.moss_tts_local_docker_services == "moss-tts-local"
    assert settings.moss_tts_local_docker_idle_timeout_sec == 10
    assert settings.indextts2_docker_guard_enabled is False
    assert settings.indextts2_docker_services == "indextts2"
    assert settings.indextts2_docker_idle_timeout_sec == 10


def test_runtime_preflight_skips_compose_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_preflight, "get_settings", lambda: SimpleNamespace(runtime_preflight_docker_enabled=False))
    monkeypatch.setattr(runtime_preflight.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(runtime_preflight, "adopt_running_idle_managed_gpu_services", lambda reason="": None)

    def fail_run(*args, **kwargs):
        raise AssertionError("docker compose should not be called when runtime preflight Docker is disabled")

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fail_run)

    runtime_preflight._ensure_core_compose_services_started()


def test_managed_service_targets_include_lifecycle_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = SimpleNamespace(
        transcription_provider="local_http_asr",
        local_asr_api_base_url="http://127.0.0.1:30200",
        local_asr_docker_compose_file="E:/WorkSpace/RoughCut/docker-compose.asr-matrix.yml",
        local_asr_docker_env_file="",
        local_asr_docker_services="faster-whisper-large-v3",
        local_asr_docker_guard_enabled=True,
        local_asr_docker_idle_timeout_sec=120,
        cosyvoice3_tts_api_base_url="http://127.0.0.1:30180",
        cosyvoice3_tts_docker_compose_file="E:/WorkSpace/RoughCut/docker-compose.cosyvoice3.yml",
        cosyvoice3_tts_docker_env_file="",
        cosyvoice3_tts_docker_services="cosyvoice3-tts",
        cosyvoice3_tts_docker_guard_enabled=True,
        cosyvoice3_tts_docker_idle_timeout_sec=180,
        moss_tts_local_api_base_url="http://127.0.0.1:30191",
        moss_tts_local_docker_compose_file="E:/WorkSpace/RoughCut/docker-compose.moss-tts-local.yml",
        moss_tts_local_docker_env_file="",
        moss_tts_local_docker_services="moss-tts-local",
        moss_tts_local_docker_guard_enabled=True,
        moss_tts_local_docker_idle_timeout_sec=10,
        avatar_provider="",
        voice_provider="runninghub",
        docker_gpu_guard_enabled=True,
        docker_gpu_guard_idle_timeout_sec=900,
    )
    monkeypatch.setattr(runtime_preflight, "get_settings", lambda: settings)

    targets = {str(target["name"]): target for target in runtime_preflight._managed_service_targets()}

    assert targets["local_http_asr"]["kind"] == "asr"
    assert targets["local_http_asr"]["services"] == "faster-whisper-large-v3"
    assert targets["local_http_asr"]["guard_enabled"] is True
    assert targets["local_http_asr"]["auto_release_enabled"] is True
    assert targets["local_http_asr"]["idle_timeout_sec"] == 120
    assert targets["cosyvoice3_tts"]["kind"] == "tts"
    assert targets["cosyvoice3_tts"]["services"] == "cosyvoice3-tts"
    assert targets["cosyvoice3_tts"]["guard_enabled"] is True
    assert targets["cosyvoice3_tts"]["idle_timeout_sec"] == 180
    assert "moss_tts" not in targets
    assert targets["moss_tts_local"]["kind"] == "tts"
    assert targets["moss_tts_local"]["services"] == "moss-tts-local"
    assert targets["moss_tts_local"]["guard_enabled"] is True
    assert targets["moss_tts_local"]["idle_timeout_sec"] == 10


def test_adopt_running_idle_managed_gpu_services_schedules_idle_stop(monkeypatch: pytest.MonkeyPatch) -> None:
    target = SimpleNamespace(key="local_asr")
    monkeypatch.setattr(
        runtime_preflight,
        "adopt_running_idle_managed_gpu_services",
        lambda reason="": None,
    )

    from roughcut import docker_gpu_guard

    monkeypatch.setattr(
        docker_gpu_guard,
        "get_settings",
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_build_target_configs",
        lambda settings: [target],
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_target_management_supported",
        lambda current: True,
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_current_lease_count",
        lambda key: 0,
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_target_ready",
        lambda current: True,
    )

    writes: list[tuple[str, str, float]] = []
    scheduled: list[tuple[object, str]] = []
    monkeypatch.setattr(
        docker_gpu_guard,
        "_write_float_key",
        lambda key, field, value: writes.append((key, field, value)),
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_read_float_key",
        lambda key, field, default=0.0: 0.0,
    )
    monkeypatch.setattr(
        docker_gpu_guard,
        "_schedule_idle_stop_locked",
        lambda *, target, reason: scheduled.append((target, reason)),
    )
    monkeypatch.setattr(docker_gpu_guard, "_IDLE_TIMERS", {})

    docker_gpu_guard.adopt_running_idle_managed_gpu_services(reason="unit_test")

    assert writes
    assert writes[0][0] == "local_asr"
    assert writes[0][1] == "last_release_at"
    assert scheduled == [(target, "unit_test")]


def test_managed_service_defaults_use_current_project_root() -> None:
    settings = Settings(_env_file=None)

    assert settings.local_asr_docker_compose_file == str((docker_gpu_guard.DEFAULT_PROJECT_ROOT / "docker-compose.asr-matrix.yml").as_posix())
    assert settings.cosyvoice3_tts_docker_compose_file == str((docker_gpu_guard.DEFAULT_PROJECT_ROOT / "docker-compose.cosyvoice3.yml").as_posix())
    assert settings.moss_tts_local_docker_compose_file == str((docker_gpu_guard.DEFAULT_PROJECT_ROOT / "docker-compose.moss-tts-local.yml").as_posix())


def test_resolve_path_remaps_legacy_windows_workspace_path() -> None:
    resolved = docker_gpu_guard._resolve_path("E:/WorkSpace/RoughCut/docker-compose.moss-tts-local.yml")

    assert resolved == docker_gpu_guard.DEFAULT_PROJECT_ROOT / "docker-compose.moss-tts-local.yml"


def test_resolve_path_ignores_external_windows_path_in_non_windows_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docker_gpu_guard.os, "name", "posix")

    resolved = docker_gpu_guard._resolve_path("E:/WorkSpace/heygem/docker-compose.yml")

    assert resolved is None
