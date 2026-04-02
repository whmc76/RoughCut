from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.edit.presets import WorkflowPreset, get_workflow_preset, normalize_workflow_template_name, select_workflow_template
from roughcut.llm_cache import digest_payload
from roughcut.providers.factory import get_ocr_provider, get_reasoning_provider, get_search_provider
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.usage import track_usage_operation
from roughcut.db.session import get_session_factory
from roughcut.review.content_understanding_evidence import build_evidence_bundle
from roughcut.review.content_understanding_infer import infer_content_understanding
from roughcut.review.content_understanding_schema import ContentUnderstanding, map_content_understanding_to_legacy_profile
from roughcut.review.content_understanding_verify import build_hybrid_verification_bundle, verify_content_understanding
from roughcut.review.content_profile_memory import summarize_content_profile_user_memory
from roughcut.review.content_profile_ocr import build_content_profile_ocr
from roughcut.review.content_profile_candidates import build_identity_candidates
from roughcut.review.content_profile_evidence import IdentityEvidenceBundle
from roughcut.review.content_profile_resolve import resolve_identity_candidates
from roughcut.review.content_profile_review_stats import build_content_profile_auto_review_gate
from roughcut.review.content_profile_scoring import score_identity_candidates
from roughcut.review.domain_glossaries import detect_glossary_domains, select_primary_subject_domain
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

_CONTENT_PROFILE_INFER_CACHE_VERSION = "2026-04-03.infer.v8"
_CONTENT_PROFILE_ENRICH_CACHE_VERSION = "2026-04-03.enrich.v8"
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
_GEAR_STYLE_SIGNALS = (
    "工具钳",
    "战术笔",
    "edc",
    "弹夹",
    "装备",
    "莱德曼",
)

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
    normalized = {
        "subject_brand": str(seeded.get("subject_brand") or "").strip(),
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
        )
    ):
        return {}
    return normalized


def build_content_profile_cache_fingerprint(
    *,
    source_name: str,
    source_file_hash: str | None,
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    transcript_excerpt: str,
    subtitle_digest: str | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    include_research: bool,
    copy_style: str | None = None,
    seeded_profile: dict[str, Any] | None = None,
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
        "glossary_terms_sha256": digest_payload(normalized_glossary),
        "glossary_term_count": len(normalized_glossary),
        "user_memory_sha256": digest_payload(normalized_memory),
        "include_research": bool(include_research),
        "copy_style": str(copy_style or "").strip(),
        "seeded_profile_sha256": digest_payload(normalized_seeded_profile) if normalized_seeded_profile else "",
    }


