from roughcut.media.subtitles import remap_subtitles_to_timeline


def test_remap_subtitle_inside_keep_segment_preserves_local_offset() -> None:
    remapped = remap_subtitles_to_timeline(
        [{"index": 0, "start_time": 5.2, "end_time": 5.8, "text_final": "正常口播"}],
        [{"start": 3.0, "end": 7.0}],
    )

    assert len(remapped) == 1
    assert remapped[0]["start_time"] == 2.2
    assert remapped[0]["end_time"] == 2.8


def test_remap_subtitle_spanning_cut_uses_each_kept_fragment_local_offset() -> None:
    remapped = remap_subtitles_to_timeline(
        [{"index": 0, "start_time": 1.5, "end_time": 4.5, "text_final": "跨剪切字幕"}],
        [
            {"start": 0.0, "end": 2.0},
            {"start": 4.0, "end": 6.0},
        ],
    )

    assert [(item["start_time"], item["end_time"]) for item in remapped] == [(1.5, 2.0), (2.0, 2.5)]
    assert len({item["index"] for item in remapped}) == 2
    assert [item["source_index"] for item in remapped] == [0, 0]
    assert [item["source_indexes"] for item in remapped] == [[0], [0]]
    assert [item["source_fragment_index"] for item in remapped] == [0, 1]
    assert [item["source_fragment_count"] for item in remapped] == [2, 2]


def test_remap_subtitle_spanning_cut_splits_display_text_across_fragments() -> None:
    remapped = remap_subtitles_to_timeline(
        [{"index": 0, "start_time": 1.0, "end_time": 5.0, "text_final": "这个产品真的不错"}],
        [
            {"start": 1.0, "end": 2.0},
            {"start": 4.0, "end": 5.0},
        ],
    )

    assert [item["text_final"] for item in remapped] == ["这个产品", "真的不错"]
    assert all(item["source_text_full"] == "这个产品真的不错" for item in remapped)


def test_remap_subtitle_spanning_cut_keeps_full_text_on_dominant_fragment() -> None:
    remapped = remap_subtitles_to_timeline(
        [{"index": 30, "start_time": 156.26, "end_time": 160.72, "text_final": "06来讲它的这个锆合"}],
        [
            {"start": 152.74, "end": 156.58},
            {"start": 157.52, "end": 163.28},
        ],
    )

    assert len(remapped) == 1
    assert round(remapped[0]["start_time"], 2) == 3.84
    assert round(remapped[0]["end_time"], 2) == 7.04
    assert remapped[0]["text_final"] == "06来讲它的这个锆合"


def test_remap_subtitle_spanning_cut_uses_word_timestamps_for_fragment_text() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 5.0,
                "text_final": "这个产品真的不错",
                "words": [
                    {"word": "这个", "start": 1.0, "end": 1.6},
                    {"word": "产品", "start": 1.6, "end": 2.0},
                    {"word": "真的", "start": 4.0, "end": 4.5},
                    {"word": "不错", "start": 4.5, "end": 5.0},
                ],
            }
        ],
        [
            {"start": 1.0, "end": 1.75},
            {"start": 4.0, "end": 5.0},
        ],
    )

    assert [item["text_final"] for item in remapped] == ["这个产品", "真的不错"]


def test_remap_clipped_single_fragment_uses_word_timestamps_for_text() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 0,
                "start_time": 1.0,
                "end_time": 2.0,
                "text_final": "嗯今天看这个",
                "words": [
                    {"word": "嗯", "start": 1.0, "end": 1.08},
                    {"word": "今天", "start": 1.08, "end": 1.35},
                    {"word": "看", "start": 1.35, "end": 1.55},
                    {"word": "这个", "start": 1.55, "end": 2.0},
                ],
            }
        ],
        [{"start": 1.08, "end": 2.0}],
    )

    assert len(remapped) == 1
    assert remapped[0]["start_time"] == 0.0
    assert remapped[0]["text_final"] == "今天看这个"


def test_remap_full_single_fragment_keeps_display_text_when_word_times_are_incomplete() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 25,
                "start_time": 78.5,
                "end_time": 79.28,
                "text_final": "快递都给你轻松干穿",
                "words": [
                    {"word": "给", "start": 78.5, "end": 78.56},
                    {"word": "你", "start": 78.56, "end": 78.72},
                    {"word": "轻", "start": 78.72, "end": 78.88},
                    {"word": "松", "start": 78.88, "end": 79.04},
                    {"word": "干", "start": 79.04, "end": 79.2},
                    {"word": "穿", "start": 79.2, "end": 79.28},
                ],
            }
        ],
        [{"start": 78.5, "end": 79.28}],
    )

    assert len(remapped) == 1
    assert remapped[0]["text_final"] == "快递都给你轻松干穿"


