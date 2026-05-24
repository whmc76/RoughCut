from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from roughcut.providers.transcription.chunking import (
    AudioChunkConfig,
    AudioChunkSpec,
    build_audio_chunk_specs,
    extract_chunking_summary,
    resolve_audio_chunk_config,
    should_chunk_audio,
)
from roughcut.providers.transcription.base import TranscriptResult, TranscriptSegment
from roughcut.providers.transcription.local_http_asr import LocalHTTPASRProvider


def test_build_audio_chunk_specs_for_long_audio() -> None:
    config = AudioChunkConfig(
        enabled=True,
        threshold_sec=120.0,
        chunk_size_sec=60.0,
        min_chunk_sec=20.0,
        overlap_sec=1.5,
        request_timeout_sec=180.0,
        request_max_retries=2,
        request_retry_backoff_sec=5.0,
        export_timeout_sec=180.0,
    )

    chunks = build_audio_chunk_specs(185.0, config=config)

    assert [(chunk.start, chunk.end) for chunk in chunks[:3]] == [
        (0.0, 60.0),
        (58.5, 118.5),
        (117.0, 185.0),
    ]
    assert chunks[-1].end == 185.0


@pytest.mark.asyncio
async def test_transcribe_long_audio_in_chunks_offsets_segments_and_reports_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = LocalHTTPASRProvider()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    chunk_config = AudioChunkConfig(
        enabled=True,
        threshold_sec=10.0,
        chunk_size_sec=100.0,
        min_chunk_sec=20.0,
        overlap_sec=0.0,
        request_timeout_sec=180.0,
        request_max_retries=2,
        request_retry_backoff_sec=5.0,
        export_timeout_sec=180.0,
    )

    monkeypatch.setattr(
        "roughcut.providers.transcription.local_http_asr.build_audio_chunk_specs",
        lambda duration, config: [
            AudioChunkSpec(index=0, count=2, start=0.0, end=100.0),
            AudioChunkSpec(index=1, count=2, start=100.0, end=200.0),
        ],
    )

    def _export_audio_chunk(_: Path, chunk_path: Path, *, start: float, end: float, timeout_sec: float | None = None) -> None:
        chunk_path.write_bytes(f"{start}-{end}".encode("utf-8"))

    async def _post_transcribe_request(chunk_path: Path, *, context: str | None, max_new_tokens: int, timeout):
        return {
            "duration": 100.0,
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text": chunk_path.read_bytes().decode("utf-8"),
                }
            ],
        }

    monkeypatch.setattr("roughcut.providers.transcription.local_http_asr.export_audio_chunk", _export_audio_chunk)
    monkeypatch.setattr(provider, "_post_transcribe_request", _post_transcribe_request)

    progress_events: list[dict] = []
    result = await provider._transcribe_long_audio_in_chunks(
        audio_path,
        language="zh-CN",
        context="",
        total_duration=200.0,
        max_new_tokens=4096,
        chunk_config=chunk_config,
        progress_callback=progress_events.append,
    )

    assert [segment.start for segment in result.segments] == [0.0, 100.0]
    assert [segment.end for segment in result.segments] == [5.0, 105.0]
    assert [segment.text for segment in result.segments] == ["0.0-100.0", "100.0-200.0"]
    assert result.raw_payload["chunking"]["chunk_count"] == 2
    assert result.raw_payload["chunking"]["chunk_size_sec"] == 100.0
    assert result.raw_payload["chunking"]["request_max_retries"] == 2
    assert progress_events[-1]["progress"] == 1.0
    assert progress_events[-1]["segment_end"] == 200.0
    assert progress_events[-1]["chunk_index"] == 2
    assert progress_events[-1]["chunk_count"] == 2
    assert {event["phase"] for event in progress_events} >= {"export", "request", "complete"}


