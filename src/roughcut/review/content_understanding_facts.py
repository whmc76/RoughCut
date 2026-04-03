from __future__ import annotations

from typing import Any

from roughcut.providers.reasoning.base import Message
from roughcut.review.domain_glossaries import list_builtin_glossary_packs
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    parse_content_semantic_facts_payload,
)

_GENERIC_PRODUCT_TYPE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("双肩包", ("双肩包", "背包", "BACKPACK")),
    ("机能包", ("机能包", "SLING_BAG", "TACTICAL_BAG")),
    ("手电筒", ("手电", "手电筒", "FLASHLIGHT", "TORCH")),
    ("折刀", ("折刀", "FOLDING_KNIFE", "KNIFE", "折到")),
    ("美工刀", ("美工刀", "UTILITY_KNIFE", "BOX_CUTTER")),
    ("多功能工具", ("多功能工具", "MULTITOOL")),
    ("收纳盒", ("收纳盒", "防水盒", "HARD_CASE", "STORAGE_BOX", "CASE")),
)
_BUILTIN_GLOSSARY_BRAND_MODEL_TERMS: list[dict[str, Any]] = [
    term
    for pack in list_builtin_glossary_packs()
    for term in list(pack.get("terms") or [])
    if isinstance(term, dict) and str(term.get("category") or "").strip().lower().endswith(("_brand", "_model"))
]


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
        return _enrich_semantic_facts_from_evidence(facts, evidence_bundle)
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


def _enrich_semantic_facts_from_evidence(
    facts: ContentSemanticFacts,
    evidence_bundle: dict[str, Any],
) -> ContentSemanticFacts:
    evidence_text = _build_evidence_text_blob(evidence_bundle)
    brand_candidates = list(facts.brand_candidates)
    model_candidates = list(facts.model_candidates)
    product_name_candidates = list(facts.product_name_candidates)
    product_type_candidates = list(facts.product_type_candidates)
    primary_subject_candidates = list(facts.primary_subject_candidates)
    search_expansions = list(facts.search_expansions)

    for term in _BUILTIN_GLOSSARY_BRAND_MODEL_TERMS:
        category = str(term.get("category") or "").strip().lower()
        correct_form = str(term.get("correct_form") or "").strip()
        if not correct_form or not _evidence_contains_term(evidence_text, correct_form, wrong_forms=term.get("wrong_forms") or []):
            continue
        if category.endswith("_brand") and correct_form not in brand_candidates:
            brand_candidates.append(correct_form)
        if category.endswith("_model"):
            if correct_form not in model_candidates:
                model_candidates.append(correct_form)
            if correct_form not in product_name_candidates:
                product_name_candidates.append(correct_form)

    for canonical, aliases in _GENERIC_PRODUCT_TYPE_ALIASES:
        if not _evidence_contains_any_alias(evidence_text, aliases):
            continue
        if canonical not in product_type_candidates:
            product_type_candidates.append(canonical)

    preferred_primary = _prefer_primary_subject_candidates(
        primary_subject_candidates=primary_subject_candidates,
        component_candidates=[*facts.component_candidates, *facts.aspect_candidates],
        product_name_candidates=product_name_candidates,
        product_type_candidates=product_type_candidates,
    )
    if not preferred_primary:
        preferred_primary = list(primary_subject_candidates)

    if not search_expansions:
        search_expansions = _build_search_expansions(
            brand_candidates=brand_candidates,
            model_candidates=model_candidates,
            product_name_candidates=product_name_candidates,
            product_type_candidates=product_type_candidates,
            primary_subject_candidates=preferred_primary,
        )

    return ContentSemanticFacts(
        primary_subject_candidates=preferred_primary,
        supporting_subject_candidates=list(facts.supporting_subject_candidates),
        component_candidates=list(facts.component_candidates),
        aspect_candidates=list(facts.aspect_candidates),
        brand_candidates=brand_candidates,
        model_candidates=model_candidates,
        product_name_candidates=product_name_candidates,
        product_type_candidates=product_type_candidates,
        entity_candidates=list(facts.entity_candidates),
        collaboration_pairs=list(facts.collaboration_pairs),
        search_expansions=search_expansions,
        evidence_sentences=list(facts.evidence_sentences),
    )


