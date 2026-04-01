from __future__ import annotations

from pathlib import Path

import pytest

from roughcut import runtime_preflight as mod


class _Settings:
    transcription_provider = "qwen3_asr"
    qwen_asr_api_base_url = "http://127.0.0.1:18096"
    avatar_provider = "heygem"
    avatar_api_base_url = "http://127.0.0.1:49202"
    voice_provider = "indextts2"
    voice_clone_api_base_url = "http://127.0.0.1:49204"


def test_managed_service_urls_follow_active_providers(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mod, "get_settings", lambda: _Settings())
    assert mod._managed_service_urls() == [
        "http://127.0.0.1:18096",
        "http://127.0.0.1:49202",
        "http://127.0.0.1:49204",
    ]


@pytest.mark.asyncio
async def test_runtime_preflight_is_throttled(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def fake_ensure_managed_service_urls_ready(*, reason: str) -> None:
        calls.append(f"managed:{reason}")

    def fake_ensure_core_compose_services_started() -> None:
        calls.append("core")

    monkeypatch.setattr(mod, "_ensure_core_compose_services_started", fake_ensure_core_compose_services_started)
    monkeypatch.setattr(mod, "_ensure_managed_service_urls_ready", fake_ensure_managed_service_urls_ready)
    monkeypatch.setattr(mod, "_last_preflight_at", 0.0)

    await mod.ensure_runtime_services_ready(force=True, reason="first")
    await mod.ensure_runtime_services_ready(reason="second")

    assert calls == ["core", "managed:first"]


def test_runtime_compose_overrides_voice_clone_api_base_url_for_containers():
    compose_text = Path("docker-compose.runtime.yml").read_text(encoding="utf-8")

    assert (
        "VOICE_CLONE_API_BASE_URL: ${ROUGHCUT_DOCKER_VOICE_CLONE_API_BASE_URL:-http://host.docker.internal:49204}"
        in compose_text
    )


def test_runtime_compose_mounts_avatar_material_profiles_into_container():
    compose_text = Path("docker-compose.runtime.yml").read_text(encoding="utf-8")

    assert "./data/avatar_materials:/app/data/avatar_materials" in compose_text
