from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.providers.ocr.base import OCRFrameResult, OCRLine, OCRResult


@pytest.mark.asyncio
async def test_infer_content_profile_collects_dedicated_ocr_profile(monkeypatch, tmp_path: Path):
    import roughcut.review.content_profile as content_profile_mod

    source_path = tmp_path / "source.mp4"
    frame_path = tmp_path / "frame-001.png"
    source_path.write_bytes(b"video")
    frame_path.write_bytes(b"frame")

    monkeypatch.setattr(content_profile_mod, "get_settings", lambda: SimpleNamespace(ocr_enabled=True))
    monkeypatch.setattr(content_profile_mod, "_extract_reference_frames", lambda *_args, **_kwargs: [frame_path])
    monkeypatch.setattr(content_profile_mod, "_infer_visual_profile_hints", lambda *_args, **_kwargs: {})

    class DummyOCRProvider:
        async def recognize_frames(self, frame_paths, *, language: str = "zh-CN"):
            assert frame_paths == [frame_path]
            return OCRResult(
                provider="paddleocr",
                available=True,
                status="ok",
                frames=[
                    OCRFrameResult(
                        frame_index=0,
                        timestamp=0.0,
                        frame_path=str(frame_path),
                        lines=[OCRLine(text="OLIGHT Baton 4", confidence=0.97, box=(1.0, 2.0, 3.0, 4.0))],
                    )
                ],
            )

    async def fake_complete_with_images(*_args, **_kwargs):
        return (
            '{"subject_brand":"","subject_model":"","subject_type":"","content_kind":"","subject_domain":"",'
            '"video_theme":"","hook_line":"","visible_text":"","engagement_question":"","search_queries":[]}'
        )

    async def fake_enrich_content_profile(**kwargs):
        return kwargs["profile"]

    monkeypatch.setattr(content_profile_mod, "get_ocr_provider", lambda **_kwargs: DummyOCRProvider())
    monkeypatch.setattr(content_profile_mod, "complete_with_images", fake_complete_with_images)
    monkeypatch.setattr(content_profile_mod, "enrich_content_profile", fake_enrich_content_profile)

    result = await content_profile_mod.infer_content_profile(
        source_path=source_path,
        source_name="demo.mp4",
        subtitle_items=[],
        workflow_template="unboxing_standard",
        user_memory={},
        glossary_terms=[],
        include_research=False,
    )

    assert result["ocr_profile"]["available"] is True
    assert result["ocr_profile"]["raw_snippets"][0]["text"] == "OLIGHT Baton 4"
    assert result["ocr_profile"]["visible_text"] == "OLIGHT Baton 4"
