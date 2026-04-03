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
                        "primary_subject_candidates": ["ComfyUI 工作流"],
                        "supporting_subject_candidates": ["ComfyUI"],
                        "component_candidates": ["节点编排"],
                        "aspect_candidates": ["工作流搭建"],
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
    assert "primary_subject_candidates" in prompts[0]
    assert "comparison_subject_candidates" in prompts[0]
    assert "supporting_product_candidates" in prompts[0]
    assert "semantic_facts.primary_subject_candidates" in prompts[1]
    assert "不要把功能系统、部件、工艺过程或服务方误当成 primary_subject" in prompts[1]
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
                        "primary_subject_candidates": ["HSJUN 游刃机能双肩包"],
                        "supporting_subject_candidates": ["HSJUN"],
                        "component_candidates": ["背负系统"],
                        "aspect_candidates": ["背负"],
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
async def test_infer_content_semantic_facts_prompt_prioritizes_primary_sellable_subject_over_components():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

    prompts: list[str] = []

    class FakeResponse:
        def as_json(self):
            return {
                "primary_subject_candidates": [],
                "supporting_subject_candidates": [],
                "component_candidates": [],
                "aspect_candidates": [],
                "brand_candidates": [],
                "model_candidates": [],
                "product_name_candidates": [],
                "product_type_candidates": [],
                "entity_candidates": [],
                "collaboration_pairs": [],
                "search_expansions": [],
                "evidence_sentences": [],
            }

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            prompts.append(args[0][-1].content)
            return FakeResponse()

    await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "cue_lines": ["今天重点看这个包的背负系统"],
                "relation_hints": [],
                "entity_like_tokens": ["背负系统", "双肩包"],
            }
        },
    )

    assert "优先识别视频真正围绕的可售主体或被重点展示的核心对象" in prompts[0]
    assert "把主对象或主产品放进 primary_subject_candidates" in prompts[0]
    assert "把功能系统、部件、配件、工艺模块放进 component_candidates" in prompts[0]
    assert "把背负、做工、材质、结构、续航、亮度、锋利度等评价维度放进 aspect_candidates" in prompts[0]
    assert "不要把功能系统、部件、工艺过程、服务方或背景物直接当成主产品候选" in prompts[0]
    assert "opening_focus_lines" in prompts[0]
    assert "closing_focus_lines" in prompts[0]


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_repairs_empty_payload_when_evidence_is_informative():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

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
                        "primary_subject_candidates": [],
                        "supporting_subject_candidates": [],
                        "component_candidates": [],
                        "aspect_candidates": [],
                        "brand_candidates": [],
                        "model_candidates": [],
                        "product_name_candidates": [],
                        "product_type_candidates": [],
                        "entity_candidates": [],
                        "collaboration_pairs": [],
                        "search_expansions": [],
                        "evidence_sentences": [],
                    }
                )
            return FakeResponse(
                {
                    "primary_subject_candidates": ["HSJUN × BOLTBOAT 游刃机能双肩包"],
                    "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
                    "component_candidates": ["背负系统"],
                    "aspect_candidates": ["背负"],
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

    result = await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "source_name": "hsjun_boltboat.mp4",
                "cue_lines": ["这是 hsjun 和 boltboat 联名的包", "它叫游刃"],
                "visible_text": "HSJUN BOLTBOAT",
                "entity_like_tokens": ["HSJUN", "BOLTBOAT", "游刃"],
                "relation_hints": [
                    {"relation": "collaboration", "left": "hsjun", "right": "boltboat", "text": "这是 hsjun 和 boltboat 联名的包"},
                    {"relation": "naming", "value": "游刃", "text": "它叫游刃"},
                ],
            },
            "visual_semantic_evidence": {
                "object_categories": ["backpack"],
                "subject_candidates": ["机能双肩包"],
                "visible_brands": ["HSJUN"],
            },
        },
    )

    assert result.primary_subject_candidates[0] == "HSJUN × BOLTBOAT 游刃机能双肩包"
    assert "机能双肩包" in result.product_type_candidates
    assert result.brand_candidates == ["HSJUN", "BOLTBOAT"]
    assert len(prompts) == 2
    assert "首轮语义事实提取过空" in prompts[1]
    assert "visual_semantic_evidence" in prompts[1]


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_does_not_repair_empty_payload_when_evidence_is_weak():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

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
            self.calls += 1
            return FakeResponse(
                {
                    "primary_subject_candidates": [],
                    "supporting_subject_candidates": [],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": [],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": [],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": [],
                    "evidence_sentences": [],
                }
            )

    provider = FakeProvider()
    result = await infer_content_semantic_facts(
        provider,
        {
            "semantic_fact_inputs": {
                "source_name": "demo.mp4",
                "cue_lines": ["今天简单看一下"],
                "visible_text": "",
                "entity_like_tokens": [],
                "relation_hints": [],
            }
        },
    )

    assert result == result.__class__()
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_enriches_empty_payload_with_visual_product_aliases():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

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
            self.calls += 1
            return FakeResponse(
                {
                    "primary_subject_candidates": [],
                    "supporting_subject_candidates": [],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": [],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": [],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": [],
                    "evidence_sentences": [],
                }
            )

    provider = FakeProvider()
    result = await infer_content_semantic_facts(
        provider,
        {
            "semantic_fact_inputs": {
                "source_name": "knife_demo.mp4",
                "cue_lines": ["这把折到后面还要看开合和手感"],
                "entity_like_tokens": ["折到", "utility_knife", "folding_knife"],
                "relation_hints": [],
            },
            "visual_semantic_evidence": {
                "object_categories": ["utility_knife"],
                "subject_candidates": ["folding_knife"],
            },
        },
    )

    assert provider.calls == 2
    assert "折刀" in result.product_type_candidates
    assert "美工刀" in result.product_type_candidates
    assert result.primary_subject_candidates[0] in {"折刀", "美工刀"}
    assert any("折刀" in item or "美工刀" in item for item in result.search_expansions)


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_uses_opening_focus_to_keep_primary_product_ahead_of_closing_series_announcement():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse(
                {
                    "primary_subject_candidates": ["桌面EDC"],
                    "supporting_subject_candidates": [],
                    "comparison_subject_candidates": [],
                    "supporting_product_candidates": ["EDC桌布"],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": ["FS", "瑞特", "REATE"],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": [],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": [],
                    "evidence_sentences": [],
                }
            )

    result = await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "source_name": "reate_knife.mp4",
                "cue_lines": ["现在这把已经组装完成了", "我们就把它命名为EDC桌布吧"],
                "opening_focus_lines": ["现在这把已经组装完成了", "刀刃没有做出改变其实还是保留了一定实用性", "日常的工具因为瑞特的拆卸工具这点还是没问题的"],
                "closing_focus_lines": ["结尾我还要宣布一个重要的消息", "大家看我们这次使用的这个桌布啊", "我们就把它命名为EDC桌布吧"],
                "entity_like_tokens": ["瑞特", "刀", "刀刃", "桌布", "REATE"],
                "relation_hints": [{"relation": "naming", "value": "EDC桌布", "text": "我们就把它命名为EDC桌布吧"}],
                "transcript_text": "前半段在讲这把刀的雕刻和刀刃，后半段宣布 EDC 桌布新系列。",
            }
        },
    )

    assert result.primary_subject_candidates[0] == "REATE刀具"
    assert "刀具" in result.product_type_candidates
    assert "雕刻" in result.aspect_candidates


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_enriches_brand_and_product_type_from_opening_focus_lines_when_llm_returns_empty():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse(
                {
                    "primary_subject_candidates": [],
                    "supporting_subject_candidates": [],
                    "comparison_subject_candidates": [],
                    "supporting_product_candidates": [],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": [],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": [],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": [],
                    "evidence_sentences": [],
                }
            )

    result = await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "source_name": "reate_focus.mp4",
                "cue_lines": ["结尾我还要宣布一个重要的消息"],
                "opening_focus_lines": ["刀刃没有做出改变其实还是保留了一定实用性", "日常的工具因为瑞特的拆卸工具这点还是没问题的", "把这个雕刻就衬得更亮"],
                "closing_focus_lines": ["大家看我们这次使用的这个桌布啊", "我们就把它命名为EDC桌布吧"],
                "entity_like_tokens": ["瑞特", "刀", "刀刃", "桌布"],
            }
        },
    )

    assert "REATE" in result.brand_candidates
    assert "刀具" in result.product_type_candidates
    assert "雕刻" in result.aspect_candidates
    assert result.primary_subject_candidates[0] == "REATE刀具"


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
                                "primary_subject_candidates": ["机能双肩包"],
                                "supporting_subject_candidates": ["赫斯郡"],
                                "component_candidates": [],
                                "aspect_candidates": ["开箱"],
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
    assert result.subject_entities[0].name == "机能双肩包"
    assert any(entity.name == "赫斯郡" for entity in result.subject_entities)
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
                        "primary_subject_candidates": ["HSJUN × BOLTBOAT 游刃机能双肩包"],
                        "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
                        "component_candidates": [],
                        "aspect_candidates": ["对比评测"],
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
                        "primary_subject_candidates": ["HSJUN × BOLTBOAT 游刃机能双肩包"],
                        "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
                        "component_candidates": [],
                        "aspect_candidates": ["对比评测"],
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
                        "primary_subject_candidates": ["HSJUN × BOLTBOAT 游刃机能双肩包"],
                        "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
                        "component_candidates": [],
                        "aspect_candidates": ["对比评测"],
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
                        "primary_subject_candidates": ["HSJUN × BOLTBOAT 游刃机能双肩包"],
                        "supporting_subject_candidates": ["HSJUN", "BOLTBOAT"],
                        "component_candidates": [],
                        "aspect_candidates": ["对比评测"],
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


