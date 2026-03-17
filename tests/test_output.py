from __future__ import annotations

from roughcut.media.output import _cover_title_is_usable, _resolve_output_title_hint


def test_cover_title_rejects_generic_main_line():
    assert not _cover_title_is_usable({"top": "开箱", "main": "升级对比版", "bottom": "这次升级到位吗"})


def test_cover_title_accepts_specific_main_line():
    assert _cover_title_is_usable({"top": "LEATHERMAN", "main": "多功能工具钳", "bottom": "这次升级到位吗"})


def test_resolve_output_title_hint_skips_conflicting_theme_identity():
    resolved = _resolve_output_title_hint(
        "20260316_20260225-153519.mp4",
        content_profile={
            "subject_brand": "Loop露普",
            "subject_model": "SK05二代Pro UV版",
            "video_theme": "LEATHERMAN SK05二代Pro UV版开箱对比评测",
            "summary": "这次重点看 Loop露普 SK05二代Pro UV版 的变化。",
        },
    )

    assert resolved == "Loop露普_SK05二代Pro_UV版"
