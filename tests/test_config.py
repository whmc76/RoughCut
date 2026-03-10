from __future__ import annotations

import pytest

from fastcut.config import Settings


def test_default_settings():
    s = Settings()
    assert s.transcription_provider == "openai"
    assert s.reasoning_provider == "openai"
    assert ".mp4" in s.allowed_extensions


def test_parse_extensions_from_string():
    s = Settings(allowed_extensions=".mp4,.mov,.mkv")
    assert s.allowed_extensions == [".mp4", ".mov", ".mkv"]


def test_max_upload_size_bytes():
    s = Settings(max_upload_size_mb=100)
    assert s.max_upload_size_bytes == 100 * 1024 * 1024
