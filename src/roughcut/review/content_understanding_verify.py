from __future__ import annotations

from dataclasses import dataclass, field, is_dataclass, asdict
import json
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_understanding_infer import parse_content_understanding_payload
from roughcut.review.content_understanding_resolution import resolve_entities, should_run_entity_resolution
from roughcut.review.content_understanding_retrieval import search_confirmed_content_entities
from roughcut.review.content_understanding_schema import ContentUnderstanding, map_content_understanding_to_legacy_profile


SearchCallable = Callable[..., Awaitable[list[Any]]]


@dataclass(frozen=True)
class HybridVerificationBundle:
    search_queries: list[str] = field(default_factory=list)
    online_results: list[Any] = field(default_factory=list)
    database_results: list[Any] = field(default_factory=list)


def build_verification_search_queries(
    understanding: ContentUnderstanding,
    *,
    override_search_queries: list[str] | None = None,
    limit: int = 6,
) -> list[str]:
    merged: list[str] = []
    for source in (
        override_search_queries or [],
        understanding.search_queries,
        understanding.semantic_facts.search_expansions,
    ):
        for item in source:
            query = str(item).strip()
            if query and query not in merged:
                merged.append(query)
            if len(merged) >= limit:
                return merged
    return merged


async def build_hybrid_verification_bundle(
    *,
    search_queries: list[str],
    online_search: SearchCallable | None = None,
    internal_search: SearchCallable | None = None,
    session: AsyncSession | None = None,
) -> HybridVerificationBundle:
    normalized_queries = [str(query).strip() for query in search_queries if str(query).strip()]
    online_results = await _run_search(online_search, search_queries=normalized_queries)
    database_results = await _run_internal_search(
        internal_search,
        session=session,
        search_queries=normalized_queries,
    )
    return HybridVerificationBundle(
        search_queries=normalized_queries,
        online_results=list(online_results),
        database_results=list(database_results),
    )


async def verify_content_understanding(
    *,
    understanding: ContentUnderstanding,
    evidence_bundle: dict[str, Any],
    verification_bundle: HybridVerificationBundle | None = None,
    search_queries: list[str] | None = None,
    session: AsyncSession | None = None,
    online_search: SearchCallable | None = None,
    internal_search: SearchCallable | None = None,
    provider=None,
) -> ContentUnderstanding:
    queries = build_verification_search_queries(
        understanding,
        override_search_queries=search_queries,
    )
    bundle = verification_bundle or await build_hybrid_verification_bundle(
        search_queries=queries,
        online_search=online_search,
        internal_search=internal_search,
        session=session,
    )
    reasoning_provider = provider or get_reasoning_provider()
    prompt_payload = _bundle_to_prompt_payload(bundle)
    prompt = (
        "你是内容理解核验器。请结合在线搜索结果与内部已确认实体，判断内容在讲什么，并输出 JSON。"
        "联网搜索和数据库命中都只是弱佐证，不能覆盖当前视频的直接证据。"
        "要求："
        "1. 只输出可核验的内容，不要编造。"
        "2. primary_subject 要尽量具体，且优先对应视频真正围绕的主对象或主产品。"
        "3. subject_entities 至少列出相关主体。"
        "4. uncertainties 要写明不确定之处。"
        "5. observed_entities 要保留视频里的原始称呼；resolved_entities 和 resolved_primary_subject 用于归一化结果；"
        "6. entity_resolution_map 要说明 observed 到 resolved 的映射。"
        "7. conflicts 要列出与当前视频原始理解冲突的字段名。"
        "7.5. 如果原始理解里的 semantic_facts 已经区分了 primary_subject_candidates、component_candidates、aspect_candidates，优先保持这种主次关系；"
        "8. 不要把功能系统、工艺过程、配件、服务方、合作方或背景元素顶替成主主体，除非视频明确就是在讲它们本身。"
        "JSON 结构："
        "{"
        '"video_type":"","content_domain":"","primary_subject":"","subject_entities":[{"kind":"","name":"","brand":"","model":""}],'
        '"observed_entities":[{"kind":"","name":"","brand":"","model":""}],'
        '"resolved_entities":[{"kind":"","name":"","brand":"","model":""}],"resolved_primary_subject":"","entity_resolution_map":[{"observed_name":"","resolved_name":"","confidence":0.0,"reason":""}],'
        '"video_theme":"","summary":"","hook_line":"","engagement_question":"","search_queries":[],"evidence_spans":[],'
        '"uncertainties":[],"conflicts":[],"confidence":{},"needs_review":true,"review_reasons":[]'
        "}"
        f"\n原始理解：{json.dumps(map_content_understanding_to_legacy_profile(understanding), ensure_ascii=False)}"
        f"\n当前视频证据：{json.dumps(evidence_bundle, ensure_ascii=False)}"
        f"\n混合检索输入：{json.dumps(prompt_payload, ensure_ascii=False)}"
    )
    response = await reasoning_provider.complete(
        [
            Message(
                role="system",
                content="你是严谨的内容理解核验模型，必须输出 JSON。",
            ),
            Message(role="user", content=prompt),
        ],
        temperature=0.0,
        max_tokens=2200,
        json_mode=True,
    )
    candidate = parse_content_understanding_payload(response.as_json())
    allow_entity_resolution = should_run_entity_resolution(
        understanding=understanding,
        candidate=candidate,
        evidence_bundle=evidence_bundle,
        verification_bundle=bundle,
    )
    return resolve_entities(
        base=understanding,
        candidate=candidate,
        evidence_bundle=evidence_bundle,
        allow_entity_resolution=allow_entity_resolution,
    )


async def _run_search(online_search: SearchCallable | None, *, search_queries: list[str]) -> list[Any]:
    if online_search is not None:
        return await online_search(search_queries=search_queries)

    provider = get_search_provider()
    results: list[Any] = []
    for query in search_queries:
        results.extend(await provider.search(query))
    return results


async def _run_internal_search(
    internal_search: SearchCallable | None,
    *,
    session: AsyncSession | None,
    search_queries: list[str],
) -> list[Any]:
    if internal_search is not None:
        return await internal_search(search_queries=search_queries)
    if session is None:
        return []
    return await search_confirmed_content_entities(session, search_queries=search_queries)


def _bundle_to_prompt_payload(bundle: HybridVerificationBundle) -> dict[str, Any]:
    return {
        "search_queries": list(bundle.search_queries),
        "online_results": [_result_to_dict(item) for item in bundle.online_results],
        "database_results": [_result_to_dict(item) for item in bundle.database_results],
    }


def _result_to_dict(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return dict(item)
    if is_dataclass(item):
        return asdict(item)
    if hasattr(item, "__dict__"):
        return {
            key: value
            for key, value in vars(item).items()
            if not key.startswith("_")
        }
    return {"value": str(item)}


