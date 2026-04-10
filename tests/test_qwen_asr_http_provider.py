from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from roughcut.providers.transcription.qwen_asr_http import QwenASRHTTPProvider


@pytest.mark.asyncio
async def test_qwen_asr_http_provider_parses_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake-audio")

    captured: dict[str, object] = {}

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def post(self, url: str, *, files, data):
            captured["url"] = url
            captured["data"] = data
            captured["filename"] = files["file"][0]
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "provider": "qwen3-asr",
                    "model": "Qwen/Qwen3-ASR-1.7B",
                    "language": "Chinese",
                    "duration": 12.5,
                    "segments": [
                        {
                            "start": 0.0,
                            "end": 3.0,
                            "text": "第一句",
                            "alignment": {"type": "forced"},
                            "words": [
                                {"word": "第一", "start": 0.0, "end": 0.8, "confidence": 0.98},
                                {"word": "句", "start": 0.8, "end": 1.2, "alignment": {"phone": "ju4"}},
                            ],
                        },
                        {"start": 3.0, "end": 12.5, "text": "第二句"},
                    ],
                },
            )

    monkeypatch.setattr("roughcut.providers.transcription.qwen_asr_http.httpx.AsyncClient", DummyClient)

    provider = QwenASRHTTPProvider(model_name="qwen3-asr-1.7b")
    progress: list[dict[str, object]] = []
    result = await provider.transcribe(
        audio_path,
        language="zh-CN",
        prompt="热词：MT33",
        progress_callback=progress.append,
    )

    assert captured["url"] == "http://127.0.0.1:18096/transcribe"
    assert captured["data"] == {"language": "zh-CN", "prompt": "热词：MT33"}
    assert captured["filename"] == "sample.wav"
    assert result.language == "Chinese"
    assert result.duration == 12.5
    assert [segment.text for segment in result.segments] == ["第一句", "第二句"]
    assert [word.word for word in result.segments[0].words] == ["第一", "句"]
    assert result.segments[0].words[0].confidence == 0.98
    assert result.segments[0].words[1].alignment == {"phone": "ju4"}
    assert result.segments[0].alignment == {"type": "forced"}
    assert progress[-1]["progress"] == 1.0


@pytest.mark.asyncio
async def test_qwen_asr_http_provider_splits_single_long_segment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"fake-audio")

    long_text = (
        "好，这期在室内给大家单独看一下啊，这两个MT33啊，就是光线会更加的精准一点。"
        "其实也算一期鉴赏啊。首先还是这个次顶配镜面版啊。"
        "包括它上面这个钢码和这个锆码的反光。"
    )

    class DummyClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        async def post(self, url: str, *, files, data):
            del files, data
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "provider": "qwen3-asr",
                    "model": "Qwen/Qwen3-ASR-1.7B",
                    "language": "Chinese",
                    "duration": 18.0,
                    "segments": [
                        {"start": 0.0, "end": 18.0, "text": long_text},
                    ],
                },
            )

    monkeypatch.setattr("roughcut.providers.transcription.qwen_asr_http.httpx.AsyncClient", DummyClient)

    provider = QwenASRHTTPProvider(model_name="qwen3-asr-1.7b")
    result = await provider.transcribe(audio_path, language="zh-CN")

    assert len(result.segments) >= 3
    assert result.segments[0].start == 0.0
    assert result.segments[-1].end == 18.0
    assert all(segment.text for segment in result.segments)
