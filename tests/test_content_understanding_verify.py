from __future__ import annotations

from types import SimpleNamespace

import pytest

from roughcut.review.content_understanding_schema import ContentUnderstanding, SubjectEntity
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
