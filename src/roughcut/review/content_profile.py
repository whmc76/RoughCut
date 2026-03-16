from __future__ import annotations

from difflib import SequenceMatcher
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from roughcut.config import get_settings
from roughcut.edit.presets import WorkflowPreset, get_workflow_preset, select_preset
from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.review.content_profile_memory import summarize_content_profile_user_memory
from roughcut.review.subtitle_memory import (
    _extract_compound_components,
    apply_domain_term_corrections,
    summarize_subtitle_review_memory_for_polish,
)


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


def build_cover_title(profile: dict[str, Any], preset: WorkflowPreset) -> dict[str, str]:
    brand = _clean_line(profile.get("subject_brand") or profile.get("brand") or "")
    model = _clean_line(profile.get("subject_model") or profile.get("model") or "")
    subject_type = _clean_line(profile.get("subject_type") or "")
    raw_theme = str(profile.get("video_theme") or "").strip()
    theme = _clean_line(raw_theme)
    hook = _clean_line(profile.get("hook_line") or "")
    visible_text = str(profile.get("visible_text") or "").strip()
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
    auto_confirm_enabled: bool = True,
    threshold: float = 0.72,
) -> dict[str, Any]:
    normalized_threshold = max(0.0, min(1.0, float(threshold)))
    subtitle_items = subtitle_items or []
    transcript_excerpt = str(profile.get("transcript_excerpt") or "").strip()
    if not transcript_excerpt and subtitle_items:
        transcript_excerpt = build_transcript_excerpt(subtitle_items, max_items=24, max_chars=900)

    subtitle_count = sum(
        1
        for item in subtitle_items
        if _clean_line(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "")
    )
    preset_name = str(profile.get("preset_name") or "").strip()
    product_like_presets = {"unboxing_default", "unboxing_limited", "unboxing_upgrade", "edc_tactical"}

    score = 0.0
    reasons: list[str] = []
    review_reasons: list[str] = []
    blocking_reasons: list[str] = []

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

    subject_brand = str(profile.get("subject_brand") or "").strip()
    subject_model = str(profile.get("subject_model") or "").strip()
    if subject_brand or subject_model:
        score += 0.10 if preset_name in product_like_presets else 0.06
        reasons.append("识别出可验证主体")
    elif preset_name in product_like_presets:
        blocking_reasons.append("开箱类视频未识别出可验证主体")
    else:
        review_reasons.append("主体身份信息不完整")

    score = round(min(score, 1.0), 3)
    review_reasons = list(dict.fromkeys(review_reasons))
    blocking_reasons = list(dict.fromkeys(blocking_reasons))
    auto_confirm = auto_confirm_enabled and score >= normalized_threshold and not blocking_reasons

    return {
        "enabled": auto_confirm_enabled,
        "threshold": normalized_threshold,
        "score": score,
        "auto_confirm": auto_confirm,
        "reasons": reasons,
        "review_reasons": review_reasons,
        "blocking_reasons": blocking_reasons,
        "subtitle_count": subtitle_count,
        "transcript_excerpt_length": transcript_length,
    }


