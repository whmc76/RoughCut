from __future__ import annotations

from types import SimpleNamespace

import pytest

from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity
from roughcut.review.content_understanding_resolution import should_run_entity_resolution
from roughcut.review.content_understanding_verify import (
    HybridVerificationBundle,
    build_hybrid_verification_bundle,
    verify_content_understanding,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def as_json(self):
        return self._payload


class FakeProvider:
    def __init__(self, payload):
        self._payload = payload

    async def complete(self, *args, **kwargs):
        return FakeResponse(self._payload)


@pytest.mark.asyncio
async def test_build_hybrid_verification_bundle_keeps_online_and_database_hits():
    async def fake_online(*, search_queries):
        assert search_queries == ["ComfyUI workflow"]
        return [SimpleNamespace(title="ComfyUI 官方文档")]

    async def fake_internal(*, search_queries):
        assert search_queries == ["ComfyUI workflow"]
        return [SimpleNamespace(primary_subject="ComfyUI 工作流")]

    bundle = await build_hybrid_verification_bundle(
        search_queries=["ComfyUI workflow"],
        online_search=fake_online,
        internal_search=fake_internal,
    )

    assert bundle.online_results[0].title == "ComfyUI 官方文档"
    assert bundle.database_results[0].primary_subject == "ComfyUI 工作流"


@pytest.mark.asyncio
async def test_verify_content_understanding_merges_search_queries_with_semantic_fact_expansions():
    captured_queries: list[str] = []

    async def fake_online(*, search_queries):
        captured_queries.extend(search_queries)
        return []

    async def fake_internal(*, search_queries):
        return []

    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="flashlight",
        primary_subject="SLIM2代ULTRA手电筒",
        semantic_facts=ContentSemanticFacts(
            search_expansions=["SLIM2 ULTRA", "SLIM2 PRO", "SLIM2代ULTRA版本"]
        ),
        subject_entities=[SubjectEntity(kind="product", name="SLIM2代ULTRA手电筒")],
        search_queries=["SLIM2 ULTRA手电筒"],
        needs_review=True,
    )

    await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这是 slim2 的 ultra 版本"},
        online_search=fake_online,
        internal_search=fake_internal,
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "flashlight",
                "primary_subject": "SLIM2代ULTRA手电筒",
                "subject_entities": [{"kind": "product", "name": "SLIM2代ULTRA手电筒"}],
                "observed_entities": [{"kind": "product", "name": "SLIM2代ULTRA版本"}],
                "resolved_entities": [],
                "resolved_primary_subject": "",
                "entity_resolution_map": [],
                "video_theme": "手电筒选购与保值性对比",
                "summary": "视频围绕 SLIM2代ULTRA手电筒展开选购对比。",
                "hook_line": "手电版本怎么选",
                "engagement_question": "你更在意保值还是亮度？",
                "search_queries": ["SLIM2 ULTRA手电筒"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.8},
                "needs_review": False,
                "review_reasons": [],
            }
        ),
    )

    assert captured_queries == [
        "SLIM2 ULTRA手电筒",
        "SLIM2 ULTRA",
        "SLIM2 PRO",
        "SLIM2代ULTRA版本",
    ]


@pytest.mark.asyncio
async def test_verify_content_understanding_keeps_current_conclusion_when_hybrid_search_conflicts():
    understanding = ContentUnderstanding(
        video_type="tutorial",
        content_domain="ai",
        primary_subject="ComfyUI 工作流",
        subject_entities=[SubjectEntity(kind="software", name="ComfyUI")],
        video_theme="ComfyUI 节点编排与工作流实操",
        summary="这条视频主要演示 ComfyUI 工作流搭建。",
        hook_line="工作流直接讲透",
        engagement_question="你还想看哪类节点编排？",
        search_queries=["ComfyUI workflow"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.82},
        needs_review=False,
        review_reasons=[],
    )
    verification_payload = {
        "video_type": "review",
        "content_domain": "hardware",
        "primary_subject": "相机开箱",
        "subject_entities": [{"kind": "product", "name": "相机"}],
        "video_theme": "相机测评",
        "summary": "这条视频主要介绍相机。",
        "hook_line": "开箱看看",
        "engagement_question": "你想看哪台相机？",
        "search_queries": ["相机 开箱"],
        "evidence_spans": [{"source": "search", "text": "相机"}],
        "uncertainties": ["可能是开箱"],
        "confidence": {"overall": 0.96},
        "needs_review": False,
        "review_reasons": [],
    }

    bundle = HybridVerificationBundle(
        search_queries=["ComfyUI workflow"],
        online_results=[{"title": "相机开箱"}],
        database_results=[{"primary_subject": "相机"}],
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={},
        verification_bundle=bundle,
        provider=FakeProvider(verification_payload),
    )

    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
    assert result.subject_entities == [SubjectEntity(kind="software", name="ComfyUI")]
    assert "video_type" in result.conflicts
    assert "primary_subject" in result.conflicts
    assert result.needs_review is True
    assert any("弱佐证" in reason or "冲突" in reason for reason in result.review_reasons)


