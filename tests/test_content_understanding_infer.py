from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_infer_content_understanding_uses_reasoning_provider_payload(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_understanding_infer as infer_mod

    class FakeResponse:
        def as_json(self):
            return {
                "video_type": "tutorial",
                "content_domain": "ai",
                "primary_subject": "ComfyUI 工作流",
                "subject_entities": [{"kind": "software", "name": "ComfyUI"}],
                "video_theme": "ComfyUI 节点编排与工作流实操",
                "summary": "这条视频主要演示 ComfyUI 工作流搭建。",
                "hook_line": "工作流直接讲透",
                "engagement_question": "你还想看哪类节点编排？",
                "search_queries": ["ComfyUI workflow", "ComfyUI 节点编排"],
                "evidence_spans": [{"source": "transcript", "text": "节点编排"}],
                "uncertainties": [],
                "confidence": {"overall": 0.87},
                "needs_review": False,
                "review_reasons": [],
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse()

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "今天演示 ComfyUI 节点编排"})

    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
