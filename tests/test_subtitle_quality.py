from __future__ import annotations

from roughcut.review.subtitle_quality import (
    ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT,
    build_subtitle_quality_report,
    build_subtitle_quality_report_from_items,
)


class _Item:
    def __init__(self, *, text_final: str) -> None:
        self.text_raw = text_final
        self.text_norm = text_final
        self.text_final = text_final


def test_build_subtitle_quality_report_flags_hotword_errors_and_fragments():
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "家了这个我们赶紧开枪吧。"},
            {"text_final": "四顶配镜面版本。"},
            {"text_final": "你"},
            {"text_final": "开始吧"},
        ],
        source_name="20260213-125119 开箱NOC MT34 也叫S06mini 次顶配钢马镜面版.mp4",
        content_profile={"summary": "这条视频主要围绕NOC MT34展开，适合后续做搜索校验、字幕纠错和剪辑包装。"},
    )

    assert report["blocking"] is True
    assert report["metrics"]["bad_term_counts"]["hotword_unboxing_misheard"] == 1
    assert report["metrics"]["bad_term_counts"]["hotword_trim_variant_misheard"] == 1
    assert report["metrics"]["short_fragment_count"] >= 2
    assert any("摘要模板化" in reason for reason in report["blocking_reasons"])


def test_build_subtitle_quality_report_detects_identity_missing_in_profile():
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "这次重点看阵风的背负和分仓。"},
            {"text_final": "它用了很多机能设计。"},
        ],
        source_name="20260301-171940 狐蝠工业foxbat 阵风 机能双肩包使用体验.mp4",
        content_profile={"summary": "这条视频主要围绕一款EDC机能包展开。"},
    )

    assert report["metrics"]["identity_expected"] is True
    assert report["metrics"]["identity_missing"] is True
    assert any("品牌型号" in reason for reason in report["blocking_reasons"])


def test_build_subtitle_quality_report_keeps_informative_summary_with_generic_opening():
    report = build_subtitle_quality_report(
        subtitle_items=[
            {"text_final": "这期演示剪映里怎么批量处理字幕样式。"},
            {"text_final": "最后导出预设方便下次复用。"},
        ],
        source_name="source.mp4",
        content_profile={"summary": "这条视频主要围绕剪映字幕工作流展开，重点讲清批量调样式、检查错位和复用预设的完整步骤。"},
    )

    assert report["blocking"] is False
    assert report["metrics"]["summary_generic_hits"] == []


def test_build_subtitle_quality_report_from_items_uses_model_fields():
    report = build_subtitle_quality_report_from_items(
        subtitle_items=[_Item(text_final="EDC17对比EDC37。"), _Item(text_final="这次不是幺七。")],
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        content_profile={"content_subject": "NITECORE EDC17 · EDC手电"},
    )

    assert ARTIFACT_TYPE_SUBTITLE_QUALITY_REPORT == "subtitle_quality_report"
    assert report["metrics"]["bad_term_counts"]["hotword_numeric_edc17_uncorrected"] == 1
