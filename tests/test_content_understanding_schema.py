from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_legacy_profile,
    parse_content_semantic_facts_payload,
    parse_content_understanding_payload,
    serialize_content_understanding_payload,
)
from roughcut.review.content_understanding_orchestrator import build_content_understanding_orchestration_context


def test_map_content_understanding_to_legacy_profile_keeps_non_product_subjects_sparse():
    understanding = ContentUnderstanding(
        video_type="tutorial",
        content_domain="ai",
        primary_subject="ComfyUI 工作流",
        subject_entities=[
            SubjectEntity(kind="software", name="ComfyUI", brand="", model="工作流")
        ],
        video_theme="ComfyUI 节点编排与工作流实操",
        summary="这条视频主要演示 ComfyUI 工作流搭建和节点编排。",
        hook_line="工作流直接讲透",
        engagement_question="你更想看哪类节点工作流？",
        search_queries=["ComfyUI workflow", "ComfyUI 节点编排"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.82},
        needs_review=False,
        review_reasons=[],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_kind"] == "tutorial"
    assert legacy["subject_domain"] == "ai"
    assert legacy["subject_type"] == "ComfyUI 工作流"
    assert legacy["subject_brand"] == ""
    assert legacy["subject_model"] == ""
    assert legacy["content_understanding"]["semantic_facts"]["brand_candidates"] == []


def test_map_content_understanding_to_legacy_profile_drops_unknown_placeholder_fields():
    understanding = ContentUnderstanding(
        video_type="unknown",
        content_domain="unknown",
        primary_subject="unknown",
        subject_entities=[],
        video_theme="待确认",
        summary="这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。",
        hook_line="内容待人工确认",
        engagement_question="这条视频主要在讲什么？",
        search_queries=[],
        evidence_spans=[],
        uncertainties=["证据不足"],
        confidence={},
        needs_review=True,
        review_reasons=["证据不足"],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_kind"] == ""
    assert legacy["subject_domain"] == ""
    assert legacy["subject_type"] == ""
    assert legacy["video_theme"] == ""


def test_map_content_understanding_to_legacy_profile_exposes_semantic_facts_for_review_debugging():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="HSJUN × BOLTBOAT 游刃机能双肩包",
        semantic_facts=ContentSemanticFacts(
            brand_candidates=["HSJUN", "BOLTBOAT"],
            model_candidates=["游刃"],
            product_name_candidates=["游刃"],
            product_type_candidates=["机能双肩包"],
            entity_candidates=["HSJUN × BOLTBOAT 游刃"],
            collaboration_pairs=["HSJUN × BOLTBOAT"],
            search_expansions=["HSJUN BOLTBOAT 游刃"],
            evidence_sentences=["这是 hsjun 和 boltboat 联名的包，它叫游刃"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="游刃机能双肩包", brand="HSJUN × BOLTBOAT", model="游刃")],
        video_theme="联名机能双肩包对比评测",
        summary="视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
        hook_line="联名机能包上身实测",
        engagement_question="你更在意结构还是背负？",
        search_queries=["HSJUN BOLTBOAT 游刃"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.74},
        needs_review=False,
        review_reasons=[],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["content_understanding"]["semantic_facts"]["brand_candidates"] == ["HSJUN", "BOLTBOAT"]
    assert legacy["content_understanding"]["semantic_facts"]["collaboration_pairs"] == ["HSJUN × BOLTBOAT"]


def test_map_content_understanding_to_legacy_profile_prefers_resolved_entities():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="船长联名包",
        subject_entities=[SubjectEntity(kind="product", name="船长联名包")],
        observed_entities=[SubjectEntity(kind="product", name="船长联名包", brand="船长", model="游刃")],
        resolved_entities=[
            SubjectEntity(
                kind="product",
                name="HSJUN × BOLTBOAT 游刃机能双肩包",
                brand="HSJUN × BOLTBOAT",
                model="游刃",
            )
        ],
        resolved_primary_subject="HSJUN × BOLTBOAT 游刃机能双肩包",
        video_theme="联名机能双肩包对比评测",
        summary="视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
        hook_line="联名机能包上身实测",
        engagement_question="你更在意结构还是背负？",
        search_queries=["HSJUN BOLTBOAT 游刃"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.84},
        needs_review=True,
        review_reasons=["视频原始称呼与归一化实体存在差异"],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["subject_type"] == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert legacy["subject_brand"] == "HSJUN × BOLTBOAT"
    assert legacy["subject_model"] == "游刃"


def test_map_content_understanding_to_legacy_profile_builds_branded_subject_type_from_identity():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="flashlight",
        primary_subject="SLIM2 ULTRA版手电筒",
        subject_entities=[
            SubjectEntity(
                kind="product",
                name="SLIM2 ULTRA版手电筒",
                brand="OLIGHT",
                model="SLIM2 ULTRA",
            )
        ],
        video_theme="手电筒版本对比",
        summary="视频围绕 SLIM2 ULTRA版手电筒展开版本对比。",
        hook_line="SLIM2 ULTRA这次升级值不值",
        engagement_question="你会选 ULTRA 还是标准版？",
        search_queries=["OLIGHT SLIM2 ULTRA"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.79},
        needs_review=True,
        review_reasons=["品牌型号需继续核验"],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["subject_brand"] == "OLIGHT"
    assert legacy["subject_model"] == "SLIM2 ULTRA"
    assert legacy["subject_type"] == "OLIGHT SLIM2 ULTRA版手电筒"
    assert legacy["content_understanding"]["primary_subject"] == "OLIGHT SLIM2 ULTRA版手电筒"


def test_map_content_understanding_to_legacy_profile_recovers_brand_from_observed_alias_context():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="flashlight",
        primary_subject="SLIM2代ULTRA手电筒",
        subject_entities=[
            SubjectEntity(
                kind="product",
                name="SLIM2代ULTRA手电筒",
                brand="",
                model="SLIM2 ULTRA",
            )
        ],
        observed_entities=[
            SubjectEntity(kind="", name="奥雷"),
            SubjectEntity(kind="", name="SLIM2代ULTRA版本"),
        ],
        video_theme="手电筒版本对比",
        summary="视频围绕 SLIM2 ULTRA 手电筒展开对比。",
        hook_line="ULTRA版值不值",
        engagement_question="你会选哪个版本？",
        search_queries=["SLIM2 ULTRA 手电筒"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.71},
        needs_review=True,
        review_reasons=["品牌需继续核验"],
    )

    legacy = map_content_understanding_to_legacy_profile(understanding)

    assert legacy["subject_brand"] == "OLIGHT"
    assert legacy["subject_type"].startswith("OLIGHT ")


def test_content_understanding_payload_and_orchestrator_preserve_capability_matrix_and_trace():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="demo subject",
        capability_matrix={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
        orchestration_trace=["capability_resolution", "fact_extraction", "final_understanding"],
    )

    payload = serialize_content_understanding_payload(understanding)
    orchestration_context = build_content_understanding_orchestration_context(
        {
            "source_name": "demo.mp4",
            "capability_matrix": understanding.capability_matrix,
            "orchestration_trace": understanding.orchestration_trace,
        }
    )

    assert payload["capability_matrix"] == understanding.capability_matrix
    assert payload["orchestration_trace"] == understanding.orchestration_trace
    assert orchestration_context["capability_matrix"] == understanding.capability_matrix
    assert orchestration_context["orchestration_trace"] == understanding.orchestration_trace


def test_content_understanding_payload_round_trips_capability_matrix_and_trace_through_parser():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="demo subject",
        conflicts=["primary_subject", "video_theme"],
        capability_matrix={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
        orchestration_trace=["capability_resolution", "fact_extraction", "final_understanding"],
    )

    payload = serialize_content_understanding_payload(understanding)
    reparsed = parse_content_understanding_payload(payload)

    assert reparsed.capability_matrix == understanding.capability_matrix
    assert reparsed.orchestration_trace == understanding.orchestration_trace
    assert reparsed.conflicts == understanding.conflicts


def test_parse_content_semantic_facts_payload_preserves_role_candidates():
    facts = parse_content_semantic_facts_payload(
        {
            "primary_subject_candidates": ["机能双肩包", "机能双肩包"],
            "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
            "comparison_subject_candidates": ["上一代机能包", "竞品双肩包"],
            "supporting_product_candidates": ["配套收纳包"],
            "component_candidates": ["背负系统", "分仓结构"],
            "aspect_candidates": ["背负", "结构"],
            "brand_candidates": ["HSJUN"],
        }
    )

    assert facts.primary_subject_candidates == ["机能双肩包"]
    assert facts.supporting_subject_candidates == ["HSJUN", "BOLTBOAT"]
    assert facts.comparison_subject_candidates == ["上一代机能包", "竞品双肩包"]
    assert facts.supporting_product_candidates == ["配套收纳包"]
    assert facts.component_candidates == ["背负系统", "分仓结构"]
    assert facts.aspect_candidates == ["背负", "结构"]


def test_parse_content_semantic_facts_payload_unwraps_stringified_mapping_candidates():
    facts = parse_content_semantic_facts_payload(
        {
            "primary_subject_candidates": [
                "{'name': '瑞特拆卸工具', 'description': '原型刀具'}",
                "{'name': '瑞特拆卸工具', 'description': '原型刀具'}",
            ],
            "search_expansions": [
                "{'name': '冰型贴片刀具', 'aliases': ['冰型贴片', '定制刀具']}",
            ],
        }
    )

    assert facts.primary_subject_candidates == ["瑞特拆卸工具"]
    assert facts.search_expansions == ["冰型贴片刀具"]


def test_parse_content_understanding_payload_unwraps_stringified_subject_entity_mapping():
    understanding = parse_content_understanding_payload(
        {
            "video_type": "product_review",
            "content_domain": "edc",
            "primary_subject": "瑞特拆卸工具",
            "subject_entities": [
                "{'kind': 'product', 'name': '瑞特拆卸工具', 'brand': 'REATE'}",
            ],
            "observed_entities": [
                "{'name': '瑞特拆卸工具'}",
            ],
        }
    )

    assert understanding.subject_entities == [SubjectEntity(kind="product", name="瑞特拆卸工具", brand="REATE", model="")]
    assert understanding.observed_entities == [SubjectEntity(kind="", name="瑞特拆卸工具", brand="", model="")]
