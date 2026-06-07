from roughcut.review.copy_methodology import build_copy_methodology, build_copy_methodology_prompt
from roughcut.review import intelligent_copy as ic
from roughcut.review.intelligent_copy_templates import build_platform_description
from roughcut.review import platform_copy


def test_build_copy_methodology_for_comparison_unboxing_bilibili() -> None:
    methodology = build_copy_methodology(intent="comparison_unboxing", platform_key="bilibili")

    assert methodology["archetype"] == "双版本开箱对比"
    assert "看差别" in methodology["click_drivers"]
    assert "主体点名" in methodology["title_formula"]
    assert "讲透" in methodology["banned_phrases"]
    assert "UP 主" in methodology["platform_voice_goal"]


def test_build_copy_methodology_prompt_lists_platform_specific_constraints() -> None:
    prompt = build_copy_methodology_prompt(intent="comparison_unboxing", platform_key="douyin")

    assert "内容方法论：双版本开箱对比" in prompt
    assert "平台语气目标：" in prompt
    assert "禁用表达：" in prompt


def test_copy_brief_for_platform_appends_methodology_banned_phrases() -> None:
    brief = ic._copy_brief_for_platform(
        copy_brief={
            "intent": "comparison_unboxing",
            "forbidden_terms": ["硬广"],
        },
        platform_key="bilibili",
    )

    assert brief["methodology"]["archetype"] == "双版本开箱对比"
    assert "硬广" in brief["forbidden_terms"]
    assert "方便参考" in brief["forbidden_terms"]


def test_build_platform_description_uses_methodology_shape_for_comparison_unboxing() -> None:
    description = build_platform_description(
        "bilibili",
        summary="这期把 MAXACE 美杜莎4 两个版本放在一起开箱。",
        question="你更想先看哪处细节？",
        focus_line="顶配、次顶配、细节差异",
        methodology=build_copy_methodology(intent="comparison_unboxing", platform_key="bilibili"),
        topic_subject="MAXACE美杜莎4",
    )

    assert "你更想先看哪处细节" not in description
    assert "放在一起开箱" in description
    assert "先看顶配、次顶配、细节差异" in description


def test_apply_methodology_body_repairs_rewrites_ai_explainer_body() -> None:
    repaired = platform_copy._apply_methodology_body_repairs(
        {
            "platforms": {
                "bilibili": {
                    "titles": ["MAXACE美杜莎4顶配和次顶配到底差在哪"],
                    "description": "这期把 MAXACE 美杜莎4 两个版本放在一起，逐一摆出来对比，避免单看一个版本产生偏差。",
                    "tags": ["MAXACE", "美杜莎4"],
                }
            }
        },
        prompt_brief={
            "copy_brief": {
                "intent": "comparison_unboxing",
                "summary": "这期把MAXACE美杜莎4两个版本放在一起开箱。",
                "question": "你更想先看哪处细节？",
                "focus_points": ["顶配", "次顶配", "细节差异"],
                "topic_subject": "MAXACE美杜莎4",
            }
        },
        content_profile={"subject_brand": "MAXACE", "subject_model": "美杜莎4"},
        fact_sheet=None,
        target_platforms=["bilibili"],
    )

    body = repaired["platforms"]["bilibili"]["description"]
    assert "避免单看一个版本产生偏差" not in body
    assert "放在一起开箱" in body
    assert "先看顶配、次顶配、细节差异" in body
    assert repaired["platforms"]["bilibili"]["copy_methodology_repair"]["applied"] is True


def test_apply_methodology_title_repairs_strengthens_anchor_and_kuaishou_tone() -> None:
    repaired = platform_copy._apply_methodology_title_repairs(
        {
            "platforms": {
                "kuaishou": {
                    "titles": ["双版本上手一摸，手感差别就出来了", "顶配次顶配放一块儿掂掂", "谁更合手上手就知道"],
                    "description": "略",
                    "tags": ["MAXACE", "美杜莎4"],
                }
            }
        },
        content_profile={"subject_brand": "MAXACE", "subject_model": "美杜莎4", "subject_type": "EDC跳刀"},
        target_platforms=["kuaishou"],
        copy_style="attention_grabbing",
    )

    titles = repaired["platforms"]["kuaishou"]["titles"]
    assert len(titles) == 3
    assert any("MAXACE" in title or "美杜莎4" in title for title in titles[:2])
    assert any("给你们看" in title or "真东西" in title for title in titles)
    assert all(not title.endswith(("挺", "一", "差")) for title in titles)
