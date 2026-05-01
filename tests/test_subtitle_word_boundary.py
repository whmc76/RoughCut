from roughcut.review.subtitle_quality import build_subtitle_quality_report
from roughcut.speech.alignment import tokenize_alignment_text
from roughcut.speech.transcript_projection import build_transcript_projection_layer
from roughcut.speech.subtitle_segmentation import (
    SubtitleEntry,
    analyze_subtitle_segmentation,
    segment_subtitles,
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


def test_alignment_tokenizer_keeps_numeric_units_atomic() -> None:
    tokens = tokenize_alignment_text("最高1500流明也支持1200lm档位")

    assert "1500流明" in tokens
    assert "1200lm" in tokens


def test_allows_normal_sentence_boundary_without_word_split() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "这个产品不错"),
        _entry(1, "我们今天继续看"),
    ])

    assert analysis.generic_word_split_count == 0


def test_analyzes_number_unit_split_as_measure_phrase() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "最高亮度1500"),
        _entry(1, "流明"),
    ])

    assert "measure_phrase_split" in analysis.boundary_decisions[0].reason_tags


def test_analyzes_number_approximation_split_as_measure_phrase() -> None:
    analysis = analyze_subtitle_segmentation([
        _entry(0, "出光范围到了270"),
        _entry(1, "多的烛光范围"),
    ])

    assert "measure_phrase_split" in analysis.boundary_decisions[0].reason_tags


def test_segmenter_keeps_number_and_lumen_unit_together() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "最高亮度1500流明还有低亮度",
            "start_time": 0.0,
            "end_time": 3.0,
            "words_json": [
                {"word": "最高亮度", "start": 0.0, "end": 0.6},
                {"word": "1500", "start": 0.6, "end": 1.0},
                {"word": "流明", "start": 1.0, "end": 1.3},
                {"word": "还有", "start": 1.3, "end": 1.8},
                {"word": "低亮度", "start": 1.8, "end": 3.0},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=8, max_duration=2.0)
    texts = [entry.text_raw for entry in result.entries]

    assert not any(
        left.endswith("1500") and right.startswith("流明")
        for left, right in zip(texts, texts[1:])
    )


def test_segmenter_uses_covering_word_times_for_number_unit_entry() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "text": "这个手电最高1500流明日用够了",
            "start_time": 0.0,
            "end_time": 14.0,
            "words_json": [
                {"word": "这个手电最高", "start": 0.2, "end": 1.4},
                {"word": "1500", "start": 8.0, "end": 8.35},
                {"word": "流明", "start": 8.35, "end": 8.7},
                {"word": "日用", "start": 12.0, "end": 12.4},
                {"word": "够了", "start": 12.4, "end": 12.9},
            ],
        },
    )()

    result = segment_subtitles([segment], max_chars=4, max_duration=1.0)
    numeric_unit_entry = next(entry for entry in result.entries if "1500流明" in entry.text_raw)

    assert numeric_unit_entry.text_raw == "1500流明"
    assert numeric_unit_entry.start == 8.0
    assert numeric_unit_entry.end == 8.7


def test_transcript_projection_uses_segmented_word_level_times() -> None:
    segment = type(
        "TranscriptRow",
        (),
        {
            "segment_index": 0,
            "text": "这个手电最高1500流明日用够了",
            "start_time": 0.0,
            "end_time": 14.0,
            "words_json": [
                {"word": "这个手电最高", "start": 0.2, "end": 1.4},
                {"word": "1500", "start": 8.0, "end": 8.35},
                {"word": "流明", "start": 8.35, "end": 8.7},
                {"word": "日用", "start": 12.0, "end": 12.4},
                {"word": "够了", "start": 12.4, "end": 12.9},
            ],
        },
    )()

    layer = build_transcript_projection_layer(
        [segment],
        segmentation_analysis={},
        split_profile={"max_chars": 4, "max_duration": 1.0},
        boundary_refine={},
        quality_report={},
    )
    numeric_unit_entry = next(entry for entry in layer.entries if "1500流明" in entry.text_raw)

    assert numeric_unit_entry.text_raw == "1500流明"
    assert numeric_unit_entry.start == 8.0
    assert numeric_unit_entry.end == 8.7


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
