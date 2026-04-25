from roughcut.review.subtitle_quality import build_subtitle_quality_report
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.speech.subtitle_segmentation import (
    SubtitleEntry,
    analyze_subtitle_segmentation,
)


def _entry(index: int, text: str) -> SubtitleEntry:
    return SubtitleEntry(
        index=index,
        start=float(index),
        end=float(index + 1),
        text_raw=text,
        text_norm=text,
    )


def test_analyzes_generic_chinese_word_split() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "这个产"),
        _entry(1, "品不错"),
    ])

    assert analysis.generic_word_split_count == 1
    assert analysis.protected_term_split_count == 0
    assert "generic_word_split" in analysis.boundary_decisions[0].reason_tags


def test_analyzes_common_product_review_word_splits_without_jieba_dependency() -> None:
    cases = [
        ("狐蝠", "工业今年主打"),
        ("这个设", "计取向"),
        ("很有特", "色"),
        ("它的手", "感不错"),
        ("他", "妈这个位置"),
    ]
    for left, right in cases:
        analysis = analyze_subtitle_segmentation([
            _entry(0, left),
            _entry(1, right),
        ])

        assert analysis.generic_word_split_count == 1


def test_alignment_tokenizer_keeps_common_chinese_words_atomic() -> None:
    tokens = tokenize_alignment_text("我们他妈这个特色手感和狐蝠工业版本")

    assert "我们" in tokens
    assert "他妈" in tokens
    assert "特色" in tokens
    assert "手感" in tokens
    assert "狐蝠工业" in tokens


def test_allows_normal_sentence_boundary_without_word_split() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "这个产品不错"),
        _entry(1, "我们今天继续看"),
    ])

    assert analysis.generic_word_split_count == 0


def test_quality_report_warns_single_generic_word_split() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "先介"},
            {"text_final": "绍一下"},
        ],
    )

    assert report["blocking"] is False
    assert report["metrics"]["generic_word_split_count"] == 1
    assert any("普通词跨字幕截断" in reason for reason in report["warning_reasons"])


def test_quality_report_blocks_dense_generic_word_splits() -> None:
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "这个产"},
            {"text_final": "品不错"},
            {"text_final": "这个设"},
            {"text_final": "计取向"},
            {"text_final": "很有特"},
            {"text_final": "色"},
            {"text_final": "它的手"},
            {"text_final": "感不错"},
            {"text_final": "狐蝠"},
            {"text_final": "工业今年主打"},
            {"text_final": "这个产"},
            {"text_final": "品不错"},
            {"text_final": "这个设"},
            {"text_final": "计取向"},
            {"text_final": "很有特"},
            {"text_final": "色"},
            {"text_final": "它的手"},
            {"text_final": "感不错"},
            {"text_final": "这个产"},
            {"text_final": "品不错"},
        ],
    )

    assert report["blocking"] is True
    assert report["metrics"]["generic_word_split_count"] >= 10
    assert any("普通词跨字幕截断" in reason for reason in report["blocking_reasons"])
