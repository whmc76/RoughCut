from __future__ import annotations

import json

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


@pytest.mark.asyncio
async def test_infer_content_understanding_repairs_malformed_json_response(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_understanding_infer as infer_mod

    class BadResponse:
        content = """```json
{"video_type":"unboxing_review","content_domain":"bags"
```"""

        def as_json(self):
            raise json.JSONDecodeError("Expecting value", self.content, 12)

    class FixedResponse:
        content = '{"video_type":"unboxing_review","content_domain":"bags","primary_subject":"机能双肩包","subject_entities":["赫斯郡"],"video_theme":"机能双肩包开箱对比","summary":"视频开箱对比两款机能双肩包。","hook_line":"两款机能包开箱对比","engagement_question":"你更喜欢哪一款？","search_queries":["机能双肩包 开箱"],"evidence_spans":[{"timestamp":"[11.1-16.3]","text":"机能双肩包 赫斯郡联名","type":"subject_identification"}],"uncertainties":[],"confidence":0.78,"needs_review":true,"review_reasons":["品牌名待核验"]}'

        def as_json(self):
            return json.loads(self.content)

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *args, **kwargs):
            self.calls += 1
            return BadResponse() if self.calls == 1 else FixedResponse()

    provider = FakeProvider()
    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: provider)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "今天开箱两款机能双肩包"})

    assert provider.calls == 2
    assert result.video_type == "unboxing_review"
    assert result.content_domain == "bags"
    assert result.primary_subject == "机能双肩包"
    assert result.subject_entities[0].name == "赫斯郡"
    assert result.confidence == {"overall": 0.78}
