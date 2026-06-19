from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.providers.transcription import local_http_asr
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment, WordTiming
from roughcut.speech.transcribe import (
    _append_quality_fallbacks,
    AsrQualityGateError,
    analyze_transcript_temporal_coverage,
    analyze_transcript_asr_quality,
    execute_transcription_plan,
)


class _FakeProvider:
    def __init__(self, result: TranscriptResult | Exception) -> None:
        self._result = result

    async def transcribe(self, audio_path: Path, **kwargs) -> TranscriptResult:
        del audio_path, kwargs
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _result(provider: str, model: str, text: str, *, raw_chunk_text: str | None = None) -> TranscriptResult:
    segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=3.0,
        text=text,
        provider=provider,
        model=model,
        raw_text=text,
    )
    return TranscriptResult(
        segments=[segment],
        raw_segments=[segment],
        language="zh-CN",
        duration=3.0,
        provider=provider,
        model=model,
        raw_payload={"chunks": [{"text": raw_chunk_text if raw_chunk_text is not None else text}]},
    )


def _timed_result(
    provider: str,
    model: str,
    *,
    duration: float,
    ranges: list[tuple[float, float, str]],
) -> TranscriptResult:
    segments = [
        TranscriptSegment(
            index=index,
            start=start,
            end=end,
            text=text,
            provider=provider,
            model=model,
            raw_text=text,
        )
        for index, (start, end, text) in enumerate(ranges)
    ]
    return TranscriptResult(
        segments=segments,
        raw_segments=list(segments),
        language="zh-CN",
        duration=duration,
        provider=provider,
        model=model,
        raw_payload={},
    )


def _fake_local_asr_settings(**overrides):
    values = {
        "local_asr_api_base_url": "http://127.0.0.1:8000",
        "local_asr_transcribe_path": "/transcribe",
        "local_asr_model_name": "qwen3-asr-1.7b-forced-aligner",
        "local_asr_hotwords_field": "hotwords",
        "local_asr_hotwords_enabled": False,
        "local_asr_beam_size": 5,
        "local_asr_best_of": 5,
        "local_asr_condition_on_previous_text": False,
        "local_asr_vad_filter": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_local_http_asr_explicit_model_overrides_global_default(monkeypatch) -> None:
    monkeypatch.setattr(
        local_http_asr,
        "get_settings",
        lambda: _fake_local_asr_settings(),
    )

    provider = local_http_asr.LocalHTTPASRProvider(model_name="fun-asr-nano-2512")

    assert provider._model_name == "fun-asr-nano-2512"


def test_local_http_asr_fallback_model_uses_dedicated_base_url(monkeypatch) -> None:
    monkeypatch.delenv("LOCAL_ASR_FUNASR_NANO_2512_BASE_URL", raising=False)
    monkeypatch.setattr(
        local_http_asr,
        "get_settings",
        lambda: _fake_local_asr_settings(local_asr_api_base_url="http://127.0.0.1:30230"),
    )

    provider = local_http_asr.LocalHTTPASRProvider(model_name="fun-asr-nano-2512")

    assert provider._base_url == "http://127.0.0.1:30210"


def test_local_http_asr_fallback_model_base_url_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("LOCAL_ASR_FUNASR_NANO_2512_BASE_URL", "http://127.0.0.1:39999")
    monkeypatch.setattr(
        local_http_asr,
        "get_settings",
        lambda: _fake_local_asr_settings(local_asr_api_base_url="http://127.0.0.1:30230"),
    )

    provider = local_http_asr.LocalHTTPASRProvider(model_name="fun-asr-nano-2512")

    assert provider._base_url == "http://127.0.0.1:39999"


@pytest.mark.asyncio
async def test_qwen3_local_asr_short_duplicate_noise_uses_cleaned_segments(monkeypatch, tmp_path: Path) -> None:
    cleaned = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "你看啊好，不过好在呢，还算抢到了啊，没有这个像很多兄弟一样隐恨啊。",
        raw_chunk_text="你看啊啊好，不过好在呢，还还算抢到了啊，没没有没有这个像很多兄弟一样隐恨啊。",
    )
    providers = {
        ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"): _FakeProvider(cleaned),
    }

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del kwargs
        return providers[(provider, model)]

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    selected_result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=tmp_path / "audio.wav",
        language="zh-CN",
        prompt=None,
        provider_plan=[("local_http_asr", "qwen3-asr-1.7b-forced-aligner")],
    )

    assert selected_result is cleaned
    assert selected_provider == "local_http_asr"
    assert selected_model == "qwen3-asr-1.7b-forced-aligner"
    assert attempt_errors == []


