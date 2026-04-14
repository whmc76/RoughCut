from __future__ import annotations


from roughcut.edit.decisions import _resolve_keep_energy_for_segment, EditSegment, build_edit_decision
from roughcut.edit.skills import apply_review_focus_overrides, resolve_editing_skill
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


def test_build_edit_decision_keeps_low_signal_repeated_subtitles_for_manual_review():
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
    assert all(segment.reason != "low_signal_subtitle" for segment in remove_segments)


def test_build_edit_decision_keeps_short_hedge_heavy_subtitles_for_manual_review():
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
    assert all(segment.reason != "low_signal_subtitle" for segment in remove_segments)


def test_build_edit_decision_keeps_noise_like_subtitle_without_explicit_filler_rule():
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
    assert all(segment.reason != "low_signal_subtitle" for segment in remove_segments)


def test_build_edit_decision_keeps_subject_conflict_short_subtitle_without_explicit_restart_signal():
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
    assert all(segment.reason != "low_signal_subtitle" for segment in remove_segments)


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


def test_build_edit_decision_removes_restart_retake_window_when_restart_cue_marks_complete_prefix():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 1.6,
            "text_raw": "这个包最大的优点",
            "text_norm": "这个包最大的优点",
            "text_final": "这个包最大的优点",
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
            "end_time": 3.4,
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


def test_build_edit_decision_preserves_short_visual_showcase_cue_subtitle():
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.0,
            "end_time": 1.4,
            "text_raw": "放一起看",
            "text_norm": "放一起看",
            "text_final": "放一起看",
        }
    ]
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=[],
        subtitle_items=subtitle_items,
    )

    remove_segments = [segment for segment in decision.segments if segment.type == "remove" and segment.reason == "low_signal_subtitle"]
    assert remove_segments == []


def test_build_edit_decision_preserves_hook_micro_keep_bridge_with_keep_energy():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=[
            SilenceSegment(start=0.0, end=1.0),
            SilenceSegment(start=1.34, end=2.0),
        ],
        subtitle_items=[
            {
                "start_time": 1.06,
                "end_time": 1.22,
                "text_final": "先说尺寸更稳",
            }
        ],
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert len(keep_segments) == 1
    assert keep_segments[0].start == 1.0
    assert keep_segments[0].end == 1.34


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


def test_build_edit_decision_preserves_visual_showcase_silence_gap():
    silences = [SilenceSegment(start=1.0, end=2.2)]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 1.0,
            "text_raw": "先说参数",
            "text_norm": "先说参数",
            "text_final": "先说参数",
        },
        {
            "index": 1,
            "start_time": 2.2,
            "end_time": 3.3,
            "text_raw": "放一起看尺寸差异",
            "text_norm": "放一起看尺寸差异",
            "text_final": "放一起看尺寸差异",
        },
    ]
    transcript_segments = [
        {"index": 0, "start": 0.0, "end": 1.0, "text": "先说参数", "speaker": "A", "confidence": 0.95},
        {"index": 1, "start": 2.2, "end": 3.3, "text": "放一起看尺寸差异", "speaker": "A", "confidence": 0.95},
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


def test_build_edit_decision_removes_long_non_dialogue_keep_without_transcript_or_showcase_support():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=2.6, end=4.0),
    ]
    transcript_segments = [
        {"index": 0, "start": 0.0, "end": 0.9, "text": "开头", "speaker": "A", "confidence": 0.95},
        {"index": 1, "start": 2.7, "end": 3.6, "text": "结尾", "speaker": "A", "confidence": 0.95},
    ]

    decision = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=[],
        transcript_segments=transcript_segments,
    )

    keep_segments = [segment for segment in decision.segments if segment.type == "keep"]
    assert keep_segments == []
    assert len(decision.segments) == 1
    assert decision.segments[0].type == "remove"
    assert decision.segments[0].start == 0.0
    assert decision.segments[0].end == 4.0


