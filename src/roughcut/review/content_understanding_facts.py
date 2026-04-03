from __future__ import annotations

from typing import Any

from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    parse_content_semantic_facts_payload,
)


async def infer_content_semantic_facts(
    provider: Any,
    evidence_bundle: dict[str, Any],
) -> ContentSemanticFacts:
    prompt = (
        "你是视频证据语义抽取器。请根据多模态证据提取可供后续检索和消歧使用的通用语义事实，"
        "只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。"
        "字段必须包括 primary_subject_candidates, supporting_subject_candidates, component_candidates, "
        "aspect_candidates, brand_candidates, model_candidates, product_name_candidates, "
        "product_type_candidates, entity_candidates, collaboration_pairs, search_expansions, evidence_sentences。"
        "要求："
        "优先识别视频真正围绕的可售主体或被重点展示的核心对象；"
        "把主对象或主产品放进 primary_subject_candidates；"
        "把联名方、配套对象、辅助对象放进 supporting_subject_candidates；"
        "把功能系统、部件、配件、工艺模块放进 component_candidates；"
        "把背负、做工、材质、结构、续航、亮度、锋利度等评价维度放进 aspect_candidates；"
        "不要把功能系统、部件、工艺过程、服务方或背景物直接当成主产品候选；"
        "只提取证据支持的候选，不要输出最终结论；"
        "优先参考 cue_lines 和 relation_hints 中的命名、归属、联名、型号、系列等关系提示，以及 entity_like_tokens 中的实体样 token；"
        "search_expansions 最多 6 条，可包含中英别名、音译、联名组合、近似实体检索词；"
        "evidence_sentences 最多 6 条，应保留原始语义片段；"
        "信息不足时返回空数组。"
        f"\n证据输入: {evidence_bundle.get('semantic_fact_inputs') or {}}"
    )
    try:
        response = await provider.complete(
            [
                Message(role="system", content="你是语义事实抽取器，输出必须是 JSON。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=700,
            json_mode=True,
        )
        facts = parse_content_semantic_facts_payload(
            await _load_json_object(
                provider,
                response,
                required_fields=[
                    "primary_subject_candidates",
                    "supporting_subject_candidates",
                    "component_candidates",
                    "aspect_candidates",
                    "brand_candidates",
                    "model_candidates",
                    "product_name_candidates",
                    "product_type_candidates",
                    "entity_candidates",
                    "collaboration_pairs",
                    "search_expansions",
                    "evidence_sentences",
                ],
                empty_object_description=(
                    '{"primary_subject_candidates":[],"supporting_subject_candidates":[],"component_candidates":[],'
                    '"aspect_candidates":[],"brand_candidates":[],"model_candidates":[],"product_name_candidates":[],'
                    '"product_type_candidates":[],"entity_candidates":[],"collaboration_pairs":[],'
                    '"search_expansions":[],"evidence_sentences":[]}'
                ),
            )
        )
        if _needs_semantic_facts_repair(facts, evidence_bundle):
            repaired_facts = await _repair_semantic_facts(
                provider=provider,
                evidence_bundle=evidence_bundle,
                original_facts=facts,
            )
            if _semantic_facts_signal_score(repaired_facts) > _semantic_facts_signal_score(facts):
                facts = repaired_facts
        return facts
    except Exception:
        return ContentSemanticFacts()


async def _load_json_object(
    provider: Any,
    response: Any,
    *,
    required_fields: list[str],
    empty_object_description: str,
) -> dict[str, Any]:
    try:
        payload = response.as_json()
    except Exception:
        repair_prompt = (
            "把下面的模型输出修复成一个严格 JSON 对象。"
            "不要 Markdown，不要代码块，不要解释，不要省略字段。"
            f"必须保留字段：{', '.join(required_fields)}。"
            f"如果缺字段就补成这个结构：{empty_object_description}。"
            f"\n原始输出:\n{getattr(response, 'content', '')}"
        )
        repaired = await provider.complete(
            [
                Message(role="system", content="你是 JSON 修复器，只输出严格 JSON。"),
                Message(role="user", content=repair_prompt),
            ],
            temperature=0.0,
            max_tokens=1400,
            json_mode=True,
        )
        payload = repaired.as_json()
    return payload if isinstance(payload, dict) else {}


def _needs_semantic_facts_repair(
    facts: ContentSemanticFacts,
    evidence_bundle: dict[str, Any],
) -> bool:
    if _semantic_facts_signal_score(facts) > 0:
        return False
    semantic_inputs = evidence_bundle.get("semantic_fact_inputs") if isinstance(evidence_bundle, dict) else {}
    semantic_inputs = semantic_inputs if isinstance(semantic_inputs, dict) else {}
    relation_hints = semantic_inputs.get("relation_hints")
    entity_like_tokens = semantic_inputs.get("entity_like_tokens")
    cue_lines = semantic_inputs.get("cue_lines")
    visible_text = str(semantic_inputs.get("visible_text") or "").strip()
    visual_semantic_evidence = evidence_bundle.get("visual_semantic_evidence") if isinstance(evidence_bundle, dict) else {}
    visual_semantic_evidence = visual_semantic_evidence if isinstance(visual_semantic_evidence, dict) else {}
    visual_signal = any(
        visual_semantic_evidence.get(key)
        for key in ("subject_candidates", "visible_brands", "visible_models", "object_categories", "evidence_notes")
    )
    return bool(
        (isinstance(relation_hints, list) and relation_hints)
        or (isinstance(entity_like_tokens, list) and len([item for item in entity_like_tokens if str(item).strip()]) >= 2)
        or (isinstance(cue_lines, list) and any(str(item).strip() for item in cue_lines[:2]) and visible_text)
        or visual_signal
    )


def _semantic_facts_signal_score(facts: ContentSemanticFacts) -> int:
    groups = (
        facts.primary_subject_candidates,
        facts.supporting_subject_candidates,
        facts.component_candidates,
        facts.aspect_candidates,
        facts.brand_candidates,
        facts.model_candidates,
        facts.product_name_candidates,
        facts.product_type_candidates,
        facts.entity_candidates,
        facts.collaboration_pairs,
        facts.search_expansions,
        facts.evidence_sentences,
    )
    return sum(len(group) for group in groups)


async def _repair_semantic_facts(
    *,
    provider: Any,
    evidence_bundle: dict[str, Any],
    original_facts: ContentSemanticFacts,
) -> ContentSemanticFacts:
    repair_prompt = (
        "首轮语义事实提取过空。请基于视频内直接证据做一次更严格的事实补全，只输出严格 JSON。"
        "不要输出最终主题、摘要或包装文案，只补充语义事实。"
        "字段必须包括 primary_subject_candidates, supporting_subject_candidates, component_candidates, "
        "aspect_candidates, brand_candidates, model_candidates, product_name_candidates, "
        "product_type_candidates, entity_candidates, collaboration_pairs, search_expansions, evidence_sentences。"
        "要求："
        "1. 优先从 cue_lines、relation_hints、entity_like_tokens、visible_text、ocr_semantic_evidence、visual_semantic_evidence 中提取更具体的主对象、品牌、型号、产品名；"
        "2. 只提取证据支持的事实，不输出最终结论；"
        "3. 如果只能提取到泛化主体，也要尽量保留品牌、版本、命名、联名、型号线索；"
        "4. 功能系统、部件、结构、手感、材质等仍然只能放在 component_candidates 或 aspect_candidates；"
        "5. search_expansions 应优先生成可用于后续联网搜索和数据库检索的细粒度查询词。"
        f"\n首轮事实: {original_facts.__dict__}"
        f"\n证据输入: {_build_facts_repair_evidence_payload(evidence_bundle)}"
    )
    repaired = await provider.complete(
        [
            Message(role="system", content="你是语义事实补全器，只输出严格 JSON。"),
            Message(role="user", content=repair_prompt),
        ],
        temperature=0.0,
        max_tokens=1000,
        json_mode=True,
    )
    payload = await _load_json_object(
        provider,
        repaired,
        required_fields=[
            "primary_subject_candidates",
            "supporting_subject_candidates",
            "component_candidates",
            "aspect_candidates",
            "brand_candidates",
            "model_candidates",
            "product_name_candidates",
            "product_type_candidates",
            "entity_candidates",
            "collaboration_pairs",
            "search_expansions",
            "evidence_sentences",
        ],
        empty_object_description=(
            '{"primary_subject_candidates":[],"supporting_subject_candidates":[],"component_candidates":[],"aspect_candidates":[],'
            '"brand_candidates":[],"model_candidates":[],"product_name_candidates":[],"product_type_candidates":[],"entity_candidates":[],'
            '"collaboration_pairs":[],"search_expansions":[],"evidence_sentences":[]}'
        ),
    )
    return parse_content_semantic_facts_payload(payload)


def _build_facts_repair_evidence_payload(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    semantic_inputs = evidence_bundle.get("semantic_fact_inputs") if isinstance(evidence_bundle, dict) else {}
    semantic_inputs = semantic_inputs if isinstance(semantic_inputs, dict) else {}
    visual_semantic_evidence = evidence_bundle.get("visual_semantic_evidence") if isinstance(evidence_bundle, dict) else {}
    visual_semantic_evidence = visual_semantic_evidence if isinstance(visual_semantic_evidence, dict) else {}
    ocr_semantic_evidence = evidence_bundle.get("ocr_semantic_evidence") if isinstance(evidence_bundle, dict) else {}
    ocr_semantic_evidence = ocr_semantic_evidence if isinstance(ocr_semantic_evidence, dict) else {}
    return {
        "semantic_fact_inputs": {
            "source_name": semantic_inputs.get("source_name") or "",
            "cue_lines": list(semantic_inputs.get("cue_lines") or [])[:8],
            "relation_hints": list(semantic_inputs.get("relation_hints") or [])[:8],
            "entity_like_tokens": list(semantic_inputs.get("entity_like_tokens") or [])[:20],
            "visible_text": semantic_inputs.get("visible_text") or "",
        },
        "visual_semantic_evidence": {
            key: visual_semantic_evidence.get(key)
            for key in ("object_categories", "visible_brands", "visible_models", "subject_candidates", "interaction_type", "scene_context", "evidence_notes")
            if visual_semantic_evidence.get(key)
        },
        "ocr_semantic_evidence": {
            key: ocr_semantic_evidence.get(key)
            for key in ("visible_text", "ocr_profile")
            if ocr_semantic_evidence.get(key)
        },
    }
