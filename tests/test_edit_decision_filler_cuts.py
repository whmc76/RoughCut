from roughcut.edit.decisions import (
    EditSegment,
    _build_subtitle_cut_candidates,
    _is_low_signal_subtitle_text,
    _refine_segments_for_pacing,
    build_edit_decision,
)
from roughcut.media.silence import SilenceSegment


def _subtitle(text: str) -> dict:
    return {
        "start_time": 1.0,
        "end_time": 2.0,
        "text_raw": text,
        "text_norm": text,
        "text_final": text,
    }


def test_filler_cut_keeps_short_normal_speech_after_filler_prefix() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle("这个刀"),
            _subtitle("这个我跟你说"),
            _subtitle("即使这样"),
        ],
        content_profile=None,
    )

    assert candidates == []


def test_filler_cut_only_removes_pure_filler_subtitle() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("这个嘛")],
        content_profile=None,
    )

    assert len(candidates) == 1
    assert candidates[0].reason == "filler_word"


def test_short_normal_speech_is_not_low_signal() -> None:
    assert not _is_low_signal_subtitle_text("我懒得看了")


def test_silence_cut_does_not_remove_subtitle_backed_speech() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=4.0,
        silence_segments=[SilenceSegment(start=1.0, end=1.8)],
        subtitle_items=[
            {
                "index": 0,
                "start_time": 1.05,
                "end_time": 1.65,
                "text_raw": "我懒得看了",
                "text_norm": "我懒得看了",
                "text_final": "我懒得看了",
            }
        ],
        content_profile=None,
    )

    assert any(segment.type == "keep" and segment.start <= 1.05 and segment.end >= 1.65 for segment in decision.segments)
    assert not any(segment.type == "remove" and segment.start <= 1.05 and segment.end >= 1.65 for segment in decision.segments)
    assert decision.analysis["silence_segments"] == [
        {"start": 1.0, "end": 1.8, "duration_sec": 0.8, "source": "audio_vad"}
    ]


def test_synthetic_transcript_word_timing_does_not_veto_vad_silence() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=4.0,
        silence_segments=[SilenceSegment(start=1.0, end=2.0)],
        subtitle_items=[],
        transcript_segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 3.0,
                "text": "今天先看这个手电",
                "words": [
                    {
                        "word": "手电",
                        "start": 1.2,
                        "end": 1.5,
                        "alignment": {"source": "roughcut_synthesized"},
                        "raw_payload": {"source": "roughcut_synthesized"},
                    }
                ],
            }
        ],
        content_profile=None,
    )

    assert any(cut["reason"] == "silence" for cut in decision.analysis["accepted_cuts"])
    assert any("vad_gap_over_synthetic_timing" in signal for cut in decision.analysis["accepted_cuts"] for signal in cut["signals"])


def test_trusted_transcript_word_timing_still_protects_speech_from_silence_cut() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=4.0,
        silence_segments=[SilenceSegment(start=1.0, end=2.0)],
        subtitle_items=[],
        transcript_segments=[
            {
                "index": 0,
                "start": 0.0,
                "end": 3.0,
                "text": "今天先看这个手电",
                "words": [
                    {
                        "word": "手电",
                        "start": 1.2,
                        "end": 1.5,
                        "alignment": {"source": "provider"},
                    }
                ],
            }
        ],
        content_profile=None,
    )

    assert not any(cut["reason"] == "silence" for cut in decision.analysis["accepted_cuts"])


def test_micro_keep_bridge_preserves_transcribed_speech() -> None:
    refined = _refine_segments_for_pacing(
        [
            EditSegment(start=0.0, end=1.0, type="remove", reason="silence"),
            EditSegment(start=1.0, end=1.45, type="keep"),
            EditSegment(start=1.45, end=2.2, type="remove", reason="silence"),
        ],
        subtitle_items=[
            {
                "index": 0,
                "start_time": 1.05,
                "end_time": 1.4,
                "text_raw": "我懒得看了",
                "text_norm": "我懒得看了",
                "text_final": "我懒得看了",
            }
        ],
        transcript_segments=[],
        content_profile=None,
        duration=2.2,
    )

    assert any(segment.type == "keep" and segment.start <= 1.05 and segment.end >= 1.4 for segment in refined)
