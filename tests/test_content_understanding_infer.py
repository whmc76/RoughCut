from __future__ import annotations

import json

import pytest


@pytest.mark.asyncio
async def test_infer_content_understanding_runs_fact_extraction_before_final_understanding(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_understanding_infer as infer_mod
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding

    call_order: list[str] = []
    providers_seen: list[object] = []

    class SentinelProvider:
        pass

    sentinel_provider = SentinelProvider()

    async def fake_infer_content_semantic_facts(provider, evidence_bundle):
        call_order.append("facts")
        providers_seen.append(provider)
        return ContentSemanticFacts(entity_candidates=["HSJUN", "游刃"])

    async def fake_infer_final_understanding(provider, evidence_bundle, semantic_facts):
        call_order.append("final")
        providers_seen.append(provider)
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="HSJUN × BOLTBOAT 游刃机能双肩包",
            semantic_facts=semantic_facts,
        )

    monkeypatch.setattr(infer_mod, "infer_content_semantic_facts", fake_infer_content_semantic_facts, raising=False)
    monkeypatch.setattr(infer_mod, "infer_final_understanding", fake_infer_final_understanding, raising=False)
    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: sentinel_provider)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "这是 HSJUN 的游刃"})

    assert call_order == ["facts", "final"]
    assert providers_seen == [sentinel_provider, sentinel_provider]
    assert result.semantic_facts.entity_candidates == ["HSJUN", "游刃"]


@pytest.mark.asyncio
async def test_infer_content_understanding_always_uses_staged_semantic_facts(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_understanding_infer as infer_mod
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding

    staged_facts = ContentSemanticFacts(entity_candidates=["HSJUN", "游刃"])
    overwritten_facts = ContentSemanticFacts(entity_candidates=["WRONG"])

    async def fake_infer_content_semantic_facts(provider, evidence_bundle):
        return staged_facts

    async def fake_infer_final_understanding(provider, evidence_bundle, semantic_facts):
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="HSJUN × BOLTBOAT 游刃机能双肩包",
            semantic_facts=overwritten_facts,
        )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: object())
    monkeypatch.setattr(infer_mod, "infer_content_semantic_facts", fake_infer_content_semantic_facts, raising=False)
    monkeypatch.setattr(infer_mod, "infer_final_understanding", fake_infer_final_understanding, raising=False)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "这是 HSJUN 的游刃"})

    assert result.semantic_facts == staged_facts


def test_parse_content_understanding_payload_preserves_capability_matrix_and_trace():
    from roughcut.review import content_understanding_infer as infer_mod

    result = infer_mod.parse_content_understanding_payload(
        {
            "video_type": "product_review",
            "content_domain": "gear",
            "primary_subject": "demo subject",
            "capability_matrix": {"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
            "orchestration_trace": ["capability_resolution", "fact_extraction", "final_understanding"],
        }
    )

    assert result.capability_matrix == {"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}}
    assert result.orchestration_trace == ["capability_resolution", "fact_extraction", "final_understanding"]


@pytest.mark.asyncio
async def test_infer_content_understanding_preserves_capability_matrix_and_trace(
    monkeypatch: pytest.MonkeyPatch,
):
    from roughcut.review import content_understanding_infer as infer_mod
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding

    capability_matrix = {"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}}
    orchestration_trace = ["capability_resolution", "fact_extraction", "final_understanding"]

    async def fake_infer_content_semantic_facts(provider, evidence_bundle):
        return ContentSemanticFacts(entity_candidates=["demo"])

    async def fake_infer_final_understanding(provider, evidence_bundle, semantic_facts):
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="gear",
            primary_subject="demo subject",
            semantic_facts=semantic_facts,
            capability_matrix=capability_matrix,
            orchestration_trace=orchestration_trace,
        )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: object())
    monkeypatch.setattr(infer_mod, "infer_content_semantic_facts", fake_infer_content_semantic_facts, raising=False)
    monkeypatch.setattr(infer_mod, "infer_final_understanding", fake_infer_final_understanding, raising=False)

    result = await infer_mod.infer_content_understanding({"transcript_excerpt": "demo"})

    assert result.capability_matrix == capability_matrix
    assert result.orchestration_trace == orchestration_trace


@pytest.mark.asyncio
async def test_infer_content_understanding_populates_capability_matrix_and_trace_when_final_stage_omits_them(
    monkeypatch: pytest.MonkeyPatch,
):
    from types import SimpleNamespace

    from roughcut.review import content_understanding_infer as infer_mod
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding

    async def fake_infer_content_semantic_facts(provider, evidence_bundle):
        return ContentSemanticFacts(entity_candidates=["demo"])

    async def fake_infer_final_understanding(provider, evidence_bundle, semantic_facts):
        return ContentUnderstanding(
            video_type="product_review",
            content_domain="gear",
            primary_subject="demo subject",
            semantic_facts=semantic_facts,
        )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: object())
    monkeypatch.setattr(infer_mod, "infer_content_semantic_facts", fake_infer_content_semantic_facts, raising=False)
    monkeypatch.setattr(infer_mod, "infer_final_understanding", fake_infer_final_understanding, raising=False)
    monkeypatch.setattr(
        infer_mod,
        "get_settings",
        lambda: SimpleNamespace(active_reasoning_provider="minimax", reasoning_provider="minimax"),
    )

    result = await infer_mod.infer_content_understanding(
        {"transcript_excerpt": "demo", "visual_hints": {"subject_type": "gear"}}
    )

    assert result.capability_matrix["reasoning"]["provider"] == "minimax"
    assert result.capability_matrix["visual_understanding"]["status"] == "ready"
    assert result.orchestration_trace == ["capability_resolution", "fact_extraction", "final_understanding"]


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
    assert "primary_subject, semantic_facts, subject_entities" not in prompts[1]
    assert "cue_lines" in prompts[0]
    assert "relation_hints" in prompts[0]
    assert result.video_type == "tutorial"
    assert result.content_domain == "ai"
    assert result.primary_subject == "ComfyUI 工作流"
    assert result.semantic_facts.brand_candidates == ["ComfyUI"]