def test_build_edit_decision_gameplay_skill_trims_keep_more_aggressively():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=3.0, end=4.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.5,
            "end_time": 2.2,
            "text_raw": "这波操作非常关键",
            "text_norm": "这波操作非常关键",
            "text_final": "这波操作非常关键",
        }
    ]

    gameplay = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={"content_kind": "gameplay"},
    )
    commentary = build_edit_decision(
        source_path="test.mp4",
        duration=4.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={"content_kind": "commentary"},
    )

    gameplay_keep = next(segment for segment in gameplay.segments if segment.type == "keep")
    commentary_keep = next(segment for segment in commentary.segments if segment.type == "keep")
    assert gameplay_keep.start >= commentary_keep.start
    assert gameplay_keep.end <= commentary_keep.end
    assert (gameplay_keep.end - gameplay_keep.start) < (commentary_keep.end - commentary_keep.start)


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


def test_build_edit_decision_commentary_skill_preserves_micro_bridge_keep():
    silences = [
        SilenceSegment(start=0.0, end=1.0),
        SilenceSegment(start=1.48, end=2.0),
    ]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 1.1,
            "end_time": 1.36,
            "text_raw": "这个参数一定要看",
            "text_norm": "这个参数一定要看",
            "text_final": "这个参数一定要看",
        }
    ]

    gameplay = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={"content_kind": "gameplay"},
    )
    commentary = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        content_profile={"content_kind": "commentary"},
    )

    gameplay_keeps = [segment for segment in gameplay.segments if segment.type == "keep"]
    commentary_keeps = [segment for segment in commentary.segments if segment.type == "keep"]
    assert gameplay_keeps == []
    assert len(commentary_keeps) == 1


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


def test_build_edit_decision_hook_boundary_focus_suppresses_hook_cut():
    silences = [SilenceSegment(start=0.9, end=1.48)]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 0.82,
            "text_raw": "先说结论这把很稳",
            "text_norm": "先说结论这把很稳",
            "text_final": "先说结论这把很稳",
        },
        {
            "index": 1,
            "start_time": 1.48,
            "end_time": 2.2,
            "text_raw": "直接说结论亮度也够",
            "text_norm": "直接说结论亮度也够",
            "text_final": "直接说结论亮度也够",
        },
    ]

    default_decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
    )
    focused_decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        editing_skill=apply_review_focus_overrides(
            resolve_editing_skill(workflow_template="unboxing_standard", content_profile={}),
            review_focus="hook_boundary",
        ),
    )

    default_cuts = [segment for segment in default_decision.segments if segment.type == "remove" and segment.reason == "silence"]
    focused_cuts = [segment for segment in focused_decision.segments if segment.type == "remove" and segment.reason == "silence"]
    assert len(default_cuts) == 1
    assert focused_cuts == []
    assert focused_decision.analysis["review_focus"] == "hook_boundary"


def test_build_edit_decision_mid_transition_focus_suppresses_mid_cut():
    silences = [SilenceSegment(start=0.92, end=1.48)]
    subtitle_items = [
        {
            "index": 0,
            "start_time": 0.0,
            "end_time": 0.84,
            "text_raw": "重点看参数部分",
            "text_norm": "重点看参数部分",
            "text_final": "重点看参数部分",
        },
        {
            "index": 1,
            "start_time": 1.48,
            "end_time": 2.3,
            "text_raw": "细节对比这里更关键",
            "text_norm": "细节对比这里更关键",
            "text_final": "细节对比这里更关键",
        },
    ]

    default_decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
    )
    focused_decision = build_edit_decision(
        source_path="test.mp4",
        duration=3.0,
        silence_segments=silences,
        subtitle_items=subtitle_items,
        editing_skill=apply_review_focus_overrides(
            resolve_editing_skill(workflow_template="unboxing_standard", content_profile={}),
            review_focus="mid_transition",
        ),
    )

    default_cuts = [segment for segment in default_decision.segments if segment.type == "remove" and segment.reason == "silence"]
    focused_cuts = [segment for segment in focused_decision.segments if segment.type == "remove" and segment.reason == "silence"]
    assert len(default_cuts) == 1
    assert focused_cuts == []


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


def test_build_edit_decision_uses_aggressive_gameplay_silence_profile():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=[SilenceSegment(start=0.8, end=1.2)],
        content_profile={"content_kind": "gameplay"},
    )

    silence_cut = next(segment for segment in decision.segments if segment.type == "remove" and segment.reason == "silence")
    assert silence_cut.start == 0.8
    assert silence_cut.end == 1.2
    assert decision.to_dict()["analysis"]["effective_min_silence_to_cut"] == 0.34