@pytest.mark.asyncio
async def test_transcribe_long_audio_in_chunks_drops_repeated_chunk_decode_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "qwen3-asr-1.7b-forced-aligner"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    chunk_config = AudioChunkConfig(
        enabled=True,
        threshold_sec=10.0,
        chunk_size_sec=20.0,
        min_chunk_sec=8.0,
        overlap_sec=0.0,
        request_timeout_sec=180.0,
        request_max_retries=2,
        request_retry_backoff_sec=5.0,
        export_timeout_sec=180.0,
    )
    repeated_sentence = "之前都是那个人先开的，它的这个结合金版本确实还挺帅的完全不差。"

    monkeypatch.setattr(
        "roughcut.providers.transcription.local_http_asr.build_audio_chunk_specs",
        lambda duration, config: [
            AudioChunkSpec(index=0, count=2, start=0.0, end=20.0),
            AudioChunkSpec(index=1, count=2, start=20.0, end=40.0),
        ],
    )

    def _export_audio_chunk(_: Path, chunk_path: Path, *, start: float, end: float, timeout_sec: float | None = None) -> None:
        chunk_path.write_bytes(f"{start}-{end}".encode("utf-8"))

    async def _post_transcribe_request(chunk_path: Path, *, context: str | None, max_new_tokens: int, timeout):
        return {
            "duration": 20.0,
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": 12.0,
                    "text": repeated_sentence,
                }
            ],
        }

    monkeypatch.setattr("roughcut.providers.transcription.local_http_asr.export_audio_chunk", _export_audio_chunk)
    monkeypatch.setattr(provider, "_post_transcribe_request", _post_transcribe_request)

    result = await provider._transcribe_long_audio_in_chunks(
        audio_path,
        language="zh-CN",
        context="",
        total_duration=40.0,
        max_new_tokens=4096,
        chunk_config=chunk_config,
        progress_callback=None,
    )

    assert "".join(segment.text for segment in result.segments) == repeated_sentence
    assert result.segments[0].start == 0.0
    assert result.segments[-1].end == 20.0
    filtering = result.segments[0].raw_payload["_roughcut_filtering"]
    assert filtering["dropped_decode_loop_segment_sequences"]["dropped_count"] == 2
    assert filtering["dropped_decode_loop_segment_sequences"]["dropped_start"] == 20.0


def test_extract_chunking_summary() -> None:
    summary = extract_chunking_summary(
        {
            "chunking": {
                "enabled": True,
                "threshold_sec": 600.0,
                "chunk_size_sec": 60.0,
                "min_chunk_sec": 20.0,
                "overlap_sec": 1.5,
                "request_timeout_sec": 180.0,
                "request_max_retries": 2,
                "request_retry_backoff_sec": 5.0,
                "export_timeout_sec": 180.0,
                "chunk_count": 12,
                "duration_sec": 1717.6,
            }
        }
    )

    assert summary == {
        "enabled": True,
        "threshold_sec": 600.0,
        "chunk_size_sec": 60.0,
        "min_chunk_sec": 20.0,
        "overlap_sec": 1.5,
        "request_timeout_sec": 180.0,
        "request_max_retries": 2,
        "request_retry_backoff_sec": 5.0,
        "export_timeout_sec": 180.0,
        "chunk_count": 12,
        "duration_sec": 1717.6,
    }


def test_resolve_audio_chunk_config_clamps_invalid_relationships() -> None:
    config = resolve_audio_chunk_config(
        SimpleNamespace(
            transcription_chunking_enabled=True,
            transcription_chunk_threshold_sec=120,
            transcription_chunk_size_sec=30,
            transcription_chunk_min_sec=45,
            transcription_chunk_overlap_sec=40,
            transcription_chunk_request_timeout_sec=20,
            transcription_chunk_request_max_retries=3,
            transcription_chunk_request_retry_backoff_sec=0.25,
            ffmpeg_timeout_sec=90,
        )
    )

    assert config.chunk_size_sec == 30.0
    assert config.min_chunk_sec == 30.0
    assert config.overlap_sec == 0.0
    assert config.request_timeout_sec == 30.0
    assert config.request_max_retries == 3
    assert config.request_retry_backoff_sec == 0.5
    assert config.export_timeout_sec == 30.0


def test_default_chunk_threshold_covers_medium_local_asr_audio() -> None:
    config = resolve_audio_chunk_config(SimpleNamespace())

    assert config.threshold_sec == 300.0
    assert config.chunk_size_sec == 300.0
    assert config.min_chunk_sec == 60.0
    assert config.overlap_sec == 0.0
    assert should_chunk_audio(duration=453.6, config=config)
    assert should_chunk_audio(duration=511.2, config=config)
    assert not should_chunk_audio(duration=113.5, config=config)
    assert not should_chunk_audio(duration=299.5, config=config)


def test_qwen3_local_http_asr_caps_transformers_token_budget() -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "qwen3-asr-1.7b-forced-aligner"

    assert provider._resolve_max_new_tokens(SimpleNamespace(local_asr_max_new_tokens=2048), audio_duration=20.0) == 256
    assert provider._resolve_max_new_tokens(SimpleNamespace(local_asr_max_new_tokens=128), audio_duration=20.0) == 128


