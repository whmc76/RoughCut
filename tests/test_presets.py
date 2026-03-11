from __future__ import annotations

from roughcut.edit.presets import get_workflow_preset, select_preset
from roughcut.review.content_profile import apply_glossary_terms, build_cover_title


def test_select_preset_by_transcript_hint():
    preset = select_preset(
        channel_profile=None,
        subject_model="FAS刀帕马年限定版",
        subject_type="EDC 刀具",
        transcript_hint="这是今年的限定版开箱",
    )
    assert preset.name == "unboxing_limited"


def test_get_workflow_preset_default():
    assert get_workflow_preset(None).name == "unboxing_default"


def test_build_cover_title_uses_profile_and_preset():
    preset = get_workflow_preset("unboxing_upgrade")
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
