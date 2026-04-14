from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from roughcut.config import get_settings
from roughcut.edit.presets import WorkflowPreset, get_workflow_preset, normalize_workflow_template_name, select_workflow_template
from roughcut.llm_cache import digest_payload
from roughcut.providers.factory import get_ocr_provider, get_reasoning_provider, get_search_provider
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.usage import track_usage_operation
from roughcut.db.session import get_session_factory
from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities
from roughcut.review.content_understanding_evidence import build_evidence_bundle
from roughcut.review.content_understanding_infer import infer_content_understanding
from roughcut.review.content_understanding_schema import (
    ContentUnderstanding,
    map_content_understanding_to_legacy_profile,
    normalize_video_type,
)
from roughcut.review.content_understanding_visual import infer_visual_semantic_evidence
from roughcut.review.content_understanding_verify import (
    HybridVerificationBundle,
    build_hybrid_verification_bundle,
    build_verification_search_queries,
    verify_content_understanding,
)
from roughcut.review.content_profile_memory import summarize_content_profile_user_memory
from roughcut.review.content_profile_ocr import build_content_profile_ocr
from roughcut.review.content_profile_candidates import build_identity_candidates
from roughcut.review.content_profile_evidence import IdentityEvidenceBundle
from roughcut.review.spoken_identity import canonicalize_spoken_identity_text
from roughcut.review.content_profile_keywords import (
    _clean_line as _clean_line_keywords,
    _extract_query_support_terms as _extract_query_support_terms_keywords,
    _extract_search_signal_terms as _extract_search_signal_terms_keywords,
    _extract_topic_terms as _extract_topic_terms_keywords,
    _is_informative_source_hint as _is_informative_source_hint_keywords,
    _looks_like_camera_stem as _looks_like_camera_stem_keywords,
    _normalize_profile_value as _normalize_profile_value_keywords,
    build_review_keywords as _build_review_keywords_public,
    collect_review_keyword_seed_terms as _collect_review_keyword_seed_terms_public,
    extract_review_keyword_tokens as _extract_review_keyword_tokens_public,
    fallback_search_queries_for_profile as _fallback_search_queries_for_profile_public,
    normalize_query_list as _normalize_query_list_public,
)
from roughcut.review.content_profile_feedback import (
    apply_content_profile_feedback as _apply_content_profile_feedback_public,
    build_review_feedback_search_queries as _build_review_feedback_search_queries_public,
    build_review_feedback_verification_bundle as _build_review_feedback_verification_bundle_public,
    build_review_feedback_verification_snapshot as _build_review_feedback_verification_snapshot_public,
    resolve_content_profile_review_feedback as _resolve_content_profile_review_feedback_public,
)
from roughcut.review.content_profile_resolve import resolve_identity_candidates
from roughcut.review.content_profile_review_stats import build_content_profile_auto_review_gate
from roughcut.review.content_profile_scoring import score_identity_candidates
from roughcut.review.content_profile_field_rules import CONTENT_PROFILE_FIELD_GUIDELINES
from roughcut.review.domain_glossaries import detect_glossary_domains, select_primary_subject_domain
from roughcut.review.platform_copy import build_transcript_for_packaging
from roughcut.review.subtitle_memory import (
    _extract_compound_components,
    apply_domain_term_corrections,
    summarize_subtitle_review_memory_for_polish,
)
from roughcut.speech.postprocess import (
    apply_subtitle_clause_spacing,
    cleanup_subtitle_fillers,
    normalize_display_numbers,
    normalize_display_text,
)

_CONTENT_PROFILE_INFER_CACHE_VERSION = "2026-04-14.infer.v36"
_CONTENT_PROFILE_ENRICH_CACHE_VERSION = "2026-04-14.enrich.v37"
_INGESTIBLE_PRODUCT_SIGNALS = (
    "luckykiss",
    "kisspod",
    "kissport",
    "含片",
    "益生菌",
    "口香糖",
    "薄荷糖",
    "零糖",
    "口气",
)
_INGESTIBLE_DEFAULT_SUBJECT_TYPE = "弹射益生菌含片"
_GEAR_STYLE_SIGNALS = (
    "工具钳",
    "战术笔",
    "edc",
    "弹夹",
    "装备",
    "莱德曼",
)
_SOURCE_BRAND_PREFIX_STOPWORDS = {
    "年度",
    "旗舰",
    "旗舰级",
    "旗舰款",
    "新品",
    "新款",
    "新版",
    "系列",
    "官方",
    "品牌",
    "开箱",
    "评测",
    "测评",
    "详评",
    "体验",
    "教程",
    "横版",
    "竖版",
    "主片",
    "素板",
    "封面",
    "成片",
    "预览",
    "特效",
    "数字",
    "字幕",
    "白铜",
    "铜雕",
    "雕像",
}

_CONTENT_KIND_DEFAULT_SUBJECT_TYPE = {
    "tutorial": "录屏教学",
    "vlog": "Vlog日常",
    "commentary": "口播观点",
    "gameplay": "游戏实况",
    "food": "探店试吃",
}

_CONTENT_KIND_DEFAULT_VIDEO_THEME = {
    "tutorial": "软件流程演示与步骤讲解",
    "vlog": "日常记录与生活分享",
    "commentary": "观点表达与信息拆解",
    "gameplay": "高能操作与对局复盘",
    "food": "探店试吃与性价比判断",
}
_VISIBLE_TEXT_EMPTY_DEFAULT = "未识别到稳定画面文字，请人工补充"
_REVIEW_KEYWORDS_LIMIT = 10
_REVIEW_KEYWORDS_MIN_LEN = 2
_REVIEW_KEYWORD_MIN_COUNT = 4
_REVIEW_KEYWORD_NOISE_CHUNKS = {
    "开箱",
    "评测",
    "实测",
    "介绍",
    "对比",
    "上手",
    "内容",
    "产品",
    "视频",
    "主题",
}
_MODEL_FAMILY_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z]{1,10}\d{1,6}[A-Za-z0-9-]{0,12}|[A-Za-z]{2,12})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _hint_candidate_key(field_name: str) -> str:
    return f"{field_name}_candidates"


def _append_hint_candidate(hints: dict[str, Any], field_name: str, value: object) -> None:
    text = str(value or "").strip()
    if not text:
        return
    key = _hint_candidate_key(field_name)
    current = [
        str(item).strip()
        for item in (hints.get(key) or [])
        if str(item).strip()
    ]
    if text not in current:
        current.append(text)
    if current:
        hints[key] = current


def _hint_values(hints: dict[str, Any] | None, field_name: str) -> list[str]:
    candidate = hints if isinstance(hints, dict) else {}
    values: list[str] = []
    direct = str(candidate.get(field_name) or "").strip()
    if direct:
        values.append(direct)
    for item in candidate.get(_hint_candidate_key(field_name)) or []:
        text = str(item).strip()
        if text and text not in values:
            values.append(text)
    return values


def _hint_primary_value(hints: dict[str, Any] | None, field_name: str) -> str:
    values = _hint_values(hints, field_name)
    return values[0] if values else ""


def _workflow_template_name(profile: dict[str, Any] | None) -> str:
    candidate = profile or {}
    workflow_template = normalize_workflow_template_name(str(candidate.get("workflow_template") or "").strip())
    if workflow_template:
        return get_workflow_preset(workflow_template).name
    legacy_preset = str(candidate.get("preset_name") or "").strip()
    if legacy_preset:
        return get_workflow_preset(legacy_preset).name
    return ""


def _content_kind_name(profile: dict[str, Any] | None) -> str:
    candidate = profile or {}
    value = str(candidate.get("content_kind") or "").strip().lower()
    if value:
        return value
    template_name = _workflow_template_name(candidate)
    if template_name:
        return get_workflow_preset(template_name).content_kind
    return "unboxing"


def _normalize_main_content_type(value: str) -> str:
    return normalize_video_type(value)


def _coerce_subject_type_to_supported_main_type(profile: dict[str, Any] | None) -> str:
    candidate = profile or {}
    resolved_subject_type = str(candidate.get("subject_type") or "").strip()
    if not resolved_subject_type:
        return ""
    normalized = _normalize_main_content_type(resolved_subject_type)
    generic_aliases = {
        "tutorial",
        "教程",
        "vlog",
        "commentary",
        "观点",
        "gameplay",
        "游戏",
        "food",
        "探店",
        "unboxing",
        "开箱",
    }
    if normalized and (
        resolved_subject_type.strip().lower() in generic_aliases
        or _is_generic_subject_type(resolved_subject_type)
    ):
        return normalized
    return ""


def _ensure_subject_type_main(profile: dict[str, Any]) -> str:
    normalized = _coerce_subject_type_to_supported_main_type(profile)
    profile["subject_type"] = normalized
    return normalized


def _normalize_query_list(values: list[str]) -> list[str]:
    return _normalize_query_list_public(values)


def _extract_review_keyword_tokens(
    text: str,
    *,
    seed_terms: list[str] | None = None,
) -> list[str]:
    return _extract_review_keyword_tokens_public(text, seed_terms=seed_terms)


def _build_review_keywords(profile: dict[str, Any]) -> list[str]:
    return _build_review_keywords_public(profile)


def _collect_review_keyword_seed_terms(profile_values: dict[str, Any]) -> list[str]:
    return _collect_review_keyword_seed_terms_public(profile_values)


def _coerce_subject_type_for_review_display(value: str) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    if "tutorial" in raw or "教程" in raw:
        return "教程(tutorial)"
    if "vlog" in raw or "生活" in raw or "日常" in raw:
        return "Vlog(vlog)"
    if "commentary" in raw or "观点" in raw:
        return "观点(commentary)"
    if "gameplay" in raw or "游戏" in raw:
        return "游戏(gameplay)"
    if "food" in raw or "探店" in raw:
        return "探店(food)"
    if "unboxing" in raw or "开箱" in raw:
        return "开箱(unboxing)"
    return value.strip()


def _build_review_field_subject(profile: dict[str, Any]) -> str:
    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    model = _clean_line(profile.get("subject_model") or profile.get("model") or "")
    subject_type = _clean_line(profile.get("subject_type") or "")
    theme = _clean_line(profile.get("video_theme") or "")
    if brand and model:
        return f"{brand} {model}".strip()
    if model and subject_type and not _is_generic_subject_type(subject_type):
        return f"{model}{subject_type}"[:24]
    if brand and subject_type and not _is_generic_subject_type(subject_type):
        return f"{brand}{subject_type}"[:24]
    if model:
        return model[:24]
    if brand:
        return brand[:24]
    if subject_type and not _is_generic_subject_type(subject_type):
        return subject_type[:24]
    if theme:
        return theme[:24]
    return "这条视频"


