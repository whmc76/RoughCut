import pytest

from roughcut.api import tools


def test_resolve_tts_spoken_text_prefers_tts_text_from_json() -> None:
    payload = """
    {
      "prompt": "你是短视频 AI 导演，请输出结构化结果。",
      "tts_text": "这才是应该真正朗读的正文。"
    }
    """

    assert tools._resolve_tts_spoken_text(payload) == "这才是应该真正朗读的正文。"


def test_resolve_tts_spoken_text_joins_voiceover_segment_rewrites() -> None:
    payload = """
    ```json
    {
      "opening_hook": "结构化字段，不应该被朗读",
      "voiceover_segments": [
        {
          "purpose": "hook",
          "source_text": "原始字幕",
          "rewritten_text": "第一句口播。"
        },
        {
          "purpose": "closing",
          "source_text": "原始字幕二",
          "rewritten_text": "第二句口播。"
        }
      ]
    }
    ```
    """

    assert tools._resolve_tts_spoken_text(payload) == "第一句口播。 第二句口播。"


def test_resolve_tts_spoken_text_rejects_structured_prompt_without_tts_text() -> None:
    prompt = "你是短视频 AI 导演。请根据字幕输出 JSON：opening_hook、rewrite_strategy、voiceover_segments。"

    with pytest.raises(ValueError, match="tts_text"):
        tools._resolve_tts_spoken_text(prompt)


def test_strip_tts_text_ui_hints_still_keeps_plain_text() -> None:
    text = "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。 这是一段试音。"

    assert tools._resolve_tts_spoken_text(text) == "这是一段试音。"