@pytest.mark.asyncio
async def test_verify_content_understanding_stays_conservative_without_direct_evidence():
    understanding = ContentUnderstanding(
        video_type="tutorial",
        content_domain="ai",
        primary_subject="ComfyUI 工作流",
        subject_entities=[SubjectEntity(kind="software", name="ComfyUI")],
        video_theme="ComfyUI 节点编排与工作流实操",
        summary="这条视频主要演示 ComfyUI 工作流搭建。",
        hook_line="工作流直接讲透",
        engagement_question="你还想看哪类节点编排？",
        search_queries=["ComfyUI workflow"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.82},
        needs_review=False,
        review_reasons=[],
    )
    verification_payload = {
        "video_type": "review",
        "content_domain": "hardware",
        "primary_subject": "相机开箱",
        "subject_entities": [{"kind": "product", "name": "相机"}],
        "video_theme": "相机测评",
        "summary": "这条视频主要介绍相机。",
        "hook_line": "开箱看看",
        "engagement_question": "你想看哪台相机？",
        "search_queries": ["相机 开箱"],
        "evidence_spans": [{"source": "search", "text": "相机"}],
        "uncertainties": ["可能是开箱"],
        "confidence": {"overall": 0.96},
        "needs_review": False,
        "review_reasons": [],
    }

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={},
        verification_bundle=HybridVerificationBundle(
            search_queries=["ComfyUI workflow"],
            online_results=[],
            database_results=[],
        ),
        provider=FakeProvider(verification_payload),
    )

    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
    assert result.needs_review is True
    assert "缺少直接视频证据" in " ".join(result.review_reasons)