def _sanitize_profile_identity(
    profile: dict[str, Any],
    *,
    transcript_excerpt: str,
    source_name: str,
    memory_hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sanitized = dict(profile or {})
    transcript_hints = _seed_profile_from_transcript_excerpt(transcript_excerpt)
    visual_hints = _seed_profile_from_text(str(sanitized.get("visible_text") or "").strip())
    theme_hints = _seed_profile_from_text(str(sanitized.get("video_theme") or "").strip())
    source_hints = _seed_profile_from_text(Path(source_name).stem) if _is_informative_source_hint(Path(source_name).stem) else {}
    confirmed_fields = _extract_confirmed_profile_fields(sanitized)

    confirmed_brand = str(confirmed_fields.get("subject_brand") or "").strip()
    confirmed_model = str(confirmed_fields.get("subject_model") or "").strip()

    if confirmed_model:
        verified_model = confirmed_model
    else:
        verified_model = _supported_identity_value(
            sanitized.get("subject_model"),
            transcript_hints.get("subject_model"),
            visual_hints.get("subject_model"),
            theme_hints.get("subject_model"),
            source_hints.get("subject_model"),
        )

    if confirmed_brand:
        verified_brand = confirmed_brand
    else:
        verified_brand = _supported_identity_value(
            sanitized.get("subject_brand"),
            transcript_hints.get("subject_brand"),
            visual_hints.get("subject_brand"),
            theme_hints.get("subject_brand"),
            source_hints.get("subject_brand"),
        )
        if not verified_brand and verified_model:
            mapped_brand = _MODEL_TO_BRAND.get(_normalize_profile_value(verified_model))
            current_brand = str(sanitized.get("subject_brand") or "").strip()
            if mapped_brand and (
                not current_brand or _normalize_profile_value(current_brand) == _normalize_profile_value(mapped_brand)
            ):
                verified_brand = mapped_brand

    if not verified_brand:
        sanitized["subject_brand"] = ""
    else:
        sanitized["subject_brand"] = verified_brand

    if not verified_model:
        sanitized["subject_model"] = ""
    else:
        sanitized["subject_model"] = verified_model

    if not sanitized.get("subject_brand") and not sanitized.get("subject_model"):
        for key in ("visible_text", "hook_line", "summary", "engagement_question"):
            if key in confirmed_fields:
                continue
            value = str(sanitized.get(key) or "").strip()
            if value and _text_has_unsupported_identity(
                value,
                transcript_hints=transcript_hints,
                memory_hints=memory_hints,
                source_hints=source_hints,
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
            ):
                continue
            evidence.append(item)
        sanitized["evidence"] = evidence

    return sanitized


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
    normalized_query = _normalize_profile_value(query)
    if not normalized_query:
        return False
    transcript_norm = _normalize_profile_value(transcript_excerpt)
    if transcript_norm and normalized_query in transcript_norm:
        return True
    source_stem = Path(source_name).stem
    if _is_informative_source_hint(source_stem) and normalized_query in _normalize_profile_value(source_stem):
        return True
    return False


def _normalize_profile_value(value: object) -> str:
    return "".join(str(value or "").strip().upper().split())


def _text_has_unsupported_identity(
    text: str,
    *,
    transcript_hints: dict[str, Any],
    memory_hints: dict[str, Any] | None,
    source_hints: dict[str, Any],
) -> bool:
    seeded = _seed_profile_from_text(text)
    seeded_brand = str(seeded.get("subject_brand") or "").strip()
    seeded_model = str(seeded.get("subject_model") or "").strip()
    if not seeded_brand and not seeded_model:
        return False
    if seeded_brand and not _first_supported_identity_value(
        seeded_brand,
        transcript_hints.get("subject_brand"),
        (memory_hints or {}).get("subject_brand"),
        source_hints.get("subject_brand"),
    ):
        return True
    if seeded_model and not _first_supported_identity_value(
        seeded_model,
        transcript_hints.get("subject_model"),
        (memory_hints or {}).get("subject_model"),
        source_hints.get("subject_model"),
    ):
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
    channel_profile: str | None,
    user_memory: dict[str, Any] | None = None,
    include_research: bool = True,
    copy_style: str = "attention_grabbing",
) -> dict[str, Any]:
    transcript_excerpt = build_transcript_excerpt(subtitle_items)
    heuristic_profile = _seed_profile_from_subtitles(subtitle_items)
    memory_profile = _seed_profile_from_user_memory(transcript_excerpt, user_memory)
    memory_prompt = summarize_content_profile_user_memory(user_memory)
    initial_profile = _fallback_profile(
        source_name=source_name,
        channel_profile=channel_profile,
        transcript_excerpt=transcript_excerpt,
    )
    initial_profile.update(heuristic_profile)
    initial_profile.update(memory_profile)
    initial_profile["copy_style"] = str(copy_style or "attention_grabbing").strip() or "attention_grabbing"

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            frame_paths = _extract_reference_frames(source_path, Path(tmpdir), count=3)
            visual_hints = await _infer_visual_profile_hints(frame_paths)
            if visual_hints:
                initial_profile["visual_hints"] = dict(visual_hints)
            _merge_specific_profile_hints(initial_profile, visual_hints)
            _apply_visual_subject_guard(initial_profile)
            if frame_paths:
                prompt = (
                    "你在分析一条中文短视频。视频可能是开箱评测、录屏教学、vlog、口播观点、游戏高光或美食探店。"
                    "请结合图片和口播字幕，判断视频主体是什么。"
                    "如果画面里有产品、软件界面、店招、包装、盒体、logo、英文单词、型号字样，都优先识别。"
                    "如果是软件/AI/科技类视频，优先识别软件名、平台名、功能名、版本名和当前演示的核心主题，不要退化成“软件工具”。"
                    "尽量给出开箱产品品牌、开箱产品型号/版本，或软件品牌、功能名/模块名、主体类型、视频主题，以及适合的剪辑预设。"
                    "另外补一个适合评论区互动的问题，要贴合内容，不要总是泛泛地问值不值。"
                    "subject_brand 指视频里被开箱/被讲解的产品或主体品牌，不是频道名、作者名。"
                    "如果不确定，不要乱编，留空即可。\n\n"
                    "输出 JSON："
                    '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
                    '"preset_name":"","hook_line":"","visible_text":"","engagement_question":"","search_queries":[]}'
                    "\n要求：preset_name 只能从 unboxing_default、unboxing_limited、unboxing_upgrade、edc_tactical、screen_tutorial、vlog_daily、talking_head_commentary、gameplay_highlight、food_explore 中选择。"
                    "\n如果文件名像时间戳、相机命名或流水号，不要把它当成型号。"
                    "\nsearch_queries 提供 2-3 个适合联网搜索验证的查询词。"
                    f"\n视觉粗分类（优先级高于脏字幕和错误搜索）：{json.dumps(visual_hints, ensure_ascii=False)}"
                    f"\n用户历史偏好（仅作辅助参考，不能压过当前字幕和画面）：\n{memory_prompt or '无'}"
                    f"\n源文件名：{source_name}\n字幕节选：\n{transcript_excerpt}"
                )
                content = await complete_with_images(prompt, frame_paths, max_tokens=500, json_mode=True)
                candidate = json.loads(extract_json_text(content))
                initial_profile.update({k: v for k, v in candidate.items() if v})
                _merge_specific_profile_hints(initial_profile, heuristic_profile)
                _merge_specific_profile_hints(initial_profile, memory_profile)
                _merge_specific_profile_hints(initial_profile, visual_hints)
                _apply_visual_subject_guard(initial_profile)
    except Exception:
        pass

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你在分析中文短视频的口播内容。视频可能是开箱评测、录屏教学、vlog、口播观点、游戏高光或美食探店。"
            "请根据文件名、字幕节选和已有视觉判断，补全视频主体的开箱产品品牌、开箱产品型号/版本，或软件品牌、功能名/模块名、主体类型、视频主题，并给出适合联网验证的搜索词。"
            "同时补一个适合评论区互动的问题，要基于视频内容，不要重复泛化问题。"
            "subject_brand 指视频里被开箱/被讲解的产品或主体品牌，不是频道名、作者名。"
            "如果是软件/AI/科技类内容，subject_brand 应该是软件/平台名，subject_model 优先填功能名、模块名或版本名，video_theme 必须点明真实主题，比如某个新功能上线、某个工作流实操，而不是泛泛写“软件功能演示与教程”。"
            "如果文件名像时间戳、相机命名或流水号，不要把它当成型号。"
            "如果不确定，请留空，不要乱编。"
            "\n输出 JSON："
            '{"subject_brand":"","subject_model":"","subject_type":"","video_theme":"",'
            '"preset_name":"","hook_line":"","visible_text":"","engagement_question":"","search_queries":[]}'
            f"\n视觉粗分类（优先级高于脏字幕和错误搜索）：{json.dumps(initial_profile.get('visual_hints') or {}, ensure_ascii=False)}"
            f"\n用户历史偏好（仅作辅助参考，不能压过当前字幕和画面）：\n{memory_prompt or '无'}"
            f"\n已有判断：{json.dumps(initial_profile, ensure_ascii=False)}"
            f"\n源文件名：{source_name}\n字幕节选：\n{transcript_excerpt}"
        )
        response = await provider.complete(
            [
                Message(role="system", content="你是中文短视频内容策划助手。"),
                Message(role="user", content=prompt),
            ],
            temperature=0.1,
            max_tokens=500,
            json_mode=True,
        )
        candidate = response.as_json()
        initial_profile.update({k: v for k, v in candidate.items() if v})
        _merge_specific_profile_hints(initial_profile, heuristic_profile)
        _merge_specific_profile_hints(initial_profile, memory_profile)
        _apply_visual_subject_guard(initial_profile)
    except Exception:
        pass

    return await enrich_content_profile(
        profile=initial_profile,
        source_name=source_name,
        channel_profile=channel_profile,
        transcript_excerpt=transcript_excerpt,
        user_memory=user_memory,
        include_research=include_research,
    )


