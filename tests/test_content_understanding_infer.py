from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_infer_content_understanding_uses_reasoning_provider_payload(monkeypatch: pytest.MonkeyPatch):
    from roughcut.review import content_understanding_infer as infer_mod

    prompts: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *args, **kwargs):
            prompts.append(args[0][-1].content)
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(
                    {
                        "brand_candidates": ["ComfyUI"],
                        "model_candidates": ["工作流"],
                        "product_name_candidates": [],
                        "product_type_candidates": ["节点编排工作流"],
                        "entity_candidates": ["ComfyUI 工作流"],
                        "collaboration_pairs": [],
                        "search_expansions": ["ComfyUI workflow", "ComfyUI 节点编排"],
                        "evidence_sentences": ["今天演示 ComfyUI 节点编排"],
                    }
                )
            return FakeResponse(
                {
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
            )

    provider = FakeProvider()
    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: provider)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "今天演示 ComfyUI 节点编排"})

    assert provider.calls == 2
    assert "brand_candidates" in prompts[1]
    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
    assert result.semantic_facts.brand_candidates == ["ComfyUI"]


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
            if self.calls == 1:
                return type(
                    "FactsResponse",
                    (),
                    {
                        "content": '{"brand_candidates":["赫斯郡"],"model_candidates":[],"product_name_candidates":[],"product_type_candidates":["机能双肩包"],"entity_candidates":["机能双肩包"],"collaboration_pairs":[],"search_expansions":["机能双肩包 开箱"],"evidence_sentences":["今天开箱两款机能双肩包"]}',
                        "as_json": staticmethod(
                            lambda: {
                                "brand_candidates": ["赫斯郡"],
                                "model_candidates": [],
                                "product_name_candidates": [],
                                "product_type_candidates": ["机能双肩包"],
                                "entity_candidates": ["机能双肩包"],
                                "collaboration_pairs": [],
                                "search_expansions": ["机能双肩包 开箱"],
                                "evidence_sentences": ["今天开箱两款机能双肩包"],
                            }
                        ),
                    },
                )()
            return BadResponse() if self.calls == 2 else FixedResponse()

    provider = FakeProvider()
    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: provider)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "今天开箱两款机能双肩包"})

    assert provider.calls == 3
    assert result.video_type == "unboxing_review"
    assert result.content_domain == "bags"
    assert result.primary_subject == "机能双肩包"
    assert result.subject_entities[0].name == "赫斯郡"
    assert result.confidence == {"overall": 0.78}


@pytest.mark.asyncio
async def test_infer_content_understanding_uses_semantic_facts_to_expand_retrieval_candidates(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_understanding_infer as infer_mod

    prompts: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, *args, **kwargs):
            prompts.append(args[0][-1].content)
            self.calls += 1
            if self.calls == 1:
                return FakeResponse(
                    {
                        "brand_candidates": ["HSJUN", "BOLTBOAT"],
                        "model_candidates": ["游刃"],
                        "product_name_candidates": ["游刃"],
                        "product_type_candidates": ["机能双肩包"],
                        "entity_candidates": ["HSJUN × BOLTBOAT 游刃"],
                        "collaboration_pairs": ["HSJUN × BOLTBOAT"],
                        "search_expansions": ["HSJUN BOLTBOAT 游刃", "boltboat hsjun 游刃"],
                        "evidence_sentences": ["这是 hsjun 和 boltboat 联名的包，它叫游刃"],
                    }
                )
            return FakeResponse(
                {
                    "video_type": "product_review",
                    "content_domain": "bags",
                    "primary_subject": "HSJUN × BOLTBOAT 游刃机能双肩包",
                    "subject_entities": [{"kind": "product", "name": "游刃机能双肩包", "brand": "HSJUN × BOLTBOAT", "model": "游刃"}],
                    "video_theme": "联名机能双肩包对比评测",
                    "summary": "视频围绕 HSJUN × BOLTBOAT 游刃机能双肩包展开对比评测。",
                    "hook_line": "联名机能包上身实测",
                    "engagement_question": "你更在意结构还是背负？",
                    "search_queries": ["HSJUN BOLTBOAT 游刃", "boltboat hsjun 游刃"],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "confidence": {"overall": 0.74},
                    "needs_review": False,
                    "review_reasons": [],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    result = await infer_mod.infer_content_understanding(
        {
            "transcript_excerpt": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
            "semantic_fact_inputs": {
                "source_name": "hsjun_boltboat.mp4",
                "subtitle_lines": ["这是 hsjun 和 boltboat 联名的包", "它叫游刃"],
                "transcript_text": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
                "visible_text": "HSJUN BOLTBOAT",
                "hint_candidates": [],
            },
        }
    )

    assert "HSJUN" in prompts[1]
    assert "游刃" in prompts[1]
    assert result.search_queries == ["HSJUN BOLTBOAT 游刃", "boltboat hsjun 游刃"]
