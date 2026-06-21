import json
from pathlib import Path

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


def test_resolve_tts_spoken_text_allows_plain_narration_with_weak_prompt_words() -> None:
    text = (
        "育儿问题：孩子上学前这些小仪式，到底有没有必要？"
        "有的孩子会要求：爸爸必须抱一下，再挥一次手。"
        "这不是结构化提示词，而是孩子在用自己的方式完成分离。"
    )

    assert tools._resolve_tts_spoken_text(text) == text


def test_strip_tts_text_ui_hints_still_keeps_plain_text() -> None:
    text = "需要 prompt_wav/reference_audio；prompt_text 和 instruct_text 不参与该模式。 这是一段试音。"

    assert tools._resolve_tts_spoken_text(text) == "这是一段试音。"


def test_normalize_cosyvoice3_instruct_text_compacts_preset_stack() -> None:
    raw = "\n".join(
        [
            "请像幼教老师一样，声音亲切、有耐心，语气更温柔活泼。",
            "请用有声故事演播风格表达，语气有画面感，人物和情节转折要更清楚。",
            "请用课堂教学风格表达，逻辑清楚，重点词需要自然强调。",
            "请用紧凑、有节奏、适合短视频旁白的方式说这句话。",
        ]
    )

    normalized = tools._normalize_cosyvoice3_instruct_text(raw)

    assert normalized == (
        "You are a helpful assistant.\n"
        "幼教老师风格，亲切耐心、温柔活泼；故事演播，画面感，转折清楚；课堂教学，逻辑清楚，重点自然强调；短视频旁白、紧凑有节奏。<|endofprompt|>"
    )
    assert "幼教老师" in normalized
    assert "故事演播" in normalized
    assert "课堂教学" in normalized
    assert "短视频旁白" in normalized
    assert "请像" not in normalized
    assert "请用" not in normalized


def test_build_tts_oralization_messages_uses_structured_json_contract() -> None:
    messages = tools._build_tts_oralization_messages(
        source_text="这个产品的续航是二十小时，适合通勤。",
        style="warm_explainer",
        provider="moss_tts_local",
        speaker_count=1,
        target_chars=40,
    )

    assert messages[0].role == "system"
    assert "只输出 JSON" in messages[0].content
    payload = json.loads(messages[1].content)
    assert payload["task"] == "rewrite_for_natural_tts"
    assert payload["output_schema"]["tts_text"] == "最终送入 TTS 的可朗读正文。"
    assert any("单人口播不要加 [S1] 标签" in rule for rule in payload["rules"])
    assert payload["source_text"] == "这个产品的续航是二十小时，适合通勤。"


def test_build_tts_oralization_messages_podcast_requires_speaker_tags() -> None:
    messages = tools._build_tts_oralization_messages(
        source_text="今天讨论续航。",
        style="podcast_dialogue",
        provider="moss_tts_local",
        speaker_count=2,
        target_chars=0,
    )

    payload = json.loads(messages[1].content)
    assert payload["speaker_count"] == 2
    assert any("tts_text 必须使用 [S1]-[S5] 标签" in rule for rule in payload["rules"])


def test_validate_tts_audio_output_rejects_zero_duration_wav(tmp_path: Path) -> None:
    path = tmp_path / "empty.wav"
    tools._write_pcm16_wav(path, b"", sample_rate=24000)

    with pytest.raises(RuntimeError, match="returned empty audio"):
        tools._validate_tts_audio_output(path, service_label="MOSS-TTS Local")


def test_validate_tts_audio_duration_rejects_obviously_truncated_long_text() -> None:
    text = "很多父母都会遇到这种情况。孩子明明自己说了可以，可事情结束以后，他又不高兴了。" * 4

    with pytest.raises(RuntimeError, match="too short for the target text"):
        tools._validate_tts_audio_duration_for_text(4.9, text, service_label="MOSS-TTS Local")


def test_validate_tts_audio_duration_rejects_medium_text_cut_short() -> None:
    text = (
        "很多父母都会遇到这种情况。孩子明明自己说了“可以”，可事情结束以后，他又不高兴了。"
        "大人就会很疑惑：“不是你自己答应的吗？”“不是你说可以的吗？”“那你现在为什么又委屈？” "
        "可《示例动画》这集《跳舞模式》真正想讲的，不是孩子反复无常，而是一个特别容易被大人忽略的问题："
        "孩子嘴上说可以，不代表他心里真的愿意。先说结论，再解释原因。这个问题可以分成三个层面来看。"
    )

    with pytest.raises(RuntimeError, match="too short for the target text"):
        tools._validate_tts_audio_duration_for_text(12.9, text, service_label="MOSS-TTS Local")


def test_validate_tts_audio_duration_allows_short_text() -> None:
    tools._validate_tts_audio_duration_for_text(1.0, "小手，数一数：一、二、三。", service_label="MOSS-TTS Local")
