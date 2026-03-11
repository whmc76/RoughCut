from __future__ import annotations

import pytest

from roughcut.config import Settings


def test_default_settings():
    s = Settings(_env_file=None)
    assert s.transcription_provider == "openai"
    assert s.llm_mode == "performance"
    assert s.reasoning_provider == "openai"
    assert s.local_reasoning_model == "qwen3.5:9b"
    assert s.multimodal_fallback_provider == "ollama"
    assert s.search_provider == "auto"
    assert s.search_fallback_provider == "searxng"
    assert s.openai_auth_mode == "api_key"
    assert s.anthropic_auth_mode == "api_key"
    assert s.minimax_base_url == "https://api.minimaxi.com/v1"
    assert ".mp4" in s.allowed_extensions
    assert s.render_debug_dir == "logs/render-debug"
    assert s.cover_output_variants == 5
    assert s.active_reasoning_provider == "openai"


def test_local_mode_switches_active_provider():
    s = Settings(_env_file=None, llm_mode="local", local_reasoning_model="qwen3.5:9b")
    assert s.active_reasoning_provider == "ollama"
    assert s.active_reasoning_model == "qwen3.5:9b"
    assert s.active_search_provider == "auto"


def test_parse_extensions_from_string():
    s = Settings(_env_file=None, allowed_extensions=".mp4,.mov,.mkv")
    assert s.allowed_extensions == [".mp4", ".mov", ".mkv"]


def test_max_upload_size_bytes():
    s = Settings(_env_file=None, max_upload_size_mb=100)
    assert s.max_upload_size_bytes == 100 * 1024 * 1024
