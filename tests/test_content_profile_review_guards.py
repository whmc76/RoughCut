from roughcut.review.content_profile import (
    _build_subject_aware_unboxing_cover_hook,
    _default_engagement_question,
    _format_content_understanding_failure_reason,
    _is_generic_engagement_question,
    select_workflow_template,
)
from roughcut.review.content_profile_keywords import build_review_keywords, extract_review_keyword_tokens


def test_generic_engagement_question_detects_review_placeholder() -> None:
    assert _is_generic_engagement_question("这条视频主要在讲什么？") is True


def test_unboxing_hook_fallback_keeps_subject_anchor() -> None:
    hook = _build_subject_aware_unboxing_cover_hook(
        brand="",
        model="MT34",
        subject_type="折刀",
        theme="MT34开箱介绍与玩法上手展示",
        transcript_excerpt="",
    )
    assert hook == "MT34开箱先看这几点"


def test_default_unboxing_question_is_not_generic_price_prompt() -> None:
    preset = select_workflow_template(workflow_template="unboxing_standard", transcript_hint="")
    assert _default_engagement_question(preset) == "你最想先看哪处细节？"


def test_review_keywords_drop_timecode_and_long_sentence_noise() -> None:
    keywords = build_review_keywords(
        {
            "subject_model": "MT34",
            "subject_type": "折刀",
            "video_theme": "MT34开箱介绍与玩法上手展示",
            "transcript_excerpt": "功能 2.5]哦今天[3.0, 5.3]终于收到了年前的[6.2",
            "search_queries": [
                "折刀",
                "MT34",
                "NOC",
                "DLC",
                "MT34教程",
                "功能",
                "2.5]哦今天[3.0, 5.3]终于收到了年前的[6.2",
            ],
        }
    )
    assert keywords == ["MT34", "折刀", "NOC", "DLC", "玩法"]


def test_review_keyword_tokens_keep_suffix_compounds() -> None:
    tokens = extract_review_keyword_tokens("这是他家新出的这个Ultra版本，黑绿配色也很明显")

    assert "Ultra版本" in tokens
    assert "黑绿配色" in tokens
    assert "版本" not in tokens


def test_review_keywords_prefer_full_suffix_compounds() -> None:
    keywords = build_review_keywords(
        {
            "visible_text": "Ultra版本 黑绿配色",
            "video_theme": "狐蝠工业胸包开箱",
        }
    )

    assert "Ultra版本" in keywords
    assert "黑绿配色" in keywords


def test_content_understanding_failure_reason_preserves_provider_root_cause() -> None:
    reason = _format_content_understanding_failure_reason(
        ValueError("OpenAI API credential is not configured")
    )

    assert reason == "内容理解调用失败：OpenAI API credential is not configured"
