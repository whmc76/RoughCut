from roughcut.speech.subtitle_segmentation import (
    SubtitleEntry,
    _assess_subtitle_boundary,
    analyze_subtitle_segmentation,
)


def _worded_entry(index: int, start: float, text: str, duration: float) -> SubtitleEntry:
    return SubtitleEntry(
        index=index,
        start=start,
        end=start + duration,
        text_raw=text,
        text_norm=text,
        words=(
            {
                "word": text,
                "start": start,
                "end": start + duration,
                "segment_index": 0,
            },
        ),
    )


def test_boundary_blocks_subject_clause_restart_after_trailing_pronoun() -> None:
    assessment = _assess_subtitle_boundary("而且，呃，你不一定非要勾着这个钩子去砍的，你", "可以从这边上的孔啊。")

    assert assessment.forbidden is True
    assert "subject_clause_restart" in assessment.damage_flags


def test_boundary_blocks_demonstrative_modifier_phrase_restart() -> None:
    assessment = _assess_subtitle_boundary("然后高科技", "那个版本的重量呢也非常好")

    assert assessment.forbidden is True
    assert "demonstrative_modifier_phrase" in assessment.damage_flags


def test_boundary_blocks_classifier_noun_phrase_restart() -> None:
    assessment = _assess_subtitle_boundary("这个蓄力足带来的一个反馈", "手感就非常好，就是清脆。")

    assert assessment.forbidden is True
    assert "classifier_noun_phrase" in assessment.damage_flags


def test_low_confidence_analysis_flags_demonstrative_modifier_restart() -> None:
    entries = [
        _worded_entry(0, 0.0, "然后高科技", 1.11),
        _worded_entry(1, 1.11, "那个版本的重量呢也非常好", 2.96),
    ]

    analysis = analyze_subtitle_segmentation(entries)

    assert analysis.suspicious_boundary_count == 1
    assert analysis.low_confidence_window_count == 1


def test_low_confidence_analysis_flags_classifier_noun_phrase_restart() -> None:
    entries = [
        _worded_entry(0, 0.0, "这个蓄力足带来的一个反馈", 0.67),
        _worded_entry(1, 0.67, "手感就非常好，就是清脆。", 0.67),
    ]

    analysis = analyze_subtitle_segmentation(entries)

    assert analysis.suspicious_boundary_count == 1
    assert analysis.low_confidence_window_count == 1
