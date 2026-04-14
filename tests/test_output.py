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


def test_resolve_output_title_hint_accepts_compatible_model_variant_prefix():
    resolved = _resolve_output_title_hint(
        "20260301-162038 狐蝠工业foxbat 蜜獾2代 戒备和全新黑绿款开箱对比 以及psigear粗苯胸包对比.mp4",
        content_profile={
            "subject_brand": "狐蝠工业",
            "subject_model": "LEG-16 MKII",
            "subject_type": "EDC机能包",
            "video_theme": "狐蝠工业开箱对比评测",
            "summary": "这条视频主要围绕一款EDC机能包展开，重点看开合，具体品牌型号待人工确认。",
            "cover_title": {"top": "狐蝠工业", "main": "LEG-16MKII", "bottom": "开合手感直接看"},
        },
    )

    assert resolved == "狐蝠工业_LEG-16_MKII_开箱对比评测"
