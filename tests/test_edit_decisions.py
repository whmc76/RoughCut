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


def test_build_edit_decision_removes_noise_like_subtitle():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 1.5,
            "text_raw": "咳咳咳",
            "text_norm": "咳咳咳",
            "text_final": "咳咳咳",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
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


def test_build_edit_decision_removes_restart_retake_window():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 1.6,
            "text_raw": "这个包最大的",
            "text_norm": "这个包最大的",
            "text_final": "这个包最大的",
        },
        {
            "index": 1,
            "start_time": 1.6,
            "end_time": 2.0,
            "text_raw": "等一下重来",
            "text_norm": "等一下重来",
            "text_final": "等一下重来",
        },
        {
            "index": 2,
            "start_time": 2.2,
            "end_time": 3.3,
            "text_raw": "这个包最大的优点就是容量很大",
            "text_norm": "这个包最大的优点就是容量很大",
            "text_final": "这个包最大的优点就是容量很大",
        },
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
    )

    restart_cut = next(segment for segment in decision.segments if segment.reason == "restart_retake")
    assert restart_cut.start == 1.0
    assert restart_cut.end == 2.2


def test_edit_decision_to_dict():
    silences = [SilenceSegment(start=2.0, end=3.0)]
    decision = build_edit_decision("test.mp4", 5.0, silences)
    d = decision.to_dict()
    assert d["version"] == 2
    assert d["source"] == "test.mp4"
    assert isinstance(d["segments"], list)
    assert isinstance(d["analysis"], dict)
    types = {s["type"] for s in d["segments"]}
    assert "keep" in types
    assert "remove" in types


def test_build_edit_decision_removes_micro_keep_without_subtitle_overlap():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=1.28, end=3.0),
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=[],
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert keep_segments == []
    assert len(decision.segments) == 1
    assert decision.segments[0].type == "remove"
    assert decision.segments[0].start == 0.0
    assert decision.segments[0].end == 3.0


def test_build_edit_decision_trims_keep_edges_to_subtitle_bounds():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=2.8, end=4.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.28,
            "end_time": 1.58,
            "text_raw": "KissPod",
            "text_norm": "KissPod",
            "text_final": "KissPod",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "LuckyKiss",
            "subject_model": "KissPod",
            "subject_type": "弹射益生菌含片",
        },
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    keep = keep_segments[0]
    assert keep.start == 1.0
    assert 1.58 < keep.end < 2.8
    assert keep.end - keep.start < 1.8


def test_build_edit_decision_preserves_short_anchor_keep_between_cuts():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=1.42, end=2.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.08,
            "end_time": 1.32,
            "text_raw": "KissPod",
            "text_norm": "KissPod",
            "text_final": "KissPod",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "LuckyKiss",
            "subject_model": "KissPod",
            "subject_type": "弹射益生菌含片",
        },
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    assert keep_segments[0].end - keep_segments[0].start > 0.3


def test_build_edit_decision_preserves_short_portability_comparison_keep():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=1.58, end=2.1),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.08,
            "end_time": 1.46,
            "text_raw": "尺寸和莱德曼是很接近的",
            "text_norm": "尺寸和莱德曼是很接近的",
            "text_final": "尺寸和莱德曼是很接近的",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=2.1,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "LuckyKiss",
            "subject_model": "KissPod",
            "subject_type": "弹射益生菌含片",
        },
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    keep = keep_segments[0]
    assert keep.start < 1.08
    assert keep.end > 1.46
    assert keep.end - keep.start >= 0.45


def test_build_edit_decision_skips_edge_trim_for_short_keep_audio_safety():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=2.0, end=3.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.28,
            "end_time": 1.58,
            "text_raw": "KissPod真的挺好用",
            "text_norm": "KissPod真的挺好用",
            "text_final": "KissPod真的挺好用",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "LuckyKiss",
            "subject_model": "KissPod",
            "subject_type": "弹射益生菌含片",
        },
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    keep = keep_segments[0]
    assert keep.start == 1.0
    assert keep.end == 2.0


def test_build_edit_decision_keeps_wider_audio_safe_padding_for_long_keep():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=3.0, end=4.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.5,
            "end_time": 2.2,
            "text_raw": "KissPod真的挺好用",
            "text_norm": "KissPod真的挺好用",
            "text_final": "KissPod真的挺好用",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={
            "subject_brand": "LuckyKiss",
            "subject_model": "KissPod",
            "subject_type": "弹射益生菌含片",
        },
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    keep = keep_segments[0]
    assert keep.start <= 1.32
    assert keep.end >= 2.44


def test_build_edit_decision_preserves_more_tail_for_incomplete_sentence():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=2.8, end=4.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.5,
            "end_time": 2.1,
            "text_raw": "这个包最大的优点就是",
            "text_norm": "这个包最大的优点就是",
            "text_final": "这个包最大的优点就是",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    assert keep_segments[0].end >= 2.48


def test_build_edit_decision_keeps_sentence_continuation_across_short_silence():
    silences = [SilenceSegment(start=1.7, end=2.3)]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 1.65,
            "text_raw": "这个包最大的优点就是",
            "text_norm": "这个包最大的优点就是",
            "text_final": "这个包最大的优点就是",
        },
        {
            "index": 1,
            "start_time": 2.3,
            "end_time": 3.0,
            "text_raw": "容量很大而且分仓很清楚",
            "text_norm": "容量很大而且分仓很清楚",
            "text_final": "容量很大而且分仓很清楚",
        },
    ]
    transcript_segments = [
        {"index": 0, "start": 1.0, "end": 1.65, "text": "这个包最大的优点就是", "speaker": "A", "confidence": 0.94},
        {"index": 1, "start": 2.3, "end": 3.0, "text": "容量很大而且分仓很清楚", "speaker": "A", "confidence": 0.95},
    ]

    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
    )

    silence_cuts = [segment for segment in decision.segments if segment.type == "remove" and segment.reason == "silence"]
    assert silence_cuts == []


def test_build_edit_decision_prefers_speaker_change_cut():
    silences = [SilenceSegment(start=1.0, end=1.5)]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 0.9,
            "text_raw": "intro section 123",
            "text_norm": "intro section 123",
            "text_final": "intro section 123",
        },
        {
            "index": 1,
            "start_time": 1.5,
            "end_time": 2.4,
            "text_raw": "spec section 456",
            "text_norm": "spec section 456",
            "text_final": "spec section 456",
        },
    ]
    transcript_segments = [
        {"index": 0, "start": 0.0, "end": 0.9, "text": "intro section 123", "speaker": "A", "confidence": 0.92},
        {"index": 1, "start": 1.5, "end": 2.4, "text": "spec section 456", "speaker": "B", "confidence": 0.93},
    ]

    decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        transcript_segments=transcript_segments,
    )

    silence_cut = next(segment for segment in decision.segments if segment.type == "remove" and segment.reason == "silence")
    assert silence_cut.start == 1.0
    assert silence_cut.end == 1.5


def test_build_edit_decision_snaps_silence_cut_to_scene_boundary():
    silences = [SilenceSegment(start=1.0, end=1.5)]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=[],
        scene_boundaries=[0.96, 1.46],
    )

    silence_cut = next(segment for segment in decision.segments if segment.type == "remove" and segment.reason == "silence")
    assert silence_cut.start == 0.96
    assert silence_cut.end == 1.46