async def apply_content_profile_feedback(
    *,
    draft_profile: dict[str, Any],
    source_name: str,
    channel_profile: str | None,
    user_feedback: dict[str, Any],
    reviewed_subtitle_excerpt: str | None = None,
    accepted_corrections: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
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
        channel_profile=channel_profile,
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
        preset = get_workflow_preset(str(result.get("preset_name") or channel_profile or "unboxing_default"))
        result["cover_title"] = build_cover_title(result, preset)
    return result


async def enrich_content_profile(
    *,
    profile: dict[str, Any],
    source_name: str,
    channel_profile: str | None,
    transcript_excerpt: str,
    user_memory: dict[str, Any] | None = None,
    include_research: bool = True,
) -> dict[str, Any]:
    enriched = dict(profile or {})
    confirmed_fields = _extract_confirmed_profile_fields(enriched)
    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    memory_hints = _seed_profile_from_user_memory(transcript_excerpt, user_memory)
    enriched = _sanitize_profile_identity(
        enriched,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        memory_hints=memory_hints,
    )
    context_hints = _seed_profile_from_context(enriched, transcript_excerpt)
    memory_prompt = summarize_content_profile_user_memory(user_memory)
    _merge_specific_profile_hints(enriched, context_hints)
    _merge_specific_profile_hints(enriched, memory_hints)

    preset = select_preset(
        channel_profile=channel_profile or enriched.get("preset_name"),
        subject_model=str(enriched.get("subject_model", "")),
        subject_type=str(enriched.get("subject_type", "")),
        transcript_hint=transcript_excerpt,
    )
    enriched["preset_name"] = preset.name
    enriched["preset"] = preset.to_dict()
    enriched["transcript_excerpt"] = transcript_excerpt
    enriched = _sanitize_profile_identity(
        enriched,
        transcript_excerpt=transcript_excerpt,
        source_name=source_name,
        memory_hints=memory_hints,
    )

    if include_research:
        evidence = await _search_evidence(enriched, source_name, transcript_excerpt=transcript_excerpt)
        evidence = _filter_evidence_by_visual_subject(
            evidence,
            visual_subject_type=str(((enriched.get("visual_hints") or {}).get("subject_type") or "")),
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
                    f"\n视觉粗分类（优先级高于脏字幕和错误搜索）：{json.dumps(enriched.get('visual_hints') or {}, ensure_ascii=False)}"
                    f"\n已有判断：{json.dumps(enriched, ensure_ascii=False)}"
                    f"\n用户历史偏好（仅作辅助参考，不能压过当前字幕和画面）：\n{memory_prompt or '无'}"
                    f"\n字幕/画面线索：{transcript_excerpt}"
                    f"\n搜索证据：{json.dumps(evidence, ensure_ascii=False)}"
                )
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
                _merge_specific_profile_hints(enriched, context_hints)
                _merge_specific_profile_hints(enriched, memory_hints)
                enriched = _sanitize_profile_identity(
                    enriched,
                    transcript_excerpt=transcript_excerpt,
                    source_name=source_name,
                    memory_hints=memory_hints,
                )
                _apply_visual_subject_guard(enriched)
            except Exception:
                pass

    _apply_confirmed_profile_fields(enriched, confirmed_fields)
    _apply_visual_subject_guard(enriched)

    if _is_generic_subject_type(str(enriched.get("subject_type") or "")):
        hinted = memory_hints or context_hints
        if hinted.get("subject_type"):
            enriched["subject_type"] = hinted["subject_type"]

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


async def _infer_visual_profile_hints(frame_paths: list[Path]) -> dict[str, Any]:
    if not frame_paths:
        return {}
    try:
        prompt = (
            "只看这组视频画面，不参考字幕。"
            "请判断画面里被重点展示或被手持操作的主体属于哪一类。"
            "优先在这些类型中选择：EDC折刀、多功能工具钳、智能灯具、软件界面、人物口播、食品饮品、游戏画面、其他产品。"
            "如果画面里能直接看到型号、品牌字样，也提取出来。"
            "不要因为背景海报、桌垫、摆件或贴纸误判主体。"
            "输出 JSON："
            '{"subject_type":"","visible_text":"","reason":""}'
        )
        content = await complete_with_images(prompt, frame_paths, max_tokens=220, json_mode=True)
        data = json.loads(extract_json_text(content))
        subject_type = str(data.get("subject_type") or "").strip()
        visible_text = str(data.get("visible_text") or "").strip()
        if not subject_type and not visible_text:
            return {}
        return {
            "subject_type": subject_type,
            "visible_text": visible_text[:24],
            "reason": str(data.get("reason") or "").strip(),
        }
    except Exception:
        return {}


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
    visual_hints = profile.get("visual_hints") or {}
    visual_subject_type = str(visual_hints.get("subject_type") or "").strip()
    if not visual_subject_type:
        return
    current_subject_type = str(profile.get("subject_type") or "").strip()
    visual_family = _subject_type_family(visual_subject_type)
    current_family = _subject_type_family(current_subject_type)
    if not current_subject_type or _is_generic_subject_type(current_subject_type):
        profile["subject_type"] = visual_subject_type
    elif visual_family and current_family and visual_family != current_family:
        profile["subject_type"] = visual_subject_type
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
    preset = get_workflow_preset(content_profile.get("preset_name"))
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
                    "7. 输出 JSON：{\"items\":[{\"index\":1,\"text_final\":\"...\"}]}\n\n"
                    f"视频主体：{json.dumps(content_profile, ensure_ascii=False)}\n"
                    f"预设要求：{preset.subtitle_goal}；风格：{preset.subtitle_tone}\n"
                    f"词表：\n{glossary_text}\n"
                    f"同类内容记忆：\n{review_memory_text or '无'}\n"
                    f"搜索证据：\n{evidence_text}\n"
                    f"待处理字幕：{json.dumps(payload_items, ensure_ascii=False)}"
                )
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
                        polished = _cleanup_polished_text(polished)
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
    queries: list[str] = []
    for value in profile.get("search_queries") or []:
        if value:
            queries.append(str(value))

    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    subject_type = str(profile.get("subject_type") or "").strip()
    visible_text = str(profile.get("visible_text") or "").strip()
    source_stem = Path(source_name).stem
    signal_terms = _extract_search_signal_terms(transcript_excerpt, visible_text, source_stem)
    topic_terms = _extract_topic_terms("\n".join(part for part in (transcript_excerpt, visible_text, source_stem) if part))
    software_like = _is_software_like_subject(subject_type, brand=brand, model=model, topic_terms=topic_terms)

    if brand and model:
        queries.append(f"{brand} {model}")
        if software_like:
            queries.append(f"{brand} {model} 教程")
            queries.append(f"{brand} {model} 功能")
        else:
            queries.append(f"{brand} {model} 开箱")
    elif brand:
        for term in signal_terms[:2]:
            queries.append(f"{brand} {term}")
            if subject_type:
                queries.append(f"{brand} {term} {subject_type}")
    elif model:
        if subject_type and not _is_generic_subject_type(subject_type):
            queries.append(f"{model} {subject_type}")
            compact_subject = _subject_type_search_anchor(subject_type)
            if compact_subject:
                queries.append(f"{model} {compact_subject}")
        else:
            queries.append(model)
            queries.append(f"{model} 开箱")
        if subject_type:
            queries.append(f"{model} {subject_type}")
    if brand and subject_type:
        queries.append(f"{brand} {subject_type}")
    if model and subject_type:
        queries.append(f"{model} {subject_type}")
    if software_like and brand and model and any(term in {"无限画布", "漫剧工作流", "工作流", "节点编排", "智能体"} for term in topic_terms):
        for topic in topic_terms[:3]:
            if topic != model:
                queries.append(f"{brand} {topic}")
            queries.append(f"{brand} {topic} 教程")
        if "无限画布" in topic_terms or model == "无限画布":
            queries.append(f"{brand} 无限画布 漫剧")
    if not brand and not model:
        for term in signal_terms[:3]:
            suffix = "教程" if software_like else "开箱"
            queries.append(f"{term} {suffix}")
            if subject_type and not _is_generic_subject_type(subject_type):
                queries.append(f"{term} {subject_type}")
    if _is_informative_source_hint(source_stem):
        queries.append(source_stem)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


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
    "SK05二代ProUV版": "Loop露普",
    "SK05二代Pro UV版": "Loop露普",
    "SK05二代UV版": "Loop露普",
    "SK05二代 UV版": "Loop露普",
    "SK05UV版": "Loop露普",
    "SK05 UV版": "Loop露普",
}


