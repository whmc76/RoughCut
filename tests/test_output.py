from __future__ import annotations

from roughcut.media.output import _cover_title_is_usable


def test_cover_title_rejects_generic_main_line():
    assert not _cover_title_is_usable({"top": "开箱", "main": "升级对比版", "bottom": "这次升级到位吗"})


def test_cover_title_accepts_specific_main_line():
    assert _cover_title_is_usable({"top": "LEATHERMAN", "main": "多功能工具钳", "bottom": "这次升级到位吗"})
