from types import SimpleNamespace

import pytest

from roughcut.config import Settings
from roughcut import runtime_preflight


def test_docker_autostart_defaults_to_disabled() -> None:
    settings = Settings(_env_file=None)

    assert settings.runtime_preflight_docker_enabled is False
    assert settings.docker_gpu_guard_enabled is False


def test_runtime_preflight_skips_compose_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_preflight, "get_settings", lambda: SimpleNamespace(runtime_preflight_docker_enabled=False))
    monkeypatch.setattr(runtime_preflight.shutil, "which", lambda name: "docker")

    def fail_run(*args, **kwargs):
        raise AssertionError("docker compose should not be called when runtime preflight Docker is disabled")

    monkeypatch.setattr(runtime_preflight.subprocess, "run", fail_run)

    runtime_preflight._ensure_core_compose_services_started()