def _seed_profile_from_subtitles(subtitle_items: list[dict]) -> dict[str, Any]:
    transcript_lines = [
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items
    ]
    transcript = "\n".join(line for line in transcript_lines if line)
    return _seed_profile_from_text(transcript)


def _seed_profile_from_transcript_excerpt(transcript_excerpt: str) -> dict[str, Any]:
    return _seed_profile_from_text(transcript_excerpt)


def _seed_profile_from_context(profile: dict[str, Any], transcript_excerpt: str) -> dict[str, Any]:
    text = "\n".join(
        part
        for part in (
            transcript_excerpt,
            str(profile.get("visible_text") or "").strip(),
            str(profile.get("hook_line") or "").strip(),
        )
        if part
    )
    return _seed_profile_from_text(text)


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
            if field_name in {"subject_brand", "subject_model", "subject_type", "video_theme"} and field_name not in seeded:
                seeded[field_name] = corrected

    for field_name in ("subject_brand", "subject_model", "subject_type"):
        if field_name in seeded:
            continue
        for item in field_preferences.get(field_name) or []:
            value = str(item.get("value") or "").strip()
            if value and _normalize_profile_value(value) in transcript_norm:
                seeded[field_name] = value
                break

    if "video_theme" not in seeded:
        for item in field_preferences.get("video_theme") or []:
            value = str(item.get("value") or "").strip()
            if not value:
                continue
            tokens = [token for token in re.split(r"[\s/·\-]+", value) if token]
            hit_count = sum(1 for token in tokens if _normalize_profile_value(token) and _normalize_profile_value(token) in transcript_norm)
            if hit_count >= 2:
                seeded["video_theme"] = value
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

    if "subject_type" not in seeded:
        transcript_seed = _seed_profile_from_text(transcript_excerpt)
        if transcript_seed.get("subject_type"):
            seeded["subject_type"] = transcript_seed["subject_type"]
        elif seeded.get("subject_brand") == "Loop露普" or str(seeded.get("subject_model") or "").startswith("SK05"):
            seeded["subject_type"] = "EDC手电"

    return seeded


