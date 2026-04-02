from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    map_content_understanding_to_legacy_profile,
)


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
