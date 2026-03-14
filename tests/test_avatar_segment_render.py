from __future__ import annotations

from roughcut.pipeline.steps import _remap_avatar_segments_to_timeline


def test_remap_avatar_segments_to_timeline_maps_to_kept_ranges():
    segments = [
        {
            "segment_id": "avatar_seg_001",
            "start_time": 10.0,
            "end_time": 14.0,
            "duration_sec": 4.0,
            "script": "测试片段",
            "video_local_path": "segment.mp4",
        }
    ]
    keep_segments = [
        {"start": 0.0, "end": 8.0},
        {"start": 10.0, "end": 20.0},
    ]

    remapped = _remap_avatar_segments_to_timeline(segments, keep_segments)

    assert len(remapped) == 1
    assert remapped[0]["start_time"] == 8.0
    assert remapped[0]["end_time"] == 12.0