def _seed_profile_from_text(transcript: str) -> dict[str, Any]:
    normalized = transcript.upper()
    canon = _canonicalize_spoken_identity_text(transcript)

    brand = ""
    for name, pattern in _BRAND_ALIAS_PATTERNS:
        if pattern.search(transcript):
            brand = name
            break

    model = ""
    if re.search(r"(?<![A-Z0-9])ARC(?![A-Z0-9])", normalized):
        model = "ARC"
    elif re.search(r"(?<![A-Z0-9])SURGE(?![A-Z0-9])", normalized):
        model = "SURGE"
    elif re.search(r"(?<![A-Z0-9])CHARGE(?![A-Z0-9])", normalized):
        model = "CHARGE"
    else:
        model = _extract_edc_flashlight_model(canon)

    if not brand and model in _MODEL_TO_BRAND:
        brand = _MODEL_TO_BRAND[model]

    subject_type = ""
    knife_keywords = ("折刀", "刀片", "锁定机构", "推刀", "梯片", "锁片", "刀柄", "柄身", "开刃")
    plier_keywords = ("工具钳", "钳子", "尖嘴钳", "钢丝钳")
    flashlight_keywords = ("手电", "电筒", "筒身", "紫光", "UV", "流明", "泛光", "照射")

    if brand == "LEATHERMAN" or model in {"ARC", "SURGE", "CHARGE"}:
        subject_type = "多功能工具钳"
    elif brand == "REATE" or any(keyword in transcript for keyword in knife_keywords):
        subject_type = "EDC折刀"
    elif brand == "Loop露普" or model.startswith("SK05") or any(keyword in canon.upper() for keyword in flashlight_keywords):
        subject_type = "EDC手电"
    elif any(keyword in transcript for keyword in plier_keywords):
        subject_type = "多功能工具钳"

    topic_terms = _extract_topic_terms(transcript)
    tech_brand = _detect_primary_tech_brand(transcript, topic_terms=topic_terms)
    feature = topic_terms[0] if topic_terms else ""
    tech_subject_type = _infer_tech_subject_type(
        transcript=transcript,
        tech_brand=tech_brand,
        topic_terms=topic_terms,
    )
    if tech_brand and not brand:
        brand = tech_brand
    if tech_subject_type:
        subject_type = tech_subject_type
    if feature and not model:
        model = feature

    seeded: dict[str, Any] = {}
    if brand:
        seeded["subject_brand"] = brand
    if model:
        seeded["subject_model"] = model
    if subject_type:
        seeded["subject_type"] = subject_type
    video_theme = _build_seeded_video_theme(
        transcript=transcript,
        brand=brand,
        model=model,
        subject_type=subject_type,
        topic_terms=topic_terms,
    )
    if video_theme:
        seeded["video_theme"] = video_theme
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
    if hints.get("subject_type") and _is_generic_subject_type(str(profile.get("subject_type") or "")):
        profile["subject_type"] = hints["subject_type"]
    hinted_theme = str(hints.get("video_theme") or "").strip()
    current_theme = str(profile.get("video_theme") or "").strip()
    preset_name = str(profile.get("preset_name") or "").strip()
    if hinted_theme and _is_specific_video_theme(hinted_theme, preset_name=preset_name):
        if not _is_specific_video_theme(current_theme, preset_name=preset_name):
            profile["video_theme"] = hinted_theme

    current_queries = [str(item).strip() for item in profile.get("search_queries") or [] if str(item).strip()]
    for item in hints.get("search_queries") or []:
        value = str(item).strip()
        if value and value not in current_queries:
            current_queries.append(value)
    if current_queries:
        profile["search_queries"] = current_queries


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
    normalized = _clean_line(text)
    if not normalized:
        return False
    if normalized in {"产品开箱与上手体验", "产品开箱评测", "新品开箱评测", "开箱评测", "开箱体验", "上手体验", "产品体验", "评测"}:
        return False
    default_theme = _clean_line(_default_video_theme_by_name(preset_name))
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

    frames: list[Path] = []
    for i in range(count):
        seek = duration * (i + 1) / (count + 1)
        out = tmpdir / f"profile_{i:02d}.jpg"
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

    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(source_path)],
        capture_output=True,
        timeout=10,
    )
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace"))
    except Exception:
        return 0.0
    return float(data.get("format", {}).get("duration", 0.0) or 0.0)


