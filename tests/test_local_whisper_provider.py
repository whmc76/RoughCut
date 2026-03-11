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


def test_local_whisper_reports_segment_progress(monkeypatch):
    progress_updates: list[dict] = []

    class DummySegment:
        def __init__(self, start: float, end: float, text: str) -> None:
            self.start = start
            self.end = end
            self.text = text
            self.words = []

    class DummyModel:
        def transcribe(self, *_args, **_kwargs):
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