def test_remap_reconciles_adjacent_boundary_drift_before_projection() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 3,
                "start_time": 17.12,
                "end_time": 20.0,
                "text_final": "NOC的这个发售太难了",
                "words": [
                    {"word": "NOC", "start": 17.12, "end": 17.52},
                    {"word": "的", "start": 17.52, "end": 17.6},
                    {"word": "这", "start": 17.6, "end": 17.76},
                    {"word": "个", "start": 17.76, "end": 18.32},
                    {"word": "发", "start": 18.4, "end": 18.56},
                    {"word": "售", "start": 18.56, "end": 18.72},
                    {"word": "啊", "start": 18.72, "end": 18.88},
                    {"word": "太", "start": 19.6, "end": 19.84},
                    {"word": "难", "start": 19.84, "end": 20.0},
                ],
            },
            {
                "index": 4,
                "start_time": 20.0,
                "end_time": 20.78,
                "text_final": "太难了难上加难",
                "words": [
                    {"word": "了", "start": 20.0, "end": 20.14},
                    {"word": "难", "start": 20.14, "end": 20.22},
                    {"word": "上", "start": 20.3, "end": 20.38},
                    {"word": "加", "start": 20.38, "end": 20.54},
                    {"word": "难", "start": 20.54, "end": 20.78},
                ],
            },
        ],
        [{"start": 19.6, "end": 20.78}],
    )

    assert [item["text_final"] for item in remapped] == ["太难", "了难上加难"]
    assert "".join(item["text_final"] for item in remapped) == "太难了难上加难"


def test_remap_uses_display_word_times_when_subtitle_start_includes_filler_pause() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 6,
                "start_time": 24.54,
                "end_time": 27.073,
                "text_final": "没想到",
                "words": [
                    {"word": "呃", "start": 26.06, "end": 26.3},
                    {"word": "没", "start": 26.3, "end": 26.38},
                    {"word": "想", "start": 26.38, "end": 26.54},
                    {"word": "到", "start": 26.54, "end": 26.7},
                    {"word": "啊", "start": 26.7, "end": 26.94},
                ],
            }
        ],
        [{"start": 26.22, "end": 29.5}],
    )

    assert len(remapped) == 1
    assert remapped[0]["text_final"] == "没想到"


def test_remap_matches_normalized_chinese_digits_to_display_numbers() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 30,
                "start_time": 156.26,
                "end_time": 160.72,
                "text_final": "06来讲它的这个锆合",
                "words": [
                    {"word": "零", "start": 157.6, "end": 157.68},
                    {"word": "六", "start": 157.68, "end": 157.84},
                    {"word": "来", "start": 157.84, "end": 158.0},
                    {"word": "讲", "start": 158.0, "end": 158.16},
                    {"word": "它", "start": 158.16, "end": 158.24},
                    {"word": "的", "start": 158.24, "end": 158.32},
                    {"word": "这", "start": 158.32, "end": 158.4},
                    {"word": "个", "start": 158.4, "end": 158.48},
                    {"word": "锆", "start": 158.48, "end": 158.56},
                    {"word": "合", "start": 158.56, "end": 158.64},
                ],
            }
        ],
        [{"start": 157.52, "end": 163.28}],
    )

    assert len(remapped) == 1
    assert remapped[0]["text_final"] == "06来讲它的这个锆合"


def test_remap_keeps_short_protected_phrase_when_internal_pause_is_cut() -> None:
    remapped = remap_subtitles_to_timeline(
        [
            {
                "index": 26,
                "start_time": 79.28,
                "end_time": 81.92,
                "text_final": "毫不费力",
                "words": [
                    {"word": "毫", "start": 79.28, "end": 79.44},
                    {"word": "不", "start": 81.44, "end": 81.52},
                    {"word": "费", "start": 81.52, "end": 81.76},
                    {"word": "力", "start": 81.76, "end": 81.92},
                ],
            }
        ],
        [
            {"start": 77.46, "end": 79.52},
            {"start": 81.36, "end": 87.64},
        ],
    )

    assert len(remapped) == 1
    assert remapped[0]["text_final"] == "毫不费力"
