from roughcut.edit.decisions import (
    EditSegment,
    _build_subtitle_cut_candidates,
    _is_low_signal_subtitle_text,
    _refine_segments_for_pacing,
    build_edit_decision,
)
from roughcut.media.silence import SilenceSegment


def _subtitle(text: str, *, words: list[dict] | None = None, start: float = 1.0, end: float = 2.0) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "text_raw": text,
        "text_norm": text,
        "text_final": text,
        "words": words or [],
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


def test_auto_subtitle_rule_cuts_leading_hesitation_filler_only() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle(
                "嗯先看手电",
                words=[
                    {"word": "嗯", "start": 1.0, "end": 1.2},
                    {"word": "先", "start": 1.2, "end": 1.32},
                    {"word": "看", "start": 1.28, "end": 1.4},
                    {"word": "手", "start": 1.4, "end": 1.7},
                    {"word": "电", "start": 1.7, "end": 2.0},
                ],
            )
        ],
        content_profile=None,
    )

    assert len(candidates) == 1
    assert candidates[0].reason == "filler_word"
    assert candidates[0].signals[0] == "partial_filler"
    assert candidates[0].start == 1.0
    assert candidates[0].end <= 1.2


def test_auto_subtitle_rule_requires_transcript_filler_confirmation_when_asr_present() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle(
                "嗯先看手电",
                words=[
                    {"word": "嗯", "start": 1.0, "end": 1.2},
                    {"word": "先", "start": 1.22, "end": 1.3},
                    {"word": "看", "start": 1.3, "end": 1.42},
                    {"word": "手", "start": 1.42, "end": 1.7},
                    {"word": "电", "start": 1.7, "end": 2.0},
                ],
            )
        ],
        content_profile=None,
        transcript_segments=[
            {
                "index": 0,
                "start": 1.0,
                "end": 2.0,
                "text": "先看手电",
                "words": [
                    {"word": "先看", "start": 1.0, "end": 1.18, "alignment": {"source": "provider"}},
                ],
            }
        ],
    )

    assert candidates == []


def test_auto_subtitle_rule_allows_transcript_confirmed_filler_cut() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle(
                "嗯先看手电",
                words=[
                    {"word": "嗯", "start": 1.0, "end": 1.2},
                    {"word": "先", "start": 1.22, "end": 1.3},
                    {"word": "看", "start": 1.3, "end": 1.42},
                    {"word": "手", "start": 1.42, "end": 1.7},
                    {"word": "电", "start": 1.7, "end": 2.0},
                ],
            )
        ],
        content_profile=None,
        transcript_segments=[
            {
                "index": 0,
                "start": 1.0,
                "end": 2.0,
                "text": "嗯先看手电",
                "words": [
                    {"word": "嗯", "start": 1.0, "end": 1.2, "alignment": {"source": "provider"}},
                    {"word": "先看", "start": 1.22, "end": 1.42, "alignment": {"source": "provider"}},
                ],
            }
        ],
    )

    assert len(candidates) == 1
    assert candidates[0].reason == "filler_word"
    assert "subtitle_rule_confirmed_by_transcript_filler" in candidates[0].signals


def test_build_edit_decision_marks_filler_rules_without_auto_cutting_source() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=3.0,
        silence_segments=[],
        subtitle_items=[
            _subtitle(
                "嗯先看手电",
                start=1.0,
                end=2.0,
                words=[
                    {"word": "嗯", "start": 1.0, "end": 1.2},
                    {"word": "先", "start": 1.22, "end": 1.3},
                    {"word": "看", "start": 1.3, "end": 1.42},
                    {"word": "手", "start": 1.42, "end": 1.7},
                    {"word": "电", "start": 1.7, "end": 2.0},
                ],
            )
        ],
        transcript_segments=[
            {
                "index": 0,
                "start": 1.0,
                "end": 2.0,
                "text": "嗯先看手电",
                "words": [
                    {"word": "嗯", "start": 1.0, "end": 1.2, "alignment": {"source": "provider"}},
                    {"word": "先看", "start": 1.22, "end": 1.42, "alignment": {"source": "provider"}},
                ],
            }
        ],
        content_profile=None,
    )

    assert not any(cut["reason"] == "filler_word" for cut in decision.analysis["accepted_cuts"])
    assert any(
        cut["reason"] == "filler_word"
        and cut["candidate_stage"] == "manual_editor_full_transcript"
        and cut["auto_applied"] is False
        for cut in decision.analysis["manual_editor_rule_candidates"]
    )
    assert not any(segment.type == "remove" and segment.reason == "filler_word" for segment in decision.segments)


