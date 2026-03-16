from __future__ import annotations

from pathlib import Path

import pytest


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def ping(self):
        return True

    def incr(self, key: str) -> int:
        value = int(self.store.get(key, "0")) + 1
        self.store[key] = str(value)
        return value

    def decr(self, key: str) -> int:
        value = int(self.store.get(key, "0")) - 1
        self.store[key] = str(value)
        return value

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value, nx: bool = False, ex: int | None = None):
        if nx and key in self.store:
            return False
        self.store[key] = str(value)
        return True

    def delete(self, key: str):
        self.store.pop(key, None)
        return 1


def _settings_stub(tmp_path: Path):
    class Settings:
        docker_gpu_guard_enabled = True
        docker_gpu_guard_idle_timeout_sec = 15
        redis_url = "redis://fake/0"
        avatar_api_base_url = "http://127.0.0.1:49202"
        avatar_training_api_base_url = "http://127.0.0.1:49204"
        voice_clone_api_base_url = "http://127.0.0.1:49204"
        heygem_docker_guard_enabled = True
        heygem_docker_compose_file = str(tmp_path / "deploy" / "heygem-shared" / "docker-compose.yml")
        heygem_docker_env_file = str(tmp_path / "deploy" / "heygem-shared" / ".env")
        heygem_docker_services = "heygem"
        heygem_docker_idle_timeout_sec = 15
        indextts2_docker_guard_enabled = True
        indextts2_docker_compose_file = str(tmp_path / "deploy" / "heygem-shared" / "docker-compose.yml")
        indextts2_docker_env_file = str(tmp_path / "deploy" / "heygem-shared" / ".env")
        indextts2_docker_services = "indextts2"
        indextts2_docker_idle_timeout_sec = 15
        qwen_asr_api_base_url = "http://127.0.0.1:18096"
        qwen_asr_docker_guard_enabled = True
        qwen_asr_docker_compose_file = str(tmp_path / "deploy" / "qwen-asr" / "docker-compose.yml")
        qwen_asr_docker_env_file = str(tmp_path / "deploy" / "qwen-asr" / ".env")
        qwen_asr_docker_services = "qwen-asr"
        qwen_asr_docker_idle_timeout_sec = 15

    compose_file = Path(Settings.heygem_docker_compose_file)
    compose_file.parent.mkdir(parents=True, exist_ok=True)
    compose_file.write_text("name: heygem-shared\nservices: {}\n", encoding="utf-8")
    Path(Settings.heygem_docker_env_file).write_text("", encoding="utf-8")
    qwen_compose = Path(Settings.qwen_asr_docker_compose_file)
    qwen_compose.parent.mkdir(parents=True, exist_ok=True)
    qwen_compose.write_text("name: qwen-asr\nservices: {}\n", encoding="utf-8")
    Path(Settings.qwen_asr_docker_env_file).write_text("", encoding="utf-8")
    return Settings()


def test_hold_managed_indextts2_gpu_services_starts_needed_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import roughcut.docker_gpu_guard as guard_mod

    fake_redis = FakeRedis()
    settings = _settings_stub(tmp_path)
    calls: list[tuple[str, ...]] = []
    started = {"value": False}

    monkeypatch.setattr(guard_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(guard_mod, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(guard_mod.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(guard_mod, "_run_compose_command", lambda target, *args: (calls.append((target.key, *args)), started.__setitem__("value", args[:2] == ("up", "-d"))))

    def fake_probe(url: str, *, probe_kind: str) -> bool:
        assert url == "http://127.0.0.1:49204"
        assert probe_kind == "health_json"
        return started["value"]

    monkeypatch.setattr(guard_mod, "_probe_service_health", fake_probe)

    with guard_mod.hold_managed_gpu_services(
        required_urls=["http://127.0.0.1:49204/v1/audio/speech"],
        reason="test",
    ):
        assert fake_redis.get("roughcut:docker_gpu_guard:indextts2:lease_count") == "1"

    assert calls == [("indextts2", "up", "-d", "indextts2")]
    assert fake_redis.get("roughcut:docker_gpu_guard:indextts2:lease_count") == "0"


def test_stop_services_if_idle_stops_full_stack(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import roughcut.docker_gpu_guard as guard_mod

    fake_redis = FakeRedis()
    settings = _settings_stub(tmp_path)
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(guard_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(guard_mod, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(guard_mod.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(guard_mod, "_run_compose_command", lambda target, *args: calls.append((target.key, *args)))

    fake_redis.set("roughcut:docker_gpu_guard:indextts2:lease_count", 0)
    fake_redis.set("roughcut:docker_gpu_guard:indextts2:last_release_at", "1")
    monkeypatch.setattr(guard_mod.time, "time", lambda: 60.0)

    target = guard_mod._resolve_required_targets(["http://127.0.0.1:49204/v1/audio/speech"])[0]
    guard_mod._stop_target_if_idle(target=target, reason="test")

    assert calls == [("indextts2", "stop", "indextts2")]


def test_hold_managed_qwen_asr_services_starts_needed_service(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    import roughcut.docker_gpu_guard as guard_mod

    fake_redis = FakeRedis()
    settings = _settings_stub(tmp_path)
    calls: list[tuple[str, ...]] = []
    started = {"value": False}

    monkeypatch.setattr(guard_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(guard_mod, "_get_redis_client", lambda: fake_redis)
    monkeypatch.setattr(guard_mod.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(guard_mod, "_run_compose_command", lambda target, *args: (calls.append((target.key, *args)), started.__setitem__("value", args[:2] == ("up", "-d"))))

    def fake_probe(url: str, *, probe_kind: str) -> bool:
        assert url == "http://127.0.0.1:18096"
        assert probe_kind == "health_json"
        return started["value"]

    monkeypatch.setattr(guard_mod, "_probe_service_health", fake_probe)

    with guard_mod.hold_managed_gpu_services(
        required_urls=["http://127.0.0.1:18096/transcribe"],
        reason="test",
    ):
        assert fake_redis.get("roughcut:docker_gpu_guard:qwen_asr:lease_count") == "1"

    assert calls == [("qwen_asr", "up", "-d", "qwen-asr")]
    assert fake_redis.get("roughcut:docker_gpu_guard:qwen_asr:lease_count") == "0"
