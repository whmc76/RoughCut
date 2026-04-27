from roughcut.review.content_understanding_evidence import build_evidence_bundle
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_profile,
    parse_content_understanding_payload,
)


def test_source_context_and_asr_are_both_exposed_to_understanding() -> None:
    bundle = build_evidence_bundle(
        source_name="IMG_0024 lucky kiss edc弹射舱 益生菌含片.MOV",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "今天给大家介绍一个战术技能"},
            {"start_time": 2.0, "end_time": 5.0, "text_final": "这个就是可以弹出来吃的益生菌含片"},
        ],
        transcript_excerpt="今天给大家介绍一个战术技能，这个就是可以弹出来吃的益生菌含片。",
        candidate_hints={
            "source_context": {
                "video_description": "零食开箱：LuckyKiss 弹射舱益生菌含片。",
                "manual_video_summary": "这期是入口含片/零食产品，不是刀具或工具。",
            }
        },
    )

    semantic_inputs = bundle["semantic_fact_inputs"]
    assert "视频说明: 零食开箱" in "\n".join(semantic_inputs["editorial_context_lines"])
    assert "益生菌含片" in semantic_inputs["transcript_text"]
    assert "LUCKY" in semantic_inputs["entity_like_tokens"]
    assert "益生菌含片" in "".join(semantic_inputs["entity_like_tokens"])


def test_food_understanding_wins_over_edc_style_hint_in_profile_mapping() -> None:
    understanding = ContentUnderstanding(
        video_type="unboxing",
        content_domain="edc",
        primary_subject="LuckyKiss 益生菌含片",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["LuckyKiss 益生菌含片"],
            brand_candidates=["LUCKYKISS"],
            product_name_candidates=["益生菌含片"],
            product_type_candidates=["益生菌含片"],
            evidence_sentences=["标题和说明说零食开箱，ASR 持续提到益生菌含片。"],
        ),
        subject_entities=[
            SubjectEntity(kind="product", name="LuckyKiss 益生菌含片", brand="LUCKYKISS"),
        ],
        observed_entities=[
            SubjectEntity(kind="product", name="益生菌含片", brand="LUCKYKISS"),
        ],
        video_theme="LuckyKiss 弹射舱益生菌含片开箱",
        summary="这期围绕 LuckyKiss 弹射舱益生菌含片展开，EDC 只是包装描述风格。",
        confidence={"overall": 0.82},
        needs_review=False,
    )

    profile = map_content_understanding_to_profile(understanding)

    assert profile["subject_domain"] == "food"
    assert profile["subject_brand"] == "LUCKYKISS"
    assert "益生菌含片" in profile["subject_type"]


def test_dict_primary_subject_payload_maps_to_name_not_repr() -> None:
    understanding = parse_content_understanding_payload(
        {
            "video_type": "unboxing",
            "content_domain": "flashlight",
            "primary_subject": {
                "kind": "primary_product",
                "name": "傲雷掠夺者2mini战术手电",
                "brand": "OLIGHT",
                "model": "掠夺者2mini",
            },
            "subject_entities": [
                {
                    "kind": "primary_product",
                    "name": "傲雷掠夺者2mini战术手电",
                    "brand": "OLIGHT",
                    "model": "掠夺者2mini",
                }
            ],
            "video_theme": "傲雷掠夺者2mini战术手电开箱",
            "summary": "开箱傲雷掠夺者2mini战术手电。",
            "needs_review": False,
        }
    )

    profile = map_content_understanding_to_profile(understanding)

    assert "傲雷掠夺者2mini战术手电" in profile["subject_type"]
    assert "{" not in profile["subject_type"]
