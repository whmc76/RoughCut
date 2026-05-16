from roughcut.edit.decisions import EditSegment, build_edit_decision
from roughcut.edit.timeline_contract import audit_edit_decision_contract
from roughcut.media.silence import SilenceSegment


def test_trusted_speech_cut_by_silence_is_blocking() -> None:
    contract = audit_edit_decision_contract(
        duration=3.0,
        edit_segments=[
            EditSegment(start=0.0, end=1.0, type="keep"),
            EditSegment(start=1.0, end=1.6, type="remove", reason="silence"),
            EditSegment(start=1.6, end=3.0, type="keep"),
        ],
        transcript_segments=[
            {
                "index": 0,
                "text": "今天看手电",
                "words": [
                    {"word": "手电", "start": 1.2, "end": 1.45, "alignment": {"source": "provider"}},
                ],
            }
        ],
        subtitle_items=[
            {"start_time": 1.15, "end_time": 1.5, "text_final": "手电"},
        ],
        silence_segments=[],
    )

    assert contract["blocking"]
    assert contract["issue_counts"]["trusted_speech_cut_by_non_speech_reason"] == 1
    assert contract["cut_speech_examples"][0]["reason"] == "silence"


def test_explicit_filler_cut_is_allowed_for_speech_token() -> None:
    contract = audit_edit_decision_contract(
        duration=2.0,
        edit_segments=[
            EditSegment(start=0.0, end=0.25, type="remove", reason="filler_word"),
            EditSegment(start=0.25, end=2.0, type="keep"),
        ],
        transcript_segments=[
            {
                "index": 0,
                "text": "嗯今天看手电",
                "words": [
                    {"word": "嗯", "start": 0.02, "end": 0.16, "alignment": {"source": "provider"}},
                    {"word": "今天", "start": 0.3, "end": 0.55, "alignment": {"source": "provider"}},
                ],
            }
        ],
        subtitle_items=[
            {"start_time": 0.28, "end_time": 0.65, "text_final": "今天"},
        ],
        silence_segments=[],
    )

    assert not contract["blocking"]
    assert contract["cut_speech_unit_count"] == 1
    assert contract["cut_speech_examples"][0]["reason"] == "filler_word"


def test_pause_cut_requires_explicit_pause_reason() -> None:
    contract = audit_edit_decision_contract(
        duration=3.0,
        edit_segments=[
            EditSegment(start=0.0, end=1.0, type="keep"),
            EditSegment(start=1.0, end=1.7, type="remove"),
            EditSegment(start=1.7, end=3.0, type="keep"),
        ],
        transcript_segments=[],
        subtitle_items=[],
        silence_segments=[SilenceSegment(start=1.0, end=1.7)],
    )

    assert contract["blocking"]
    assert contract["issue_counts"]["pause_cut_without_reason"] == 1


def test_pause_cut_with_silence_reason_is_audited_as_explicit() -> None:
    contract = audit_edit_decision_contract(
        duration=3.0,
        edit_segments=[
            EditSegment(start=0.0, end=1.0, type="keep"),
            EditSegment(start=1.0, end=1.7, type="remove", reason="silence"),
            EditSegment(start=1.7, end=3.0, type="keep"),
        ],
        transcript_segments=[],
        subtitle_items=[],
        silence_segments=[SilenceSegment(start=1.0, end=1.7)],
    )

    assert not contract["blocking"]
    assert contract["cut_pause_unit_count"] == 1
    assert contract["cut_pause_examples"][0]["reason"] == "silence"


def test_long_kept_pause_is_visible_in_contract() -> None:
    contract = audit_edit_decision_contract(
        duration=3.0,
        edit_segments=[EditSegment(start=0.0, end=3.0, type="keep")],
        transcript_segments=[],
        subtitle_items=[],
        silence_segments=[SilenceSegment(start=1.0, end=1.75)],
    )

    assert not contract["blocking"]
    assert contract["warning_issue_count"] == 1
    assert contract["issue_counts"]["long_pause_kept_without_reason"] == 1
    assert contract["kept_long_pause_examples"][0]["overlap_sec"] == 0.75


def test_kept_speech_with_suppressed_display_reason_is_explicit_blocking() -> None:
    contract = audit_edit_decision_contract(
        duration=2.0,
        edit_segments=[EditSegment(start=0.0, end=2.0, type="keep")],
        transcript_segments=[
            {
                "index": 0,
                "text": "今天看手电",
                "words": [
                    {"word": "手电", "start": 0.8, "end": 1.2, "alignment": {"source": "provider"}},
                ],
            }
        ],
        subtitle_items=[
            {
                "start_time": 0.75,
                "end_time": 1.25,
                "text_final": "",
                "display_suppressed_reason": "asr_noise_marker",
            },
        ],
        silence_segments=[],
    )

    assert contract["blocking"]
    assert contract["issue_counts"]["kept_speech_display_suppressed"] == 1
    assert contract["blocking_examples"][0]["display_suppressed_reason"] == "asr_noise_marker"


def test_build_edit_decision_emits_source_timeline_contract_and_gate() -> None:
    decision = build_edit_decision(
        "demo.mp4",
        duration=3.0,
        silence_segments=[SilenceSegment(start=1.0, end=1.8)],
        subtitle_items=[],
        transcript_segments=[],
        content_profile=None,
    )

    contract = decision.analysis["source_timeline_contract"]
    assert contract["contract_version"] == "source_timeline_v1"
    assert contract["pause_unit_count"] == 1
    assert decision.analysis["automatic_gate"] == {
        "blocking": False,
        "blocking_reasons": [],
    }
