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
    assert [item["source_fragment_index"] for item in remapped] == [0, 1]
    assert [item["source_fragment_count"] for item in remapped] == [2, 2]
