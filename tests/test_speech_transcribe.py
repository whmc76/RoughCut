from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.speech import transcribe as transcribe_mod


@pytest.mark.asyncio
async def test_execute_transcription_plan_falls_back_when_provider_init_fails(monkeypatch: pytest.MonkeyPatch):
    attempts: list[tuple[str, str]] = []

    class DummyProvider:
        async def transcribe(self, audio_path: Path, *, language: str, prompt: str | None = None, progress_callback=None):
            del audio_path, language, prompt, progress_callback
            return TranscriptResult(
                segments=[TranscriptSegment(index=0, start=0.0, end=1.0, text="手电筒开箱")],
                language="zh-CN",
                duration=1.0,
            )

    def fake_get_transcription_provider(*, provider: str | None = None, model: str | None = None):
        attempts.append((str(provider), str(model)))
        if provider == "openai":
            raise ValueError("OpenAI API credential is not configured")
        return DummyProvider()

    monkeypatch.setattr(
        transcribe_mod,
        "get_transcription_provider",
        fake_get_transcription_provider,
    )

    result, selected_provider, selected_model, errors = await transcribe_mod.execute_transcription_plan(
        audio_path=Path("demo.wav"),
        language="zh-CN",
        prompt="热词：手电筒, 开箱",
        provider_plan=[
            ("openai", "gpt-4o-transcribe"),
            ("qwen3_asr", "qwen3-asr-1.7b"),
        ],
    )

    assert [segment.text for segment in result.segments] == ["手电筒开箱"]
    assert selected_provider == "qwen3_asr"
    assert selected_model == "qwen3-asr-1.7b"
    assert attempts == [
        ("openai", "gpt-4o-transcribe"),
        ("qwen3_asr", "qwen3-asr-1.7b"),
    ]
    assert errors == [
        {
            "provider": "openai",
            "model": "gpt-4o-transcribe",
            "error": "OpenAI API credential is not configured",
        }
    ]