def _fallback_profile(
    *,
    source_name: str,
    channel_profile: str | None,
    transcript_excerpt: str,
) -> dict[str, Any]:
    preset = select_preset(
        channel_profile=channel_profile,
        transcript_hint=transcript_excerpt,
    )
    subject_type = _default_subject_type_for_preset(preset)
    video_theme = _default_video_theme_for_preset(preset)
    engagement_question = _default_engagement_question(preset)
    return {
        "subject_brand": "",
        "subject_model": "",
        "subject_type": subject_type,
        "video_theme": video_theme,
        "preset_name": preset.name,
        "preset": preset.to_dict(),
        "hook_line": preset.cover_accent,
        "summary": _build_profile_summary(
            {
                "subject_brand": "",
                "subject_model": "",
                "subject_type": subject_type,
                "video_theme": video_theme,
                "preset_name": preset.name,
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

    if preset.name == "screen_tutorial":
        return "这一步你平时最容易卡在哪？"
    if preset.name == "vlog_daily":
        return "这种日常节奏你还想看我拍哪一段？"
    if preset.name == "talking_head_commentary":
        return "这个判断你是赞同还是反对？"
    if preset.name == "gameplay_highlight":
        return "这波如果换你来打会怎么处理？"
    if preset.name == "food_explore":
        return "这家店你会为了这道菜专门跑一趟吗？"
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
    polished = re.sub(r"(。){2,}", "。", polished)
    polished = re.sub(r"(，){2,}", "，", polished)
    return polished


def _cleanup_polished_text(text: str) -> str:
    text = re.sub(r"\s+", "", text.strip())
    text = text.replace("「", "“").replace("」", "”")
    text = re.sub(r"[!！]{2,}", "！", text)
    text = re.sub(r"[?？]{2,}", "？", text)
    return text


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


_LEADING_FILLER_RE = re.compile(
    r"^(?:(?:呃|嗯|啊|诶|欸|哎)(?:[，,\s]*))+",
)
_PURE_FILLER_CLAUSE_RE = re.compile(r"^(?:呃|嗯|啊|诶|欸|哎)+$")
_TRAILING_FILLER_RE = re.compile(r"(?:啊|呀|哈|哦)+$")


def _remove_subtitle_filler_words(text: str, *, prev_text: str = "", next_text: str = "") -> str:
    result = str(text or "").strip()
    if not result:
        return result

    pieces = [piece for piece in re.split(r"([，,。！？!?；;])", result) if piece != ""]
    cleaned: list[str] = []
    for piece in pieces:
        if piece in "，,。！？!?；;":
            cleaned.append(piece)
            continue
        clause = piece.strip()
        if not clause:
            continue
        clause = _LEADING_FILLER_RE.sub("", clause).strip()
        if not clause:
            continue
        if _PURE_FILLER_CLAUSE_RE.fullmatch(clause):
            continue
        trimmed_clause = _TRAILING_FILLER_RE.sub("", clause).strip()
        if trimmed_clause and trimmed_clause != clause and len(trimmed_clause) >= 4:
            clause = trimmed_clause
        cleaned.append(clause)

    collapsed = "".join(cleaned).strip("，,")
    collapsed = re.sub(r"([，,]){2,}", r"\1", collapsed)
    collapsed = re.sub(r"^[，,]+", "", collapsed)
    collapsed = re.sub(r"[，,]+([。！？!?；;])", r"\1", collapsed)
    if not collapsed:
        return str(text or "").strip()
    return collapsed or str(text or "").strip()


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
    original = _cleanup_polished_text(original_text)
    polished = _cleanup_polished_text(polished_text)
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
    if preset.name == "screen_tutorial":
        return "教程"
    if preset.name == "vlog_daily":
        return "VLOG"
    if preset.name == "talking_head_commentary":
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
    if preset.name == "screen_tutorial":
        fallback = _build_screen_tutorial_cover_hook(
            brand=brand,
            model=model,
            subject_type=subject_type,
            theme=theme,
            copy_style=copy_style,
        )
    elif preset.name == "unboxing_limited":
        fallback = "限定细节值不值"
    elif preset.name == "unboxing_upgrade":
        fallback = "这次升级够不够狠"
    elif preset.name == "edc_tactical":
        fallback = "做工结构直接看"
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
    if preset.name == "screen_tutorial":
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
    if any(token in normalized for token in ("升级", "够不够", "值不值", "重点", "细节", "讲透")):
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


def _build_profile_summary(profile: dict[str, Any]) -> str:
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    preset_name = str(profile.get("preset_name") or "").strip()
    subject_type = str(profile.get("subject_type") or _default_subject_type_by_name(preset_name)).strip()
    theme = str(profile.get("video_theme") or _default_video_theme_by_name(preset_name)).strip()
    parts = [part for part in (brand, model or subject_type) if part]
    product = " ".join(parts).strip() or subject_type
    if preset_name == "screen_tutorial":
        return f"这条视频主要围绕{product}的操作演示展开，内容方向偏{theme}，重点是步骤清晰、术语准确，方便后续剪成可跟做的教程。"
    if preset_name == "vlog_daily":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是保留生活感、场景切换和真实情绪。"
    if preset_name == "talking_head_commentary":
        return f"这条视频主要围绕{product}展开表达，内容方向偏{theme}，重点是观点钩子、论点节奏和结论清晰。"
    if preset_name == "gameplay_highlight":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是高能操作、关键节点和结果反馈。"
    if preset_name == "food_explore":
        return f"这条视频主要围绕{product}展开，内容方向偏{theme}，重点是店名菜名、口感描述和是否值得去。"
    return f"这条视频主要围绕{product}展开，内容方向偏{theme}，适合后续做搜索校验、字幕纠错和剪辑包装。"


def _default_subject_type_for_preset(preset: WorkflowPreset) -> str:
    return _default_subject_type_by_name(preset.name)


def _default_subject_type_by_name(preset_name: str) -> str:
    mapping = {
        "screen_tutorial": "录屏教学",
        "vlog_daily": "Vlog日常",
        "talking_head_commentary": "口播观点",
        "gameplay_highlight": "游戏实况",
        "food_explore": "探店试吃",
    }
    return mapping.get(preset_name, "开箱产品")


def _default_video_theme_for_preset(preset: WorkflowPreset) -> str:
    return _default_video_theme_by_name(preset.name)


def _default_video_theme_by_name(preset_name: str) -> str:
    mapping = {
        "screen_tutorial": "软件流程演示与步骤讲解",
        "vlog_daily": "日常记录与生活分享",
        "talking_head_commentary": "观点表达与信息拆解",
        "gameplay_highlight": "高能操作与对局复盘",
        "food_explore": "探店试吃与性价比判断",
    }
    return mapping.get(preset_name, "产品开箱与上手体验")


def _default_engagement_question(preset: WorkflowPreset) -> str:
    mapping = {
        "screen_tutorial": "这套流程你会直接照着做吗？",
        "vlog_daily": "你最想看我下次拍哪种日常？",
        "talking_head_commentary": "这件事你同意这个判断吗？",
        "gameplay_highlight": "这波操作你会怎么打？",
        "food_explore": "这家店你会专门去吃一次吗？",
    }
    return mapping.get(preset.name, "你觉得这次到手值不值？")
