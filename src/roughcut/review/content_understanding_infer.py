from __future__ import annotations

from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_evidence import normalize_evidence_bundle
from roughcut.review.content_understanding_facts import _load_json_object, infer_content_semantic_facts
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    parse_content_understanding_payload as parse_content_understanding_payload_from_schema,
)


def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    return parse_content_understanding_payload_from_schema(data)


async def infer_content_understanding(evidence_bundle: dict[str, Any]) -> ContentUnderstanding:
    evidence_bundle = normalize_evidence_bundle(evidence_bundle)
    provider = get_reasoning_provider()
    semantic_facts = await infer_content_semantic_facts(provider, evidence_bundle)
    understanding = await infer_final_understanding(provider, evidence_bundle, semantic_facts)
    return _with_staged_semantic_facts(understanding, semantic_facts)


async def infer_final_understanding(
    provider: Any,
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> ContentUnderstanding:
    prompt = _build_content_understanding_prompt(evidence_bundle, semantic_facts)

    response = await provider.complete(
        [
            Message(role="system", content="你是内容理解分析器，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=1400,
        json_mode=True,
    )
    payload = await _load_json_object(
        provider,
        response,
        required_fields=[
            "video_type",
            "content_domain",
            "primary_subject",
            "subject_entities",
            "observed_entities",
            "resolved_entities",
            "resolved_primary_subject",
            "entity_resolution_map",
            "video_theme",
            "summary",
            "hook_line",
            "engagement_question",
            "search_queries",
            "evidence_spans",
            "uncertainties",
            "confidence",
            "needs_review",
            "review_reasons",
        ],
        empty_object_description=(
            '{"video_type":"","content_domain":"","primary_subject":"","subject_entities":[],'
            '"observed_entities":[],"resolved_entities":[],"resolved_primary_subject":"","entity_resolution_map":[],'
            '"video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[],'
            '"evidence_spans":[],"uncertainties":[],"confidence":{},"needs_review":true,"review_reasons":[]}'
        ),
    )
    understanding = parse_content_understanding_payload(payload)
    if _needs_understanding_repair(understanding, semantic_facts):
        repaired_payload = await _repair_empty_understanding_payload(
            provider=provider,
            response=response,
            evidence_bundle=evidence_bundle,
            semantic_facts=semantic_facts,
        )
        repaired_understanding = parse_content_understanding_payload(repaired_payload)
        if not _needs_understanding_repair(repaired_understanding, semantic_facts):
            understanding = repaired_understanding
    if understanding.semantic_facts == ContentSemanticFacts():
        understanding = ContentUnderstanding(
            video_type=understanding.video_type,
            content_domain=understanding.content_domain,
            primary_subject=understanding.primary_subject,
            semantic_facts=semantic_facts,
            subject_entities=understanding.subject_entities,
            observed_entities=understanding.observed_entities,
            resolved_entities=understanding.resolved_entities,
            resolved_primary_subject=understanding.resolved_primary_subject,
            entity_resolution_map=understanding.entity_resolution_map,
            video_theme=understanding.video_theme,
            summary=understanding.summary,
            hook_line=understanding.hook_line,
            engagement_question=understanding.engagement_question,
            search_queries=understanding.search_queries or semantic_facts.search_expansions[:4],
            evidence_spans=understanding.evidence_spans,
            uncertainties=understanding.uncertainties,
            confidence=understanding.confidence,
            needs_review=understanding.needs_review,
            review_reasons=understanding.review_reasons,
            capability_matrix=understanding.capability_matrix,
            orchestration_trace=understanding.orchestration_trace,
        )
    return understanding


def _with_staged_semantic_facts(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
) -> ContentUnderstanding:
    return ContentUnderstanding(
        video_type=understanding.video_type,
        content_domain=understanding.content_domain,
        primary_subject=understanding.primary_subject,
        semantic_facts=semantic_facts,
        subject_entities=understanding.subject_entities,
        observed_entities=understanding.observed_entities,
        resolved_entities=understanding.resolved_entities,
        resolved_primary_subject=understanding.resolved_primary_subject,
        entity_resolution_map=understanding.entity_resolution_map,
        video_theme=understanding.video_theme,
        summary=understanding.summary,
        hook_line=understanding.hook_line,
        engagement_question=understanding.engagement_question,
        search_queries=understanding.search_queries or semantic_facts.search_expansions[:4],
        evidence_spans=understanding.evidence_spans,
        uncertainties=understanding.uncertainties,
        confidence=understanding.confidence,
        needs_review=understanding.needs_review,
        review_reasons=understanding.review_reasons,
        capability_matrix=understanding.capability_matrix,
        orchestration_trace=understanding.orchestration_trace,
    )


def _build_content_understanding_prompt(
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> str:
    transcript_excerpt = str(evidence_bundle.get("transcript_excerpt") or "").strip()
    compact_evidence = _build_compact_evidence_payload(evidence_bundle)
    prompt = (
        "你是严谨的视频内容理解引擎。根据证据包和已抽取的语义事实，推断一个通用内容理解结果，"
        "只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。"
        "字段必须包括 video_type, content_domain, primary_subject, subject_entities, observed_entities, "
        "resolved_entities, resolved_primary_subject, entity_resolution_map, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        "约束："
        "subject_entities 必须是对象数组，每项包含 kind,name,brand,model；"
        "observed_entities 必须保留视频里原始看到或听到的主体称呼；"
        "resolved_entities、resolved_primary_subject、entity_resolution_map 在首轮推断可为空；"
        "summary 用中文且不超过 100 字；"
        "hook_line 用中文且不超过 24 字；"
        "search_queries 最多 4 条，优先结合 semantic_facts.search_expansions 生成；"
        "evidence_spans 最多 4 条，字段只允许 timestamp,text,type；"
        "confidence 必须是对象，例如 {\"overall\":0.78}；"
        "信息不足时字段留空或空数组，不要编造。"
        f"\n紧凑证据包: {compact_evidence}"
        f"\n语义事实: {semantic_facts.__dict__}"
    )
    if transcript_excerpt:
        prompt += f"\n转写片段: {transcript_excerpt}"
    return prompt


def _build_compact_evidence_payload(evidence_bundle: dict[str, Any]) -> dict[str, Any]:
    semantic_fact_inputs = evidence_bundle.get("semantic_fact_inputs")
    raw_semantic_inputs = semantic_fact_inputs if isinstance(semantic_fact_inputs, dict) else {}
    compact_semantic_inputs = {
        "source_name": str(raw_semantic_inputs.get("source_name") or "").strip(),
        "cue_lines": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("cue_lines") or [])
            if str(item).strip()
        ][:8],
        "relation_hints": [
            {
                str(key): str(value).strip()
                for key, value in item.items()
                if str(value).strip()
            }
            for item in (raw_semantic_inputs.get("relation_hints") or [])
            if isinstance(item, dict)
        ][:8],
        "transcript_text": str(raw_semantic_inputs.get("transcript_text") or "").strip(),
        "visible_text": str(raw_semantic_inputs.get("visible_text") or "").strip(),
        "hint_candidates": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("hint_candidates") or [])
            if str(item).strip()
        ][:12],
        "entity_like_tokens": [
            str(item).strip()
            for item in (raw_semantic_inputs.get("entity_like_tokens") or [])
            if str(item).strip()
        ][:20],
    }
    candidate_hints = evidence_bundle.get("candidate_hints")
    compact_candidate_hints = candidate_hints if isinstance(candidate_hints, dict) else {}
    return {
        "source_name": str(evidence_bundle.get("source_name") or "").strip(),
        "transcript_excerpt": str(evidence_bundle.get("transcript_excerpt") or "").strip(),
        "visible_text": str(evidence_bundle.get("visible_text") or "").strip(),
        "semantic_fact_inputs": compact_semantic_inputs,
        "candidate_hints": compact_candidate_hints,
    }