@pytest.mark.asyncio
async def test_faster_whisper_local_asr_duplicate_text_is_not_rejected(monkeypatch, tmp_path: Path) -> None:
    result = _result(
        "local_http_asr",
        "faster-whisper-large-v3-beam5-nohot",
        "你看啊啊好，不过好在呢，还还算抢到了啊，没没有没有这个像很多兄弟一样隐恨啊。",
    )

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del provider, model, kwargs
        return _FakeProvider(result)

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    selected_result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=tmp_path / "audio.wav",
        language="zh-CN",
        prompt=None,
        provider_plan=[("local_http_asr", "faster-whisper-large-v3-beam5-nohot")],
    )

    assert selected_result is result
    assert selected_provider == "local_http_asr"
    assert selected_model == "faster-whisper-large-v3-beam5-nohot"
    assert attempt_errors == []


def test_normal_reduplication_does_not_trip_asr_quality_gate() -> None:
    result = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "我们开开箱吧，试试这个，轻轻一推，一点点手法，三三的背夹。",
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["suspicious_duplicate_count"] == 0


def test_two_isolated_qwen_duplicate_findings_are_advisory_not_blocking() -> None:
    result = TranscriptResult(
        segments=[],
        raw_segments=[],
        language="zh-CN",
        duration=120.0,
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_payload={
            "chunks": [
                {"text": "样的。哦，沉甸甸的，好沉的。赶紧看看"},
                {"text": "这把刀是能用的吧？呃，既既能这个切菜，又能削水"},
                {"text": "这里是正常的一段产品展示，没有重复污染。"},
                {"text": "这里也是正常的一段手感描述。"},
                {"text": "继续说一下快开和背夹。"},
                {"text": "这个角度可以看到细节。"},
                {"text": "合上以后再试一下。"},
                {"text": "最后说一下整体感觉。"},
            ],
        },
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["suspicious_duplicate_count"] == 2


def test_qwen3_duplicate_gate_uses_word_timestamps_to_keep_real_speech_repeats() -> None:
    segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=2.0,
        text="这里高肩背背负以后会更舒服",
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_text="这里高肩背背负以后会更舒服",
        words=[
            WordTiming("这", 0.00, 0.08),
            WordTiming("里", 0.08, 0.16),
            WordTiming("高", 0.20, 0.30),
            WordTiming("肩", 0.30, 0.42),
            WordTiming("背", 0.42, 0.56),
            WordTiming("背", 0.68, 0.82),
            WordTiming("负", 0.82, 0.96),
            WordTiming("以", 1.02, 1.14),
            WordTiming("后", 1.14, 1.28),
            WordTiming("会", 1.30, 1.42),
            WordTiming("更", 1.42, 1.54),
            WordTiming("舒", 1.54, 1.68),
            WordTiming("服", 1.68, 1.82),
        ],
    )
    result = TranscriptResult(
        segments=[segment],
        raw_segments=[segment],
        language="zh-CN",
        duration=2.0,
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_payload={},
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["suspicious_duplicate_count"] == 0
    assert analysis["likely_real_duplicate_count"] == 1
    assert analysis["advisory_units"][0]["findings"][0]["timing_reason"] == "duplicate_has_plausible_word_timing"


def test_qwen3_duplicate_gate_rejects_collapsed_timestamp_noise() -> None:
    segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=2.0,
        text="这么甩甩甩甩甩然后我们继续看",
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_text="这么甩甩甩甩甩然后我们继续看",
        words=[
            WordTiming("这", 0.00, 0.08),
            WordTiming("么", 0.08, 0.16),
            WordTiming("甩", 0.50, 0.50),
            WordTiming("甩", 0.50, 0.50),
            WordTiming("甩", 0.50, 0.50),
            WordTiming("甩", 0.50, 0.50),
            WordTiming("甩", 0.50, 0.50),
            WordTiming("然", 0.70, 0.82),
            WordTiming("后", 0.82, 0.94),
            WordTiming("我", 1.00, 1.12),
            WordTiming("们", 1.12, 1.24),
            WordTiming("继", 1.30, 1.42),
            WordTiming("续", 1.42, 1.54),
            WordTiming("看", 1.54, 1.70),
        ],
    )
    result = TranscriptResult(
        segments=[segment],
        raw_segments=[segment],
        language="zh-CN",
        duration=2.0,
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_payload={},
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is True
    assert analysis["severe_timing_noise_count"] >= 1
    assert analysis["affected_units"][0]["findings"][0]["timing_reason"] == "duplicate_timing_collapsed_or_jittered"


def test_qwen3_duplicate_gate_keeps_multi_segment_advisory_repeats() -> None:
    segments = []
    for index, start in enumerate([10.0, 30.0, 50.0]):
        segments.append(
            TranscriptSegment(
                index=index,
                start=start,
                end=start + 2.0,
                text=f"这里嘿嘿然后继续第{index}段",
                provider="local_http_asr",
                model="qwen3-asr-1.7b-forced-aligner",
                raw_text=f"这里嘿嘿然后继续第{index}段",
                words=[
                    WordTiming("这", start, start + 0.08),
                    WordTiming("里", start + 0.08, start + 0.16),
                    WordTiming("嘿", start + 0.3, start + 0.3),
                    WordTiming("嘿", start + 0.58, start + 0.72),
                    WordTiming("然", start + 0.8, start + 0.9),
                    WordTiming("后", start + 0.9, start + 1.0),
                ],
            )
        )
    result = TranscriptResult(
        segments=segments,
        raw_segments=list(segments),
        language="zh-CN",
        duration=80.0,
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_payload={},
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["affected_unit_count"] == 3
    assert analysis["advisory_duplicate_count"] == 3
    assert analysis["confirmed_noise_duplicate_count"] == 0
    assert analysis["severe_timing_noise_count"] == 0


def test_qwen3_duplicate_gate_keeps_common_laughter_without_word_timestamps_advisory() -> None:
    result = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "好了孩子们准备好，宾果嘿嘿好了，轮到我了吗哈哈继续。",
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["advisory_duplicate_count"] == 2
    assert analysis["confirmed_noise_duplicate_count"] == 0
    assert {
        finding["timing_reason"]
        for unit in analysis["affected_units"]
        for finding in unit["findings"]
    } == {"duplicate_text_without_word_timestamps_but_common_laughter_or_sound"}


def test_qwen3_duplicate_gate_keeps_common_laughter_with_collapsed_timing_advisory() -> None:
    segment = TranscriptSegment(
        index=0,
        start=0.0,
        end=2.0,
        text="好了孩子们嘿嘿准备好",
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_text="好了孩子们嘿嘿准备好",
        words=[
            WordTiming("好", 0.00, 0.10),
            WordTiming("了", 0.10, 0.20),
            WordTiming("孩", 0.20, 0.30),
            WordTiming("子", 0.30, 0.40),
            WordTiming("们", 0.40, 0.50),
            WordTiming("嘿", 0.60, 0.60),
            WordTiming("嘿", 0.60, 0.60),
            WordTiming("准", 0.80, 0.90),
            WordTiming("备", 0.90, 1.00),
            WordTiming("好", 1.00, 1.10),
        ],
    )
    result = TranscriptResult(
        segments=[segment],
        raw_segments=[segment],
        language="zh-CN",
        duration=2.0,
        provider="local_http_asr",
        model="qwen3-asr-1.7b-forced-aligner",
        raw_payload={},
    )

    analysis = analyze_transcript_asr_quality(result)

    assert analysis["rejected"] is False
    assert analysis["advisory_duplicate_count"] == 1
    assert analysis["confirmed_noise_duplicate_count"] == 0
    assert analysis["severe_timing_noise_count"] == 0
    assert analysis["affected_units"][0]["findings"][0]["timing_reason"] == (
        "duplicate_common_laughter_or_sound_with_limited_timing_evidence"
    )


def test_transcript_temporal_coverage_rejects_large_trailing_gap() -> None:
    result = _timed_result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        duration=436.8,
        ranges=[
            (1.1, 253.5, "前半段产品介绍"),
            (300.3, 377.8, "后半段手感描述"),
        ],
    )

    analysis = analyze_transcript_temporal_coverage(result)

    assert analysis["rejected"] is True
    assert analysis["reason"] == "transcript_temporal_coverage_low"
    assert analysis["trailing_gap_sec"] == 59.0


def test_transcript_temporal_coverage_accepts_normal_tail_gap() -> None:
    result = _timed_result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        duration=120.0,
        ranges=[(0.8, 112.0, "主体内容覆盖到接近结尾")],
    )

    assert analyze_transcript_temporal_coverage(result)["rejected"] is False


