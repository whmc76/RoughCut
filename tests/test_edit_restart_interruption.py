from roughcut.edit.decisions import (
    build_edit_decision,
    _collect_restart_cue_cuts,
    _collect_restart_retake_cuts,
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
