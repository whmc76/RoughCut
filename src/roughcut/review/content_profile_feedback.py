from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.edit.presets import get_workflow_preset, select_workflow_template
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_profile_field_rules import CONTENT_PROFILE_FIELD_GUIDELINES
from roughcut.review.content_understanding_schema import normalize_video_type
from roughcut.review.content_understanding_verify import (
    HybridVerificationBundle,
    build_hybrid_verification_bundle,
)
from roughcut.usage import track_usage_operation


def _content_profile_module():
    from roughcut.review import content_profile as content_profile_module

    return content_profile_module


def _apply_accepted_corrections_to_excerpt(
    excerpt: str | None,
    accepted_corrections: list[dict[str, Any]] | None = None,
) -> str:
    text = str(excerpt or "")
    for item in accepted_corrections or []:
        original = str(item.get("original") or "").strip()
        accepted = str(item.get("accepted") or "").strip()
        if not original or not accepted or original == accepted:
            continue
        text = text.replace(original, accepted)
    return text


def build_review_feedback_verification_snapshot(
    verification_bundle: HybridVerificationBundle | None,
) -> dict[str, Any]:
    if verification_bundle is None:
        return {
            "search_queries": [],
            "online_count": 0,
            "database_count": 0,
            "online_results": [],
            "database_results": [],
        }

    search_queries = [
        query
        for query in (
            str(item).strip()
            for item in list(verification_bundle.search_queries or [])[:6]
        )
        if query
    ]

    online_results: list[dict[str, str]] = []
    for item in list(verification_bundle.online_results or [])[:4]:
        normalized = {
            "query": str((item or {}).get("query") or "").strip(),
            "title": str((item or {}).get("title") or "").strip(),
            "snippet": str((item or {}).get("snippet") or "").strip(),
            "url": str((item or {}).get("url") or "").strip(),
        }
        if any(normalized.values()):
            online_results.append(normalized)

    database_results: list[dict[str, str]] = []
    for item in list(verification_bundle.database_results or [])[:3]:
        normalized = {
            "brand": str((item or {}).get("brand") or "").strip(),
            "model": str((item or {}).get("model") or "").strip(),
            "primary_subject": str((item or {}).get("primary_subject") or "").strip(),
            "subject_type": str((item or {}).get("subject_type") or "").strip(),
            "source_type": str((item or {}).get("source_type") or "").strip(),
        }
        if any(normalized.values()):
            database_results.append(normalized)

    return {
        "search_queries": search_queries,
        "online_count": len(verification_bundle.online_results),
        "database_count": len(verification_bundle.database_results),
        "online_results": online_results,
        "database_results": database_results,
    }


def _normalize_review_feedback_match_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_/·.]+", "", text)


def _review_feedback_has_strong_verification_signal(
    proposed_feedback: dict[str, Any],
    verification_bundle: HybridVerificationBundle | None,
) -> bool:
    if verification_bundle is None:
        return False
    brand = _normalize_review_feedback_match_text(proposed_feedback.get("subject_brand"))
    model = _normalize_review_feedback_match_text(proposed_feedback.get("subject_model"))
    if not brand and not model:
        return False

    def _matches(text: str) -> bool:
        normalized = _normalize_review_feedback_match_text(text)
        if not normalized:
            return False
        brand_ok = not brand or brand in normalized
        model_ok = not model or model in normalized
        return brand_ok and model_ok

    online_hits = 0
    for item in verification_bundle.online_results:
        haystack = " ".join(
            [
                str((item or {}).get("title") or ""),
                str((item or {}).get("snippet") or ""),
                str((item or {}).get("url") or ""),
            ]
        )
        if _matches(haystack):
            online_hits += 1

    database_hits = 0
    for item in verification_bundle.database_results:
        haystack = " ".join(
            [
                str((item or {}).get("brand") or ""),
                str((item or {}).get("model") or ""),
                str((item or {}).get("primary_subject") or ""),
            ]
        )
        if _matches(haystack):
            database_hits += 1

    return database_hits > 0 or online_hits >= 2