@pytest.mark.asyncio
async def test_verify_content_understanding_can_promote_resolved_entity_over_observed_alias():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="船长联名包",
        subject_entities=[SubjectEntity(kind="product", name="船长联名包", brand="船长", model="游刃")],
        observed_entities=[SubjectEntity(kind="product", name="船长联名包", brand="船长", model="游刃")],
        video_theme="联名机能双肩包对比评测",
        summary="视频围绕船长联名包展开对比评测。",
        hook_line="联名机能包上身实测",
        engagement_question="你更在意结构还是背负？",
        search_queries=["船长 游刃 双肩包"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.7},
        needs_review=True,
        review_reasons=[],
    )
    verification_payload = {
        "video_type": "product_review",
        "content_domain": "bags",
        "primary_subject": "船长联名包",
        "resolved_primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
        "subject_entities": [{"kind": "product", "name": "船长联名包", "brand": "船长", "model": "游刃"}],
        "observed_entities": [{"kind": "product", "name": "船长联名包", "brand": "船长", "model": "游刃"}],
        "resolved_entities": [{"kind": "product", "name": "HSJUN × BOLTBOAT 游刃机能双肩包", "brand": "HSJUN × BOLTBOAT", "model": "游刃"}],
        "entity_resolution_map": [{"observed_name": "船长联名包", "resolved_name": "HSJUN × BOLTBOAT 游刃机能双肩包", "confidence": 0.93, "reason": "在线搜索和内部记录稳定指向 BOLTBOAT"}],
        "video_theme": "联名机能双肩包对比评测",
        "summary": "视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
        "hook_line": "联名机能包上身实测",
        "engagement_question": "你更在意结构还是背负？",
        "search_queries": ["HSJUN BOLTBOAT 游刃"],
        "evidence_spans": [],
        "uncertainties": ["视频里更常用船长这个叫法"],
        "confidence": {"overall": 0.86, "resolution": 0.93},
        "needs_review": True,
        "review_reasons": ["原始称呼与归一化实体存在差异"],
    }

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这是船长联名的包，它叫游刃"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["船长 游刃 双肩包"],
            online_results=[{"title": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
            database_results=[{"primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
        ),
        provider=FakeProvider(verification_payload),
    )

    assert result.primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert result.needs_review is True


@pytest.mark.asyncio
async def test_verify_content_understanding_keeps_observed_entity_when_resolution_is_weak():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="船长联名包",
        subject_entities=[SubjectEntity(kind="product", name="船长联名包", brand="船长", model="游刃")],
        observed_entities=[SubjectEntity(kind="product", name="船长联名包", brand="船长", model="游刃")],
        video_theme="联名机能双肩包对比评测",
        summary="视频围绕船长联名包展开对比评测。",
        hook_line="联名机能包上身实测",
        engagement_question="你更在意结构还是背负？",
        search_queries=["船长 游刃 双肩包"],
        evidence_spans=[],
        uncertainties=[],
        confidence={"overall": 0.7},
        needs_review=True,
        review_reasons=[],
    )
    verification_payload = {
        "video_type": "product_review",
        "content_domain": "bags",
        "primary_subject": "船长联名包",
        "resolved_primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
        "subject_entities": [{"kind": "product", "name": "船长联名包", "brand": "船长", "model": "游刃"}],
        "observed_entities": [{"kind": "product", "name": "船长联名包", "brand": "船长", "model": "游刃"}],
        "resolved_entities": [{"kind": "product", "name": "HSJUN × BOLTBOAT 游刃机能双肩包", "brand": "HSJUN × BOLTBOAT", "model": "游刃"}],
        "entity_resolution_map": [{"observed_name": "船长联名包", "resolved_name": "HSJUN × BOLTBOAT 游刃机能双肩包", "confidence": 0.42, "reason": "只有弱匹配"}],
        "video_theme": "联名机能双肩包对比评测",
        "summary": "视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
        "hook_line": "联名机能包上身实测",
        "engagement_question": "你更在意结构还是背负？",
        "search_queries": ["HSJUN BOLTBOAT 游刃"],
        "evidence_spans": [],
        "uncertainties": ["只能弱匹配到外部实体"],
        "confidence": {"overall": 0.68, "resolution": 0.42},
        "needs_review": True,
        "review_reasons": ["外部消歧证据偏弱"],
    }

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这是船长联名的包，它叫游刃"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["船长 游刃 双肩包"],
            online_results=[{"title": "疑似相关结果"}],
            database_results=[],
        ),
        provider=FakeProvider(verification_payload),
    )

    assert result.primary_subject == "船长联名包"
    assert result.needs_review is True
    assert result.resolved_primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert len(result.resolved_entities) == 1
    assert result.resolved_entities[0].name == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert result.resolved_entities[0].brand == "HSJUN × BOLTBOAT"
    assert result.resolved_entities[0].model == "游刃"
    assert len(result.entity_resolution_map) == 1
    assert result.entity_resolution_map[0].observed_name == "船长联名包"
    assert result.entity_resolution_map[0].resolved_name == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert result.entity_resolution_map[0].confidence == 0.42
    assert result.entity_resolution_map[0].reason == "只有弱匹配"


def test_should_run_entity_resolution_skips_when_entities_are_aligned():
    base = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="船长联名包",
        subject_entities=[SubjectEntity(kind="product", name="船长联名包")],
        observed_entities=[SubjectEntity(kind="product", name="船长联名包")],
    )
    candidate = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="船长联名包",
        subject_entities=[SubjectEntity(kind="product", name="船长联名包")],
        observed_entities=[SubjectEntity(kind="product", name="船长联名包")],
        resolved_primary_subject="",
        resolved_entities=[],
    )

    assert should_run_entity_resolution(
        understanding=base,
        candidate=candidate,
        evidence_bundle={"transcript_excerpt": "这是船长联名的包"},
        verification_bundle=HybridVerificationBundle(),
    ) is False


