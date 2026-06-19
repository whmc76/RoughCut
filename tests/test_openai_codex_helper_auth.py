from __future__ import annotations

import json
from pathlib import Path

import pytest

from roughcut.providers.auth import resolve_credential
from roughcut.providers import multimodal
from roughcut.providers.multimodal import (
    _finalize_text,
    _normalize_json_mode_multimodal_content,
    _openai_direct_api_unavailable,
    _resolve_vision_model,
    _stage_codex_bridge_media_paths,
)


def test_codex_helper_reads_mounted_auth_when_script_is_missing(tmp_path, monkeypatch) -> None:
    auth_path = tmp_path / "auth.json"
    auth_path.write_text(json.dumps({"tokens": {"access_token": "codex-access-token"}}), encoding="utf-8")
    monkeypatch.setenv("ROUGHCUT_CODEX_AUTH_FILE", str(auth_path))

    token = resolve_credential(
        mode="helper",
        direct_value="",
        helper_command="python scripts/print_codex_access_token.py",
        provider_name="OpenAI",
    )

    assert token == "codex-access-token"


def test_multimodal_openai_attempts_codex_helper_when_configured() -> None:
    class Settings:
        openai_auth_mode = "helper"
        openai_api_key = ""
        openai_api_key_helper = "python scripts/print_codex_access_token.py"

    assert _openai_direct_api_unavailable(Settings()) is False


def test_multimodal_json_mode_wraps_non_json_text() -> None:
    assert _finalize_text("画面里是一台设备", json_mode=True) == '{"text": "画面里是一台设备"}'


def test_multimodal_json_mode_empty_text_shell_is_rejected() -> None:
    with pytest.raises(ValueError, match="empty text shell"):
        _normalize_json_mode_multimodal_content('{"text":""}', json_mode=True)


def test_multimodal_json_mode_non_empty_text_shell_extracts_embedded_json() -> None:
    normalized = _normalize_json_mode_multimodal_content('{"text":"```json\\n{\\"ok\\":true}\\n```"}', json_mode=True)

    assert normalized == '{"ok":true}'


@pytest.mark.asyncio
async def test_resolve_vision_model_uses_openai_compatible_default_when_active_model_is_minimax(monkeypatch) -> None:
    class Settings:
        vision_model = ""
        active_reasoning_provider = "minimax"
        active_vision_model = "MiniMax-M2.7"
        ollama_base_url = "http://127.0.0.1:11434"

    monkeypatch.setattr(multimodal, "get_settings", lambda: Settings())

    resolved = await _resolve_vision_model(provider="openai")

    assert resolved == "gpt-5.5"


@pytest.mark.asyncio
async def test_openai_codex_helper_multimodal_uses_host_bridge(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")
    calls: list[dict] = []

    class Settings:
        openai_auth_mode = "helper"
        openai_api_key = ""
        openai_api_key_helper = "python scripts/print_codex_access_token.py"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"stdout": json.dumps({"payload_json": "{\"ok\":true}"})}

    class FakeAsyncClient:
        def __init__(self, *, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, *, json, headers):
            calls.append({"url": url, "json": json, "headers": headers})
            return FakeResponse()

    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_URL", "http://host.docker.internal:38695/v1/codex/exec")
    monkeypatch.setenv("ROUGHCUT_ACP_BRIDGE_CODEX_PROXY_TOKEN", "token-1")
    async def fake_record_usage_event(**_kwargs):
        return None

    monkeypatch.setattr(multimodal.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(multimodal, "record_usage_event", fake_record_usage_event)

    result = await multimodal._complete_once_unthrottled(
        provider="openai",
        model="gpt-5.5",
        prompt='Return {"ok":true}',
        image_paths=[image_path],
        images_b64=["unused"],
        max_tokens=100,
        temperature=0.2,
        json_mode=True,
        settings=Settings(),
    )

    assert result == "{\"ok\":true}"
    assert calls[0]["url"] == "http://127.0.0.1:38695/v1/codex/exec"
    assert calls[0]["headers"]["Authorization"] == "Bearer token-1"
    assert calls[0]["json"]["images"] == [str(image_path)]


def test_stage_codex_bridge_media_paths_copies_files_when_staging_is_required(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"demo-image")

    monkeypatch.setattr(multimodal, "_should_stage_codex_bridge_media_path", lambda _path: True)

    with _stage_codex_bridge_media_paths([source]) as staged:
        assert len(staged) == 1
        assert staged[0].exists()
        assert staged[0].read_bytes() == b"demo-image"
        assert staged[0] != source


@pytest.mark.asyncio
async def test_complete_with_images_uses_openai_rescue_when_minimax_shell_is_empty(tmp_path, monkeypatch) -> None:
    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"fake-jpeg")
    calls: list[tuple[str, str]] = []

    class Settings:
        active_reasoning_provider = "minimax"
        active_vision_model = "MiniMax-M3"
        vision_model = ""
        llm_mode = "cloud"
        multimodal_fallback_provider = "minimax"
        multimodal_fallback_model = "MiniMax-M3"
        active_multimodal_fallback_provider = "minimax"
        active_multimodal_fallback_model = "MiniMax-M3"
        minimax_api_key = "mini-key"
        openai_auth_mode = "helper"
        openai_api_key = ""
        openai_api_key_helper = "python scripts/print_codex_access_token.py"

    async def fake_complete_once(**kwargs):
        calls.append((kwargs["provider"], kwargs["model"]))
        if kwargs["provider"] == "minimax":
            return '{"text":""}'
        return '{"best_number":3}'

    monkeypatch.setattr(multimodal, "get_settings", lambda: Settings())
    monkeypatch.setattr(multimodal, "_complete_once", fake_complete_once)
    monkeypatch.setattr(multimodal, "_store_cached_multimodal_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(multimodal, "_get_cached_multimodal_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(multimodal, "_can_attempt_multimodal_provider", lambda provider, _settings: provider in {"minimax", "openai"})

    result = await multimodal.complete_with_images(
        "pick one",
        [Path(image_path)],
        max_tokens=120,
        json_mode=True,
        preferred_provider="minimax",
        preferred_model="MiniMax-M3",
    )

    assert result == '{"best_number":3}'
    assert calls[0][0] == "minimax"
    assert calls[1][0] == "openai"
    assert calls[1][1] == "gpt-5.5"