@pytest.mark.asyncio
async def test_infer_content_understanding_repairs_role_conflict_when_component_overrides_primary_subject(
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
                        "primary_subject_candidates": ["户外背包"],
                        "supporting_subject_candidates": ["联名机能包"],
                        "component_candidates": ["背包背负系统", "肩带系统"],
                        "aspect_candidates": ["背负调节"],
                        "brand_candidates": [],
                        "model_candidates": [],
                        "product_name_candidates": [],
                        "product_type_candidates": ["户外背包"],
                        "entity_candidates": ["户外背包", "背包背负系统"],
                        "collaboration_pairs": [],
                        "search_expansions": ["户外背包 背负调节"],
                        "evidence_sentences": ["这期主要看这个户外背包和它的背负系统调节方式"],
                    }
                )
            if self.calls == 2:
                return FakeResponse(
                    {
                        "video_type": "product_review",
                        "content_domain": "bags",
                        "primary_subject": "背包背负系统",
                        "subject_entities": [{"kind": "component", "name": "背包背负系统"}],
                        "observed_entities": [{"kind": "component", "name": "肩带系统"}],
                        "resolved_entities": [],
                        "resolved_primary_subject": "",
                        "entity_resolution_map": [],
                        "video_theme": "背包背负系统功能展示与调节方式演示",
                        "summary": "视频重点介绍背包背负系统与调节方式。",
                        "hook_line": "背负系统细讲",
                        "engagement_question": "你更在意背负还是调节？",
                        "search_queries": ["户外背包 背负调节"],
                        "evidence_spans": [],
                        "uncertainties": [],
                        "confidence": {"overall": 0.72},
                        "needs_review": True,
                        "review_reasons": [],
                    }
                )
            return FakeResponse(
                {
                    "video_type": "product_review",
                    "content_domain": "bags",
                    "primary_subject": "户外背包",
                    "subject_entities": [{"kind": "product", "name": "户外背包"}],
                    "observed_entities": [{"kind": "product", "name": "户外背包"}],
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
                    "review_reasons": ["组件描述较多，主体仍需人工复核"],
                }
            )

    monkeypatch.setattr(infer_mod, "get_reasoning_provider", lambda: FakeProvider())

    result = await infer_mod.infer_content_understanding(
        {
            "transcript_excerpt": "这期主要看这个户外背包和它的背负系统调节方式",
            "semantic_fact_inputs": {
                "cue_lines": ["这期主要看这个户外背包和它的背负系统调节方式"],
                "entity_like_tokens": ["户外背包", "背包背负系统", "肩带系统"],
            },
        }
    )

    assert result.primary_subject == "户外背包"
    assert result.observed_entities[0].name == "户外背包"
    assert len(prompts) == 3
    assert "必须优先让主对象候选成为 primary_subject" in prompts[2]


