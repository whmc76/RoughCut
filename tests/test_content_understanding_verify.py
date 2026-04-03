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
