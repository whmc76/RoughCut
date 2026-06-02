from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.speech.transcribe import analyze_transcript_asr_quality, execute_transcription_plan


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


@pytest.mark.asyncio
async def test_rejected_qwen3_local_asr_result_is_not_returned(monkeypatch, tmp_path: Path) -> None:
    bad = _result(
        "local_http_asr",
        "qwen3-asr-1.7b-forced-aligner",
        "去去防御，你不要把东西掏出来。也就就加一个更字儿，啊啊好。",
    )

    def fake_get_transcription_provider(*, provider: str, model: str, **kwargs) -> _FakeProvider:
        del kwargs
        if provider == "local_http_asr":
            return _FakeProvider(bad)
        return _FakeProvider(RuntimeError(f"{provider}/{model} unavailable"))

    monkeypatch.setattr("roughcut.speech.transcribe.get_transcription_provider", fake_get_transcription_provider)

    with pytest.raises(RuntimeError) as exc_info:
        await execute_transcription_plan(
            audio_path=tmp_path / "audio.wav",
            language="zh-CN",
            prompt=None,
            provider_plan=[("local_http_asr", "qwen3-asr-1.7b-forced-aligner")],
        )

    message = str(exc_info.value)
    assert "asr_quality_gate" in message
