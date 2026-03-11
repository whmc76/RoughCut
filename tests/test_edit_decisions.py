from __future__ import annotations

import pytest

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
