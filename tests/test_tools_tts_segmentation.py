from pathlib import Path
import wave

from roughcut.api import tools


def test_split_tts_text_for_synthesis_uses_sentence_boundaries() -> None:
    text = "第一句介绍背景。第二句补充细节。第三句给出结论。"

    segments = tools._split_tts_text_for_synthesis(text, max_chars=12)

    assert segments == ["第一句介绍背景。", "第二句补充细节。", "第三句给出结论。"]
    assert all(len(segment) <= 12 for segment in segments)


def test_split_tts_text_for_synthesis_splits_long_text_without_punctuation() -> None:
    text = "abcdefghijklmnopqrstuvwxyz"

    segments = tools._split_tts_text_for_synthesis(text, max_chars=10)

    assert segments == ["abcdefghij", "klmnopqrst", "uvwxyz"]


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
