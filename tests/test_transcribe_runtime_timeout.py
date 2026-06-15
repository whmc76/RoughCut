from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import uuid

import httpx
import pytest

from roughcut.edit.decisions import EditDecision
from roughcut.llm_cache import save_cached_json
from roughcut.pipeline.steps import (
    _resolve_transcribe_no_progress_timeout_seconds,
    _resolve_edit_decision_llm_review_timeout_seconds,
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


def test_resolve_transcribe_no_progress_timeout_scales_for_single_request_audio(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        transcribe_runtime_timeout_sec=900,
        step_stale_timeout_sec=900,
        step_heartbeat_interval_sec=20,
        transcription_chunk_request_timeout_sec=180,
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

    monkeypatch.setattr("roughcut.pipeline.steps.probe_audio_duration", lambda path: 511.0)
    monkeypatch.setattr("roughcut.pipeline.steps.resolve_audio_chunk_config", lambda current: chunk_config)
    monkeypatch.setattr("roughcut.pipeline.steps.should_chunk_audio", lambda *, duration, config: False)

    timeout = _resolve_transcribe_no_progress_timeout_seconds(settings, audio_path=audio_path)

    assert timeout == 698.75


def test_resolve_edit_decision_llm_review_timeout_scales_for_zhipu_cooldown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        edit_decision_llm_review_timeout_sec=30,
        active_reasoning_provider="zhipu",
        zhipu_base_url="https://open.bigmodel.cn/api/paas/v4",
    )

    monkeypatch.setattr(
        "roughcut.pipeline.steps.provider_cooldown_remaining_seconds_for_url",
        lambda _url: 25.0,
    )

    timeout = _resolve_edit_decision_llm_review_timeout_seconds(settings, candidate_count=2)

    assert timeout == 125.0


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


@pytest.mark.asyncio
async def test_llm_cut_review_falls_back_when_payload_repair_still_fails(
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
    monkeypatch.setattr("roughcut.pipeline.steps.get_reasoning_provider", lambda: object())
    monkeypatch.setattr(
        "roughcut.pipeline.steps._complete_reasoning_with_timeout",
        lambda *args, **kwargs: SimpleNamespace(content='{"decisions":[],"summary":""}', raw_content='{"decisions":[],"summary":""}', usage=None),
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps._load_edit_decision_cut_review_json_payload",
        lambda **kwargs: (_ for _ in ()).throw(ValueError("edit decision cut review payload remained unusable after repair")),
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
        "error": "llm_cut_review_failed",
        "fallback": "deterministic_evidence",
    }


@pytest.mark.asyncio
async def test_llm_cut_review_reuses_compatible_cross_job_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = EditDecision(source="unit-test")
    settings = SimpleNamespace(
        edit_decision_llm_review_enabled=True,
        edit_decision_llm_review_min_confidence=0.72,
        active_reasoning_provider="openai",
        active_reasoning_model="gpt-5",
        output_dir=str(tmp_path),
    )
    candidates = [{"candidate_id": "cut-1", "start": 1.0, "end": 2.0, "reason": "silence"}]
    old_job_id = uuid.uuid4()
    new_job_id = uuid.uuid4()

    monkeypatch.setattr("roughcut.pipeline.steps.get_settings", lambda: settings)
    monkeypatch.setattr("roughcut.pipeline.steps.llm_task_route", lambda *args, **kwargs: nullcontext())
    monkeypatch.setattr(
        "roughcut.pipeline.steps._build_edit_decision_llm_review_candidates",
        lambda **kwargs: list(candidates),
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps.build_high_risk_cut_review_prompt",
        lambda **kwargs: [{"role": "system", "content": "review"}],
    )
    monkeypatch.setattr(
        "roughcut.pipeline.steps.get_reasoning_provider",
        lambda: (_ for _ in ()).throw(AssertionError("provider should not be called when compatible cache exists")),
    )

    fingerprint = {
        "source_meta": {
            "job_id": str(old_job_id),
            "source_name": "sample.mp4",
            "subject_brand": "NOC",
            "subject_model": "MT34",
            "subject_type": "EDC折刀",
        },
        "provider": "openai",
        "model": "gpt-5",
        "candidates_sha256": "same-candidates",
        "min_confidence": 0.72,
    }
    save_cached_json(
        "edit_plan.cut_review",
        "legacy-key",
        fingerprint=fingerprint,
        result={
            "provider": "openai",
            "model": "gpt-5",
            "summary": "cached review",
            "decisions": [
                {
                    "candidate_id": "cut-1",
                    "verdict": "keep",
                    "confidence": 0.91,
                    "reason": "cached keep",
                    "evidence": [],
                }
            ],
        },
    )
    monkeypatch.setattr("roughcut.pipeline.steps.digest_payload", lambda payload: "same-candidates")

    result = await _maybe_review_edit_decision_cuts_with_llm(
        job_id=new_job_id,
        source_name="sample.mp4",
        decision=decision,
        subtitle_items=[],
        transcript_segments=[],
        content_profile={
            "subject_brand": "NOC",
            "subject_model": "MT34",
            "subject_type": "EDC折刀",
        },
    )

    assert result.analysis["llm_cut_review"]["reviewed"] is True
    assert result.analysis["llm_cut_review"]["cached"] is True
    assert result.analysis["llm_cut_review"]["summary"] == "cached review"


@pytest.mark.asyncio
async def test_llm_cut_review_surfaces_upstream_zhipu_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decision = EditDecision(source="unit-test")
    settings = SimpleNamespace(
        edit_decision_llm_review_enabled=True,
        edit_decision_llm_review_min_confidence=0.72,
        active_reasoning_provider="zhipu",
        active_reasoning_model="glm-5.2",
    )
    request = httpx.Request("POST", "https://example.com/chat/completions")
    response = httpx.Response(
        429,
        request=request,
        headers={"retry-after-ms": "25", "x-log-id": "trace-123"},
        json={"error": {"code": "1113", "message": "余额不足或无可用资源包,请充值。"}},
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
    monkeypatch.setattr("roughcut.pipeline.steps.get_reasoning_provider", lambda: object())

    async def raise_http_error(*args, **kwargs):
        raise httpx.HTTPStatusError("429", request=request, response=response)

    monkeypatch.setattr("roughcut.pipeline.steps._complete_reasoning_with_timeout", raise_http_error)

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
        "error": "llm_cut_review_failed",
        "fallback": "deterministic_evidence",
        "upstream_status": 429,
        "upstream_error_code": "1113",
        "upstream_error_message": "余额不足或无可用资源包,请充值。",
        "retry_after_seconds": 0.025,
        "x_log_id": "trace-123",
        "upstream_body_excerpt": '{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}',
    }