def _needs_understanding_repair(
    understanding: ContentUnderstanding,
    semantic_facts: ContentSemanticFacts,
) -> bool:
    informative_semantic_facts = any(
        (
            semantic_facts.brand_candidates,
            semantic_facts.model_candidates,
            semantic_facts.product_name_candidates,
            semantic_facts.product_type_candidates,
            semantic_facts.entity_candidates,
            semantic_facts.collaboration_pairs,
            semantic_facts.search_expansions,
            semantic_facts.evidence_sentences,
        )
    )
    if not informative_semantic_facts:
        return False
    has_core_output = any(
        (
            understanding.video_type,
            understanding.content_domain,
            understanding.primary_subject,
            understanding.subject_entities,
            understanding.video_theme,
            understanding.summary,
            understanding.hook_line,
            understanding.engagement_question,
            understanding.search_queries,
            understanding.review_reasons,
        )
    )
    return not has_core_output


async def _repair_empty_understanding_payload(
    *,
    provider: Any,
    response: Any,
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> dict[str, Any]:
    repair_prompt = (
        "下面这个内容理解结果虽然是 JSON，但核心字段为空。"
        "请基于原始输出、语义事实和紧凑证据，重写成一个严格 JSON 对象。"
        "不要输出 Markdown，不要代码块，不要解释。"
        "字段必须包括 video_type, content_domain, primary_subject, subject_entities, observed_entities, "
        "resolved_entities, resolved_primary_subject, entity_resolution_map, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        "要求："
        "1. 如果证据足够，就补全最合理的内容理解结果；"
        "2. 如果证据不足，也必须明确写出 review_reasons，不能整包留空；"
        "3. 不要编造未被证据支持的品牌/型号；"
        "4. 允许保守，但不能忽略 semantic_facts 已经明确给出的候选。"
        f"\n原始输出:\n{getattr(response, 'content', '')}"
        f"\n语义事实:\n{semantic_facts.__dict__}"
        f"\n紧凑证据包:\n{_build_compact_evidence_payload(evidence_bundle)}"
    )
    repaired = await provider.complete(
        [
            Message(role="system", content="你是内容理解 JSON 修复器，只输出严格 JSON。"),
            Message(role="user", content=repair_prompt),
        ],
        temperature=0.0,
        max_tokens=1400,
        json_mode=True,
    )
    payload = repaired.as_json()
    return payload if isinstance(payload, dict) else {}