def _build_evidence_text_blob(evidence_bundle: dict[str, Any]) -> str:
    semantic_inputs = evidence_bundle.get("semantic_fact_inputs") if isinstance(evidence_bundle, dict) else {}
    semantic_inputs = semantic_inputs if isinstance(semantic_inputs, dict) else {}
    visual_semantic_evidence = evidence_bundle.get("visual_semantic_evidence") if isinstance(evidence_bundle, dict) else {}
    visual_semantic_evidence = visual_semantic_evidence if isinstance(visual_semantic_evidence, dict) else {}
    tokens: list[str] = []
    for raw in (
        semantic_inputs.get("source_name"),
        semantic_inputs.get("transcript_text"),
        semantic_inputs.get("visible_text"),
        *(semantic_inputs.get("cue_lines") or []),
        *(semantic_inputs.get("hint_candidates") or []),
        *(semantic_inputs.get("entity_like_tokens") or []),
        *(visual_semantic_evidence.get("object_categories") or []),
        *(visual_semantic_evidence.get("subject_candidates") or []),
        *(visual_semantic_evidence.get("visible_brands") or []),
        *(visual_semantic_evidence.get("visible_models") or []),
    ):
        text = str(raw or "").strip()
        if text:
            tokens.append(text)
    return " \n ".join(tokens)


def _evidence_contains_term(text_blob: str, correct_form: str, *, wrong_forms: list[Any]) -> bool:
    terms = [correct_form, *[str(item or "").strip() for item in wrong_forms]]
    return _evidence_contains_any_alias(text_blob, terms)


def _evidence_contains_any_alias(text_blob: str, aliases: list[str] | tuple[str, ...]) -> bool:
    haystack = str(text_blob or "")
    compact_haystack = _compact_ascii(haystack)
    for raw in aliases:
        alias = str(raw or "").strip()
        if not alias:
            continue
        if any(ord(ch) > 127 for ch in alias):
            if alias in haystack:
                return True
            continue
        compact_alias = _compact_ascii(alias)
        if compact_alias and compact_alias in compact_haystack:
            return True
    return False


def _compact_ascii(text: str) -> str:
    return "".join(ch for ch in str(text or "").upper() if ch.isalnum())


def _prefer_primary_subject_candidates(
    *,
    primary_subject_candidates: list[str],
    component_candidates: list[str],
    product_name_candidates: list[str],
    product_type_candidates: list[str],
) -> list[str]:
    ordered: list[str] = []
    component_set = {str(item).strip().lower() for item in component_candidates if str(item).strip()}

    def _is_component_like(value: str) -> bool:
        normalized = str(value or "").strip().lower()
        if not normalized:
            return False
        return normalized in component_set

    for group in (
        [item for item in primary_subject_candidates if not _is_component_like(item)],
        [item for item in primary_subject_candidates if _is_component_like(item)],
        [item for item in product_name_candidates if not _is_component_like(item)],
        [item for item in product_type_candidates if not _is_component_like(item)],
    ):
        for item in group:
            text = str(item or "").strip()
            if text and text not in ordered:
                ordered.append(text)
    return ordered


def _build_search_expansions(
    *,
    brand_candidates: list[str],
    model_candidates: list[str],
    product_name_candidates: list[str],
    product_type_candidates: list[str],
    primary_subject_candidates: list[str],
) -> list[str]:
    expansions: list[str] = []
    for item in (
        *primary_subject_candidates,
        *product_name_candidates,
        *product_type_candidates,
    ):
        text = str(item or "").strip()
        if text and text not in expansions:
            expansions.append(text)
    for brand in brand_candidates[:2]:
        for item in [*model_candidates[:2], *product_name_candidates[:2], *product_type_candidates[:2]]:
            combo = " ".join(part for part in (brand, item) if str(part).strip()).strip()
            if combo and combo not in expansions:
                expansions.append(combo)
    return expansions[:6]
