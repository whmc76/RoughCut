from roughcut.edit.decisions import (
    build_edit_decision,
    _collect_rollback_instruction_cuts,
    _collect_repeated_attempt_retake_candidates,
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


def test_repeated_failed_demo_attempts_keep_final_success_as_candidate() -> None:
    candidates = _collect_repeated_attempt_retake_candidates(
        [
            _subtitle(0, 0.0, 1.0, "我试一下这个快拆扣"),
            _subtitle(1, 1.2, 2.2, "这里没扣上好像有点卡住"),
            _subtitle(2, 2.6, 3.4, "再试一下"),
            _subtitle(3, 3.8, 5.4, "这样就很轻松扣上到位了"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert len(candidates) == 1
    assert candidates[0].start == 0.0
    assert candidates[0].end == 3.8
    assert candidates[0].reason == "restart_retake"
    assert candidates[0].evidence["cluster_type"] == "failed_demo_attempt"
    assert "keep_final_attempt" in candidates[0].evidence["tags"]


def test_progressive_spoken_line_retake_keeps_final_clean_line_as_candidate() -> None:
    candidates = _collect_repeated_attempt_retake_candidates(
        [
            _subtitle(0, 0.0, 0.8, "这个前置快开"),
            _subtitle(1, 1.0, 1.9, "这个前置快开其实"),
            _subtitle(2, 2.1, 4.0, "这个前置快开其实是最爽的一个开法"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert len(candidates) == 1
    assert candidates[0].start == 0.0
    assert candidates[0].end == 2.1
    assert candidates[0].evidence["cluster_type"] == "progressive_line_retake"


def test_self_correction_retake_handles_action_words_without_failed_demo_label() -> None:
    candidates = _collect_repeated_attempt_retake_candidates(
        [
            _subtitle(0, 719.129, 721.408, "拇指这还有个弹"),
            _subtitle(1, 721.408, 725.508, "开啊 就是你用这个指甲直接去"),
            _subtitle(2, 725.508, 727.786, "你用指甲卡住"),
            _subtitle(3, 727.786, 730.064, "这个大拇指的这个"),
            _subtitle(4, 730.064, 733.254, "不是 你用大拇指的指甲去卡"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert len(candidates) == 1
    assert candidates[0].start == 719.129
    assert candidates[0].end == 730.064
    assert candidates[0].evidence["cluster_type"] == "progressive_line_retake"


def test_sequential_product_explanation_is_not_treated_as_retake_cluster() -> None:
    candidates = _collect_repeated_attempt_retake_candidates(
        [
            _subtitle(0, 0.0, 1.0, "先看一下肩带这个位置"),
            _subtitle(1, 1.2, 2.4, "再看一下外袋容量"),
            _subtitle(2, 2.7, 4.0, "最后看背面的贴合效果"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    assert candidates == []


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


def test_waste_clip_semantics_are_not_decided_by_direct_text_matching() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=12.0,
        silence_segments=[],
        subtitle_items=[
            _subtitle(0, 0.0, 2.0, "这里打不开我再试一下"),
            _subtitle(1, 2.4, 4.2, "还是不行有点卡住"),
            _subtitle(2, 4.8, 6.0, "这次打开了"),
            _subtitle(3, 6.2, 7.0, "等一下我接个电话"),
            _subtitle(4, 7.4, 9.0, "继续看右边这个结构"),
        ],
        content_profile={"content_kind": "unboxing"},
    )

    reasons = {
        str(cut.get("reason") or "")
        for cut in decision.analysis["manual_editor_rule_candidates"]
    }
    assert "failed_attempt" not in reasons
    assert "off_topic_interruption" not in reasons


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