@pytest.mark.asyncio
async def test_infer_content_understanding_compact_payload_includes_visual_semantic_evidence(monkeypatch: pytest.MonkeyPatch):
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
                        "brand_candidates": ["HSJUN"],
                        "model_candidates": ["游刃"],
                        "product_name_candidates": ["游刃"],
                        "product_type_candidates": ["机能双肩包"],
                        "entity_candidates": ["HSJUN 游刃机能双肩包"],
                        "collaboration_pairs": [],
                        "search_expansions": ["HSJUN 游刃 双肩包"],
                        "evidence_sentences": ["画面里持续展示一个双肩包"],
                    }
                )
            return FakeResponse(
                {
                    "video_type": "product_review",
                    "content_domain": "bags",
                    "primary_subject": "HSJUN 游刃机能双肩包",
                    "subject_entities": [{"kind": "product", "name": "HSJUN 游刃机能双肩包"}],
                    "observed_entities": [],
                    "resolved_entities": [],
                    "resolved_primary_subject": "",
                    "entity_resolution_map": [],
                    "video_theme": "机能双肩包展示",
                    "summary": "视频主要展示机能双肩包。",
                    "hook_line": "机能包展示",
                    "engagement_question": "你更在意背负还是结构？",
                    "search_queries": ["HSJUN 游刃 双肩包"],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "confidence": {"overall": 0.8},
                    "needs_review": False,
                    "review_reasons": [],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    await infer_mod.infer_content_understanding(
        {
            "source_name": "demo.mp4",
            "transcript_excerpt": "今天看这个包的背负系统",
            "visual_semantic_evidence": {
                "object_categories": ["backpack"],
                "subject_candidates": ["机能双肩包"],
                "visible_brands": ["HSJUN"],
                "interaction_type": "handheld_demo",
                "scene_context": "桌面开箱展示",
            },
        }
    )

    assert "visual_semantic_evidence" in prompts[1]
    assert "backpack" in prompts[1]
    assert "handheld_demo" in prompts[1]


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


@pytest.mark.asyncio
async def test_infer_content_understanding_uses_compact_evidence_payload_for_final_prompt(
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
                        "search_expansions": ["HSJUN BOLTBOAT 游刃"],
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
                    "search_queries": ["HSJUN BOLTBOAT 游刃"],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "confidence": {"overall": 0.74},
                    "needs_review": False,
                    "review_reasons": [],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    subtitle_items = [
        {
            "index": index,
            "start_time": float(index),
            "end_time": float(index) + 1.0,
            "text_final": f"字幕片段 {index}",
        }
        for index in range(50)
    ]
    evidence_bundle = {
        "source_name": "hsjun_boltboat.mp4",
        "transcript_excerpt": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
        "subtitle_items": subtitle_items,
        "semantic_fact_inputs": {
            "source_name": "hsjun_boltboat.mp4",
            "subtitle_lines": [f"字幕片段 {index}" for index in range(6)],
            "transcript_text": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
            "visible_text": "HSJUN BOLTBOAT",
            "hint_candidates": ["HSJUN", "BOLTBOAT", "游刃"],
        },
    }

    await infer_mod.infer_content_understanding(evidence_bundle)

    assert "'subtitle_items':" not in prompts[1]
    assert "字幕片段 49" not in prompts[1]
    assert "HSJUN BOLTBOAT" in prompts[1]
    assert "这是 hsjun 和 boltboat 联名的包，它叫游刃" in prompts[1]


@pytest.mark.asyncio
async def test_infer_content_understanding_compact_payload_keeps_relation_hints(monkeypatch: pytest.MonkeyPatch):
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
                        "search_expansions": ["HSJUN BOLTBOAT 游刃"],
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
                    "search_queries": ["HSJUN BOLTBOAT 游刃"],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "confidence": {"overall": 0.74},
                    "needs_review": False,
                    "review_reasons": [],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    await infer_mod.infer_content_understanding(
        {
            "transcript_excerpt": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
            "semantic_fact_inputs": {
                "source_name": "hsjun_boltboat.mp4",
                "cue_lines": ["这是 hsjun 和 boltboat 联名的包", "这个系列叫游刃"],
                "transcript_text": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
                "visible_text": "HSJUN BOLTBOAT",
                "hint_candidates": ["HSJUN", "BOLTBOAT", "游刃"],
                "entity_like_tokens": ["HSJUN", "BOLTBOAT", "YOUREN"],
                "relation_hints": [
                    {"relation": "collaboration", "left": "hsjun", "right": "boltboat", "text": "这是 hsjun 和 boltboat 联名的包"},
                    {"relation": "naming", "value": "游刃", "text": "这个系列叫游刃"},
                ],
            },
        }
    )

    assert "relation_hints" in prompts[1]
    assert "collaboration" in prompts[1]
    assert "YOUREN" in prompts[1]


@pytest.mark.asyncio
async def test_infer_content_understanding_repairs_empty_final_payload_when_semantic_facts_are_informative(
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
                        "search_expansions": ["HSJUN BOLTBOAT 游刃"],
                        "evidence_sentences": ["这是 hsjun 和 boltboat 联名的包，它叫游刃"],
                    }
                )
            if self.calls == 2:
                return FakeResponse(
                    {
                        "video_type": "",
                        "content_domain": "",
                        "primary_subject": "",
                        "subject_entities": [],
                        "video_theme": "",
                        "summary": "",
                        "hook_line": "",
                        "engagement_question": "",
                        "search_queries": [],
                        "evidence_spans": [],
                        "uncertainties": [],
                        "confidence": {},
                        "needs_review": True,
                        "review_reasons": [],
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
                    "search_queries": ["HSJUN BOLTBOAT 游刃"],
                    "evidence_spans": [],
                    "uncertainties": [],
                    "confidence": {"overall": 0.74},
                    "needs_review": True,
                    "review_reasons": ["联名实体待核验"],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    result = await infer_mod.infer_content_understanding(
        {
            "transcript_excerpt": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
            "semantic_fact_inputs": {
                "source_name": "hsjun_boltboat.mp4",
                "cue_lines": ["这是 hsjun 和 boltboat 联名的包", "这个系列叫游刃"],
                "transcript_text": "这是 hsjun 和 boltboat 联名的包，它叫游刃",
                "visible_text": "HSJUN BOLTBOAT",
                "hint_candidates": ["HSJUN", "BOLTBOAT", "游刃"],
                "entity_like_tokens": ["HSJUN", "BOLTBOAT", "YOUREN"],
                "relation_hints": [
                    {"relation": "collaboration", "left": "hsjun", "right": "boltboat", "text": "这是 hsjun 和 boltboat 联名的包"},
                    {"relation": "naming", "value": "游刃", "text": "这个系列叫游刃"},
                ],
            },
        }
    )

    assert result.primary_subject == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert result.video_theme == "联名机能双肩包对比评测"
    assert result.search_queries == ["HSJUN BOLTBOAT 游刃"]
    assert len(prompts) == 3
