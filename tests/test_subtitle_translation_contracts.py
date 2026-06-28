from types import SimpleNamespace

import pytest

from roughcut.review import subtitle_translation as st


def test_detect_subtitle_language_uses_canonical_surface() -> None:
    language = st.detect_subtitle_language(
        [
            {
                "text_raw": "EDC folding knife review",
                "text_norm": "这是 MAXACE 美杜莎4 直跳",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ]
    )

    assert language == "zh-CN"


def test_auto_translation_target_uses_english_chinese_pair() -> None:
    assert st.resolve_translation_target_language(
        source_language="zh-CN",
        target_language=None,
        target_language_mode="auto",
        preferred_ui_language="zh-CN",
    ) == "en"
    assert st.resolve_translation_target_language(
        source_language="en-US",
        target_language=None,
        target_language_mode="auto",
        preferred_ui_language="zh-CN",
    ) == "zh-CN"


@pytest.mark.asyncio
async def test_translate_subtitle_chunk_uses_canonical_surface() -> None:
    captured: dict[str, object] = {}

    class _Provider:
        async def complete(self, messages, **_kwargs):
            captured["prompt"] = messages[-1].content
            return SimpleNamespace(content='{"items":[{"index":0,"translated_text":"MAXACE Medusa 4"}]}')

    items = await st._translate_subtitle_chunk(
        provider=_Provider(),
        subtitle_items=[
            {
                "index": 0,
                "start_time": 0.0,
                "end_time": 1.0,
                "text_raw": "EDC folding knife",
                "text_norm": "这是 MAXACE 美杜莎4",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            }
        ],
        target_language="en",
    )

    assert "这是 MAXACE 美杜莎4" in str(captured["prompt"])
    assert "EDC folding knife" not in str(captured["prompt"])
    assert items[0]["text_source"] == "这是 MAXACE 美杜莎4"