async def _load_review_feedback_json_payload(
    provider: Any,
    response: Any,
) -> dict[str, Any]:
    try:
        payload = response.as_json()
    except Exception:
        raw_output = str(getattr(response, "content", "") or "").strip()
        if not raw_output:
            return {}
        repair_prompt = (
            "把下面的模型输出修复成一个严格 JSON 对象。"
            "不要 Markdown，不要代码块，不要解释。"
            "必须保留这些字段：apply_feedback, reason, subject_brand, subject_model, subject_type, video_theme, hook_line, visible_text, summary, engagement_question, search_queries。"
            '缺失字段时补空值，必须输出对象，结构参考：'
            '{"apply_feedback":false,"reason":"","subject_brand":"","subject_model":"","subject_type":"","video_theme":"","hook_line":"","visible_text":"","summary":"","engagement_question":"","search_queries":[]}'
            f"\n原始输出:\n{raw_output}"
        )
        repaired = await provider.complete(
            [
                Message(role="system", content="你是 JSON 修复器，只输出严格 JSON。"),
                Message(role="user", content=repair_prompt),
            ],
            temperature=0.0,
            max_tokens=700,
            json_mode=True,
        )
        try:
            payload = repaired.as_json()
        except Exception:
            return {}
    return payload if isinstance(payload, dict) else {}


def build_review_feedback_search_queries(
    *,
    draft_profile: dict[str, Any],
    proposed_feedback: dict[str, Any] | None = None,
    source_name: str | None = None,
    limit: int = 6,
) -> list[str]:
    cp = _content_profile_module()
    proposed = dict(proposed_feedback or {})
    brand = str(proposed.get("subject_brand") or draft_profile.get("subject_brand") or "").strip()
    model = str(proposed.get("subject_model") or draft_profile.get("subject_model") or "").strip()
    subject_type = str(proposed.get("subject_type") or draft_profile.get("subject_type") or "").strip()
    video_theme = str(proposed.get("video_theme") or draft_profile.get("video_theme") or "").strip()
    profile_source_name = str(
        source_name
        or draft_profile.get("source_name")
        or draft_profile.get("source_file_name")
        or ""
    ).strip()
    source_stem = Path(profile_source_name).stem if profile_source_name else ""
    queries: list[str] = []
    profile_with_feedback = dict(draft_profile)
    if brand:
        profile_with_feedback["subject_brand"] = brand
    if model:
        profile_with_feedback["subject_model"] = model
    if subject_type:
        profile_with_feedback["subject_type"] = subject_type
    if video_theme:
        profile_with_feedback["video_theme"] = video_theme
    if source_stem:
        profile_with_feedback["source_name"] = source_stem
    transcript_excerpt = str(draft_profile.get("transcript_excerpt") or "").strip()

    def _append(value: str) -> None:
        query = str(value or "").strip()
        if query and query not in queries and len(queries) < limit:
            queries.append(query)

    if brand and model:
        _append(f"{brand} {model}")
        if subject_type:
            _append(f"{brand} {model} {subject_type}")
    if model and subject_type:
        _append(f"{model} {subject_type}")
    if brand and subject_type:
        _append(f"{brand} {subject_type}")
    for item in list(draft_profile.get("search_queries") or []):
        query = str(item).strip()
        if not query:
            continue
        _append(query)
        if brand:
            _append(f"{brand} {query}")
        if model:
            _append(f"{model} {query}")
        if brand and model:
            _append(f"{brand} {model} {query}")
        if len(queries) >= limit:
            break

    if subject_type and not cp._is_generic_subject_type(subject_type):
        _append(subject_type)
    if model:
        _append(model)
    if brand:
        _append(brand)
    if video_theme:
        _append(video_theme)
    for term in cp._extract_topic_terms(video_theme):
        _append(term)

    if len(queries) < limit and source_stem:
        _append(cp._clean_line(source_stem))

    if len(queries) < limit:
        for query in cp._build_search_queries(
            profile_with_feedback,
            profile_source_name,
            transcript_excerpt=transcript_excerpt,
        ):
            _append(query)
            if len(queries) >= limit:
                break

    if len(queries) < limit:
        for query in cp._fallback_search_queries_for_profile(profile_with_feedback, profile_source_name):
            _append(query)

    return queries


async def build_review_feedback_verification_bundle(
    *,
    draft_profile: dict[str, Any],
    proposed_feedback: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
) -> HybridVerificationBundle | None:
    cp = _content_profile_module()
    search_queries = build_review_feedback_search_queries(
        draft_profile=draft_profile,
        proposed_feedback=proposed_feedback,
        source_name=str(draft_profile.get("source_name") or ""),
    )
    if not search_queries:
        return None
    return await build_hybrid_verification_bundle(
        search_queries=search_queries,
        online_search=cp._online_search_content_understanding,
        internal_search=None,
        session=session,
    )


