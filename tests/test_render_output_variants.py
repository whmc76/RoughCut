from __future__ import annotations

import pytest

import roughcut.pipeline.steps as steps_mod


def test_shift_subtitles_for_insert_splits_crossing_item():
    shifted = steps_mod._shift_subtitles_for_insert(
        [
            {"start_time": 1.0, "end_time": 2.0, "text_final": "前段"},
            {"start_time": 4.5, "end_time": 5.5, "text_final": "跨过插入点"},
            {"start_time": 6.0, "end_time": 7.0, "text_final": "后段"},
        ],
        insert_after_sec=5.0,
        insert_duration=1.2,
    )

    assert shifted[0]["start_time"] == 1.0
    assert shifted[0]["end_time"] == 2.0
    assert shifted[1]["start_time"] == 4.5
    assert shifted[1]["end_time"] == 5.0
    assert shifted[2]["start_time"] == 6.2
    assert shifted[2]["end_time"] == 6.7
    assert shifted[3]["start_time"] == 7.2
    assert shifted[3]["end_time"] == 8.2


@pytest.mark.asyncio
async def test_map_subtitles_to_packaged_timeline_offsets_intro_and_insert(monkeypatch: pytest.MonkeyPatch):
    class DummyMeta:
        def __init__(self, duration: float) -> None:
            self.duration = duration

    async def fake_probe(path):
        name = str(path)
        if "intro" in name:
            return DummyMeta(1.5)
        if "insert" in name:
            return DummyMeta(0.8)
        return DummyMeta(0.0)

    monkeypatch.setattr(steps_mod, "probe", fake_probe)

    mapped = await steps_mod._map_subtitles_to_packaged_timeline(
        [
            {"start_time": 0.5, "end_time": 1.0, "text_final": "开头"},
            {"start_time": 3.0, "end_time": 4.0, "text_final": "后半段"},
        ],
        {
            "intro": {"path": "intro.mp4"},
            "insert": {"path": "insert.mp4", "insert_after_sec": 3.8},
        },
    )

    assert mapped[0]["start_time"] == 2.0
    assert mapped[0]["end_time"] == 2.5
    assert mapped[1]["start_time"] == 4.5
    assert mapped[1]["end_time"] == 5.3
    assert mapped[2]["start_time"] == 6.1
    assert mapped[2]["end_time"] == 6.3