def test_qwen3_local_asr_plan_does_not_append_non_qwen_fallback_models_by_default(
    monkeypatch,
) -> None:
    monkeypatch.delenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS", raising=False)

    assert _append_quality_fallbacks(
        [("local_http_asr", "qwen3-asr-1.7b-forced-aligner")]
    ) == [
        ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"),
    ]


def test_qwen3_local_asr_plan_appends_quality_fallback_models_only_when_enabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS", "1")

    assert _append_quality_fallbacks(
        [("local_http_asr", "qwen3-asr-1.7b-forced-aligner")]
    ) == [
        ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"),
        ("local_http_asr", "faster-whisper-large-v3-beam5-nohot"),
    ]


@pytest.mark.asyncio
async def test_rejected_qwen3_local_asr_result_falls_back_to_next_local_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS", "1")
    bad = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "去去防御，你不要把东西掏出来。也就就加一个更字儿，啊啊好。",
    )
    good = _result(
        "local_http_asr",
        "faster-whisper-large-v3-beam5-nohot",
        "这个包的肩带和主仓结构看一下，整体容量比较适合日常通勤。",
    )
    providers = {
        ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"): _FakeProvider(bad),
        ("local_http_asr", "faster-whisper-large-v3-beam5-nohot"): _FakeProvider(good),
    }

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del kwargs
        return providers[(provider, model)]

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    selected_result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=tmp_path / "audio.wav",
        language="zh-CN",
        prompt=None,
        provider_plan=[("local_http_asr", "qwen3-asr-1.7b-forced-aligner")],
    )

    assert selected_result is good
    assert selected_provider == "local_http_asr"
    assert selected_model == "faster-whisper-large-v3-beam5-nohot"
    assert attempt_errors[0]["error"].startswith("asr_quality_gate:")
    gate = selected_result.raw_payload["_roughcut_asr_quality_gate"]
    assert gate["fallback_selected"] == {
        "provider": "local_http_asr",
        "model": "faster-whisper-large-v3-beam5-nohot",
    }
    assert gate["rejected_attempts"][0]["model"] == "qwen3-asr-1.7b-forced-aligner"