def test_auto_subtitle_rule_does_not_cut_mid_sentence_hesitation_particle() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("大家看到现在这个嗯后面继续讲")],
        content_profile=None,
    )

    assert [candidate for candidate in candidates if candidate.reason == "filler_word"] == []


def test_auto_subtitle_rule_drops_sub_frame_leading_hesitation_cut() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("嗯今天先看这个手电筒参数然后继续对比续航亮度做工细节")],
        content_profile=None,
    )

    assert [candidate for candidate in candidates if candidate.reason == "filler_word"] == []


def test_auto_subtitle_rule_cuts_repeated_phrase_second_copy_only() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle(
                "这个产品产品真的不错",
                words=[
                    {"word": "这", "start": 1.0, "end": 1.1},
                    {"word": "个", "start": 1.1, "end": 1.2},
                    {"word": "产", "start": 1.2, "end": 1.35},
                    {"word": "品", "start": 1.35, "end": 1.5},
                    {"word": "产", "start": 1.5, "end": 1.65},
                    {"word": "品", "start": 1.65, "end": 1.8},
                    {"word": "真", "start": 1.8, "end": 1.86},
                    {"word": "的", "start": 1.86, "end": 1.9},
                    {"word": "不", "start": 1.9, "end": 1.95},
                    {"word": "错", "start": 1.95, "end": 2.0},
                ],
            )
        ],
        content_profile=None,
    )

    repeated = [candidate for candidate in candidates if candidate.reason == "repeated_speech"]
    assert len(repeated) == 1
    assert repeated[0].signals[0] == "partial_repeated_speech"
    assert 1.49 < repeated[0].start < 1.51
    assert 1.79 < repeated[0].end < 1.81


def test_auto_subtitle_rule_does_not_estimate_partial_cut_without_alignment() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("这个产品产品真的不错")],
        content_profile=None,
    )

    assert [candidate for candidate in candidates if candidate.reason == "repeated_speech"] == []


def test_auto_subtitle_rule_does_not_cut_repeated_word_across_long_pause() -> None:
    candidates = _build_subtitle_cut_candidates(
        [
            _subtitle(
                "就是这个 这个能不能看到",
                start=552.83,
                end=555.23,
                words=[
                    {"word": "就", "start": 552.83, "end": 552.94},
                    {"word": "是", "start": 552.94, "end": 553.05},
                    {"word": "这", "start": 553.05, "end": 553.2},
                    {"word": "个", "start": 553.2, "end": 553.35},
                    {"word": "这", "start": 554.35, "end": 554.57},
                    {"word": "个", "start": 554.57, "end": 554.79},
                    {"word": "能", "start": 554.79, "end": 554.93},
                    {"word": "不", "start": 554.93, "end": 554.98},
                    {"word": "能", "start": 554.98, "end": 555.03},
                    {"word": "看", "start": 555.03, "end": 555.13},
                    {"word": "到", "start": 555.13, "end": 555.23},
                ],
            )
        ],
        content_profile=None,
    )

    assert [candidate for candidate in candidates if candidate.reason == "repeated_speech"] == []


def test_auto_subtitle_rule_drops_sub_frame_repeated_phrase_cut() -> None:
    candidates = _build_subtitle_cut_candidates(
        [_subtitle("这个产品产品真的不错然后继续看参数续航亮度做工体验")],
        content_profile=None,
    )

    assert [candidate for candidate in candidates if candidate.reason == "repeated_speech"] == []


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


def test_vad_silence_cut_is_bounded_between_trusted_words() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=12.0,
        silence_segments=[SilenceSegment(start=8.37, end=9.45)],
        subtitle_items=[],
        transcript_segments=[
            {
                "index": 0,
                "start": 4.88,
                "end": 11.52,
                "text": "大家看到现在这个镜头里有两把手电",
                "words": [
                    {"word": "这个", "start": 7.68, "end": 8.16, "alignment": {"source": "provider"}},
                    {"word": "镜头", "start": 9.46, "end": 9.76, "alignment": {"source": "provider"}},
                ],
            }
        ],
        content_profile=None,
        editing_skill={"silence_floor_sec": 0.8, "silence_score_bias": 0.3},
    )

    silence_cuts = [cut for cut in decision.analysis["accepted_cuts"] if cut["reason"] == "silence"]
    assert len(silence_cuts) == 1
    assert silence_cuts[0]["start"] == 8.37
    assert silence_cuts[0]["end"] == 9.38


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