def build_transcript_excerpt(subtitle_items: list[dict], *, max_items: int = 36, max_chars: int = 1400) -> str:
    selected = _select_excerpt_items(subtitle_items, max_items=max_items)
    lines: list[str] = []
    total = 0
    for item in selected:
        text = item.get("text_final") or item.get("text_norm") or item.get("text_raw") or ""
        if not text:
            continue
        line = f"[{item.get('start_time', 0):.1f}-{item.get('end_time', 0):.1f}] {text}"
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
    profile_blob = " ".join(
        [
            str(profile.get("subject_type") or ""),
            str(profile.get("summary") or ""),
            str(profile.get("video_theme") or ""),
            str(profile.get("subject_brand") or ""),
            str(profile.get("subject_model") or ""),
            json.dumps(profile.get("cover_title") or {}, ensure_ascii=False),
        ]
    ).lower()
    subtitle_blob = f"{transcript_excerpt}\n{_build_subtitle_signal_blob(subtitle_items)}".lower()

    ingestible_hits = sum(1 for token in _INGESTIBLE_PRODUCT_SIGNALS if token in subtitle_blob)
    gear_hits = sum(1 for token in _GEAR_STYLE_SIGNALS if token in profile_blob)
    profile_ingestible_hits = sum(1 for token in _INGESTIBLE_PRODUCT_SIGNALS if token in profile_blob)

    return ingestible_hits >= 2 and gear_hits >= 1 and profile_ingestible_hits == 0


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
    anchor = _extract_cover_entity_anchor(
        brand=brand,
        model=model,
        subject_type=subject_type,
        theme=raw_theme,
        visible_text=visible_text,
    )

    top = _pick_cover_top(
        brand=brand,
        subject_type=subject_type,
        visible_text=visible_text,
        preset=preset,
        anchor=anchor,
    )
    main = _pick_cover_main(
        brand=brand,
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
        if bool(identity_review.get("conservative_summary")):
            guarded["summary"] = _build_conservative_identity_summary(
                guarded,
                subtitle_items=subtitle_items,
            )
        return guarded
    memory_hints = _seed_profile_from_user_memory(transcript_excerpt, user_memory)
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
    support_sources = _collect_identity_support_sources(evidence_bundle)
    support_count = len(support_sources)
    has_external_evidence = "evidence" in support_sources
    evidence_strength = "strong" if has_external_evidence or support_count >= 2 else "weak"
    required = first_seen_brand or first_seen_model
    conservative_summary = required and evidence_strength != "strong"

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
    return support_sources


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
    visible_text = str(profile.get("visible_text") or ocr_hints.get("visible_text") or "").strip()
    evidence_text = " ".join(
        " ".join(
            str(item.get(key) or "")
            for key in ("query", "title", "snippet")
        )
        for item in (profile.get("evidence") or [])
        if isinstance(item, dict)
    ).strip()
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
    raw_visual_hints = _profile_visual_cluster_hints(sanitized)
    transcript_hints = _seed_profile_from_transcript_excerpt(
        transcript_excerpt,
        glossary_terms=glossary_terms,
    )
    visual_hints = _seed_profile_from_text(
        str(sanitized.get("visible_text") or "").strip(),
        glossary_terms=glossary_terms,
    )
    theme_hints = _seed_profile_from_text(
        str(sanitized.get("video_theme") or "").strip(),
        glossary_terms=glossary_terms,
    )
    source_hints = (
        _seed_profile_from_text(Path(source_name).stem, glossary_terms=glossary_terms)
        if _is_informative_source_hint(Path(source_name).stem)
        else {}
    )
    memory_confirmed_hints = _select_confirmed_entity_from_user_memory(
        transcript_excerpt,
        user_memory=user_memory,
        subject_type=str(
            sanitized.get("subject_type")
            or transcript_hints.get("subject_type")
            or ""
        ),
    )
    transcript_source_labels = _profile_transcript_source_labels(sanitized)
    ocr_hints = _profile_ocr_hints(sanitized, glossary_terms=glossary_terms)
    confirmed_fields = _extract_confirmed_profile_fields(sanitized)

    confirmed_brand = str(confirmed_fields.get("subject_brand") or "").strip()
    confirmed_model = str(confirmed_fields.get("subject_model") or "").strip()
    evidence_bundle = IdentityEvidenceBundle(
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        transcript_hints=transcript_hints,
        transcript_source_labels=transcript_source_labels,
        source_hints=source_hints,
        visual_cluster_hints={
            "subject_brand": str(raw_visual_hints.get("subject_brand") or "").strip(),
            "subject_model": str(raw_visual_hints.get("subject_model") or "").strip(),
            "subject_type": str(raw_visual_hints.get("subject_type") or "").strip(),
            "visible_text": str(raw_visual_hints.get("visible_text") or "").strip(),
        },
        visual_hints={},
        visible_text_hints=visual_hints,
        ocr_hints=ocr_hints,
        memory_confirmed_hints=memory_confirmed_hints,
        graph_confirmed_entities=_graph_confirmed_entities(user_memory)[:6],
        profile_identity={
            "subject_brand": str(sanitized.get("subject_brand") or "").strip(),
            "subject_model": str(sanitized.get("subject_model") or "").strip(),
            "subject_type": str(sanitized.get("subject_type") or "").strip(),
            "video_theme": str(sanitized.get("video_theme") or "").strip(),
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

    return sanitized


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
        seeded = _seed_profile_from_text(visible_text, glossary_terms=glossary_terms)
        for field_name in ("subject_brand", "subject_model"):
            value = str(seeded.get(field_name) or "").strip()
            if value and field_name not in hints:
                hints[field_name] = value
        for value in _hint_values(seeded, "subject_type"):
            _append_hint_candidate(hints, "subject_type", value)
    return hints


def _graph_confirmed_entities(user_memory: dict[str, Any] | None) -> list[dict[str, Any]]:
    graph_bucket = (user_memory or {}).get("entity_graph")
    if isinstance(graph_bucket, dict):
        graph_entities = list(graph_bucket.get("confirmed_entities") or [])
        if graph_entities:
            return graph_entities
    return list((user_memory or {}).get("confirmed_entities") or [])


def _mapped_brand_for_model(model: object) -> str:
    normalized_model = _normalize_profile_value(model)
    if not normalized_model:
        return ""
    for candidate, brand in _MODEL_TO_BRAND.items():
        if _normalize_profile_value(candidate) == normalized_model:
            return brand
    return ""


def _first_supported_identity_value(primary: Any, *candidates: Any) -> str:
    normalized_candidates = {
        _normalize_profile_value(candidate): str(candidate).strip()
        for candidate in candidates
        if _normalize_profile_value(candidate)
    }
    primary_key = _normalize_profile_value(primary)
    if primary_key and primary_key in normalized_candidates:
        return normalized_candidates[primary_key]
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
    primary_key = _normalize_profile_value(primary)
    if not primary_key:
        return 0
    count = 0
    for candidate in candidates:
        if _normalize_profile_value(candidate) == primary_key:
            count += 1
    return count


def _query_is_identity_supported(query: str, *, transcript_excerpt: str, source_name: str) -> bool:
    return _search_query_support_score(
        query,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
    ) > 0


def _normalize_profile_value(value: object) -> str:
    return "".join(str(value or "").strip().upper().split())


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
            and normalized_known_brand != normalized_brand
            and normalized_known_brand in normalized_text
        ):
            return True
    seeded = _seed_profile_from_text(text, glossary_terms=glossary_terms)
    seeded_brand = str(seeded.get("subject_brand") or "").strip()
    seeded_model = str(seeded.get("subject_model") or "").strip()
    if seeded_brand and brand and _normalize_profile_value(seeded_brand) != _normalize_profile_value(brand):
        return True
    if seeded_model and model and _normalize_profile_value(seeded_model) != _normalize_profile_value(model):
        return True
    mapped_brand = _mapped_brand_for_model(seeded_model or model)
    effective_brand = seeded_brand or brand
    if mapped_brand and effective_brand and _normalize_profile_value(effective_brand) != _normalize_profile_value(mapped_brand):
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
    workflow_template: str | None = None,
    channel_profile: str | None = None,
    user_memory: dict[str, Any] | None = None,
    glossary_terms: list[dict[str, Any]] | None = None,
    include_research: bool = True,
    copy_style: str = "attention_grabbing",
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    transcript_excerpt = build_transcript_excerpt(subtitle_items)
    initial_profile: dict[str, Any] = {
        "copy_style": str(copy_style or "attention_grabbing").strip() or "attention_grabbing",
    }
    settings = get_settings()
    visual_hints: dict[str, Any] = {}

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = _extract_reference_frames(source_path, Path(tmpdir), count=3)
            if bool(getattr(settings, "ocr_enabled", False)):
                ocr_profile = await _collect_content_profile_ocr(frame_paths, source_name=source_name)
                if ocr_profile:
                    initial_profile["ocr_profile"] = ocr_profile
                    if ocr_profile.get("visible_text") and not str(initial_profile.get("visible_text") or "").strip():
                        initial_profile["visible_text"] = str(ocr_profile.get("visible_text") or "").strip()
            visual_hints = await _infer_visual_profile_hints(frame_paths)
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
        visual_hints=visual_hints,
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

    if include_research and understanding.search_queries:
        try:
            async with get_session_factory()() as session:
                verification_bundle = await build_hybrid_verification_bundle(
                    search_queries=understanding.search_queries,
                    online_search=_online_search_content_understanding,
                    internal_search=None,
                    session=session,
                )
                with track_usage_operation("content_profile.universal_verify"):
                    understanding = await verify_content_understanding(
                        understanding=understanding,
                        evidence_bundle=evidence_bundle,
                        verification_bundle=verification_bundle,
                    )
        except Exception:
            pass

    profile = map_content_understanding_to_legacy_profile(understanding)
    profile["content_understanding"] = profile.get("content_understanding") or {}
    profile["transcript_excerpt"] = transcript_excerpt
    profile["workflow_template"] = str(workflow_template or "").strip()
    profile["copy_style"] = str(copy_style or "attention_grabbing").strip() or "attention_grabbing"
    if initial_profile.get("ocr_profile"):
        profile["ocr_profile"] = dict(initial_profile.get("ocr_profile") or {})
    if initial_profile.get("visible_text") and not profile.get("visible_text"):
        profile["visible_text"] = str(initial_profile.get("visible_text") or "").strip()
    if visual_hints:
        profile["visual_hints"] = dict(visual_hints)
        profile["visual_cluster_hints"] = dict(visual_hints)

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


async def _online_search_content_understanding(*, search_queries: list[str]) -> list[dict[str, Any]]:
    provider = get_search_provider()
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
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    merged = dict(draft_profile or {})
    merged["user_feedback"] = dict(user_feedback or {})
    if not any(value for value in (user_feedback or {}).values()):
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
        value = user_feedback.get(key)
        if value:
            merged[key] = str(value).strip()

    if user_feedback.get("keywords"):
        merged["search_queries"] = [str(item).strip() for item in user_feedback["keywords"] if str(item).strip()]
    if user_feedback.get("summary"):
        merged["summary"] = str(user_feedback["summary"]).strip()
    if user_feedback.get("engagement_question"):
        merged["engagement_question"] = str(user_feedback["engagement_question"]).strip()
    if user_feedback.get("copy_style"):
        merged["copy_style"] = str(user_feedback["copy_style"]).strip()
    if user_feedback.get("correction_notes"):
        merged["correction_notes"] = str(user_feedback["correction_notes"]).strip()
    if user_feedback.get("supplemental_context"):
        merged["supplemental_context"] = str(user_feedback["supplemental_context"]).strip()

    try:
        provider = get_reasoning_provider()
        accepted_examples = [
            {
                "original": str(item.get("original") or "").strip(),
                "accepted": str(item.get("accepted") or "").strip(),
            }
            for item in (accepted_corrections or [])
            if str(item.get("original") or "").strip() and str(item.get("accepted") or "").strip()
        ]
        reviewed_excerpt = str(reviewed_subtitle_excerpt or merged.get("transcript_excerpt") or "").strip()
        prompt = (
            "你在整理一条中文短视频的人工确认摘要。请结合模型草稿和用户修正，"
            "输出一个后续可直接用于搜索、字幕修正和剪辑规划的确认版摘要。"
            "用户修正优先级最高，不要忽略用户手动填写的信息。\n"
            "subject_brand 指开箱产品品牌，不是频道名；subject_model 指开箱产品名、系列名、型号或版本，不要回填文件名或时间戳。\n"
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
    except Exception:
        pass

    transcript_excerpt = str(reviewed_subtitle_excerpt or merged.get("transcript_excerpt") or "")
    result = await enrich_content_profile(
        profile=merged,
        source_name=source_name,
        channel_profile=workflow_template,
        transcript_excerpt=transcript_excerpt,
        include_research=False,
    )
    result["user_feedback"] = dict(user_feedback or {})
    result["review_mode"] = "manual_confirmed"
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
        value = user_feedback.get(key)
        if value:
            result[key] = str(value).strip()
    if user_feedback.get("keywords"):
        manual_queries: list[str] = []
        for item in user_feedback["keywords"]:
            query = str(item).strip()
            if query and query not in manual_queries:
                manual_queries.append(query)
        if manual_queries:
            result["search_queries"] = manual_queries
    if any(
        user_feedback.get(key)
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
        result["cover_title"] = build_cover_title(result, preset)
    return result


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
    glossary_terms: list[dict[str, Any]] | None = None,
    user_memory: dict[str, Any] | None = None,
    include_research: bool = True,
) -> dict[str, Any]:
    if workflow_template is None and channel_profile is not None:
        workflow_template = channel_profile
    enriched = dict(profile or {})
    confirmed_fields = _extract_confirmed_profile_fields(enriched)
    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    memory_hints = _seed_profile_from_user_memory(transcript_excerpt, user_memory)
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
    context_hints = _seed_profile_from_context(
        enriched,
        transcript_excerpt,
        glossary_terms=glossary_terms,
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
                enriched[key] = llm_profile[key]
        enriched["content_understanding"] = llm_profile.get("content_understanding") or {}

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
                    "确认视频主体的开箱产品品牌、开箱产品型号/版本、主体类型、视频主题，并生成适合做封面的三段标题。"
                    "如果是软件/AI/科技视频，必须锁定软件名和功能名，封面标题不能再写成“软件工具”“功能演示”这种泛词。"
                    "同时生成一个适合评论区互动的问题，要具体、自然、贴合内容，不要反复使用同一句泛化问题。"
                    "只有当字幕/画面线索与搜索结果能够互相印证时，才提升品牌、型号等关键信息。"
                    "如果搜索结果与字幕线索冲突，优先保守，保留已有可信字段，不要为了补全而乱改。"
                    "优先给出品牌名、系列名或主体名，不要输出泛化标题如“产品开箱与上手体验”。"
                    "subject_brand 指开箱产品品牌，不是频道名；不要把文件名、时间戳或相机编号当成开箱产品型号。"
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

    _apply_confirmed_profile_fields(enriched, confirmed_fields)

    if "hook_line" not in confirmed_fields:
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
    if not enriched.get("summary") or _is_generic_profile_summary(str(enriched.get("summary") or "")):
        enriched["summary"] = _build_profile_summary(enriched)
    if _is_generic_engagement_question(str(enriched.get("engagement_question") or "")):
        generated_question = await _generate_engagement_question(
            profile=enriched,
            transcript_excerpt=transcript_excerpt,
            evidence=enriched.get("evidence") or [],
            preset=preset,
            memory_prompt=memory_prompt,
        )
        if generated_question:
            enriched["engagement_question"] = generated_question
    if _is_generic_engagement_question(str(enriched.get("engagement_question") or "")):
        enriched["engagement_question"] = _build_fallback_engagement_question(enriched, preset)
    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    if confirmed_fields and any(
        key in confirmed_fields
        for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "hook_line", "visible_text")
    ):
        enriched["cover_title"] = build_cover_title(enriched, preset)
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
        visual_hints=_profile_visual_cluster_hints(profile),
    )
    evidence_bundle["candidate_hints"] = _enrich_candidate_hints(profile)
    try:
        with track_usage_operation("content_profile.enrich_universal_infer"):
            understanding = await infer_content_understanding(evidence_bundle)
    except Exception:
        return None

    if include_research and understanding.search_queries:
        try:
            async with get_session_factory()() as session:
                verification_bundle = await build_hybrid_verification_bundle(
                    search_queries=understanding.search_queries,
                    online_search=_online_search_content_understanding,
                    internal_search=None,
                    session=session,
                )
                with track_usage_operation("content_profile.enrich_universal_verify"):
                    understanding = await verify_content_understanding(
                        understanding=understanding,
                        evidence_bundle=evidence_bundle,
                        verification_bundle=verification_bundle,
                    )
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
    return {
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
                    "只做最小必要的字幕纠错。"
                    "要求：\n"
                    "1. 只允许修正 ASR 错字、同音词、品牌型号、行业术语、明显断句问题。\n"
                    "2. 禁止总结、改写、扩写、缩写、换说法、重排信息、添加没说过的品牌型号或参数。\n"
                    "3. 如果原句基本可用，就保持原句，只修正错别字即可。\n"
                    "4. 结合 prev_text / next_text 只做邻句消歧，不要借邻句重写本句。\n"
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
    elif brand:
        for term in signal_terms[:2]:
            query_candidates.append(f"{brand} {term}")
            if subject_type:
                query_candidates.append(f"{brand} {term} {subject_type}")
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
    if model and subject_type:
        query_candidates.append(f"{model} {subject_type}")
    if software_like and brand and model and any(term in {"无限画布", "漫剧工作流", "工作流", "节点编排", "智能体"} for term in topic_terms):
        for topic in topic_terms[:3]:
            if topic != model:
                query_candidates.append(f"{brand} {topic}")
            query_candidates.append(f"{brand} {topic} 教程")
        if "无限画布" in topic_terms or model == "无限画布":
            query_candidates.append(f"{brand} 无限画布 漫剧")
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

    for value, weight in (
        (brand, 3),
        (model, 3),
        (subject_type, 2),
        (_subject_type_search_anchor(subject_type), 1),
    ):
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
    terms: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        normalized = text.upper()
        for match in re.finditer(r"(?<![A-Z0-9])([A-Z][A-Z0-9-]{1,17})(?![A-Z0-9])", normalized):
            token = match.group(1).strip("-")
            if not token or token in _SEARCH_SIGNAL_STOPWORDS:
                continue
            if re.fullmatch(r"\d+", token) or _looks_like_camera_stem(token):
                continue
            if token not in seen:
                seen.add(token)
                terms.append(token)
    return terms


def _select_excerpt_items(subtitle_items: list[dict], *, max_items: int) -> list[dict]:
    if not subtitle_items:
        return []

    selected: list[dict] = []
    seen: set[tuple[float, float, str]] = set()

    def _append(item: dict) -> None:
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        key = (
            round(float(item.get("start_time", 0.0) or 0.0), 3),
            round(float(item.get("end_time", 0.0) or 0.0), 3),
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
        key=lambda item: (_transcript_signal_score(item), float(item.get("start_time", 0.0) or 0.0)),
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

    selected.sort(key=lambda item: float(item.get("start_time", 0.0) or 0.0))
    return selected[:max_items]


def _transcript_signal_score(item: dict[str, Any]) -> int:
    text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
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
    ("Loop露普", re.compile(r"(LOOP|露普|陆虎|路普|鲁普)", re.IGNORECASE)),
    ("狐蝠工业", re.compile(r"(FOXBAT|狐蝠工业|狐蝠)", re.IGNORECASE)),
]

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
    "FXX1": "狐蝠工业",
    "FXX1小副包": "狐蝠工业",
    "SK05二代ProUV版": "Loop露普",
    "SK05二代Pro UV版": "Loop露普",
    "SK05二代UV版": "Loop露普",
    "SK05二代 UV版": "Loop露普",
    "SK05UV版": "Loop露普",
    "SK05 UV版": "Loop露普",
}


def _seed_profile_from_subtitles(
    subtitle_items: list[dict],
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    transcript_lines = [
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items
    ]
    transcript = "\n".join(line for line in transcript_lines if line)
    return _seed_profile_from_text(transcript, glossary_terms=glossary_terms)


def _seed_profile_from_transcript_excerpt(
    transcript_excerpt: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return _seed_profile_from_text(transcript_excerpt, glossary_terms=glossary_terms)


def _seed_profile_from_context(
    profile: dict[str, Any],
    transcript_excerpt: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
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
    return _seed_profile_from_text(text, glossary_terms=glossary_terms)


def _seed_profile_from_user_memory(transcript_excerpt: str, user_memory: dict[str, Any] | None) -> dict[str, Any]:
    transcript_norm = _normalize_profile_value(transcript_excerpt)
    if not transcript_norm or not user_memory:
        return {}

    seeded: dict[str, Any] = {}
    field_preferences = user_memory.get("field_preferences") or {}
    recent_corrections = user_memory.get("recent_corrections") or []
    phrase_preferences = user_memory.get("phrase_preferences") or []

    for item in recent_corrections:
        corrected = str(item.get("corrected_value") or "").strip()
        if corrected and _normalize_profile_value(corrected) in transcript_norm:
            field_name = str(item.get("field_name") or "").strip()
            if field_name in {"subject_brand", "subject_model"} and field_name not in seeded:
                seeded[field_name] = corrected
            elif field_name in {"subject_type", "video_theme"}:
                _append_hint_candidate(seeded, field_name, corrected)

    for field_name in ("subject_brand", "subject_model", "subject_type"):
        if field_name in {"subject_brand", "subject_model"} and field_name in seeded:
            continue
        if field_name == "subject_type" and _hint_primary_value(seeded, field_name):
            continue
        for item in field_preferences.get(field_name) or []:
            value = str(item.get("value") or "").strip()
            if value and _normalize_profile_value(value) in transcript_norm:
                if field_name in {"subject_brand", "subject_model"}:
                    seeded[field_name] = value
                else:
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
            phrase_seed = _seed_profile_from_text(phrase)
            if phrase_seed.get("subject_brand"):
                seeded["subject_brand"] = phrase_seed["subject_brand"]
            if phrase_seed.get("subject_model") and "subject_model" not in seeded:
                seeded["subject_model"] = phrase_seed["subject_model"]
            if seeded.get("subject_brand"):
                break

    if not _hint_primary_value(seeded, "subject_type"):
        transcript_seed = _seed_profile_from_text(transcript_excerpt)
        transcript_subject_type = _hint_primary_value(transcript_seed, "subject_type")
        if transcript_subject_type:
            _append_hint_candidate(seeded, "subject_type", transcript_subject_type)
        elif seeded.get("subject_brand") == "Loop露普" or str(seeded.get("subject_model") or "").startswith("SK05"):
            _append_hint_candidate(seeded, "subject_type", "EDC手电")

    if "subject_brand" not in seeded and "subject_model" not in seeded:
        confirmed_entity = _select_confirmed_entity_from_user_memory(
            transcript_excerpt,
            user_memory=user_memory,
            subject_type=_hint_primary_value(seeded, "subject_type"),
        )
        if confirmed_entity:
            brand = str(confirmed_entity.get("brand") or "").strip()
            model = str(confirmed_entity.get("model") or "").strip()
            if brand:
                seeded["subject_brand"] = brand
            if model:
                seeded["subject_model"] = model
            if confirmed_entity.get("subject_type") and not _hint_primary_value(seeded, "subject_type"):
                _append_hint_candidate(seeded, "subject_type", confirmed_entity.get("subject_type"))

    return seeded


def _select_confirmed_entity_from_user_memory(
    transcript_excerpt: str,
    *,
    user_memory: dict[str, Any] | None,
    subject_type: str,
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
) -> bool:
    entity_subject_type = str(entity.get("subject_type") or "").strip()
    effective_subject_type = str(subject_type or "").strip()
    alias_context_support = _confirmed_entity_has_alias_context_support(
        entity,
        transcript=transcript,
        normalized=normalized,
    )
    if not effective_subject_type:
        transcript_seed = _seed_profile_from_text(transcript)
        effective_subject_type = _hint_primary_value(transcript_seed, "subject_type")

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

    for term in glossary_terms:
        correct_form = str(term.get("correct_form") or "").strip()
        category = str(term.get("category") or "").strip().lower()
        if not correct_form:
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
            if candidate and (best_brand is None or score > best_brand[0]):
                best_brand = (score, candidate)
                best_brand_category = category
        elif _looks_like_product_model(correct_form):
            score = len(_normalize_profile_value(correct_form))
            if best_model is None or score > best_model[0]:
                best_model = (score, correct_form)

    if best_brand:
        seeded["subject_brand"] = best_brand[1]
        subject_type = _subject_type_from_glossary_category(best_brand_category)
        if subject_type:
            _append_hint_candidate(seeded, "subject_type", subject_type)
    if best_model:
        seeded["subject_model"] = best_model[1]
        if "subject_brand" not in seeded and best_model[1] in _MODEL_TO_BRAND:
            seeded["subject_brand"] = _MODEL_TO_BRAND[best_model[1]]
    return seeded


def _seed_profile_from_text(
    transcript: str,
    *,
    glossary_terms: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
    if re.search(r"(?<![A-Z0-9])ARC(?![A-Z0-9])", normalized):
        model = "ARC"
        model_source = "explicit_alias"
    elif re.search(r"(?<![A-Z0-9])SURGE(?![A-Z0-9])", normalized):
        model = "SURGE"
        model_source = "explicit_alias"
    elif re.search(r"(?<![A-Z0-9])CHARGE(?![A-Z0-9])", normalized):
        model = "CHARGE"
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
        model = ""

    if not brand and model in _MODEL_TO_BRAND:
        brand = _MODEL_TO_BRAND[model]

    subject_type = ""
    knife_keywords = ("折刀", "刀片", "锁定机构", "推刀", "梯片", "锁片", "刀柄", "柄身", "开刃")
    plier_keywords = ("工具钳", "钳子", "尖嘴钳", "钢丝钳")
    flashlight_keywords = ("手电", "电筒", "筒身", "紫光", "UV", "流明", "泛光", "照射")
    bag_keywords = ("机能包", "副包", "小副包", "斜挎包", "胸包", "快取包", "分仓", "挂点", "收纳")

    if brand == "LEATHERMAN" or model in {"ARC", "SURGE", "CHARGE"}:
        subject_type = "多功能工具钳"
    elif brand == "REATE" or any(keyword in transcript for keyword in knife_keywords):
        subject_type = "EDC折刀"
    elif brand == "Loop露普" or model.startswith("SK05") or any(keyword in canon.upper() for keyword in flashlight_keywords):
        subject_type = "EDC手电"
    elif brand == "狐蝠工业" or model.startswith("FXX1") or any(keyword in transcript for keyword in bag_keywords):
        subject_type = "EDC机能包"
    elif any(keyword in transcript for keyword in plier_keywords):
        subject_type = "多功能工具钳"
    elif _hint_primary_value(glossary_seed, "subject_type"):
        subject_type = _hint_primary_value(glossary_seed, "subject_type")

    topic_terms = _extract_topic_terms(transcript)
    product_identity_detected = bool(
        subject_type
        or brand in {"LEATHERMAN", "REATE", "Loop露普", "狐蝠工业"}
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
    if brand or model:
        queries = _build_seeded_search_queries(
            brand=brand,
            model=model,
            subject_type=subject_type,
            topic_terms=topic_terms,
        )
        seeded["search_queries"] = queries
    return seeded


def _canonicalize_spoken_identity_text(text: str) -> str:
    normalized = str(text or "").upper()
    replacements = {
        "零": "0",
        "〇": "0",
        "Ｏ": "0",
        "一": "1",
        "二": "2",
        "两": "2",
        "三": "3",
        "四": "4",
        "五": "5",
        "六": "6",
        "七": "7",
        "八": "8",
        "九": "9",
        "Ⅱ": "II",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return normalized


def _extract_edc_flashlight_model(text: str) -> str:
    normalized = _canonicalize_spoken_identity_text(text)
    if "SK05" not in normalized:
        return ""
    suffixes: list[str] = ["SK05"]
    if "2代" in normalized or "二代" in text or "II" in normalized:
        suffixes.append("二代")
    if "PRO" in normalized:
        suffixes.append("Pro")
    if "UV" in normalized:
        suffixes.append("UV版")
    return " ".join(suffixes[:1]).replace(" ", "") if len(suffixes) == 1 else f"{suffixes[0]}{''.join(suffixes[1:])}"


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
    normalized = re.sub(r"F叉21", "FXX1", normalized, flags=re.IGNORECASE)
    normalized = normalized.replace("叉", "X")
    if "FXX1" not in normalized:
        return ""
    if "小副包" in str(original_text or ""):
        return "FXX1小副包"
    return "FXX1"


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
    terms: list[str] = []
    seen: set[str] = set()
    for label, pattern in _TECH_TOPIC_PATTERNS:
        if pattern.search(text) and label not in seen:
            seen.add(label)
            terms.append(label)
    return terms


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


def _looks_like_product_model(value: str) -> bool:
    compact = _clean_line(value)
    if not compact:
        return False
    if re.search(r"[A-Za-z]", compact) and re.search(r"[\d零〇一二三四五六七八九十]", compact):
        return True
    return compact.endswith(("小副包", "副包", "Pro", "MAX", "Mini", "Ultra", "Plus", "SE"))


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
    match = re.match(r"^这[\u4e00-\u9fff]{1,4}在(?P<rest>.+给大家(?:单独)?看[下看]?)", result)
    if match and "一期" not in result[:6]:
        return f"这一期在{match.group('rest')}"
    return result


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
    return re.sub(r"\s+", "", str(text)).strip("，。！？：:;；、")


def _looks_like_camera_stem(text: str) -> bool:
    normalized = text.strip().lower()
    return bool(
        re.fullmatch(r"(img|dsc|mvimg|pxl|cimg|vid)[-_]?\d+", normalized)
        or re.fullmatch(r"\d{8}[_-].+", normalized)
    )


def _is_informative_source_hint(text: str) -> bool:
    normalized = _clean_line(text)
    if not normalized:
        return False
    if _looks_like_camera_stem(normalized):
        return False
    if re.fullmatch(r"[\d_-]+", normalized):
        return False
    return True


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
    subject_type: str,
    visible_text: str,
    preset: WorkflowPreset,
    anchor: dict[str, str] | None = None,
) -> str:
    anchor_brand = _clean_line((anchor or {}).get("brand") or "")
    if anchor_brand:
        return anchor_brand[:14]
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

    compact_brand = _compact_brand_name(brand, visible_text=visible_text)
    display_subject_type = _cover_subject_type_label(subject_type)
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
) -> dict[str, str]:
    cleaned_brand = _clean_line(brand)
    cleaned_model = _clean_line(model)
    if _is_generic_cover_line(cleaned_model):
        cleaned_model = ""
    display_subject_type = _cover_subject_type_label(subject_type)

    if cleaned_brand and cleaned_model and display_subject_type:
        return {
            "brand": _compact_brand_name(cleaned_brand, visible_text=visible_text),
            "main": f"{cleaned_brand} {cleaned_model}{display_subject_type}".replace("  ", " ").strip(),
        }
    if cleaned_brand and cleaned_model:
        return {
            "brand": _compact_brand_name(cleaned_brand, visible_text=visible_text),
            "main": f"{cleaned_brand} {cleaned_model}".replace("  ", " ").strip(),
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
    terms: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9+-]{1,23}", str(text or "")):
        token = match.group(0).strip()
        if len(token) < 2:
            continue
        if token in {"主要围绕", "内容方向", "产品开箱与上手体验"}:
            continue
        if token not in seen:
            seen.add(token)
            terms.append(token)
    return terms


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