def test_normalize_understanding_subject_roles_promotes_primary_candidates_over_components():
    from roughcut.review.content_understanding_infer import _normalize_understanding_subject_roles
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    normalized = _normalize_understanding_subject_roles(
        ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="背包背负系统",
            semantic_facts=ContentSemanticFacts(),
            subject_entities=[SubjectEntity(kind="component", name="肩带系统")],
            observed_entities=[SubjectEntity(kind="component", name="背包背负系统")],
            video_theme="户外背包背负系统功能展示与调节方式演示",
            summary="视频重点介绍背包背负系统与调节方式。",
            hook_line="背负系统细讲",
            engagement_question="你更在意背负还是调节？",
            search_queries=["户外背包 背负调节"],
            needs_review=True,
        ),
        ContentSemanticFacts(
            primary_subject_candidates=["户外背包"],
            supporting_subject_candidates=["联名机能包"],
            component_candidates=["背包背负系统", "肩带系统"],
            aspect_candidates=["背负调节"],
        ),
    )

    assert normalized.primary_subject == "户外背包"
    assert normalized.observed_entities[0].name == "户外背包"
    assert normalized.subject_entities[0].name == "户外背包"
    assert normalized.subject_entities[-1].name == "联名机能包"


def test_normalize_understanding_subject_roles_prefers_non_component_primary_candidate_when_first_candidate_is_component():
    from roughcut.review.content_understanding_infer import _normalize_understanding_subject_roles
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    normalized = _normalize_understanding_subject_roles(
        ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="背负系统",
            semantic_facts=ContentSemanticFacts(),
            subject_entities=[SubjectEntity(kind="component", name="背负系统")],
            observed_entities=[SubjectEntity(kind="component", name="背负系统")],
            video_theme="户外背包高身位背负系统功能演示",
            summary="视频重点介绍背负系统。",
            hook_line="背负系统细讲",
            engagement_question="你更在意背负还是调节？",
            search_queries=["户外背包 背负系统"],
            needs_review=True,
        ),
        ContentSemanticFacts(
            primary_subject_candidates=["背负系统", "户外背包"],
            component_candidates=["背负系统", "肩带系统"],
            aspect_candidates=["背负调节"],
            product_type_candidates=["双肩包"],
        ),
    )

    assert normalized.primary_subject == "户外背包"
    assert normalized.observed_entities[0].name == "户外背包"
    assert normalized.subject_entities[0].name == "户外背包"