async def resolve_content_profile_review_feedback(
    *,
    draft_profile: dict[str, Any],
    source_name: str,
    review_feedback: str | None = None,
    proposed_feedback: dict[str, Any] | None = None,
    reviewed_subtitle_excerpt: str | None = None,
    accepted_corrections: list[dict[str, Any]] | None = None,
    verification_bundle: HybridVerificationBundle | None = None,
) -> dict[str, Any]:
    cp = _content_profile_module()
    note = str(review_feedback or "").strip()
    proposed = dict(proposed_feedback or {})
    if not note and not any(proposed.values()):
        return {}

    try:
        provider = cp.get_reasoning_provider()
        reviewed_excerpt = str(reviewed_subtitle_excerpt or draft_profile.get("transcript_excerpt") or "").strip()
        current_snapshot = {
            "subject_brand": str(draft_profile.get("subject_brand") or "").strip(),
            "subject_model": str(draft_profile.get("subject_model") or "").strip(),
            "subject_type": str(draft_profile.get("subject_type") or "").strip(),
            "video_theme": str(draft_profile.get("video_theme") or "").strip(),
            "summary": str(draft_profile.get("summary") or "").strip(),
        }
        understanding = draft_profile.get("content_understanding") if isinstance(draft_profile.get("content_understanding"), dict) else {}
        understanding_snapshot = {
            "primary_subject": str(understanding.get("primary_subject") or "").strip(),
            "resolved_primary_subject": str(understanding.get("resolved_primary_subject") or "").strip(),
            "subject_entities": list(understanding.get("subject_entities") or [])[:6],
            "observed_entities": list(understanding.get("observed_entities") or [])[:6],
            "resolved_entities": list(understanding.get("resolved_entities") or [])[:6],
        }
        verification_snapshot = build_review_feedback_verification_snapshot(verification_bundle)
        accepted_examples = [
            {
                "original": str(item.get("original") or "").strip(),
                "accepted": str(item.get("accepted") or "").strip(),
            }
            for item in (accepted_corrections or [])
            if str(item.get("original") or "").strip() and str(item.get("accepted") or "").strip()
        ]
        prompt = (
            "你在解析成片审核意见，目标是判断这条审核意见是否应该作用到当前视频主体，并输出可执行修正补丁。"
            "审核意见是高优先级证据，但不能机械照抄；你必须先判断它是不是在修正当前主对象。"
            "如果视频围绕单一主产品展开，或围绕同一产品族做版本对比，而审核意见只是在修正该主产品的品牌、型号、系列或版本，通常应当应用。"
            "只有当审核意见明显指向另一个对象，或当前证据不足以判断作用对象时，才拒绝应用。"
            "不要被旧草稿中的错误品牌型号绑住，也不要因为 ASR 噪声而忽略人工修正。"
            "当前草稿里的品牌/型号可能本身就是错的，它们不能作为否决人工审核修正的主要依据。"
            "如果审核意见明确写了“品牌改成X、型号改成Y”，并且当前视频主题仍是同一类产品的开箱、评测、版本对比或上手体验，应优先把 X/Y 视为当前主对象的候选修正。"
            "返回 apply_feedback=true 时，才在 patch 中填入应应用字段；否则 patch 保持为空。"
            "输出 JSON："
            '{"apply_feedback":false,"reason":"","subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
            '"hook_line":"","visible_text":"","summary":"","engagement_question":"","search_queries":[]}'
            f"\n当前主对象快照：{json.dumps(current_snapshot, ensure_ascii=False)}"
            f"\n当前内容理解快照：{json.dumps(understanding_snapshot, ensure_ascii=False)}"
            f"\n审核意见原文：{note or '无'}"
            f"\n从审核意见提取的候选修正：{json.dumps(proposed, ensure_ascii=False)}"
            f"\n源文件名：{source_name}"
        )
        if reviewed_excerpt:
            prompt += f"\n当前字幕摘录：{reviewed_excerpt}"
        if accepted_examples:
            prompt += f"\n已接受的字幕校对：{json.dumps(accepted_examples[:12], ensure_ascii=False)}"
        if verification_bundle is not None:
            prompt += (
                "\n针对审核修正的混合检索结果（弱佐证，不能单独决定结论）："
                f"{json.dumps(verification_snapshot, ensure_ascii=False)}"
            )
        with track_usage_operation("content_profile.review_feedback_resolve"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是严谨的中文视频内容审核修正助手。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.1,
                max_tokens=700,
                json_mode=True,
            )
        payload = await _load_review_feedback_json_payload(provider, response)
        if not bool((payload or {}).get("apply_feedback")) and _review_feedback_has_strong_verification_signal(
            proposed,
            verification_bundle,
        ):
            repair_prompt = (
                "第一次判断偏保守。现在你已经拿到较强的外部佐证，请重新判断审核修正是否应作用于当前主对象。"
                "如果混合检索已经稳定支持 proposed_feedback，且当前视频仍围绕同一产品族展开，应优先应用审核修正。"
                "只有当检索结果明确指向别的对象时，才继续拒绝。"
                "输出同样的 JSON，并明确 apply_feedback。"
                f"\n当前主对象快照：{json.dumps(current_snapshot, ensure_ascii=False)}"
                f"\n当前内容理解快照：{json.dumps(understanding_snapshot, ensure_ascii=False)}"
                f"\n审核意见原文：{note or '无'}"
                f"\n候选修正：{json.dumps(proposed, ensure_ascii=False)}"
                f"\n混合检索结果：{json.dumps(verification_snapshot, ensure_ascii=False)}"
            )
            with track_usage_operation("content_profile.review_feedback_resolve_repair"):
                repair_response = await provider.complete(
                    [
                        Message(role="system", content="你是严谨的中文视频内容审核修正助手。"),
                        Message(role="user", content=repair_prompt),
                    ],
                    temperature=0.0,
                    max_tokens=700,
                    json_mode=True,
                )
            payload = await _load_review_feedback_json_payload(provider, repair_response)
        if not bool((payload or {}).get("apply_feedback")) and _review_feedback_has_strong_verification_signal(
            proposed,
            verification_bundle,
        ):
            minimal_prompt = (
                "当前任务只做最小修正判断。"
                "你只需要判断 proposed_feedback 中的品牌/型号是否应作用于当前视频主对象。"
                "前两轮未能稳定输出结果，但外部佐证已经较强。"
                "如果当前视频仍围绕同一产品族展开，且 proposed_feedback 与混合检索一致，就应 apply_feedback=true。"
                "只输出严格 JSON。"
                '{"apply_feedback":false,"reason":"","subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
                '"hook_line":"","visible_text":"","summary":"","engagement_question":"","search_queries":[]}'
                f"\n当前主对象快照：{json.dumps(current_snapshot, ensure_ascii=False)}"
                f"\n审核意见原文：{note or '无'}"
                f"\n候选修正：{json.dumps(proposed, ensure_ascii=False)}"
                f"\n混合检索结果：{json.dumps(verification_snapshot, ensure_ascii=False)}"
            )
            with track_usage_operation("content_profile.review_feedback_resolve_minimal_patch"):
                minimal_response = await provider.complete(
                    [
                        Message(role="system", content="你是严谨的中文视频内容审核修正助手。"),
                        Message(role="user", content=minimal_prompt),
                    ],
                    temperature=0.0,
                    max_tokens=500,
                    json_mode=True,
                )
            payload = await _load_review_feedback_json_payload(provider, minimal_response)
        if not bool((payload or {}).get("apply_feedback")):
            return {}
        resolved: dict[str, Any] = {}
        for key in (
            "subject_brand",
            "subject_model",
            "subject_type",
            "video_theme",
            "hook_line",
            "visible_text",
            "summary",
            "engagement_question",
        ):
            value = str((payload or {}).get(key) or "").strip()
            if value:
                resolved[key] = value
        queries: list[str] = []
        for item in list((payload or {}).get("search_queries") or []):
            value = str(item).strip()
            if value and value not in queries:
                queries.append(value)
        if queries:
            resolved["search_queries"] = list(queries)
            resolved["keywords"] = cp._build_review_keywords(
                {
                    "subject_brand": str(resolved.get("subject_brand") or "").strip(),
                    "subject_model": str(resolved.get("subject_model") or "").strip(),
                    "subject_type": str(resolved.get("subject_type") or "").strip(),
                    "video_theme": str(resolved.get("video_theme") or "").strip(),
                    "visible_text": str(resolved.get("visible_text") or "").strip(),
                    "search_queries": list(queries),
                }
            )
        return resolved
    except Exception:
        return {}


