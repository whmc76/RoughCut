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
        "字段必须包括 brand_candidates, model_candidates, product_name_candidates, product_type_candidates, "
        "entity_candidates, collaboration_pairs, search_expansions, evidence_sentences。"
        "要求："
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
            max_tokens=1400,
            json_mode=True,
        )
        payload = repaired.as_json()
    return payload if isinstance(payload, dict) else {}
