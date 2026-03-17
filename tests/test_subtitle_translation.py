from __future__ import annotations

import pytest

from roughcut.providers.reasoning.base import ReasoningResponse
from roughcut.review.subtitle_translation import (
    detect_subtitle_language,
    languages_equivalent,
    resolve_translation_target_language,
    translate_subtitle_items,
)


@pytest.mark.asyncio
async def test_translate_subtitle_items_recovers_missing_lines_with_single_fallback(monkeypatch: pytest.MonkeyPatch):
    import roughcut.review.subtitle_translation as translation_mod

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, messages, *, temperature=0.3, max_tokens=4096, json_mode=False):
            self.calls += 1
            if self.calls == 1:
                return ReasoningResponse(
                    content='{"items":[{"index":0,"translated_text":"First line."}]}',
                    usage={},
                    model="fake",
                )
            return ReasoningResponse(
                content='{"translation":"Second line."}',
                usage={},
                model="fake",
            )

    monkeypatch.setattr(translation_mod, "get_reasoning_provider", lambda: FakeProvider())

    result = await translate_subtitle_items(
        [
            {"index": 0, "start_time": 0.0, "end_time": 1.0, "text_final": "第一句"},
            {"index": 1, "start_time": 1.0, "end_time": 2.0, "text_final": "第二句"},
        ],
        target_language="en",
    )

    assert result["target_language"] == "en"
    assert result["item_count"] == 2
    assert result["items"][0]["text_translated"] == "First line."
    assert result["items"][1]["text_translated"] == "Second line."


def test_detect_subtitle_language_prefers_chinese_for_cjk_dominant_text():
    language = detect_subtitle_language(
        [
            {"text_final": "这是中文句子。"},
            {"text_final": "第二句也还是中文。"},
        ]
    )

    assert language == "zh-CN"


def test_resolve_translation_target_language_auto_flips_with_chinese_ui():
    assert (
        resolve_translation_target_language(
            source_language="zh-CN",
            target_language=None,
            target_language_mode="auto",
            preferred_ui_language="zh-CN",
        )
        == "en"
    )
    assert (
        resolve_translation_target_language(
            source_language="en-US",
            target_language=None,
            target_language_mode="auto",
            preferred_ui_language="zh-CN",
        )
        == "zh-CN"
    )


def test_resolve_translation_target_language_auto_uses_system_language_as_anchor():
    assert (
        resolve_translation_target_language(
            source_language="ja-JP",
            target_language=None,
            target_language_mode="auto",
            preferred_ui_language="en-US",
        )
        == "en-US"
    )
    assert (
        resolve_translation_target_language(
            source_language="en-US",
            target_language=None,
            target_language_mode="auto",
            preferred_ui_language="en-US",
        )
        == "en"
    )


def test_languages_equivalent_matches_language_family():
    assert languages_equivalent("en-US", "en") is True
    assert languages_equivalent("zh-CN", "zh-TW") is True
    assert languages_equivalent("ja-JP", "zh-CN") is False
