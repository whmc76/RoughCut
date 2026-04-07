from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from roughcut.providers.ocr.base import OCRFrameResult, OCRLine
from roughcut.review.content_profile_ocr import build_content_profile_ocr


@pytest.mark.asyncio
async def test_paddleocr_provider_gracefully_degrades_without_dependency(monkeypatch):
    import roughcut.providers.ocr.paddleocr_provider as provider_mod

    monkeypatch.setattr(provider_mod.importlib.util, "find_spec", lambda _name: None)

    provider = provider_mod.PaddleOCRProvider()
    result = await provider.recognize_frames([Path("frame-001.png")])

    assert result.available is False
    assert result.frames == []
    assert result.status == "unavailable"
    assert "paddleocr" in result.reason.lower()


def test_content_profile_ocr_aggregation_preserves_raw_snippets_and_normalized_candidates():
    frames = [
        OCRFrameResult(
            frame_index=0,
            timestamp=0.0,
            lines=[
                OCRLine(
                    text="大疆 DJI Mini 4 Pro",
                    confidence=0.96,
                    box=(12.0, 34.0, 210.0, 78.0),
                )
            ],
        ),
        OCRFrameResult(
            frame_index=1,
            timestamp=1.5,
            lines=[
                OCRLine(
                    text="DJI Mini 4 Pro",
                    confidence=0.91,
                    box=(16.0, 36.0, 208.0, 76.0),
                )
            ],
        ),
    ]

    profile = build_content_profile_ocr(frames, source_name="demo.mp4")

    assert profile["frame_count"] == 2
    assert profile["raw_snippets"]
    assert profile["raw_snippets"][0]["text"] == "大疆 DJI Mini 4 Pro"
    assert profile["raw_snippets"][0]["box"] == [12.0, 34.0, 210.0, 78.0]
    assert any(
        candidate["normalized_text"] == "dji mini 4 pro"
        and candidate["raw_texts"] == ["DJI Mini 4 Pro"]
        for candidate in profile["normalized_subject_candidates"]
    )


def test_content_profile_ocr_filters_filename_like_and_timestamp_lines():
    frames = [
        OCRFrameResult(
            frame_index=0,
            timestamp=0.0,
            lines=[
                OCRLine(
                    text="IMG_0041.MOV",
                    confidence=0.98,
                    box=(10.0, 20.0, 100.0, 40.0),
                ),
                OCRLine(
                    text="[1.8-2.3] 开箱",
                    confidence=0.97,
                    box=(12.0, 18.0, 110.0, 52.0),
                ),
            ],
        ),
        OCRFrameResult(
            frame_index=1,
            timestamp=1.0,
            lines=[
                OCRLine(
                    text="赫斯俊 船长 联名机能双肩包",
                    confidence=0.95,
                    box=(14.0, 22.0, 220.0, 52.0),
                ),
            ],
        ),
    ]

    profile = build_content_profile_ocr(frames, source_name="IMG_0041.MOV")

    assert "IMG_0041.MOV" not in profile["visible_text"]
    assert "[1.8-2.3] 开箱" not in profile["visible_text"]
    assert "赫斯俊 船长 联名机能双肩包" in profile["visible_text"]
    assert all("IMG_0041" not in snippet["text"] for snippet in profile["raw_snippets"])
    assert all("[" not in snippet["text"] for snippet in profile["raw_snippets"])


def test_content_profile_ocr_prefers_stable_lines_in_visible_text():
    frames = [
        OCRFrameResult(
            frame_index=0,
            timestamp=0.0,
            lines=[
                OCRLine(
                    text="机能双肩包",
                    confidence=0.95,
                    box=(12.0, 34.0, 210.0, 78.0),
                ),
                OCRLine(
                    text="噪音",
                    confidence=0.51,
                    box=(14.0, 36.0, 78.0, 50.0),
                ),
            ],
        ),
        OCRFrameResult(
            frame_index=1,
            timestamp=1.5,
            lines=[
                OCRLine(
                    text="机能双肩包",
                    confidence=0.94,
                    box=(15.0, 36.0, 208.0, 74.0),
                ),
                OCRLine(
                    text="干扰文本",
                    confidence=0.35,
                    box=(17.0, 46.0, 102.0, 58.0),
                ),
            ],
        ),
    ]

    profile = build_content_profile_ocr(frames, source_name="video.mp4")

    assert profile["visible_text"] == "机能双肩包"


def test_get_ocr_provider_uses_paddleocr_entrypoint(monkeypatch):
    import roughcut.providers.factory as factory_mod

    factory_mod._OCR_PROVIDER_CACHE.clear()

    class DummyProvider:
        def __init__(self, *, available: bool = True) -> None:
            self.available = available

    monkeypatch.setattr(factory_mod, "get_settings", lambda: object())
    monkeypatch.setitem(
        sys.modules,
        "roughcut.providers.ocr.paddleocr_provider",
        types.SimpleNamespace(PaddleOCRProvider=DummyProvider),
    )

    first = factory_mod.get_ocr_provider()
    second = factory_mod.get_ocr_provider()

    assert first is second
    assert isinstance(first, DummyProvider)