@pytest.mark.asyncio
async def test_low_coverage_local_asr_result_falls_back_to_next_model(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS", "1")
    sparse = _timed_result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        duration=436.8,
        ranges=[
            (1.1, 253.5, "前半段产品介绍"),
            (300.3, 377.8, "后半段手感描述"),
        ],
    )
    good = _timed_result(
        "local_http_asr",
        "faster-whisper-large-v3-beam5-nohot",
        duration=436.8,
        ranges=[(0.5, 430.0, "完整覆盖产品讲解")],
    )
    providers = {
        ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"): _FakeProvider(sparse),
        ("local_http_asr", "faster-whisper-large-v3-beam5-nohot"): _FakeProvider(good),
    }

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del kwargs
        return providers[(provider, model)]

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    selected_result, selected_provider, selected_model, attempt_errors = await execute_transcription_plan(
        audio_path=tmp_path / "audio.wav",
        language="zh-CN",
        prompt=None,
        provider_plan=[
            ("local_http_asr", "qwen3-asr-1.7b-forced-aligner"),
        ],
    )

    assert selected_result is good
    assert selected_provider == "local_http_asr"
    assert selected_model == "faster-whisper-large-v3-beam5-nohot"
    assert "low temporal coverage" in attempt_errors[0]["error"]


@pytest.mark.asyncio
async def test_rejected_qwen3_local_asr_result_is_not_returned(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ROUGHCUT_ASR_ENABLE_NON_QWEN_FALLBACKS", raising=False)
    bad = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "去去防御，你不要把东西掏出来。也就就加一个更字儿，啊啊好。",
    )

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del kwargs
        if provider == "local_http_asr" and model == "qwen3-asr-1.7b-forced-aligner":
            return _FakeProvider(bad)
        return _FakeProvider(RuntimeError(f"{provider}/{model} unavailable"))

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    with pytest.raises(AsrQualityGateError) as exc_info:
        await execute_transcription_plan(
            audio_path=tmp_path / "audio.wav",
            language="zh-CN",
            prompt=None,
            provider_plan=[("local_http_asr", "qwen3-asr-1.7b-forced-aligner")],
        )

    message = str(exc_info.value)
    assert "asr_quality_gate" in message
    assert exc_info.value.payload["status"] == "rejected"
    assert exc_info.value.payload["rejected_attempts"][0]["model"] == "qwen3-asr-1.7b-forced-aligner"