def test_local_http_asr_collapses_repeated_decoder_loop_text_before_splitting(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "qwen3-asr-1.7b-forced-aligner"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    sentence = "啊，刚才我发现那个盒子放底下有点黑啊，看不清它的这个全貌。"
    payload = {
        "duration": 10.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 10.0,
                "text": sentence * 20,
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    assert len(result.segments) == 1
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 10.0
    assert result.segments[0].text == sentence
    filtering = result.raw_segments[0].raw_payload["_roughcut_filtering"]
    assert filtering["collapsed_decode_loop_text"]["text"] == sentence


def test_local_http_asr_collapses_repeated_decoder_loop_text_without_terminal_punctuation(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "qwen3-asr-1.7b-forced-aligner"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    sentence = "啊，刚才我发现那个盒子放底下有点黑啊，看不清它的这个全貌"
    payload = {
        "duration": 10.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 10.0,
                "text": sentence * 20,
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    assert [segment.text for segment in result.segments] == [sentence]


def test_local_http_asr_collapses_qwen3_short_duplicate_noise_but_keeps_real_repeats(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "qwen3-asr-1.7b-forced-aligner"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    payload = {
        "duration": 10.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 10.0,
                "text": "啊啊！不过好在呢，还还算抢到了啊，没没有没有这个像很多兄弟一样隐恨啊，我最近这这三次三次NOC的这个发售啊。",
                "words": [
                    {"text": "啊", "start": 0.0, "end": 0.1},
                    {"text": "啊", "start": 0.1, "end": 0.2},
                    {"text": "还", "start": 1.0, "end": 1.1},
                    {"text": "还", "start": 1.1, "end": 1.2},
                    {"text": "没", "start": 2.0, "end": 2.1},
                    {"text": "没有", "start": 2.1, "end": 2.3},
                    {"text": "没有", "start": 2.3, "end": 2.5},
                    {"text": "这", "start": 3.0, "end": 3.1},
                    {"text": "这", "start": 3.1, "end": 3.2},
                    {"text": "三次", "start": 3.2, "end": 3.4},
                    {"text": "三次", "start": 3.4, "end": 3.6},
                ],
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    segment = result.segments[0]
    assert "啊啊" not in segment.text
    assert "还还" not in segment.text
    assert "没没有没有" not in segment.text
    assert "这这三次三次" in segment.text
    assert [word.word for word in segment.words] == ["啊", "还", "没有", "这", "这", "三次", "三次"]
    assert segment.words[2].start == 2.0
    filtering = segment.raw_payload["_roughcut_filtering"]["collapsed_short_duplicate_noise"]
    assert filtering["dropped_word_count"] == 4


def test_local_http_asr_applies_short_duplicate_noise_to_funasr_nano(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "FunAudioLLM/Fun-ASR-Nano-2512"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    payload = {
        "duration": 2.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 2.0,
                "text": "啊啊，不过好在呢，还还算抢到了啊，没没有没有这个。",
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    assert result.segments[0].text == "啊，不过好在呢，还算抢到了啊，没有这个。"


def test_local_http_asr_keeps_short_duplicate_noise_for_other_models(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    provider._model_name = "faster-whisper-large-v3-beam5-nohot"
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    payload = {
        "duration": 2.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 2.0,
                "text": "啊啊，还还，没没有没有。",
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    assert result.segments[0].text == "啊啊，还还，没没有没有。"


def test_local_http_asr_preserves_provider_word_timestamps(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    payload = {
        "duration": 1.0,
        "segments": [
            {
                "start_time": 0.1,
                "end_time": 0.8,
                "text": "天敌",
                "words": [
                    {"text": "天", "start": 0.1, "end": 0.4},
                    {"text": "敌", "start": 0.4, "end": 0.8},
                ],
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="天敌",
        progress_callback=None,
    )

    assert result.segments[0].text == "天敌"
    assert [(word.word, word.start, word.end) for word in result.segments[0].words] == [
        ("天", 0.1, 0.4),
        ("敌", 0.4, 0.8),
    ]


def test_local_http_asr_does_not_split_provider_aligned_long_segment(tmp_path: Path) -> None:
    provider = LocalHTTPASRProvider()
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    text = "这是一个已经带有逐字时间戳的长段落，后处理不应该把原始对齐信息丢掉。"
    payload = {
        "duration": 8.0,
        "segments": [
            {
                "start_time": 0.0,
                "end_time": 8.0,
                "text": text,
                "words": [
                    {"text": char, "start": index * 0.1, "end": index * 0.1 + 0.08}
                    for index, char in enumerate(text)
                ],
            }
        ],
    }

    result = provider._build_result_from_payload(
        payload,
        audio_path=audio_path,
        language="zh-CN",
        context="",
        progress_callback=None,
    )

    assert len(result.segments) == 1
    assert result.segments[0].text == text
    assert len(result.segments[0].words) == len(text)


def test_local_http_asr_collapses_repeated_decoder_loop_segments() -> None:
    provider = LocalHTTPASRProvider()
    sentence = "啊，刚才我发现那个盒子放底下有点黑啊，看不清它的这个全貌。"
    segments = [
        TranscriptSegment(
            index=index,
            start=index * 0.5,
            end=(index + 1) * 0.5,
            text=sentence,
            provider="local_http_asr",
        )
        for index in range(20)
    ]

    sanitized = provider._sanitize_decode_loop_segments(segments)

    assert len(sanitized) == 1
    assert sanitized[0].start == 0.0
    assert sanitized[0].end == 10.0
    assert sanitized[0].text == sentence
    filtering = sanitized[0].raw_payload["_roughcut_filtering"]
    assert filtering["collapsed_decode_loop_segments"]["repeat_count"] == 20


@pytest.mark.asyncio
async def test_post_chunk_transcribe_request_retries_and_reports_wait(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = LocalHTTPASRProvider()
    chunk_path = tmp_path / "chunk.wav"
    chunk_path.write_bytes(b"stub")
    chunk = AudioChunkSpec(index=0, count=1, start=0.0, end=60.0)
    chunk_config = AudioChunkConfig(
        enabled=True,
        threshold_sec=10.0,
        chunk_size_sec=60.0,
        min_chunk_sec=20.0,
        overlap_sec=0.0,
        request_timeout_sec=180.0,
        request_max_retries=2,
        request_retry_backoff_sec=0.5,
        export_timeout_sec=60.0,
    )
    attempts = {"count": 0}

    async def _post_transcribe_request(chunk_path: Path, *, context: str | None, max_new_tokens: int, timeout):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("timed out")
        return {
            "duration": 60.0,
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text": "ok",
                }
            ],
        }

    async def _sleep(_: float) -> None:
        return None

    monkeypatch.setattr(provider, "_post_transcribe_request", _post_transcribe_request)
    monkeypatch.setattr("roughcut.providers.transcription.local_http_asr.asyncio.sleep", _sleep)
    progress_events: list[dict] = []

    payload = await provider._post_chunk_transcribe_request(
        chunk_path=chunk_path,
        chunk=chunk,
        context="",
        max_new_tokens=4096,
        timeout=httpx.Timeout(180.0, connect=30.0),
        chunk_config=chunk_config,
        covered_until=0.0,
        total_duration=60.0,
        segment_count=0,
        latest_text="",
        progress_callback=progress_events.append,
    )

    assert payload["segments"][0]["text"] == "ok"
    assert attempts["count"] == 2
    assert [event["phase"] for event in progress_events] == ["request", "retry_wait", "request"]


@pytest.mark.asyncio
async def test_transcribe_uses_extracted_hotwords_as_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = LocalHTTPASRProvider()
    provider._hotwords_enabled = True
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")
    captured: dict[str, str | None] = {}

    async def _transcribe_single_audio(
        audio_path: Path,
        *,
        language: str,
        context: str | None,
        max_new_tokens: int,
        progress_callback,
    ) -> TranscriptResult:
        captured["context"] = context
        return TranscriptResult(segments=[], language=language, duration=0.0, context=context, hotword=context)

    monkeypatch.setattr(provider, "_transcribe_single_audio", _transcribe_single_audio)
    monkeypatch.setattr(
        "roughcut.providers.transcription.local_http_asr.probe_audio_duration",
        lambda _path: 1.0,
    )
    monkeypatch.setattr(
        "roughcut.providers.transcription.local_http_asr.should_chunk_audio",
        lambda duration, config: False,
    )

    await provider.transcribe(
        audio_path,
        prompt="热词：OLIGHT, 掠夺者2 mini。请保持品牌、型号和圈内术语原词。源文件名参考：傲雷.mp4",
    )

    assert captured["context"] == "OLIGHT, 掠夺者2 mini"


@pytest.mark.asyncio
async def test_transcribe_single_audio_reports_request_progress(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    provider = LocalHTTPASRProvider()
    provider._hotwords_enabled = True
    audio_path = tmp_path / "audio.wav"
    audio_path.write_bytes(b"stub")

    async def _post_transcribe_request(audio_path: Path, *, context: str | None, max_new_tokens: int, timeout):
        return {
            "duration": 42.0,
            "segments": [
                {
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "text": "ok",
                }
            ],
        }

    monkeypatch.setattr(provider, "_post_transcribe_request", _post_transcribe_request)
    monkeypatch.setattr(
        "roughcut.providers.transcription.local_http_asr.probe_audio_duration",
        lambda _path: 42.0,
    )
    progress_events: list[dict] = []

    result = await provider._transcribe_single_audio(
        audio_path,
        language="zh-CN",
        context="",
        max_new_tokens=4096,
        progress_callback=progress_events.append,
    )

    assert result.segments[0].text == "ok"
    assert progress_events[0]["phase"] == "request"
    assert progress_events[0]["total_duration"] == 42.0