async def apply_content_profile_feedback(
    *,
    draft_profile: dict[str, Any],
    source_name: str,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    user_feedback: dict[str, Any],
    reviewed_subtitle_excerpt: str | None = None,
    accepted_corrections: list[dict[str, Any]] | None = None,
    skip_model_refinement: bool = False,
) -> dict[str, Any]:
    cp = _content_profile_module()
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    resolved_feedback: dict[str, Any] = dict(user_feedback or {})
    merged = dict(draft_profile or {})
    merged["user_feedback"] = dict(resolved_feedback)
    transcript_excerpt = str(
        reviewed_subtitle_excerpt
        or _apply_accepted_corrections_to_excerpt(merged.get("transcript_excerpt"), accepted_corrections)
        or merged.get("transcript_excerpt")
        or ""
    )
    merged["transcript_excerpt"] = transcript_excerpt
    content_understanding = dict(merged.get("content_understanding") or {}) if isinstance(merged.get("content_understanding"), dict) else {}
    feedback_video_type = normalize_video_type(str(resolved_feedback.get("video_type") or "").strip())
    current_video_type = normalize_video_type(
        str(content_understanding.get("video_type") or merged.get("content_kind") or "").strip()
    )
    effective_video_type = feedback_video_type or current_video_type
    if effective_video_type:
        merged["content_kind"] = effective_video_type
        content_understanding["video_type"] = effective_video_type
        merged["content_understanding"] = content_understanding
    if feedback_video_type:
        resolved_feedback["video_type"] = feedback_video_type

    if not any(value for value in resolved_feedback.values()):
        specific_subject_type = str(merged.get("subject_type") or "").strip()
        cp._ensure_subject_type_main(merged)
        if specific_subject_type and not cp._is_generic_subject_type(specific_subject_type):
            merged["subject_type"] = specific_subject_type
        cp._ensure_search_queries(merged, source_name, transcript_excerpt=transcript_excerpt)
        cp._ensure_review_fields_not_empty(merged, source_name=source_name, transcript_excerpt=transcript_excerpt)
        merged["keywords"] = cp._build_review_keywords(merged)
        preset = select_workflow_template(
            workflow_template=workflow_template,
            content_kind=cp._content_kind_name(merged),
            subject_domain=str(merged.get("subject_domain") or ""),
            subject_model=str(merged.get("subject_model") or ""),
            subject_type=str(merged.get("subject_type") or ""),
            transcript_hint=transcript_excerpt,
        )
        if not str(merged.get("hook_line") or "").strip() or cp._is_generic_cover_line(str(merged.get("hook_line") or "")):
            merged["hook_line"] = cp._build_cover_hook(
                hook=str(merged.get("hook_line") or ""),
                brand=cp._clean_line(merged.get("subject_brand") or merged.get("brand") or ""),
                model=cp._clean_line(merged.get("subject_model") or merged.get("model") or ""),
                subject_type=cp._clean_line(merged.get("subject_type") or ""),
                theme=cp._clean_line(str(merged.get("video_theme") or "").strip()),
                transcript_excerpt=transcript_excerpt,
                copy_style=str(merged.get("copy_style") or "attention_grabbing").strip() or "attention_grabbing",
                preset=preset,
            )
        merged["review_mode"] = "manual_confirmed"
        return merged

    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
    ):
        value = resolved_feedback.get(key)
        if value:
            merged[key] = str(value).strip()

    if resolved_feedback.get("keywords"):
        merged["search_queries"] = [str(item).strip() for item in resolved_feedback["keywords"] if str(item).strip()]
    elif isinstance(merged.get("search_queries"), list):
        existing_queries = [str(item).strip() for item in (merged.get("search_queries") or []) if str(item).strip()]
        if existing_queries:
            resolved_feedback["keywords"] = existing_queries
    if resolved_feedback.get("summary"):
        merged["summary"] = str(resolved_feedback["summary"]).strip()
    if resolved_feedback.get("engagement_question"):
        merged["engagement_question"] = str(resolved_feedback["engagement_question"]).strip()
    if resolved_feedback.get("copy_style"):
        merged["copy_style"] = str(resolved_feedback["copy_style"]).strip()
    if resolved_feedback.get("correction_notes"):
        merged["correction_notes"] = str(resolved_feedback["correction_notes"]).strip()
    if resolved_feedback.get("supplemental_context"):
        merged["supplemental_context"] = str(resolved_feedback["supplemental_context"]).strip()
    if not resolved_feedback.get("correction_notes"):
        merged.setdefault("correction_notes", "")
    if not resolved_feedback.get("supplemental_context"):
        merged.setdefault("supplemental_context", "")
    if not merged.get("search_queries"):
        merged["search_queries"] = build_review_feedback_search_queries(
            draft_profile=merged,
            source_name=source_name,
            proposed_feedback=resolved_feedback,
        )

    if skip_model_refinement:
        specific_subject_type = str(merged.get("subject_type") or "").strip()
        cp._ensure_subject_type_main(merged)
        if specific_subject_type and not cp._is_generic_subject_type(specific_subject_type):
            merged["subject_type"] = specific_subject_type
        cp._ensure_search_queries(merged, source_name, transcript_excerpt=transcript_excerpt)
        merged["keywords"] = cp._build_review_keywords(merged)
        merged_keywords = [str(item).strip() for item in (draft_profile.get("keywords") or []) if str(item).strip()]
        for keyword in merged_keywords:
            if keyword not in merged["keywords"]:
                merged["keywords"].append(keyword)
        preset = select_workflow_template(
            workflow_template=workflow_template,
            content_kind=cp._content_kind_name(merged),
            subject_domain=str(merged.get("subject_domain") or ""),
            subject_model=str(merged.get("subject_model") or ""),
            subject_type=str(merged.get("subject_type") or ""),
            transcript_hint=transcript_excerpt,
        )
        if not str(merged.get("hook_line") or "").strip() or cp._is_generic_cover_line(str(merged.get("hook_line") or "")):
            merged["hook_line"] = cp._build_cover_hook(
                hook=str(merged.get("hook_line") or ""),
                brand=cp._clean_line(merged.get("subject_brand") or merged.get("brand") or ""),
                model=cp._clean_line(merged.get("subject_model") or merged.get("model") or ""),
                subject_type=cp._clean_line(merged.get("subject_type") or ""),
                theme=cp._clean_line(str(merged.get("video_theme") or "").strip()),
                transcript_excerpt=transcript_excerpt,
                copy_style=str(merged.get("copy_style") or "attention_grabbing").strip() or "attention_grabbing",
                preset=preset,
            )
        cover_title = merged.get("cover_title")
        if not isinstance(cover_title, dict) or not cp._cover_title_is_usable(cover_title):
            merged["cover_title"] = cp.build_cover_title(merged, preset)
        if not str(merged.get("summary") or "").strip():
            merged["summary"] = cp._build_profile_summary(merged)
        if cp._is_generic_engagement_question(str(merged.get("engagement_question") or "")):
            merged["engagement_question"] = cp._build_fallback_engagement_question(merged, preset)
        cp._ensure_review_fields_not_empty(merged, source_name=source_name, transcript_excerpt=transcript_excerpt)
        merged["review_mode"] = "manual_confirmed"
        return merged

    try:
        provider = cp.get_reasoning_provider()
        accepted_examples = [
            {
                "original": str(item.get("original") or "").strip(),
                "accepted": str(item.get("accepted") or "").strip(),
            }
            for item in (accepted_corrections or [])
            if str(item.get("original") or "").strip() and str(item.get("accepted") or "").strip()
        ]
        reviewed_excerpt = transcript_excerpt
        prompt = (
            "你在整理一条中文短视频的人工确认摘要。请结合模型草稿和用户修正，"
            "输出一个后续可直接用于搜索、字幕修正和剪辑规划的确认版摘要。"
            "用户修正优先级最高，不要忽略用户手动填写的信息。\n"
            f"字段规则（通用）：\n"
            "subject_brand：视频主体品牌，不是频道名；subject_model：视频主体型号、版本或系列名，不要回填文件名或时间戳。\n"
            f"{CONTENT_PROFILE_FIELD_GUIDELINES}"
            "输出 JSON："
            '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
            '"hook_line":"","visible_text":"","summary":"","engagement_question":"","search_queries":[]}'
            f"\n模型草稿：{json.dumps(draft_profile or {}, ensure_ascii=False)}"
            f"\n用户修正：{json.dumps(user_feedback, ensure_ascii=False)}"
            f"\n源文件名：{source_name}"
        )
        if reviewed_excerpt:
            prompt += f"\n人工复检后的字幕摘录：{reviewed_excerpt}"
        if accepted_examples:
            prompt += f"\n已接受的字幕校对：{json.dumps(accepted_examples[:12], ensure_ascii=False)}"
        with track_usage_operation("content_profile.manual_feedback_normalize"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是严谨的中文视频内容摘要整理助手。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.1,
                max_tokens=700,
                json_mode=True,
            )
        normalized = response.as_json()
        merged.update({k: v for k, v in normalized.items() if v})
        for key in (
            "subject_brand",
            "subject_model",
            "subject_type",
            "video_theme",
            "hook_line",
            "visible_text",
            "summary",
            "engagement_question",
            "copy_style",
        ):
            value = str((normalized or {}).get(key) or "").strip()
            if value and not str(resolved_feedback.get(key) or "").strip():
                resolved_feedback[key] = value
        normalized_queries: list[str] = []
        for item in list((normalized or {}).get("search_queries") or []):
            query = str(item).strip()
            if query and query not in normalized_queries:
                normalized_queries.append(query)
        if normalized_queries and not list(resolved_feedback.get("keywords") or []):
            resolved_feedback["keywords"] = normalized_queries
    except Exception:
        pass
    merged["user_feedback"] = dict(resolved_feedback)

    result = await cp.enrich_content_profile(
        profile=merged,
        source_name=source_name,
        channel_profile=workflow_template,
        transcript_excerpt=transcript_excerpt,
        include_research=False,
    )
    result["user_feedback"] = dict(resolved_feedback)
    result["review_mode"] = "manual_confirmed"
    if "workflow_mode" in merged and "workflow_mode" not in result:
        result["workflow_mode"] = str(merged.get("workflow_mode") or "")
    if "enhancement_modes" in merged and "enhancement_modes" not in result:
        result["enhancement_modes"] = list(merged.get("enhancement_modes") or [])
    if effective_video_type:
        result["content_kind"] = effective_video_type
        result_understanding = dict(result.get("content_understanding") or {}) if isinstance(result.get("content_understanding"), dict) else {}
        result_understanding["video_type"] = effective_video_type
        result["content_understanding"] = result_understanding

    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
        "summary",
        "engagement_question",
        "copy_style",
    ):
        value = resolved_feedback.get(key)
        if value:
            result[key] = str(value).strip()
    if resolved_feedback.get("keywords"):
        manual_queries: list[str] = []
        for item in resolved_feedback["keywords"]:
            query = str(item).strip()
            if query and query not in manual_queries:
                manual_queries.append(query)
        if manual_queries:
            result["search_queries"] = manual_queries
    if not result.get("search_queries"):
        result["search_queries"] = build_review_feedback_search_queries(
            draft_profile=result,
            source_name=source_name,
            proposed_feedback=resolved_feedback,
        )
    resolved_specific_subject_type = str(result.get("subject_type") or "").strip()
    cp._ensure_subject_type_main(result)
    if resolved_specific_subject_type and not cp._is_generic_subject_type(resolved_specific_subject_type):
        result["subject_type"] = resolved_specific_subject_type
    cp._ensure_search_queries(result, source_name, transcript_excerpt=transcript_excerpt)
    result["keywords"] = cp._build_review_keywords(result)
    merged_keywords = [str(item).strip() for item in (merged.get("keywords") or []) if str(item).strip()]
    for keyword in merged_keywords:
        if keyword not in result["keywords"]:
            result["keywords"].append(keyword)
    if any(
        resolved_feedback.get(key)
        for key in (
            "subject_brand",
            "subject_model",
            "subject_type",
            "video_theme",
            "hook_line",
            "visible_text",
        )
    ):
        preset = get_workflow_preset(str(result.get("workflow_template") or workflow_template or "unboxing_standard"))
        result["cover_title"] = cp.build_cover_title(result, preset)
    cp._ensure_review_fields_not_empty(result, source_name=source_name, transcript_excerpt=transcript_excerpt)
    return result


__all__ = [
    "apply_content_profile_feedback",
    "build_review_feedback_search_queries",
    "build_review_feedback_verification_bundle",
    "build_review_feedback_verification_snapshot",
    "resolve_content_profile_review_feedback",
]