def test_normalize_understanding_subject_roles_strips_secondary_product_from_primary_subject_label():
    from roughcut.review.content_understanding_infer import _normalize_understanding_subject_roles
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    normalized = _normalize_understanding_subject_roles(
        ContentUnderstanding(
            video_type="product_review",
            content_domain="edc_tools",
            primary_subject="REATE刀具（EDC桌布系列特别版）",
            semantic_facts=ContentSemanticFacts(),
            subject_entities=[
                SubjectEntity(kind="product", name="REATE刀具"),
                SubjectEntity(kind="related", name="EDC桌布"),
            ],
            observed_entities=[
                SubjectEntity(kind="product", name="这把刀"),
                SubjectEntity(kind="related", name="EDC桌布"),
            ],
            video_theme="组装完成刀具的外观效果与配套桌布发布展示",
            summary="视频前半段展示刀具完成效果，后半段带出配套桌布。",
            hook_line="这把刀终于组完了",
            engagement_question="你更关注刀还是配套桌布？",
            search_queries=["REATE 刀具 EDC桌布"],
            needs_review=True,
        ),
        ContentSemanticFacts(
            primary_subject_candidates=["REATE刀具", "组装完成的刀具"],
            supporting_subject_candidates=["EDC桌布", "FS"],
            brand_candidates=["REATE", "FS"],
            product_type_candidates=["折刀"],
        ),
    )

    assert normalized.primary_subject == "REATE刀具"
    assert normalized.subject_entities[0].name == "REATE刀具"
    assert normalized.subject_entities[-1].name == "EDC桌布"