def test_build_edit_decision_uses_conservative_commentary_silence_profile():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=2.0,
        silence_segments=[SilenceSegment(start=0.8, end=1.2)],
        content_profile={"content_kind": "commentary"},
    )

    silence_cuts = [segment for segment in decision.segments if segment.type == "remove" and segment.reason == "silence"]
    assert silence_cuts == []
    assert decision.to_dict()["analysis"]["effective_min_silence_to_cut"] == 0.68


def test_build_edit_decision_emits_timeline_analysis():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=12.0,
        silence_segments=[],
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.8, "text_final": "先说结论，这个方案更稳。"},
            {"start_time": 3.0, "end_time": 6.2, "text_final": "接着看参数和细节。"},
            {"start_time": 9.5, "end_time": 11.8, "text_final": "记得点赞收藏。"},
        ],
    )

    analysis = decision.to_dict()["analysis"]
    assert analysis["hook_end_sec"] >= 2.8
    assert analysis["cta_start_sec"] == 9.5
    assert analysis["semantic_sections"]
    assert analysis["section_directives"]
    assert analysis["section_actions"]
    assert analysis["editing_skill"]["key"] == "unboxing_standard"
    assert any(action["packaging_intent"] == "hook_focus" for action in analysis["section_actions"] if action["role"] == "hook")
    assert any(not directive["insert_allowed"] for directive in analysis["section_directives"] if directive["role"] == "hook")
    assert analysis["emphasis_candidates"]
    assert analysis["keep_energy_segments"]
    assert analysis["keep_energy_summary"]["count"] >= 1
    assert analysis["keep_energy_summary"]["max_keep_energy"] >= 1.0


def test_build_edit_decision_emits_creative_preference_rationale_in_timeline_analysis():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=12.0,
        silence_segments=[],
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.8, "text_final": "先说结论，这个方案更稳。"},
            {"start_time": 3.0, "end_time": 6.2, "text_final": "接着看参数和细节。"},
            {"start_time": 9.5, "end_time": 11.8, "text_final": "记得点赞收藏。"},
        ],
        content_profile={
            "creative_preferences": [
                {"tag": "conclusion_first", "count": 3},
                {"tag": "comparison_focus", "count": 2},
                {"tag": "closeup_focus", "count": 2},
            ],
        },
    )

    analysis = decision.to_dict()["analysis"]
    hook_directive = next(item for item in analysis["section_directives"] if item["role"] == "hook")
    detail_action = next(item for item in analysis["section_actions"] if item["role"] == "detail")

    assert "先给结论" in hook_directive["creative_preferences"]
    assert "关键差异" in hook_directive["creative_rationale"]
    assert "突出近景特写" in detail_action["creative_preferences"]
    assert "细节段优先保留近景和做工镜头" in detail_action["creative_rationale"]


def test_build_edit_decision_annotates_accepted_cuts_with_boundary_keep_energy():
    decision = build_edit_decision(
        source_path="test.mp4",
        duration=7.0,
        silence_segments=[SilenceSegment(start=2.8, end=3.55)],
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.5, "text_final": "先说结论，这个方案更稳。"},
            {"start_time": 3.8, "end_time": 6.1, "text_final": "接着看参数和细节。"},
        ],
    )

    silence_cut = next(cut for cut in decision.to_dict()["analysis"]["accepted_cuts"] if cut["reason"] == "silence")
    assert silence_cut["boundary_keep_energy"] >= 1.0
    assert silence_cut["left_keep_role"] == "hook"
    assert silence_cut["right_keep_role"] == "detail"


def test_resolve_keep_energy_for_segment_combines_signal_section_and_emphasis():
    energy = _resolve_keep_energy_for_segment(
        EditSegment(start=1.0, end=1.36, type="keep"),
        overlaps=[
            {
                "start_time": 1.04,
                "end_time": 1.24,
                "text_final": "先说这个更稳",
            }
        ],
        content_profile=None,
        timeline_analysis={
            "emphasis_candidates": [
                {"start_time": 1.18, "end_time": 1.4, "text": "这个更稳", "role": "hook", "score": 1.6}
            ],
            "section_actions": [
                {
                    "role": "hook",
                    "start_sec": 0.0,
                    "end_sec": 2.0,
                    "packaging_intent": "hook_focus",
                    "transition_boost": 0.8,
                }
            ],
        },
    )

    assert energy > 1.0