@pytest.mark.asyncio
async def test_verify_content_understanding_only_runs_resolution_when_conflicts_exist():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="gear",
        primary_subject="船长联名包",
        observed_entities=[SubjectEntity(kind="product", name="船长联名包")],
        subject_entities=[SubjectEntity(kind="product", name="船长联名包")],
        search_queries=["船长 游刃 双肩包"],
        confidence={"overall": 0.78},
        needs_review=False,
    )
    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这是船长联名的包"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["船长 游刃 双肩包"],
            online_results=[{"title": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
            database_results=[{"primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包"}],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "gear",
                "primary_subject": "船长联名包",
                "subject_entities": [{"kind": "product", "name": "船长联名包"}],
                "observed_entities": [{"kind": "product", "name": "船长联名包"}],
                "resolved_entities": [
                    {"kind": "product", "name": "HSJUN × BOLTBOAT 游刃机能双肩包", "brand": "HSJUN × BOLTBOAT", "model": "游刃"}
                ],
                "resolved_primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
                "entity_resolution_map": [
                    {
                        "observed_name": "船长联名包",
                        "resolved_name": "HSJUN × BOLTBOAT 游刃机能双肩包",
                        "confidence": 0.93,
                        "reason": "在线搜索和内部记录稳定指向 BOLTBOAT",
                    }
                ],
                "video_theme": "联名机能双肩包对比评测",
                "summary": "视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
                "hook_line": "联名机能包上身实测",
                "engagement_question": "你更在意结构还是背负？",
                "search_queries": ["HSJUN BOLTBOAT 游刃"],
                "evidence_spans": [],
                "uncertainties": ["视频里更常用船长这个叫法"],
                "confidence": {"overall": 0.84, "resolution": 0.93},
                "needs_review": True,
                "review_reasons": ["原始称呼与归一化实体存在差异"],
            }
        ),
    )

    assert result.entity_resolution_map
    assert result.resolved_primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"


@pytest.mark.asyncio
async def test_verify_content_understanding_normalizes_observed_entities_when_base_only_has_components():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="户外背包",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["户外背包"],
            component_candidates=["背包背负系统", "肩带系统"],
            aspect_candidates=["背负调节"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="户外背包")],
        observed_entities=[SubjectEntity(kind="component", name="背包背负系统")],
        video_theme="户外背包背负系统功能展示与调节方式演示",
        summary="视频围绕户外背包展开，并重点展示背负系统与调节方式。",
        hook_line="背包背负调节细讲",
        engagement_question="你更在意背负还是调节？",
        search_queries=["户外背包 背负调节"],
        confidence={"overall": 0.76},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这期主要看这个户外背包和它的背负系统调节方式"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["户外背包 背负调节"],
            online_results=[],
            database_results=[],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "bags",
                "primary_subject": "户外背包",
                "subject_entities": [{"kind": "product", "name": "户外背包"}],
                "observed_entities": [{"kind": "component", "name": "背包背负系统"}],
                "resolved_entities": [],
                "resolved_primary_subject": "",
                "entity_resolution_map": [],
                "video_theme": "户外背包背负系统功能展示与调节方式演示",
                "summary": "视频围绕户外背包展开，并重点展示背负系统与调节方式。",
                "hook_line": "背包背负调节细讲",
                "engagement_question": "你更在意背负还是调节？",
                "search_queries": ["户外背包 背负调节"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.76},
                "needs_review": True,
                "review_reasons": [],
            }
        ),
    )

    assert result.observed_entities[0].name == "户外背包"


