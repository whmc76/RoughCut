from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from roughcut.edit.decisions import EditDecision
from roughcut.pipeline.steps import (
    _maybe_review_edit_decision_cuts_with_llm,
    _resolve_transcribe_runtime_timeout_seconds,
)
from roughcut.providers.transcription.chunking import AudioChunkConfig, AudioChunkSpec


def test_resolve_transcribe_runtime_timeout_seconds_scales_for_chunked_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        transcribe_runtime_timeout_sec=900,
        step_stale_timeout_sec=900,
    )
    audio_path = Path("E:/tmp/audio.wav")
    chunk_config = AudioChunkConfig(
        enabled=True,
        threshold_sec=600.0,
        chunk_size_sec=60.0,
        min_chunk_sec=20.0,
        overlap_sec=1.5,
        request_timeout_sec=180.0,
        request_max_retries=2,
        request_retry_backoff_sec=5.0,
        export_timeout_sec=180.0,
    )
    chunk_specs = [AudioChunkSpec(index=i, count=30, start=float(i) * 58.5, end=float(i) * 58.5 + 60.0) for i in range(30)]

    monkeypatch.setattr("roughcut.pipeline.steps.probe_audio_duration", lambda path: 1717.6)
    monkeypatch.setattr("roughcut.pipeline.steps.resolve_audio_chunk_config", lambda current: chunk_config)
    monkeypatch.setattr("roughcut.pipeline.steps.should_chunk_audio", lambda *, duration, config: True)
    monkeypatch.setattr("roughcut.pipeline.steps.build_audio_chunk_specs", lambda duration, *, config: chunk_specs)

    timeout = _resolve_transcribe_runtime_timeout_seconds(settings, audio_path=audio_path)

    assert timeout == 3300.0


@pytest.mark.asyncio
async def test_llm_cut_review_skips_when_credentials_are_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = EditDecision(source="unit-test")
    settings = SimpleNamespace(
        edit_decision_llm_review_enabled=True,
        edit_decision_llm_review_min_confidence=0.72,
        active_reasoning_provider="openai",
        active_reasoning_model="gpt-5",
    )

    monkeypatch.setattr("roughcut.pipeline.steps.get_settings", lambda: settings)
    monkeypatch.setattr("roughcut.pipeline.steps.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        "roughcut.pipeline.steps._build_edit_decision_llm_review_candidates",
        lambda **kwargs: [{"candidate_id": "cut-1"}],
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps.build_high_risk_cut_review_prompt",
        lambda **kwargs: [{"role": "system", "content": "review"}],
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps.get_reasoning_provider",
        lambda: (_ for _ in ()).throw(ValueError("OpenAI API credential is not configured")),
    )

    result = await _maybe_review_edit_decision_cuts_with_llm(
        job_id=uuid.uuid4(),
        source_name="sample.mp4",
        decision=decision,
        subtitle_items=[],
        transcript_segments=[],
        content_profile={},
    )

    assert result.analysis["llm_cut_review"] == {
        "reviewed": False,
        "candidate_count": 1,
        "error": "llm_cut_review_unconfigured",
        "fallback": "deterministic_evidence",
    }
