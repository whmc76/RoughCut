import pytest

from roughcut.review.content_understanding_evidence import build_evidence_bundle
from roughcut.review.content_understanding_facts import infer_content_semantic_facts
from roughcut.review.content_understanding_infer import _normalize_understanding_evidence_spans
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_profile,
    parse_content_understanding_payload,
)


class _UnexpectedLLMProvider:
    async def complete(self, *args, **kwargs):
        raise AssertionError("heuristic fact extraction should skip LLM")


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


@pytest.mark.asyncio
async def test_semantic_fact_extraction_uses_heuristic_fast_path_when_signal_is_strong() -> None:
    bundle = build_evidence_bundle(
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "今天看一下NITECORE EDC17这支EDC手电。"},
            {"start_time": 2.0, "end_time": 5.0, "text_final": "顺便和我之前常用的EDC37做个对比。"},
            {"start_time": 5.0, "end_time": 7.0, "text_final": "这支手电有UV光和1500mAh电池。"},
        ],
        transcript_excerpt="今天看一下NITECORE EDC17这支EDC手电，顺便和EDC37做个对比。",
    )

    facts = await infer_content_semantic_facts(_UnexpectedLLMProvider(), bundle)

    assert "NITECORE" in facts.brand_candidates
    assert "EDC17" in facts.model_candidates
    assert "手电筒" in facts.product_type_candidates
    assert any("NITECORE EDC17" in query for query in facts.search_expansions)


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


def test_build_evidence_bundle_emits_timed_focus_spans() -> None:
    bundle = build_evidence_bundle(
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 2.0, "text_final": "今天看一下NITECORE EDC17这支EDC手电。"},
            {"start_time": 2.0, "end_time": 5.0, "text_final": "顺便和我之前常用的EDC37做个对比。"},
            {"start_time": 5.0, "end_time": 7.0, "text_final": "这支手电有UV光和1500mAh电池。"},
        ],
        transcript_excerpt="今天看一下NITECORE EDC17这支EDC手电，顺便和EDC37做个对比。",
    )

    timed_focus_spans = bundle["semantic_fact_inputs"]["timed_focus_spans"]

    assert any(
        span["timestamp"] == "00:00-00:02" and span["type"] == "hook"
        for span in timed_focus_spans
    )
    assert any(
        span["type"] == "comparison" and span["start_time"] == 2.0 and span["end_time"] == 5.0
        for span in timed_focus_spans
    )


def test_build_evidence_bundle_uses_canonical_surface_for_semantic_inputs() -> None:
    bundle = build_evidence_bundle(
        source_name="demo.mp4",
        subtitle_items=[
            {
                "start_time": 0.0,
                "end_time": 1.5,
                "text_raw": "那个",
                "text_norm": "这是 NITECORE EDC17 手电",
                "text_final": "",
                "display_suppressed_reason": "standalone_filler",
            },
            {
                "start_time": 1.5,
                "end_time": 3.0,
                "text_raw": "顺便和 EDC37 做个对比",
                "text_norm": "顺便和 EDC37 做个对比",
                "text_final": "顺便和 EDC37 做个对比",
            },
        ],
        transcript_excerpt="这是 NITECORE EDC17 手电，顺便和 EDC37 做个对比。",
    )

    semantic_inputs = bundle["semantic_fact_inputs"]
    assert "这是 NITECORE EDC17 手电" in semantic_inputs["subtitle_lines"]
    assert any(
        span["timestamp"] == "00:00-00:01" and "NITECORE EDC17" in span["text"]
        for span in semantic_inputs["timed_focus_spans"]
    )


def test_understanding_evidence_spans_backfill_timing_from_bundle() -> None:
    bundle = build_evidence_bundle(
        source_name="demo.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 1.8, "text_final": "先讲结论这个 EDC17 到底值不值。"},
            {"start_time": 2.0, "end_time": 5.5, "text_final": "这里拿 EDC17 和 EDC37 做个对比。"},
            {"start_time": 5.8, "end_time": 7.2, "text_final": "你会怎么选欢迎留言。"},
        ],
        transcript_excerpt="先讲结论这个 EDC17 到底值不值，这里拿 EDC17 和 EDC37 做个对比。",
    )
    understanding = ContentUnderstanding(
        video_type="unboxing",
        content_domain="flashlight",
        primary_subject="NITECORE EDC17 手电",
        evidence_spans=[
            {"text": "这里拿 EDC17 和 EDC37 做个对比。", "type": "comparison"},
        ],
        needs_review=False,
    )

    normalized = _normalize_understanding_evidence_spans(understanding, bundle)

    assert normalized.evidence_spans[0]["timestamp"] == "00:02-00:05"
    assert normalized.evidence_spans[0]["start_time"] == 2.0
    assert normalized.evidence_spans[0]["end_time"] == 5.5