@pytest.mark.asyncio
async def test_verify_content_understanding_does_not_promote_component_biased_resolved_primary_subject():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="户外徒步背包",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["户外徒步背包"],
            component_candidates=["背负系统", "快速释放拉带"],
            aspect_candidates=["快速调节", "省力背负"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="户外徒步背包")],
        observed_entities=[SubjectEntity(kind="product", name="背包"), SubjectEntity(kind="component", name="背负系统")],
        video_theme="户外徒步背包背负系统功能展示与使用指南",
        summary="视频围绕户外徒步背包展开，并重点展示背负系统与调节方式。",
        hook_line="背包背负调节细讲",
        engagement_question="你更在意背负还是调节？",
        search_queries=["户外徒步背包 背负系统"],
        confidence={"overall": 0.8},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这期主要看这个背包和它的背负系统快速调节方式"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["户外徒步背包 背负系统"],
            online_results=[{"title": "户外背包背负系统调节指南"}],
            database_results=[],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "bags",
                "primary_subject": "户外徒步背包",
                "subject_entities": [{"kind": "product", "name": "户外徒步背包"}],
                "observed_entities": [{"kind": "product", "name": "背包"}, {"kind": "component", "name": "背负系统"}],
                "resolved_entities": [
                    {"kind": "产品类别", "name": "户外徒步背包"},
                    {"kind": "功能系统", "name": "背负系统"},
                ],
                "resolved_primary_subject": "户外背包背负系统快速调节功能",
                "entity_resolution_map": [
                    {
                        "observed_name": "背包",
                        "resolved_name": "户外徒步背包",
                        "confidence": 0.93,
                        "reason": "检索结果稳定指向徒步背包，但同时强调背负系统功能",
                    }
                ],
                "video_theme": "户外徒步背包背负系统的快速调节功能展示与省力背负体验",
                "summary": "视频主要展示户外徒步背包的背负系统和快速调节方式。",
                "hook_line": "背包背负调节细讲",
                "engagement_question": "你更在意背负还是调节？",
                "search_queries": ["户外徒步背包 背负系统 快速调节"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.88, "resolution": 0.93},
                "needs_review": True,
                "review_reasons": ["核验结果更强调功能系统而非主产品"],
            }
        ),
    )

    assert result.primary_subject == "户外徒步背包"
    assert result.resolved_primary_subject == ""


@pytest.mark.asyncio
async def test_verify_content_understanding_does_not_promote_product_plus_component_compound_resolved_primary_subject():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="徒步背包",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["徒步背包", "徒步背包背负系统"],
            component_candidates=["背负系统", "肩带系统"],
            product_type_candidates=["双肩包"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="徒步背包")],
        observed_entities=[SubjectEntity(kind="product", name="徒步背包"), SubjectEntity(kind="component", name="背负系统")],
        video_theme="徒步背包背负系统功能演示",
        summary="视频围绕徒步背包展开，并重点展示背负系统。",
        hook_line="背负系统细看",
        engagement_question="你更在意背负还是容量？",
        search_queries=["徒步背包 背负系统"],
        confidence={"overall": 0.8},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这期主要看这个徒步背包和它的背负系统"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["徒步背包 背负系统"],
            online_results=[{"title": "徒步背包背负系统调节指南"}],
            database_results=[{"primary_subject": "徒步背包"}],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "bags",
                "primary_subject": "徒步背包",
                "subject_entities": [{"kind": "product", "name": "徒步背包"}],
                "observed_entities": [{"kind": "product", "name": "徒步背包"}, {"kind": "component", "name": "背负系统"}],
                "resolved_entities": [
                    {"kind": "产品类别", "name": "徒步背包"},
                    {"kind": "功能系统", "name": "背负系统"},
                ],
                "resolved_primary_subject": "徒步背包背负系统",
                "entity_resolution_map": [
                    {
                        "observed_name": "徒步背包",
                        "resolved_name": "徒步背包背负系统",
                        "confidence": 0.82,
                        "reason": "检索结果频繁提到背负系统",
                    }
                ],
                "video_theme": "徒步背包背负系统功能演示",
                "summary": "视频围绕徒步背包展开，并重点展示背负系统。",
                "hook_line": "背负系统细看",
                "engagement_question": "你更在意背负还是容量？",
                "search_queries": ["徒步背包 背负系统"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.8, "resolution": 0.82},
                "needs_review": True,
                "review_reasons": [],
            }
        ),
    )

    assert result.primary_subject == "徒步背包"
    assert result.resolved_primary_subject == ""


