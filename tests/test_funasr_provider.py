from __future__ import annotations

import sys
import types
from pathlib import Path

from roughcut.providers.transcription.funasr_provider import FunASRProvider


def test_funasr_builds_hotword_generate_kwargs():
    provider = FunASRProvider(model_name="sensevoice-small")

    kwargs = provider._build_generate_kwargs(
        lang_code="zh",
        prompt="热词：NOC, REATE, 顶配。请保持品牌原词。",
    )

    assert kwargs["language"] == "zh"
    assert kwargs["hotword"] == "NOC REATE 顶配"
    assert kwargs["merge_vad"] is True
    assert kwargs["merge_length_s"] == 15


def test_funasr_transcribe_parses_sentence_info(monkeypatch):
    created: list[dict[str, object]] = []

    class DummyModel:
        def generate(self, *_args, **_kwargs):
            return [
                {
                    "sentence_info": [
                        {"text": "<|zh|>先看 NOC。", "start": 0, "end": 1200},
                        {"text": "<|zh|>再看 REATE。", "timestamp": [[1300, 1800], [1850, 2400]]},
                    ]
                }
            ]

    class DummyAutoModel:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)

        def generate(self, *args, **kwargs):
            return DummyModel().generate(*args, **kwargs)

    def fake_postprocess(text: str) -> str:
        return text.replace("<|zh|>", "").strip()

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=DummyAutoModel))
    monkeypatch.setitem(
        sys.modules,
        "funasr.utils.postprocess_utils",
        types.SimpleNamespace(rich_transcription_postprocess=fake_postprocess),
    )

    provider = FunASRProvider(model_name="sensevoice-small")
    result = provider._transcribe_sync(Path("dummy.wav"), "zh", prompt="热词：NOC, REATE。")

    assert created[0]["model"] == "iic/SenseVoiceSmall"
    assert len(result.segments) == 2
    assert result.segments[0].text == "先看 NOC。"
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 1.2
    assert result.segments[1].text == "再看 REATE。"
    assert result.segments[1].start == 1.3
    assert result.segments[1].end == 2.4

