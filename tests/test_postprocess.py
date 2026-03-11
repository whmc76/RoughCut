from __future__ import annotations

from types import SimpleNamespace

from roughcut.speech.postprocess import normalize_text, split_into_subtitles


def _mock_segment(idx, start, end, text, words=None):
    """Create a mock TranscriptSegment-like object."""
    return SimpleNamespace(
        segment_index=idx,
        start_time=start,
        end_time=end,
        text=text,
        words_json=words,
        speaker=None,
    )


def test_normalize_text_strips():
    assert normalize_text("  hello  ") == "hello"


def test_normalize_text_short_no_punctuation():
    result = normalize_text("好")
    assert result == "好"  # Too short to add punctuation


def test_split_into_subtitles_basic():
    segs = [_mock_segment(0, 0.0, 5.0, "这是一段很长的测试文本，用于验证字幕分割功能是否正常工作")]
    entries = split_into_subtitles(segs, max_chars=15, max_duration=5.0)
    assert len(entries) > 1
    for e in entries:
        assert len(e.text_raw) <= 15


def test_split_into_subtitles_with_words():
    words = [
        {"word": "你好", "start": 0.0, "end": 0.5},
        {"word": "世界", "start": 0.5, "end": 1.0},
        {"word": "这是", "start": 1.0, "end": 1.5},
        {"word": "测试", "start": 1.5, "end": 2.0},
    ]
    segs = [_mock_segment(0, 0.0, 2.0, "你好世界这是测试", words=words)]
    entries = split_into_subtitles(segs, max_chars=4, max_duration=5.0)
    assert len(entries) >= 2
    assert entries[0].start == 0.0


def test_split_preserves_timing():
    segs = [
        _mock_segment(0, 0.0, 2.0, "第一句"),
        _mock_segment(1, 3.0, 5.0, "第二句"),
    ]
    entries = split_into_subtitles(segs)
    assert entries[0].start == 0.0
    assert entries[1].start == 3.0