@pytest.mark.asyncio
async def test_verify_content_understanding_falls_back_to_clean_resolved_product_when_base_primary_is_component_biased():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="bags",
        primary_subject="户外徒步背包背负系统",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["户外徒步背包背负系统"],
            component_candidates=["背负系统", "肩带系统"],
            product_type_candidates=["双肩包"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="户外徒步背包背负系统")],
        observed_entities=[SubjectEntity(kind="component", name="背负系统")],
        video_theme="户外背包背负系统调节功能展示",
        summary="视频围绕背负系统展开。",
        hook_line="背负系统细看",
        engagement_question="你更在意背负还是容量？",
        search_queries=["户外徒步背包 背负系统"],
        confidence={"overall": 0.76},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "这期主要看这个户外徒步背包和它的背负系统"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["户外徒步背包 背负系统"],
            online_results=[{"title": "户外徒步背包背负系统调节指南"}],
            database_results=[],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "bags",
                "primary_subject": "户外徒步背包背负系统",
                "subject_entities": [{"kind": "product", "name": "户外徒步背包背负系统"}],
                "observed_entities": [{"kind": "component", "name": "背负系统"}],
                "resolved_entities": [
                    {"kind": "product", "name": "户外徒步背包"},
                    {"kind": "功能系统", "name": "高身位背负系统"},
                ],
                "resolved_primary_subject": "户外徒步背包背负系统",
                "entity_resolution_map": [],
                "video_theme": "户外背包背负系统调节功能展示",
                "summary": "视频围绕背负系统展开。",
                "hook_line": "背负系统细看",
                "engagement_question": "你更在意背负还是容量？",
                "search_queries": ["户外徒步背包 背负系统"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.76, "resolution": 0.82},
                "needs_review": True,
                "review_reasons": [],
            }
        ),
    )

    assert result.primary_subject == "户外徒步背包"
    assert result.subject_entities[0].name == "户外徒步背包"
    assert result.resolved_primary_subject == ""


@pytest.mark.asyncio
async def test_verify_content_understanding_does_not_promote_secondary_product_biased_resolved_primary_subject():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="edc_tools",
        primary_subject="REATE刀具",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["REATE刀具", "组装完成的刀具"],
            supporting_subject_candidates=["EDC桌布", "FS"],
            brand_candidates=["REATE", "FS"],
            product_type_candidates=["折刀"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="REATE刀具"), SubjectEntity(kind="related", name="EDC桌布")],
        observed_entities=[SubjectEntity(kind="product", name="这把刀"), SubjectEntity(kind="related", name="EDC桌布")],
        video_theme="组装完成刀具的外观效果与EDC日常实用价值展示",
        summary="视频先展示刀具完成效果，后半段带到配套桌布发布。",
        hook_line="这把刀终于组完了",
        engagement_question="你更关注刀还是配套桌布？",
        search_queries=["REATE 刀具 EDC桌布"],
        confidence={"overall": 0.82},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "前半段看这把REATE刀，后半段补充一下EDC桌布新系列"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["REATE 刀具 EDC桌布"],
            online_results=[{"title": "REATE 刀具展示"}, {"title": "FS EDC桌布系列发布"}],
            database_results=[],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "edc_tools",
                "primary_subject": "REATE刀具（EDC桌布系列特别版）",
                "subject_entities": [
                    {"kind": "product", "name": "REATE刀具", "brand": "REATE"},
                    {"kind": "配套产品", "name": "EDC桌布", "brand": "FS"},
                ],
                "observed_entities": [
                    {"kind": "product", "name": "这把刀"},
                    {"kind": "related", "name": "EDC桌布"},
                ],
                "resolved_entities": [
                    {"kind": "product", "name": "REATE刀具", "brand": "REATE"},
                    {"kind": "配套产品", "name": "EDC桌布", "brand": "FS"},
                ],
                "resolved_primary_subject": "REATE刀具（EDC桌布系列特别版）",
                "entity_resolution_map": [
                    {
                        "observed_name": "这把刀",
                        "resolved_name": "REATE刀具",
                        "confidence": 0.92,
                        "reason": "视频前半段和检索都指向 REATE 刀具",
                    }
                ],
                "video_theme": "组装完成刀具的外观效果与配套桌布发布展示",
                "summary": "视频先展示刀具完成效果，后半段带到配套桌布发布。",
                "hook_line": "这把刀终于组完了",
                "engagement_question": "你更关注刀还是配套桌布？",
                "search_queries": ["REATE 刀具 EDC桌布"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.88, "resolution": 0.92},
                "needs_review": True,
                "review_reasons": ["核验结果混入了配套产品名称"],
            }
        ),
    )

    assert result.primary_subject == "REATE刀具"
    assert result.resolved_primary_subject == ""


