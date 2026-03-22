from __future__ import annotations


from roughcut.edit.decisions import build_edit_decision
from roughcut.media.silence import SilenceSegment


def test_build_edit_decision_basic():
    silences = [
        SilenceSegment(start=5.0, end=7.0),  # 2s silence
        SilenceSegment(start=10.0, end=10.4),  # 0.4s — below threshold
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=15.0,
        silence_segments=silences,
        min_silence_to_cut=0.5,
    )

    assert decision.source == "test.mp4"
    # 0.4s silence below threshold, so only the 2s one is cut
    remove_segments = [s for s in decision.segments if s.type == "remove"]
    assert len(remove_segments) == 1
    assert remove_segments[0].start == 5.0
    assert remove_segments[0].end == 7.0
    assert remove_segments[0].reason == "silence"


def test_build_edit_decision_no_silence():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=10.0,
        silence_segments=[],
    )
    assert len(decision.segments) == 1
    assert decision.segments[0].type == "keep"
    assert decision.segments[0].start == 0.0
    assert decision.segments[0].end == 10.0


def test_build_edit_decision_filler_detection():
    subtitle_items = [
        {"index": 0, "start_time": 3.0, "end_time": 3.8, "text_raw": "嗯", "text_norm": "嗯"},
        {"index": 1, "start_time": 5.0, "end_time": 6.0, "text_raw": "这是一个测试句子", "text_norm": "这是一个测试句子"},
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=10.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
        cut_fillers=True,
    )
    remove_segments = [s for s in decision.segments if s.type == "remove"]
    filler_cuts = [s for s in remove_segments if s.reason == "filler_word"]
    assert len(filler_cuts) == 1
    assert filler_cuts[0].start == 3.0


def test_build_edit_decision_removes_low_signal_repeated_subtitles():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 3.0,
            "end_time": 4.2,
            "text_raw": "这些自顶配尽量这些自顶配尽量",
            "text_norm": "这些自顶配尽量这些自顶配尽量",
            "text_final": "这些自顶配尽量这些自顶配尽量",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=8.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
    )

    remove_segments = [s for s in decision.segments if s.type == "remove"]
    assert len(remove_segments) == 1
    assert remove_segments[0].reason == "low_signal_subtitle"


def test_build_edit_decision_removes_short_hedge_heavy_subtitles():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 2.2,
            "text_raw": "其实也算上是一个呼应",
            "text_norm": "其实也算上是一个呼应",
            "text_final": "其实也算上是一个呼应",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=5.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
    )

    remove_segments = [s for s in decision.segments if s.type == "remove"]
    assert len(remove_segments) == 1
    assert remove_segments[0].reason == "low_signal_subtitle"


def test_build_edit_decision_removes_subject_conflict_short_subtitle():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 2.4,
            "text_raw": "这两个MT-33光线",
            "text_norm": "这两个MT-33光线",
            "text_final": "这两个MT-33光线",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=5.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "NOC",
            "subject_model": "MT-33",
            "subject_type": "EDC折刀",
            "visible_text": "MT33、磁顶配镜面板、液压杆螺丝、钢码",
        },
    )

    remove_segments = [s for s in decision.segments if s.type == "remove"]
    assert len(remove_segments) == 1
    assert remove_segments[0].reason == "low_signal_subtitle"


def test_edit_decision_to_dict():
    silences = [SilenceSegment(start=2.0, end=3.0)]
    decision = build_edit_decision("test.mp4", 5.0, silences)
    d = decision.to_dict()
    assert d["version"] == 1
    assert d["source"] == "test.mp4"
    assert isinstance(d["segments"], list)
    types = {s["type"] for s in d["segments"]}
    assert "keep" in types
    assert "remove" in types
