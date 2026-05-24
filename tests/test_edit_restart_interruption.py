from roughcut.edit.decisions import (
    build_edit_decision,
    _collect_rollback_instruction_cuts,
    _collect_restart_cue_cuts,
    _collect_restart_retake_cuts,
    _is_rollback_instruction_text,
    _is_restart_cue_text,
)
from roughcut.media.silence import SilenceSegment


def _subtitle(index: int, start: float, end: float, text: str) -> dict:
    return {
        "index": index,
        "start_time": start,
        "end_time": end,
        "text_final": text,
    }


def test_interruption_cue_is_restart_cue() -> None:
    assert _is_restart_cue_text("滚")
    assert _is_restart_cue_text("别打扰")
    assert not _is_restart_cue_text("滚轮是金属的")


def test_spoken_rollback_instruction_cuts_previous_attempt_window() -> None:
    cuts = _collect_rollback_instruction_cuts(
        [
            _subtitle(0, 10.0, 13.0, "这个地方打不开我再试一下"),
            _subtitle(1, 13.4, 17.2, "还是不行这个位置有点卡住"),
            _subtitle(2, 18.0, 19.0, "把刚才这段剪掉"),
            _subtitle(3, 19.2, 21.0, "正式说这里其实只要往外推"),
        ],
        content_profile={},
    )

    assert len(cuts) == 1
    assert cuts[0].start == 10.0
    assert cuts[0].end == 18.0
    assert cuts[0].reason == "rollback_instruction"
    assert "spoken_editorial_rollback" in cuts[0].signals
    assert cuts[0].evidence["subtitle_count"] == 2


def test_rollback_instruction_accepts_asr_variant_from_real_failure_case() -> None:
    assert _is_rollback_instruction_text("本来就是减6啊所以说也是很爽啊")


def test_build_edit_decision_marks_rollback_instruction_for_manual_full_transcript() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=22.0,
        silence_segments=[],
        subtitle_items=[
            _subtitle(0, 10.0, 13.0, "这个地方打不开我再试一下"),
            _subtitle(1, 13.4, 17.2, "还是不行这个位置有点卡住"),
            _subtitle(2, 18.0, 19.0, "把刚才这段剪掉"),
            _subtitle(3, 19.2, 21.0, "正式说这里其实只要往外推"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert not any(cut["reason"] == "rollback_instruction" for cut in decision.analysis["accepted_cuts"])
    assert any(
        cut["reason"] == "rollback_instruction"
        and cut["start"] == 10.0
        and cut["end"] == 18.0
        and cut["candidate_stage"] == "manual_editor_full_transcript"
        and cut["auto_applied"] is False
        for cut in decision.analysis["manual_editor_rule_candidates"]
    )
    assert not any(segment.type == "remove" and segment.start == 10.0 and segment.end == 18.0 for segment in decision.segments)


def test_coarse_transcript_text_does_not_create_rollback_candidates_for_every_subtitle() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=40.0,
        silence_segments=[],
        subtitle_items=[
            _subtitle(0, 1.0, 5.0, "今天看这个小工具"),
            _subtitle(1, 5.0, 9.0, "它的手感还不错"),
            _subtitle(2, 9.0, 13.0, "接下来展示一下开合"),
        ],
        transcript_segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 300.0,
                "text": "今天看这个小工具，它的手感还不错。后面误识别成这段剪掉但这不是当前字幕。",
                "words": [],
            }
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert not any(
        cut["reason"] == "rollback_instruction"
        for cut in decision.analysis["manual_editor_rule_candidates"]
    )


def test_interruption_between_retake_lines_becomes_cut_candidate() -> None:
    cuts = _collect_restart_retake_cuts(
        [
            _subtitle(0, 0.0, 1.0, "这个手感不错"),
            _subtitle(1, 1.2, 1.6, "滚"),
            _subtitle(2, 2.0, 4.0, "这个手感不错但是容量更大"),
        ],
        content_profile={},
    )

    assert cuts == [(0.0, 2.0, "restart_retake")]


def test_standalone_interruption_cue_becomes_cut_candidate() -> None:
    cuts = _collect_restart_cue_cuts(
        [
            _subtitle(0, 0.0, 1.0, "先看一下左边"),
            _subtitle(1, 1.2, 1.5, "别打扰"),
            _subtitle(2, 1.8, 3.0, "继续看右边"),
        ],
        content_profile={},
    )

    assert cuts == [(1.2, 1.5, "restart_cue")]


def test_visual_showcase_silence_is_preserved() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=10.0,
        silence_segments=[SilenceSegment(start=2.1, end=5.7)],
        subtitle_items=[
            _subtitle(0, 0.0, 1.0, "今天看这个工具"),
            _subtitle(1, 1.4, 2.0, "先展示一下细节"),
            _subtitle(2, 6.0, 7.0, "这个纹理很清楚"),
        ],
        content_profile={"content_kind": "unboxing"},
        scene_boundaries=[{"start": 3.6, "end": 3.7}],
    )

    removed = [segment for segment in decision.segments if segment.type == "remove"]
    assert not any(segment.start <= 2.1 and segment.end >= 5.7 for segment in removed)
    assert decision.analysis["decision_methodology"]["version"] == "multisignal_v1"


def test_plain_long_silence_cut_keeps_evidence_payload() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=8.0,
        silence_segments=[SilenceSegment(start=1.2, end=6.5)],
        subtitle_items=[
            _subtitle(0, 0.0, 1.0, "今天先说结论"),
            _subtitle(1, 7.0, 8.0, "继续讲下一点"),
        ],
        content_profile={"content_kind": "commentary"},
    )

    silence_cuts = [
        cut
        for cut in decision.analysis["accepted_cuts"]
        if cut["reason"] == "silence"
    ]
    assert silence_cuts
    evidence = silence_cuts[0]["evidence"]
    assert evidence["subtitle_count"] == 0
    assert "no_dialogue_inside" in evidence["tags"]
    assert decision.analysis["cut_evidence_summary"]["evidence_cut_count"] >= 1