@pytest.mark.asyncio
async def test_verify_content_understanding_detects_secondary_product_bias_from_resolved_entities_even_without_supporting_candidates():
    understanding = ContentUnderstanding(
        video_type="product_review",
        content_domain="edc_tools",
        primary_subject="组装完成的REATE刀具",
        semantic_facts=ContentSemanticFacts(
            primary_subject_candidates=["组装完成的REATE刀具", "组装完成的刀具"],
            supporting_subject_candidates=["瑞特", "金丝帮"],
            brand_candidates=["REATE", "FS"],
            product_type_candidates=["折刀"],
        ),
        subject_entities=[SubjectEntity(kind="product", name="组装完成的REATE刀具")],
        observed_entities=[SubjectEntity(kind="product", name="这把"), SubjectEntity(kind="related", name="EDC桌布")],
        video_theme="组装完成刀具的外观效果展示",
        summary="视频先展示刀具完成效果，后半段带到配套桌布发布。",
        hook_line="这把刀终于组完了",
        engagement_question="你更关注刀还是配套桌布？",
        search_queries=["REATE 刀具 EDC桌布"],
        confidence={"overall": 0.82},
        needs_review=True,
    )

    result = await verify_content_understanding(
        understanding=understanding,
        evidence_bundle={"transcript_excerpt": "前半段看这把REATE刀，后半段补充一下EDC桌布新系列"},
        verification_bundle=HybridVerificationBundle(
            search_queries=["REATE 刀具 EDC桌布"],
            online_results=[{"title": "REATE 刀具展示"}, {"title": "FS EDC桌布系列发布"}],
            database_results=[],
        ),
        provider=FakeProvider(
            {
                "video_type": "product_review",
                "content_domain": "edc_tools",
                "primary_subject": "组装完成的REATE刀具（EDC桌布系列特别版）",
                "subject_entities": [
                    {"kind": "刀具品牌", "name": "瑞特", "brand": "REATE"},
                    {"kind": "配套产品", "name": "EDC桌布", "brand": "FS"},
                ],
                "observed_entities": [
                    {"kind": "product", "name": "这把"},
                    {"kind": "related", "name": "EDC桌布"},
                ],
                "resolved_entities": [
                    {"kind": "刀具品牌", "name": "瑞特", "brand": "REATE"},
                    {"kind": "配套产品", "name": "EDC桌布", "brand": "FS"},
                ],
                "resolved_primary_subject": "组装完成的REATE刀具（EDC桌布系列特别版）",
                "entity_resolution_map": [
                    {
                        "observed_name": "这把",
                        "resolved_name": "组装完成的REATE刀具",
                        "confidence": 0.92,
                        "reason": "视频前半段和检索都指向 REATE 刀具",
                    },
                    {
                        "observed_name": "EDC桌布",
                        "resolved_name": "EDC桌布系列",
                        "confidence": 0.8,
                        "reason": "后半段补充发布了配套桌布系列",
                    },
                ],
                "video_theme": "组装完成刀具的外观效果与配套桌布发布展示",
                "summary": "视频先展示刀具完成效果，后半段带到配套桌布发布。",
                "hook_line": "这把刀终于组完了",
                "engagement_question": "你更关注刀还是配套桌布？",
                "search_queries": ["REATE 刀具 EDC桌布"],
                "evidence_spans": [],
                "uncertainties": [],
                "confidence": {"overall": 0.88, "resolution": 0.92},
                "needs_review": True,
                "review_reasons": ["核验结果混入了配套产品名称"],
            }
        ),
    )

    assert result.primary_subject == "组装完成的REATE刀具"
    assert result.resolved_primary_subject == ""