def _collect_review_context_terms(profile: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("subject_model", "subject_type"):
        value = _clean_line(profile.get(key) or "")
        if value:
            candidates.append(value)
    theme = str(profile.get("video_theme") or "").strip()
    if theme:
        candidates.extend(_extract_topic_terms_keywords(theme))
    for query in list(profile.get("search_queries") or [])[:3]:
        candidates.extend(_extract_review_keyword_tokens_public(str(query or "").strip(), seed_terms=[]))

    terms: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = _clean_line(candidate)
        normalized = _normalize_profile_value(term)
        if not term or not normalized or normalized in seen:
            continue
        if term in _REVIEW_KEYWORD_NOISE_CHUNKS:
            continue
        if len(term) > 18:
            continue
        seen.add(normalized)
        terms.append(term)
        if len(terms) >= 3:
            break
    return terms


def _build_contextual_correction_notes(profile: dict[str, Any], *, transcript_excerpt: str) -> str:
    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    model = _clean_line(profile.get("subject_model") or profile.get("model") or "")
    subject_type = _clean_line(profile.get("subject_type") or "")
    focus_terms = _collect_review_context_terms(profile)
    named_terms = [term for term in (brand, model, subject_type) if term and not (term == subject_type and _is_generic_subject_type(term))]
    focus_phrase = "、".join(focus_terms[:2])
    if named_terms and focus_phrase:
        return f"重点核对字幕里的{'、'.join(named_terms[:3])}写法，以及{focus_phrase}相关表述是否与画面和调研证据一致。"
    if named_terms:
        return f"重点核对字幕里的{'、'.join(named_terms[:3])}写法，确认 ASR 术语、版本信息和画面表达一致。"
    if focus_phrase:
        return f"重点复核字幕中的{focus_phrase}相关表述，确认 ASR 术语、版本差异和画面信息一致。"
    if _clean_line(transcript_excerpt):
        return "重点复核完整字幕中的主体名称、术语和版本信息，确认没有 ASR 误听或误写。"
    return "重点复核画面与字幕中的主体名称和关键术语，确认没有识别误差。"


def _build_contextual_supplemental_context(profile: dict[str, Any], *, transcript_excerpt: str) -> str:
    subject = _build_review_field_subject(profile)
    theme = _clean_line(profile.get("video_theme") or "")
    focus_terms = _collect_review_context_terms(profile)
    focus_phrase = "、".join(focus_terms[:2])
    if theme and focus_phrase:
        return f"当前稿件主要围绕{subject if subject != '这条视频' else theme}展开，审核时重点关注{focus_phrase}，并结合完整字幕与调研证据确认使用场景和对比关系。"
    if theme:
        return f"当前稿件主要围绕{theme}展开，建议结合完整字幕与调研证据补充拍摄目标、使用场景和审核关注点。"
    if subject != "这条视频":
        return f"当前稿件以{subject}为主要对象，建议结合完整字幕与调研证据确认拍摄目标、使用场景和需要重点核对的版本差异。"
    if _clean_line(transcript_excerpt):
        return "当前稿件上下文仍需结合完整字幕补充，审核时建议同步确认拍摄目标、对比对象和使用场景。"
    return "当前稿件上下文仍不完整，建议结合画面和调研证据补充拍摄目标、对比对象与使用场景。"


def _ensure_review_fields_not_empty(profile: dict[str, Any], *, source_name: str, transcript_excerpt: str) -> None:
    if not str(profile.get("visible_text") or "").strip():
        fallback = _build_review_field_fallback_visible_text(profile=profile, source_name=source_name, transcript_excerpt=transcript_excerpt)
        profile["visible_text"] = fallback
    if not str(profile.get("correction_notes") or "").strip():
        profile["correction_notes"] = _build_contextual_correction_notes(profile, transcript_excerpt=transcript_excerpt)
    if not str(profile.get("supplemental_context") or "").strip():
        profile["supplemental_context"] = _build_contextual_supplemental_context(profile, transcript_excerpt=transcript_excerpt)


def _normalize_review_payload_keywords(values: Any) -> list[str]:
    return _normalize_query_list([str(item).strip() for item in (values or []) if str(item).strip()])[:_REVIEW_KEYWORDS_LIMIT]


async def _generate_llm_review_page_payload(
    *,
    profile: dict[str, Any],
    source_name: str,
    transcript_excerpt: str,
    transcript_text: str,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    provider = get_reasoning_provider()
    evidence_payload = [dict(item) for item in (evidence or [])[:6] if isinstance(item, dict)]
    content_understanding = dict(profile.get("content_understanding") or {}) if isinstance(profile.get("content_understanding"), dict) else {}
    semantic_facts = dict(content_understanding.get("semantic_facts") or {}) if isinstance(content_understanding.get("semantic_facts"), dict) else {}
    review_focus_payload = {
        "subject_brand": str(profile.get("subject_brand") or "").strip(),
        "subject_model": str(profile.get("subject_model") or "").strip(),
        "subject_type": str(profile.get("subject_type") or "").strip(),
        "video_theme": str(profile.get("video_theme") or "").strip(),
        "visible_text": str(profile.get("visible_text") or "").strip(),
        "search_queries": [str(item).strip() for item in (profile.get("search_queries") or []) if str(item).strip()][:6],
    }
    prompt = (
        "你在生成短视频审核页面的最终展示内容。"
        "必须以完整 ASR/字幕和调研证据为主，输出给人工审核直接看的结构化结果。"
        "不要输出解释，只输出严格 JSON。"
        "字段必须包括：video_type, video_theme, hook_line, summary, engagement_question, correction_notes, supplemental_context, keywords, search_queries。"
        "要求："
        "0. video_type 只能输出 tutorial / vlog / commentary / gameplay / food / unboxing 之一；"
        "1. 所有字段都基于完整字幕和调研证据，不要沿用泛化默认文案；"
        "2. keywords 必须是 4-10 个高价值短词，优先品牌、型号、主体类型、联名关系、核心卖点、版本差异；"
        "3. keywords 不能硬切中文碎片，不能输出“开箱”“评测”“视频”“内容”这种单独噪声词，除非它是更长短语的一部分；"
        "4. search_queries 保留 1-6 条可用于检索核验的自然短语；"
        "5. correction_notes 要给审核者明确校对关注点，基于 ASR 可能误听、术语、型号、字幕一致性来写；"
        "6. supplemental_context 要补充这条视频的拍摄目标、对比关系、使用场景或审核关注背景；"
        "7. 如果证据不足，宁可保守简洁，也不要编造。"
        f"\n当前识别出的主体信息：{json.dumps(review_focus_payload, ensure_ascii=False)}"
        f"\n当前内容理解：{json.dumps(content_understanding, ensure_ascii=False)}"
        f"\n语义事实：{json.dumps(semantic_facts, ensure_ascii=False)}"
        f"\n源文件名：{source_name}"
        f"\n完整字幕：{transcript_text or transcript_excerpt or '无'}"
    )
    if transcript_excerpt and transcript_text.strip() != transcript_excerpt.strip():
        prompt += f"\n字幕节选：{transcript_excerpt}"
    if evidence_payload:
        prompt += f"\n调研证据：{json.dumps(evidence_payload, ensure_ascii=False)}"
    prompt += (
        '\n输出 JSON：{"video_type":"","video_theme":"","hook_line":"","summary":"","engagement_question":"",'
        '"correction_notes":"","supplemental_context":"","keywords":[],"search_queries":[]}'
    )

    with track_usage_operation("content_profile.review_page_payload"):
        response = await provider.complete(
            [
                Message(role="system", content="你是严谨的中文短视频审核页内容生成器，只输出严格 JSON。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=900,
            json_mode=True,
        )
    payload = response.as_json()
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    video_type = normalize_video_type(str(payload.get("video_type") or "").strip())
    if video_type:
        normalized["video_type"] = video_type
    for key in (
        "video_theme",
        "hook_line",
        "summary",
        "engagement_question",
        "correction_notes",
        "supplemental_context",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            normalized[key] = value
    keywords = _normalize_review_payload_keywords(payload.get("keywords"))
    if keywords:
        normalized["keywords"] = keywords
    search_queries = _normalize_query_list([str(item).strip() for item in (payload.get("search_queries") or []) if str(item).strip()])[:6]
    if search_queries:
        normalized["search_queries"] = search_queries
    return normalized


def _build_review_field_fallback_visible_text(
    *,
    profile: dict[str, Any],
    source_name: str,
    transcript_excerpt: str,
) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    candidates = [
        _coerce_subject_type_for_review_display(str(profile.get("subject_type") or "")),
        brand,
        model,
    ]
    if not (brand or model):
        return ""
    compact = " ".join(part for part in candidates if part)
    return compact[:80] if compact else _VISIBLE_TEXT_EMPTY_DEFAULT


def _fallback_search_queries_for_profile(profile: dict[str, Any], source_name: str) -> list[str]:
    return _fallback_search_queries_for_profile_public(profile, source_name)


def _ensure_search_queries(
    profile: dict[str, Any],
    source_name: str,
    *,
    transcript_excerpt: str,
    limit: int = 6,
) -> list[str]:
    existing = _normalize_query_list([str(item).strip() for item in (profile.get("search_queries") or [])])
    if not existing:
        existing = _normalize_query_list(
            _build_search_queries(profile, source_name, transcript_excerpt=transcript_excerpt)
        )
    if not existing:
        existing = _normalize_query_list(_fallback_search_queries_for_profile(profile, source_name))
    if not existing:
        existing = []
    if limit and len(existing) > limit:
        existing = existing[:limit]
    profile["search_queries"] = existing
    return existing


def _infer_subject_domain_from_content(
    *,
    profile: dict[str, Any] | None,
    transcript_excerpt: str,
    source_name: str,
) -> str:
    return str(select_primary_subject_domain(detect_glossary_domains(
        workflow_template=None,
        content_profile=profile,
        subtitle_items=[{"text_final": transcript_excerpt}] if str(transcript_excerpt or "").strip() else None,
        source_name=source_name,
    )) or "")


def _normalize_seeded_profile_for_cache(profile: dict[str, Any] | None) -> dict[str, Any]:
    seeded = profile or {}
    if not seeded:
        return {}
    cover_title = seeded.get("cover_title") if isinstance(seeded.get("cover_title"), dict) else {}
    evidence = [
        {
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": str(item.get("snippet") or "").strip(),
        }
        for item in (seeded.get("evidence") or [])
        if isinstance(item, dict) and (item.get("url") or item.get("title") or item.get("snippet"))
    ]
    visual_hints = seeded.get("visual_hints") if isinstance(seeded.get("visual_hints"), dict) else {}
    visual_cluster_hints = seeded.get("visual_cluster_hints") if isinstance(seeded.get("visual_cluster_hints"), dict) else visual_hints
    source_context = _normalize_source_context_payload(seeded.get("source_context"))
    normalized = {
        "subject_brand": str(seeded.get("subject_brand") or "").strip(),
        "subject_brand_cn": str(seeded.get("subject_brand_cn") or "").strip(),
        "subject_brand_bilingual": str(seeded.get("subject_brand_bilingual") or "").strip(),
        "subject_model": str(seeded.get("subject_model") or "").strip(),
        "subject_type": str(seeded.get("subject_type") or "").strip(),
        "subject_type_candidates": [str(item).strip() for item in (seeded.get("subject_type_candidates") or []) if str(item).strip()],
        "content_kind": str(seeded.get("content_kind") or "").strip(),
        "subject_domain": str(seeded.get("subject_domain") or "").strip(),
        "video_theme": str(seeded.get("video_theme") or "").strip(),
        "video_theme_candidates": [str(item).strip() for item in (seeded.get("video_theme_candidates") or []) if str(item).strip()],
        "workflow_template": _workflow_template_name(seeded),
        "hook_line": str(seeded.get("hook_line") or "").strip(),
        "visible_text": str(seeded.get("visible_text") or "").strip(),
        "summary": str(seeded.get("summary") or "").strip(),
        "engagement_question": str(seeded.get("engagement_question") or "").strip(),
        "copy_style": str(seeded.get("copy_style") or "").strip(),
        "search_queries": [str(item).strip() for item in (seeded.get("search_queries") or []) if str(item).strip()],
        "cover_title": {
            "top": str(cover_title.get("top") or "").strip(),
            "main": str(cover_title.get("main") or "").strip(),
            "bottom": str(cover_title.get("bottom") or "").strip(),
        },
        "evidence": evidence,
        "visual_hints": {
            "subject_type": str(visual_hints.get("subject_type") or "").strip(),
            "subject_type_candidates": [str(item).strip() for item in (visual_hints.get("subject_type_candidates") or []) if str(item).strip()],
            "subject_brand": str(visual_hints.get("subject_brand") or "").strip(),
            "subject_model": str(visual_hints.get("subject_model") or "").strip(),
            "visible_text": str(visual_hints.get("visible_text") or "").strip(),
        },
        "visual_cluster_hints": {
            "subject_type": str(visual_cluster_hints.get("subject_type") or "").strip(),
            "subject_type_candidates": [str(item).strip() for item in (visual_cluster_hints.get("subject_type_candidates") or []) if str(item).strip()],
            "subject_brand": str(visual_cluster_hints.get("subject_brand") or "").strip(),
            "subject_model": str(visual_cluster_hints.get("subject_model") or "").strip(),
            "visible_text": str(visual_cluster_hints.get("visible_text") or "").strip(),
        },
        "source_context": source_context,
    }
    if not any(
        (
            normalized["subject_brand"],
            normalized["subject_model"],
            normalized["subject_type"],
            normalized["subject_type_candidates"],
            normalized["content_kind"],
            normalized["subject_domain"],
            normalized["video_theme"],
            normalized["video_theme_candidates"],
            normalized["workflow_template"],
            normalized["hook_line"],
            normalized["visible_text"],
            normalized["summary"],
            normalized["engagement_question"],
            normalized["copy_style"],
            normalized["search_queries"],
            normalized["evidence"],
            any(normalized["cover_title"].values()),
            any(normalized["visual_hints"].values()),
            any(normalized["visual_cluster_hints"].values()),
            normalized["source_context"],
        )
    ):
        return {}
    return normalized


def _normalize_source_context_payload(value: Any) -> dict[str, Any]:
    payload = dict(value) if isinstance(value, dict) else {}
    video_description = str(payload.get("video_description") or "").strip()
    if len(video_description) > 4000:
        video_description = video_description[:4000]
    merged_source_names = [
        str(item).strip()
        for item in (payload.get("merged_source_names") or payload.get("related_source_names") or [])
        if str(item).strip()
    ]
    resolved_feedback = dict(payload.get("resolved_feedback") or {}) if isinstance(payload.get("resolved_feedback"), dict) else {}
    related_profiles: list[dict[str, Any]] = []
    for item in payload.get("related_profiles") or payload.get("adjacent_profiles") or []:
        profile = dict(item) if isinstance(item, dict) else {}
        source_name = str(profile.get("source_name") or "").strip()
        subject_brand = str(profile.get("subject_brand") or "").strip()
        subject_model = str(profile.get("subject_model") or "").strip()
        subject_type = str(profile.get("subject_type") or "").strip()
        video_theme = str(profile.get("video_theme") or "").strip()
        summary = str(profile.get("summary") or "").strip()
        search_queries = [str(query).strip() for query in (profile.get("search_queries") or []) if str(query).strip()]
        review_mode = str(profile.get("review_mode") or "").strip().lower()
        manual_confirmed = bool(profile.get("manual_confirmed")) or review_mode == "manual_confirmed"
        try:
            score = round(float(profile.get("score") or 0.0), 3)
        except (TypeError, ValueError):
            score = 0.0
        normalized_profile = {
            "source_name": source_name,
            "subject_brand": subject_brand,
            "subject_model": subject_model,
            "subject_type": subject_type,
            "video_theme": video_theme,
            "summary": summary,
            "search_queries": search_queries[:6],
            "score": max(0.0, min(1.0, score)),
            "review_mode": review_mode,
            "manual_confirmed": manual_confirmed,
        }
        if any(
            (
                normalized_profile["source_name"],
                normalized_profile["subject_brand"],
                normalized_profile["subject_model"],
                normalized_profile["subject_type"],
                normalized_profile["video_theme"],
                normalized_profile["summary"],
                normalized_profile["search_queries"],
            )
        ):
            related_profiles.append(normalized_profile)
    normalized: dict[str, Any] = {}
    if video_description:
        normalized["video_description"] = video_description
    if merged_source_names:
        normalized["merged_source_names"] = merged_source_names[:12]
    if resolved_feedback:
        normalized["resolved_feedback"] = resolved_feedback
    if related_profiles:
        normalized["related_profiles"] = related_profiles[:4]
    return normalized


def _normalize_source_context_filename_hint(value: Any) -> str:
    stem = Path(str(value or "").strip()).stem
    if not stem:
        return ""
    stem = re.sub(r"^(?:IMG|VID|DSC|PXL|CIMG|MVIMG)[-_]?\d+(?:[_-]\d+)*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^\d{8}(?:[-_]\d{6,})?", "", stem)
    stem = re.sub(r"^[\s._-]+", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" _-")
    if not _is_informative_source_hint(stem):
        return ""
    return stem


def _source_context_filename_entries(source_context: dict[str, Any] | None) -> list[str]:
    payload = _normalize_source_context_payload(source_context)
    entries: list[str] = []
    seen: set[str] = set()

    def append(value: Any) -> None:
        text = _normalize_source_context_filename_hint(value)
        normalized = _normalize_profile_value(text)
        if not text or not normalized or normalized in seen:
            return
        seen.add(normalized)
        entries.append(text)

    append(payload.get("source_name"))
    for item in payload.get("merged_source_names") or []:
        append(item)
    return entries[:12]


def _source_context_description_entries(source_context: dict[str, Any] | None) -> list[str]:
    payload = _normalize_source_context_payload(source_context)
    video_description = str(payload.get("video_description") or "").strip()
    if not video_description:
        return []
    text = re.sub(r"^任务说明依据文件名[:：]\s*", "", video_description)
    for marker in ("固定要求：", "审核依据："):
        if marker in text:
            text = text.split(marker, 1)[0].strip("；;，,。 ")
    text = re.sub(r"\s+", " ", text).strip()
    return [text] if _is_informative_source_hint(text) else []


def _merge_source_context_seed_hints(
    target: dict[str, Any],
    seed: dict[str, Any] | None,
) -> None:
    candidate = seed if isinstance(seed, dict) else {}
    for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        for value in _hint_values(candidate, field_name):
            _append_hint_candidate(target, field_name, value)
        if not str(target.get(field_name) or "").strip():
            primary = _hint_primary_value(candidate, field_name)
            if primary:
                target[field_name] = primary
    search_queries = [
        str(item).strip()
        for item in (candidate.get("search_queries") or [])
        if str(item).strip()
    ]
    if search_queries:
        existing = [
            str(item).strip()
            for item in (target.get("search_queries") or [])
            if str(item).strip()
        ]
        normalized_existing = {_normalize_profile_value(item) for item in existing}
        for query in search_queries:
            normalized = _normalize_profile_value(query)
            if normalized and normalized not in normalized_existing:
                existing.append(query)
                normalized_existing.add(normalized)
        if existing:
            target["search_queries"] = existing[:8]


def _build_source_context_derived_hints(source_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = _normalize_source_context_payload(source_context)
    if not payload:
        return {}
    derived: dict[str, Any] = {}
    entries = _source_context_filename_entries(payload)
    if entries:
        derived["filename_entries"] = entries
        derived["related_source_names"] = list(entries[:3])
        for entry in entries:
            _merge_source_context_seed_hints(derived, _seed_profile_from_text(entry))
    for entry in _source_context_description_entries(payload):
        _merge_source_context_seed_hints(derived, _seed_profile_from_text(entry))
    return derived


def _source_context_has_editorial_brief(source_context: dict[str, Any] | None) -> bool:
    payload = _normalize_source_context_payload(source_context)
    if str(payload.get("video_description") or "").strip():
        return True
    return bool(_source_context_filename_entries(payload))


def _source_name_has_editorial_brief(source_name: str | None) -> bool:
    return bool(_normalize_source_context_filename_hint(source_name))


def _source_context_supports_identity(
    source_context: dict[str, Any] | None,
    *,
    brand: str = "",
    model: str = "",
) -> bool:
    derived = _build_source_context_derived_hints(source_context)
    if not derived:
        return False
    brand_norm = _normalize_profile_value(brand)
    model_norm = _normalize_profile_value(model)
    candidate_brand_norms = {_normalize_profile_value(item) for item in _hint_values(derived, "subject_brand")}
    candidate_model_norms = {_normalize_profile_value(item) for item in _hint_values(derived, "subject_model")}
    if model_norm:
        if model_norm not in candidate_model_norms:
            return False
        if not brand_norm:
            return True
        if brand_norm in candidate_brand_norms:
            return True
        mapped_brand = _normalize_profile_value(_mapped_brand_for_model(model))
        return bool(mapped_brand and mapped_brand == brand_norm)
    if brand_norm and brand_norm in candidate_brand_norms:
        return True
    return False


def _source_name_supports_identity(
    source_name: str | None,
    *,
    brand: str = "",
    model: str = "",
) -> bool:
    source_hint = _normalize_source_context_filename_hint(source_name)
    if not source_hint:
        return False
    normalized_hint = _normalize_profile_value(source_hint)
    brand_norm = _normalize_profile_value(brand)
    model_norm = _normalize_profile_value(model)
    if model_norm and model_norm not in normalized_hint:
        return False
    if brand_norm and brand_norm in normalized_hint:
        return True
    mapped_brand = _normalize_profile_value(_mapped_brand_for_model(model))
    if brand_norm and mapped_brand and mapped_brand == brand_norm:
        return True
    return bool(model_norm or brand_norm)


def _is_generic_source_brand_prefix(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return True
    if candidate in _SOURCE_BRAND_PREFIX_STOPWORDS:
        return True
    if any(candidate.startswith(prefix) for prefix in _SOURCE_BRAND_PREFIX_STOPWORDS):
        return True
    return False


def _extract_source_brand_prefix_candidates(source_name: str) -> list[str]:
    stem = _normalize_source_context_filename_hint(source_name)
    if not stem:
        return []
    candidates: list[str] = []
    seen: set[str] = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,24}", stem):
        prefix_candidates = [chunk] if len(chunk) <= 4 else [chunk[:4], chunk[:3], chunk[:2]]
        for candidate in prefix_candidates:
            if not candidate or candidate in seen or _is_generic_source_brand_prefix(candidate):
                continue
            seen.add(candidate)
            candidates.append(candidate)
    return candidates


def _build_source_visual_overlap_hints(*, source_name: str, visible_text: str) -> dict[str, Any]:
    source_candidates = _extract_source_brand_prefix_candidates(source_name)
    visible = str(visible_text or "").strip()
    normalized_visible = _normalize_profile_value(visible)
    if not source_candidates or not normalized_visible:
        return {}
    matched = [
        candidate
        for candidate in source_candidates
        if _normalize_profile_value(candidate) in normalized_visible
    ]
    if not matched:
        return {}
    return {
        "subject_brand": max(matched, key=len),
        "visible_text": visible,
    }


def _is_filename_dependent_review_reason(reason: str) -> bool:
    text = str(reason or "").strip()
    if not text:
        return False
    tokens = (
        "文件名hint推断",
        "缺乏视觉证据",
        "建议补充原视频画面帧截图",
        "建议补充完整字幕转写",
        "semantic_facts全字段为空",
        "依赖文件名字段",
    )
    return any(token in text for token in tokens)


def build_content_profile_cache_fingerprint(
    *,
    source_name: str,
    source_file_hash: str | None,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    transcript_excerpt: str,
    subtitle_digest: str | None = None,
    transcript_digest: str | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    include_research: bool,
    copy_style: str | None = None,
    seeded_profile: dict[str, Any] | None = None,
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    normalized_glossary = [
        {
            "correct_form": str(item.get("correct_form") or "").strip(),
            "wrong_forms": [str(value).strip() for value in (item.get("wrong_forms") or []) if str(value).strip()],
            "category": str(item.get("category") or "").strip(),
            "context_hint": str(item.get("context_hint") or "").strip(),
        }
        for item in (glossary_terms or [])
        if isinstance(item, dict)
    ]
    normalized_memory = user_memory if isinstance(user_memory, dict) else {}
    normalized_seeded_profile = _normalize_seeded_profile_for_cache(seeded_profile)
    return {
        "version": (
            _CONTENT_PROFILE_ENRICH_CACHE_VERSION
            if normalized_seeded_profile
            else _CONTENT_PROFILE_INFER_CACHE_VERSION
        ),
        "source_name": str(source_name or "").strip(),
        "source_file_hash": str(source_file_hash or "").strip(),
        "workflow_template": str(workflow_template or "").strip(),
        "transcript_excerpt_sha256": digest_payload(str(transcript_excerpt or "").strip()),
        "subtitle_digest": str(subtitle_digest or "").strip(),
        "transcript_digest": str(transcript_digest or "").strip(),
        "glossary_terms_sha256": digest_payload(normalized_glossary),
        "glossary_term_count": len(normalized_glossary),
        "user_memory_sha256": digest_payload(normalized_memory),
        "include_research": bool(include_research),
        "copy_style": str(copy_style or "").strip(),
        "seeded_profile_sha256": digest_payload(normalized_seeded_profile) if normalized_seeded_profile else "",
        "source_context_sha256": digest_payload(_normalize_source_context_payload(source_context)),
    }


def _excerpt_item_text(item: dict[str, Any]) -> str:
    return str(
        item.get("text_final")
        or item.get("text_norm")
        or item.get("text_raw")
        or item.get("text")
        or item.get("raw_text")
        or ""
    ).strip()


def _excerpt_item_start(item: dict[str, Any]) -> float:
    return float(item.get("start_time", item.get("start", 0.0)) or 0.0)


def _excerpt_item_end(item: dict[str, Any]) -> float:
    return float(item.get("end_time", item.get("end", 0.0)) or 0.0)


def build_transcript_excerpt(subtitle_items: list[dict], *, max_items: int = 36, max_chars: int = 1400) -> str:
    selected = _select_excerpt_items(subtitle_items, max_items=max_items)
    lines: list[str] = []
    total = 0
    for item in selected:
        text = _excerpt_item_text(item)
        if not text:
            continue
        line = f"[{_excerpt_item_start(item):.1f}-{_excerpt_item_end(item):.1f}] {text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


def build_reviewed_transcript_excerpt(
    subtitle_items: list[dict[str, Any]],
    accepted_corrections: list[dict[str, Any]] | None = None,
    *,
    max_items: int = 36,
    max_chars: int = 1400,
) -> str:
    corrections_by_index: dict[int, list[dict[str, Any]]] = {}
    for item in accepted_corrections or []:
        try:
            index = int(item.get("item_index"))
        except (TypeError, ValueError):
            continue
        corrections_by_index.setdefault(index, []).append(item)

    reviewed_items: list[dict[str, Any]] = []
    for subtitle in subtitle_items:
        item = dict(subtitle)
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
        for correction in corrections_by_index.get(int(item.get("index", -1)), []):
            original = str(correction.get("original") or "").strip()
            accepted = str(correction.get("accepted") or "").strip()
            if not original or not accepted or original == accepted:
                continue
            if original in text:
                text = text.replace(original, accepted)
        item["text_final"] = text
        reviewed_items.append(item)
    return build_transcript_excerpt(reviewed_items, max_items=max_items, max_chars=max_chars)


def apply_glossary_terms(text: str, glossary_terms: list[dict[str, Any]]) -> str:
    result = text
    for term in glossary_terms:
        correct_form = (term.get("correct_form") or "").strip()
        if not correct_form:
            continue
        for wrong_form in term.get("wrong_forms") or []:
            if wrong_form and wrong_form != correct_form:
                result = re.sub(re.escape(wrong_form), correct_form, result, flags=re.IGNORECASE)
    return result


def _build_subtitle_signal_blob(subtitle_items: list[dict[str, Any]] | None, *, max_items: int = 96) -> str:
    chunks: list[str] = []
    for item in (subtitle_items or [])[:max_items]:
        text = _clean_line(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
        if text:
            chunks.append(text)
    return "\n".join(chunks)


def _has_ingestible_product_subject_conflict(
    *,
    profile: dict[str, Any],
    subtitle_items: list[dict[str, Any]] | None = None,
    transcript_excerpt: str = "",
) -> bool:
    subject_blob = str(profile.get("subject_type") or "").lower()
    narrative_blob = " ".join(
        [
            str(profile.get("summary") or ""),
            str(profile.get("video_theme") or ""),
            json.dumps(profile.get("cover_title") or {}, ensure_ascii=False),
        ]
    ).lower()
    subtitle_blob = f"{transcript_excerpt}\n{_build_subtitle_signal_blob(subtitle_items)}".lower()

    ingestible_hits = sum(1 for token in _INGESTIBLE_PRODUCT_SIGNALS if token in subtitle_blob)
    subject_gear_hits = sum(1 for token in _GEAR_STYLE_SIGNALS if token in subject_blob)
    narrative_gear_hits = sum(1 for token in _GEAR_STYLE_SIGNALS if token in narrative_blob)

    return ingestible_hits >= 2 and (
        subject_gear_hits >= 1
        or narrative_gear_hits >= 1
    )


def _has_ingestible_product_context(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    hits = sum(1 for token in _INGESTIBLE_PRODUCT_SIGNALS if token in lowered)
    if hits >= 2:
        return True
    return "kisspod" in lowered and hits >= 1


def _looks_like_gear_subject_text(text: str) -> bool:
    lowered = str(text or "").lower()
    if not lowered:
        return False
    return any(token in lowered for token in _GEAR_STYLE_SIGNALS)


def _has_arc_spoken_alias(text: str) -> bool:
    transcript = str(text or "")
    upper = transcript.upper()
    if re.search(r"(?<![A-Z0-9])ARC(?![A-Z0-9])", upper):
        return True
    has_leatherman_context = bool(_BRAND_ALIAS_PATTERNS[0][1].search(transcript)) or any(
        token in transcript for token in ("工具钳", "多功能工具钳", "钳头", "单手开合", "批头", "钢丝钳")
    )
    if not has_leatherman_context:
        return False
    return bool(re.search(r"(?<![A-Z0-9])A(?:[\s._/-]*(?:R|S))?[\s._/-]*C(?![A-Z0-9])", upper))


def _apply_ingestible_subject_conflict_guard(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None = None,
    transcript_excerpt: str = "",
    glossary_terms: list[dict[str, Any]] | None = None,
    source_name: str,
) -> dict[str, Any]:
    guarded = dict(profile or {})
    if not _has_ingestible_product_subject_conflict(
        profile=guarded,
        subtitle_items=subtitle_items,
        transcript_excerpt=transcript_excerpt,
    ):
        return guarded

    confirmed_fields = _extract_confirmed_profile_fields(guarded)
    transcript_signal = str(transcript_excerpt or "").strip()
    if not transcript_signal and subtitle_items:
        transcript_signal = build_transcript_excerpt(list(subtitle_items), max_items=24, max_chars=900)
    seeded = _seed_profile_from_text(
        transcript_signal,
        glossary_terms=glossary_terms,
        subject_domain="food",
    )
    subject_type = _hint_primary_value(seeded, "subject_type") or _INGESTIBLE_DEFAULT_SUBJECT_TYPE

    if "subject_brand" not in confirmed_fields and str(seeded.get("subject_brand") or "").strip():
        guarded["subject_brand"] = str(seeded.get("subject_brand") or "").strip()
    if "subject_model" not in confirmed_fields and str(seeded.get("subject_model") or "").strip():
        guarded["subject_model"] = str(seeded.get("subject_model") or "").strip()
    if "subject_type" not in confirmed_fields:
        current_subject_type = str(guarded.get("subject_type") or "").strip()
        if not current_subject_type or _looks_like_gear_subject_text(current_subject_type):
            guarded["subject_type"] = subject_type
    if not str(guarded.get("subject_domain") or "").strip():
        guarded["subject_domain"] = "food"

    for key in ("video_theme", "summary", "hook_line", "engagement_question"):
        if key not in confirmed_fields:
            guarded[key] = ""
    if "visible_text" not in confirmed_fields and _looks_like_gear_subject_text(str(guarded.get("visible_text") or "")):
        guarded["visible_text"] = ""
    if "search_queries" not in confirmed_fields:
        guarded["search_queries"] = []
    guarded["cover_title"] = {}
    guarded["evidence"] = []

    seeded_theme = _hint_primary_value(seeded, "video_theme")
    if "video_theme" not in confirmed_fields and seeded_theme:
        guarded["video_theme"] = seeded_theme
    if "visible_text" not in confirmed_fields and not str(guarded.get("visible_text") or "").strip():
        visible_text = " ".join(
            part for part in (
                str(guarded.get("subject_brand") or "").strip(),
                str(guarded.get("subject_model") or "").strip(),
            )
            if part
        ).strip()
        if visible_text:
            guarded["visible_text"] = visible_text
    if "summary" not in confirmed_fields:
        guarded["summary"] = _build_profile_summary(guarded)

    _ensure_search_queries(guarded, source_name, transcript_excerpt=transcript_signal)
    preset = select_workflow_template(
        workflow_template=guarded.get("workflow_template"),
        content_kind=_content_kind_name(guarded),
        subject_domain=str(guarded.get("subject_domain") or ""),
        subject_model=str(guarded.get("subject_model") or ""),
        subject_type=str(guarded.get("subject_type") or ""),
        transcript_hint=transcript_signal,
    )
    if "engagement_question" not in confirmed_fields:
        guarded["engagement_question"] = _build_fallback_engagement_question(guarded, preset)
    guarded["cover_title"] = build_cover_title(guarded, preset)
    return guarded


def build_cover_title(profile: dict[str, Any], preset: WorkflowPreset) -> dict[str, str]:
    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    model = _clean_line(profile.get("subject_model") or profile.get("model") or "")
    subject_type = _clean_line(profile.get("subject_type") or "")
    raw_theme = str(profile.get("video_theme") or "").strip()
    theme = _clean_line(raw_theme)
    hook = _clean_line(profile.get("hook_line") or "")
    visible_text = str(profile.get("visible_text") or "").strip()
    transcript_excerpt = str(profile.get("transcript_excerpt") or "").strip()
    copy_style = str(profile.get("copy_style") or "attention_grabbing").strip() or "attention_grabbing"
    display_subject_type = _cover_subject_type_label(subject_type)
    cover_top_brand = _select_cover_brand_display(
        profile,
        visible_text=visible_text,
        max_length=14,
        prefer_bilingual=True,
    )
    cover_main_brand = _select_cover_brand_display(
        profile,
        visible_text=visible_text,
        max_length=max(0, 18 - len(display_subject_type)) if display_subject_type else 18,
        prefer_bilingual=False,
    )
    anchor = _extract_cover_entity_anchor(
        brand=brand,
        model=model,
        subject_type=subject_type,
        theme=raw_theme,
        visible_text=visible_text,
        brand_top_label=cover_top_brand,
        brand_main_label=cover_main_brand,
    )

    top = _pick_cover_top(
        brand=brand,
        brand_label=cover_top_brand,
        subject_type=subject_type,
        visible_text=visible_text,
        preset=preset,
        anchor=anchor,
    )
    main = _pick_cover_main(
        brand=brand,
        brand_label=cover_main_brand,
        model=model,
        subject_type=subject_type,
        theme=theme,
        visible_text=visible_text,
        preset=preset,
        anchor=anchor,
    )

    hook = _build_cover_hook(
        hook=hook,
        brand=brand,
        model=model,
        subject_type=subject_type,
        theme=theme,
        transcript_excerpt=transcript_excerpt,
        copy_style=copy_style,
        preset=preset,
    )

    title = {
        "top": top[:14],
        "main": main[:18],
        "bottom": hook[:18],
    }
    visible_brand_hint = _compact_brand_name(brand, visible_text=visible_text)
    return _dedupe_cover_title_lines(
        title,
        preserve_top=bool(
            brand
            or (anchor or {}).get("brand")
            or _is_brand_like_cover_label(visible_brand_hint)
        ),
    )


def assess_content_profile_automation(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    source_name: str = "",
    auto_confirm_enabled: bool = True,
    threshold: float = 0.72,
) -> dict[str, Any]:
    normalized_threshold = max(0.0, min(1.0, float(threshold)))
    subtitle_items = subtitle_items or []
    content_understanding = profile.get("content_understanding")
    if not isinstance(content_understanding, dict):
        content_understanding = {}
    transcript_excerpt = str(profile.get("transcript_excerpt") or "").strip()
    if not transcript_excerpt and subtitle_items:
        transcript_excerpt = build_transcript_excerpt(subtitle_items, max_items=24, max_chars=900)

    subtitle_count = sum(
        1
        for item in subtitle_items
        if _clean_line(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
    )
    source_context = _normalize_source_context_payload((profile or {}).get("source_context"))
    has_editorial_source_context = _source_context_has_editorial_brief(source_context)
    resolved_source_name = str(source_name or profile.get("source_name") or "").strip()
    has_editorial_source_name = _source_name_has_editorial_brief(resolved_source_name)
    has_editorial_review_basis = has_editorial_source_context or has_editorial_source_name
    preset_name = _workflow_template_name(profile)
    product_like_presets = {"unboxing_standard", "edc_tactical"}

    score = 0.0
    reasons: list[str] = []
    review_reasons: list[str] = []
    blocking_reasons: list[str] = []
    identity_review = (
        profile.get("identity_review")
        if isinstance(profile.get("identity_review"), dict)
        else _assess_identity_review_requirement(
            profile,
            subtitle_items=subtitle_items,
            user_memory=user_memory,
            glossary_terms=glossary_terms,
            source_name=source_name,
        )
    )

    subject_type = str(profile.get("subject_type") or "").strip()
    if subject_type and not _is_generic_subject_type(subject_type):
        score += 0.18
        reasons.append("主体类型明确")
    else:
        review_reasons.append("主体类型仍然偏泛化")

    video_theme = str(profile.get("video_theme") or "").strip()
    if _is_specific_video_theme(video_theme, preset_name=preset_name):
        score += 0.14
        reasons.append("视频主题有足够区分度")
    else:
        review_reasons.append("视频主题还不够具体")

    summary = str(profile.get("summary") or "").strip()
    if summary and not _is_generic_profile_summary(summary):
        score += 0.16
        reasons.append("摘要可直接用于后续步骤")
    else:
        review_reasons.append("摘要仍像默认模板")

    cover_title = profile.get("cover_title")
    if isinstance(cover_title, dict) and _cover_title_is_usable(cover_title):
        score += 0.12
        reasons.append("封面标题可用")
    else:
        review_reasons.append("封面标题还不够稳定")

    engagement_question = str(profile.get("engagement_question") or "").strip()
    if engagement_question and not _is_generic_engagement_question(engagement_question):
        score += 0.08
        reasons.append("互动问题贴合内容")
    else:
        review_reasons.append("互动问题偏泛化")

    search_queries = []
    seen_queries: set[str] = set()
    for item in profile.get("search_queries") or []:
        value = str(item).strip()
        normalized = _normalize_profile_value(value)
        if value and normalized and normalized not in seen_queries:
            seen_queries.add(normalized)
            search_queries.append(value)
    if len(search_queries) >= 2:
        score += 0.12
        reasons.append("搜索校验关键词充足")
    elif len(search_queries) == 1:
        score += 0.06
        review_reasons.append("搜索校验关键词偏少")
    else:
        review_reasons.append("缺少搜索校验关键词")

    evidence = profile.get("evidence") or []
    if isinstance(evidence, list) and evidence:
        score += 0.08
        reasons.append("已有外部证据用于交叉校验")
    elif has_editorial_review_basis:
        score += 0.06
        reasons.append("已提供任务说明作为审核依据")
    else:
        review_reasons.append("缺少外部证据")

    transcript_length = len(_clean_line(transcript_excerpt))
    if subtitle_count >= 6 or transcript_length >= 120:
        score += 0.12
        reasons.append("字幕上下文足够")
    elif subtitle_count >= 3 or transcript_length >= 60:
        score += 0.06
        review_reasons.append("字幕上下文偏少")
    else:
        review_reasons.append("字幕上下文不足")

    if _has_ingestible_product_subject_conflict(
        profile=profile,
        subtitle_items=subtitle_items,
        transcript_excerpt=transcript_excerpt,
    ):
        blocking_reasons.append("字幕显示为含片/益生菌等入口产品，但当前摘要主体仍落在装备/工具类")

    subject_brand = str(profile.get("subject_brand") or "").strip()
    subject_model = str(profile.get("subject_model") or "").strip()
    has_verifiable_subject = bool(subject_brand or subject_model)
    has_complete_subject_identity = bool(subject_brand and subject_model)
    mapped_brand = _mapped_brand_for_model(subject_model)
    if has_verifiable_subject:
        score += 0.10 if preset_name in product_like_presets else 0.06
        reasons.append("识别出可验证主体")
    if (
        preset_name in product_like_presets
        and subject_brand
        and subject_model
        and mapped_brand
        and _normalize_profile_value(subject_brand) != _normalize_profile_value(mapped_brand)
    ):
        blocking_reasons.append("开箱类视频主体品牌与型号冲突")
    elif preset_name in product_like_presets and not has_verifiable_subject:
        blocking_reasons.append("开箱类视频未识别出可验证主体")
    elif preset_name in product_like_presets and not has_complete_subject_identity:
        review_reasons.append("开箱类视频主体身份信息仍不完整")
    elif has_verifiable_subject and not has_complete_subject_identity:
        review_reasons.append("主体身份信息不完整")

    if bool(identity_review.get("required")):
        blocking_reasons.append(str(identity_review.get("reason") or "开箱类视频主体身份待人工确认"))
        if bool(identity_review.get("conservative_summary")):
            review_reasons.append("首次品牌/型号证据不足，已退化为保守摘要")

    llm_review_reasons = [
        str(item).strip()
        for item in content_understanding.get("review_reasons") or []
        if str(item).strip()
    ]
    if bool(content_understanding.get("needs_review")):
        if llm_review_reasons:
            if has_editorial_review_basis:
                blocking_reasons.extend(
                    reason for reason in llm_review_reasons if not _is_filename_dependent_review_reason(reason)
                )
                for reason in llm_review_reasons:
                    if _is_filename_dependent_review_reason(reason) and reason not in review_reasons:
                        review_reasons.append(reason)
            else:
                blocking_reasons.extend(llm_review_reasons)
        else:
            blocking_reasons.append("LLM 内容理解结果要求人工复核")
    else:
        review_reasons.extend(llm_review_reasons)

    score = round(min(score, 1.0), 3)
    review_reasons = list(dict.fromkeys(review_reasons))
    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    quality_gate_passed = score >= normalized_threshold and not blocking_reasons
    settings = get_settings()
    accuracy_gate = build_content_profile_auto_review_gate(
        min_accuracy=float(getattr(settings, "content_profile_auto_review_min_accuracy", 0.9) or 0.9),
        min_samples=int(getattr(settings, "content_profile_auto_review_min_samples", 20) or 20),
    )
    auto_confirm = auto_confirm_enabled and quality_gate_passed and bool(accuracy_gate["gate_passed"])

    return {
        "enabled": auto_confirm_enabled,
        "threshold": normalized_threshold,
        "score": score,
        "quality_gate_passed": quality_gate_passed,
        "auto_confirm": auto_confirm,
        "reasons": reasons,
        "review_reasons": review_reasons,
        "blocking_reasons": blocking_reasons,
        "identity_review": identity_review,
        "subtitle_count": subtitle_count,
        "transcript_excerpt_length": transcript_length,
        "approval_accuracy_gate_passed": bool(accuracy_gate["gate_passed"]),
        "approval_accuracy": accuracy_gate["measured_accuracy"],
        "approval_accuracy_required": accuracy_gate["required_accuracy"],
        "approval_accuracy_sample_size": accuracy_gate["sample_size"],
        "approval_accuracy_min_samples": accuracy_gate["minimum_sample_size"],
        "approval_accuracy_detail": accuracy_gate["detail"],
        "manual_review_sample_size": accuracy_gate["manual_review_total"],
    }


def apply_identity_review_guard(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    source_name: str = "",
) -> dict[str, Any]:
    guarded = dict(profile or {})
    resolved_specific_subject_type = str(guarded.get("subject_type") or "").strip()
    transcript_excerpt = str(guarded.get("transcript_excerpt") or "").strip()
    if not transcript_excerpt and subtitle_items:
        transcript_excerpt = build_transcript_excerpt(list(subtitle_items), max_items=24, max_chars=900)
    if isinstance(guarded.get("content_understanding"), dict):
        identity_review = _assess_identity_review_requirement(
            guarded,
            subtitle_items=subtitle_items,
            user_memory=user_memory,
            glossary_terms=glossary_terms,
            source_name=source_name,
        )
        guarded["identity_review"] = identity_review
        identity_backfilled = False
        identity_seed = (
            _seed_profile_from_subtitles(
                list(subtitle_items or []),
                glossary_terms=glossary_terms,
                subject_domain=str(guarded.get("subject_domain") or "").strip(),
            )
            if subtitle_items
            else _seed_profile_from_transcript_excerpt(
                transcript_excerpt,
                glossary_terms=glossary_terms,
                subject_domain=str(guarded.get("subject_domain") or "").strip(),
            )
        )
        for key in ("subject_brand", "subject_model"):
            if not str(guarded.get(key) or "").strip() and str(identity_seed.get(key) or "").strip():
                guarded[key] = str(identity_seed.get(key) or "").strip()
                identity_backfilled = True
        current_search_queries = [str(item).strip() for item in (guarded.get("search_queries") or []) if str(item).strip()]
        replacement_queries = [str(item).strip() for item in (identity_seed.get("search_queries") or []) if str(item).strip()]
        if (
            not current_search_queries
            and replacement_queries
        ):
            guarded["search_queries"] = list(identity_seed.get("search_queries") or [])
        elif identity_backfilled and current_search_queries and replacement_queries:
            normalized_query_blob = _normalize_profile_value(" ".join(current_search_queries))
            if not any(
                _text_matches_identity_value(
                    value,
                    normalized_text=normalized_query_blob,
                    glossary_terms=glossary_terms,
                )
                for value in (
                    str(guarded.get("subject_brand") or "").strip(),
                    str(guarded.get("subject_model") or "").strip(),
                )
                if value
            ):
                guarded["search_queries"] = replacement_queries
        if not str(guarded.get("video_theme") or "").strip():
            seeded_theme = _hint_primary_value(identity_seed, "video_theme")
            if seeded_theme:
                guarded["video_theme"] = seeded_theme
        if bool(identity_review.get("conservative_summary")):
            guarded["summary"] = _build_conservative_identity_summary(
                guarded,
                subtitle_items=subtitle_items,
            )
        elif (
            not str(guarded.get("summary") or "").strip()
            or _is_generic_profile_summary(str(guarded.get("summary") or ""))
            or (
                identity_backfilled
                and not any(
                    _text_matches_identity_value(
                        value,
                        normalized_text=_normalize_profile_value(str(guarded.get("summary") or "")),
                        glossary_terms=glossary_terms,
                    )
                    for value in (
                        str(guarded.get("subject_brand") or "").strip(),
                        str(guarded.get("subject_model") or "").strip(),
                    )
                    if value
                )
            )
        ):
            guarded["summary"] = _build_profile_summary(guarded)
        guarded = _apply_ingestible_subject_conflict_guard(
            guarded,
            subtitle_items=subtitle_items,
            transcript_excerpt=transcript_excerpt,
            glossary_terms=glossary_terms,
            source_name=source_name,
        )
        _ensure_subject_type_main(guarded)
        if resolved_specific_subject_type and not _is_generic_subject_type(resolved_specific_subject_type):
            guarded["subject_type"] = resolved_specific_subject_type
        guarded = _apply_identity_extraction_rewrite_guard(
            guarded,
            transcript_excerpt=transcript_excerpt,
            source_name=source_name,
            subtitle_items=subtitle_items,
            glossary_terms=glossary_terms,
            user_memory=user_memory,
        )
        guarded = _apply_verification_candidate_backfill(
            guarded,
            transcript_excerpt=transcript_excerpt,
            source_name=source_name,
            glossary_terms=glossary_terms,
        )
        _ensure_review_fields_not_empty(guarded, source_name=source_name, transcript_excerpt=transcript_excerpt)
        return guarded
    memory_hints = _seed_profile_from_user_memory(
        transcript_excerpt,
        user_memory,
        subject_domain=str(guarded.get("subject_domain") or "").strip(),
    )
    guarded = _sanitize_profile_identity(
        guarded,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        memory_hints=memory_hints,
        user_memory=user_memory,
        allow_subject_type_inference=False,
        allow_video_theme_inference=False,
    )
    guarded = _apply_ingestible_subject_conflict_guard(
        guarded,
        subtitle_items=subtitle_items,
        transcript_excerpt=transcript_excerpt,
        glossary_terms=glossary_terms,
        source_name=source_name,
    )
    confirmed_fields = _extract_confirmed_profile_fields(guarded)
    if "subject_type" not in confirmed_fields:
        current_subject_type = str(guarded.get("subject_type") or "").strip()
        transcript_source_labels = _profile_transcript_source_labels(guarded)
        source_label_subject_type = str(transcript_source_labels.get("subject_type") or "").strip()
        if current_subject_type and (
            _is_generic_subject_type(current_subject_type)
            or (
                source_label_subject_type
                and _normalize_profile_value(current_subject_type) != _normalize_profile_value(source_label_subject_type)
            )
            or _text_conflicts_with_verified_identity(
                current_subject_type,
                brand=str(guarded.get("subject_brand") or ""),
                model=str(guarded.get("subject_model") or ""),
                glossary_terms=glossary_terms,
            )
        ):
            guarded["subject_type"] = ""
    if "video_theme" not in confirmed_fields:
        current_video_theme = str(guarded.get("video_theme") or "").strip()
        transcript_source_labels = _profile_transcript_source_labels(guarded)
        source_label_video_theme = str(transcript_source_labels.get("video_theme") or "").strip()
        if current_video_theme and (
            (
                source_label_video_theme
                and _normalize_profile_value(current_video_theme) != _normalize_profile_value(source_label_video_theme)
            )
            or _text_conflicts_with_verified_identity(
                current_video_theme,
                brand=str(guarded.get("subject_brand") or ""),
                model=str(guarded.get("subject_model") or ""),
                glossary_terms=glossary_terms,
            )
        ):
            guarded["video_theme"] = ""
    identity_review = _assess_identity_review_requirement(
        guarded,
        subtitle_items=subtitle_items,
        user_memory=user_memory,
        glossary_terms=glossary_terms,
        source_name=source_name,
    )
    guarded["identity_review"] = identity_review
    if bool(identity_review.get("conservative_summary")):
        guarded["summary"] = _build_conservative_identity_summary(
            guarded,
            subtitle_items=subtitle_items,
        )
    guarded = _apply_identity_extraction_rewrite_guard(
        guarded,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        subtitle_items=subtitle_items,
        glossary_terms=glossary_terms,
        user_memory=user_memory,
    )
    guarded = _apply_verification_candidate_backfill(
        guarded,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
    )
    return guarded


def _assess_identity_review_requirement(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None,
    user_memory: dict[str, Any] | None,
    glossary_terms: list[dict[str, Any]] | None,
    source_name: str,
) -> dict[str, Any]:
    preset_name = _workflow_template_name(profile)
    product_like_presets = {"unboxing_standard", "edc_tactical"}
    if preset_name not in product_like_presets:
        return {
            "required": False,
            "first_seen_brand": False,
            "first_seen_model": False,
            "conservative_summary": False,
            "support_sources": [],
            "evidence_strength": "n/a",
            "reason": "",
        }

    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    if not brand and not model:
        return {
            "required": False,
            "first_seen_brand": False,
            "first_seen_model": False,
            "conservative_summary": False,
            "support_sources": [],
            "evidence_strength": "missing",
            "reason": "",
        }

    first_seen_brand = bool(brand) and not _identity_seen_before(brand, field_name="subject_brand", user_memory=user_memory)
    first_seen_model = bool(model) and not _identity_seen_before(model, field_name="subject_model", user_memory=user_memory)
    evidence_bundle = _collect_identity_evidence_bundle(
        profile,
        subtitle_items=subtitle_items,
        user_memory=user_memory,
        glossary_terms=glossary_terms,
        source_name=source_name,
    )
    trusted_source_context_identity = _source_context_supports_identity(
        (profile or {}).get("source_context"),
        brand=brand,
        model=model,
    )
    trusted_source_name_identity = _source_name_supports_identity(
        source_name,
        brand=brand,
        model=model,
    )
    related_identity_matches = [
        dict(item)
        for item in (evidence_bundle.get("matched_related_profile_sources") or [])
        if isinstance(item, dict)
    ]
    if first_seen_brand and any(
        bool(item.get("brand_match")) and _related_profile_review_priority(item) > 0
        for item in related_identity_matches
    ):
        first_seen_brand = False
    if first_seen_model and any(
        bool(item.get("model_match")) and _related_profile_review_priority(item) > 0
        for item in related_identity_matches
    ):
        first_seen_model = False
    support_sources = _collect_identity_support_sources(evidence_bundle)
    support_count = len(support_sources)
    has_external_evidence = "evidence" in support_sources
    has_related_manual_review = "related_manual_review" in support_sources
    evidence_strength = "strong" if has_external_evidence or has_related_manual_review or support_count >= 2 else "weak"
    trusted_editorial_identity = trusted_source_context_identity or trusted_source_name_identity
    required = (first_seen_brand or first_seen_model) and not trusted_editorial_identity
    current_source_support = {
        label
        for label in support_sources
        if label in {"transcript", "transcript_labels", "source_name", "source_context", "ocr", "visible_text"}
    }
    identity_bearing_non_transcript_support = current_source_support & {"source_name", "source_context", "ocr", "visible_text"}
    has_multisource_current_evidence = len(current_source_support) >= 2 and bool(
        identity_bearing_non_transcript_support
    )
    # External retrieval can help fact-checking, but it should not remove the
    # manual-confirmation cue for a first-seen product identity. We only relax
    # the conservative summary when the current clip itself provides multiple
    # identity-bearing signals.
    conservative_summary = required and not (has_multisource_current_evidence or trusted_editorial_identity)

    reason = ""
    if required and conservative_summary:
        reason = "开箱类视频命中首次品牌/型号且缺少交叉印证，需人工确认"
    elif required:
        reason = "开箱类视频命中首次品牌/型号，默认待人工确认"

    return {
        "required": required,
        "first_seen_brand": first_seen_brand,
        "first_seen_model": first_seen_model,
        "conservative_summary": conservative_summary,
        "support_sources": support_sources,
        "evidence_strength": evidence_strength,
        "reason": reason,
        "evidence_bundle": evidence_bundle,
    }


def _identity_seen_before(
    value: str,
    *,
    field_name: str,
    user_memory: dict[str, Any] | None,
) -> bool:
    normalized = _normalize_profile_value(value)
    if not normalized:
        return False

    field_preferences = (user_memory or {}).get("field_preferences") or {}
    for item in field_preferences.get(field_name) or []:
        if _normalize_profile_value(item.get("value")) == normalized:
            return True

    for item in (user_memory or {}).get("recent_corrections") or []:
        if str(item.get("field_name") or "").strip() != field_name:
            continue
        if _normalize_profile_value(item.get("corrected_value")) == normalized:
            return True

    for item in (user_memory or {}).get("keyword_preferences") or []:
        if normalized and normalized in _normalize_profile_value(item.get("keyword")):
            return True

    for item in (user_memory or {}).get("phrase_preferences") or []:
        if normalized and normalized in _normalize_profile_value(item.get("phrase")):
            return True
    return False


def _related_profile_review_priority(item: dict[str, Any] | None) -> int:
    payload = item or {}
    review_mode = str(payload.get("review_mode") or "").strip().lower()
    if bool(payload.get("manual_confirmed")) or review_mode == "manual_confirmed":
        return 2
    if review_mode == "auto_confirmed":
        return 1
    return 0


def _collect_matching_related_identity_profiles(
    profile: dict[str, Any] | None,
    *,
    brand: str,
    model: str,
) -> list[dict[str, Any]]:
    source_context = _normalize_source_context_payload((profile or {}).get("source_context"))
    if not source_context:
        return []
    brand_normalized = _normalize_profile_value(brand)
    model_normalized = _normalize_profile_value(model)
    if not brand_normalized and not model_normalized:
        return []

    matches: list[dict[str, Any]] = []
    for item in source_context.get("related_profiles") or []:
        if not isinstance(item, dict):
            continue
        priority = _related_profile_review_priority(item)
        if priority <= 0:
            continue
        candidate_brand = str(item.get("subject_brand") or "").strip()
        candidate_model = str(item.get("subject_model") or "").strip()
        candidate_brand_normalized = _normalize_profile_value(candidate_brand)
        candidate_model_normalized = _normalize_profile_value(candidate_model)
        brand_match = bool(brand_normalized) and candidate_brand_normalized == brand_normalized
        model_match = bool(model_normalized) and candidate_model_normalized == model_normalized
        if brand_normalized and candidate_brand_normalized and not brand_match:
            continue
        if model_normalized and candidate_model_normalized and not model_match:
            continue
        if not brand_match and not model_match:
            continue
        matches.append(
            {
                "source_name": str(item.get("source_name") or "").strip(),
                "subject_brand": candidate_brand,
                "subject_model": candidate_model,
                "review_mode": str(item.get("review_mode") or "").strip(),
                "manual_confirmed": bool(item.get("manual_confirmed")),
                "score": float(item.get("score") or 0.0),
                "brand_match": brand_match,
                "model_match": model_match,
            }
        )
    if not matches:
        return []
    matches.sort(
        key=lambda item: (
            _related_profile_review_priority(item),
            float(item.get("score") or 0.0),
            bool(item.get("model_match")),
            bool(item.get("brand_match")),
        ),
        reverse=True,
    )
    return matches[:4]


def _collect_identity_support_sources(evidence_bundle: dict[str, Any] | None) -> list[str]:
    bundle = evidence_bundle or {}
    support_sources: list[str] = []
    source_flags = (
        ("transcript", bundle.get("matched_subtitle_snippets") or []),
        ("transcript_labels", bundle.get("matched_transcript_source_labels") or {}),
        ("source_name", bundle.get("matched_source_name_terms") or []),
        ("ocr", bundle.get("matched_ocr_terms") or []),
        ("visible_text", bundle.get("matched_visible_text_terms") or []),
        ("evidence", bundle.get("matched_evidence_terms") or []),
    )
    for label, hits in source_flags:
        if hits and label not in support_sources:
            support_sources.append(label)
    source_context_hints = dict(bundle.get("source_context_hints") or {}) if isinstance(bundle.get("source_context_hints"), dict) else {}
    if any(
        _hint_values(source_context_hints, field_name)
        for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme")
    ) or list(source_context_hints.get("filename_entries") or []):
        support_sources.append("source_context")
    related_profiles = [
        dict(item)
        for item in (bundle.get("matched_related_profile_sources") or [])
        if isinstance(item, dict)
    ]
    if any(_related_profile_review_priority(item) >= 2 for item in related_profiles):
        support_sources.append("related_manual_review")
    elif related_profiles:
        support_sources.append("related_profile")
    return support_sources


def _trusted_identity_visible_text(profile: dict[str, Any] | None, *, ocr_hints: dict[str, Any] | None) -> str:
    ocr_visible_text = str((ocr_hints or {}).get("visible_text") or "").strip()
    if ocr_visible_text:
        return ocr_visible_text
    visual_hints = _profile_visual_cluster_hints(profile)
    return str(visual_hints.get("visible_text") or "").strip()


def _collect_identity_evidence_bundle(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None,
    user_memory: dict[str, Any] | None = None,
    glossary_terms: list[dict[str, Any]] | None,
    source_name: str,
) -> dict[str, Any]:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    matched_brand_aliases = _collect_identity_aliases(brand, glossary_terms=glossary_terms) if brand else []
    matched_model_aliases = _collect_identity_aliases(model, glossary_terms=glossary_terms) if model else []
    transcript_source_labels = _profile_transcript_source_labels(profile)
    ocr_hints = _profile_ocr_hints(profile, glossary_terms=glossary_terms)
    visible_text = _trusted_identity_visible_text(profile, ocr_hints=ocr_hints)
    evidence_text = " ".join(
        " ".join(
            str(item.get(key) or "")
            for key in ("query", "title", "snippet")
        )
        for item in (profile.get("evidence") or [])
        if isinstance(item, dict)
    ).strip()
    related_profiles = _collect_matching_related_identity_profiles(
        profile,
        brand=brand,
        model=model,
    )
    return {
        "candidate_brand": brand or None,
        "candidate_model": model or None,
        "graph_confirmed_entities": _graph_confirmed_entities(user_memory)[:6],
        "matched_subtitle_snippets": _collect_identity_subtitle_snippets(
            brand,
            model,
            subtitle_items=subtitle_items,
            glossary_terms=glossary_terms,
        ),
        "matched_transcript_source_labels": {
            field_name: str(transcript_source_labels.get(field_name) or "").strip()
            for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme")
            if str(transcript_source_labels.get(field_name) or "").strip()
        },
        "matched_glossary_aliases": {
            "brand": _collect_identity_matched_aliases(
                brand,
                source_texts=[
                    source_name,
                    visible_text,
                    evidence_text,
                    *[
                        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
                        for item in (subtitle_items or [])
                    ],
                ],
                glossary_terms=glossary_terms,
            ),
            "model": _collect_identity_matched_aliases(
                model,
                source_texts=[
                    source_name,
                    visible_text,
                    evidence_text,
                    *[
                        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
                        for item in (subtitle_items or [])
                    ],
                ],
                glossary_terms=glossary_terms,
            ),
        },
        "matched_source_name_terms": _collect_identity_match_terms(
            brand,
            model,
            text=source_name,
            glossary_terms=glossary_terms,
        ),
        "matched_visible_text_terms": _collect_identity_match_terms(
            brand,
            model,
            text=visible_text,
            glossary_terms=glossary_terms,
        ),
        "matched_ocr_terms": _collect_identity_match_terms(
            brand,
            model,
            text=str(ocr_hints.get("visible_text") or "").strip(),
            glossary_terms=glossary_terms,
        ),
        "matched_evidence_terms": _collect_identity_match_terms(
            brand,
            model,
            text=evidence_text,
            glossary_terms=glossary_terms,
        ),
        "matched_related_profile_sources": related_profiles,
        "brand_aliases": matched_brand_aliases,
        "model_aliases": matched_model_aliases,
    }


def _collect_identity_subtitle_snippets(
    brand: str,
    model: str,
    *,
    subtitle_items: list[dict[str, Any]] | None,
    glossary_terms: list[dict[str, Any]] | None,
    limit: int = 4,
) -> list[str]:
    snippets: list[str] = []
    for item in subtitle_items or []:
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        matched_terms = _collect_identity_match_terms(
            brand,
            model,
            text=text,
            glossary_terms=glossary_terms,
        )
        if not matched_terms:
            continue
        snippet = f"[{float(item.get('start_time', 0.0) or 0.0):.1f}-{float(item.get('end_time', 0.0) or 0.0):.1f}] {text}"
        if snippet not in snippets:
            snippets.append(snippet)
        if len(snippets) >= limit:
            break
    return snippets


def _collect_identity_match_terms(
    brand: str,
    model: str,
    *,
    text: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> list[str]:
    matched_terms: list[str] = []
    for value in (brand, model):
        for term in _collect_matched_identity_terms(value, text=text, glossary_terms=glossary_terms):
            if term not in matched_terms:
                matched_terms.append(term)
    return matched_terms


def _collect_identity_matched_aliases(
    value: str,
    *,
    source_texts: list[str],
    glossary_terms: list[dict[str, Any]] | None,
) -> list[str]:
    normalized_value = _normalize_profile_value(value)
    aliases: list[str] = []
    if not normalized_value:
        return aliases
    for source_text in source_texts:
        for term in _collect_matched_identity_terms(value, text=source_text, glossary_terms=glossary_terms):
            if _normalize_profile_value(term) == normalized_value:
                continue
            if term not in aliases:
                aliases.append(term)
    return aliases


def _collect_matched_identity_terms(
    value: str,
    *,
    text: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> list[str]:
    normalized_text = _normalize_profile_value(text)
    if not normalized_text:
        return []
    matched_terms: list[str] = []
    for alias in _collect_identity_aliases(value, glossary_terms=glossary_terms):
        normalized_alias = _normalize_profile_value(alias)
        if normalized_alias and normalized_alias in normalized_text and alias not in matched_terms:
            matched_terms.append(alias)
    return matched_terms


def _identity_supported_by_text(
    brand: str,
    model: str,
    *,
    text: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> bool:
    normalized_text = _normalize_profile_value(text)
    if not normalized_text:
        return False
    brand_ok = not brand or _text_matches_identity_value(brand, normalized_text=normalized_text, glossary_terms=glossary_terms)
    model_ok = not model or _text_matches_identity_value(model, normalized_text=normalized_text, glossary_terms=glossary_terms)
    return brand_ok and model_ok


def _text_matches_identity_value(
    value: str,
    *,
    normalized_text: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> bool:
    normalized_value = _normalize_profile_value(value)
    if normalized_value and normalized_value in normalized_text:
        return True
    for alias in _collect_identity_aliases(value, glossary_terms=glossary_terms):
        normalized_alias = _normalize_profile_value(alias)
        if normalized_alias and normalized_alias in normalized_text:
            return True
    return False


def _collect_identity_aliases(value: str, *, glossary_terms: list[dict[str, Any]] | None) -> list[str]:
    aliases: list[str] = []
    normalized_value = _normalize_profile_value(value)
    for candidate in [value]:
        if candidate and candidate not in aliases:
            aliases.append(candidate)
    for term in glossary_terms or []:
        correct_form = str(term.get("correct_form") or "").strip()
        if _normalize_profile_value(correct_form) != normalized_value:
            continue
        for item in term.get("wrong_forms") or []:
            alias = str(item or "").strip()
            if alias and alias not in aliases:
                aliases.append(alias)
    return aliases


def _build_conservative_identity_summary(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None,
) -> str:
    subject_type = str(profile.get("subject_type") or "").strip()
    safe_subject = subject_type if subject_type and not _is_generic_subject_type(subject_type) else ""
    raw_theme = str(profile.get("video_theme") or "").strip()
    theme = (
        _summary_theme_fragment(
            raw_theme,
            brand=str(profile.get("subject_brand") or "").strip(),
            model=str(profile.get("subject_model") or "").strip(),
            preset_name=_workflow_template_name(profile) or _content_kind_name(profile),
            content_kind=_content_kind_name(profile),
            subject_domain=str(profile.get("subject_domain") or "").strip(),
        )
        if raw_theme
        else ""
    )
    focus = _build_conservative_identity_focus(profile, subtitle_items=subtitle_items)
    if not safe_subject:
        if theme:
            return f"这条视频主要围绕{theme}展开，主体品牌型号待进一步确认，建议先结合字幕、画面文字和人工核对后再继续包装。"
        if focus:
            return f"这条视频当前主体待进一步确认，重点看{focus}，建议先结合字幕、画面文字和人工核对后再继续包装。"
        return "这条视频当前主体待进一步确认，建议先结合字幕、画面文字和人工核对后再继续包装。"
    if focus:
        return f"这条视频主要围绕一款{safe_subject}展开，重点看{focus}，具体品牌型号待人工确认。"
    return f"这条视频主要围绕一款{safe_subject}展开，具体品牌型号待人工确认，适合先人工核对主体身份后再继续包装。"


def _profile_visual_cluster_hints(profile: dict[str, Any] | None) -> dict[str, Any]:
    candidate = profile or {}
    explicit_cluster = candidate.get("visual_cluster_hints")
    if isinstance(explicit_cluster, dict) and explicit_cluster:
        return dict(explicit_cluster)
    visual_hints = candidate.get("visual_hints")
    if isinstance(visual_hints, dict) and visual_hints:
        return dict(visual_hints)
    return {}


def _visual_cluster_prompt_payload(profile: dict[str, Any] | None) -> dict[str, Any]:
    hints = _profile_visual_cluster_hints(profile)
    return {
        "subject_type": str(hints.get("subject_type") or "").strip(),
        "subject_brand": str(hints.get("subject_brand") or "").strip(),
        "subject_model": str(hints.get("subject_model") or "").strip(),
        "visible_text": str(hints.get("visible_text") or "").strip(),
    }


def _build_conservative_identity_focus(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None,
) -> str:
    focus_terms = _extract_profile_focus_terms(profile, subtitle_items=subtitle_items, limit=3)
    if focus_terms:
        return "、".join(focus_terms)
    theme = _strip_identity_tokens_from_text(
        str(profile.get("video_theme") or ""),
        brand=str(profile.get("subject_brand") or ""),
        model=str(profile.get("subject_model") or ""),
    )
    return theme[:16] if theme else ""


_OUTPUT_FOCUS_PATTERNS: list[tuple[str, tuple[str, ...]]] = [
    ("锁定机构", ("锁定机构", "锁片", "锁定")),
    ("开合", ("单手开合", "开合")),
    ("钳头", ("钳头",)),
    ("分仓", ("分仓",)),
    ("挂点", ("挂点",)),
    ("收纳", ("收纳", "装载")),
    ("做工", ("做工",)),
    ("结构", ("结构",)),
    ("材质", ("材质",)),
    ("细节", ("细节",)),
    ("手感", ("手感",)),
    ("泛光", ("泛光",)),
    ("聚光", ("聚光",)),
    ("UV", ("UV", "紫外")),
    ("亮度", ("亮度", "流明")),
    ("步骤", ("步骤",)),
    ("节点编排", ("节点编排", "节点搭建", "节点连接")),
    ("工作流", ("工作流", "流程编排")),
    ("无限画布", ("无限画布",)),
    ("新功能", ("新功能", "上线", "更新")),
    ("口感", ("口感",)),
    ("价格", ("价格", "性价比")),
]


def _extract_profile_focus_terms(
    profile: dict[str, Any],
    *,
    subtitle_items: list[dict[str, Any]] | None = None,
    limit: int = 3,
) -> list[str]:
    transcript_excerpt = str(profile.get("transcript_excerpt") or "").strip()
    if not transcript_excerpt and subtitle_items:
        transcript_excerpt = build_transcript_excerpt(list(subtitle_items), max_items=24, max_chars=900)
    preset_name = _workflow_template_name(profile) or _content_kind_name(profile)
    theme_fragment = _summary_theme_fragment(
        str(profile.get("video_theme") or ""),
        brand=str(profile.get("subject_brand") or ""),
        model=str(profile.get("subject_model") or ""),
        preset_name=preset_name,
        content_kind=_content_kind_name(profile),
        subject_domain=str(profile.get("subject_domain") or ""),
    )
    summary = _strip_identity_tokens_from_text(
        str(profile.get("summary") or ""),
        brand=str(profile.get("subject_brand") or ""),
        model=str(profile.get("subject_model") or ""),
    )
    combined = "\n".join(part for part in (transcript_excerpt, theme_fragment, summary) if part)
    if not combined:
        return []
    focus_terms: list[str] = []
    for label, patterns in _OUTPUT_FOCUS_PATTERNS:
        if any(pattern and pattern in combined for pattern in patterns):
            focus_terms.append(label)
            if len(focus_terms) >= limit:
                break
    return focus_terms


def _strip_identity_tokens_from_text(text: str, *, brand: str, model: str) -> str:
    result = str(text or "").strip()
    for token in (brand, model):
        value = str(token or "").strip()
        if value:
            result = re.sub(re.escape(value), "", result, flags=re.IGNORECASE)
    result = re.sub(r"(开箱与上手评测|开箱与功能实测|开箱对比评测|开箱评测|上手评测)", "", result)
    return _clean_line(result)


def _resolve_profile_identity(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
) -> tuple[IdentityEvidenceBundle, dict[str, list[Any]], Any]:
    candidate_profile = dict(profile or {})
    raw_visual_hints = _profile_visual_cluster_hints(candidate_profile)
    subject_domain = str(candidate_profile.get("subject_domain") or "").strip()
    transcript_hints = _seed_profile_from_transcript_excerpt(
        transcript_excerpt,
        glossary_terms=glossary_terms,
        subject_domain=subject_domain,
    )
    visible_text_hints = _seed_profile_from_text(
        str(candidate_profile.get("visible_text") or "").strip(),
        glossary_terms=glossary_terms,
        subject_domain=subject_domain,
    )
    source_hints = (
        _seed_profile_from_text(
            Path(source_name).stem,
            glossary_terms=glossary_terms,
            subject_domain=subject_domain,
        )
        if _is_informative_source_hint(Path(source_name).stem)
        else {}
    )
    ocr_hints = _profile_ocr_hints(candidate_profile, glossary_terms=glossary_terms)
    source_visual_overlap_hints = _build_source_visual_overlap_hints(
        source_name=source_name,
        visible_text=(
            str(ocr_hints.get("visible_text") or "").strip()
            or str(raw_visual_hints.get("visible_text") or "").strip()
            or str(candidate_profile.get("visible_text") or "").strip()
        ),
    )
    memory_confirmed_hints = _select_confirmed_entity_from_user_memory(
        transcript_excerpt,
        user_memory=user_memory,
        subject_type=str(candidate_profile.get("subject_type") or transcript_hints.get("subject_type") or ""),
        subject_domain=subject_domain,
    )
    evidence_bundle = IdentityEvidenceBundle(
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        transcript_hints=transcript_hints,
        transcript_source_labels=_profile_transcript_source_labels(candidate_profile),
        source_hints=source_hints,
        source_context_hints=_source_context_candidate_hints(candidate_profile.get("source_context")),
        source_visual_overlap_hints=source_visual_overlap_hints,
        visual_cluster_hints={
            "subject_brand": str(raw_visual_hints.get("subject_brand") or "").strip(),
            "subject_model": str(raw_visual_hints.get("subject_model") or "").strip(),
            "subject_type": str(raw_visual_hints.get("subject_type") or "").strip(),
            "visible_text": str(raw_visual_hints.get("visible_text") or "").strip(),
        },
        visual_hints={},
        visible_text_hints=visible_text_hints,
        ocr_hints=ocr_hints,
        memory_confirmed_hints=memory_confirmed_hints,
        graph_confirmed_entities=_graph_confirmed_entities(user_memory)[:6],
        profile_identity={
            "subject_brand": str(candidate_profile.get("subject_brand") or "").strip(),
            "subject_model": str(candidate_profile.get("subject_model") or "").strip(),
            "subject_type": str(candidate_profile.get("subject_type") or "").strip(),
            "video_theme": str(candidate_profile.get("video_theme") or "").strip(),
        },
    )
    scored_candidates = score_identity_candidates(
        build_identity_candidates(evidence_bundle),
        normalize=_normalize_profile_value,
    )
    resolved_identity = resolve_identity_candidates(
        scored_candidates,
        normalize=_normalize_profile_value,
        mapped_brand_for_model=_mapped_brand_for_model,
    )
    return evidence_bundle, scored_candidates, resolved_identity


def _selected_identity_candidate(candidates: list[Any], selected_value: str) -> Any | None:
    normalized_selected = _normalize_profile_value(selected_value)
    if not normalized_selected:
        return None
    for candidate in candidates:
        if getattr(candidate, "normalized_value", "") == normalized_selected:
            return candidate
    return None


def _identity_candidate_confidence(candidate: Any | None) -> float:
    if candidate is None:
        return 0.0
    current_evidence_score = max(0, int(getattr(candidate, "current_evidence_score", 0) or 0))
    current_source_count = max(0, int(getattr(candidate, "current_source_count", 0) or 0))
    total_score = max(current_evidence_score, int(getattr(candidate, "total_score", 0) or 0))
    confidence = min(1.0, current_evidence_score / 5.0)
    if current_source_count > 1:
        confidence = min(1.0, confidence + (current_source_count - 1) * 0.08)
    if total_score > current_evidence_score:
        confidence = min(1.0, confidence + 0.04)
    return round(confidence, 3)


def _serialize_identity_candidates(candidates: list[Any], *, selected_value: str) -> list[dict[str, Any]]:
    selected_normalized = _normalize_profile_value(selected_value)
    serialized: list[dict[str, Any]] = []
    for candidate in candidates[:3]:
        serialized.append(
            {
                "value": str(getattr(candidate, "value", "") or "").strip(),
                "selected": bool(selected_normalized and getattr(candidate, "normalized_value", "") == selected_normalized),
                "current_evidence_score": int(getattr(candidate, "current_evidence_score", 0) or 0),
                "current_source_count": int(getattr(candidate, "current_source_count", 0) or 0),
                "total_score": int(getattr(candidate, "total_score", 0) or 0),
                "sources": list(getattr(candidate, "all_sources", ()) or ()),
            }
        )
    return serialized


def _build_identity_extraction(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_bundle, scored_candidates, resolved_identity = _resolve_profile_identity(
        profile,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        user_memory=user_memory,
    )
    resolved_values = {
        "subject_brand": str(resolved_identity.subject_brand or "").strip(),
        "subject_model": str(resolved_identity.subject_model or "").strip(),
        "subject_type": str(resolved_identity.subject_type or "").strip(),
        "video_theme": str(resolved_identity.video_theme or "").strip(),
    }
    confidence: dict[str, float] = {}
    sources: dict[str, list[str]] = {}
    candidates: dict[str, list[dict[str, Any]]] = {}
    for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        field_candidates = list(scored_candidates.get(field_name) or [])
        selected_candidate = _selected_identity_candidate(field_candidates, resolved_values.get(field_name, ""))
        confidence[field_name] = _identity_candidate_confidence(selected_candidate)
        sources[field_name] = list(getattr(selected_candidate, "all_sources", ()) or ())
        candidates[field_name] = _serialize_identity_candidates(
            field_candidates,
            selected_value=resolved_values.get(field_name, ""),
        )
    confidence["overall"] = round(
        max(confidence.get("subject_brand", 0.0), confidence.get("subject_model", 0.0), confidence.get("subject_type", 0.0)),
        3,
    )
    return {
        "resolved": resolved_values,
        "confidence": confidence,
        "sources": sources,
        "candidates": candidates,
        "conflicts": list(getattr(resolved_identity, "conflicts", ()) or ()),
        "supporting_signals": {
            "transcript_source_labels": _profile_transcript_source_labels(profile),
            "ocr_hints": _profile_ocr_hints(profile, glossary_terms=glossary_terms),
            "memory_confirmed_hints": dict(evidence_bundle.memory_confirmed_hints or {}),
            "source_hints": dict(evidence_bundle.source_hints or {}),
            "source_context_hints": dict(evidence_bundle.source_context_hints or {}),
        },
    }


def _sanitize_profile_identity(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    glossary_terms: list[dict[str, Any]] | None = None,
    memory_hints: dict[str, Any] | None = None,
    user_memory: dict[str, Any] | None = None,
    allow_subject_type_inference: bool = False,
    allow_video_theme_inference: bool = False,
) -> dict[str, Any]:
    sanitized = dict(profile or {})
    transcript_source_labels = _profile_transcript_source_labels(sanitized)
    confirmed_fields = _extract_confirmed_profile_fields(sanitized)
    subject_domain = str(sanitized.get("subject_domain") or "").strip()
    transcript_hints = _seed_profile_from_transcript_excerpt(
        transcript_excerpt,
        glossary_terms=glossary_terms,
        subject_domain=subject_domain,
    )
    source_hints = (
        _seed_profile_from_text(
            Path(source_name).stem,
            glossary_terms=glossary_terms,
            subject_domain=subject_domain,
        )
        if _is_informative_source_hint(Path(source_name).stem)
        else {}
    )

    confirmed_brand = str(confirmed_fields.get("subject_brand") or "").strip()
    confirmed_model = str(confirmed_fields.get("subject_model") or "").strip()
    _evidence_bundle, scored_candidates, resolved_identity = _resolve_profile_identity(
        sanitized,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        user_memory=user_memory,
    )
    identity_conflict_detected = bool(resolved_identity.conflicts)

    if confirmed_model:
        verified_model = confirmed_model
    else:
        verified_model = resolved_identity.subject_model

    if confirmed_brand:
        verified_brand = confirmed_brand
    else:
        verified_brand = resolved_identity.subject_brand

    profile_identity_conflict_detected = False
    current_profile_brand = str(sanitized.get("subject_brand") or "").strip()
    current_profile_model = str(sanitized.get("subject_model") or "").strip()
    if current_profile_brand and verified_brand and _normalize_profile_value(current_profile_brand) != _normalize_profile_value(verified_brand):
        profile_identity_conflict_detected = True
    if current_profile_model and verified_model and _normalize_profile_value(current_profile_model) != _normalize_profile_value(verified_model):
        profile_identity_conflict_detected = True

    if (
        current_profile_model
        and verified_model
        and _identity_values_compatible(current_profile_model, verified_model)
        and len(current_profile_model) > len(verified_model)
    ):
        verified_model = current_profile_model
    if verified_model == "FXX1":
        verified_model = "FXX1小副包"

    if not verified_brand:
        sanitized["subject_brand"] = ""
    else:
        sanitized["subject_brand"] = verified_brand

    if not verified_model:
        sanitized["subject_model"] = ""
    else:
        sanitized["subject_model"] = verified_model

    if allow_subject_type_inference and "subject_type" not in confirmed_fields:
        resolved_subject_type = str(resolved_identity.subject_type or "").strip()
        current_subject_type = str(sanitized.get("subject_type") or "").strip()
        if resolved_subject_type:
            sanitized["subject_type"] = resolved_subject_type
        elif _is_generic_subject_type(current_subject_type):
            sanitized["subject_type"] = ""

    if allow_video_theme_inference and "video_theme" not in confirmed_fields:
        resolved_video_theme = str(resolved_identity.video_theme or "").strip()
        current_video_theme = str(sanitized.get("video_theme") or "").strip()
        preset_name = _workflow_template_name(sanitized)
        content_kind = _content_kind_name(sanitized)
        subject_domain = str(sanitized.get("subject_domain") or "").strip()
        if _should_replace_video_theme(
            current_video_theme=current_video_theme,
            resolved_video_theme=resolved_video_theme,
            preset_name=preset_name,
            content_kind=content_kind,
            subject_domain=subject_domain,
        ):
            sanitized["video_theme"] = resolved_video_theme
        elif current_video_theme and not _is_specific_video_theme_for_context(
            current_video_theme,
            preset_name=preset_name,
            content_kind=content_kind,
            subject_domain=subject_domain,
        ):
            sanitized["video_theme"] = ""

    if "visible_text" not in confirmed_fields:
        current_visible_text = str(sanitized.get("visible_text") or "").strip()
        if _visible_text_conflicts_with_verified_identity(
            current_visible_text,
            brand=str(sanitized.get("subject_brand") or ""),
            model=str(sanitized.get("subject_model") or ""),
            glossary_terms=glossary_terms,
        ):
            sanitized["visible_text"] = ""

    resolved_video_theme_value = str(resolved_identity.video_theme or "").strip()
    if sanitized.get("subject_brand") or sanitized.get("subject_model"):
        for key in ("video_theme", "summary"):
            if key in confirmed_fields:
                continue
            value = str(sanitized.get(key) or "").strip()
            if (
                key == "video_theme"
                and resolved_video_theme_value
                and _normalize_profile_value(value) == _normalize_profile_value(resolved_video_theme_value)
            ):
                continue
            if value and _text_conflicts_with_verified_identity(
                value,
                brand=str(sanitized.get("subject_brand") or ""),
                model=str(sanitized.get("subject_model") or ""),
                glossary_terms=glossary_terms,
            ):
                sanitized[key] = ""
                continue
            if value and _text_mentions_conflicting_previous_identity(
                value,
                previous_brand=current_profile_brand,
                previous_model=current_profile_model,
                verified_brand=str(sanitized.get("subject_brand") or ""),
                verified_model=str(sanitized.get("subject_model") or ""),
            ):
                sanitized[key] = ""

    if identity_conflict_detected or profile_identity_conflict_detected or (not sanitized.get("subject_brand") and not sanitized.get("subject_model")):
        for key in ("video_theme", "visible_text", "hook_line", "summary", "engagement_question"):
            if key in confirmed_fields:
                continue
            value = str(sanitized.get(key) or "").strip()
            if (
                key == "video_theme"
                and resolved_video_theme_value
                and _normalize_profile_value(value) == _normalize_profile_value(resolved_video_theme_value)
            ):
                continue
            if value and (
                _text_has_unsupported_identity(
                    value,
                    transcript_hints=transcript_hints,
                    memory_hints=memory_hints,
                    source_hints=source_hints,
                    glossary_terms=glossary_terms,
                )
                or _text_conflicts_with_verified_identity(
                    value,
                    brand=str(sanitized.get("subject_brand") or ""),
                    model=str(sanitized.get("subject_model") or ""),
                    glossary_terms=glossary_terms,
                )
            ):
                sanitized[key] = ""

        search_queries = [
            str(item).strip()
            for item in sanitized.get("search_queries") or []
            if str(item).strip()
        ]
        if "search_queries" not in confirmed_fields:
            sanitized["search_queries"] = [
                query for query in search_queries
                if _query_is_identity_supported(query, transcript_excerpt=transcript_excerpt, source_name=source_name)
            ]
        cover_title = sanitized.get("cover_title")
        if isinstance(cover_title, dict):
            title_text = " ".join(str(cover_title.get(key) or "") for key in ("top", "main", "bottom"))
            title_tokens = _extract_guard_tokens(
                title_text
            )
            if title_tokens or _text_has_unsupported_identity(
                title_text,
                transcript_hints=transcript_hints,
                memory_hints=memory_hints,
                source_hints=source_hints,
                glossary_terms=glossary_terms,
            ) or _text_conflicts_with_verified_identity(
                title_text,
                brand=str(sanitized.get("subject_brand") or ""),
                model=str(sanitized.get("subject_model") or ""),
                glossary_terms=glossary_terms,
            ):
                sanitized["cover_title"] = {}
        evidence = []
        for item in sanitized.get("evidence") or []:
            evidence_text = " ".join(
                str(item.get(key) or "")
                for key in ("query", "title", "snippet")
            )
            if _text_has_unsupported_identity(
                evidence_text,
                transcript_hints=transcript_hints,
                memory_hints=memory_hints,
                source_hints=source_hints,
                glossary_terms=glossary_terms,
            ) or _text_conflicts_with_verified_identity(
                evidence_text,
                brand=str(sanitized.get("subject_brand") or ""),
                model=str(sanitized.get("subject_model") or ""),
                glossary_terms=glossary_terms,
            ):
                continue
            evidence.append(item)
        sanitized["evidence"] = evidence

    return _apply_brand_display_fields(sanitized)


def _profile_transcript_source_labels(profile: dict[str, Any] | None) -> dict[str, Any]:
    transcript_evidence = (profile or {}).get("transcript_evidence")
    if not isinstance(transcript_evidence, dict):
        return {}
    labels = transcript_evidence.get("source_labels")
    return dict(labels) if isinstance(labels, dict) else {}


def _profile_ocr_hints(
    profile: dict[str, Any] | None,
    *,
    glossary_terms: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    ocr_evidence = (profile or {}).get("ocr_evidence")
    ocr_profile = (profile or {}).get("ocr_profile")
    source = ocr_evidence if isinstance(ocr_evidence, dict) else ocr_profile if isinstance(ocr_profile, dict) else {}
    hints = {
        field_name: str(source.get(field_name) or "").strip()
        for field_name in ("subject_brand", "subject_model", "subject_type")
        if str(source.get(field_name) or "").strip()
    }
    visible_text = str(source.get("visible_text") or "").strip()
    if visible_text:
        hints.setdefault("visible_text", visible_text)
        seeded = _seed_profile_from_text(
            visible_text,
            glossary_terms=glossary_terms,
            subject_domain=str((profile or {}).get("subject_domain") or "").strip(),
        )
        for field_name in ("subject_brand", "subject_model"):
            value = str(seeded.get(field_name) or "").strip()
            if value and field_name not in hints:
                hints[field_name] = value
        for value in _hint_values(seeded, "subject_type"):
            _append_hint_candidate(hints, "subject_type", value)
    return hints


def _dedupe_text_entries(values: list[Any] | tuple[Any, ...] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = str(item or "").strip()
        normalized = _normalize_profile_value(text)
        if not text or not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(text)
    return deduped


def extract_source_identity_constraints(
    profile: dict[str, Any] | None,
    *,
    source_name: str = "",
) -> dict[str, Any]:
    candidate = dict(profile or {})
    source_context = _normalize_source_context_payload(candidate.get("source_context"))
    effective_source_context = dict(source_context)
    merged_source_names = [
        str(item).strip()
        for item in (effective_source_context.get("merged_source_names") or [])
        if str(item).strip()
    ]
    normalized_source_name = str(source_name or "").strip()
    if normalized_source_name and normalized_source_name not in merged_source_names:
        effective_source_context["merged_source_names"] = [normalized_source_name, *merged_source_names][:12]
    if not effective_source_context:
        return {}

    source_hints = _source_context_candidate_hints(effective_source_context)
    resolved_feedback = (
        dict(effective_source_context.get("resolved_feedback") or {})
        if isinstance(effective_source_context.get("resolved_feedback"), dict)
        else {}
    )
    constraints: dict[str, Any] = {
        "authoritative": bool(
            str(effective_source_context.get("video_description") or "").strip()
            or list(source_hints.get("filename_entries") or [])
        ),
        "review_basis": "source_context" if source_context else "source_name",
        "video_description": str(effective_source_context.get("video_description") or "").strip(),
        "filename_entries": list(source_hints.get("filename_entries") or []),
    }
    for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        values = _dedupe_text_entries(
            [
                resolved_feedback.get(field_name),
                *_hint_values(source_hints, field_name),
            ]
        )
        if not values:
            continue
        constraints[field_name] = values[0]
        constraints[_hint_candidate_key(field_name)] = values

    search_queries = _dedupe_text_entries(
        [
            *(resolved_feedback.get("search_queries") or []),
            *(source_hints.get("search_queries") or []),
        ]
    )
    if search_queries:
        constraints["search_queries"] = search_queries[:8]

    if not any(
        constraints.get(field_name)
        for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme")
    ):
        return {}
    return constraints


def apply_source_identity_constraints(
    profile: dict[str, Any] | None,
    *,
    source_name: str = "",
    transcript_excerpt: str = "",
) -> dict[str, Any]:
    constrained = dict(profile or {})
    constraints = extract_source_identity_constraints(constrained, source_name=source_name)
    if not constraints:
        return constrained

    constrained["source_identity_constraints"] = dict(constraints)
    manual_feedback = (
        dict(constrained.get("resolved_review_user_feedback") or {})
        if isinstance(constrained.get("resolved_review_user_feedback"), dict)
        else {}
    )
    manual_override_fields = {
        field_name
        for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme")
        if str(manual_feedback.get(field_name) or "").strip()
    }

    changed_identity = False
    for field_name in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        if field_name in manual_override_fields:
            continue
        constrained_value = str(constraints.get(field_name) or "").strip()
        if not constrained_value:
            continue
        if field_name == "video_theme":
            current_theme = str(constrained.get("video_theme") or "").strip()
            current_brand = str(constrained.get("subject_brand") or "").strip()
            current_model = str(constrained.get("subject_model") or "").strip()
            if current_theme and _is_specific_video_theme_for_context(
                current_theme,
                preset_name=_workflow_template_name(constrained),
                content_kind=_content_kind_name(constrained),
                subject_domain=str(constrained.get("subject_domain") or ""),
            ) and not _text_conflicts_with_verified_identity(
                current_theme,
                brand=current_brand,
                model=current_model,
                glossary_terms=None,
            ):
                continue
        if str(constrained.get(field_name) or "").strip() != constrained_value:
            constrained[field_name] = constrained_value
            changed_identity = True

    merged_queries = _dedupe_text_entries(
        [
            *(constraints.get("search_queries") or []),
            *(constrained.get("search_queries") or []),
        ]
    )
    if merged_queries:
        constrained["search_queries"] = merged_queries[:8]

    if not str(constrained.get("subject_domain") or "").strip():
        inferred_subject_domain = _subject_domain_from_subject_type(str(constrained.get("subject_type") or "").strip())
        if inferred_subject_domain:
            constrained["subject_domain"] = inferred_subject_domain

    brand = str(constrained.get("subject_brand") or "").strip()
    model = str(constrained.get("subject_model") or "").strip()
    current_theme = str(constrained.get("video_theme") or "").strip()
    if (
        not current_theme
        or _text_conflicts_with_verified_identity(
            current_theme,
            brand=brand,
            model=model,
            glossary_terms=None,
        )
    ):
        rebuilt_theme = _build_identity_driven_video_theme(constrained, transcript_excerpt=transcript_excerpt)
        if rebuilt_theme:
            constrained["video_theme"] = rebuilt_theme

    current_summary = str(constrained.get("summary") or "").strip()
    summary_needs_refresh = (
        changed_identity
        or not current_summary
        or _is_generic_profile_summary(current_summary)
        or _text_conflicts_with_verified_identity(
            current_summary,
            brand=brand,
            model=model,
            glossary_terms=None,
        )
        or not any(
            _text_matches_identity_value(
                value,
                normalized_text=_normalize_profile_value(current_summary),
                glossary_terms=None,
            )
            for value in (brand, model)
            if value
        )
    )
    if summary_needs_refresh:
        constrained["summary"] = _build_profile_summary(constrained)

    _ensure_search_queries(constrained, source_name, transcript_excerpt=transcript_excerpt)
    constrained["keywords"] = _build_review_keywords(constrained)

    preset = select_workflow_template(
        workflow_template=_workflow_template_name(constrained) or constrained.get("workflow_template"),
        content_kind=_content_kind_name(constrained),
        subject_domain=str(constrained.get("subject_domain") or ""),
        subject_model=str(constrained.get("subject_model") or ""),
        subject_type=str(constrained.get("subject_type") or ""),
        transcript_hint=transcript_excerpt,
    )
    if _is_generic_engagement_question(str(constrained.get("engagement_question") or "")):
        constrained["engagement_question"] = _default_engagement_question(preset)
    constrained["cover_title"] = build_cover_title(constrained, preset)
    return constrained


def _prefer_content_understanding_video_theme(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    confirmed_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    preferred = dict(profile or {})
    confirmed = confirmed_fields or {}
    if "video_theme" in confirmed:
        return preferred

    content_understanding = (
        dict(preferred.get("content_understanding") or {})
        if isinstance(preferred.get("content_understanding"), dict)
        else {}
    )
    understanding_theme = str(content_understanding.get("video_theme") or "").strip()
    if not understanding_theme:
        return preferred

    preset_name = _workflow_template_name(preferred)
    content_kind = _content_kind_name(preferred)
    subject_domain = str(preferred.get("subject_domain") or "").strip()
    if not _is_specific_video_theme_for_context(
        understanding_theme,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        return preferred

    brand = str(preferred.get("subject_brand") or "").strip()
    model = str(preferred.get("subject_model") or "").strip()
    if _text_conflicts_with_verified_identity(
        understanding_theme,
        brand=brand,
        model=model,
        glossary_terms=None,
    ):
        return preferred

    current_theme = str(preferred.get("video_theme") or "").strip()
    if not current_theme:
        preferred["video_theme"] = understanding_theme
        return preferred
    if _normalize_profile_value(current_theme) == _normalize_profile_value(understanding_theme):
        return preferred

    detail_terms = _content_understanding_detail_terms(preferred)
    current_detail_coverage = _detail_term_coverage_score(current_theme, detail_terms)
    understanding_detail_coverage = _detail_term_coverage_score(understanding_theme, detail_terms)
    if understanding_detail_coverage > current_detail_coverage:
        preferred["video_theme"] = understanding_theme
        return preferred

    rebuilt_theme = _build_identity_driven_video_theme(preferred, transcript_excerpt=transcript_excerpt)
    extracted_theme = ""
    identity_extraction = preferred.get("identity_extraction")
    if isinstance(identity_extraction, dict):
        resolved = identity_extraction.get("resolved")
        if isinstance(resolved, dict):
            extracted_theme = str(resolved.get("video_theme") or "").strip()
    if (
        extracted_theme
        and _normalize_profile_value(current_theme) == _normalize_profile_value(extracted_theme)
    ):
        preferred["video_theme"] = understanding_theme
        return preferred
    if _normalize_profile_value(current_theme) == _normalize_profile_value(rebuilt_theme):
        preferred["video_theme"] = understanding_theme
        return preferred
    if not _is_specific_video_theme_for_context(
        current_theme,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        preferred["video_theme"] = understanding_theme
        return preferred
    if _text_conflicts_with_verified_identity(
        current_theme,
        brand=brand,
        model=model,
        glossary_terms=None,
    ):
        preferred["video_theme"] = understanding_theme
    return preferred


def _prefer_content_understanding_summary(
    profile: dict[str, Any],
    *,
    confirmed_fields: dict[str, str] | None = None,
    allow_override: bool = True,
) -> dict[str, Any]:
    preferred = dict(profile or {})
    confirmed = confirmed_fields or {}
    if "summary" in confirmed:
        return preferred

    content_understanding = (
        dict(preferred.get("content_understanding") or {})
        if isinstance(preferred.get("content_understanding"), dict)
        else {}
    )
    understanding_summary = str(content_understanding.get("summary") or "").strip()
    if not understanding_summary:
        return preferred

    brand = str(preferred.get("subject_brand") or "").strip()
    model = str(preferred.get("subject_model") or "").strip()
    if _text_conflicts_with_verified_identity(
        understanding_summary,
        brand=brand,
        model=model,
        glossary_terms=None,
    ):
        return preferred

    current_summary = str(preferred.get("summary") or "").strip()
    detail_terms = _content_understanding_detail_terms(preferred)
    current_detail_coverage = _detail_term_coverage_score(current_summary, detail_terms)
    understanding_detail_coverage = _detail_term_coverage_score(understanding_summary, detail_terms)

    if understanding_detail_coverage > current_detail_coverage:
        preferred["summary"] = understanding_summary
        return preferred
    if current_summary and not allow_override and not _is_generic_profile_summary(current_summary):
        return preferred
    preferred["summary"] = understanding_summary
    return preferred


def _content_understanding_detail_terms(profile: dict[str, Any]) -> list[str]:
    content_understanding = (
        dict(profile.get("content_understanding") or {})
        if isinstance(profile.get("content_understanding"), dict)
        else {}
    )
    semantic_facts = (
        dict(content_understanding.get("semantic_facts") or {})
        if isinstance(content_understanding.get("semantic_facts"), dict)
        else {}
    )
    terms: list[str] = []
    for key in ("aspect_candidates", "component_candidates", "entity_candidates"):
        for item in list(semantic_facts.get(key) or [])[:12]:
            value = str(item or "").strip()
            if value:
                terms.append(value)
    for span in list(content_understanding.get("evidence_spans") or [])[:8]:
        if not isinstance(span, dict):
            continue
        value = str(span.get("text") or "").strip()
        if value:
            terms.extend(_extract_query_support_terms_keywords(value))
    filtered: list[str] = []
    seen: set[str] = set()
    for item in terms:
        normalized = _normalize_profile_value(item)
        if (
            not normalized
            or normalized in seen
            or normalized in {"开箱", "实测", "体验", "教程", "功能", "产品", "视频", "内容", "日常"}
            or len(normalized) < 2
        ):
            continue
        seen.add(normalized)
        filtered.append(str(item).strip())
    return filtered[:12]


def _detail_term_coverage_score(text: str, detail_terms: list[str]) -> int:
    normalized_text = _normalize_profile_value(text)
    if not normalized_text:
        return 0
    return sum(
        1
        for term in detail_terms
        if (normalized := _normalize_profile_value(term)) and normalized in normalized_text
    )


def _graph_confirmed_entities(user_memory: dict[str, Any] | None) -> list[dict[str, Any]]:
    graph_bucket = (user_memory or {}).get("entity_graph")
    if isinstance(graph_bucket, dict):
        graph_entities = list(graph_bucket.get("confirmed_entities") or [])
        if graph_entities:
            return graph_entities
    return list((user_memory or {}).get("confirmed_entities") or [])


def _mapped_brand_for_model(model: object) -> str:
    if not str(model or "").strip():
        return ""
    for candidate, brand in _MODEL_TO_BRAND.items():
        if _identity_values_compatible(candidate, model):
            return brand
    return ""


def _first_supported_identity_value(primary: Any, *candidates: Any) -> str:
    primary_value = str(primary or "").strip()
    if not primary_value:
        return ""
    for candidate in candidates:
        candidate_value = str(candidate or "").strip()
        if candidate_value and _identity_values_compatible(primary_value, candidate_value):
            return candidate_value
    return ""


def _supported_identity_value(primary: Any, *candidates: Any) -> str:
    primary_value = str(primary or "").strip()
    if not primary_value:
        normalized_candidates: dict[str, str] = {}
        candidate_counts: dict[str, int] = {}
        for candidate in candidates:
            candidate_value = str(candidate or "").strip()
            candidate_key = _normalize_profile_value(candidate_value)
            if not candidate_key:
                continue
            normalized_candidates.setdefault(candidate_key, candidate_value)
            candidate_counts[candidate_key] = candidate_counts.get(candidate_key, 0) + 1
        if not candidate_counts:
            return ""
        if len(candidate_counts) == 1:
            only_key = next(iter(candidate_counts))
            return normalized_candidates[only_key]
        supported_keys = [key for key, count in candidate_counts.items() if count >= 2]
        if len(supported_keys) == 1:
            return normalized_candidates[supported_keys[0]]
        return ""
    if _identity_support_count(primary_value, *candidates) >= 2:
        return primary_value
    return ""


def _identity_support_count(primary: Any, *candidates: Any) -> int:
    primary_value = str(primary or "").strip()
    if not primary_value:
        return 0
    count = 0
    for candidate in candidates:
        candidate_value = str(candidate or "").strip()
        if candidate_value and _identity_values_compatible(primary_value, candidate_value):
            count += 1
    return count


def _query_is_identity_supported(query: str, *, transcript_excerpt: str, source_name: str) -> bool:
    return _search_query_support_score(
        query,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
    ) > 0


def _normalize_profile_value(value: object) -> str:
    return _normalize_profile_value_keywords(value)


def _model_family_key(value: object) -> str:
    normalized = _normalize_profile_value(value)
    if not normalized:
        return ""
    matches = [match.group(1) for match in _MODEL_FAMILY_RE.finditer(str(value or ""))]
    normalized_matches = [_normalize_profile_value(item) for item in matches if _normalize_profile_value(item)]
    if normalized_matches:
        normalized_matches.sort(key=len, reverse=True)
        return normalized_matches[0]
    compact = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    if re.search(r"[A-Z]", compact) and re.search(r"\d", compact):
        return compact
    return normalized


def _identity_values_compatible(left: object, right: object) -> bool:
    normalized_left = _normalize_profile_value(left)
    normalized_right = _normalize_profile_value(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    left_family = _model_family_key(left)
    right_family = _model_family_key(right)
    if left_family and right_family and left_family == right_family:
        return True
    if len(normalized_left) >= 4 and len(normalized_right) >= 4:
        if normalized_left in normalized_right or normalized_right in normalized_left:
            return True
    return False


def _text_has_unsupported_identity(
    text: str,
    *,
    transcript_hints: dict[str, Any],
    memory_hints: dict[str, Any] | None,
    source_hints: dict[str, Any],
    glossary_terms: list[dict[str, Any]] | None = None,
) -> bool:
    seeded = _seed_profile_from_text(text, glossary_terms=glossary_terms)
    seeded_brand = str(seeded.get("subject_brand") or "").strip()
    seeded_model = str(seeded.get("subject_model") or "").strip()
    if not seeded_brand and not seeded_model:
        return False
    if seeded_brand and not _first_supported_identity_value(
        seeded_brand,
        transcript_hints.get("subject_brand"),
        source_hints.get("subject_brand"),
    ):
        return True
    if seeded_model and not _first_supported_identity_value(
        seeded_model,
        transcript_hints.get("subject_model"),
        source_hints.get("subject_model"),
    ):
        return True
    return False


def _text_conflicts_with_verified_identity(
    text: str,
    *,
    brand: str,
    model: str,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> bool:
    if not text or not (brand or model):
        return False
    normalized_text = _normalize_profile_value(text)
    normalized_brand = _normalize_profile_value(brand)
    for known_brand in set(_MODEL_TO_BRAND.values()):
        normalized_known_brand = _normalize_profile_value(known_brand)
        if (
            normalized_known_brand
            and not _identity_values_compatible(known_brand, brand)
            and normalized_known_brand in normalized_text
        ):
            return True
    seeded = _seed_profile_from_text(text, glossary_terms=glossary_terms)
    seeded_brand = str(seeded.get("subject_brand") or "").strip()
    seeded_model = str(seeded.get("subject_model") or "").strip()
    if seeded_brand and brand and not _identity_values_compatible(seeded_brand, brand):
        return True
    if seeded_model and model and not _identity_values_compatible(seeded_model, model):
        return True
    mapped_brand = _mapped_brand_for_model(seeded_model or model)
    effective_brand = seeded_brand or brand
    if mapped_brand and effective_brand and not _identity_values_compatible(effective_brand, mapped_brand):
        return True
    return False


def _text_mentions_conflicting_previous_identity(
    text: str,
    *,
    previous_brand: str,
    previous_model: str,
    verified_brand: str,
    verified_model: str,
) -> bool:
    normalized_text = _normalize_profile_value(text)
    if not normalized_text:
        return False
    for previous, verified in (
        (previous_brand, verified_brand),
        (previous_model, verified_model),
    ):
        previous_normalized = _normalize_profile_value(previous)
        verified_normalized = _normalize_profile_value(verified)
        if (
            previous_normalized
            and previous_normalized in normalized_text
            and previous_normalized != verified_normalized
        ):
            return True
    return False


def _visible_text_conflicts_with_verified_identity(
    text: str,
    *,
    brand: str,
    model: str,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> bool:
    visible_text = str(text or "").strip()
    if not visible_text or not (brand or model):
        return False
    if _text_conflicts_with_verified_identity(
        visible_text,
        brand=brand,
        model=model,
        glossary_terms=glossary_terms,
    ):
        return True

    tokens = _extract_guard_tokens(visible_text)
    if not tokens:
        return False

    allowed_tokens: set[str] = set()
    for value in (brand, model):
        for alias in _collect_identity_aliases(value, glossary_terms=glossary_terms):
            allowed_tokens.update(_extract_guard_tokens(alias))
    unmatched_tokens = {token for token in tokens if token not in allowed_tokens}
    if not unmatched_tokens:
        return False

    brand_supported = not brand or _text_matches_identity_value(
        brand,
        normalized_text=_normalize_profile_value(visible_text),
        glossary_terms=glossary_terms,
    )
    model_supported = not model or _text_matches_identity_value(
        model,
        normalized_text=_normalize_profile_value(visible_text),
        glossary_terms=glossary_terms,
    )
    if not brand_supported and any(re.fullmatch(r"[A-Z]{3,14}", token) for token in unmatched_tokens):
        return True
    if not model_supported and unmatched_tokens:
        return True
    if not brand_supported and not model_supported:
        return True
    return False


def _extract_confirmed_profile_fields(profile: dict[str, Any] | None) -> dict[str, Any]:
    feedback = (profile or {}).get("user_feedback")
    if not isinstance(feedback, dict):
        return {}

    confirmed: dict[str, Any] = {}
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
        value = str(feedback.get(key) or "").strip()
        if value:
            confirmed[key] = value

    manual_queries: list[str] = []
    for item in feedback.get("keywords") or []:
        value = str(item).strip()
        if value and value not in manual_queries:
            manual_queries.append(value)
    if manual_queries:
        confirmed["search_queries"] = manual_queries

    return confirmed


def _apply_confirmed_profile_fields(profile: dict[str, Any], confirmed_fields: dict[str, Any]) -> None:
    if not confirmed_fields:
        return
    for key, value in confirmed_fields.items():
        if key == "search_queries":
            profile[key] = list(value)
        else:
            profile[key] = value


async def infer_content_profile(
    *,
    source_path: Path,
    source_name: str,
    subtitle_items: list[dict],
    transcript_items: list[dict[str, Any]] | None = None,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    user_memory: dict[str, Any] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    include_research: bool = True,
    copy_style: str = "attention_grabbing",
    source_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    transcript_excerpt = build_transcript_excerpt(list(transcript_items or subtitle_items))
    initial_profile: dict[str, Any] = {
        "copy_style": str(copy_style or "attention_grabbing").strip() or "attention_grabbing",
    }
    settings = get_settings()
    visual_hints: dict[str, Any] = {}
    visual_semantic_evidence: dict[str, Any] = {}

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = _extract_reference_frames(source_path, Path(tmpdir), count=3)
            if bool(getattr(settings, "ocr_enabled", False)):
                ocr_profile = await _collect_content_profile_ocr(frame_paths, source_name=source_name)
                if ocr_profile:
                    initial_profile["ocr_profile"] = ocr_profile
                    if ocr_profile.get("visible_text") and not str(initial_profile.get("visible_text") or "").strip():
                        initial_profile["visible_text"] = str(ocr_profile.get("visible_text") or "").strip()
            capabilities = resolve_content_understanding_capabilities(
                reasoning_provider=str(settings.active_reasoning_provider or settings.reasoning_provider or "").strip(),
                visual_provider=str(settings.active_reasoning_provider or settings.reasoning_provider or "").strip(),
                visual_mcp_provider="",
            )
            visual_semantic_evidence = await infer_visual_semantic_evidence(frame_paths, capabilities)
            if visual_semantic_evidence:
                initial_profile["visual_semantic_evidence"] = dict(visual_semantic_evidence)
                visual_hints = _build_visual_hints_from_semantic_evidence(visual_semantic_evidence)
            if visual_hints:
                initial_profile["visual_hints"] = dict(visual_hints)
                initial_profile["visual_cluster_hints"] = dict(visual_hints)
    except Exception:
        pass

    evidence_bundle = build_evidence_bundle(
        source_name=source_name,
        subtitle_items=subtitle_items,
        transcript_excerpt=transcript_excerpt,
        visible_text=str(initial_profile.get("visible_text") or "").strip(),
        ocr_profile=initial_profile.get("ocr_profile") if isinstance(initial_profile.get("ocr_profile"), dict) else {},
        visual_semantic_evidence=visual_semantic_evidence,
        visual_hints=visual_hints,
        candidate_hints=_source_context_candidate_hints(source_context),
    )

    try:
        with track_usage_operation("content_profile.universal_infer"):
            understanding = await infer_content_understanding(evidence_bundle)
        force_neutral_cover_title = False
    except Exception:
        understanding = _build_failed_content_understanding(
            transcript_excerpt=transcript_excerpt,
            failure_reason="内容理解推断失败",
        )
        force_neutral_cover_title = True

    verification_queries = build_verification_search_queries(understanding)
    if include_research and verification_queries:
        try:
            async with get_session_factory()() as session:
                verification_bundle = await build_hybrid_verification_bundle(
                    search_queries=verification_queries,
                    online_search=_online_search_content_understanding,
                    internal_search=None,
                    session=session,
                    subject_domain=understanding.content_domain,
                    evidence_texts=_collect_verification_evidence_texts(
                        evidence_bundle,
                        source_name=source_name,
                        transcript_excerpt=transcript_excerpt,
                        visible_text=str(initial_profile.get("visible_text") or "").strip(),
                    ),
                    glossary_terms=glossary_terms,
                    confirmed_entities=list((user_memory or {}).get("confirmed_entities") or []),
                )
                with track_usage_operation("content_profile.universal_verify"):
                    understanding = await verify_content_understanding(
                        understanding=understanding,
                        evidence_bundle=evidence_bundle,
                        verification_bundle=verification_bundle,
                    )
                initial_profile["verification_evidence"] = _build_profile_verification_snapshot(verification_bundle)
        except Exception:
            pass

    profile = map_content_understanding_to_legacy_profile(understanding)
    profile["content_understanding"] = profile.get("content_understanding") or {}
    profile["transcript_excerpt"] = transcript_excerpt
    profile["workflow_template"] = str(workflow_template or "").strip()
    profile["copy_style"] = str(copy_style or "attention_grabbing").strip() or "attention_grabbing"
    _ensure_subject_type_main(profile)
    if initial_profile.get("ocr_profile"):
        profile["ocr_profile"] = dict(initial_profile.get("ocr_profile") or {})
    if initial_profile.get("visible_text") and not profile.get("visible_text"):
        profile["visible_text"] = str(initial_profile.get("visible_text") or "").strip()
    if visual_hints:
        profile["visual_hints"] = dict(visual_hints)
        profile["visual_cluster_hints"] = dict(visual_hints)
    if visual_semantic_evidence:
        profile["visual_semantic_evidence"] = dict(visual_semantic_evidence)
    if initial_profile.get("verification_evidence"):
        profile["verification_evidence"] = dict(initial_profile.get("verification_evidence") or {})
    normalized_source_context = _normalize_source_context_payload(source_context)
    if normalized_source_context:
        profile["source_context"] = normalized_source_context
    profile = apply_source_identity_constraints(
        profile,
        source_name=source_name,
        transcript_excerpt=transcript_excerpt,
    )
    profile = _prefer_content_understanding_video_theme(
        profile,
        transcript_excerpt=transcript_excerpt,
    )
    profile = _prefer_content_understanding_summary(profile)
    _ensure_search_queries(profile, source_name, transcript_excerpt=transcript_excerpt)
    _ensure_review_fields_not_empty(profile, source_name=source_name, transcript_excerpt=transcript_excerpt)
    profile["keywords"] = _build_review_keywords(profile)

    preset = select_workflow_template(
        workflow_template=workflow_template,
        content_kind=str(profile.get("content_kind") or "").strip(),
        subject_domain=str(profile.get("subject_domain") or "").strip(),
        subject_model=str(profile.get("subject_model") or "").strip(),
        subject_type=str(profile.get("subject_type") or "").strip(),
        transcript_hint=transcript_excerpt,
    )
    if not str(profile.get("summary") or "").strip():
        profile["summary"] = _build_profile_summary(profile)
    if not str(profile.get("engagement_question") or "").strip():
        profile["engagement_question"] = _default_engagement_question(preset)
    profile["cover_title"] = build_cover_title(profile, preset)
    if force_neutral_cover_title:
        profile["cover_title"] = {
            "top": "",
            "main": "内容待确认",
            "bottom": "",
        }
    return profile


def _build_failed_content_understanding(*, transcript_excerpt: str, failure_reason: str) -> ContentUnderstanding:
    summary = _build_neutral_profile_summary()
    return ContentUnderstanding(
        video_type="",
        content_domain="",
        primary_subject="",
        subject_entities=[],
        video_theme="",
        summary=summary,
        hook_line="内容待人工确认",
        engagement_question="这条视频主要在讲什么？",
        search_queries=[],
        evidence_spans=[],
        uncertainties=[str(failure_reason or "内容理解暂不可用").strip()],
        confidence={},
        needs_review=True,
        review_reasons=[str(failure_reason or "内容理解暂不可用").strip()],
    )


def _collect_verification_evidence_texts(
    evidence_bundle: dict[str, Any] | None,
    *,
    source_name: str = "",
    transcript_excerpt: str = "",
    visible_text: str = "",
) -> list[str]:
    fragments: list[str] = []

    def _remember(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in fragments:
            fragments.append(text)

    _remember(source_name)
    _remember(transcript_excerpt)
    _remember(visible_text)
    bundle = evidence_bundle or {}
    for key in (
        "transcript_excerpt",
        "visible_text",
        "source_name",
        "matched_subtitle_snippets",
        "matched_source_name_terms",
        "matched_visible_text_terms",
        "matched_ocr_terms",
        "matched_evidence_terms",
    ):
        value = bundle.get(key)
        if isinstance(value, list):
            for item in value[:16]:
                _remember(item)
            continue
        _remember(value)
    ocr_profile = bundle.get("ocr_profile")
    if isinstance(ocr_profile, dict):
        _remember(ocr_profile.get("visible_text"))
        for line in list(ocr_profile.get("lines") or [])[:12]:
            if isinstance(line, dict):
                _remember(line.get("text"))
            else:
                _remember(line)
    return fragments[:18]


def _build_profile_verification_snapshot(
    verification_bundle: HybridVerificationBundle | None,
) -> dict[str, Any]:
    if verification_bundle is None:
        return {}

    online_results: list[dict[str, Any]] = []
    for item in list(verification_bundle.online_results or [])[:4]:
        if isinstance(item, dict):
            normalized = {
                "query": str(item.get("query") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "snippet": str(item.get("snippet") or "").strip(),
                "url": str(item.get("url") or "").strip(),
            }
        else:
            normalized = {"value": str(item)}
        if any(normalized.values()):
            online_results.append(normalized)

    database_results: list[dict[str, Any]] = []
    for item in list(verification_bundle.database_results or [])[:4]:
        if isinstance(item, dict):
            normalized = {
                "brand": str(item.get("brand") or "").strip(),
                "model": str(item.get("model") or "").strip(),
                "primary_subject": str(item.get("primary_subject") or "").strip(),
                "subject_type": str(item.get("subject_type") or "").strip(),
                "source_type": str(item.get("source_type") or "").strip(),
            }
        else:
            normalized = {"value": str(item)}
        if any(normalized.values()):
            database_results.append(normalized)

    entity_catalog_candidates: list[dict[str, Any]] = []
    for item in list(verification_bundle.entity_catalog_candidates or [])[:5]:
        if isinstance(item, dict):
            normalized = {
                "brand": str(item.get("brand") or "").strip(),
                "model": str(item.get("model") or "").strip(),
                "primary_subject": str(item.get("primary_subject") or "").strip(),
                "subject_type": str(item.get("subject_type") or "").strip(),
                "subject_domain": str(item.get("subject_domain") or "").strip(),
                "source_type": str(item.get("source_type") or "").strip(),
                "source_origins": [str(value).strip() for value in list(item.get("source_origins") or []) if str(value).strip()],
                "matched_fields": [str(value).strip() for value in list(item.get("matched_fields") or []) if str(value).strip()],
                "matched_queries": [str(value).strip() for value in list(item.get("matched_queries") or []) if str(value).strip()],
                "matched_evidence_texts": [str(value).strip() for value in list(item.get("matched_evidence_texts") or []) if str(value).strip()],
                "matched_aliases": {
                    key: [str(value).strip() for value in list(values or []) if str(value).strip()]
                    for key, values in dict(item.get("matched_aliases") or {}).items()
                    if [str(value).strip() for value in list(values or []) if str(value).strip()]
                },
                "evidence_strength": str(item.get("evidence_strength") or "").strip(),
                "support_score": float(item.get("support_score") or 0.0),
                "confidence": float(item.get("confidence") or 0.0),
            }
        else:
            normalized = {"value": str(item)}
        if any(value for key, value in normalized.items() if key != "matched_aliases"):
            entity_catalog_candidates.append(normalized)

    return {
        "search_queries": [str(item).strip() for item in list(verification_bundle.search_queries or []) if str(item).strip()],
        "online_count": len(list(verification_bundle.online_results or [])),
        "database_count": len(list(verification_bundle.database_results or [])),
        "entity_catalog_count": len(list(verification_bundle.entity_catalog_candidates or [])),
        "online_results": online_results,
        "database_results": database_results,
        "entity_catalog_candidates": entity_catalog_candidates,
    }


def _select_verification_backfill_candidate(profile: dict[str, Any]) -> dict[str, Any] | None:
    snapshot = profile.get("verification_evidence")
    if not isinstance(snapshot, dict):
        return None
    candidates = [
        item
        for item in list(snapshot.get("entity_catalog_candidates") or [])
        if isinstance(item, dict)
    ]
    if not candidates:
        return None

    current_brand = str(profile.get("subject_brand") or "").strip()
    current_model = str(profile.get("subject_model") or "").strip()
    current_subject_type = str(profile.get("subject_type") or "").strip()
    current_subject_domain = str(profile.get("subject_domain") or "").strip() or _subject_domain_from_subject_type(current_subject_type)

    def _is_viable(item: dict[str, Any]) -> bool:
        support_score = float(item.get("support_score") or 0.0)
        evidence_strength = str(item.get("evidence_strength") or "").strip().lower()
        matched_evidence = [str(value).strip() for value in list(item.get("matched_evidence_texts") or []) if str(value).strip()]
        matched_fields = [str(value).strip() for value in list(item.get("matched_fields") or []) if str(value).strip()]
        return (
            support_score >= 0.7
            and evidence_strength in {"moderate", "strong"}
            and (
                matched_evidence
                or "video_evidence" in matched_fields
                or "brand_alias" in matched_fields
                or "model_alias" in matched_fields
                or "supporting_keyword" in matched_fields
            )
            and bool(str(item.get("brand") or "").strip() or str(item.get("model") or "").strip())
        )

    def _alignment_score(item: dict[str, Any]) -> int:
        score = 0
        candidate_brand = str(item.get("brand") or "").strip()
        candidate_model = str(item.get("model") or "").strip()
        candidate_subject_type = str(item.get("subject_type") or "").strip()
        candidate_domain = str(item.get("subject_domain") or "").strip() or _subject_domain_from_subject_type(candidate_subject_type)

        if current_model and candidate_model:
            if _identity_values_compatible(current_model, candidate_model):
                score += 6
            else:
                score -= 3
        if current_brand and candidate_brand:
            if _identity_values_compatible(current_brand, candidate_brand):
                score += 4
            else:
                score -= 2
        mapped_brand = _mapped_brand_for_model(current_model or candidate_model)
        effective_brand = current_brand or candidate_brand
        if mapped_brand and effective_brand and _identity_values_compatible(mapped_brand, effective_brand):
            score += 2
        if current_subject_domain and candidate_domain:
            if current_subject_domain == candidate_domain:
                score += 2
            else:
                score -= 1
        if current_subject_type and candidate_subject_type:
            if _normalize_profile_value(current_subject_type) == _normalize_profile_value(candidate_subject_type):
                score += 2
            elif current_model and _text_conflicts_with_verified_identity(
                current_subject_type,
                brand=candidate_brand or current_brand,
                model=candidate_model or current_model,
                glossary_terms=None,
            ):
                score -= 2
        return score

    viable = [item for item in candidates if _is_viable(item)]
    if not viable:
        return None
    viable.sort(
        key=lambda item: (
            -_alignment_score(item),
            -float(item.get("support_score") or 0.0),
            -float(item.get("confidence") or 0.0),
            0 if str(item.get("source_type") or "").strip() == "builtin_entity_catalog" else 1,
            -len(str(item.get("model") or "").strip()),
            -len(str(item.get("subject_type") or "").strip()),
            -(len(item.get("matched_evidence_texts") or [])),
        )
    )
    return dict(viable[0])


def _apply_verification_candidate_backfill(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    guarded = dict(profile or {})
    candidate = _select_verification_backfill_candidate(guarded)
    if not candidate:
        return guarded

    candidate_brand = str(candidate.get("brand") or "").strip()
    candidate_model = str(candidate.get("model") or "").strip()
    candidate_subject_type = str(candidate.get("subject_type") or "").strip()
    current_brand = str(guarded.get("subject_brand") or "").strip()
    current_model = str(guarded.get("subject_model") or "").strip()
    effective_model = current_model or candidate_model
    mapped_brand = _mapped_brand_for_model(effective_model)
    allow_brand_override = bool(
        current_brand
        and candidate_brand
        and effective_model
        and _identity_values_compatible(effective_model, candidate_model or effective_model)
        and mapped_brand
        and _identity_values_compatible(mapped_brand, candidate_brand)
        and not _identity_values_compatible(mapped_brand, current_brand)
    )
    if current_brand and candidate_brand and not _identity_values_compatible(current_brand, candidate_brand) and not allow_brand_override:
        return guarded
    if current_model and candidate_model and not _identity_values_compatible(current_model, candidate_model):
        return guarded

    backfilled_fields: list[str] = []
    effective_brand = current_brand or candidate_brand
    resolved_candidate_brand = candidate_brand or mapped_brand
    if (not current_brand or allow_brand_override) and resolved_candidate_brand:
        guarded["subject_brand"] = resolved_candidate_brand
        backfilled_fields.append("subject_brand")
    if not current_model and candidate_model:
        guarded["subject_model"] = candidate_model
        backfilled_fields.append("subject_model")
    effective_brand = str(guarded.get("subject_brand") or "").strip()
    effective_model = str(guarded.get("subject_model") or "").strip()

    current_subject_type = str(guarded.get("subject_type") or "").strip()
    current_subject_type_lacks_identity = bool(current_subject_type) and not any(
        _text_matches_identity_value(
            value,
            normalized_text=_normalize_profile_value(current_subject_type),
            glossary_terms=glossary_terms,
        )
        for value in (effective_brand, effective_model)
        if value
    )
    if candidate_subject_type and (
        not current_subject_type
        or _is_generic_subject_type(current_subject_type)
        or current_subject_type_lacks_identity
        or _text_conflicts_with_verified_identity(
            current_subject_type,
            brand=effective_brand,
            model=effective_model,
            glossary_terms=glossary_terms,
        )
    ):
        guarded["subject_type"] = candidate_subject_type
        backfilled_fields.append("subject_type")

    if backfilled_fields:
        verification_gate = dict(guarded.get("verification_gate") or {}) if isinstance(guarded.get("verification_gate"), dict) else {}
        verification_gate["backfilled_fields"] = list(dict.fromkeys([*list(verification_gate.get("backfilled_fields") or []), *backfilled_fields]))
        verification_gate["backfill_candidate"] = candidate
        guarded["verification_gate"] = verification_gate

    summary = str(guarded.get("summary") or "").strip()
    if not summary or _is_generic_profile_summary(summary) or not any(
        _text_matches_identity_value(
            value,
            normalized_text=_normalize_profile_value(summary),
            glossary_terms=glossary_terms,
        )
        for value in (
            str(guarded.get("subject_brand") or "").strip(),
            str(guarded.get("subject_model") or "").strip(),
        )
        if value
    ):
        guarded["summary"] = _build_profile_summary(guarded)
    current_video_theme = str(guarded.get("video_theme") or "").strip()
    if (
        not current_video_theme
        or not _is_specific_video_theme_for_context(
            current_video_theme,
            preset_name=_workflow_template_name(guarded),
            content_kind=_content_kind_name(guarded),
            subject_domain=str(guarded.get("subject_domain") or ""),
        )
        or _text_conflicts_with_verified_identity(
            current_video_theme,
            brand=str(guarded.get("subject_brand") or "").strip(),
            model=str(guarded.get("subject_model") or "").strip(),
            glossary_terms=glossary_terms,
        )
    ):
        rebuilt_theme = _build_identity_driven_video_theme(guarded, transcript_excerpt=transcript_excerpt)
        if rebuilt_theme:
            guarded["video_theme"] = rebuilt_theme

    _ensure_search_queries(guarded, source_name, transcript_excerpt=transcript_excerpt)
    return guarded


async def _online_search_content_understanding(*, search_queries: list[str]) -> list[dict[str, Any]]:
    try:
        provider = get_search_provider()
    except Exception:
        return []
    results: list[dict[str, Any]] = []
    for query in search_queries[:4]:
        for item in await provider.search(query):
            results.append(
                {
                    "query": query,
                    "title": str(getattr(item, "title", "") or ""),
                    "url": str(getattr(item, "url", "") or ""),
                    "snippet": str(getattr(item, "snippet", "") or ""),
                    "score": float(getattr(item, "score", 0.0) or 0.0),
                }
            )
    return results


async def _collect_content_profile_ocr(frame_paths: list[Path], *, source_name: str) -> dict[str, Any]:
    if not frame_paths:
        return {}
    try:
        provider = get_ocr_provider()
        result = await provider.recognize_frames(frame_paths, language="zh-CN")
    except Exception:
        return {}

    profile = build_content_profile_ocr(result.frames, source_name=source_name)
    profile["provider"] = str(result.provider or "").strip()
    profile["available"] = bool(result.available) and bool(profile.get("line_count"))
    profile["status"] = str(result.status or profile.get("status") or ("ok" if profile.get("line_count") else "empty")).strip()
    if result.reason:
        profile["reason"] = str(result.reason).strip()
    if result.metadata:
        profile["metadata"] = dict(result.metadata)
    return profile


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
    return await _apply_content_profile_feedback_public(
        draft_profile=draft_profile,
        source_name=source_name,
        workflow_template=workflow_template,
        channel_profile=channel_profile,
        user_feedback=user_feedback,
        reviewed_subtitle_excerpt=reviewed_subtitle_excerpt,
        accepted_corrections=accepted_corrections,
        skip_model_refinement=skip_model_refinement,
    )


def build_review_feedback_search_queries(
    *,
    draft_profile: dict[str, Any],
    proposed_feedback: dict[str, Any] | None = None,
    source_name: str | None = None,
    limit: int = 6,
) -> list[str]:
    return _build_review_feedback_search_queries_public(
        draft_profile=draft_profile,
        proposed_feedback=proposed_feedback,
        source_name=source_name,
        limit=limit,
    )


async def build_review_feedback_verification_bundle(
    *,
    draft_profile: dict[str, Any],
    proposed_feedback: dict[str, Any] | None = None,
    session: AsyncSession | None = None,
) -> HybridVerificationBundle | None:
    return await _build_review_feedback_verification_bundle_public(
        draft_profile=draft_profile,
        proposed_feedback=proposed_feedback,
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
    return await _resolve_content_profile_review_feedback_public(
        draft_profile=draft_profile,
        source_name=source_name,
        review_feedback=review_feedback,
        proposed_feedback=proposed_feedback,
        reviewed_subtitle_excerpt=reviewed_subtitle_excerpt,
        accepted_corrections=accepted_corrections,
        verification_bundle=verification_bundle,
    )


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


def _build_review_feedback_verification_snapshot(
    verification_bundle: HybridVerificationBundle | None,
) -> dict[str, Any]:
    return _build_review_feedback_verification_snapshot_public(verification_bundle)


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


def _normalize_review_feedback_match_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return re.sub(r"[\s\-_/·.]+", "", text)


def _profile_needs_text_refinement(profile: dict[str, Any] | None) -> bool:
    candidate = profile or {}
    subject_type = str(candidate.get("subject_type") or "").strip()
    video_theme = str(candidate.get("video_theme") or "").strip()
    engagement_question = str(candidate.get("engagement_question") or "").strip()
    preset_name = _workflow_template_name(candidate)

    if not subject_type or _is_generic_subject_type(subject_type):
        return True
    if not _is_specific_video_theme(video_theme, preset_name=preset_name):
        return True
    if _is_generic_engagement_question(engagement_question):
        return True
    if not preset_name:
        return True

    visible_text = str(candidate.get("visible_text") or "").strip()
    subject_brand = str(candidate.get("subject_brand") or "").strip()
    subject_model = str(candidate.get("subject_model") or "").strip()
    if not any((visible_text, subject_brand, subject_model)):
        return True
    return False


async def enrich_content_profile(
    *,
    profile: dict[str, Any],
    source_name: str,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    transcript_excerpt: str,
    subtitle_items: list[dict[str, Any]] | None = None,
    transcript_items: list[dict[str, Any]] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    include_research: bool = True,
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    enriched = dict(profile or {})
    transcript_items = transcript_items or []
    transcript_text = build_transcript_excerpt(transcript_items, max_items=120, max_chars=6000) if transcript_items else ""
    confirmed_fields = _extract_confirmed_profile_fields(enriched)
    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    memory_hints = _seed_profile_from_user_memory(
        transcript_excerpt,
        user_memory,
        subject_domain=str(enriched.get("subject_domain") or "").strip(),
    )
    enriched = _sanitize_profile_identity(
        enriched,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        memory_hints=memory_hints,
        user_memory=user_memory,
        allow_subject_type_inference=False,
        allow_video_theme_inference=False,
    )
    inferred_subject_domain = str(enriched.get("subject_domain") or "").strip()
    if not inferred_subject_domain:
        inferred_subject_domain = _infer_subject_domain_from_content(
            profile=enriched,
            transcript_excerpt=transcript_excerpt,
            source_name=source_name,
        )
        if inferred_subject_domain:
            enriched["subject_domain"] = inferred_subject_domain
    context_hints = _seed_profile_from_context(
        enriched,
        transcript_excerpt,
        glossary_terms=glossary_terms,
        subject_domain=inferred_subject_domain or str(enriched.get("subject_domain") or "").strip(),
    )
    memory_prompt = summarize_content_profile_user_memory(user_memory)
    _merge_specific_profile_hints(enriched, _identity_only_profile_hints(context_hints))
    _merge_specific_profile_hints(enriched, _identity_only_profile_hints(memory_hints))

    if not str(enriched.get("content_kind") or "").strip():
        template_hint = get_workflow_preset(workflow_template)
        enriched["content_kind"] = template_hint.content_kind
    if not str(enriched.get("subject_domain") or "").strip():
        inferred_subject_domain = _infer_subject_domain_from_content(
            profile=enriched,
            transcript_excerpt=transcript_excerpt,
            source_name=source_name,
        )
        if inferred_subject_domain:
            enriched["subject_domain"] = inferred_subject_domain

    llm_understanding = await _infer_content_understanding_for_enrich(
        profile=enriched,
        source_name=source_name,
        transcript_excerpt=transcript_excerpt,
        include_research=include_research,
    )
    if llm_understanding is not None:
        llm_profile = map_content_understanding_to_legacy_profile(llm_understanding)
        for key in (
            "content_kind",
            "subject_domain",
            "subject_brand",
            "subject_model",
            "subject_type",
            "video_theme",
            "summary",
            "hook_line",
            "engagement_question",
            "search_queries",
        ):
            if key in llm_profile and llm_profile.get(key):
                if key == "subject_type":
                    current_subject_type = str(enriched.get("subject_type") or "").strip()
                    if current_subject_type and not _is_generic_subject_type(current_subject_type):
                        continue
                enriched[key] = llm_profile[key]
        enriched["content_understanding"] = llm_profile.get("content_understanding") or {}
    if not str(enriched.get("subject_type") or "").strip():
        _ensure_subject_type_main(enriched)

    preset = select_workflow_template(
        workflow_template=workflow_template or enriched.get("workflow_template"),
        content_kind=_content_kind_name(enriched),
        subject_domain=str(enriched.get("subject_domain") or ""),
        subject_model=str(enriched.get("subject_model", "")),
        subject_type=str(enriched.get("subject_type", "")),
        transcript_hint=transcript_excerpt,
    )
    enriched["workflow_template"] = preset.name
    enriched["preset"] = preset.to_dict()
    enriched["transcript_excerpt"] = transcript_excerpt
    enriched = _sanitize_profile_identity(
        enriched,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        memory_hints=memory_hints,
        user_memory=user_memory,
        allow_subject_type_inference=False,
        allow_video_theme_inference=False,
    )

    evidence: list[dict[str, Any]] = []
    review_payload_fields: set[str] = set()
    if include_research:
        evidence = await _search_evidence(enriched, source_name, transcript_excerpt=transcript_excerpt)
        evidence = _filter_evidence_by_visual_subject(
            evidence,
            visual_subject_type=str((_profile_visual_cluster_hints(enriched).get("subject_type") or "")),
        )
        if evidence:
            enriched["evidence"] = evidence
            try:
                provider = get_reasoning_provider()
                prompt = (
                    "你在做短视频字幕与封面前置研究。请把字幕/画面线索与搜索证据做双重校验，"
                    "确认视频主体品牌、型号/版本、主体类型、视频主题，并生成适合做封面的三段标题。"
                    "如果是软件/AI/科技视频，必须锁定软件名和功能名，封面标题不能再写成“软件工具”“功能演示”这种泛词。"
                    "同时生成一个适合评论区互动的问题，要具体、自然、贴合内容，不要反复使用同一句泛化问题。"
                    "只有当字幕/画面线索与搜索结果能够互相印证时，才提升品牌、型号等关键信息。"
                    "如果搜索结果与字幕线索冲突，优先保守，保留已有可信字段，不要为了补全而乱改。"
                    "优先给出品牌名、系列名或主体名，不要输出泛化标题如“产品开箱与上手体验”。"
                    "subject_brand 指视频主体品牌，不是频道名；不要把文件名、时间戳或相机编号当成型号。"
                    "如果证据不足，不要编造，保留已有可信信息。\n\n"
                    "输出 JSON："
                    '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
                    '"hook_line":"","visible_text":"","summary":"","engagement_question":"",'
                    '"cover_title":{"top":"","main":"","bottom":""}}'
                    f"\n视觉一致簇（当前画面主体验证结果，优先级高于脏字幕和错误搜索）：{json.dumps(_visual_cluster_prompt_payload(enriched), ensure_ascii=False)}"
                    f"\n已有判断：{json.dumps(enriched, ensure_ascii=False)}"
                    f"\n用户历史偏好（仅作辅助参考，不能压过当前字幕和画面）：\n{memory_prompt or '无'}"
                    f"\n字幕/画面线索：{transcript_excerpt}"
                    f"\n搜索证据：{json.dumps(evidence, ensure_ascii=False)}"
                )
                with track_usage_operation("content_profile.research_refine"):
                    response = await provider.complete(
                        [
                            Message(role="system", content="你是中文短视频内容策划与字幕审校助手。"),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.1,
                        max_tokens=700,
                        json_mode=True,
                    )
                refined = response.as_json()
                enriched.update({k: v for k, v in refined.items() if v})
                _merge_specific_profile_hints(enriched, _identity_only_profile_hints(context_hints))
                _merge_specific_profile_hints(enriched, _identity_only_profile_hints(memory_hints))
                enriched = _sanitize_profile_identity(
                    enriched,
                    transcript_excerpt=transcript_excerpt,
                    source_name=source_name,
                    glossary_terms=glossary_terms,
                    memory_hints=memory_hints,
                    user_memory=user_memory,
                    allow_subject_type_inference=False,
                    allow_video_theme_inference=False,
                )
            except Exception:
                pass

        try:
            review_payload = await _generate_llm_review_page_payload(
                profile=enriched,
                source_name=source_name,
                transcript_excerpt=transcript_excerpt,
                transcript_text=transcript_text or build_transcript_for_packaging(subtitle_items or [], max_chars=6000) or transcript_excerpt,
                evidence=evidence,
            )
            video_type = normalize_video_type(str(review_payload.get("video_type") or "").strip())
            if video_type and "video_type" not in confirmed_fields:
                enriched["video_type"] = video_type
                review_payload_fields.add("video_type")
            for key in (
                "video_theme",
                "hook_line",
                "summary",
                "engagement_question",
                "correction_notes",
                "supplemental_context",
            ):
                value = str(review_payload.get(key) or "").strip()
                if value and key not in confirmed_fields:
                    enriched[key] = value
                    review_payload_fields.add(key)
            if review_payload.get("search_queries") and "search_queries" not in confirmed_fields:
                enriched["search_queries"] = list(review_payload.get("search_queries") or [])
                review_payload_fields.add("search_queries")
            if review_payload.get("keywords"):
                enriched["keywords"] = list(review_payload.get("keywords") or [])
                review_payload_fields.add("keywords")
        except Exception:
            pass

    _apply_confirmed_profile_fields(enriched, confirmed_fields)

    if "hook_line" not in confirmed_fields and "hook_line" not in review_payload_fields:
        current_hook = str(enriched.get("hook_line") or "").strip()
        if not current_hook or _is_generic_cover_line(current_hook):
            enriched["hook_line"] = _build_cover_hook(
                hook=current_hook,
                brand=_clean_line(enriched.get("subject_brand") or enriched.get("brand") or ""),
                model=_clean_line(enriched.get("subject_model") or enriched.get("model") or ""),
                subject_type=_clean_line(enriched.get("subject_type") or ""),
                theme=_clean_line(str(enriched.get("video_theme") or "").strip()),
                transcript_excerpt=transcript_excerpt,
                copy_style=str(enriched.get("copy_style") or "attention_grabbing").strip() or "attention_grabbing",
                preset=preset,
            )

    cover_title = enriched.get("cover_title")
    if not isinstance(cover_title, dict) or not _cover_title_is_usable(cover_title):
        cover_title = build_cover_title(enriched, preset)
    else:
        cover_title = {
            "top": _clean_line(cover_title.get("top") or "")[:14],
            "main": _clean_line(cover_title.get("main") or "")[:18],
            "bottom": _clean_line(cover_title.get("bottom") or "")[:18],
        }
    enriched["cover_title"] = cover_title
    if "summary" not in review_payload_fields and (
        not enriched.get("summary") or _is_generic_profile_summary(str(enriched.get("summary") or ""))
    ):
        enriched["summary"] = _build_profile_summary(enriched)
    if "engagement_question" not in review_payload_fields and _is_generic_engagement_question(str(enriched.get("engagement_question") or "")):
        generated_question = await _generate_engagement_question(
            profile=enriched,
            transcript_excerpt=transcript_excerpt,
            evidence=enriched.get("evidence") or [],
            preset=preset,
            memory_prompt=memory_prompt,
        )
        if generated_question:
            enriched["engagement_question"] = generated_question
    if "engagement_question" not in review_payload_fields and _is_generic_engagement_question(str(enriched.get("engagement_question") or "")):
        enriched["engagement_question"] = _build_fallback_engagement_question(enriched, preset)
    if not str(enriched.get("subject_type") or "").strip():
        _ensure_subject_type_main(enriched)
    if isinstance(enriched.get("verification_evidence"), dict) or isinstance(enriched.get("content_understanding"), dict):
        enriched = apply_identity_review_guard(
            enriched,
            subtitle_items=subtitle_items,
            user_memory=user_memory,
            glossary_terms=glossary_terms,
            source_name=source_name,
        )
    enriched = apply_source_identity_constraints(
        enriched,
        source_name=source_name,
        transcript_excerpt=transcript_excerpt,
    )
    enriched = _prefer_content_understanding_video_theme(
        enriched,
        transcript_excerpt=transcript_excerpt,
        confirmed_fields=confirmed_fields,
    )
    enriched = _prefer_content_understanding_summary(
        enriched,
        confirmed_fields=confirmed_fields,
        allow_override="summary" not in review_payload_fields,
    )
    _ensure_search_queries(enriched, source_name, transcript_excerpt=transcript_excerpt)
    if not list(enriched.get("keywords") or []):
        enriched["keywords"] = _build_review_keywords(enriched)
    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    if confirmed_fields and any(
        key in confirmed_fields
        for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "hook_line", "visible_text")
    ):
        enriched["cover_title"] = build_cover_title(enriched, preset)
    _ensure_review_fields_not_empty(enriched, source_name=source_name, transcript_excerpt=transcript_excerpt)
    return enriched


async def _infer_content_understanding_for_enrich(
    *,
    profile: dict[str, Any],
    source_name: str,
    transcript_excerpt: str,
    include_research: bool,
) -> Any | None:
    evidence_bundle = build_evidence_bundle(
        source_name=source_name,
        subtitle_items=[],
        transcript_excerpt=transcript_excerpt,
        visible_text=str(profile.get("visible_text") or "").strip(),
        ocr_profile=_enrich_ocr_profile(profile),
        visual_semantic_evidence=dict(profile.get("visual_semantic_evidence") or {})
        if isinstance(profile.get("visual_semantic_evidence"), dict)
        else {},
        visual_hints=_profile_visual_cluster_hints(profile),
        candidate_hints=_enrich_candidate_hints(profile),
    )
    try:
        with track_usage_operation("content_profile.enrich_universal_infer"):
            understanding = await infer_content_understanding(evidence_bundle)
    except Exception:
        return None

    verification_queries = build_verification_search_queries(understanding)
    if include_research and verification_queries:
        try:
            async with get_session_factory()() as session:
                verification_bundle = await build_hybrid_verification_bundle(
                    search_queries=verification_queries,
                    online_search=_online_search_content_understanding,
                    internal_search=None,
                    session=session,
                    subject_domain=understanding.content_domain,
                    evidence_texts=_collect_verification_evidence_texts(
                        evidence_bundle,
                        source_name=source_name,
                        transcript_excerpt=transcript_excerpt,
                        visible_text=str(profile.get("visible_text") or "").strip(),
                    ),
                )
                with track_usage_operation("content_profile.enrich_universal_verify"):
                    understanding = await verify_content_understanding(
                        understanding=understanding,
                        evidence_bundle=evidence_bundle,
                        verification_bundle=verification_bundle,
                    )
                profile["verification_evidence"] = _build_profile_verification_snapshot(verification_bundle)
        except Exception:
            pass
    return understanding


def _enrich_ocr_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    candidate = profile or {}
    for key in ("ocr_profile", "ocr_evidence"):
        value = candidate.get(key)
        if isinstance(value, dict) and value:
            return dict(value)
    return {}


def _enrich_candidate_hints(profile: dict[str, Any] | None) -> dict[str, Any]:
    candidate = profile or {}
    search_queries = [str(item).strip() for item in (candidate.get("search_queries") or []) if str(item).strip()]
    hints = {
        "subject_brand": str(candidate.get("subject_brand") or "").strip(),
        "subject_model": str(candidate.get("subject_model") or "").strip(),
        "subject_type": str(candidate.get("subject_type") or "").strip(),
        "video_theme": str(candidate.get("video_theme") or "").strip(),
        "summary": str(candidate.get("summary") or "").strip(),
        "hook_line": str(candidate.get("hook_line") or "").strip(),
        "engagement_question": str(candidate.get("engagement_question") or "").strip(),
        "search_queries": search_queries,
        "visual_hints": _profile_visual_cluster_hints(candidate),
    }
    source_context = _normalize_source_context_payload(candidate.get("source_context"))
    if source_context:
        hints["source_context"] = source_context
    return hints


def _source_context_candidate_hints(source_context: dict[str, Any] | None) -> dict[str, Any]:
    payload = _normalize_source_context_payload(source_context)
    if not payload:
        return {}
    hints: dict[str, Any] = {"source_context": payload}
    derived_hints = _build_source_context_derived_hints(payload)
    if derived_hints:
        if derived_hints.get("filename_entries"):
            hints["filename_entries"] = list(derived_hints.get("filename_entries") or [])
        if derived_hints.get("related_source_names") and not hints.get("related_source_names"):
            hints["related_source_names"] = list(derived_hints.get("related_source_names") or [])
        _merge_source_context_seed_hints(hints, derived_hints)
    resolved_feedback = dict(payload.get("resolved_feedback") or {}) if isinstance(payload.get("resolved_feedback"), dict) else {}
    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "summary",
        "hook_line",
        "visible_text",
        "engagement_question",
    ):
        text = str(resolved_feedback.get(key) or "").strip()
        if text:
            hints[key] = text
    search_queries = [str(item).strip() for item in (resolved_feedback.get("search_queries") or []) if str(item).strip()]
    if search_queries:
        hints["search_queries"] = search_queries[:6]
    related_profiles = [
        dict(item)
        for item in (payload.get("related_profiles") or [])
        if isinstance(item, dict)
    ]
    if related_profiles:
        def _related_profile_priority(item: dict[str, Any]) -> tuple[int, float]:
            review_mode = str(item.get("review_mode") or "").strip().lower()
            if bool(item.get("manual_confirmed")) or review_mode == "manual_confirmed":
                return (2, float(item.get("score") or 0.0))
            if review_mode == "auto_confirmed":
                return (1, float(item.get("score") or 0.0))
            return (0, float(item.get("score") or 0.0))

        related_profiles.sort(key=_related_profile_priority, reverse=True)
        primary = related_profiles[0]
        primary_score = float(primary.get("score") or 0.0)
        primary_priority = _related_profile_priority(primary)[0]
        primary_brand = _normalize_profile_value(primary.get("subject_brand"))
        primary_model = _normalize_profile_value(primary.get("subject_model"))
        conflicting_neighbor = False
        for candidate in related_profiles[1:]:
            candidate_score = float(candidate.get("score") or 0.0)
            if candidate_score < 0.75:
                continue
            if _related_profile_priority(candidate)[0] < primary_priority:
                continue
            candidate_brand = _normalize_profile_value(candidate.get("subject_brand"))
            candidate_model = _normalize_profile_value(candidate.get("subject_model"))
            if primary_brand and candidate_brand and primary_brand != candidate_brand:
                conflicting_neighbor = True
                break
            if primary_model and candidate_model and primary_model != candidate_model:
                conflicting_neighbor = True
                break
        if primary_score >= 0.82 and not conflicting_neighbor:
            hints["related_source_names"] = [
                str(item.get("source_name") or "").strip()
                for item in related_profiles
                if str(item.get("source_name") or "").strip()
            ][:3]
            for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary"):
                value = str(primary.get(key) or "").strip()
                if value and not str(hints.get(key) or "").strip():
                    hints[key] = value
            profile_queries = [
                str(item).strip()
                for item in (primary.get("search_queries") or [])
                if str(item).strip()
            ]
            if profile_queries and not hints.get("search_queries"):
                hints["search_queries"] = profile_queries[:6]
    return hints


async def _infer_visual_profile_hints(frame_paths: list[Path]) -> dict[str, Any]:
    if not frame_paths:
        return {}
    per_frame_hints: list[dict[str, Any]] = []
    for frame_path in frame_paths:
        hint = await _infer_visual_profile_hint_from_images([frame_path])
        if hint:
            per_frame_hints.append(hint)
    aggregated = _aggregate_visual_profile_hints(per_frame_hints)
    if aggregated:
        return aggregated
    return await _infer_visual_profile_hint_from_images(frame_paths)


async def _infer_visual_profile_hint_from_images(frame_paths: list[Path]) -> dict[str, Any]:
    if not frame_paths:
        return {}
    try:
        prompt = (
            "只看这组视频画面，不参考字幕。"
            "请判断画面里被重点展示或被手持操作的主体属于哪一类。"
            "优先在这些类型中选择：EDC折刀、多功能工具钳、EDC手电、EDC机能包、软件界面、人物口播、食品饮品、游戏画面、其他产品。"
            "如果画面里能直接看到型号、品牌字样，也提取出来。"
            "不要因为背景海报、桌垫、摆件或贴纸误判主体。"
            "输出 JSON："
            '{"subject_type":"","subject_brand":"","subject_model":"","visible_text":"","reason":""}'
        )
        with track_usage_operation("content_profile.visual_classify"):
            content = await complete_with_images(prompt, frame_paths, max_tokens=220, json_mode=True)
        data = json.loads(extract_json_text(content))
        subject_type = str(data.get("subject_type") or "").strip()
        subject_brand = str(data.get("subject_brand") or "").strip()
        subject_model = str(data.get("subject_model") or "").strip()
        visible_text = str(data.get("visible_text") or "").strip()
        if not visible_text:
            visible_text = " ".join(part for part in (subject_brand, subject_model) if part).strip()
        if not subject_type and not visible_text and not subject_brand and not subject_model:
            return {}
        hints = {
            "subject_type": subject_type,
            "visible_text": visible_text[:24],
            "reason": str(data.get("reason") or "").strip(),
        }
        if subject_brand:
            hints["subject_brand"] = subject_brand
        if subject_model:
            hints["subject_model"] = subject_model
        return hints
    except Exception:
        return {}


def _aggregate_visual_profile_hints(hints_list: list[dict[str, Any]]) -> dict[str, Any]:
    if not hints_list:
        return {}

    best_cluster_indexes = _select_visual_hint_cluster_indexes(hints_list)
    cluster_hints = [hints_list[index] for index in best_cluster_indexes] or hints_list

    def _pick_value(key: str) -> str:
        votes: dict[str, tuple[int, int, str]] = {}
        for index, hints in enumerate(cluster_hints):
            raw_value = str(hints.get(key) or "").strip()
            normalized = _normalize_profile_value(raw_value)
            if not normalized:
                continue
            score, first_index, canonical = votes.get(normalized, (0, -1, raw_value))
            score += 1
            if len(raw_value) > len(canonical):
                canonical = raw_value
            votes[normalized] = (score, index if first_index == -1 else first_index, canonical)
        if not votes:
            return ""
        _, _, value = max(votes.values(), key=lambda item: (item[0], len(item[2]), -item[1]))
        return value

    def _pick_visible_text_value(*, subject_brand: str, subject_model: str) -> str:
        votes: dict[str, tuple[int, int, int, str]] = {}
        for index, hints in enumerate(cluster_hints):
            raw_value = str(hints.get("visible_text") or "").strip()
            normalized = _normalize_profile_value(raw_value)
            if not normalized:
                continue
            score, first_index, support, canonical = votes.get(normalized, (0, -1, 0, raw_value))
            score += 1
            support += _visual_hint_visible_text_support_score(
                raw_value,
                subject_brand=subject_brand,
                subject_model=subject_model,
                hint_brand=str(hints.get("subject_brand") or "").strip(),
                hint_model=str(hints.get("subject_model") or "").strip(),
            )
            if len(raw_value) > len(canonical):
                canonical = raw_value
            votes[normalized] = (score, index if first_index == -1 else first_index, support, canonical)
        if not votes:
            return ""
        _, _, _, value = max(votes.values(), key=lambda item: (item[2], item[0], len(item[3]), -item[1]))
        return value

    subject_brand = _pick_value("subject_brand")
    subject_model = _pick_value("subject_model")
    subject_type = _pick_value("subject_type")
    visible_text = _pick_visible_text_value(subject_brand=subject_brand, subject_model=subject_model)
    if not visible_text:
        visible_text = " ".join(part for part in (subject_brand, subject_model) if part).strip()

    reasons = [
        str(hints.get("reason") or "").strip()
        for hints in hints_list
        if str(hints.get("reason") or "").strip()
    ]

    aggregated: dict[str, Any] = {}
    if subject_type:
        aggregated["subject_type"] = subject_type
    if subject_brand:
        aggregated["subject_brand"] = subject_brand
    if subject_model:
        aggregated["subject_model"] = subject_model
    if visible_text:
        aggregated["visible_text"] = visible_text[:24]
    if reasons:
        aggregated["reason"] = reasons[0]
    return aggregated


def _build_visual_hints_from_semantic_evidence(visual_semantic_evidence: dict[str, Any] | None) -> dict[str, Any]:
    evidence = dict(visual_semantic_evidence or {})
    subject_candidates = [str(item).strip() for item in list(evidence.get("subject_candidates") or []) if str(item).strip()]
    visible_brands = [str(item).strip() for item in list(evidence.get("visible_brands") or []) if str(item).strip()]
    visible_models = [str(item).strip() for item in list(evidence.get("visible_models") or []) if str(item).strip()]
    object_categories = [str(item).strip() for item in list(evidence.get("object_categories") or []) if str(item).strip()]
    evidence_notes = [str(item).strip() for item in list(evidence.get("evidence_notes") or []) if str(item).strip()]

    hints: dict[str, Any] = {}
    if subject_candidates:
        hints["subject_type"] = subject_candidates[0]
    elif object_categories:
        hints["subject_type"] = object_categories[0]
    if visible_brands:
        hints["subject_brand"] = visible_brands[0]
    if visible_models:
        hints["subject_model"] = visible_models[0]
    visible_text = " ".join(part for part in (visible_brands[:1] + visible_models[:1]) if part).strip()
    if visible_text:
        hints["visible_text"] = visible_text
    if evidence_notes:
        hints["reason"] = evidence_notes[0]
    return hints


def _select_visual_hint_cluster_indexes(hints_list: list[dict[str, Any]]) -> list[int]:
    best_indexes: list[int] = []
    best_signature: tuple[int, int, int, int, int] | None = None
    for index, anchor in enumerate(hints_list):
        cluster_indexes = [
            candidate_index
            for candidate_index, candidate in enumerate(hints_list)
            if _visual_hints_are_cluster_compatible(anchor, candidate)
        ]
        signature = _score_visual_hint_cluster(anchor, cluster_indexes=cluster_indexes, hints_list=hints_list)
        if best_signature is None or signature > best_signature:
            best_signature = signature
            best_indexes = cluster_indexes
    return best_indexes


def _score_visual_hint_cluster(
    anchor: dict[str, Any],
    *,
    cluster_indexes: list[int],
    hints_list: list[dict[str, Any]],
) -> tuple[int, int, int, int, int]:
    support_score = 0
    completeness = 0
    visible_support = 0
    anchor_completeness = 0

    anchor_brand = str(anchor.get("subject_brand") or "").strip()
    anchor_model = str(anchor.get("subject_model") or "").strip()
    anchor_type = str(anchor.get("subject_type") or "").strip()
    if anchor_brand:
        anchor_completeness += 1
    if anchor_model:
        anchor_completeness += 1
    if anchor_type:
        anchor_completeness += 1

    for index in cluster_indexes:
        hint = hints_list[index]
        hint_brand = str(hint.get("subject_brand") or "").strip()
        hint_model = str(hint.get("subject_model") or "").strip()
        hint_type = str(hint.get("subject_type") or "").strip()
        hint_visible_text = str(hint.get("visible_text") or "").strip()

        support_score += 1
        if hint_brand and anchor_brand and _normalize_profile_value(hint_brand) == _normalize_profile_value(anchor_brand):
            support_score += 2
        if hint_model and anchor_model and _normalize_profile_value(hint_model) == _normalize_profile_value(anchor_model):
            support_score += 2
        if hint_type and anchor_type and _normalize_profile_value(hint_type) == _normalize_profile_value(anchor_type):
            support_score += 1

        completeness += int(bool(hint_brand)) + int(bool(hint_model)) + int(bool(hint_type))
        visible_support += _visual_hint_visible_text_support_score(
            hint_visible_text,
            subject_brand=anchor_brand,
            subject_model=anchor_model,
            hint_brand=hint_brand,
            hint_model=hint_model,
        )

    return (support_score, anchor_completeness, completeness, visible_support, -min(cluster_indexes))


def _visual_hints_are_cluster_compatible(anchor: dict[str, Any], candidate: dict[str, Any]) -> bool:
    for key in ("subject_type", "subject_brand", "subject_model"):
        anchor_value = str(anchor.get(key) or "").strip()
        candidate_value = str(candidate.get(key) or "").strip()
        if anchor_value and candidate_value and _normalize_profile_value(anchor_value) != _normalize_profile_value(candidate_value):
            return False
    anchor_brand = str(anchor.get("subject_brand") or "").strip()
    anchor_model = str(anchor.get("subject_model") or "").strip()
    if not anchor_brand and not anchor_model:
        return True

    candidate_brand = str(candidate.get("subject_brand") or "").strip()
    candidate_model = str(candidate.get("subject_model") or "").strip()
    candidate_visible_text = str(candidate.get("visible_text") or "").strip()

    supports_anchor = False
    if anchor_brand and (
        (candidate_brand and _normalize_profile_value(candidate_brand) == _normalize_profile_value(anchor_brand))
        or _text_matches_identity_value(anchor_brand, normalized_text=_normalize_profile_value(candidate_visible_text), glossary_terms=None)
    ):
        supports_anchor = True
    if anchor_model and (
        (candidate_model and _normalize_profile_value(candidate_model) == _normalize_profile_value(anchor_model))
        or _text_matches_identity_value(anchor_model, normalized_text=_normalize_profile_value(candidate_visible_text), glossary_terms=None)
    ):
        supports_anchor = True
    return supports_anchor


def _visual_hint_visible_text_support_score(
    text: str,
    *,
    subject_brand: str,
    subject_model: str,
    hint_brand: str,
    hint_model: str,
) -> int:
    score = 0
    normalized_text = _normalize_profile_value(text)
    if not normalized_text:
        return score
    if subject_brand and _text_matches_identity_value(subject_brand, normalized_text=normalized_text, glossary_terms=None):
        score += 4
    if subject_model and _text_matches_identity_value(subject_model, normalized_text=normalized_text, glossary_terms=None):
        score += 4
    if hint_brand and subject_brand and _normalize_profile_value(hint_brand) == _normalize_profile_value(subject_brand):
        score += 2
    if hint_model and subject_model and _normalize_profile_value(hint_model) == _normalize_profile_value(subject_model):
        score += 2
    if hint_brand and subject_brand and _normalize_profile_value(hint_brand) != _normalize_profile_value(subject_brand):
        score -= 3
    if hint_model and subject_model and _normalize_profile_value(hint_model) != _normalize_profile_value(subject_model):
        score -= 3
    return score


def _subject_type_family(subject_type: str) -> str:
    normalized = _clean_line(subject_type)
    if not normalized:
        return ""
    if any(token in normalized for token in ("折刀", "刀具", "刀", "工具钳", "钳", "EDC", "战术")):
        return "edc"
    if any(token in normalized for token in ("灯具", "台灯", "灯", "照明")):
        return "lighting"
    if any(token in normalized for token in ("软件", "工作流", "界面", "AI", "智能体", "画布")):
        return "software"
    if any(token in normalized for token in ("口播", "解说", "人物")):
        return "talking_head"
    return "product"


def _apply_visual_subject_guard(profile: dict[str, Any]) -> None:
    visual_hints = _profile_visual_cluster_hints(profile)
    visual_subject_type = str(visual_hints.get("subject_type") or "").strip()
    if not visual_subject_type:
        current_subject_type = str(profile.get("subject_type") or "").strip()
    else:
        current_subject_type = str(profile.get("subject_type") or "").strip()
        visual_family = _subject_type_family(visual_subject_type)
        current_family = _subject_type_family(current_subject_type)
        if not current_subject_type or _is_generic_subject_type(current_subject_type):
            profile["subject_type"] = visual_subject_type
        elif visual_family and current_family and visual_family != current_family:
            profile["subject_type"] = visual_subject_type
    if visual_hints.get("subject_brand") and not profile.get("subject_brand"):
        profile["subject_brand"] = str(visual_hints.get("subject_brand") or "").strip()
    if visual_hints.get("subject_model") and not profile.get("subject_model"):
        profile["subject_model"] = str(visual_hints.get("subject_model") or "").strip()
    visible_text = str(visual_hints.get("visible_text") or "").strip()
    if visible_text and not profile.get("visible_text"):
        profile["visible_text"] = visible_text


def _filter_evidence_by_visual_subject(
    evidence: list[dict[str, str]],
    *,
    visual_subject_type: str,
) -> list[dict[str, str]]:
    visual_family = _subject_type_family(visual_subject_type)
    if not evidence or not visual_family:
        return evidence
    filtered: list[dict[str, str]] = []
    for item in evidence:
        text = " ".join(
            str(item.get(key) or "")
            for key in ("query", "title", "snippet")
        )
        family = _subject_type_family(text)
        if not family or family == "product" or family == visual_family:
            filtered.append(item)
    return filtered


async def polish_subtitle_items(
    subtitle_items,
    *,
    content_profile: dict[str, Any],
    glossary_terms: list[dict[str, Any]],
    review_memory: dict[str, Any] | None = None,
    chunk_size: int = 28,
    allow_llm: bool = True,
) -> int:
    provider = None
    if allow_llm:
        try:
            provider = get_reasoning_provider()
        except Exception:
            provider = None

    polished_count = 0
    preset = get_workflow_preset(_workflow_template_name(content_profile))
    evidence = content_profile.get("evidence") or []
    evidence_text = "\n".join(
        f"- {item.get('title', '')}: {item.get('snippet', '')}" for item in evidence[:6]
    )
    glossary_text = "\n".join(
        f"- {term.get('correct_form')}: 错写可能包括 {', '.join(term.get('wrong_forms') or [])}"
        for term in glossary_terms[:30]
    )
    review_memory_text = summarize_subtitle_review_memory_for_polish(review_memory)
    indexed_items = list(subtitle_items)

    for start in range(0, len(subtitle_items), chunk_size):
        chunk = subtitle_items[start:start + chunk_size]
        chunk_positions = {
            item.item_index: position
            for position, item in enumerate(chunk, start=start)
        }

        if provider is not None:
            try:
                payload_items = [
                    {
                        "index": item.item_index,
                        "start_time": item.start_time,
                        "end_time": item.end_time,
                        "prev_text": (
                            indexed_items[position - 1].text_final
                            or indexed_items[position - 1].text_norm
                            or indexed_items[position - 1].text_raw
                        ) if position > 0 else "",
                        "text": item.text_final or item.text_norm or item.text_raw,
                        "next_text": (
                            indexed_items[position + 1].text_final
                            or indexed_items[position + 1].text_norm
                            or indexed_items[position + 1].text_raw
                        ) if position + 1 < len(indexed_items) else "",
                    }
                    for position, item in enumerate(chunk, start=start)
                ]
                prompt = (
                    "你在精修中文短视频字幕。请根据视频主体、主题和搜索证据，"
                    "只做最小必要的字幕文本纠错。"
                    "要求：\n"
                    "1. 只允许修正 ASR 错字、同音词、品牌型号、行业术语和标点微调，不要做结构性重切分。\n"
                    "2. 禁止合并或拆分字幕条目，禁止总结、改写、扩写、缩写、换说法、重排信息，禁止添加没说过的品牌型号或参数。\n"
                    "3. 如果原句基本可用，就保持原句，只修正错别字或明显标点即可，不要把未说完的碎片补成完整句。\n"
                    "4. 结合 prev_text / next_text 只做邻句消歧，不要借邻句重写本句，也不要用邻句补结构。\n"
                    "5. 单条输出必须和原句表达同一件事，禁止写成标题、摘要、卖点文案。\n"
                    "6. 优先保证品牌、型号、版本名、EDC/工具钳相关术语正确。\n"
                    "7. 数字写法按展示语境润色：字母+数字组合、日期时间、型号规格、版本代号、价格、档位、序号优先用阿拉伯数字；"
                    "自然口语数量词和模糊词组优先用中文数字，例如“一个”“一次”“两三个”“一点”。\n"
                    "8. 输出 JSON：{\"items\":[{\"index\":1,\"text_final\":\"...\"}]}\n\n"
                    f"视频主体：{json.dumps(content_profile, ensure_ascii=False)}\n"
                    f"预设要求：{preset.subtitle_goal}；风格：{preset.subtitle_tone}\n"
                    f"词表：\n{glossary_text}\n"
                    f"同类内容记忆：\n{review_memory_text or '无'}\n"
                    f"搜索证据：\n{evidence_text}\n"
                    f"待处理字幕：{json.dumps(payload_items, ensure_ascii=False)}"
                )
                with track_usage_operation("subtitle_polish.chunk"):
                    response = await provider.complete(
                        [
                            Message(role="system", content="你是严谨的中文短视频字幕审校助手。"),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.1,
                        max_tokens=1600,
                        json_mode=True,
                    )
                data = response.as_json()
                updates = {
                    int(item["index"]): str(item["text_final"]).strip()
                    for item in data.get("items", [])
                    if item.get("text_final")
                }
                for item in chunk:
                    polished = updates.get(item.item_index)
                    if polished:
                        polished = _cleanup_polished_text(polished, preserve_display_numbers=True)
                        original = item.text_final or item.text_norm or item.text_raw or ""
                        current_position = chunk_positions.get(item.item_index, start)
                        if _is_safe_subtitle_polish(
                            original_text=original,
                            polished_text=polished,
                            prev_text=(
                                indexed_items[current_position - 1].text_final
                                or indexed_items[current_position - 1].text_norm
                                or indexed_items[current_position - 1].text_raw
                            ) if current_position > 0 else "",
                            next_text=(
                                indexed_items[current_position + 1].text_final
                                or indexed_items[current_position + 1].text_norm
                                or indexed_items[current_position + 1].text_raw
                            ) if current_position + 1 < len(indexed_items) else "",
                            glossary_terms=glossary_terms,
                            review_memory=review_memory,
                            content_profile=content_profile,
                        ):
                            polished = _fallback_polish_text(
                                polished,
                                glossary_terms=glossary_terms,
                                review_memory=review_memory,
                                prev_text=(
                                    indexed_items[current_position - 1].text_final
                                    or indexed_items[current_position - 1].text_norm
                                    or indexed_items[current_position - 1].text_raw
                                ) if current_position > 0 else "",
                                next_text=(
                                    indexed_items[current_position + 1].text_final
                                    or indexed_items[current_position + 1].text_norm
                                    or indexed_items[current_position + 1].text_raw
                                ) if current_position + 1 < len(indexed_items) else "",
                                preserve_display_numbers=True,
                            )
                            item.text_final = polished
                        else:
                            item.text_final = _fallback_polish_text(
                                original,
                                glossary_terms=glossary_terms,
                                review_memory=review_memory,
                                prev_text=(
                                    indexed_items[current_position - 1].text_final
                                    or indexed_items[current_position - 1].text_norm
                                    or indexed_items[current_position - 1].text_raw
                                ) if current_position > 0 else "",
                                next_text=(
                                    indexed_items[current_position + 1].text_final
                                    or indexed_items[current_position + 1].text_norm
                                    or indexed_items[current_position + 1].text_raw
                                ) if current_position + 1 < len(indexed_items) else "",
                                preserve_display_numbers=True,
                            )
                        polished_count += 1
                        continue
                    item.text_final = _fallback_polish_text(
                        item.text_norm or item.text_raw,
                        glossary_terms=glossary_terms,
                        review_memory=review_memory,
                        prev_text=(
                            indexed_items[chunk_positions.get(item.item_index, start) - 1].text_final
                            or indexed_items[chunk_positions.get(item.item_index, start) - 1].text_norm
                            or indexed_items[chunk_positions.get(item.item_index, start) - 1].text_raw
                        ) if chunk_positions.get(item.item_index, start) > 0 else "",
                        next_text=(
                            indexed_items[chunk_positions.get(item.item_index, start) + 1].text_final
                            or indexed_items[chunk_positions.get(item.item_index, start) + 1].text_norm
                            or indexed_items[chunk_positions.get(item.item_index, start) + 1].text_raw
                        ) if chunk_positions.get(item.item_index, start) + 1 < len(indexed_items) else "",
                        preserve_display_numbers=True,
                    )
                    polished_count += 1
                continue
            except Exception:
                pass

        for position, item in enumerate(chunk, start=start):
            item.text_final = _fallback_polish_text(
                item.text_norm or item.text_raw,
                glossary_terms=glossary_terms,
                review_memory=review_memory,
                prev_text=(
                    indexed_items[position - 1].text_final
                    or indexed_items[position - 1].text_norm
                    or indexed_items[position - 1].text_raw
                ) if position > 0 else "",
                next_text=(
                    indexed_items[position + 1].text_final
                    or indexed_items[position + 1].text_norm
                    or indexed_items[position + 1].text_raw
                ) if position + 1 < len(indexed_items) else "",
                preserve_display_numbers=True,
            )
            polished_count += 1

    return polished_count


async def _search_evidence(
    profile: dict[str, Any],
    source_name: str,
    *,
    transcript_excerpt: str = "",
) -> list[dict[str, str]]:
    queries = _build_search_queries(profile, source_name, transcript_excerpt=transcript_excerpt)
    if not queries:
        return []
    try:
        provider = get_search_provider()
    except Exception:
        return []

    evidence: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for query in queries[:3]:
        try:
            results = await provider.search(query, max_results=3)
        except Exception:
            continue
        for item in results:
            if item.url in seen_urls:
                continue
            seen_urls.add(item.url)
            evidence.append(
                {
                    "query": query,
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                }
            )
    return evidence


def _build_search_queries(
    profile: dict[str, Any],
    source_name: str,
    *,
    transcript_excerpt: str = "",
) -> list[str]:
    brand = str(profile.get("subject_brand") or "").strip()
    brand_aliases = _brand_search_aliases(profile, include_canonical=False)
    model = str(profile.get("subject_model") or "").strip()
    subject_type = str(profile.get("subject_type") or "").strip()
    video_theme = str(profile.get("video_theme") or "").strip()
    visible_text = str(profile.get("visible_text") or "").strip()
    source_stem = Path(source_name).stem
    signal_terms = _extract_search_signal_terms(transcript_excerpt, visible_text, source_stem)
    topic_terms = _extract_topic_terms("\n".join(part for part in (transcript_excerpt, visible_text, source_stem) if part))
    software_like = _is_software_like_subject(subject_type, brand=brand, model=model, topic_terms=topic_terms)
    query_candidates: list[str] = []

    for value in profile.get("search_queries") or []:
        if value:
            query_candidates.append(str(value))

    if brand and model:
        query_candidates.append(f"{brand} {model}")
        if software_like:
            query_candidates.append(f"{brand} {model} 教程")
            query_candidates.append(f"{brand} {model} 功能")
        else:
            query_candidates.append(f"{brand} {model} 开箱")
        for brand_alias in brand_aliases:
            query_candidates.append(f"{brand_alias} {model}")
            if software_like:
                query_candidates.append(f"{brand_alias} {model} 教程")
                query_candidates.append(f"{brand_alias} {model} 功能")
            else:
                query_candidates.append(f"{brand_alias} {model} 开箱")
    elif brand:
        for term in signal_terms[:2]:
            query_candidates.append(f"{brand} {term}")
            if subject_type:
                query_candidates.append(f"{brand} {term} {subject_type}")
        for brand_alias in brand_aliases:
            for term in signal_terms[:2]:
                query_candidates.append(f"{brand_alias} {term}")
                if subject_type:
                    query_candidates.append(f"{brand_alias} {term} {subject_type}")
    elif model:
        if subject_type and not _is_generic_subject_type(subject_type):
            query_candidates.append(f"{model} {subject_type}")
            compact_subject = _subject_type_search_anchor(subject_type)
            if compact_subject:
                query_candidates.append(f"{model} {compact_subject}")
        else:
            query_candidates.append(model)
            query_candidates.append(f"{model} 开箱")
        if subject_type:
            query_candidates.append(f"{model} {subject_type}")
    if brand and subject_type:
        query_candidates.append(f"{brand} {subject_type}")
        for brand_alias in brand_aliases:
            query_candidates.append(f"{brand_alias} {subject_type}")
    if model and subject_type:
        query_candidates.append(f"{model} {subject_type}")
    if software_like and brand and model and any(term in {"无限画布", "漫剧工作流", "工作流", "节点编排", "智能体"} for term in topic_terms):
        for topic in topic_terms[:3]:
            if topic != model:
                query_candidates.append(f"{brand} {topic}")
            query_candidates.append(f"{brand} {topic} 教程")
        for brand_alias in brand_aliases:
            for topic in topic_terms[:3]:
                if topic != model:
                    query_candidates.append(f"{brand_alias} {topic}")
                query_candidates.append(f"{brand_alias} {topic} 教程")
        if "无限画布" in topic_terms or model == "无限画布":
            query_candidates.append(f"{brand} 无限画布 漫剧")
            for brand_alias in brand_aliases:
                query_candidates.append(f"{brand_alias} 无限画布 漫剧")
    if not brand and not model:
        for term in signal_terms[:3]:
            suffix = "教程" if software_like else "开箱"
            query_candidates.append(f"{term} {suffix}")
            if subject_type and not _is_generic_subject_type(subject_type):
                query_candidates.append(f"{term} {subject_type}")
    if _is_informative_source_hint(source_stem):
        query_candidates.append(source_stem)

    support_kwargs = {
        "brand": brand,
        "brand_aliases": brand_aliases,
        "model": model,
        "subject_type": subject_type,
        "video_theme": video_theme,
        "visible_text": visible_text,
        "transcript_excerpt": transcript_excerpt,
        "source_name": source_name,
        "signal_terms": signal_terms,
        "topic_terms": topic_terms,
        "software_like": software_like,
    }
    scored: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for index, query in enumerate(query_candidates):
        normalized = query.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        score = _search_query_support_score(normalized, **support_kwargs)
        if score <= 0:
            continue
        scored.append((score, -index, normalized))
    scored.sort(reverse=True)
    return [query for _, _, query in scored]


def _search_query_support_score(
    query: str,
    *,
    transcript_excerpt: str,
    source_name: str,
    brand: str = "",
    brand_aliases: list[str] | None = None,
    model: str = "",
    subject_type: str = "",
    video_theme: str = "",
    visible_text: str = "",
    signal_terms: list[str] | None = None,
    topic_terms: list[str] | None = None,
    software_like: bool | None = None,
) -> int:
    normalized_query = _normalize_profile_value(query)
    if not normalized_query:
        return 0

    transcript_norm = _normalize_profile_value(transcript_excerpt)
    visible_norm = _normalize_profile_value(visible_text)
    source_stem = Path(source_name).stem
    source_norm = _normalize_profile_value(source_stem if _is_informative_source_hint(source_stem) else "")
    score = 0

    if transcript_norm and normalized_query in transcript_norm:
        score += 6
    if visible_norm and normalized_query in visible_norm:
        score += 4
    if source_norm and normalized_query in source_norm:
        score += 4

    support_values: list[tuple[str, int]] = [(brand, 3)]
    support_values.extend((alias, 2) for alias in (brand_aliases or []))
    support_values.extend(
        [
            (model, 3),
            (subject_type, 2),
            (_subject_type_search_anchor(subject_type), 1),
        ]
    )
    for value, weight in support_values:
        normalized_value = _normalize_profile_value(value)
        if normalized_value and normalized_value in normalized_query:
            score += weight

    for term in signal_terms or []:
        normalized_term = _normalize_profile_value(term)
        if normalized_term and normalized_term in normalized_query:
            score += 2

    for term in topic_terms or []:
        normalized_term = _normalize_profile_value(term)
        if normalized_term and normalized_term in normalized_query:
            score += 2

    theme_support = _summary_theme_fragment(
        video_theme,
        brand=brand,
        model=model,
        preset_name="",
    )
    for term in _extract_query_support_terms(theme_support):
        normalized_term = _normalize_profile_value(term)
        if normalized_term and normalized_term in normalized_query:
            score += 1

    intent_pairs: list[tuple[str, bool]] = [
        ("对比", "对比" in transcript_excerpt or "差异" in transcript_excerpt or "版本" in transcript_excerpt),
        ("升级", "升级" in transcript_excerpt or "升级" in video_theme),
    ]
    if software_like is not None:
        intent_pairs.extend(
            [
                ("教程", software_like),
                ("功能", software_like),
                ("开箱", not software_like),
                ("评测", not software_like),
                ("上手", not software_like),
                ("体验", not software_like),
            ]
        )
    for term, supported in intent_pairs:
        if term in query and supported:
            score += 1

    return score


def _is_software_like_subject(
    subject_type: str,
    *,
    brand: str,
    model: str,
    topic_terms: list[str],
) -> bool:
    normalized = _clean_line(subject_type)
    if any(token in normalized for token in ("软件", "工作流", "AI", "教程", "智能体", "画布")):
        return True
    if brand in _TECH_BRAND_DEFAULT_SUBJECT_TYPES:
        return True
    if model in {"无限画布", "工作流", "漫剧工作流", "节点编排", "智能体"}:
        return True
    return any(term in {"无限画布", "工作流", "漫剧工作流", "节点编排", "智能体"} for term in topic_terms)


def _extract_search_signal_terms(*texts: str) -> list[str]:
    return _extract_search_signal_terms_keywords(*texts)


def _select_excerpt_items(subtitle_items: list[dict], *, max_items: int) -> list[dict]:
    if not subtitle_items:
        return []

    selected: list[dict] = []
    seen: set[tuple[float, float, str]] = set()

    def _append(item: dict) -> None:
        text = _excerpt_item_text(item)
        key = (
            round(_excerpt_item_start(item), 3),
            round(_excerpt_item_end(item), 3),
            text,
        )
        if not text or key in seen:
            return
        seen.add(key)
        selected.append(item)

    for item in subtitle_items[: min(18, len(subtitle_items))]:
        _append(item)

    scored = sorted(
        subtitle_items,
        key=lambda item: (_transcript_signal_score(item), _excerpt_item_start(item)),
        reverse=True,
    )
    for item in scored:
        if len(selected) >= max_items - 4:
            break
        if _transcript_signal_score(item) <= 0:
            continue
        _append(item)

    for item in subtitle_items[-6:]:
        _append(item)

    selected.sort(key=lambda item: (_excerpt_item_start(item), _excerpt_item_end(item)))
    return selected[:max_items]


def _transcript_signal_score(item: dict[str, Any]) -> int:
    text = _excerpt_item_text(item)
    if not text:
        return 0

    normalized = text.upper()
    score = 0
    if re.search(r"(?<![A-Z0-9])[A-Z]{2,}[A-Z0-9-]{0,10}(?![A-Z0-9])", normalized):
        score += 4
    if re.search(r"(?<![A-Z0-9])(?:[A-Z]+\d+|\d+[A-Z]+)(?![A-Z0-9])", normalized):
        score += 3
    if any(keyword in text for keyword in ("型号", "版本", "主刀", "工具", "钳", "刀", "锁", "单手", "开合")):
        score += 2
    if any(pattern.search(text) for _, pattern in _BRAND_ALIAS_PATTERNS):
        score += 2
    if len(text) >= 10:
        score += 1
    return score


_BRAND_ALIAS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("LEATHERMAN", re.compile(r"(LEATHERMAN|莱[泽着]曼|来[自自泽着]慢|来[自泽着]曼|雷[泽着]曼)", re.IGNORECASE)),
    ("REATE", re.compile(r"(REATE|锐特|瑞特|睿特)", re.IGNORECASE)),
    ("OLIGHT", re.compile(r"(OLIGHT|O\s*LIGHT|傲雷|奥雷)", re.IGNORECASE)),
    ("Loop露普", re.compile(r"(LOOP|露普|陆虎|路普|鲁普)", re.IGNORECASE)),
    ("狐蝠工业", re.compile(r"(FOXBAT|狐蝠工业|狐蝠)", re.IGNORECASE)),
    ("LuckyKiss", re.compile(r"(LUCKYKISS|LuckyKiss|luckykiss)", re.IGNORECASE)),
]

_BRAND_CN_DISPLAY_MAP: dict[str, str] = {
    "LEATHERMAN": "莱泽曼",
    "REATE": "锐特",
    "OLIGHT": "傲雷",
    "NexTool": "纳拓",
}

_TECH_BRAND_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("RunningHub", re.compile(r"(RUNNINGHUB|RunningHub|runninghub|(?<![A-Za-z0-9])RH(?![A-Za-z0-9]))", re.IGNORECASE)),
    ("ComfyUI", re.compile(r"(COMFYUI|ComfyUI|comfyui)", re.IGNORECASE)),
    ("OpenClaw", re.compile(r"(OPENCLAW|OpenClaw|openclaw)", re.IGNORECASE)),
    ("OpenAI", re.compile(r"(OPENAI|OpenAI|openai)", re.IGNORECASE)),
    ("Claude", re.compile(r"(?<![A-Za-z])(CLAUDE|Claude|claude)(?![A-Za-z])", re.IGNORECASE)),
    ("Gemini", re.compile(r"(?<![A-Za-z])(GEMINI|Gemini|gemini)(?![A-Za-z])", re.IGNORECASE)),
]

_TECH_BRAND_DEFAULT_SUBJECT_TYPES: dict[str, str] = {
    "RunningHub": "AI工作流创作平台",
    "ComfyUI": "AI图像工作流工具",
    "OpenClaw": "AI Agent 框架",
    "OpenAI": "AI模型平台",
    "Claude": "AI模型工具",
    "Gemini": "AI模型工具",
}

_TECH_TOPIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("无限画布", re.compile(r"(无限画布|无边画布|无限画板|无限canvas|infinite\s+canvas)", re.IGNORECASE)),
    ("工作流", re.compile(r"(工作流|workflow|节点流|流程编排)", re.IGNORECASE)),
    ("节点编排", re.compile(r"(节点编排|节点连接|节点搭建|节点串联)", re.IGNORECASE)),
    ("漫剧工作流", re.compile(r"(漫剧工作流|漫剧制作|漫画剧|短剧工作流|剧情工作流)", re.IGNORECASE)),
    ("智能体", re.compile(r"(智能体|agent mode|agents?|multi-agent|多智能体)", re.IGNORECASE)),
    ("提示词", re.compile(r"(提示词|prompt)", re.IGNORECASE)),
    ("LoRA", re.compile(r"(lora|罗拉)", re.IGNORECASE)),
    ("RAG", re.compile(r"(?<![A-Za-z])(rag|RAG)(?![A-Za-z])", re.IGNORECASE)),
    ("工作流编排", re.compile(r"(工作流编排|流程编排)", re.IGNORECASE)),
]

_SEARCH_SIGNAL_STOPWORDS: set[str] = {
    "ASMR",
    "DIY",
    "EDC",
    "POV",
    "VLOG",
}

_MODEL_TO_BRAND: dict[str, str] = {
    "ARC": "LEATHERMAN",
    "F12": "NexTool",
    "F2": "NexTool",
    "FXX1": "狐蝠工业",
    "FXX1小副包": "狐蝠工业",
    "KissPod": "LuckyKiss",
    "S11 PRO": "NexTool",
    "S11PRO": "NexTool",
    "SK05二代ProUV版": "Loop露普",
    "SK05二代Pro UV版": "Loop露普",
    "SK05二代UV版": "Loop露普",
    "SK05二代 UV版": "Loop露普",
    "SK05UV版": "Loop露普",
    "SK05 UV版": "Loop露普",
    "SLIM2代ULTRA版本": "OLIGHT",
    "SLIM2 ULTRA": "OLIGHT",
    "司令官2Ultra": "OLIGHT",
}

_CATEGORY_SCOPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "bag": ("包", "背包", "双肩包", "机能包", "斜挎包", "胸包", "快取包", "副包", "分仓", "挂点", "背负", "收纳"),
    "flashlight": ("手电", "电筒", "筒身", "流明", "泛光", "聚光", "色温", "夜骑", "尾按", "尾绳孔", "绳孔", "补光", "UV"),
    "knife": ("刀", "折刀", "重力刀", "开合", "锁定", "背夹", "刃型", "柄材", "钢材", "雕刻", "电镀"),
    "tools": ("工具钳", "钳", "批头", "螺丝刀", "扳手", "尖嘴钳", "钢丝钳"),
}


def _subject_domain_from_subject_type(subject_type: str) -> str:
    normalized = _clean_line(str(subject_type or ""))
    if not normalized:
        return ""
    if any(token in normalized for token in ("机能包", "背包", "双肩包", "背负", "副包", "收纳", "EDC机能包")):
        return "bag"
    if any(token in normalized for token in ("手电", "手电筒", "电筒", "EDC手电")):
        return "flashlight"
    if any(token in normalized for token in ("折刀", "重力刀", "EDC折刀")):
        return "knife"
    if any(token in normalized for token in ("工具钳", "多功能工具钳")):
        return "tools"
    return ""


def _infer_subject_domain_from_text(text: str) -> str:
    transcript = str(text or "")
    if _has_ingestible_product_context(transcript):
        return "food"
    if any(token in transcript for token in _CATEGORY_SCOPE_KEYWORDS["bag"]):
        return "bag"
    if any(token in transcript for token in _CATEGORY_SCOPE_KEYWORDS["flashlight"]):
        return "flashlight"
    if any(token in transcript for token in _CATEGORY_SCOPE_KEYWORDS["knife"]):
        return "knife"
    if any(token in transcript for token in _CATEGORY_SCOPE_KEYWORDS["tools"]):
        return "tools"
    return ""


def _seed_profile_domain_matches(seed: dict[str, Any], *, subject_domain: str) -> bool:
    if not subject_domain:
        return True
    seed_subject_type = _hint_primary_value(seed, "subject_type")
    if not seed_subject_type:
        return True
    seed_domain = _subject_domain_from_subject_type(seed_subject_type)
    return not seed_domain or seed_domain == subject_domain


def _seed_profile_from_subtitles(
    subtitle_items: list[dict],
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
    subject_domain: str = "",
) -> dict[str, Any]:
    transcript_lines = [
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items
    ]
    transcript = "\n".join(line for line in transcript_lines if line)
    return _seed_profile_from_text(transcript, glossary_terms=glossary_terms, subject_domain=subject_domain)


def _seed_profile_from_transcript_excerpt(
    transcript_excerpt: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
    subject_domain: str = "",
) -> dict[str, Any]:
    return _seed_profile_from_text(
        transcript_excerpt,
        glossary_terms=glossary_terms,
        subject_domain=subject_domain,
    )


def _seed_profile_from_context(
    profile: dict[str, Any],
    transcript_excerpt: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
    subject_domain: str = "",
) -> dict[str, Any]:
    text = "\n".join(
        part
        for part in (
            transcript_excerpt,
            str(profile.get("visible_text") or "").strip(),
            str(profile.get("hook_line") or "").strip(),
        )
        if part
    )
    return _seed_profile_from_text(
        text,
        glossary_terms=glossary_terms,
        subject_domain=subject_domain,
    )


def _seed_profile_from_user_memory(
    transcript_excerpt: str,
    user_memory: dict[str, Any] | None,
    *,
    subject_domain: str | None = None,
) -> dict[str, Any]:
    transcript_norm = _normalize_profile_value(transcript_excerpt)
    if not transcript_norm or not user_memory:
        return {}

    seeded: dict[str, Any] = {}
    field_preferences = user_memory.get("field_preferences") or {}
    recent_corrections = user_memory.get("recent_corrections") or []
    phrase_preferences = user_memory.get("phrase_preferences") or []
    transcript_domain = str(subject_domain or "").strip() or _infer_subject_domain_from_text(transcript_excerpt)

    for item in recent_corrections:
        corrected = str(item.get("corrected_value") or "").strip()
        if corrected and _normalize_profile_value(corrected) in transcript_norm:
            field_name = str(item.get("field_name") or "").strip()
            if field_name in {"subject_brand", "subject_model"} and field_name not in seeded:
                seeded[field_name] = corrected
            elif field_name in {"subject_type", "video_theme"}:
                _append_hint_candidate(seeded, field_name, corrected)

    subject_identity_available = bool(_hint_primary_value(seeded, "subject_brand") or _hint_primary_value(seeded, "subject_model"))
    for field_name in ("subject_brand", "subject_model", "subject_type"):
        if field_name in {"subject_brand", "subject_model"} and field_name in seeded:
            continue
        if field_name == "subject_type" and _hint_primary_value(seeded, field_name):
            continue
        for item in field_preferences.get(field_name) or []:
            value = str(item.get("value") or "").strip()
            if field_name in {"subject_brand", "subject_model"}:
                if value and _normalize_profile_value(value) in transcript_norm:
                    seeded[field_name] = value
                    break
                continue
            if value and (subject_identity_available or _normalize_profile_value(value) in transcript_norm):
                _append_hint_candidate(seeded, field_name, value)
                break

    if not _hint_primary_value(seeded, "video_theme"):
        for item in field_preferences.get("video_theme") or []:
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            tokens = [token for token in re.split(r"[\s/·\-]+", value) if token]
            hit_count = sum(1 for token in tokens if _normalize_profile_value(token) and _normalize_profile_value(token) in transcript_norm)
            if hit_count >= 2:
                _append_hint_candidate(seeded, "video_theme", value)
                break

    if "subject_brand" not in seeded:
        for item in phrase_preferences:
            phrase = str(item.get("phrase") or "").strip()
            if not phrase or _normalize_profile_value(phrase) not in transcript_norm:
                continue
            phrase_seed = _seed_profile_from_text(
                phrase,
                subject_domain=transcript_domain,
            )
            if not _seed_profile_domain_matches(phrase_seed, subject_domain=transcript_domain):
                continue
            if phrase_seed.get("subject_brand"):
                seeded["subject_brand"] = phrase_seed["subject_brand"]
            if phrase_seed.get("subject_model") and "subject_model" not in seeded:
                seeded["subject_model"] = phrase_seed["subject_model"]
            if seeded.get("subject_brand"):
                break

        if not _hint_primary_value(seeded, "subject_type"):
            transcript_seed = _seed_profile_from_text(
                transcript_excerpt,
                subject_domain=transcript_domain,
            )
            transcript_subject_type = _hint_primary_value(transcript_seed, "subject_type")
            if transcript_subject_type:
                _append_hint_candidate(seeded, "subject_type", transcript_subject_type)
            elif seeded.get("subject_brand") == "Loop露普" or str(seeded.get("subject_model") or "").startswith("SK05"):
                _append_hint_candidate(seeded, "subject_type", "EDC手电")

    if "subject_brand" not in seeded and "subject_model" not in seeded:
        subject_type = _hint_primary_value(seeded, "subject_type")
        subject_domain = _subject_domain_from_subject_type(subject_type)
        if not subject_domain:
            subject_domain = transcript_domain
        confirmed_entity = _select_confirmed_entity_from_user_memory(
            transcript_excerpt,
            user_memory=user_memory,
            subject_type=subject_type,
            subject_domain=subject_domain,
        )
        if confirmed_entity:
            brand = str(confirmed_entity.get("brand") or "").strip()
            model = str(confirmed_entity.get("model") or "").strip()
            model_aliases = confirmed_entity.get("model_aliases") or []
            if brand:
                seeded["subject_brand"] = brand
            alias_hit = any(
                _memory_value_matches_transcript(
                    str(item.get("wrong") or "").strip(),
                    transcript_excerpt,
                    transcript_norm,
                )
                for item in model_aliases
            )
            if model and (_memory_keyword_matches_transcript(model, transcript_excerpt, transcript_norm) or alias_hit):
                seeded["subject_model"] = model
            if confirmed_entity.get("subject_type") and not _hint_primary_value(seeded, "subject_type"):
                _append_hint_candidate(seeded, "subject_type", confirmed_entity.get("subject_type"))

    return seeded


def _select_confirmed_entity_from_user_memory(
    transcript_excerpt: str,
    *,
    user_memory: dict[str, Any] | None,
    subject_type: str,
    subject_domain: str,
) -> dict[str, Any]:
    transcript = str(transcript_excerpt or "").strip()
    normalized = _normalize_profile_value(transcript)
    if not transcript or not normalized:
        return {}
    for entity in (user_memory or {}).get("confirmed_entities") or []:
        if not _confirmed_entity_matches_current_context(
            entity,
            transcript=transcript,
            normalized=normalized,
            subject_type=subject_type,
            subject_domain=subject_domain,
        ):
            continue
        return dict(entity)
    return {}


def _confirmed_entity_matches_current_context(
    entity: dict[str, Any],
    *,
    transcript: str,
    normalized: str,
    subject_type: str,
    subject_domain: str,
) -> bool:
    entity_subject_type = str(entity.get("subject_type") or "").strip()
    effective_subject_type = str(subject_type or "").strip()
    effective_subject_domain = str(subject_domain or "").strip().lower()
    if not effective_subject_domain:
        effective_subject_domain = _subject_domain_from_subject_type(effective_subject_type)
    alias_context_support = _confirmed_entity_has_alias_context_support(
        entity,
        transcript=transcript,
        normalized=normalized,
    )
    if not effective_subject_type:
        transcript_seed = _seed_profile_from_text(
            transcript,
            subject_domain=effective_subject_domain,
        )
        effective_subject_type = _hint_primary_value(transcript_seed, "subject_type")
    if effective_subject_domain:
        entity_subject_domain = _subject_domain_from_subject_type(entity_subject_type)
        if not entity_subject_domain and str(entity.get("subject_domain") or "").strip():
            entity_subject_domain = str(entity.get("subject_domain") or "").strip().lower()
        if entity_subject_domain and entity_subject_domain != effective_subject_domain:
            return False

    if entity_subject_type and effective_subject_type and _normalize_profile_value(entity_subject_type) != _normalize_profile_value(effective_subject_type):
        return False
    if (
        entity_subject_type
        and "手电" in entity_subject_type
        and not alias_context_support
        and not any(token in transcript for token in ("手电", "电筒", "开箱", "流明", "夜骑", "泛光", "聚光", "夹持"))
    ):
        return False

    brand = str(entity.get("brand") or "").strip()
    model = str(entity.get("model") or "").strip()
    if brand and _memory_value_matches_transcript(brand, transcript, normalized):
        return True
    if model and _memory_keyword_matches_transcript(model, transcript, normalized):
        return True

    for phrase in entity.get("phrases") or []:
        if _memory_keyword_matches_transcript(str(phrase or "").strip(), transcript, normalized):
            return True

    model_norm = _normalize_profile_value(model)
    variant_tokens = [
        token for token in ("ULTRA", "PRO", "UV", "MAX", "MINI", "PLUS", "二代", "2代")
        if token in model.upper() or token in model
    ]
    for item in entity.get("model_aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        if not wrong or not _memory_value_matches_transcript(wrong, transcript, normalized):
            continue
        if not variant_tokens:
            return True
        if any(token.upper() in transcript.upper() or token in transcript for token in variant_tokens):
            return True
        if model_norm and _memory_keyword_matches_transcript(model, transcript, normalized):
            return True
    return False


def _confirmed_entity_has_alias_context_support(
    entity: dict[str, Any],
    *,
    transcript: str,
    normalized: str,
) -> bool:
    brand = str(entity.get("brand") or "").strip()
    model = str(entity.get("model") or "").strip()
    if brand and _memory_value_matches_transcript(brand, transcript, normalized):
        return True
    if model and _memory_keyword_matches_transcript(model, transcript, normalized):
        return True
    for phrase in entity.get("phrases") or []:
        if _memory_keyword_matches_transcript(str(phrase or "").strip(), transcript, normalized):
            return True

    model_norm = _normalize_profile_value(model)
    variant_tokens = [
        token for token in ("ULTRA", "PRO", "UV", "MAX", "MINI", "PLUS", "二代", "2代")
        if token in model.upper() or token in model
    ]
    for item in entity.get("model_aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        if not wrong or not _memory_value_matches_transcript(wrong, transcript, normalized):
            continue
        if not variant_tokens:
            return True
        if any(token.upper() in transcript.upper() or token in transcript for token in variant_tokens):
            return True
        if model_norm and _memory_keyword_matches_transcript(model, transcript, normalized):
            return True
    return False


def _seed_profile_from_glossary_terms(
    transcript_excerpt: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    transcript = str(transcript_excerpt or "").strip()
    if not transcript or not glossary_terms:
        return {}

    normalized_transcript = _normalize_profile_value(transcript)
    seeded: dict[str, Any] = {}
    best_brand: tuple[int, str] | None = None
    best_brand_category = ""
    best_model: tuple[int, str] | None = None
    best_model_category = ""
    matched_brands: list[str] = []

    for term in glossary_terms:
        correct_form = str(term.get("correct_form") or "").strip()
        category = str(term.get("category") or "").strip().lower()
        if not correct_form:
            continue
        if not _glossary_term_matches_category_scope(term, transcript):
            continue
        matched_value = _match_glossary_identity_candidate(
            normalized_transcript=normalized_transcript,
            correct_form=correct_form,
            wrong_forms=term.get("wrong_forms") or [],
        )
        if not matched_value:
            continue

        if _is_brand_like_glossary_category(category):
            candidate = _canonical_brand_display_name(correct_form)
            score = len(_normalize_profile_value(matched_value))
            if candidate and candidate not in matched_brands:
                matched_brands.append(candidate)
            if candidate and (best_brand is None or score > best_brand[0]):
                best_brand = (score, candidate)
                best_brand_category = category
        elif _is_model_like_glossary_category(category) or _looks_like_product_model(correct_form):
            score = len(_normalize_profile_value(correct_form))
            if best_model is None or score > best_model[0]:
                best_model = (score, correct_form)
                best_model_category = category

    if best_brand and len(matched_brands) == 1:
        seeded["subject_brand"] = best_brand[1]
        subject_type = _subject_type_from_glossary_category(best_brand_category)
        if subject_type:
            _append_hint_candidate(seeded, "subject_type", subject_type)
    if best_model:
        seeded["subject_model"] = best_model[1]
        subject_type = _subject_type_from_glossary_category(best_model_category)
        if subject_type:
            _append_hint_candidate(seeded, "subject_type", subject_type)
        if "subject_brand" not in seeded and best_model[1] in _MODEL_TO_BRAND:
            seeded["subject_brand"] = _MODEL_TO_BRAND[best_model[1]]
    if matched_brands:
        queries: list[str] = []
        model = str(seeded.get("subject_model") or "").strip()
        subject_type = _hint_primary_value(seeded, "subject_type")
        for brand in matched_brands[:3]:
            if model:
                queries.append(f"{brand} {model}")
            elif subject_type:
                queries.append(f"{brand} {subject_type}")
            else:
                queries.append(brand)
        if queries:
            seeded["search_queries"] = queries
    return seeded


def _seed_profile_from_text(
    transcript: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
    subject_domain: str = "",
) -> dict[str, Any]:
    normalized_subject_domain = str(subject_domain or "").strip().lower()
    if not normalized_subject_domain:
        normalized_subject_domain = _infer_subject_domain_from_text(transcript)
    normalized = transcript.upper()
    canon = _canonicalize_spoken_identity_text(transcript)
    glossary_seed = _seed_profile_from_glossary_terms(transcript, glossary_terms)

    brand = ""
    for name, pattern in _BRAND_ALIAS_PATTERNS:
        if pattern.search(transcript):
            brand = name
            break
    glossary_brand = str(glossary_seed.get("subject_brand") or "").strip()
    if glossary_brand and (
        not brand
        or _normalize_profile_value(brand) in _normalize_profile_value(glossary_brand)
    ):
        brand = glossary_brand

    model = ""
    model_source = ""
    if _has_arc_spoken_alias(transcript):
        model = "ARC"
        model_source = "explicit_alias"
    elif re.search(r"(?<![A-Z0-9])SURGE(?![A-Z0-9])", normalized):
        model = "SURGE"
        model_source = "explicit_alias"
    elif re.search(r"(?<![A-Z0-9])CHARGE(?![A-Z0-9])", normalized):
        model = "CHARGE"
        model_source = "explicit_alias"
    elif re.search(r"(?<![A-Z0-9])KISSPOD(?![A-Z0-9])", normalized):
        model = "KissPod"
        model_source = "explicit_alias"
    elif _extract_edc_bag_model(canon, transcript):
        model = _extract_edc_bag_model(canon, transcript)
        model_source = "bag_alias"
    else:
        model = _extract_edc_flashlight_model(canon)
        if model:
            model_source = "flashlight_alias"
    if not model:
        model = _extract_generic_product_model(canon, transcript)
        if model:
            model_source = "generic"
    if not model:
        model = str(glossary_seed.get("subject_model") or "").strip()
        if model:
            model_source = "glossary"

    if model and not _has_supported_product_model_hint(
        transcript=transcript,
        brand=brand,
        model=model,
        model_source=model_source,
    ):
        keep_scoped_glossary_model = (
            model_source == "glossary"
            and model == str(glossary_seed.get("subject_model") or "").strip()
            and bool(_hint_primary_value(glossary_seed, "subject_type"))
        )
        if not keep_scoped_glossary_model:
            model = ""

    if not brand and model in _MODEL_TO_BRAND:
        brand = _MODEL_TO_BRAND[model]

    subject_type = ""
    knife_keywords = ("折刀", "刀片", "锁定机构", "推刀", "梯片", "锁片", "刀柄", "柄身", "开刃")
    plier_keywords = ("工具钳", "钳子", "尖嘴钳", "钢丝钳")
    flashlight_keywords = ("手电", "电筒", "筒身", "紫光", "UV", "流明", "泛光", "照射")
    bag_keywords = ("机能包", "机能双肩包", "双肩包", "副包", "小副包", "斜挎包", "胸包", "快取包", "分仓", "挂点", "收纳", "背负")

    if brand == "LEATHERMAN" or model in {"ARC", "SURGE", "CHARGE"}:
        subject_type = "多功能工具钳"
    elif brand == "REATE" or any(keyword in transcript for keyword in knife_keywords):
        subject_type = "EDC折刀"
    elif (
        brand in {"Loop露普", "OLIGHT"}
        or model.startswith(("SK05", "SLIM2", "司令官2"))
        or (normalized_subject_domain == "flashlight" and any(keyword in canon.upper() for keyword in flashlight_keywords))
        or (
            not normalized_subject_domain
            and not any(keyword in transcript for keyword in bag_keywords)
            and any(keyword in canon.upper() for keyword in flashlight_keywords)
        )
    ):
        subject_type = "EDC手电"
    elif (
        brand == "狐蝠工业"
        or model.startswith("FXX1")
        or normalized_subject_domain in {"bag", ""}
        and any(keyword in transcript for keyword in bag_keywords)
    ):
        subject_type = "EDC机能包"
    elif _has_ingestible_product_context(transcript):
        subject_type = _INGESTIBLE_DEFAULT_SUBJECT_TYPE
    elif any(keyword in transcript for keyword in plier_keywords):
        subject_type = "多功能工具钳"
    elif _hint_primary_value(glossary_seed, "subject_type"):
        subject_type = _hint_primary_value(glossary_seed, "subject_type")

    topic_terms = _extract_topic_terms(transcript)
    product_identity_detected = bool(
        subject_type
        or brand in {"LEATHERMAN", "REATE", "Loop露普", "狐蝠工业", "LuckyKiss"}
        or model
    )
    tech_brand = _detect_primary_tech_brand(transcript, topic_terms=topic_terms)
    feature = topic_terms[0] if topic_terms else ""
    tech_subject_type = _infer_tech_subject_type(
        transcript=transcript,
        tech_brand=tech_brand,
        topic_terms=topic_terms,
    )
    if tech_brand and not brand and not product_identity_detected:
        brand = tech_brand
    if tech_subject_type and not product_identity_detected:
        subject_type = tech_subject_type
    if feature and not model and not product_identity_detected:
        model = feature

    seeded: dict[str, Any] = {}
    if brand:
        seeded["subject_brand"] = brand
    if model:
        seeded["subject_model"] = model
    if subject_type:
        _append_hint_candidate(seeded, "subject_type", subject_type)
    video_theme = _build_seeded_video_theme(
        transcript=transcript,
        brand=brand,
        model=model,
        subject_type=subject_type,
        topic_terms=topic_terms,
    )
    if video_theme:
        _append_hint_candidate(seeded, "video_theme", video_theme)
    queries: list[str] = [str(item).strip() for item in (glossary_seed.get("search_queries") or []) if str(item).strip()]
    if brand or model:
        seeded_queries = _build_seeded_search_queries(
            brand=brand,
            model=model,
            subject_type=subject_type,
            topic_terms=topic_terms,
        )
        for item in seeded_queries:
            if item not in queries:
                queries.append(item)
    elif subject_type:
        seeded_queries = _build_scoped_seed_search_queries(
            transcript=transcript,
            subject_type=subject_type,
            glossary_terms=glossary_terms,
        )
        for item in seeded_queries:
            if item not in queries:
                queries.append(item)
    if queries:
        seeded["search_queries"] = queries
    return _apply_brand_display_fields(seeded)


def _canonicalize_spoken_identity_text(text: str) -> str:
    return canonicalize_spoken_identity_text(text)


def _extract_edc_flashlight_model(text: str) -> str:
    normalized = _canonicalize_spoken_identity_text(text)
    if (
        re.search(r"(?:司令官|COMMANDER)\s*(?:2|II)", str(text or ""), re.IGNORECASE)
        or re.search(r"(?:司令官|COMMANDER)\s*(?:2|II)", normalized, re.IGNORECASE)
    ) and "ULTRA" in normalized:
        return "司令官2Ultra"

    if "SK05" in normalized:
        suffixes: list[str] = ["SK05"]
        if "2代" in normalized or "二代" in text or "II" in normalized:
            suffixes.append("二代")
        if "PRO" in normalized:
            suffixes.append("Pro")
        if "UV" in normalized:
            suffixes.append("UV版")
        return " ".join(suffixes[:1]).replace(" ", "") if len(suffixes) == 1 else f"{suffixes[0]}{''.join(suffixes[1:])}"

    if "SLIM2" in normalized:
        if "ULTRA" in normalized:
            return "SLIM2代ULTRA版本"
        if "PRO" in normalized:
            return "SLIM2 PRO"
        return "SLIM2"

    return ""


def _has_supported_product_model_hint(
    *,
    transcript: str,
    brand: str,
    model: str,
    model_source: str = "",
) -> bool:
    compact_model = re.sub(r"[^A-Z0-9]+", "", _canonicalize_spoken_identity_text(model))
    compact_transcript = re.sub(r"[^A-Z0-9]+", "", _canonicalize_spoken_identity_text(transcript))
    mention_count = compact_transcript.count(compact_model)
    first_index = compact_transcript.find(compact_model)
    early_mention = first_index != -1 and first_index <= 240
    has_variant_marker = any(token in compact_model for token in ("PRO", "MAX", "MINI", "UV", "II"))
    product_cues = (
        "开箱",
        "对比",
        "评测",
        "测评",
        "上手",
        "手电",
        "电筒",
        "UV",
        "流明",
        "泛光",
        "聚光",
        "夜骑",
        "版本",
        "一代",
        "二代",
    )

    if not compact_model:
        return False
    if model_source == "bag_alias":
        return True
    if model_source == "explicit_alias" and model == "ARC" and _has_arc_spoken_alias(transcript):
        return True
    if model_source in {"glossary", "explicit_alias", "generic"}:
        return mention_count >= 1
    if model_source == "flashlight_alias":
        family_match = re.match(r"[A-Z]{1,4}\d{1,4}", compact_model)
        family = family_match.group(0) if family_match else compact_model
        canonical_transcript = _canonicalize_spoken_identity_text(transcript)
        family_mentions = compact_transcript.count(family)
        family_index = canonical_transcript.find(family)
        family_is_early = family_index != -1 and family_index <= 240
        local_window = canonical_transcript[max(0, family_index - 16):family_index + 32] if family_index != -1 else ""
        variant_hits = 0
        local_variant_hits = 0
        if "2" in compact_model and any(token in transcript for token in ("二代", "2代", "Ⅱ代", "II")):
            variant_hits += 1
            if any(token in local_window for token in ("2代", "II")):
                local_variant_hits += 1
        if "PRO" in compact_model and "PRO" in transcript.upper():
            variant_hits += 1
            if "PRO" in local_window:
                local_variant_hits += 1
        if "UV" in compact_model and "UV" in transcript.upper():
            variant_hits += 1
            if "UV" in local_window:
                local_variant_hits += 1

        if family_mentions >= 2:
            return True
        if brand and family_mentions >= 1:
            return True
        if family_mentions >= 1 and variant_hits >= 2:
            return True
        if family_is_early and local_variant_hits >= 1 and any(cue in transcript for cue in product_cues):
            return True
        return False
    if len(compact_model) < 4:
        return False

    if mention_count >= 2:
        return True
    if brand and mention_count >= 1:
        return True
    if early_mention and (has_variant_marker or any(cue in transcript for cue in product_cues)):
        return True
    return False


def _extract_edc_bag_model(text: str, original_text: str) -> str:
    normalized = _canonicalize_spoken_identity_text(text)
    normalized = re.sub(r"F\s*X\s*21(?=小副包|[^A-Z0-9]|$)", "FXX1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"F\s*X\s*X\s*1(?=小副包|[^A-Z0-9]|$)", "FXX1", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"F\s*21(?=小副包|[^A-Z0-9]|$)", "FXX1", normalized, flags=re.IGNORECASE)
    if "FXX1" not in normalized:
        return ""
    return "FXX1小副包"


def _extract_generic_product_model(normalized_text: str, original_text: str) -> str:
    compact_normalized = _canonicalize_spoken_identity_text(normalized_text)
    original = str(original_text or "")
    for match in re.finditer(
        r"(?<![A-Z0-9])([A-Z]{1,6}-?\d{1,4}[A-Z0-9-]{0,6})(?![A-Z0-9])",
        compact_normalized,
    ):
        candidate = match.group(1).strip("-")
        if not candidate or _looks_like_camera_stem(candidate):
            continue
        if candidate in _TECH_BRAND_DEFAULT_SUBJECT_TYPES:
            continue
        tail = original[match.end():match.end() + 8].lstrip()
        if tail.startswith("小副包"):
            return f"{candidate}小副包"
        if tail.startswith("副包"):
            return f"{candidate}副包"
        if tail.startswith("UV版"):
            return f"{candidate}UV版"
        return candidate
    return ""


def _extract_topic_terms(text: str) -> list[str]:
    return _extract_topic_terms_keywords(text)


def _detect_primary_tech_brand(transcript: str, *, topic_terms: list[str]) -> str:
    workflow_topics = {"无限画布", "工作流", "工作流编排", "节点编排", "漫剧工作流", "智能体"}
    best_brand = ""
    best_score = 0
    for brand, pattern in _TECH_BRAND_PATTERNS:
        matches = list(pattern.finditer(transcript))
        if not matches:
            continue
        score = len(matches) * 2
        first_pos = matches[0].start()
        if first_pos < 220:
            score += 2
        if brand in {"RunningHub", "ComfyUI", "OpenClaw"} and any(topic in workflow_topics for topic in topic_terms):
            score += 4
        if brand == "RunningHub" and (
            "无限画布" in topic_terms
            or "漫剧工作流" in topic_terms
            or re.search(r"(?<![A-Za-z0-9])RH(?![A-Za-z0-9])", transcript, re.IGNORECASE)
        ):
            score += 4
        if brand in {"Gemini", "Claude", "OpenAI"} and any(topic in workflow_topics for topic in topic_terms):
            score -= 1
        if score > best_score:
            best_brand = brand
            best_score = score
    return best_brand


def _infer_tech_subject_type(
    *,
    transcript: str,
    tech_brand: str,
    topic_terms: list[str],
) -> str:
    if tech_brand in _TECH_BRAND_DEFAULT_SUBJECT_TYPES:
        if tech_brand == "OpenClaw":
            return _TECH_BRAND_DEFAULT_SUBJECT_TYPES[tech_brand]
        if any(term in {"无限画布", "工作流", "工作流编排", "节点编排", "漫剧工作流"} for term in topic_terms):
            return _TECH_BRAND_DEFAULT_SUBJECT_TYPES[tech_brand]
    normalized = transcript.upper()
    if any(term in topic_terms for term in ("智能体",)) or "AGENT" in normalized:
        return "AI Agent 框架"
    if any(term in topic_terms for term in ("无限画布", "工作流", "工作流编排", "节点编排", "漫剧工作流")):
        return "AI工作流创作平台"
    if "COMFYUI" in normalized:
        return "AI图像工作流工具"
    if any(keyword in transcript for keyword in ("录屏", "教程", "演示", "实操", "节点", "画布", "工作流")):
        return "AI创作工具"
    return ""


def _build_seeded_video_theme(
    *,
    transcript: str,
    brand: str,
    model: str,
    subject_type: str,
    topic_terms: list[str],
) -> str:
    lowered = transcript.lower()
    feature = model if model in topic_terms else (topic_terms[0] if topic_terms else "")
    if feature == "工作流" and "漫剧工作流" in topic_terms:
        feature = "漫剧工作流"
    product_anchor = f"{brand}{model}".strip() or brand or model

    if product_anchor and "software" not in lowered:
        has_unboxing = any(keyword in transcript for keyword in ("开箱", "包装"))
        has_review = any(keyword in transcript for keyword in ("评测", "测评", "上手", "体验"))
        has_compare = any(keyword in transcript for keyword in ("对比", "比较", "横评"))
        has_gen_comparison = "一代" in transcript and any(
            keyword in transcript for keyword in ("二代", "2代", "Ⅱ代", "II")
        )
        if has_unboxing or has_review or has_compare or has_gen_comparison:
            if has_compare or has_gen_comparison:
                if "一代" in transcript:
                    return f"{product_anchor}开箱与一代对比评测"
                return f"{product_anchor}开箱对比评测"
            if has_unboxing and has_review:
                return f"{product_anchor}开箱与上手评测"
            if has_unboxing:
                return f"{product_anchor}开箱与功能实测"
            if has_review:
                return f"{product_anchor}上手评测"

    if feature == "无限画布":
        if any(keyword in transcript for keyword in ("上线", "更新", "新功能", "刚出", "发布")):
            return f"{brand or '这款工具'}无限画布新功能上线与实操演示"
        if any(keyword in transcript for keyword in ("漫剧", "短剧", "漫画剧")):
            return f"{brand or '这款工具'}无限画布漫剧工作流演示"
        return f"{brand or '这款工具'}无限画布功能实测与教程"
    if feature == "漫剧工作流":
        return f"{brand or '这款工具'}漫剧工作流搭建与实操演示"
    if feature == "工作流" or feature == "工作流编排":
        return f"{brand or '这款工具'}工作流搭建与节点编排教程"
    if feature == "节点编排":
        return f"{brand or '这款工具'}节点编排与工作流搭建演示"
    if feature == "智能体":
        return f"{brand or '这款工具'}智能体工作流搭建与能力演示"
    if feature == "提示词":
        return f"{brand or '这款工具'}提示词工作流实操"
    if brand and any(keyword in transcript for keyword in ("教程", "演示", "实操", "录屏", "怎么用")):
        return f"{brand}{subject_type or '功能'}实操教程"
    if brand and subject_type and "software" not in lowered:
        return f"{brand}{subject_type}功能演示"
    return ""


def _build_seeded_search_queries(
    *,
    brand: str,
    model: str,
    subject_type: str,
    topic_terms: list[str],
) -> list[str]:
    queries: list[str] = []
    if brand and model:
        queries.extend(
            [
                f"{brand} {model}",
                f"{brand} {model} 教程",
                f"{brand} {model} 功能",
            ]
        )
        if "漫剧工作流" in topic_terms or model == "无限画布":
            queries.append(f"{brand} {model} 漫剧")
    elif brand:
        queries.extend([brand, f"{brand} 教程"])
    elif model:
        queries.extend([model, f"{model} 教程"])
    if brand and subject_type and "开箱" not in subject_type:
        queries.append(f"{brand} {subject_type}")
    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _build_scoped_seed_search_queries(
    *,
    transcript: str,
    subject_type: str,
    glossary_terms: list[dict[str, Any]] | None,
) -> list[str]:
    if not subject_type or not glossary_terms:
        return []
    if "包" not in subject_type:
        return []

    seed_brands: list[str] = []
    seed_models: list[str] = []
    seed_product_terms: list[str] = []
    for term in glossary_terms or []:
        if not _glossary_term_matches_category_scope(term, transcript):
            continue
        correct_form = str(term.get("correct_form") or "").strip()
        category = str(term.get("category") or "").strip().lower()
        if not correct_form:
            continue
        if _is_brand_like_glossary_category(category):
            if not term.get("transcription_seed_templates"):
                continue
            display = _canonical_brand_display_name(correct_form)
            if display and display not in seed_brands:
                seed_brands.append(display)
        elif _is_model_like_glossary_category(category) or _looks_like_product_model(correct_form):
            if not term.get("transcription_seed_templates"):
                continue
            if correct_form not in seed_models:
                seed_models.append(correct_form)
        elif "包" in correct_form and correct_form not in seed_product_terms:
            seed_product_terms.append(correct_form)

    queries: list[str] = []
    for brand in seed_brands[:3]:
        for model in seed_models[:2]:
            queries.append(f"{brand} {model}")
        for product_term in seed_product_terms[:1]:
            queries.append(f"{brand} {product_term}")

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def _match_glossary_identity_candidate(
    *,
    normalized_transcript: str,
    correct_form: str,
    wrong_forms: list[Any],
) -> str:
    candidates = [correct_form, *(str(item or "").strip() for item in wrong_forms)]
    for candidate in candidates:
        normalized_candidate = _normalize_profile_value(candidate)
        if normalized_candidate and normalized_candidate in normalized_transcript:
            return candidate
    return ""


def _is_brand_like_glossary_category(category: str) -> bool:
    return "brand" in str(category or "")


def _is_model_like_glossary_category(category: str) -> bool:
    return "model" in str(category or "").strip().lower()


def _looks_like_product_model(value: str) -> bool:
    compact = _clean_line(value)
    if not compact:
        return False
    if re.search(r"[A-Za-z]", compact) and re.search(r"[\d零〇一二三四五六七八九十]", compact):
        return True
    return compact.endswith(("小副包", "副包", "Pro", "MAX", "Mini", "Ultra", "Plus", "SE"))


def _normalize_category_scopes(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = []
    scopes: list[str] = []
    for item in raw_items:
        text = str(item or "").strip().lower()
        if text and text not in scopes:
            scopes.append(text)
    return scopes


def _infer_category_scope_from_glossary_category(category: str) -> str:
    normalized = str(category or "").strip().lower()
    if "bag" in normalized:
        return "bag"
    if "flashlight" in normalized:
        return "flashlight"
    if "knife" in normalized:
        return "knife"
    if "tool" in normalized:
        return "tools"
    return ""


def _text_supports_category_scope(text: str, scope: str) -> bool:
    compact = str(text or "").strip()
    keywords = _CATEGORY_SCOPE_KEYWORDS.get(str(scope or "").strip().lower(), ())
    return bool(compact and any(keyword in compact for keyword in keywords))


def _glossary_term_matches_category_scope(term: dict[str, Any], transcript: str) -> bool:
    scopes = _normalize_category_scopes(term.get("category_scope"))
    inferred_scope = _infer_category_scope_from_glossary_category(str(term.get("category") or ""))
    if inferred_scope and inferred_scope not in scopes:
        scopes.append(inferred_scope)
    if not scopes:
        return True
    return any(_text_supports_category_scope(transcript, scope) for scope in scopes)


def _canonical_brand_display_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    english_tokens = re.findall(r"[A-Za-z]{2,}", text)
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,12}", text)
    if english_tokens and chinese_tokens:
        return "".join(text.split())
    if chinese_tokens:
        return chinese_tokens[-1]
    if english_tokens:
        return english_tokens[0].upper()
    return text


def _brand_cn_display_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    mapped = str(_BRAND_CN_DISPLAY_MAP.get(text) or "").strip()
    if mapped:
        return mapped
    chinese_tokens = re.findall(r"[\u4e00-\u9fff]{2,12}", text)
    if chinese_tokens:
        return chinese_tokens[-1]
    return ""


def _brand_bilingual_display_name(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if re.search(r"[\u4e00-\u9fff]", text) and re.search(r"[A-Za-z]", text):
        return "".join(text.split())
    cn_name = _brand_cn_display_name(text)
    if cn_name and cn_name != text:
        return f"{cn_name}{text}"
    return text


def _normalize_brand_display_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parenthetical_english = re.search(r"[（(]\s*([A-Za-z][A-Za-z0-9 .+-]{1,20})\s*[)）]", text)
    if parenthetical_english:
        return parenthetical_english.group(1).strip().upper()[:18]
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9 .+-]{1,20}", text):
        return text.strip().upper()[:18]
    if re.search(r"[\u4e00-\u9fff]", text) and re.search(r"[A-Za-z]", text):
        return "".join(text.split())[:18]
    return _clean_line(text)


def _brand_display_candidates(
    profile: dict[str, Any],
    *,
    prefer_bilingual: bool,
    include_canonical: bool = True,
) -> list[str]:
    ordered_keys = (
        ("subject_brand_bilingual", "subject_brand_cn", "subject_brand")
        if prefer_bilingual
        else ("subject_brand_cn", "subject_brand_bilingual", "subject_brand")
    )
    candidates: list[str] = []
    seen: set[str] = set()
    for key in ordered_keys:
        if key == "subject_brand" and not include_canonical:
            continue
        candidate = _normalize_brand_display_label(profile.get(key) or "")
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        candidates.append(candidate)
    return candidates


def _select_cover_brand_display(
    profile: dict[str, Any],
    *,
    visible_text: str,
    max_length: int,
    prefer_bilingual: bool,
) -> str:
    if max_length <= 0:
        return ""
    for candidate in _brand_display_candidates(profile, prefer_bilingual=prefer_bilingual):
        if len(candidate) <= max_length:
            return candidate

    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    compact_brand = _compact_brand_name(brand, visible_text=visible_text)
    if compact_brand:
        return compact_brand[:max_length]

    fallback_candidates = _brand_display_candidates(
        profile,
        prefer_bilingual=prefer_bilingual,
        include_canonical=False,
    )
    if fallback_candidates:
        return fallback_candidates[0][:max_length]
    return ""


def _brand_search_aliases(profile: dict[str, Any], *, include_canonical: bool = True) -> list[str]:
    aliases: list[str] = []
    seen: set[str] = set()
    for candidate in _brand_display_candidates(
        profile,
        prefer_bilingual=False,
        include_canonical=include_canonical,
    ):
        if candidate in seen:
            continue
        seen.add(candidate)
        aliases.append(candidate)
    return aliases


def _apply_brand_display_fields(profile: dict[str, Any]) -> dict[str, Any]:
    updated = dict(profile or {})
    brand = str(updated.get("subject_brand") or "").strip()
    if not brand:
        updated.pop("subject_brand_cn", None)
        updated.pop("subject_brand_bilingual", None)
        return updated
    cn_name = _brand_cn_display_name(brand)
    bilingual = _brand_bilingual_display_name(brand)
    if cn_name:
        updated["subject_brand_cn"] = cn_name
    else:
        updated.pop("subject_brand_cn", None)
    if bilingual and bilingual != brand:
        updated["subject_brand_bilingual"] = bilingual
    else:
        updated.pop("subject_brand_bilingual", None)
    return updated


def _subject_type_from_glossary_category(category: str) -> str:
    normalized = str(category or "").strip().lower()
    if "flashlight" in normalized:
        return "EDC手电"
    if "knife" in normalized:
        return "EDC折刀"
    if "bag" in normalized:
        return "EDC机能包"
    if "tool" in normalized:
        return "多功能工具钳"
    return ""


def _subject_type_search_anchor(subject_type: str) -> str:
    normalized = _clean_line(subject_type)
    if any(token in normalized for token in ("EDC", "折刀")):
        return "折刀"
    if "工具钳" in normalized:
        return "工具钳"
    if any(token in normalized for token in ("潮玩", "手办", "盲盒")):
        return "潮玩"
    return normalized[:8]


def _memory_value_matches_transcript(value: str, transcript: str, normalized: str) -> bool:
    if not value:
        return False
    upper = value.upper()
    if upper in normalized:
        return True
    compact = _clean_line(value)
    if compact and compact in _clean_line(transcript):
        return True
    return False


def _memory_keyword_matches_transcript(keyword: str, transcript: str, normalized: str) -> bool:
    if _memory_value_matches_transcript(keyword, transcript, normalized):
        return True

    tokens = [token.strip().upper() for token in keyword.split() if len(token.strip()) >= 3]
    if len(tokens) >= 2 and all(token in normalized for token in tokens[:2]):
        return True
    if len(tokens) == 1 and tokens[0] in normalized:
        return True
    return False


def _merge_specific_profile_hints(profile: dict[str, Any], hints: dict[str, Any]) -> None:
    if hints.get("subject_brand") and not profile.get("subject_brand"):
        profile["subject_brand"] = hints["subject_brand"]
    if hints.get("subject_model") and not profile.get("subject_model"):
        profile["subject_model"] = hints["subject_model"]

    current_queries = [str(item).strip() for item in profile.get("search_queries") or [] if str(item).strip()]
    for item in hints.get("search_queries") or []:
        value = str(item).strip()
        if value and value not in current_queries:
            current_queries.append(value)
    if current_queries:
        profile["search_queries"] = current_queries


def _identity_only_profile_hints(hints: dict[str, Any] | None) -> dict[str, Any]:
    candidate = hints if isinstance(hints, dict) else {}
    normalized_queries = [str(item).strip() for item in (candidate.get("search_queries") or []) if str(item).strip()]
    return {
        "subject_brand": str(candidate.get("subject_brand") or "").strip(),
        "subject_model": str(candidate.get("subject_model") or "").strip(),
        "search_queries": normalized_queries,
    }


def _is_generic_subject_type(text: str) -> bool:
    normalized = _clean_line(text)
    return normalized in {
        "",
        "开箱产品",
        "开箱",
        "开箱评测",
        "体验",
        "产品体验",
        "上手体验",
        "评测",
        "软件工具",
        "AI工具",
        "AI软件",
        "创作软件",
        "软件功能演示与教程",
    }


def _is_generic_profile_summary(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return True
    generic_fragments = (
        "围绕开箱产品展开",
        "偏产品开箱与上手体验",
        "适合后续做搜索校验、字幕纠错和剪辑包装",
    )
    return all(fragment in normalized for fragment in generic_fragments)


def _is_generic_engagement_question(text: str) -> bool:
    normalized = _clean_line(text).rstrip("？?")
    if not normalized:
        return True
    generic_questions = {
        "你觉得这次到手值不值",
        "你觉得值不值",
        "这次值不值",
        "你会买吗",
        "你会入手吗",
        "你怎么看",
    }
    return normalized in generic_questions


def _is_specific_video_theme(text: str, *, preset_name: str) -> bool:
    return _is_specific_video_theme_for_context(text, preset_name=preset_name, content_kind="", subject_domain="")


def _is_specific_video_theme_for_context(
    text: str,
    *,
    preset_name: str,
    content_kind: str,
    subject_domain: str,
) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return False
    if normalized in {
        "产品开箱与上手体验",
        "产品开箱评测",
        "新品开箱评测",
        "开箱评测",
        "开箱体验",
        "上手体验",
        "产品体验",
        "评测",
        "教程",
        "软件教程",
        "AI教程",
        "数码教程",
        "操作演示",
        "功能讲解",
        "步骤讲解",
        "流程演示",
    }:
        return False
    default_theme = _clean_line(
        _default_video_theme_by_context(
            preset_name=preset_name,
            content_kind=content_kind,
            subject_domain=subject_domain,
        )
    )
    if default_theme and normalized == default_theme:
        return False
    return len(normalized) >= 6 or any(
        token in normalized
        for token in (
            "升级",
            "限定",
            "联名",
            "教程",
            "步骤",
            "观点",
            "复盘",
            "高光",
            "探店",
            "试吃",
            "对比",
            "无限画布",
            "工作流",
            "节点",
            "新功能",
            "上线",
            "漫剧",
            "智能体",
        )
    )


def _should_replace_video_theme(
    *,
    current_video_theme: str,
    resolved_video_theme: str,
    preset_name: str,
    content_kind: str = "",
    subject_domain: str = "",
) -> bool:
    resolved = str(resolved_video_theme or "").strip()
    if not _is_specific_video_theme_for_context(
        resolved,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        return False
    current = str(current_video_theme or "").strip()
    if not _is_specific_video_theme_for_context(
        current,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        return True
    return _video_theme_specificity_score(resolved) > _video_theme_specificity_score(current)


def _video_theme_specificity_score(text: str) -> int:
    normalized = _clean_line(text)
    if not normalized:
        return 0
    score = 1
    informative_tokens = (
        "升级",
        "限定",
        "联名",
        "教程",
        "步骤",
        "观点",
        "复盘",
        "高光",
        "探店",
        "试吃",
        "对比",
        "横评",
        "无限画布",
        "工作流",
        "节点",
        "新功能",
        "上线",
        "漫剧",
        "智能体",
        "实测",
        "开箱",
        "上手",
    )
    generic_tokens = (
        "功能演示",
        "软件功能演示",
        "流程演示",
        "产品体验",
        "上手体验",
    )
    for token in informative_tokens:
        if token in normalized:
            score += 3
    for token in generic_tokens:
        if token in normalized:
            score -= 2
    if any(char.isdigit() for char in normalized):
        score += 1
    if re.search(r"(PRO|ULTRA|MAX|MINI|SE|PLUS|UV)", normalized, re.IGNORECASE):
        score += 1
    return score


async def _generate_engagement_question(
    *,
    profile: dict[str, Any],
    transcript_excerpt: str,
    evidence: list[dict[str, Any]],
    preset: WorkflowPreset,
    memory_prompt: str,
) -> str | None:
    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在给中文短视频设计评论区互动问题。"
            "请基于视频主体、主题、字幕线索和搜索证据，输出 1 条最适合这条视频的问题。"
            "要求：自然、具体、像真人会问的话，优先围绕升级点、争议点、购买决策、使用体验、教程卡点或口味判断。"
            "不要重复“你觉得值不值”这类泛化问题，除非视频核心真的就是价格值不值。"
            "不要输出多条，不要解释。\n"
            '输出 JSON：{"engagement_question":""}'
            f"\n当前视频信息：{json.dumps(profile, ensure_ascii=False)}"
            f"\n用户历史偏好（仅作辅助参考，不能压过当前视频）：\n{memory_prompt or '无'}"
            f"\n字幕节选：\n{transcript_excerpt or '无'}"
            f"\n搜索证据：{json.dumps(evidence[:6], ensure_ascii=False)}"
            f"\n预设：{preset.name} / {preset.label}"
        )
        with track_usage_operation("content_profile.engagement_question"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是中文短视频互动策划助手。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.3,
                max_tokens=160,
                json_mode=True,
            )
        question = _normalize_engagement_question(response.as_json().get("engagement_question") or "")
        if _is_generic_engagement_question(question):
            return None
        return question or None
    except Exception:
        return None


def _extract_reference_frames(source_path: Path, tmpdir: Path, *, count: int) -> list[Path]:
    import subprocess

    duration = _probe_duration(source_path)
    if duration <= 0:
        return []

    safe_margin = min(max(duration * 0.08, 1.0), max(duration / 4, 0.0))
    usable_start = safe_margin if duration > safe_margin * 2 else 0.0
    usable_end = duration - safe_margin if duration > safe_margin * 2 else duration
    usable_duration = max(usable_end - usable_start, duration)

    frames: list[Path] = []
    for i in range(count):
        segment_start = usable_start + (usable_duration * i / max(count, 1))
        segment_end = usable_start + (usable_duration * (i + 1) / max(count, 1))
        segment_length = max(segment_end - segment_start, 0.8)
        seek = max(segment_start + (segment_length / 2), 0.0)
        out = tmpdir / f"profile_{i:02d}.jpg"
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{segment_start:.2f}",
                "-t",
                f"{segment_length:.2f}",
                "-i",
                str(source_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                "-vf",
                "thumbnail=90,scale=960:-2",
                str(out),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0 or not out.exists():
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    f"{seek:.2f}",
                    "-i",
                    str(source_path),
                    "-frames:v",
                    "1",
                    "-update",
                    "1",
                    "-q:v",
                    "3",
                    "-vf",
                    "scale=960:-2",
                    str(out),
                ],
                capture_output=True,
                timeout=20,
            )
        if result.returncode == 0 and out.exists():
            frames.append(out)
    return frames


def _probe_duration(source_path: Path) -> float:
    import subprocess

    timeout_seconds = max(30, int(get_settings().ffmpeg_timeout_sec or 600))
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(source_path)],
        capture_output=True,
        timeout=timeout_seconds,
    )
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return 0.0
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def _fallback_profile(
    *,
    source_name: str,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    transcript_excerpt: str,
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    preset = select_workflow_template(
        workflow_template=workflow_template,
        transcript_hint=transcript_excerpt,
    )
    content_kind = preset.content_kind
    subject_domain = _infer_subject_domain_from_content(
        profile={
            "subject_type": _default_subject_type_for_preset(preset),
            "video_theme": _default_video_theme_for_preset(preset),
        },
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
    )
    subject_type = _default_subject_type_for_preset(preset)
    video_theme = _default_video_theme_by_context(
        preset_name=preset.name,
        content_kind=content_kind,
        subject_domain=str(subject_domain or ""),
    )
    engagement_question = _default_engagement_question(preset)
    return {
        "subject_brand": "",
        "subject_model": "",
        "content_kind": content_kind,
        "subject_domain": subject_domain,
        "subject_type": subject_type,
        "video_theme": video_theme,
        "workflow_template": preset.name,
        "preset": preset.to_dict(),
        "hook_line": preset.cover_accent,
        "summary": _build_profile_summary(
            {
                "subject_brand": "",
                "subject_model": "",
                "content_kind": content_kind,
                "subject_domain": subject_domain,
                "subject_type": subject_type,
                "video_theme": video_theme,
                "workflow_template": preset.name,
            }
        ),
        "engagement_question": engagement_question,
        "cover_title": build_cover_title(
            {
                "subject_brand": "",
                "subject_model": "",
                "subject_type": subject_type,
                "video_theme": video_theme,
                "hook_line": preset.cover_accent,
            },
            preset,
        ),
    }


def _normalize_engagement_question(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    value = re.sub(r"\s+", "", value).strip("，。！!；;：:")
    if not value:
        return ""
    if not value.endswith(("？", "?")):
        value = f"{value}？"
    return value


def _build_fallback_engagement_question(profile: dict[str, Any], preset: WorkflowPreset) -> str:
    theme = str(profile.get("video_theme") or "").strip()
    subject = _build_engagement_subject(profile, preset)
    focus_terms = _extract_profile_focus_terms(profile, limit=3)

    if _is_tutorial_preset(preset):
        return "这一步你平时最容易卡在哪？"
    if preset.name == "vlog_daily":
        return "这种日常节奏你还想看我拍哪一段？"
    if _is_commentary_preset(preset):
        return "这个判断你是赞同还是反对？"
    if preset.name == "gameplay_highlight":
        return "这波如果换你来打会怎么处理？"
    if preset.name == "food_explore":
        return "这家店你会为了这道菜专门跑一趟吗？"
    if len(focus_terms) >= 2 and any(token in theme for token in ("升级", "改款", "新版", "迭代")):
        return _normalize_engagement_question(f"{subject}这次升级你更在意{focus_terms[0]}还是{focus_terms[1]}")
    if len(focus_terms) >= 2:
        return _normalize_engagement_question(f"{subject}你更想先看{focus_terms[0]}还是{focus_terms[1]}")
    if any(token in theme for token in ("对比", "横评", "比较")):
        return _normalize_engagement_question(f"{subject}和上一版你更站哪边")
    if any(token in theme for token in ("升级", "改款", "新版", "迭代")):
        return _normalize_engagement_question(f"{subject}这次升级你最在意哪一项")
    if any(token in theme for token in ("限定", "联名", "纪念版", "特别版")):
        return _normalize_engagement_question(f"{subject}这版你会为了限定入手吗")
    if any(token in theme for token in ("体验", "上手", "实测")):
        return _normalize_engagement_question(f"{subject}第一眼你最想先看哪处细节")
    return _normalize_engagement_question(f"{subject}你最想先看哪项细节")


def _build_engagement_subject(profile: dict[str, Any], preset: WorkflowPreset) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    subject_type = str(profile.get("subject_type") or "").strip()
    if brand and model:
        return f"{brand} {model}".strip()[:18]
    if model:
        return model[:18]
    if brand and subject_type and not _is_generic_subject_type(subject_type):
        return f"{brand}{subject_type}"[:18]
    if subject_type and not _is_generic_subject_type(subject_type):
        return subject_type[:18]
    return preset.label[:18]


def _fallback_polish_text(
    text: str,
    *,
    glossary_terms: list[dict[str, Any]],
    review_memory: dict[str, Any] | None = None,
    prev_text: str = "",
    next_text: str = "",
    preserve_display_numbers: bool = False,
) -> str:
    polished = _apply_learned_phrase_preferences(text.strip(), review_memory)
    polished = _repair_common_intro_slot(polished)
    polished = _repair_collapsed_predicate_clause(polished, review_memory=review_memory)
    polished = _apply_contextual_phrase_rewrite(
        polished,
        review_memory=review_memory,
        prev_text=prev_text,
        next_text=next_text,
    )
    polished = _dedupe_repeated_domain_terms(polished, review_memory=review_memory)
    polished = _prune_low_signal_clauses(polished, review_memory=review_memory)
    polished = apply_glossary_terms(polished, glossary_terms)
    polished = _apply_explicit_review_aliases_for_polish(polished, review_memory=review_memory)
    polished = apply_domain_term_corrections(
        polished,
        review_memory,
        prev_text=prev_text,
        next_text=next_text,
    )
    polished = _repair_fragmentary_repetition(
        polished,
        prev_text=prev_text,
        next_text=next_text,
    )
    if get_settings().subtitle_filler_cleanup_enabled:
        polished = _remove_subtitle_filler_words(
            polished,
            prev_text=prev_text,
            next_text=next_text,
        )
    if preserve_display_numbers:
        polished = str(polished or "").strip()
        polished = _normalize_display_numbers_for_polish(polished)
        polished = apply_subtitle_clause_spacing(polished)
        polished = re.sub(r"\s+([，,。.!！？；;：:])", r"\1", polished)
        polished = re.sub(r"([，；：])(?=[^\s])", r"\1 ", polished)
        polished = re.sub(r"[，,]{2,}", "，", polished)
        polished = re.sub(r"[。.]{2,}", "。", polished)
        polished = re.sub(r"[，,]+([。.!！？])", r"\1", polished)
        polished = re.sub(r"\s{2,}", " ", polished).strip("，,")
    else:
        polished = normalize_display_text(
            polished,
            cleanup_fillers=get_settings().subtitle_filler_cleanup_enabled,
        )
    polished = _strip_terminal_punctuation_for_fragmentary_subtitle(
        original_text=text,
        polished_text=polished,
    )
    polished = re.sub(r"(。){2,}", "。", polished)
    polished = re.sub(r"(，){2,}", "，", polished)
    return polished


def _cleanup_polished_text(text: str, *, preserve_display_numbers: bool = False) -> str:
    if preserve_display_numbers:
        text = apply_subtitle_clause_spacing(str(text or "").strip())
        text = _normalize_display_numbers_for_polish(text)
        text = re.sub(r"\s+([，,。.!！？；;：:])", r"\1", text)
        text = re.sub(r"([，；：])(?=[^\s])", r"\1 ", text)
        text = re.sub(r"[，,]{2,}", "，", text)
        text = re.sub(r"[。.]{2,}", "。", text)
        text = re.sub(r"[，,]+([。.!！？])", r"\1", text)
        text = re.sub(r"\s{2,}", " ", text).strip("，,")
    else:
        text = normalize_display_text(text, cleanup_fillers=False)
    text = text.replace("「", "“").replace("」", "”")
    text = re.sub(r"[!！]{2,}", "！", text)
    text = re.sub(r"[?？]{2,}", "？", text)
    return text


_FRAGMENTARY_SUBTITLE_ENDINGS = (
    "如果",
    "因为",
    "所以",
    "但是",
    "然后",
    "或者",
    "以及",
    "比如",
    "比如说",
    "这边",
    "这里",
    "这个",
    "那个",
    "这种",
    "这样",
    "那种",
    "那些",
    "这些",
    "一点",
    "一下",
)
_FRAGMENTARY_SUBTITLE_END_CHARS = tuple("的了着呢吧啊吗呀哦嘛呗喽啦么我你他她它们这那要会能可把给在对向从到为被和跟与及或而但又再还也就是去来看的做用说买拆装")


def _strip_terminal_punctuation_for_fragmentary_subtitle(*, original_text: str, polished_text: str) -> str:
    source = str(original_text or "").strip()
    result = str(polished_text or "").strip()
    if not source or not result:
        return result
    if re.search(r"[。.!！？?…]$", source):
        return result
    compact = re.sub(r"\s+", "", source)
    if not compact:
        return result
    if compact.endswith(_FRAGMENTARY_SUBTITLE_END_CHARS) or any(
        compact.endswith(suffix) for suffix in _FRAGMENTARY_SUBTITLE_ENDINGS
    ):
        return re.sub(r"[。.!！？?…]+$", "", result)
    return result


def _normalize_display_numbers_for_polish(text: str) -> str:
    return normalize_display_numbers(str(text or "").strip())


def _apply_explicit_review_aliases_for_polish(text: str, *, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    for item in (review_memory or {}).get("aliases") or []:
        wrong = str(item.get("wrong") or "").strip()
        correct = str(item.get("correct") or "").strip()
        category = str(item.get("category") or "").strip()
        if not wrong or not correct:
            continue
        if category and category != "confirmed_subject":
            continue
        result = re.sub(re.escape(wrong), correct, result, flags=re.IGNORECASE)
    return result


def _remove_subtitle_filler_words(text: str, *, prev_text: str = "", next_text: str = "") -> str:
    result = cleanup_subtitle_fillers(text)
    if not result:
        return str(text or "").strip()
    return result


def _apply_learned_phrase_preferences(text: str, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    phrases = [
        str(item.get("phrase") or "").strip()
        for item in (review_memory or {}).get("phrase_preferences") or []
        if item.get("phrase")
    ]
    for phrase in phrases:
        result = apply_domain_term_corrections(
            result,
            {
                "terms": [{"term": phrase}],
                "aliases": [],
                "style_examples": [],
            },
        )
    return result


def _repair_common_intro_slot(text: str) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    result = re.sub(r"^这(?:7|七|几)个(?:咱|我)?给大家讲讲", "这期给大家讲讲", result)
    match = re.match(r"^这[\u4e00-\u9fff]{1,4}在(?P<rest>.+给大家(?:单独)?看[下看]?)", result)
    if match and "一期" not in result[:6]:
        return f"这一期在{match.group('rest')}"
    return result


def _repair_fragmentary_repetition(text: str, *, prev_text: str = "", next_text: str = "") -> str:
    result = str(text or "").strip()
    if not result:
        return result

    repeated_phrase = _collapse_repeated_phrase_prefix(result)
    if repeated_phrase:
        result = repeated_phrase

    prev_compact = str(prev_text or "").strip().rstrip("。！？!?；;,，：:")
    next_compact = str(next_text or "").strip()

    overlap = _shared_boundary_overlap(prev_compact, result, max_overlap=8)
    if overlap and len(overlap) >= 4 and len(result) >= len(overlap) + 2:
        result = result[len(overlap):].lstrip("，。！？!?、：:；;,. ")

    if (
        prev_compact
        and result
        and prev_compact[-1] == result[0]
        and prev_compact[-1] in "讲说看聊提做用谈"
        and len(result) >= 2
        and result[1] in "也就是了啊呢嘛吧"
    ):
        result = result[1:].lstrip("，。！？!?、：:；;,. ")

    trailing_particle_match = re.match(r"^(?P<body>.+?)(?P<tail>[那啊呢嘛吧呀呃])$", result)
    if trailing_particle_match and next_compact:
        body = trailing_particle_match.group("body")
        for size in range(min(4, len(body)), 1, -1):
            if next_compact.startswith(body[-size:]):
                result = body
                break

    return result or str(text or "").strip()


def _collapse_repeated_phrase_prefix(text: str) -> str:
    candidate = str(text or "").strip()
    if len(candidate) < 8:
        return ""
    suffix = ""
    if candidate and candidate[-1] in "。！？!?；;":
        suffix = candidate[-1]
        candidate = candidate[:-1]
    for unit_len in range(min(16, len(candidate) // 2), 3, -1):
        prefix = candidate[:unit_len]
        if not candidate.startswith(prefix * 2):
            continue
        tail = candidate[unit_len * 2:]
        if len(tail) <= 2 and re.fullmatch(r"[那啊呢嘛吧呀呃]*", tail):
            return f"{prefix}{tail}{suffix}"
    return ""


def _shared_boundary_overlap(left: str, right: str, *, max_overlap: int = 8) -> str:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return ""
    upper = min(max_overlap, len(left_text), len(right_text))
    for size in range(upper, 3, -1):
        suffix = left_text[-size:]
        if right_text.startswith(suffix):
            return suffix
    return ""


def _repair_collapsed_predicate_clause(text: str, *, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    match = re.match(r"^(?P<subject>[\u4e00-\u9fffA-Za-z0-9-]{2,8})(?P<predicate>会更加|会更)(?P<tail>[\u4e00-\u9fff]{1,4})(?P<suffix>[。！？，,]?.*)$", result)
    if not match:
        return result
    tail = match.group("tail")
    if _clause_has_learned_signal(tail, review_memory=review_memory):
        return result
    if any(token in tail for token in ("镜面", "顶配", "次顶配", "折刀", "钢马", "MT-33", "LEATHERMAN", "NOC", "REATE")):
        return result
    if len(tail) <= 4:
        return f"{match.group('subject')}会更好{match.group('suffix')}"
    return result


def _apply_contextual_phrase_rewrite(
    text: str,
    *,
    review_memory: dict[str, Any] | None,
    prev_text: str,
    next_text: str,
) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    phrase_items = list((review_memory or {}).get("phrase_preferences") or [])
    if not phrase_items:
        return result

    slot_match = re.match(r"^(?P<prefix>.*?(?:还是这个|先看这个|先看这把|先看这款))(?P<body>.*?)(?P<suffix>[吧啊呢了。！？，,]*)$", result)
    if not slot_match:
        return result

    body = slot_match.group("body").strip("，,。！？!?. ")
    if not body or len(body) > 12:
        return result

    for item in phrase_items:
        phrase = str(item.get("phrase") or "").strip()
        if not phrase or len(phrase) < 4 or len(phrase) > 18:
            continue
        if _phrase_can_fill_sentence_slot(phrase, body, prev_text=prev_text, next_text=next_text):
            prefix = slot_match.group("prefix")
            suffix = slot_match.group("suffix") or ""
            return f"{prefix}{phrase}{suffix or '。'}"
    return result


def _prune_low_signal_clauses(text: str, *, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    if ",我是来看" in result:
        result = result.split(",我是来看", 1)[0]
    if "，我是来看" in result:
        result = result.split("，我是来看", 1)[0]
    clauses = [part.strip() for part in re.split(r"([，。！？!?])", result) if part.strip()]
    if len(clauses) <= 1:
        return result

    rebuilt: list[str] = []
    current = ""
    for part in clauses:
        if re.fullmatch(r"[，。！？!?]", part):
            if current:
                rebuilt.append(current + part)
                current = ""
            continue
        current = part
    if current:
        rebuilt.append(current)

    kept = [clause for clause in rebuilt if not _looks_like_low_signal_clause(clause, review_memory=review_memory)]
    if not kept:
        kept = [rebuilt[0]]
    pruned = "".join(kept)
    if ",我是来看" in pruned:
        pruned = pruned.split(",我是来看", 1)[0]
    if "，我是来看" in pruned:
        pruned = pruned.split("，我是来看", 1)[0]
    pruned = re.sub(r"[，,](?:其实|也算|我是来看|我来看|见)[^。！？!?]*$", "", pruned)
    pruned = re.sub(r"[，,](?:其实|也算|我是来看|我来看|见)[^，。！？!?]*", "", pruned)
    pruned = re.sub(r"[，,](?:这就是|就是这个|就是这样)[^，。！？!?]*", "", pruned)
    pruned = re.sub(r"(?:^|[。！？!?])(?:其实|也算|见)[^。！？!?]*[。！？!?]?", lambda m: "" if m.start() > 0 else m.group(0), pruned)
    return pruned or "".join(kept)


def _phrase_can_fill_sentence_slot(phrase: str, body: str, *, prev_text: str, next_text: str) -> bool:
    components = _extract_compound_components(phrase)
    if len(components) < 2:
        return False
    joined_context = f"{prev_text} {body} {next_text}"
    hits = 0
    for component in components:
        if component in joined_context:
            hits += 1
            continue
        normalized = apply_domain_term_corrections(
            body,
            {
                "terms": [{"term": component}],
                "aliases": [],
                "style_examples": [],
            },
        )
        if component in normalized:
            hits += 1
    return hits >= 1


def _looks_like_low_signal_clause(text: str, *, review_memory: dict[str, Any] | None) -> bool:
    clause = _cleanup_polished_text(text)
    if not clause:
        return True
    if len(clause) <= 1:
        return True
    if clause in {"见。", "见", "这个。", "这个", "一期。", "一期"}:
        return True
    if clause.count("其实") >= 1 and len(clause) <= 10:
        return True
    if clause.count("也算") >= 1 and len(clause) <= 12:
        return True
    if _is_repetitive_fragment(clause):
        return True
    if len(clause) <= 8 and not _clause_has_learned_signal(clause, review_memory=review_memory):
        filler_hits = sum(1 for token in ("这个", "那个", "其实", "就是", "然后", "一个", "一期", "一下", "也算", "来看") if token in clause)
        if filler_hits >= 2:
            return True
    return False


def _is_repetitive_fragment(text: str) -> bool:
    compact = _cleanup_polished_text(text)
    if len(compact) < 6:
        return False
    tokens = [token for token in re.findall(r"[\u4e00-\u9fff]{1,4}|[A-Za-z0-9-]{2,}", compact) if token]
    if len(tokens) < 3:
        return False
    unique = set(tokens)
    return len(unique) <= max(1, len(tokens) // 2)


def _clause_has_learned_signal(text: str, *, review_memory: dict[str, Any] | None) -> bool:
    clause = str(text or "")
    for item in (review_memory or {}).get("terms") or []:
        term = str(item.get("term") or "").strip()
        if term and term in clause:
            return True
    for item in (review_memory or {}).get("phrase_preferences") or []:
        phrase = str(item.get("phrase") or "").strip()
        if phrase and any(component in clause for component in _extract_compound_components(phrase)):
            return True
    return False


def _dedupe_repeated_domain_terms(text: str, *, review_memory: dict[str, Any] | None) -> str:
    result = str(text or "").strip()
    if not result:
        return result
    candidates: list[str] = []
    for item in (review_memory or {}).get("terms") or []:
        term = str(item.get("term") or "").strip()
        if 2 <= len(term) <= 8:
            candidates.append(term)
    for term in sorted(set(candidates), key=len, reverse=True):
        pattern = re.compile(rf"({re.escape(term)})(?:和这个|这个|和|跟)+({re.escape(term)})")
        result = pattern.sub(term, result)
    return result


def _is_safe_subtitle_polish(
    *,
    original_text: str,
    polished_text: str,
    prev_text: str,
    next_text: str,
    glossary_terms: list[dict[str, Any]],
    review_memory: dict[str, Any] | None,
    content_profile: dict[str, Any],
) -> bool:
    original = _cleanup_polished_text(original_text, preserve_display_numbers=True)
    polished = _cleanup_polished_text(polished_text, preserve_display_numbers=True)
    if not original or not polished:
        return False
    if polished == original:
        return True

    if len(original) >= 8:
        if len(polished) > max(len(original) + 10, int(len(original) * 1.6)):
            return False
        if len(polished) < max(2, int(len(original) * 0.45)):
            return False

    similarity = SequenceMatcher(None, _subtitle_guard_text(original), _subtitle_guard_text(polished)).ratio()
    if similarity < 0.42:
        return False

    allowed_tokens = _collect_allowed_subtitle_tokens(
        original_text=original,
        prev_text=prev_text,
        next_text=next_text,
        glossary_terms=glossary_terms,
        review_memory=review_memory,
        content_profile=content_profile,
    )
    introduced_tokens = [
        token for token in _extract_guard_tokens(polished)
        if token not in allowed_tokens and token not in _extract_guard_tokens(original)
    ]
    return len(introduced_tokens) < 2


def _collect_allowed_subtitle_tokens(
    *,
    original_text: str,
    prev_text: str,
    next_text: str,
    glossary_terms: list[dict[str, Any]],
    review_memory: dict[str, Any] | None,
    content_profile: dict[str, Any],
) -> set[str]:
    allowed: set[str] = set()
    for text in (original_text, prev_text, next_text):
        allowed.update(_extract_guard_tokens(text))

    for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "visible_text"):
        allowed.update(_extract_guard_tokens(str(content_profile.get(key) or "")))

    for term in glossary_terms:
        allowed.update(_extract_guard_tokens(str(term.get("correct_form") or "")))
        for wrong_form in term.get("wrong_forms") or []:
            allowed.update(_extract_guard_tokens(str(wrong_form or "")))

    for item in (review_memory or {}).get("aliases") or []:
        allowed.update(_extract_guard_tokens(str(item.get("wrong") or "")))
        allowed.update(_extract_guard_tokens(str(item.get("correct") or "")))

    for item in (review_memory or {}).get("terms") or []:
        allowed.update(_extract_guard_tokens(str(item.get("term") or "")))

    return allowed


def _subtitle_guard_text(text: str) -> str:
    return re.sub(r"[，。！？、,.!?\s]+", "", str(text or "").strip())


def _extract_guard_tokens(text: str) -> set[str]:
    return {
        token.strip().upper()
        for token in re.findall(r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9+-]{1,23})(?![A-Za-z0-9])", str(text or ""))
        if len(token.strip()) >= 2
    }


def _clean_line(text: str) -> str:
    return _clean_line_keywords(text)


def _looks_like_camera_stem(text: str) -> bool:
    return _looks_like_camera_stem_keywords(text)


def _is_informative_source_hint(text: str) -> bool:
    return _is_informative_source_hint_keywords(text)


def _cover_title_is_usable(cover_title: dict[str, Any]) -> bool:
    main = _clean_line(cover_title.get("main") or "")
    return bool(main and not _is_generic_cover_line(main))


def _dedupe_cover_title_lines(
    cover_title: dict[str, str],
    *,
    preserve_top: bool = False,
) -> dict[str, str]:
    top = " ".join(str(cover_title.get("top") or "").strip().split())
    main = " ".join(str(cover_title.get("main") or "").strip().split())
    bottom = " ".join(str(cover_title.get("bottom") or "").strip().split())

    top_norm = _normalize_cover_line(top)
    main_norm = _normalize_cover_line(main)
    bottom_norm = _normalize_cover_line(bottom)

    if (
        not preserve_top
        and top_norm
        and main_norm
        and (main_norm == top_norm or main_norm.startswith(top_norm))
    ):
        top = ""
    if bottom_norm and main_norm and bottom_norm == main_norm:
        bottom = ""

    return {
        "top": top[:14],
        "main": main[:18],
        "bottom": bottom[:18],
    }


def _normalize_cover_line(text: str) -> str:
    return "".join(ch for ch in _clean_line(text).upper() if ch.isalnum() or "\u4e00" <= ch <= "\u9fff")


def _is_brand_like_cover_label(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return False
    return bool(re.fullmatch(r"[A-Z]{2,14}", normalized))


def _is_generic_cover_line(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return True
    generic_fragments = (
        "开箱产品",
        "开箱评测",
        "产品开箱",
        "上手体验",
        "开箱体验",
        "产品体验",
        "实拍体验",
        "简单开箱",
        "工具钳具体型号未知",
        "具体型号未知",
        "软件工具",
        "AI工具",
        "软件教程",
        "功能演示",
        "软件功能演示",
        "体验分享",
        "详细介绍",
        "教程演示",
        "使用教程",
        "新功能介绍",
        "功能介绍",
        "内容分享",
        "流程演示",
    )
    return any(fragment in normalized for fragment in generic_fragments)


def _pick_cover_top(
    *,
    brand: str,
    brand_label: str = "",
    subject_type: str,
    visible_text: str,
    preset: WorkflowPreset,
    anchor: dict[str, str] | None = None,
) -> str:
    anchor_brand = _clean_line((anchor or {}).get("brand") or "")
    if anchor_brand:
        return anchor_brand[:14]
    normalized_brand_label = _normalize_brand_display_label(brand_label)
    if normalized_brand_label:
        return normalized_brand_label[:14]
    compact_brand = _compact_brand_name(brand, visible_text=visible_text)
    if compact_brand:
        return compact_brand
    if subject_type:
        return subject_type[:14]
    if _is_tutorial_preset(preset):
        return "教程"
    if preset.name == "vlog_daily":
        return "VLOG"
    if _is_commentary_preset(preset):
        return "观点"
    if preset.name == "gameplay_highlight":
        return "高能"
    if preset.name == "food_explore":
        return "探店"
    return "开箱"


def _pick_cover_main(
    *,
    brand: str,
    brand_label: str = "",
    model: str,
    subject_type: str,
    theme: str,
    visible_text: str,
    preset: WorkflowPreset,
    anchor: dict[str, str] | None = None,
) -> str:
    candidate_model = _clean_line(model)
    if candidate_model and not _looks_like_camera_stem(candidate_model) and not _is_generic_cover_line(candidate_model):
        return candidate_model

    anchor_main = " ".join(str((anchor or {}).get("main") or "").strip().split())
    if anchor_main and not _is_generic_cover_line(anchor_main):
        return anchor_main[:18]

    display_subject_type = _cover_subject_type_label(subject_type)
    compact_brand = _normalize_brand_display_label(brand_label) or _compact_brand_name(
        brand,
        visible_text=visible_text,
    )
    if compact_brand and display_subject_type:
        return f"{compact_brand}{display_subject_type}"[:18]

    if display_subject_type:
        if "工具钳" in display_subject_type:
            return "高价工具钳开箱"
        return display_subject_type[:18]

    if theme and not _is_generic_cover_line(theme):
        specific_topic = _extract_specific_cover_topic(theme)
        if specific_topic:
            return specific_topic[:18]
        return theme[:18]

    return preset.label[:18]


def _extract_cover_entity_anchor(
    *,
    brand: str,
    model: str,
    subject_type: str,
    theme: str,
    visible_text: str,
    brand_top_label: str = "",
    brand_main_label: str = "",
) -> dict[str, str]:
    cleaned_brand = _clean_line(brand)
    cleaned_model = _clean_line(model)
    if _is_generic_cover_line(cleaned_model):
        cleaned_model = ""
    display_subject_type = _cover_subject_type_label(subject_type)
    anchor_brand = _normalize_brand_display_label(brand_top_label) or _compact_brand_name(
        cleaned_brand,
        visible_text=visible_text,
    )
    anchor_main_brand = _normalize_brand_display_label(brand_main_label) or cleaned_brand

    if cleaned_brand and cleaned_model and display_subject_type:
        return {
            "brand": anchor_brand[:14],
            "main": f"{anchor_main_brand} {cleaned_model}{display_subject_type}".replace("  ", " ").strip(),
        }
    if cleaned_brand and cleaned_model:
        return {
            "brand": anchor_brand[:14],
            "main": f"{anchor_main_brand} {cleaned_model}".replace("  ", " ").strip(),
        }

    if not theme or not display_subject_type:
        return {}

    prefix = _extract_theme_prefix_before_subject(theme, display_subject_type)
    if not prefix:
        return {}

    normalized_prefix = " ".join(str(prefix).strip().split()).strip(" -")
    if not normalized_prefix:
        return {}

    brand_hint = _extract_anchor_brand(normalized_prefix)
    return {
        "brand": brand_hint,
        "main": f"{normalized_prefix}{display_subject_type}".strip()[:18],
    }


def _extract_theme_prefix_before_subject(theme: str, subject_type_label: str) -> str:
    theme_text = str(theme or "").strip().strip("，。！？：:;；、")
    subject_clean = _clean_line(subject_type_label)
    if not theme_text or not subject_clean:
        return ""
    match = re.search(rf"(.{{1,20}}?){re.escape(subject_clean)}", theme_text, re.IGNORECASE)
    if not match:
        return ""
    prefix = match.group(1)
    prefix = re.split(r"(细节展示|开箱详解|开箱评测|评测|测评|体验|上手|展示)", prefix)[0]
    prefix = prefix.strip(" ·-_")
    if not prefix:
        return ""
    if len(prefix) > 16:
        return ""
    return prefix


def _extract_anchor_brand(prefix: str) -> str:
    match = re.match(r"([A-Za-z]{2,12})(?=$|[\s-])", prefix)
    if not match:
        return ""
    return match.group(1).upper()[:14]


def _extract_specific_cover_topic(theme: str) -> str:
    normalized = _clean_line(theme)
    for label, pattern in _TECH_TOPIC_PATTERNS:
        if pattern.search(normalized):
            return label
    if "新功能" in normalized and "上线" in normalized:
        return "新功能上线"
    return ""


def _build_cover_hook(
    *,
    hook: str,
    brand: str,
    model: str,
    subject_type: str,
    theme: str,
    transcript_excerpt: str,
    copy_style: str,
    preset: WorkflowPreset,
) -> str:
    cleaned_hook = _clean_line(hook)
    if cleaned_hook and not _is_generic_cover_line(cleaned_hook):
        explosive = _upgrade_cover_hook(
            cleaned_hook,
            brand=brand,
            model=model,
            subject_type=subject_type,
            theme=theme,
            copy_style=copy_style,
            preset=preset,
        )
        if explosive:
            return explosive

    fallback = ""
    if _is_tutorial_preset(preset):
        fallback = _build_screen_tutorial_cover_hook(
            brand=brand,
            model=model,
            subject_type=subject_type,
            theme=theme,
            copy_style=copy_style,
        )
    elif _is_unboxing_preset(preset):
        fallback = _build_unboxing_cover_hook(theme=theme, transcript_excerpt=transcript_excerpt)
    else:
        fallback = preset.cover_accent
    return _apply_copy_style_to_hook(
        fallback,
        copy_style=copy_style,
        brand=brand,
        model=model,
        subject_type=subject_type,
    )


def _upgrade_cover_hook(
    hook: str,
    *,
    brand: str,
    model: str,
    subject_type: str,
    theme: str,
    copy_style: str,
    preset: WorkflowPreset,
) -> str:
    if _is_tutorial_preset(preset):
        boosted = _build_screen_tutorial_cover_hook(
            brand=brand,
            model=model,
            subject_type=subject_type,
            theme=theme,
            copy_style=copy_style,
            raw_hook=hook,
        )
        if boosted:
            return boosted
    return _apply_copy_style_to_hook(
        hook,
        copy_style=copy_style,
        brand=brand,
        model=model,
        subject_type=subject_type,
    )


def _build_screen_tutorial_cover_hook(
    *,
    brand: str,
    model: str,
    subject_type: str,
    theme: str,
    copy_style: str,
    raw_hook: str = "",
) -> str:
    theme_text = _clean_line(theme)
    if model == "无限画布" or "无限画布" in theme_text:
        if any(token in theme_text for token in ("上线", "新功能", "更新")):
            return _apply_copy_style_to_hook("这功能强得离谱", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
        if any(token in theme_text for token in ("漫剧", "短剧")):
            return _apply_copy_style_to_hook("漫剧产能直接拉满", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
        return _apply_copy_style_to_hook("这功能太变态了", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
    if "节点编排" in theme_text or "工作流" in theme_text:
        if any(token in theme_text for token in ("实操", "教程", "演示")):
            return _apply_copy_style_to_hook("核心流程直接起飞", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
        return _apply_copy_style_to_hook("工作流直接封神", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
    if "智能体" in theme_text:
        return _apply_copy_style_to_hook("这套编排太狠了", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
    if raw_hook:
        raw = _clean_line(raw_hook)
        if any(token in raw for token in ("终于", "直接", "真能", "讲透", "上手", "离谱", "炸裂", "封神", "起飞", "太狠")):
            return _apply_copy_style_to_hook(raw, copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)
        if brand and model:
            return _apply_copy_style_to_hook(f"{model}这次太炸了", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)[:18]
    if brand and model:
        return _apply_copy_style_to_hook(f"{model}这次太炸了", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)[:18]
    if subject_type and not _is_generic_subject_type(subject_type):
        return _apply_copy_style_to_hook(f"{subject_type}太狠了", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)[:18]
    return _apply_copy_style_to_hook("这波效果太夸张", copy_style=copy_style, brand=brand, model=model, subject_type=subject_type)


def _focus_terms_to_cover_hook(focus_terms: list[str]) -> str:
    if len(focus_terms) >= 2 and focus_terms[0] == "分仓" and focus_terms[1] == "挂点":
        return "分仓挂点直接看"
    mapping = {
        "锁定机构": "锁定机构直接看",
        "开合": "开合手感直接看",
        "钳头": "钳头结构直接看",
        "分仓": "分仓设计直接看",
        "挂点": "挂点细节直接看",
        "收纳": "收纳装载直接看",
        "做工": "做工细节直接看",
        "结构": "结构变化直接看",
        "材质": "材质差异直接看",
        "细节": "关键细节直接看",
        "手感": "上手手感直接看",
        "泛光": "泛光表现直接看",
        "聚光": "聚光效果直接看",
        "UV": "UV表现直接看",
        "亮度": "亮度表现直接看",
    }
    for term in focus_terms:
        if term in mapping:
            return mapping[term]
    return ""


def _build_unboxing_cover_hook(*, theme: str, transcript_excerpt: str = "") -> str:
    theme_text = _clean_line(theme)
    focus_terms = _extract_profile_focus_terms(
        {
            "video_theme": theme,
            "transcript_excerpt": transcript_excerpt,
        },
        limit=2,
    )
    focus_hook = _focus_terms_to_cover_hook(focus_terms)
    if focus_hook:
        return focus_hook
    if any(token in theme_text for token in ("限定", "联名", "纪念版", "特别版")):
        return "限定细节值不值"
    if any(token in theme_text for token in ("做工", "结构", "拆解", "材质")):
        return "做工结构直接看"
    return "这次升级够不够狠"


def _is_tutorial_preset(preset: WorkflowPreset) -> bool:
    content_kind = str(getattr(preset, "content_kind", "") or "").strip().lower()
    return content_kind == "tutorial" or preset.name in {"screen_tutorial", "tutorial_standard"}


def _is_unboxing_preset(preset: WorkflowPreset) -> bool:
    content_kind = str(getattr(preset, "content_kind", "") or "").strip().lower()
    return content_kind == "unboxing" or preset.name in {"unboxing_standard", "edc_tactical"}


def _is_commentary_preset(preset: WorkflowPreset) -> bool:
    content_kind = str(getattr(preset, "content_kind", "") or "").strip().lower()
    return content_kind == "commentary" or preset.name in {"commentary_focus", "talking_head_commentary"}


def _apply_copy_style_to_hook(
    hook: str,
    *,
    copy_style: str,
    brand: str,
    model: str,
    subject_type: str,
) -> str:
    base = _clean_line(hook)
    normalized_model = _clean_line(model)
    if normalized_model and _is_generic_cover_line(normalized_model):
        normalized_model = ""
    subject = _clean_line(normalized_model or brand or subject_type)
    base = _boost_cover_click_phrase(base, subject=subject)
    if copy_style == "balanced":
        if "离谱" in base or "变态" in base or "炸" in base or "封神" in base:
            return "这次重点讲透了"
        if "拉满" in base or "起飞" in base:
            return "核心流程讲清了"
        return base or "这次重点说清楚"
    if copy_style == "premium_editorial":
        return "这次细节很值得看" if not subject else f"{subject}这次很值得看"[:18]
    if copy_style == "trusted_expert":
        return "关键差异讲明白" if not subject else f"{subject}关键差异讲明白"[:18]
    if copy_style == "playful_meme":
        return "这波真的杀疯了" if not subject else f"{subject}直接杀疯了"[:18]
    if copy_style == "emotional_story":
        return "这次真的等太久了" if not subject else f"为了{subject}我真等很久"[:18]
    return base or "这波效果太夸张"


def _boost_cover_click_phrase(text: str, *, subject: str) -> str:
    normalized = _clean_line(text)
    if not normalized:
        return normalized
    if any(token in normalized for token in ("升级", "够不够", "值不值", "重点", "细节", "讲透", "直接看")):
        return normalized[:18]

    boring_to_hot = {
        "先看结论": "结论太炸了",
        "重点讲清楚": "重点直接讲透",
        "重点讲明白": "重点一把讲透",
        "关键点讲清楚": "关键点直接拉满",
        "这次很能打": "这次强得离谱",
        "这次很顶": "这次直接起飞",
        "高级感拉满": "高级感直接封神",
        "细节很加分": "细节直接封神",
        "整体更顺眼": "这次顺眼到离谱",
        "关键差异讲明白": "差异一眼炸出来",
    }
    for old, new in boring_to_hot.items():
        if old in normalized:
            return normalized.replace(old, new)[:18]

    hot_tokens = ("离谱", "封神", "炸", "炸裂", "起飞", "拉满", "太狠", "变态", "绝了", "上头", "杀疯")
    if any(token in normalized for token in hot_tokens):
        return normalized[:18]

    if subject:
        return (f"{subject}强得离谱" if len(subject) <= 8 else f"{subject}太炸了")[:18]
    return "这次太炸了"


def _compact_brand_name(brand: str, *, visible_text: str) -> str:
    value = _clean_line(brand)
    if not value:
        return _pick_visible_brand(visible_text)

    english_match = re.search(r"[A-Za-z][A-Za-z0-9 .+-]{1,20}", value)
    if english_match:
        return english_match.group(0).strip().upper()[:14]

    if "（" in value and "）" in value:
        outside = value.split("（", 1)[0].strip()
        if outside:
            return outside[:14]
    return value[:14]


def _cover_subject_type_label(subject_type: str) -> str:
    value = _clean_line(subject_type)
    if not value:
        return ""
    if value.startswith("EDC") and len(value) > 3:
        value = value[3:]
    return value


def _pick_visible_brand(visible_text: str) -> str:
    match = re.search(r"[A-Za-z][A-Za-z0-9+-]{2,20}", visible_text or "")
    if not match:
        return ""
    return match.group(0).strip().upper()[:14]


def _summary_theme_fragment(
    theme: str,
    *,
    brand: str,
    model: str,
    preset_name: str,
    content_kind: str = "",
    subject_domain: str = "",
) -> str:
    raw_cleaned = _clean_line(theme)
    if brand or model:
        cleaned = _strip_identity_tokens_from_text(
            theme,
            brand=brand,
            model=model,
        )
    else:
        cleaned = raw_cleaned
    if not cleaned and raw_cleaned and _is_specific_video_theme_for_context(
        raw_cleaned,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        return raw_cleaned
    if _is_specific_video_theme_for_context(
        cleaned,
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    ):
        return cleaned
    fallback = _default_video_theme_by_context(
        preset_name=preset_name,
        content_kind=content_kind,
        subject_domain=subject_domain,
    )
    return str(fallback or "").strip()


def _extract_query_support_terms(text: str) -> list[str]:
    return _extract_query_support_terms_keywords(text)


def _build_neutral_profile_summary() -> str:
    return "这条视频当前主题待进一步确认，建议结合字幕、画面文字和人工核对后再继续包装。"


def _build_theme_preserving_summary(theme: str) -> str:
    return f"这条视频主要围绕{theme}展开，主体品牌型号待进一步确认，建议先结合字幕、画面文字和人工核对后再继续包装。"


def _build_profile_summary(profile: dict[str, Any]) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    preset_name = _workflow_template_name(profile)
    content_kind = _content_kind_name(profile)
    subject_domain = str(profile.get("subject_domain") or "").strip()
    subject_type = str(profile.get("subject_type") or _default_subject_type_by_name(preset_name or content_kind)).strip()
    theme = _summary_theme_fragment(
        str(profile.get("video_theme") or ""),
        brand=brand,
        model=model,
        preset_name=preset_name or content_kind,
        content_kind=content_kind,
        subject_domain=subject_domain,
    )
    default_theme = _clean_line(
        _default_video_theme_by_context(
            preset_name=preset_name or content_kind,
            content_kind=content_kind,
            subject_domain=subject_domain,
        )
    )
    theme_norm = _normalize_profile_value(theme)
    if brand and _normalize_profile_value(brand) in theme_norm:
        theme = default_theme
        theme_norm = _normalize_profile_value(theme)
    if model and _normalize_profile_value(model) in theme_norm:
        theme = default_theme
    if not brand and not model and _is_generic_subject_type(subject_type):
        if theme and _clean_line(theme) != default_theme:
            return _build_theme_preserving_summary(theme)
        return _build_neutral_profile_summary()
    parts = [part for part in (brand, model or subject_type) if part]
    product = " ".join(parts).strip() or subject_type
    if content_kind == "tutorial":
        return f"这条视频主要围绕{product}的操作演示展开，内容方向偏{theme}，重点是步骤清晰、术语准确，方便后续剪成可跟做的教程。"
    if content_kind == "vlog":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是保留生活感、场景切换和真实情绪。"
    if content_kind == "commentary":
        return f"这条视频主要围绕{product}展开表达，内容方向偏{theme}，重点是观点钩子、论点节奏和结论清晰。"
    if content_kind == "gameplay":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是高能操作、关键节点和结果反馈。"
    if content_kind == "food":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是店名菜名、口感描述和是否值得去。"
    return f"这条视频主要围绕{product}展开，内容方向偏{theme}，适合后续做搜索校验、字幕纠错和剪辑包装。"


def _build_identity_driven_video_theme(profile: dict[str, Any], *, transcript_excerpt: str) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    subject_type = str(profile.get("subject_type") or "").strip()
    preset_name = _workflow_template_name(profile)
    content_kind = _content_kind_name(profile)
    subject_domain = str(profile.get("subject_domain") or "").strip()
    product = " ".join(part for part in (brand, model or subject_type) if part).strip() or subject_type
    if not product:
        return ""
    focus_terms = _extract_profile_focus_terms(
        {**profile, "transcript_excerpt": transcript_excerpt},
        limit=2,
    )
    if focus_terms:
        suffix = "与".join(focus_terms[:2])
        if content_kind == "tutorial":
            return f"{product}{suffix}讲解"
        if content_kind == "food" or subject_domain == "food":
            return f"{product}{suffix}展示"
        return f"{product}{suffix}展示"
    default_theme = _default_video_theme_by_context(
        preset_name=preset_name or content_kind,
        content_kind=content_kind,
        subject_domain=subject_domain,
    )
    if default_theme == "产品开箱与上手体验":
        return f"{product}开箱与上手体验"
    if default_theme and default_theme != "内容主题待进一步确认":
        return f"{product}{default_theme}"
    return f"{product}开箱与上手体验"


def _apply_identity_extraction_rewrite_guard(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    subtitle_items: list[dict[str, Any]] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    guarded = dict(profile or {})
    preexisting_identity = bool(
        str((profile or {}).get("subject_brand") or "").strip()
        or str((profile or {}).get("subject_model") or "").strip()
    )
    extraction = _build_identity_extraction(
        guarded,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        glossary_terms=glossary_terms,
        user_memory=user_memory,
    )
    guarded["identity_extraction"] = extraction

    resolved = extraction.get("resolved") if isinstance(extraction, dict) else {}
    brand = str((resolved or {}).get("subject_brand") or guarded.get("subject_brand") or "").strip()
    model = str((resolved or {}).get("subject_model") or guarded.get("subject_model") or "").strip()
    overall_confidence = float(((extraction.get("confidence") if isinstance(extraction, dict) else {}) or {}).get("overall") or 0.0)
    conflicts = list((extraction.get("conflicts") if isinstance(extraction, dict) else []) or [])
    extraction_sources = (extraction.get("sources") if isinstance(extraction, dict) else {}) or {}
    brand_sources = list(extraction_sources.get("subject_brand") or [])
    model_sources = list(extraction_sources.get("subject_model") or [])
    current_evidence_supported_identity = any(
        source not in {"memory_confirmed", "graph_confirmed_entities", "source_context"}
        for source in [*brand_sources, *model_sources]
    )
    source_context_supported_identity = (
        ("source_context" in brand_sources and "source_context" in model_sources)
        or (
            "source_context" in model_sources
            and bool(brand)
            and _normalize_profile_value(_mapped_brand_for_model(model)) == _normalize_profile_value(brand)
        )
    )

    if brand and not str(guarded.get("subject_brand") or "").strip():
        guarded["subject_brand"] = brand
    if model and not str(guarded.get("subject_model") or "").strip():
        guarded["subject_model"] = model

    if not (brand or model) or conflicts or (overall_confidence < 0.72 and not source_context_supported_identity):
        return guarded

    theme = str(guarded.get("video_theme") or "").strip()
    summary = str(guarded.get("summary") or "").strip()
    hook_line = str(guarded.get("hook_line") or "").strip()
    engagement_question = str(guarded.get("engagement_question") or "").strip()
    summary_normalized = _normalize_profile_value(summary)

    theme_conflict = bool(theme) and _text_conflicts_with_verified_identity(
        theme,
        brand=brand,
        model=model,
        glossary_terms=glossary_terms,
    )
    summary_conflict = bool(summary) and _text_conflicts_with_verified_identity(
        summary,
        brand=brand,
        model=model,
        glossary_terms=glossary_terms,
    )
    hook_conflict = bool(hook_line) and _text_conflicts_with_verified_identity(
        hook_line,
        brand=brand,
        model=model,
        glossary_terms=glossary_terms,
    )
    question_conflict = bool(engagement_question) and _text_conflicts_with_verified_identity(
        engagement_question,
        brand=brand,
        model=model,
        glossary_terms=glossary_terms,
    )
    narrative_conflict = bool(summary_conflict or theme_conflict or hook_conflict or question_conflict)
    summary_missing_identity = source_context_supported_identity and not any(
        _text_matches_identity_value(
            value,
            normalized_text=summary_normalized,
            glossary_terms=glossary_terms,
        )
        for value in (brand, model)
        if value
    )

    should_rebuild_theme = bool(theme_conflict)
    if theme and not should_rebuild_theme:
        should_rebuild_theme = not _is_specific_video_theme_for_context(
            theme,
            preset_name=_workflow_template_name(guarded),
            content_kind=_content_kind_name(guarded),
            subject_domain=str(guarded.get("subject_domain") or ""),
        )
    if not theme and source_context_supported_identity:
        should_rebuild_theme = True
    if should_rebuild_theme:
        rebuilt_theme = _build_identity_driven_video_theme(guarded, transcript_excerpt=transcript_excerpt)
        if rebuilt_theme:
            guarded["video_theme"] = rebuilt_theme

    should_rebuild_summary = False
    if summary_missing_identity or (not summary and source_context_supported_identity):
        should_rebuild_summary = True
    elif summary and not summary_conflict and _is_generic_profile_summary(summary):
        should_rebuild_summary = True
    elif narrative_conflict and (
        source_context_supported_identity or current_evidence_supported_identity or preexisting_identity
    ):
        should_rebuild_summary = True

    if should_rebuild_summary:
        if overall_confidence >= 0.88:
            guarded["summary"] = _build_profile_summary(guarded)
        else:
            guarded["summary"] = _build_conservative_identity_summary(
                guarded,
                subtitle_items=subtitle_items,
            )
    elif summary_conflict:
        guarded["summary"] = ""

    if hook_conflict:
        guarded["hook_line"] = ""
    if question_conflict:
        guarded["engagement_question"] = ""

    search_queries = [str(item).strip() for item in (guarded.get("search_queries") or []) if str(item).strip()]
    supported_queries = [
        query for query in search_queries
        if any(
            _text_matches_identity_value(
                value,
                normalized_text=_normalize_profile_value(query),
                glossary_terms=glossary_terms,
            )
            for value in (brand, model)
            if value
        )
    ]
    if len(supported_queries) != len(search_queries):
        guarded["search_queries"] = supported_queries
    _ensure_search_queries(guarded, source_name, transcript_excerpt=transcript_excerpt)
    return guarded


def _default_subject_type_for_preset(preset: WorkflowPreset) -> str:
    return _default_subject_type_by_name(preset.name)


def _default_subject_type_by_name(preset_name: str) -> str:
    mapping = {
        "tutorial_standard": "录屏教学",
        "tutorial": "录屏教学",
        "vlog_daily": "Vlog日常",
        "vlog": "Vlog日常",
        "commentary_focus": "口播观点",
        "commentary": "口播观点",
        "gameplay_highlight": "游戏实况",
        "gameplay": "游戏实况",
        "food_explore": "探店试吃",
        "food": "探店试吃",
    }
    return mapping.get(preset_name, "开箱产品")


def _default_video_theme_for_preset(preset: WorkflowPreset) -> str:
    return _default_video_theme_by_context(preset_name=preset.name, content_kind=preset.content_kind, subject_domain="")


def _default_video_theme_by_name(preset_name: str) -> str:
    return _default_video_theme_by_context(preset_name=preset_name, content_kind="", subject_domain="")


def _default_video_theme_by_context(*, preset_name: str, content_kind: str, subject_domain: str) -> str:
    normalized_preset = str(preset_name or "").strip()
    normalized_kind = str(content_kind or "").strip().lower()
    normalized_domain = str(subject_domain or "").strip().lower()
    if not normalized_preset and not normalized_kind and not normalized_domain:
        return "内容主题待进一步确认"

    tutorial_domain_mapping = {
        "ai": "AI工作流与模型能力讲解",
        "tech": "数码科技体验与功能讲解",
    }
    if (normalized_kind == "tutorial" or normalized_preset in {"tutorial_standard", "tutorial"}) and normalized_domain in tutorial_domain_mapping:
        return tutorial_domain_mapping[normalized_domain]

    mapping = {
        "tutorial_standard": "软件流程演示与步骤讲解",
        "tutorial": "软件流程演示与步骤讲解",
        "vlog_daily": "日常记录与生活分享",
        "vlog": "日常记录与生活分享",
        "commentary_focus": "观点表达与信息拆解",
        "commentary": "观点表达与信息拆解",
        "gameplay_highlight": "高能操作与对局复盘",
        "gameplay": "高能操作与对局复盘",
        "food_explore": "探店试吃与性价比判断",
        "food": "探店试吃与性价比判断",
    }
    return mapping.get(normalized_preset or normalized_kind, "产品开箱与上手体验")


def _default_engagement_question(preset: WorkflowPreset) -> str:
    mapping = {
        "tutorial_standard": "这套流程你会直接照着做吗？",
        "vlog_daily": "你最想看我下次拍哪种日常？",
        "commentary_focus": "这件事你同意这个判断吗？",
        "gameplay_highlight": "这波操作你会怎么打？",
        "food_explore": "这家店你会专门去吃一次吗？",
    }
    return mapping.get(preset.name, "你觉得这次到手值不值？")
