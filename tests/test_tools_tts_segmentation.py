from pathlib import Path
import wave

from roughcut.api import tools


def test_split_tts_text_for_synthesis_uses_sentence_boundaries() -> None:
    text = "第一句介绍背景。第二句补充细节。第三句给出结论。"

    segments = tools._split_tts_text_for_synthesis(text, max_chars=12)

    assert segments == ["第一句介绍背景。", "第二句补充细节。", "第三句给出结论。"]
    assert all(len(segment) <= 12 for segment in segments)


def test_split_tts_text_for_synthesis_keeps_normal_long_text_in_one_request() -> None:
    text = "这是一段用于验证普通长文本仍交给 CosyVoice3 内部分句处理的内容。" * 20

    segments = tools._split_tts_text_for_synthesis(text)

    assert segments == [text]


def test_split_tts_text_for_synthesis_splits_long_text_without_punctuation() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"

    segments = tools._split_tts_text_for_synthesis(text, max_chars=10)

    assert segments == ["abcdefghij", "klmnopqrst", "uvwxyz"]


def test_split_moss_tts_text_uses_short_chunks_for_local_generation() -> None:
    text = (
        "很多父母都会遇到这种情况。孩子明明自己说了可以，可事情结束以后，他又不高兴了。"
        "大人就会很疑惑，不是你自己答应的吗，不是你说可以的吗，那你现在为什么又委屈。"
        "可这真正想讲的，不是孩子反复无常，而是一个特别容易被大人忽略的问题。"
        "孩子嘴上说可以，不代表他心里真的愿意，所以后面还需要继续解释原因。"
    )

    segments = tools._split_tts_text_for_synthesis(text, max_chars=tools._MOSS_TTS_TEXT_SEGMENT_MAX_CHARS)

    assert len(segments) > 1
    assert "".join(segments) == text
    assert all(len(segment) <= tools._MOSS_TTS_TEXT_SEGMENT_MAX_CHARS for segment in segments)


def test_resolve_moss_segment_duration_tokens_auto_scales_by_text_length() -> None:
    duration_tokens = tools._resolve_moss_segment_duration_tokens(
        "这是一段大约二十个字的 MOSS Local 测试。",
        requested_duration_tokens=0,
        total_text="这是一段大约二十个字的 MOSS Local 测试。",
        segment_count=1,
    )

    assert duration_tokens >= tools._MOSS_MIN_AUTO_DURATION_TOKENS


def test_resolve_moss_segment_duration_tokens_splits_manual_budget_by_segment_chars() -> None:
    first = "第一段比较短。"
    second = "第二段明显更长一些，用来验证手动 duration token 会按字符数拆分。"

    first_tokens = tools._resolve_moss_segment_duration_tokens(
        first,
        requested_duration_tokens=300,
        total_text=first + second,
        segment_count=2,
    )
    second_tokens = tools._resolve_moss_segment_duration_tokens(
        second,
        requested_duration_tokens=300,
        total_text=first + second,
        segment_count=2,
    )

    assert first_tokens < second_tokens
    assert abs(first_tokens + second_tokens - 300) <= 1


def test_split_tts_text_for_synthesis_preserves_english_word_spaces() -> None:
    text = "This is the first sentence. This is the second sentence."

    segments = tools._split_tts_text_for_synthesis(text, max_chars=80)

    assert segments == ["This is the first sentence. This is the second sentence."]


def test_split_tts_text_for_synthesis_keeps_decimal_numbers_together() -> None:
    text = "版本 3.14 已发布。请继续测试。"

    segments = tools._split_tts_text_for_synthesis(text, max_chars=12)

    assert segments[0] == "版本 3.14 已发布。"


def test_concatenate_tts_wav_segments(tmp_path: Path) -> None:
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    output = tmp_path / "output.wav"
    tools._write_pcm16_wav(first, b"\x01\x00" * 100, sample_rate=1000)
    tools._write_pcm16_wav(second, b"\x02\x00" * 200, sample_rate=1000)

    meta = tools._concatenate_tts_wav_segments([first, second], output_path=output)

    assert meta["format"] == "wav"
    assert meta["sample_rate"] == 1000
    assert meta["source_format"] == "segmented_wav"
    with wave.open(str(output), "rb") as handle:
        assert handle.getnframes() == 300
        assert handle.getframerate() == 1000
