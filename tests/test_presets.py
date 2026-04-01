from __future__ import annotations

from roughcut.edit.presets import get_workflow_preset, list_workflow_template_options, select_workflow_template
from roughcut.review.content_profile import apply_glossary_terms, build_cover_title


def test_select_workflow_template_keeps_edc_tactical_for_edc_unboxing_context():
    preset = select_workflow_template(
        workflow_template=None,
        content_kind="unboxing",
        subject_domain="designer_toy",
        subject_model="FAS刀帕马年限定版",
        subject_type="EDC 刀具",
        transcript_hint="这是今年的限定版开箱",
    )
    assert preset.name == "edc_tactical"


def test_get_workflow_preset_default():
    assert get_workflow_preset(None).name == "unboxing_standard"


def test_get_workflow_preset_normalizes_legacy_unboxing_variants():
    assert get_workflow_preset("unboxing_limited").name == "unboxing_standard"
    assert get_workflow_preset("unboxing_upgrade").name == "unboxing_standard"
    assert get_workflow_preset("unboxing_default").name == "unboxing_standard"
    assert get_workflow_preset("edc_tactical").name == "edc_tactical"


def test_workflow_template_options_only_expose_single_edc_unboxing_entry():
    options = list_workflow_template_options()
    values = {item["value"] for item in options}
    labels = {item["label"] for item in options}

    assert "unboxing_standard" in values
    assert "unboxing_limited" not in values
    assert "unboxing_upgrade" not in values
    assert "edc_tactical" not in values
    assert "潮玩EDC开箱" in labels


def test_build_cover_title_uses_profile_and_preset():
    preset = get_workflow_preset("unboxing_standard")
    title = build_cover_title(
        {
            "subject_brand": "FAS刀帕",
            "subject_model": "战术版升级",
            "video_theme": "定制化全面升级",
        },
        preset,
    )
    assert title["top"] == "FAS"
    assert title["main"] == "战术版升级"
    assert title["bottom"]


def test_apply_glossary_terms_replaces_wrong_forms():
    text = apply_glossary_terms(
        "今天开箱法斯刀帕战术版",
        [{"wrong_forms": ["法斯刀帕"], "correct_form": "FAS刀帕"}],
    )
    assert text == "今天开箱FAS刀帕战术版"


def test_select_workflow_template_for_tutorial_content_kind():
    preset = select_workflow_template(
        workflow_template=None,
        content_kind="tutorial",
        subject_domain="software",
        subject_model="Premiere 自动字幕流程",
        subject_type="录屏教学",
        transcript_hint="这期我演示一下完整操作步骤和参数设置",
    )
    assert preset.name == "tutorial_standard"


def test_select_workflow_template_for_vlog():
    preset = select_workflow_template(
        workflow_template=None,
        content_kind="vlog",
        subject_domain="travel",
        subject_model="周末 citywalk",
        subject_type="Vlog 日常",
        transcript_hint="今天带你们看我一天怎么过",
    )
    assert preset.name == "vlog_daily"
