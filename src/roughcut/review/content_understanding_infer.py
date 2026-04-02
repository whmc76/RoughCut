from __future__ import annotations

from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_schema import (
    ContentSemanticFacts,
    ContentUnderstanding,
    SubjectEntity,
    parse_content_semantic_facts_payload,
)


def parse_content_understanding_payload(data: Any) -> ContentUnderstanding:
    payload = data if isinstance(data, dict) else {}

    subject_entities: list[SubjectEntity] = []
    for item in list(payload.get("subject_entities") or []):
        if isinstance(item, str) and item.strip():
            subject_entities.append(
                SubjectEntity(
                    kind="",
                    name=item.strip(),
                    brand="",
                    model="",
                )
            )
            continue
        if not isinstance(item, dict):
            continue
        subject_entities.append(
            SubjectEntity(
                kind=str(item.get("kind") or "").strip(),
                name=str(item.get("name") or "").strip(),
                brand=str(item.get("brand") or "").strip(),
                model=str(item.get("model") or "").strip(),
            )
        )

    confidence: dict[str, float] = {}
    raw_confidence = payload.get("confidence")
    if isinstance(raw_confidence, dict):
        for key, value in raw_confidence.items():
            try:
                confidence[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
    else:
        try:
            confidence["overall"] = float(raw_confidence)
        except (TypeError, ValueError):
            pass

    return ContentUnderstanding(
        video_type=str(payload.get("video_type") or "").strip(),
        content_domain=str(payload.get("content_domain") or "").strip(),
        primary_subject=str(payload.get("primary_subject") or "").strip(),
        semantic_facts=parse_content_semantic_facts_payload(payload.get("semantic_facts")),
        subject_entities=subject_entities,
        video_theme=str(payload.get("video_theme") or "").strip(),
        summary=str(payload.get("summary") or "").strip(),
        hook_line=str(payload.get("hook_line") or "").strip(),
        engagement_question=str(payload.get("engagement_question") or "").strip(),
        search_queries=[str(item).strip() for item in list(payload.get("search_queries") or []) if str(item).strip()],
        evidence_spans=[dict(item) for item in list(payload.get("evidence_spans") or []) if isinstance(item, dict)],
        uncertainties=[str(item).strip() for item in list(payload.get("uncertainties") or []) if str(item).strip()],
        confidence=confidence,
        needs_review=bool(payload.get("needs_review", True)),
        review_reasons=[str(item).strip() for item in list(payload.get("review_reasons") or []) if str(item).strip()],
    )


async def infer_content_understanding(evidence_bundle: dict[str, Any]) -> ContentUnderstanding:
    provider = get_reasoning_provider()
    semantic_facts = await _infer_content_semantic_facts(provider, evidence_bundle)
    prompt = _build_content_understanding_prompt(evidence_bundle, semantic_facts)

    response = await provider.complete(
        [
            Message(role="system", content="你是内容理解分析器，输出必须是 JSON。"),
            Message(role="user", content=prompt),
        ],
        temperature=0.1,
        max_tokens=900,
        json_mode=True,
    )
    understanding = parse_content_understanding_payload(
        await _load_json_object(
            provider,
            response,
            required_fields=[
                "video_type",
                "content_domain",
                "primary_subject",
                "subject_entities",
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
                '"video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[],'
                '"evidence_spans":[],"uncertainties":[],"confidence":{},"needs_review":true,"review_reasons":[]}'
            ),
        )
    )
    if understanding.semantic_facts == ContentSemanticFacts():
        understanding = ContentUnderstanding(
            video_type=understanding.video_type,
            content_domain=understanding.content_domain,
            primary_subject=understanding.primary_subject,
            semantic_facts=semantic_facts,
            subject_entities=understanding.subject_entities,
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
        )
    return understanding


def _build_content_understanding_prompt(
    evidence_bundle: dict[str, Any],
    semantic_facts: ContentSemanticFacts,
) -> str:
    transcript_excerpt = str(evidence_bundle.get("transcript_excerpt") or "").strip()
    prompt = (
        "你是严谨的视频内容理解引擎。根据证据包和已抽取的语义事实，推断一个通用内容理解结果，"
        "只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。"
        "字段必须包括 video_type, content_domain, primary_subject, semantic_facts, subject_entities, "
        "video_theme, summary, hook_line, engagement_question, search_queries, evidence_spans, "
        "uncertainties, confidence, needs_review, review_reasons。"
        "约束："
        "semantic_facts 必须是对象，字段包括 brand_candidates, model_candidates, product_name_candidates, "
        "product_type_candidates, entity_candidates, collaboration_pairs, search_expansions, evidence_sentences；"
        "subject_entities 必须是对象数组，每项包含 kind,name,brand,model；"
        "summary 用中文且不超过 120 字；"
        "hook_line 用中文且不超过 24 字；"
        "search_queries 最多 4 条，优先结合 semantic_facts.search_expansions 生成；"
        "evidence_spans 最多 6 条，字段只允许 timestamp,text,type；"
        "confidence 必须是对象，例如 {\"overall\":0.78}；"
        "信息不足时字段留空或空数组，不要编造。"
        f"\n证据包: {evidence_bundle}"
        f"\n语义事实: {semantic_facts.__dict__}"
    )
    if transcript_excerpt:
        prompt += f"\n转写片段: {transcript_excerpt}"
    return prompt


async def _infer_content_semantic_facts(
    provider: Any,
    evidence_bundle: dict[str, Any],
) -> ContentSemanticFacts:
    prompt = (
        "你是视频证据语义抽取器。请根据多模态证据提取可供后续检索和消歧使用的通用语义事实，"
        "只输出一个 JSON 对象，不要 Markdown，不要代码块，不要解释。"
        "字段必须包括 brand_candidates, model_candidates, product_name_candidates, product_type_candidates, "
        "entity_candidates, collaboration_pairs, search_expansions, evidence_sentences。"
        "要求："
        "只提取证据支持的候选，不要输出最终结论；"
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
        return parse_content_semantic_facts_payload(
            await _load_json_object(
                provider,
                response,
                required_fields=[
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
                    '{"brand_candidates":[],"model_candidates":[],"product_name_candidates":[],'
                    '"product_type_candidates":[],"entity_candidates":[],"collaboration_pairs":[],'
                    '"search_expansions":[],"evidence_sentences":[]}'
                ),
            )
        )
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
            max_tokens=900,
            json_mode=True,
        )
        payload = repaired.as_json()
    return payload if isinstance(payload, dict) else {}