def test_normalize_understanding_subject_roles_strips_component_phrase_from_primary_subject_label():
    from roughcut.review.content_understanding_infer import _normalize_understanding_subject_roles
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    normalized = _normalize_understanding_subject_roles(
        ContentUnderstanding(
            video_type="product_review",
            content_domain="bags",
            primary_subject="徒步背包背负系统",
            semantic_facts=ContentSemanticFacts(),
            subject_entities=[SubjectEntity(kind="product", name="徒步背包背负系统")],
            observed_entities=[SubjectEntity(kind="component", name="背负系统")],
            video_theme="徒步背包背负系统功能演示",
            summary="视频围绕徒步背包的背负系统展开。",
            hook_line="背负系统细看",
            engagement_question="你更在意背负还是容量？",
            search_queries=["徒步背包 背负系统"],
            needs_review=True,
        ),
        ContentSemanticFacts(
            primary_subject_candidates=["徒步背包", "徒步背包背负系统"],
            component_candidates=["背负系统", "肩带系统"],
            aspect_candidates=["背负调节"],
            product_type_candidates=["双肩包"],
        ),
    )

    assert normalized.primary_subject == "徒步背包"
    assert normalized.subject_entities[0].name == "徒步背包"


def test_build_compact_evidence_payload_preserves_subject_role_candidates():
    from roughcut.review.content_understanding_infer import _build_compact_evidence_payload
    from roughcut.review.content_understanding_schema import ContentSemanticFacts

    payload = _build_compact_evidence_payload(
        {
            "source_name": "demo.mp4",
            "semantic_fact_inputs": {"cue_lines": ["重点看这个包和它的背负系统"]},
        }
    )
    facts = ContentSemanticFacts(
        primary_subject_candidates=["机能双肩包"],
        supporting_subject_candidates=["联名方"],
        component_candidates=["背负系统"],
        aspect_candidates=["背负"],
    )

    assert payload["semantic_fact_inputs"]["cue_lines"] == ["重点看这个包和它的背负系统"]
    assert facts.primary_subject_candidates == ["机能双肩包"]
    assert facts.component_candidates == ["背负系统"]


def test_build_compact_evidence_payload_preserves_opening_and_closing_focus_lines():
    from roughcut.review.content_understanding_infer import _build_compact_evidence_payload

    payload = _build_compact_evidence_payload(
        {
            "source_name": "demo.mp4",
            "semantic_fact_inputs": {
                "cue_lines": ["前半段看这把刀", "后半段宣布 EDC 桌布"],
                "opening_focus_lines": ["前半段看这把刀", "看雕刻和刀刃"],
                "closing_focus_lines": ["后半段宣布 EDC 桌布", "命名为 EDC 桌布"],
            },
        }
    )

    assert payload["semantic_fact_inputs"]["opening_focus_lines"] == ["前半段看这把刀", "看雕刻和刀刃"]
    assert payload["semantic_fact_inputs"]["closing_focus_lines"] == ["后半段宣布 EDC 桌布", "命名为 EDC 桌布"]


