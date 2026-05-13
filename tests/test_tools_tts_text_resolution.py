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


def test_resolve_tts_spoken_text_prefers_segments_over_prompt_like_top_level_text() -> None:
    payload = """
    {
      "text": "你是短视频 AI 导演。请根据字幕输出 JSON：opening_hook、rewrite_strategy、voiceover_segments。",
      "voiceover_segments": [
        {
          "source_text": "原始字幕",
          "rewritten_text": "第一段真正要朗读的正文，长度足够触发后续分段时也不能混入提示词。"
        },
        {
          "source_text": "原始字幕二",
          "rewritten_text": "第二段真正要朗读的正文。"
        }
      ]
    }
    """

    resolved = tools._resolve_tts_spoken_text(payload)
    segments = tools._split_tts_text_for_synthesis(resolved, max_chars=28)

    assert resolved == "第一段真正要朗读的正文，长度足够触发后续分段时也不能混入提示词。 第二段真正要朗读的正文。"
    assert all("你是短视频 AI 导演" not in segment for segment in segments)
    assert all("voiceover_segments" not in segment for segment in segments)


def test_resolve_tts_spoken_text_trims_nested_prompt_when_labeled_text_exists() -> None:
    payload = """
    {
      "tts_text": "你是短视频 AI 导演。请根据字幕输出 JSON。\\ntts_text: 只朗读这一句。"
    }
    """

    assert tools._resolve_tts_spoken_text(payload) == "只朗读这一句。"


def test_resolve_tts_spoken_text_rejects_prompt_polluted_tts_text() -> None:
    payload = """
    {
      "tts_text": "你是短视频 AI 导演。请根据字幕输出 JSON。第一句正文。第二句正文。"
    }
    """

    with pytest.raises(ValueError, match="结构化提示词"):
        tools._resolve_tts_spoken_text(payload)


def test_resolve_tts_spoken_text_rejects_structured_prompt_without_tts_text() -> None:
    prompt = "你是短视频 AI 导演。请根据字幕输出 JSON：opening_hook、rewrite_strategy、voiceover_segments。"

    with pytest.raises(ValueError, match="tts_text"):
        tools._resolve_tts_spoken_text(prompt)


def test_strip_tts_text_ui_hints_still_keeps_plain_text() -> None:
    text = "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。 这是一段试音。"

    assert tools._resolve_tts_spoken_text(text) == "这是一段试音。"
