from __future__ import annotations

import sys
import types
from pathlib import Path

from roughcut.providers.transcription.local_whisper import LocalWhisperProvider


def test_local_whisper_prefers_cuda_float16(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class DummyWhisperModel:
        def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
            calls.append((model_size, device, compute_type))

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(get_cuda_device_count=lambda: 1),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=DummyWhisperModel),
    )

    provider = LocalWhisperProvider(model_size="base")
    provider._load_model()

    assert calls == [("base", "cuda", "float16")]


def test_local_whisper_falls_back_to_cpu_int8(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class DummyWhisperModel:
        def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
            calls.append((model_size, device, compute_type))

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(get_cuda_device_count=lambda: 0),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=DummyWhisperModel),
    )

    provider = LocalWhisperProvider(model_size="base")
    provider._load_model()

    assert calls == [("base", "cpu", "int8")]


def test_local_whisper_falls_back_to_cpu_when_cuda_model_load_fails(monkeypatch):
    calls: list[tuple[str, str, str]] = []

    class DummyWhisperModel:
        def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
            calls.append((model_size, device, compute_type))
            if device == "cuda":
                raise RuntimeError("CUDA error: unknown error")

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(get_cuda_device_count=lambda: 1),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=DummyWhisperModel),
    )

    provider = LocalWhisperProvider(model_size="base")
    provider._load_model()

    assert calls == [("base", "cuda", "float16"), ("base", "cpu", "int8")]


def test_local_whisper_retries_on_cpu_when_cuda_transcribe_fails(monkeypatch):
    class DummySegment:
        def __init__(self, start: float, end: float, text: str) -> None:
            self.start = start
            self.end = end
            self.text = text
            self.words = []

    load_calls: list[tuple[str, str, str]] = []

    class DummyWhisperModel:
        def __init__(self, model_size: str, *, device: str, compute_type: str) -> None:
            load_calls.append((model_size, device, compute_type))
            self.device = device

        def transcribe(self, *_args, **_kwargs):
            if self.device == "cuda":
                raise RuntimeError("CUDA error: unknown error")
            return iter([DummySegment(0.0, 1.0, "ok")]), types.SimpleNamespace(duration=1.0)

    monkeypatch.setitem(
        sys.modules,
        "ctranslate2",
        types.SimpleNamespace(get_cuda_device_count=lambda: 1),
    )
    monkeypatch.setitem(
        sys.modules,
        "faster_whisper",
        types.SimpleNamespace(WhisperModel=DummyWhisperModel),
    )

    provider = LocalWhisperProvider(model_size="base")
    result = provider._transcribe_sync(Path("dummy.wav"), "zh")

    assert load_calls == [("base", "cuda", "float16"), ("base", "cpu", "int8")]
    assert len(result.segments) == 1
    assert result.segments[0].text == "ok"


def test_local_whisper_reports_segment_progress(monkeypatch):
    progress_updates: list[dict] = []
    transcribe_kwargs: dict = {}

    class DummySegment:
        def __init__(self, start: float, end: float, text: str) -> None:
            self.start = start
            self.end = end
            self.text = text
            self.words = []

    class DummyModel:
        def transcribe(self, *_args, **_kwargs):
            transcribe_kwargs.update(_kwargs)
            return iter(
                [
                    DummySegment(0.0, 3.0, "hello"),
                    DummySegment(3.0, 10.0, "world"),
                ]
            ), types.SimpleNamespace(duration=10.0)

    provider = LocalWhisperProvider(model_size="base")
    provider._model = DummyModel()

    result = provider._transcribe_sync(
        Path("dummy.wav"),
        "zh",
        progress_callback=lambda payload: progress_updates.append(payload),
    )

    assert len(result.segments) == 2
    assert progress_updates[0]["segment_count"] == 1
    assert progress_updates[0]["progress"] == 0.3
    assert progress_updates[-1]["segment_count"] == 2
    assert progress_updates[-1]["progress"] == 1.0
    assert transcribe_kwargs["beam_size"] == 6
    assert transcribe_kwargs["best_of"] == 6
    assert transcribe_kwargs["condition_on_previous_text"] is False
    assert transcribe_kwargs["vad_filter"] is True
    assert transcribe_kwargs["hallucination_silence_threshold"] == 1.0
    assert transcribe_kwargs["vad_parameters"]["min_silence_duration_ms"] == 300


def test_local_whisper_uses_hotwords_from_prompt_when_supported():
    transcribe_kwargs: dict = {}

    class DummyModel:
        def transcribe(self, *_args, **_kwargs):
            transcribe_kwargs.update(_kwargs)
            return iter([]), types.SimpleNamespace(duration=0.0)

    provider = LocalWhisperProvider(model_size="base")
    provider._model = DummyModel()

    provider._transcribe_sync(
        Path("dummy.wav"),
        "zh",
        prompt="热词：NOC, REATE, 顶配。请保持品牌、型号、圈内术语原词。",
    )

    assert transcribe_kwargs["hotwords"] == "NOC,REATE,顶配"
    assert transcribe_kwargs["beam_size"] == 6
    assert transcribe_kwargs["best_of"] == 6
    assert transcribe_kwargs["temperature"] == 0.0
    assert transcribe_kwargs["no_speech_threshold"] == 0.45


def test_local_whisper_retries_without_hotwords_when_unsupported():
    calls: list[dict] = []

    class DummyModel:
        def transcribe(self, *_args, **_kwargs):
            calls.append(dict(_kwargs))
            if "hotwords" in _kwargs:
                raise TypeError("unexpected keyword argument 'hotwords'")
            return iter([]), types.SimpleNamespace(duration=0.0)

    provider = LocalWhisperProvider(model_size="base")
    provider._model = DummyModel()

    provider._transcribe_sync(
        Path("dummy.wav"),
        "zh",
        prompt="热词：NOC, REATE, 顶配。",
    )

    assert len(calls) == 2
    assert "hotwords" in calls[0]
    assert "hotwords" not in calls[1]


def test_local_whisper_detects_unstable_repetition():
    assert LocalWhisperProvider._segment_looks_unstable("也算一个，也算一个，也算一个，也算一个", 12.0) is True
    assert LocalWhisperProvider._segment_looks_unstable("这把 NOC MT-33 先看钢马和镜面板细节", 6.0) is False


def test_local_whisper_builds_chunk_ranges_for_rescue():
    ranges = LocalWhisperProvider._build_chunk_ranges(0.0, 19.5)
    assert ranges == [(0.0, 8.0), (8.0, 16.0), (16.0, 19.5)]