def test_backfill_semantic_facts_from_understanding_recovers_primary_and_comparison_roles():
    from roughcut.review.content_understanding_infer import _backfill_semantic_facts_from_understanding
    from roughcut.review.content_understanding_schema import ContentSemanticFacts, ContentUnderstanding, SubjectEntity

    understanding = ContentUnderstanding(
        video_type="review/discussion",
        content_domain="flashlight/EDC手电筒",
        primary_subject="SLIM2代手电筒ULTRA版本",
        semantic_facts=ContentSemanticFacts(),
        subject_entities=[
            SubjectEntity(kind="product", name="SLIM2代ULTRA版", brand="傲雷", model="SLIM2 ULTRA"),
            SubjectEntity(kind="product", name="SLIM2代PRO版", brand="傲雷", model="SLIM2 PRO"),
            SubjectEntity(kind="comparison_product", name="EDC23手电筒", brand="奈特科尔", model="EDC23"),
        ],
        observed_entities=[SubjectEntity(kind="", name="SLIM2代的ULTRA版本")],
        video_theme="EDC手电筒版本选购对比与保值分析",
        summary="对比 ULTRA 与 PRO 以及其他 EDC 手电型号。",
        hook_line="SLIM2 ULTRA 值不值",
        engagement_question="你会选 PRO 还是 ULTRA？",
        search_queries=["SLIM2 手电筒 ULTRA 评测"],
        needs_review=True,
    )

    facts = _backfill_semantic_facts_from_understanding(ContentSemanticFacts(), understanding)

    assert facts.primary_subject_candidates[0] == "SLIM2代手电筒ULTRA版本"
    assert "傲雷" in facts.brand_candidates
    assert "SLIM2 ULTRA" in facts.model_candidates
    assert "EDC23手电筒" in facts.comparison_subject_candidates


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_enriches_flashlight_brand_from_asr_alias_olei():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse(
                {
                    "primary_subject_candidates": [],
                    "supporting_subject_candidates": [],
                    "comparison_subject_candidates": [],
                    "supporting_product_candidates": [],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": [],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": ["手电筒"],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": [],
                    "evidence_sentences": [],
                }
            )

    result = await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "source_name": "flashlight.mp4",
                "transcript_text": "今天聊奥雷 slim2 代的 ultra 版本",
                "cue_lines": ["今天聊奥雷 slim2 代的 ultra 版本"],
                "entity_like_tokens": ["奥雷", "SLIM2", "ULTRA", "手电"],
                "visible_text": "",
            }
        },
    )

    assert "OLIGHT" in result.brand_candidates


@pytest.mark.asyncio
async def test_infer_content_semantic_facts_enriches_flashlight_brand_from_primary_subject_candidate_text():
    from roughcut.review.content_understanding_facts import infer_content_semantic_facts

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload
            self.content = json.dumps(payload, ensure_ascii=False)

        def as_json(self):
            return self.payload

    class FakeProvider:
        async def complete(self, *args, **kwargs):
            return FakeResponse(
                {
                    "primary_subject_candidates": ["奥雷SLIM2代ULTRA版手电筒"],
                    "supporting_subject_candidates": ["PRO版"],
                    "comparison_subject_candidates": ["EDC23"],
                    "supporting_product_candidates": [],
                    "component_candidates": [],
                    "aspect_candidates": [],
                    "brand_candidates": [],
                    "model_candidates": [],
                    "product_name_candidates": [],
                    "product_type_candidates": ["手电筒"],
                    "entity_candidates": [],
                    "collaboration_pairs": [],
                    "search_expansions": ["奥雷SLIM2代ULTRA版手电筒"],
                    "evidence_sentences": [],
                }
            )

    result = await infer_content_semantic_facts(
        FakeProvider(),
        {
            "semantic_fact_inputs": {
                "source_name": "flashlight.mp4",
                "cue_lines": ["今天主要看 slim2 代 ultra 版本"],
                "entity_like_tokens": ["SLIM2", "ULTRA", "手电"],
            }
        },
    )

    assert "OLIGHT" in result.brand_candidates
