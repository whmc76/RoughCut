from __future__ import annotations

import asyncio
from collections import deque
import inspect
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image

from roughcut.config import get_settings, llm_task_route
from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token
from roughcut.media.output import _extract_frame, _overlay_title_layout, _probe_duration, _sample_cover_candidates, _title_style_tokens
from roughcut.packaging.library import list_packaging_assets
from roughcut.providers.image_generation import CodexImageGenerationPending, generate_edited_cover_image
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.review.intelligent_copy_cover_quality import assess_cover_publish_readiness
from roughcut.review.content_profile import _seed_profile_from_text, _subject_domain_from_subject_type, infer_content_profile
from roughcut.publication_platform_matrix import (
    evaluate_platform_schedule_window,
    normalize_publication_platform_name,
    platform_default_declaration,
    platform_manual_handoff_only,
    platform_manual_publish_entry_url,
    platform_requires_custom_cover_policy,
    platform_requires_explicit_collection_policy,
    publication_collection_policy_skip_values,
    suggest_platform_schedule_window_repair,
)
from roughcut.publication_packaging import publication_packaging_entry_publish_ready
from roughcut.publication_intelligence import build_cached_publication_scheme
from roughcut.review.platform_copy import PLATFORM_ORDER, generate_platform_packaging, save_platform_packaging_markdown
from roughcut.review.intelligent_copy_scoring import score_description, score_title_candidate
from roughcut.review.intelligent_copy_templates import build_platform_description, build_title_candidates
from roughcut.review.platform_copy import build_fallback_description, build_fallback_titles
from roughcut.review.intelligent_copy_topics import IntelligentCopyTopicSpec, match_intelligent_copy_topic

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MATERIAL_DIR_NAME = "smart-copy"
TITLE_OPTION_LIMIT = 3
IntelligentCopyProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
MATERIAL_SELF_HEAL_MAX_PASSES = 2

OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO = "edc_cinematic_hero"
OFFICIAL_COVER_STYLE_TECH_SHOWCASE = "tech_showcase"
OFFICIAL_COVER_STYLE_BRAND_STORY = "brand_story"
OFFICIAL_COVER_STYLE_DOCUMENTARY = "documentary"
COVER_IMAGE_STYLE_SCHEMES: dict[str, dict[str, str]] = {
    OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO: {
        "label": "EDC 电影英雄封面",
        "prompt": (
            "风格：EDC 电影英雄封面，暖金暗色史诗背景，场景层次明显，背景不能单调留白。"
            "有高能电光、雷电、火花、火焰余烬、速度线和赛博朋克发光轮廓，但都只服务主体，不盖过商品。"
            "主体要像英雄物件，金属高光强，暗部对比足，风格化明显，但商品本身保持真实。"
            "整体像成熟短视频爆款封面，而不是普通产品海报。"
        ),
    },
    OFFICIAL_COVER_STYLE_TECH_SHOWCASE: {
        "label": "科技质感封面",
        "prompt": (
            "风格：科技质感封面，硬朗对比，金属高光，局部边缘光，深色干净背景，带轻量速度感。"
            "主体像高端产品 hero shot，但保持真实。"
        ),
    },
    OFFICIAL_COVER_STYLE_BRAND_STORY: {
        "label": "品牌故事封面",
        "prompt": (
            "风格：品牌故事封面，画面精致，光线高级，层次柔和，有生活方式质感。"
            "氛围可以增强，但主体保持真实。"
        ),
    },
    OFFICIAL_COVER_STYLE_DOCUMENTARY: {
        "label": "纪实封面",
        "prompt": (
            "风格：纪实封面，主体真实可信，保留实拍感。"
            "只做轻度整理，背景更干净，主体更清楚。"
        ),
    },
}

COVER_DIRECTOR_STYLE_PROFILES: dict[str, dict[str, Any]] = {
    OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO: {
        "style_profile_key": "edc_cinematic_hero_full_cover_v1",
        "headline_effects": ["metal_3d", "lightning_edge_glow", "ember_fire_energy", "cyberpunk_blue_orange_contrast"],
        "layout_contract": ["brand_line", "main_title", "subtitle", "hook_badge"],
        "composition_contract": {
            "title_stage": "upper_center",
            "subject_stage": "lower_half",
            "avoid_occluding_primary_subject": True,
            "support_compare_subject_pair": True,
        },
    },
    OFFICIAL_COVER_STYLE_TECH_SHOWCASE: {
        "style_profile_key": "tech_showcase_full_cover_v1",
        "headline_effects": ["clean_chrome", "electric_edge_glow"],
        "layout_contract": ["brand_line", "main_title", "subtitle", "hook_badge"],
        "composition_contract": {
            "title_stage": "upper_center",
            "subject_stage": "lower_half",
            "avoid_occluding_primary_subject": True,
        },
    },
    OFFICIAL_COVER_STYLE_BRAND_STORY: {
        "style_profile_key": "brand_story_full_cover_v1",
        "headline_effects": ["premium_glass", "soft_glow"],
        "layout_contract": ["brand_line", "main_title", "subtitle", "hook_badge"],
        "composition_contract": {
            "title_stage": "upper_center",
            "subject_stage": "mid_lower",
            "avoid_occluding_primary_subject": True,
        },
    },
    OFFICIAL_COVER_STYLE_DOCUMENTARY: {
        "style_profile_key": "documentary_full_cover_v1",
        "headline_effects": ["clean_solid", "high_readability"],
        "layout_contract": ["brand_line", "main_title", "subtitle", "hook_badge"],
        "composition_contract": {
            "title_stage": "upper_center",
            "subject_stage": "center_lower",
            "avoid_occluding_primary_subject": True,
        },
    },
}


def _resolve_cover_source_candidate_count(requested_count: int) -> int:
    safe_requested = max(1, int(requested_count or 0))
    if safe_requested <= 4:
        return 4
    return 9

PLATFORM_PUBLISH_RULES: dict[str, dict[str, Any]] = {
    "bilibili": {
        "label": "B站",
        "body_label": "简介",
        "tag_label": "标签",
        "has_title": True,
        "title_limit": 80,
        "body_limit": 250,
        "tag_limit": 10,
        "tag_style": "csv",
        "cover_size": (1280, 720),
        "title_style": "tutorial_blueprint",
        "cover_style": "tech_showcase",
        "rule_note": "偏信息密度和搜索词，避免危险导向和夸张参数。",
    },
    "xiaohongshu": {
        "label": "小红书",
        "body_label": "正文",
        "tag_label": "话题",
        "has_title": True,
        "title_limit": 20,
        "body_limit": 1000,
        "tag_limit": 8,
        "tag_style": "hashtags_space",
        "cover_size": (1080, 1440),
        "title_style": "double_banner",
        "cover_style": "brand_story",
        "rule_note": "偏分享笔记语气，适合 3:4 竖版封面和话题串。",
    },
    "douyin": {
        "label": "抖音",
        "body_label": "简介",
        "tag_label": "标签",
        "has_title": True,
        "title_limit": 55,
        "body_limit": 300,
        "tag_limit": 5,
        "tag_style": "hashtags_space",
        "cover_size": (1080, 1920),
        "title_style": "comic_boom",
        "cover_style": "tech_showcase",
        "rule_note": "优先竖版 9:16，结果先行，避免危险动作引导。",
    },
    "kuaishou": {
        "label": "快手",
        "body_label": "简介",
        "tag_label": "标签",
        "has_title": False,
        "title_limit": 26,
        "body_limit": 300,
        "tag_limit": 4,
        "tag_style": "hashtags_space",
        "cover_size": (1080, 1920),
        "title_style": "comic_boom",
        "cover_style": "documentary",
        "rule_note": "按作品描述输出，优先竖版 9:16，口语直给，少一点精修腔。",
    },
    "wechat_channels": {
        "label": "视频号",
        "body_label": "简介",
        "tag_label": "标签",
        "has_title": False,
        "title_limit": 20,
        "body_limit": 1000,
        "tag_limit": 6,
        "tag_style": "hashtags_space",
        "cover_size": (1080, 1920),
        "title_style": "documentary_stamp",
        "cover_style": "documentary",
        "rule_note": "按作品描述输出，偏稳妥可信，竖版封面更通用，少用夸张网感词。",
    },
    "toutiao": {
        "label": "头条号",
        "body_label": "简介",
        "tag_label": "标签",
        "has_title": True,
        "title_limit": 30,
        "body_limit": 1000,
        "tag_limit": 5,
        "tag_style": "csv",
        "cover_size": (1280, 720),
        "title_style": "documentary_stamp",
        "cover_style": "documentary",
        "rule_note": "偏资讯摘要和观点导语，适合结论先行。",
    },
    "youtube": {
        "label": "YouTube",
        "body_label": "描述",
        "tag_label": "标签",
        "has_title": True,
        "title_limit": 100,
        "body_limit": 5000,
        "tag_limit": 15,
        "tag_style": "csv",
        "cover_size": (1280, 720),
        "title_style": "chrome_impact",
        "cover_style": "tech_showcase",
        "rule_note": "标题/描述更适合清晰检索词，标签按逗号串更方便粘贴。",
    },
    "x": {
        "label": "X",
        "body_label": "推文",
        "tag_label": "Hashtags",
        "has_title": False,
        "title_limit": 50,
        "body_limit": 280,
        "tag_limit": 2,
        "tag_style": "hashtags_space",
        "cover_size": (1600, 900),
        "title_style": "chrome_impact",
        "cover_style": "tech_showcase",
        "rule_note": "无独立标题，正文要在 280 字内，hashtags 建议克制。",
    },
}


def _normalize_external_publish_platform_key(value: Any) -> str:
    return normalize_publication_platform_name(str(value or "").strip())


def _normalize_internal_publish_platform_key(value: Any) -> str:
    normalized = _normalize_external_publish_platform_key(value)
    if normalized == "wechat-channels":
        return "wechat_channels"
    return normalized


def inspect_intelligent_copy_folder(folder_path: str) -> dict[str, Any]:
    requested_folder_path = str(folder_path or "").strip().strip('"')
    folder = _resolve_existing_folder(folder_path)
    video_files = sorted((item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in VIDEO_SUFFIXES), key=_sort_by_size_desc)
    subtitle_files = sorted((item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in SUBTITLE_SUFFIXES))
    cover_files = sorted((item for item in folder.iterdir() if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES))
    primary_video = _pick_primary_video(video_files=video_files, subtitle_files=subtitle_files)
    primary_subtitle = _pick_primary_subtitle(subtitle_files=subtitle_files, video_file=primary_video)
    primary_cover = _pick_primary_cover(cover_files=cover_files, video_file=primary_video)
    warnings: list[str] = []
    if primary_video is None:
        warnings.append("目录内未找到可用成片视频。")
    if primary_subtitle is None:
        warnings.append("目录内未找到可用字幕文件。")
    display_folder_path = _display_folder_path_for_inspection(requested_folder_path, folder)
    return {
        "folder_path": display_folder_path,
        "material_dir": str(folder / MATERIAL_DIR_NAME),
        "video_file": str(primary_video) if primary_video else None,
        "subtitle_file": str(primary_subtitle) if primary_subtitle else None,
        "cover_file": str(primary_cover) if primary_cover else None,
        "extra_video_files": [str(item) for item in video_files if item != primary_video],
        "extra_subtitle_files": [str(item) for item in subtitle_files if item != primary_subtitle],
        "extra_cover_files": [str(item) for item in cover_files if item != primary_cover],
        "warnings": warnings,
    }


async def _emit_intelligent_copy_progress(
    progress_callback: IntelligentCopyProgressCallback | None,
    payload: dict[str, Any],
) -> None:
    if progress_callback is None:
        return
    result = progress_callback(payload)
    if result is not None:
        await result


async def _maybe_await(result: Any) -> Any:
    if inspect.isawaitable(result):
        return await result
    return result


async def _resolve_generate_platform_packaging(**kwargs: Any) -> dict[str, Any]:
    result = await _maybe_await(generate_platform_packaging(**kwargs))
    return result if isinstance(result, dict) else {}


async def generate_intelligent_copy(
    folder_path: str,
    *,
    copy_style: str | None = None,
    platforms: list[str] | None = None,
    use_existing_cover: bool = False,
    creator_profile_id: str | None = None,
    creator_profile_name: str | None = None,
    progress_callback: IntelligentCopyProgressCallback | None = None,
) -> dict[str, Any]:
    inspection = inspect_intelligent_copy_folder(folder_path)
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 5,
            "stage": "inspect",
            "message": "已读取目录，正在确认成片和字幕。",
            "inspection": inspection,
            "folder_path": inspection.get("folder_path"),
            "material_dir": inspection.get("material_dir"),
        },
    )
    video_path = Path(str(inspection.get("video_file") or ""))
    subtitle_path = Path(str(inspection.get("subtitle_file") or ""))
    cover_path = Path(str(inspection.get("cover_file") or "")) if inspection.get("cover_file") else None
    display_folder_path = str(inspection.get("folder_path") or video_path.parent)
    if not video_path.exists():
        raise ValueError("目录内未找到可用成片视频。")
    if not subtitle_path.exists():
        raise ValueError("目录内未找到可用字幕文件。")

    subtitle_items = _load_subtitle_items(subtitle_path)
    if not subtitle_items:
        raise ValueError("字幕文件已找到，但无法解析出可用字幕内容。")
    selected_platform_keys = _resolve_intelligent_copy_platform_keys(platforms)
    material_dir = video_path.parent / MATERIAL_DIR_NAME
    material_dir.mkdir(parents=True, exist_ok=True)
    existing_result = _load_existing_intelligent_copy_result(material_dir)
    existing_packaging = _load_existing_intelligent_copy_packaging(
        material_dir=material_dir,
        platform_keys=selected_platform_keys,
        fallback_result=existing_result,
    )
    reusable_materials = _collect_reusable_platform_materials(existing_result, platform_keys=selected_platform_keys)
    platforms_requiring_regeneration = [key for key in selected_platform_keys if key not in reusable_materials]
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 18,
            "stage": "subtitles",
            "message": f"已解析 {len(subtitle_items)} 条字幕，正在生成内容画像。",
            "inspection": inspection,
            "folder_path": inspection.get("folder_path"),
            "material_dir": inspection.get("material_dir"),
        },
    )

    packaging_state = list_packaging_assets()
    packaging_config = packaging_state.get("config") if isinstance(packaging_state, dict) else {}
    resolved_copy_style = str(copy_style or (packaging_config or {}).get("copy_style") or "attention_grabbing").strip() or "attention_grabbing"
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 26,
            "stage": "profile",
            "message": "正在提炼主题、卖点和发布语气。",
            "inspection": inspection,
            "folder_path": inspection.get("folder_path"),
            "material_dir": inspection.get("material_dir"),
        },
    )

    content_profile = _build_intelligent_copy_fast_profile(
        video_path=video_path,
        subtitle_items=subtitle_items,
        copy_style=resolved_copy_style,
    )
    if not content_profile:
        profile_items = subtitle_items[:80]
        try:
            content_profile = await asyncio.wait_for(
                infer_content_profile(
                    source_path=video_path,
                    source_name=video_path.name,
                    subtitle_items=profile_items,
                    transcript_items=profile_items,
                    workflow_template=None,
                    include_research=False,
                    copy_style=resolved_copy_style,
                    source_context={
                        "mode": "intelligent_copy",
                        "folder_path": str(video_path.parent),
                        "video_description": f"对已剪好的成片目录直接生成多平台发布素材：{video_path.parent.name}",
                    },
                ),
                timeout=45,
            )
        except Exception:
            content_profile = {}
        content_profile = _merge_intelligent_copy_profile_hints(
            content_profile=content_profile,
            video_path=video_path,
            subtitle_items=subtitle_items,
            copy_style=resolved_copy_style,
        )
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 42,
            "stage": "brief",
            "message": "内容画像已完成，正在组织多平台文案策略。",
            "inspection": inspection,
            "folder_path": inspection.get("folder_path"),
            "material_dir": inspection.get("material_dir"),
        },
    )
    content_profile = _ensure_intelligent_copy_subject_identity(content_profile, video_path)
    copy_brief = _build_intelligent_copy_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
    )
    generated_packaging: dict[str, Any] | None = None
    if platforms_requiring_regeneration:
        generated_packaging = await _resolve_generate_platform_packaging(
            source_name=video_path.name,
            content_profile=content_profile,
            subtitle_items=subtitle_items,
            copy_style=resolved_copy_style,
            target_platforms=platforms_requiring_regeneration,
            prompt_brief={
                "mode": "intelligent_copy",
                "source_name": video_path.name,
                "copy_brief": copy_brief,
                "content_profile_summary": _content_profile_summary(content_profile),
                "requirements": [
                    "最终发布文案必须自然、像真人发布，不要模板腔、总结腔、AI味。",
                    "不要用空话凑长度；没有事实证据就写体验、画面和观感，不写参数。",
                    "每个平台都要有明显平台语气差异。",
                ],
            },
        )
        generated_packaging = _filter_intelligent_copy_packaging(generated_packaging, platforms_requiring_regeneration)
    packaging = _merge_resume_packaging(
        existing_packaging=existing_packaging,
        generated_packaging=generated_packaging,
        platform_keys=selected_platform_keys,
    )
    if reusable_materials:
        reused_count = len(reusable_materials)
        regen_count = len(platforms_requiring_regeneration)
        detail = f"已复用 {reused_count} 个已有平台物料"
        if regen_count:
            detail += f"，仅补 {regen_count} 个平台缺口"
        await _emit_intelligent_copy_progress(
            progress_callback,
            {
                "progress": 48,
                "stage": "resume",
                "message": detail + "。",
                "inspection": inspection,
                "folder_path": inspection.get("folder_path"),
                "material_dir": inspection.get("material_dir"),
            },
        )
    markdown_path = material_dir / "platform-packaging.md"
    platform_packaging_json_path = material_dir / "platform-packaging.json"
    json_path = material_dir / "smart-copy.json"
    save_platform_packaging_markdown(markdown_path, packaging)
    cover_source = await _maybe_await(_prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile=content_profile,
        packaging=packaging,
    ))
    cover_source_manifest = _load_cover_source_manifest(material_dir / "00-highlight-cover-source.json")
    cover_brief = await _maybe_await(_build_intelligent_cover_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=cover_path,
    ))
    base_result = {
        "folder_path": display_folder_path,
        "material_dir": str(material_dir),
        "markdown_path": str(markdown_path),
        "platform_packaging_json_path": str(platform_packaging_json_path),
        "json_path": str(json_path),
        "cover_source_path": str(cover_source) if cover_source else None,
        "cover_source_manifest": cover_source_manifest,
        "use_existing_cover": bool(use_existing_cover),
        "cover_brief": cover_brief,
        "copy_style": resolved_copy_style,
        "inspection": inspection,
        "highlights": dict(packaging.get("highlights") or {}),
        "fact_sheet": dict(packaging.get("fact_sheet") or {}),
        "title_audit": dict(packaging.get("title_audit") or {}),
        "generation_repair_trace": list(packaging.get("generation_repair_trace") or []),
        "content_profile_summary": _content_profile_summary(content_profile),
        "warnings": list(inspection.get("warnings") or []),
        "creator_profile_id": str(creator_profile_id or "").strip() or None,
        "creator_profile_name": str(creator_profile_name or "").strip() or None,
        "publication_context": {
            "creator_profile_id": str(creator_profile_id or "").strip() or None,
            "creator_profile_name": str(creator_profile_name or "").strip() or None,
        },
    }
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 56,
            "stage": "packaging",
            "message": "平台文案已生成，正在渲染各平台封面和物料文件。",
            "inspection": inspection,
            "folder_path": display_folder_path,
            "material_dir": str(material_dir),
            "partial_result": {**base_result, "platforms": []},
        },
    )

    platform_materials: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    cover_group_cache: dict[str, dict[str, Any]] = {}
    cover_group_title = str(cover_brief.get("cover_title") or "") or _resolve_cover_group_title(packaging=packaging, content_profile=content_profile)
    await _prime_standard_cover_matrix_groups(
        cache=cover_group_cache,
        material_dir=material_dir,
        video_path=video_path,
        source_image_path=cover_source,
        existing_cover_path=cover_path if use_existing_cover else None,
        title=cover_group_title,
        cover_brief=cover_brief,
        use_existing_cover=use_existing_cover,
    )
    publish_platforms = [item for item in PLATFORM_ORDER if item[0] in selected_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]
    for index, (platform_key, _label, _body_label, _tag_label) in enumerate(publish_platforms, start=1):
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        reused_material = reusable_materials.get(platform_key)
        reused_from_existing = isinstance(reused_material, dict)
        if isinstance(reused_material, dict):
            material = dict(reused_material)
        else:
            platform_payload = packaging.get("platforms", {}).get(platform_key) if isinstance(packaging.get("platforms"), dict) else {}
            material = _build_platform_material(
                platform_key=platform_key,
                platform_payload=platform_payload if isinstance(platform_payload, dict) else {},
                rules=rules,
            )
        cover_output_path = material_dir / f"{index:02d}-{platform_key}-cover.jpg"
        cover_group = _resolve_platform_cover_group(platform_key=platform_key, rules=rules)
        if use_existing_cover:
            cover_generation = _render_or_reuse_existing_cover_group(
                cache=cover_group_cache,
                material_dir=material_dir,
                output_path=cover_output_path,
                existing_cover_path=cover_path,
                platform_key=platform_key,
                platform_rules=rules,
                cover_group=cover_group,
            )
        else:
            cover_generation = await _render_or_reuse_platform_cover_group(
                cache=cover_group_cache,
                material_dir=material_dir,
                output_path=cover_output_path,
                video_path=video_path,
                source_image_path=cover_source,
                existing_cover_path=None,
                title=cover_group_title,
                cover_brief=cover_brief,
                platform_key=platform_key,
                platform_rules=rules,
                cover_group=cover_group,
            )
        platform_blocks = _collect_platform_material_blocking_reasons(
            {**material, "cover_generation": cover_generation} if cover_generation else material
        )
        if cover_output_path.exists() and not platform_blocks:
            material["cover_path"] = str(cover_output_path)
        if cover_generation:
            material["cover_generation"] = cover_generation
        material["blocking_reasons"] = platform_blocks
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        blocking_reasons.extend(f"{rules['label']}：{reason}" for reason in platform_blocks)
        if not (reused_from_existing and _platform_material_files_exist(material_dir=material_dir, index=index, material=material)):
            _write_platform_material_files(material_dir=material_dir, index=index, material=material)
        platform_materials.append(material)
        platform_progress = 56 + round((index / max(1, len(publish_platforms))) * 38)
        await _emit_intelligent_copy_progress(
            progress_callback,
            {
                "progress": min(platform_progress, 96),
                "stage": "platforms",
                "message": f"已生成 {rules['label']} 物料（{index}/{len(publish_platforms)}）。",
                "inspection": inspection,
                "folder_path": display_folder_path,
                "material_dir": str(material_dir),
                "partial_result": {**base_result, "platforms": list(platform_materials)},
            },
        )

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=platform_materials,
    )
    blocking_reasons = [
        f"{material.get('label') or material.get('key') or ''}：{reason}"
        for material in platform_materials
        for reason in [str(item).strip() for item in (material.get("blocking_reasons") or []) if str(item).strip()]
    ]
    material_contract = _build_material_contract(
        platform_materials,
        requested_platforms=publish_platforms,
    )
    terminal_status = _material_contract_terminal_status(material_contract)

    result = {
        **base_result,
        "copy_brief": copy_brief,
        "platforms": platform_materials,
        "status": terminal_status,
        "publish_ready": _material_contract_publish_ready(material_contract),
        "blocking_reasons": blocking_reasons,
        "manual_handoff_ready": _material_contract_manual_handoff_ready(material_contract),
        "manual_handoff_targets": list(material_contract.get("manual_handoff_platforms") or []),
    }
    result["cover_matrix"] = _serialize_cover_matrix(cover_group_cache)
    result["material_validation"] = material_validation
    result["material_contract"] = material_contract
    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=publish_platforms,
        cover_matrix=result["cover_matrix"],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 100,
            "stage": "manual_handoff" if terminal_status == "manual_handoff" else "completed",
            "message": (
                "物料生成完成，部分平台需人工登录后继续发布。"
                if terminal_status == "manual_handoff"
                else "物料生成完成。"
            ),
            "inspection": inspection,
            "folder_path": display_folder_path,
            "material_dir": str(material_dir),
            "partial_result": result,
            "result": result,
        },
    )
    return result


def _resolve_intelligent_copy_platform_keys(platforms: list[str] | None) -> list[str]:
    available = [key for key, _label, _body_label, _tag_label in PLATFORM_ORDER if PLATFORM_PUBLISH_RULES.get(key)]
    if not platforms:
        return available
    aliases = {
        "wechat": "wechat_channels",
        "b站": "bilibili",
        "小红书": "xiaohongshu",
        "抖音": "douyin",
        "快手": "kuaishou",
        "视频号": "wechat_channels",
        "头条号": "toutiao",
    }
    selected: list[str] = []
    for platform in platforms:
        raw = str(platform or "").strip()
        normalized = aliases.get(raw.casefold(), _normalize_internal_publish_platform_key(raw))
        if normalized in available and normalized not in selected:
            selected.append(normalized)
    if not selected:
        raise ValueError("请选择至少一个可生成物料的平台。")
    return selected


def _load_existing_intelligent_copy_result(material_dir: Path) -> dict[str, Any] | None:
    json_path = material_dir / "smart-copy.json"
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _load_existing_intelligent_copy_packaging(
    *,
    material_dir: Path,
    platform_keys: list[str],
    fallback_result: dict[str, Any] | None,
) -> dict[str, Any]:
    platform_packaging_path = material_dir / "platform-packaging.json"
    if platform_packaging_path.exists():
        try:
            payload = json.loads(platform_packaging_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        normalized = _normalize_existing_platform_packaging_payload(payload, platform_keys=platform_keys)
        if normalized:
            return normalized
    return _packaging_from_existing_intelligent_copy_result(fallback_result, platform_keys=platform_keys)


def _restore_existing_intelligent_copy_content_profile(
    *,
    existing_result: dict[str, Any],
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = (
        dict(existing_result.get("content_profile_summary") or {})
        if isinstance(existing_result.get("content_profile_summary"), dict)
        else {}
    )
    copy_style = str(existing_result.get("copy_style") or "").strip() or "attention_grabbing"
    profile = _merge_intelligent_copy_profile_hints(
        content_profile=profile,
        video_path=video_path,
        subtitle_items=subtitle_items,
        copy_style=copy_style,
    )
    return _ensure_intelligent_copy_subject_identity(profile, video_path)


async def _restore_existing_intelligent_cover_generation_context(
    folder_path: str,
    *,
    platforms: list[str] | None = None,
    refresh_cover_source: bool = False,
) -> dict[str, Any]:
    inspection = inspect_intelligent_copy_folder(folder_path)
    video_path = Path(str(inspection.get("video_file") or ""))
    subtitle_path = Path(str(inspection.get("subtitle_file") or ""))
    cover_path = Path(str(inspection.get("cover_file") or "")) if inspection.get("cover_file") else None
    if not video_path.exists():
        raise ValueError("目录内未找到可用成片视频。")
    if not subtitle_path.exists():
        raise ValueError("目录内未找到可用字幕文件。")
    subtitle_items = _load_subtitle_items(subtitle_path)
    if not subtitle_items:
        raise ValueError("字幕文件已找到，但无法解析出可用字幕内容。")
    material_dir = video_path.parent / MATERIAL_DIR_NAME
    existing_result = _load_existing_intelligent_copy_result(material_dir)
    if not isinstance(existing_result, dict):
        raise ValueError("未找到可用的 smart-copy.json。")
    selected_platform_keys = _resolve_upgrade_platform_keys(existing_result, platforms=platforms)
    all_platform_keys = _resolve_upgrade_platform_keys(existing_result, platforms=None)
    packaging = _load_existing_intelligent_copy_packaging(
        material_dir=material_dir,
        platform_keys=all_platform_keys,
        fallback_result=existing_result,
    )
    content_profile = _restore_existing_intelligent_copy_content_profile(
        existing_result=existing_result,
        video_path=video_path,
        subtitle_items=subtitle_items,
    )
    copy_brief = _build_intelligent_copy_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
    )
    cover_source_manifest = (
        dict(existing_result.get("cover_source_manifest") or {})
        if isinstance(existing_result.get("cover_source_manifest"), dict)
        else {}
    )
    existing_verified_source_path = _resolve_existing_material_cover_path(
        existing_result.get("cover_source_path"),
        material_dir=material_dir,
    )
    if existing_verified_source_path is None:
        fallback_cover_source = material_dir / "00-highlight-cover-source.jpg"
        if fallback_cover_source.exists() and fallback_cover_source.is_file():
            existing_verified_source_path = fallback_cover_source.resolve()
    cover_source = None
    if not refresh_cover_source:
        cover_source = existing_verified_source_path
        if not cover_source_manifest:
            cover_source_manifest = _load_cover_source_manifest(material_dir / "00-highlight-cover-source.json")
        if not cover_source or not cover_source.exists():
            cover_source = None
        elif _cover_source_manifest_is_verified(cover_source_manifest):
            cover_source = await _restore_verified_cover_source_snapshot(
                video_path=video_path,
                source_path=cover_source,
                manifest_path=material_dir / "00-highlight-cover-source.json",
                manifest=cover_source_manifest,
            )
    if cover_source is None:
        cover_source = await _maybe_await(_prepare_intelligent_copy_cover_source(
            video_path=video_path,
            material_dir=material_dir,
            content_profile=content_profile,
            packaging=packaging,
            existing_verified_source_path=existing_verified_source_path,
            existing_verified_manifest=cover_source_manifest,
        ))
        cover_source_manifest = _load_cover_source_manifest(material_dir / "00-highlight-cover-source.json")
    cover_brief = await _maybe_await(_build_intelligent_cover_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=cover_path,
    ))
    return {
        "inspection": inspection,
        "material_dir": material_dir,
        "video_path": video_path,
        "subtitle_items": subtitle_items,
        "cover_path": cover_path,
        "existing_result": existing_result,
        "all_platform_keys": all_platform_keys,
        "selected_platform_keys": selected_platform_keys,
        "packaging": packaging,
        "content_profile": content_profile,
        "copy_brief": copy_brief,
        "cover_source": cover_source,
        "cover_source_manifest": cover_source_manifest,
        "cover_brief": cover_brief,
    }


async def rerender_existing_intelligent_copy_cover_groups(
    folder_path: str,
    *,
    platforms: list[str] | None = None,
    refresh_cover_source: bool = False,
) -> dict[str, Any]:
    context = await _restore_existing_intelligent_cover_generation_context(
        folder_path,
        platforms=platforms,
        refresh_cover_source=refresh_cover_source,
    )
    material_dir: Path = context["material_dir"]
    video_path: Path = context["video_path"]
    existing_result: dict[str, Any] = context["existing_result"]
    all_platform_keys: list[str] = list(context["all_platform_keys"] or [])
    selected_platform_keys: list[str] = list(context["selected_platform_keys"] or [])
    packaging: dict[str, Any] = context["packaging"]
    content_profile: dict[str, Any] = context["content_profile"]
    cover_source = context["cover_source"]
    cover_brief: dict[str, Any] = context["cover_brief"]
    cover_source_manifest = context["cover_source_manifest"]

    platform_items = existing_result.get("platforms") if isinstance(existing_result.get("platforms"), list) else []
    existing_item_map = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in platform_items
        if isinstance(item, dict) and _normalize_internal_publish_platform_key(item.get("key"))
    }
    cover_group_cache: dict[str, dict[str, Any]] = {}
    cover_group_title = str(cover_brief.get("cover_title") or "") or _resolve_cover_group_title(packaging=packaging, content_profile=content_profile)
    await _prime_standard_cover_matrix_groups(
        cache=cover_group_cache,
        material_dir=material_dir,
        video_path=video_path,
        source_image_path=cover_source,
        existing_cover_path=None,
        title=cover_group_title,
        cover_brief=cover_brief,
        use_existing_cover=False,
    )
    rerendered_materials: dict[str, dict[str, Any]] = {}
    publish_platforms = [item for item in PLATFORM_ORDER if item[0] in selected_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]
    for platform_key, _label, _body_label, _tag_label in publish_platforms:
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        item = existing_item_map.get(platform_key)
        if not rules or not isinstance(item, dict):
            continue
        material = _normalize_existing_platform_material(item, rules=rules)
        serial = _resolve_platform_material_serial(platform_key)
        cover_output_path = material_dir / f"{serial:02d}-{platform_key}-cover.jpg"
        cover_group = _resolve_platform_cover_group(platform_key=platform_key, rules=rules)
        cover_generation = await _render_or_reuse_platform_cover_group(
            cache=cover_group_cache,
            material_dir=material_dir,
            output_path=cover_output_path,
            video_path=video_path,
            source_image_path=cover_source,
            existing_cover_path=None,
            title=cover_group_title,
            cover_brief=cover_brief,
            platform_key=platform_key,
            platform_rules=rules,
            cover_group=cover_group,
        )
        platform_blocks = _collect_platform_material_blocking_reasons(
            {**material, "cover_generation": cover_generation} if cover_generation else material
        )
        if cover_output_path.exists() and not platform_blocks:
            material["cover_path"] = str(cover_output_path)
        if cover_generation:
            material["cover_generation"] = cover_generation
        material["blocking_reasons"] = platform_blocks
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)
        rerendered_materials[platform_key] = material

    platform_materials: list[dict[str, Any]] = []
    for platform_key, _label, _body_label, _tag_label in [item for item in PLATFORM_ORDER if item[0] in all_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]:
        if platform_key in rerendered_materials:
            platform_materials.append(rerendered_materials[platform_key])
            continue
        item = existing_item_map.get(platform_key)
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not isinstance(item, dict) or not rules:
            continue
        material = _normalize_existing_platform_material(item, rules=rules)
        _restore_platform_cover_path(material=material, material_dir=material_dir, index=_resolve_platform_material_serial(platform_key))
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        platform_materials.append(material)

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
    )
    material_contract = _build_material_contract(
        platform_materials,
        requested_platforms=all_platform_keys,
    )
    updated_result = dict(existing_result)
    updated_result["platforms"] = [_material_to_result_payload(material) for material in platform_materials]
    updated_result["cover_source_path"] = str(cover_source) if cover_source else None
    updated_result["cover_source_manifest"] = cover_source_manifest
    updated_result["cover_brief"] = cover_brief
    updated_result["cover_matrix"] = _serialize_cover_matrix(cover_group_cache)
    updated_result["material_validation"] = material_validation
    updated_result["material_contract"] = material_contract
    updated_result["status"] = _material_contract_terminal_status(material_contract)
    updated_result["publish_ready"] = _material_contract_publish_ready(material_contract)
    updated_result["blocking_reasons"] = list(material_contract.get("blocking_reasons") or [])
    updated_result["manual_handoff_ready"] = _material_contract_manual_handoff_ready(material_contract)
    updated_result["manual_handoff_targets"] = list(material_contract.get("manual_handoff_platforms") or [])

    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
        cover_matrix=updated_result["cover_matrix"],
    )
    platform_packaging_json_path = material_dir / "platform-packaging.json"
    json_path = material_dir / "smart-copy.json"
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated_result


def upgrade_existing_intelligent_copy_result(
    folder_path: str,
    *,
    platforms: list[str] | None = None,
    platform_options: dict[str, Any] | None = None,
    publication_scheme: dict[str, Any] | None = None,
    publication_scheme_path: str | None = None,
    creator_profile_id: str | None = None,
    creator_profile_name: str | None = None,
    browser: str = "chrome",
) -> dict[str, Any]:
    material_dir = _resolve_existing_material_dir(folder_path)
    existing_result = _load_existing_intelligent_copy_result(material_dir)
    if not isinstance(existing_result, dict):
        raise ValueError("未找到可升级的 smart-copy.json。")

    selected_platform_keys = _resolve_upgrade_platform_keys(existing_result, platforms=platforms)
    resolved_creator_profile_id, resolved_creator_profile_name = _resolve_upgrade_creator_context(
        existing_result=existing_result,
        creator_profile_id=creator_profile_id,
        creator_profile_name=creator_profile_name,
    )
    packaging = _load_existing_intelligent_copy_packaging(
        material_dir=material_dir,
        platform_keys=selected_platform_keys,
        fallback_result=existing_result,
    )
    resolved_platform_options = _resolve_upgrade_platform_options(
        packaging=packaging,
        existing_result=existing_result,
        material_dir=material_dir,
        platform_keys=selected_platform_keys,
        platform_options=platform_options,
        publication_scheme=publication_scheme,
        publication_scheme_path=publication_scheme_path,
        creator_profile_id=resolved_creator_profile_id,
        creator_profile_name=resolved_creator_profile_name,
        browser=browser,
    )
    platform_items = existing_result.get("platforms") if isinstance(existing_result.get("platforms"), list) else []
    existing_item_map = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in platform_items
        if isinstance(item, dict) and _normalize_internal_publish_platform_key(item.get("key"))
    }

    upgraded_materials: list[dict[str, Any]] = []
    for index, platform_key in enumerate(selected_platform_keys, start=1):
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        item = existing_item_map.get(platform_key)
        if not rules or not isinstance(item, dict):
            continue
        material = _normalize_existing_platform_material(item, rules=rules)
        _restore_platform_cover_path(material=material, material_dir=material_dir, index=index)
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        option = resolved_platform_options.get(platform_key) if isinstance(resolved_platform_options, dict) and isinstance(resolved_platform_options.get(platform_key), dict) else {}
        if isinstance(option, dict) and option:
            _apply_platform_option_metadata(material=material, option=option)
        material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        _write_platform_material_files(material_dir=material_dir, index=index, material=material)
        upgraded_materials.append(material)

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=upgraded_materials,
        requested_platforms=selected_platform_keys,
    )
    material_contract = _build_material_contract(
        upgraded_materials,
        requested_platforms=selected_platform_keys,
    )
    blocking_reasons = list(material_contract.get("blocking_reasons") or [])
    platform_packaging_json_path = material_dir / "platform-packaging.json"
    json_path = material_dir / "smart-copy.json"

    updated_result = dict(existing_result)
    updated_result["platforms"] = [
        _material_to_result_payload(material)
        for material in upgraded_materials
    ]
    terminal_status = _material_contract_terminal_status(material_contract)
    updated_result["status"] = terminal_status
    updated_result["publish_ready"] = _material_contract_publish_ready(material_contract)
    updated_result["blocking_reasons"] = blocking_reasons
    updated_result["material_validation"] = material_validation
    updated_result["material_contract"] = material_contract
    updated_result["manual_handoff_ready"] = _material_contract_manual_handoff_ready(material_contract)
    updated_result["manual_handoff_targets"] = list(material_contract.get("manual_handoff_platforms") or [])
    updated_result["platform_packaging_json_path"] = str(platform_packaging_json_path)
    updated_result["json_path"] = str(json_path)
    updated_result["creator_profile_id"] = resolved_creator_profile_id or None
    updated_result["creator_profile_name"] = resolved_creator_profile_name or None
    updated_result["publication_context"] = {
        "creator_profile_id": resolved_creator_profile_id or None,
        "creator_profile_name": resolved_creator_profile_name or None,
    }

    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=upgraded_materials,
        requested_platforms=selected_platform_keys,
        cover_matrix=dict(updated_result.get("cover_matrix") or {}),
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated_result


def _resolve_upgrade_platform_options(
    *,
    packaging: dict[str, Any],
    existing_result: dict[str, Any],
    material_dir: Path,
    platform_keys: list[str],
    platform_options: dict[str, Any] | None,
    publication_scheme: dict[str, Any] | None,
    publication_scheme_path: str | None,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
    browser: str,
) -> dict[str, Any]:
    explicit = {
        key: value
        for key, value in (platform_options or {}).items()
        if key in platform_keys and isinstance(value, dict)
    }
    if explicit:
        return explicit
    resolved_scheme = _resolve_upgrade_publication_scheme(
        publication_scheme=publication_scheme,
        publication_scheme_path=publication_scheme_path,
    )
    if resolved_scheme:
        derived = _derive_upgrade_platform_options_from_publication_scheme(
            scheme=resolved_scheme,
            platform_keys=platform_keys,
        )
        if derived:
            return derived
    profile_id, profile_name = _resolve_upgrade_creator_context(
        existing_result=existing_result,
        creator_profile_id=creator_profile_id,
        creator_profile_name=creator_profile_name,
    )
    if not profile_id:
        return {}
    targets = _build_publication_scheme_targets_from_packaging(
        packaging=packaging,
        existing_result=existing_result,
        material_dir=material_dir,
        platform_keys=platform_keys,
    )
    scheme = build_cached_publication_scheme(
        creator_profile_id=profile_id,
        creator_profile_name=profile_name,
        folder_path=str(material_dir.parent),
        browser=browser,
        targets=targets,
    )
    options = scheme.get("platform_options") if isinstance(scheme.get("platform_options"), dict) else {}
    return {
        key: value
        for key, value in options.items()
        if key in platform_keys and isinstance(value, dict)
    }


def _derive_upgrade_platform_options_from_publication_scheme(
    *,
    scheme: dict[str, Any],
    platform_keys: list[str],
) -> dict[str, Any]:
    scheme_options = scheme.get("platform_options") if isinstance(scheme.get("platform_options"), dict) else {}
    option_map = {
        _normalize_internal_publish_platform_key(key): dict(value)
        for key, value in scheme_options.items()
        if key in platform_keys and isinstance(value, dict)
    }
    item_map: dict[str, dict[str, Any]] = {}
    for item in (scheme.get("items") or []):
        if not isinstance(item, dict):
            continue
        item_platform_key = _normalize_internal_publish_platform_key(
            item.get("platform")
            or item.get("name")
            or ""
        )
        if item_platform_key in platform_keys and item_platform_key and item_platform_key not in item_map:
            item_map[item_platform_key] = item
    merged: dict[str, Any] = {}
    for platform_key in platform_keys:
        option = option_map.get(platform_key) if isinstance(option_map.get(platform_key), dict) else {}
        item = item_map.get(platform_key) if isinstance(item_map.get(platform_key), dict) else {}
        if not option and not item:
            continue
        merged_option = _merge_upgrade_platform_option_with_scheme_item(
            option=option,
            item=item,
        )
        if merged_option:
            merged[platform_key] = merged_option
    return merged


def _merge_upgrade_platform_option_with_scheme_item(
    *,
    option: dict[str, Any],
    item: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(option) if isinstance(option, dict) else {}
    for field in ("scheduled_publish_at", "visibility_or_publish_mode", "collection_name", "category"):
        if str(merged.get(field) or "").strip():
            continue
        value = str(item.get(field) or "").strip()
        if value:
            merged[field] = value
    merged_overrides = (
        dict(merged.get("platform_specific_overrides"))
        if isinstance(merged.get("platform_specific_overrides"), dict)
        else {}
    )
    item_collection_management = (
        dict(item.get("collection_management"))
        if isinstance(item.get("collection_management"), dict)
        else {}
    )
    if item_collection_management and not isinstance(merged_overrides.get("collection_management"), dict):
        merged_overrides["collection_management"] = item_collection_management
    selected_options = item.get("selected_options") if isinstance(item.get("selected_options"), dict) else {}
    item_selected_declarations = [
        str(entry).strip()
        for entry in (selected_options.get("selected_declarations") or [])
        if str(entry).strip()
    ]
    existing_selected_declarations = [
        str(entry).strip()
        for entry in (merged_overrides.get("selected_declarations") or [])
        if str(entry).strip()
    ]
    if item_selected_declarations and not existing_selected_declarations:
        merged_overrides["selected_declarations"] = item_selected_declarations
    if merged_overrides:
        merged["platform_specific_overrides"] = merged_overrides
    return merged


def _resolve_upgrade_publication_scheme(
    *,
    publication_scheme: dict[str, Any] | None,
    publication_scheme_path: str | None,
) -> dict[str, Any]:
    if isinstance(publication_scheme, dict) and publication_scheme:
        return dict(publication_scheme)
    raw_path = str(publication_scheme_path or "").strip()
    if not raw_path:
        return {}
    candidate = Path(raw_path).expanduser()
    if not candidate.exists() or not candidate.is_file():
        return {}
    try:
        payload = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, dict) else {}


def _resolve_upgrade_creator_context(
    *,
    existing_result: dict[str, Any],
    creator_profile_id: str | None,
    creator_profile_name: str | None,
) -> tuple[str, str]:
    publication_context = existing_result.get("publication_context") if isinstance(existing_result.get("publication_context"), dict) else {}
    profile_id = str(
        creator_profile_id
        or existing_result.get("creator_profile_id")
        or publication_context.get("creator_profile_id")
        or ""
    ).strip()
    profile_name = str(
        creator_profile_name
        or existing_result.get("creator_profile_name")
        or publication_context.get("creator_profile_name")
        or ""
    ).strip()
    return profile_id, profile_name


def _build_publication_scheme_targets_from_packaging(
    *,
    packaging: dict[str, Any],
    existing_result: dict[str, Any],
    material_dir: Path,
    platform_keys: list[str],
) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    raw_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    platforms = {
        _normalize_internal_publish_platform_key(key): value
        for key, value in raw_platforms.items()
        if isinstance(value, dict)
    }
    existing_by_key = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in (existing_result.get("platforms") or [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    for platform_key in platform_keys:
        payload = platforms.get(platform_key) if isinstance(platforms.get(platform_key), dict) else {}
        existing_item = existing_by_key.get(platform_key) if isinstance(existing_by_key.get(platform_key), dict) else {}
        title = str(payload.get("primary_title") or existing_item.get("primary_title") or "").strip()
        titles = [str(item).strip() for item in (payload.get("titles") or existing_item.get("titles") or []) if str(item).strip()]
        body = str(payload.get("body") or payload.get("description") or existing_item.get("body") or "").strip()
        tags = [str(item).strip().lstrip("#") for item in (payload.get("tags") or existing_item.get("tags") or []) if str(item).strip()]
        cover_path = str(existing_item.get("cover_path") or payload.get("cover_path") or "").strip()
        if not cover_path:
            cover_candidate = material_dir / f"{len(targets) + 1:02d}-{platform_key}-cover.jpg"
            if cover_candidate.exists():
                cover_path = str(cover_candidate)
        targets.append(
            {
                "platform": _normalize_external_publish_platform_key(platform_key),
                "title": title,
                "titles": titles,
                "body": body,
                "tags": tags,
                "cover_path": cover_path,
                "full_copy": str(existing_item.get("full_copy") or "").strip(),
                "copy_material": dict(existing_item.get("copy_material") or {}) if isinstance(existing_item.get("copy_material"), dict) else {},
            }
        )
    return targets


def _resolve_existing_material_dir(folder_path: str) -> Path:
    requested = str(folder_path or "").strip().strip('"')
    candidate = Path(requested).expanduser()
    if candidate.name == MATERIAL_DIR_NAME:
        if not candidate.exists():
            raise ValueError("指定的 smart-copy 目录不存在。")
        return candidate.resolve()
    return _resolve_existing_folder(requested) / MATERIAL_DIR_NAME


def _resolve_upgrade_platform_keys(payload: dict[str, Any], *, platforms: list[str] | None) -> list[str]:
    if platforms:
        return _resolve_intelligent_copy_platform_keys(platforms)
    available_keys: list[str] = []
    for item in payload.get("platforms") if isinstance(payload.get("platforms"), list) else []:
        if not isinstance(item, dict):
            continue
        key = _normalize_internal_publish_platform_key(item.get("key"))
        if key and PLATFORM_PUBLISH_RULES.get(key) and key not in available_keys:
            available_keys.append(key)
    if not available_keys:
        raise ValueError("smart-copy.json 中没有可升级的平台物料。")
    return available_keys


def _merge_non_empty_publication_metadata_fields(target: dict[str, Any], source: dict[str, Any]) -> None:
    for field in ("declaration", "category", "collection_name", "visibility_or_publish_mode", "scheduled_publish_at"):
        value = str(source.get(field) or "").strip()
        if value:
            target[field] = value


def _restore_platform_cover_path(*, material: dict[str, Any], material_dir: Path, index: int) -> None:
    existing_cover_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
    if existing_cover_path is not None:
        material["cover_path"] = str(existing_cover_path)
        return

    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else {}
    group_cover_path = ""
    for key in ("cover_group", "group_generation"):
        node = cover_generation.get(key) if isinstance(cover_generation.get(key), dict) else {}
        if key == "group_generation":
            node = node.get("cover_group") if isinstance(node.get("cover_group"), dict) else {}
        candidate = str(node.get("cover_path") or "").strip()
        if candidate:
            group_cover_path = candidate
            break
    restored_group_cover = _resolve_existing_material_cover_path(group_cover_path, material_dir=material_dir)
    if restored_group_cover is None:
        return

    platform_key = str(material.get("key") or "").strip()
    target_cover_path = material_dir / f"{index:02d}-{platform_key}-cover.jpg"
    if restored_group_cover.resolve() != target_cover_path.resolve():
        shutil.copy2(restored_group_cover, target_cover_path)
    material["cover_path"] = str(target_cover_path)


def _resolve_existing_material_cover_path(raw_path: Any, *, material_dir: Path) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    candidate = Path(raw).expanduser()
    try:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()
    except OSError:
        pass

    normalized = raw.replace("\\", "/")
    runtime_prefix = "/app/data/"
    if normalized.startswith(runtime_prefix):
        workspace_root = Path(__file__).resolve().parents[3]
        mapped = workspace_root / "data" / "runtime" / normalized[len(runtime_prefix):].lstrip("/")
        if mapped.exists() and mapped.is_file():
            return mapped.resolve()

    material_candidate = material_dir / raw
    if material_candidate.exists() and material_candidate.is_file():
        return material_candidate.resolve()
    return None


def _refresh_restored_cover_generation_status(*, material: dict[str, Any], material_dir: Path) -> None:
    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else None
    if not isinstance(cover_generation, dict):
        return
    cover_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
    if cover_path is None:
        return
    source_kind = str(cover_generation.get("source") or "").strip().lower()
    if source_kind == "cover_group_reuse":
        group_generation = cover_generation.get("group_generation") if isinstance(cover_generation.get("group_generation"), dict) else None
        group_cover_path = _resolve_cover_generation_output_path(group_generation, material_dir=material_dir) if isinstance(group_generation, dict) else None
        refreshed_group = _refresh_existing_cover_generation_node(
            generation=group_generation,
            output_path=group_cover_path or cover_path,
            material_dir=material_dir,
        )
        if refreshed_group is not None:
            cover_generation["group_generation"] = refreshed_group
            cover_generation["image_generation"] = dict(refreshed_group.get("image_generation") or {})
            cover_generation["cover_quality"] = dict(refreshed_group.get("cover_quality") or {})
            cover_generation["warnings"] = list(refreshed_group.get("warnings") or [])
            cover_generation["publish_ready"] = bool(refreshed_group.get("publish_ready"))
            cover_generation["blocking_reasons"] = list(refreshed_group.get("blocking_reasons") or [])
        return
    refreshed = _refresh_existing_cover_generation_node(
        generation=cover_generation,
        output_path=cover_path,
        material_dir=material_dir,
    )
    if refreshed is not None:
        material["cover_generation"] = refreshed


def _resolve_cover_generation_output_path(
    generation: dict[str, Any] | None,
    *,
    material_dir: Path,
) -> Path | None:
    if not isinstance(generation, dict):
        return None
    for raw_path in (
        generation.get("output_path"),
        (generation.get("cover_group") or {}).get("cover_path") if isinstance(generation.get("cover_group"), dict) else None,
        (generation.get("image_generation") or {}).get("output_path") if isinstance(generation.get("image_generation"), dict) else None,
    ):
        resolved = _resolve_existing_material_cover_path(raw_path, material_dir=material_dir)
        if resolved is not None:
            return resolved
    return None


def _refresh_existing_cover_generation_node(
    *,
    generation: dict[str, Any] | None,
    output_path: Path,
    material_dir: Path,
) -> dict[str, Any] | None:
    if not isinstance(generation, dict):
        return None
    refreshed = dict(generation)
    image_generation = refreshed.get("image_generation") if isinstance(refreshed.get("image_generation"), dict) else {}
    request_path = _resolve_existing_material_cover_path(image_generation.get("request_path"), material_dir=material_dir)
    request_payload = _read_cover_request_payload(request_path) if request_path is not None else {}
    if request_payload or image_generation:
        cover_assessment = assess_cover_publish_readiness(
            image_generation,
            request_payload,
            output_path,
        )
        image_generation = dict(image_generation)
        if request_path is not None:
            image_generation["request_path"] = str(request_path)
        image_generation["output_path"] = str(output_path)
        refreshed["image_generation"] = image_generation
        refreshed["cover_quality"] = cover_assessment
        refreshed["publish_ready"] = bool(cover_assessment.get("publish_ready"))
        refreshed["blocking_reasons"] = list(cover_assessment.get("blocking_reasons") or [])
        refreshed["warnings"] = list(cover_assessment.get("warnings") or [])
        return refreshed
    if output_path.exists():
        refreshed["publish_ready"] = not list(refreshed.get("blocking_reasons") or [])
        return refreshed
    blocking_reasons = [str(item).strip() for item in (refreshed.get("blocking_reasons") or []) if str(item).strip()]
    blocking_reasons.append(f"封面输出文件不存在：{output_path}")
    refreshed["publish_ready"] = False
    refreshed["blocking_reasons"] = sorted(set(reason for reason in blocking_reasons if reason))
    return refreshed


def _apply_platform_option_metadata(*, material: dict[str, Any], option: dict[str, Any]) -> None:
    for field in ("scheduled_publish_at", "visibility_or_publish_mode", "collection_name", "category"):
        value = str(option.get(field) or "").strip()
        if value:
            material[field] = value
    selected_declarations = [
        str(item).strip()
        for item in ((option.get("platform_specific_overrides") or {}).get("selected_declarations") or [])
        if str(item).strip()
    ] if isinstance(option.get("platform_specific_overrides"), dict) else []
    if selected_declarations:
        material["declaration"] = selected_declarations[0]
    if str(material.get("collection_name") or "").strip():
        material["collection"] = {"name": str(material.get("collection_name") or "").strip()}
    option_live_publish_preflight = option.get("live_publish_preflight") if isinstance(option.get("live_publish_preflight"), dict) else {}
    if option_live_publish_preflight:
        material["live_publish_preflight"] = dict(option_live_publish_preflight)
    option_overrides = option.get("platform_specific_overrides") if isinstance(option.get("platform_specific_overrides"), dict) else {}
    if option_overrides:
        merged_overrides = dict(material.get("platform_specific_overrides") or {}) if isinstance(material.get("platform_specific_overrides"), dict) else {}
        merged_overrides.update(option_overrides)
        material["platform_specific_overrides"] = merged_overrides


def _material_to_result_payload(material: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "key": _normalize_external_publish_platform_key(material.get("key")),
        "label": str(material.get("label") or "").strip(),
        "has_title": bool(material.get("has_title", True)),
        "title_label": str(material.get("title_label") or "标题").strip() or "标题",
        "body_label": str(material.get("body_label") or "正文").strip() or "正文",
        "tag_label": str(material.get("tag_label") or "标签").strip() or "标签",
        "constraints": dict(material.get("constraints") or {}) if isinstance(material.get("constraints"), dict) else {},
        "titles": list(material.get("titles") or []),
        "title_goals": list(material.get("title_goals") or []),
        "primary_title": str(material.get("primary_title") or "").strip(),
        "title_copy_all": str(material.get("title_copy_all") or "").strip(),
        "body": str(material.get("body") or "").strip(),
        "tags": list(material.get("tags") or []),
        "tags_copy": str(material.get("tags_copy") or "").strip(),
        "full_copy": str(material.get("full_copy") or "").strip(),
        "cover_path": str(material.get("cover_path") or "").strip() or None,
        "publish_ready": publication_packaging_entry_publish_ready(material),
        "blocking_reasons": [str(item).strip() for item in (material.get("blocking_reasons") or []) if str(item).strip()],
    }
    for field in ("declaration", "category", "collection_name", "visibility_or_publish_mode", "scheduled_publish_at"):
        value = str(material.get(field) or "").strip()
        if value:
            payload[field] = value
    if isinstance(material.get("collection"), dict) and material.get("collection"):
        payload["collection"] = dict(material.get("collection") or {})
    if isinstance(material.get("copy_material"), dict) and material.get("copy_material"):
        payload["copy_material"] = dict(material.get("copy_material") or {})
    if isinstance(material.get("cover_generation"), dict) and material.get("cover_generation"):
        payload["cover_generation"] = dict(material.get("cover_generation") or {})
    if isinstance(material.get("live_publish_preflight"), dict) and material.get("live_publish_preflight"):
        payload["live_publish_preflight"] = dict(material.get("live_publish_preflight") or {})
    if isinstance(material.get("platform_specific_overrides"), dict) and material.get("platform_specific_overrides"):
        payload["platform_specific_overrides"] = dict(material.get("platform_specific_overrides") or {})
    return payload


def _packaging_from_existing_intelligent_copy_result(
    payload: dict[str, Any] | None,
    *,
    platform_keys: list[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"platforms": {}}
    platforms: dict[str, dict[str, Any]] = {}
    for item in payload.get("platforms") if isinstance(payload.get("platforms"), list) else []:
        if not isinstance(item, dict):
            continue
        key = _normalize_internal_publish_platform_key(item.get("key"))
        if key not in platform_keys:
            continue
        platforms[key] = {
            "titles": [str(title).strip() for title in (item.get("titles") or []) if str(title).strip()],
            "primary_title": str(item.get("primary_title") or "").strip(),
            "description": str(item.get("body") or "").strip(),
            "body": str(item.get("body") or "").strip(),
            "tags": [str(tag).strip().lstrip("#") for tag in (item.get("tags") or []) if str(tag).strip()],
            "cover_path": str(item.get("cover_path") or "").strip(),
            "copy_material": dict(item.get("copy_material") or {}) if isinstance(item.get("copy_material"), dict) else {},
            "publish_ready": publication_packaging_entry_publish_ready(item),
            "blocking_reasons": [str(reason).strip() for reason in (item.get("blocking_reasons") or []) if str(reason).strip()],
        }
        _merge_non_empty_publication_metadata_fields(platforms[key], item)
    return {
        "highlights": dict(payload.get("highlights") or {}),
        "fact_sheet": dict(payload.get("fact_sheet") or {}),
        "title_audit": dict(payload.get("title_audit") or {}),
        "generation_repair_trace": list(payload.get("generation_repair_trace") or []),
        "cover_matrix": dict(payload.get("cover_matrix") or {}) if isinstance(payload.get("cover_matrix"), dict) else {},
        "material_contract": dict(payload.get("material_contract") or {}) if isinstance(payload.get("material_contract"), dict) else {},
        "material_validation": dict(payload.get("material_validation") or {}) if isinstance(payload.get("material_validation"), dict) else {},
        "platforms": platforms,
    }


def _normalize_existing_platform_packaging_payload(
    payload: dict[str, Any] | None,
    *,
    platform_keys: list[str],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    raw_platforms = payload.get("platforms")
    platforms: dict[str, dict[str, Any]] = {}
    if isinstance(raw_platforms, dict):
        for key, value in raw_platforms.items():
            normalized_key = _normalize_internal_publish_platform_key(key)
            if normalized_key not in platform_keys or not isinstance(value, dict):
                continue
            platforms[normalized_key] = dict(value)
    elif isinstance(raw_platforms, list):
        return _packaging_from_existing_intelligent_copy_result(payload, platform_keys=platform_keys)
    if not platforms:
        return {}
    return {
        "highlights": dict(payload.get("highlights") or {}),
        "fact_sheet": dict(payload.get("fact_sheet") or {}),
        "title_audit": dict(payload.get("title_audit") or {}),
        "generation_repair_trace": list(payload.get("generation_repair_trace") or []),
        "cover_matrix": dict(payload.get("cover_matrix") or {}) if isinstance(payload.get("cover_matrix"), dict) else {},
        "material_contract": dict(payload.get("material_contract") or {}) if isinstance(payload.get("material_contract"), dict) else {},
        "material_validation": dict(payload.get("material_validation") or {}) if isinstance(payload.get("material_validation"), dict) else {},
        "platforms": platforms,
    }


def _merge_resume_packaging(
    *,
    existing_packaging: dict[str, Any] | None,
    generated_packaging: dict[str, Any] | None,
    platform_keys: list[str],
) -> dict[str, Any]:
    merged: dict[str, Any] = {
        "highlights": {},
        "fact_sheet": {},
        "title_audit": {},
        "generation_repair_trace": [],
        "cover_matrix": {},
        "platforms": {},
    }
    for source in (existing_packaging, generated_packaging):
        if not isinstance(source, dict):
            continue
        for key in ("highlights", "fact_sheet", "title_audit"):
            value = source.get(key)
            if isinstance(value, dict) and value:
                merged[key] = dict(value)
        trace = source.get("generation_repair_trace")
        if isinstance(trace, list) and trace:
            merged["generation_repair_trace"] = list(trace)
        cover_matrix = source.get("cover_matrix")
        if isinstance(cover_matrix, dict) and cover_matrix:
            merged["cover_matrix"] = dict(cover_matrix)
    merged_platforms: dict[str, dict[str, Any]] = {}
    for source in (existing_packaging, generated_packaging):
        if not isinstance(source, dict):
            continue
        source_platforms = source.get("platforms") if isinstance(source.get("platforms"), dict) else {}
        for key in platform_keys:
            payload = source_platforms.get(key)
            if isinstance(payload, dict):
                merged_platforms[key] = dict(payload)
    merged["platforms"] = merged_platforms
    return merged


def _collect_reusable_platform_materials(
    payload: dict[str, Any] | None,
    *,
    platform_keys: list[str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(payload, dict):
        return {}
    reusable: dict[str, dict[str, Any]] = {}
    for item in payload.get("platforms") if isinstance(payload.get("platforms"), list) else []:
        if not isinstance(item, dict):
            continue
        key = _normalize_internal_publish_platform_key(item.get("key"))
        if key not in platform_keys:
            continue
        rules = PLATFORM_PUBLISH_RULES.get(key)
        if not rules:
            continue
        material = _normalize_existing_platform_material(item, rules=rules)
        if not _validate_platform_material_ready(material):
            reusable[key] = material
    return reusable


def _normalize_existing_platform_material(item: dict[str, Any], *, rules: dict[str, Any]) -> dict[str, Any]:
    titles = [str(title).strip() for title in (item.get("titles") or []) if str(title).strip()]
    tags = [str(tag).strip() for tag in (item.get("tags") or []) if str(tag).strip()]
    payload = {
        "key": _normalize_internal_publish_platform_key(item.get("key")),
        "label": str(item.get("label") or rules.get("label") or "").strip(),
        "has_title": bool(item.get("has_title", rules.get("has_title", True))),
        "title_label": str(item.get("title_label") or "标题").strip() or "标题",
        "body_label": str(item.get("body_label") or rules.get("body_label") or "正文").strip(),
        "tag_label": str(item.get("tag_label") or rules.get("tag_label") or "标签").strip(),
        "constraints": {
            "title_limit": int(rules.get("title_limit") or 0),
            "body_limit": int(rules.get("body_limit") or 0),
            "tag_limit": int(rules.get("tag_limit") or 0),
            "tag_style": str(rules.get("tag_style") or "").strip(),
            "cover_size": {
                "width": int(rules["cover_size"][0]),
                "height": int(rules["cover_size"][1]),
            },
            "rule_note": str(rules.get("rule_note") or "").strip(),
        },
        "titles": titles,
        "title_goals": list(item.get("title_goals") or []),
        "primary_title": str(item.get("primary_title") or (titles[0] if titles else "")).strip(),
        "title_copy_all": str(item.get("title_copy_all") or "").strip(),
        "body": str(item.get("body") or "").strip(),
        "tags": tags,
        "tags_copy": str(item.get("tags_copy") or "").strip(),
        "full_copy": str(item.get("full_copy") or "").strip(),
        "cover_path": str(item.get("cover_path") or "").strip() or None,
        "copy_material": dict(item.get("copy_material") or {}) if isinstance(item.get("copy_material"), dict) else {},
        "cover_generation": dict(item.get("cover_generation") or {}) if isinstance(item.get("cover_generation"), dict) else None,
        "publish_ready": publication_packaging_entry_publish_ready(item),
        "blocking_reasons": [str(reason).strip() for reason in (item.get("blocking_reasons") or []) if str(reason).strip()],
    }
    _merge_non_empty_publication_metadata_fields(payload, item)
    return payload


def _filter_intelligent_copy_packaging(packaging: dict[str, Any], platform_keys: list[str]) -> dict[str, Any]:
    platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    return {
        **packaging,
        "platforms": {
            key: platforms.get(key, {})
            for key in platform_keys
            if PLATFORM_PUBLISH_RULES.get(key)
        },
    }


def _build_intelligent_copy_fast_profile(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    copy_style: str,
) -> dict[str, Any]:
    transcript_text = " ".join(
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items[:100]
    ).strip()
    normalized = " ".join(part for part in (video_path.stem, transcript_text) if part).strip()
    if not _should_use_intelligent_copy_fast_path(normalized):
        return {}
    return _merge_intelligent_copy_profile_hints(
        content_profile={},
        video_path=video_path,
        subtitle_items=subtitle_items,
        copy_style=copy_style,
    )


def _build_platform_material(*, platform_key: str, platform_payload: dict[str, Any], rules: dict[str, Any]) -> dict[str, Any]:
    titles = [_trim_to_display_units(str(item).strip(), int(rules["title_limit"])) for item in (platform_payload.get("titles") or []) if str(item).strip()]
    titles = [item for item in titles if item]
    if not rules.get("has_title", True):
        titles = []
    titles = titles[:TITLE_OPTION_LIMIT]
    title_goals = _build_title_goals(titles, platform_key=platform_key)
    body = _trim_to_display_units(str(platform_payload.get("description") or "").strip(), int(rules["body_limit"]))
    tags = [str(item).strip().lstrip("#") for item in (platform_payload.get("tags") or []) if str(item).strip()]
    tags = _dedupe(tags)[: int(rules["tag_limit"])]
    tags_copy = _format_tag_copy(tags, style=str(rules["tag_style"]))
    full_copy_parts = []
    if titles:
        full_copy_parts.append(titles[0])
    if body:
        full_copy_parts.append(body)
    if tags_copy:
        full_copy_parts.append(tags_copy)
    collection = platform_payload.get("collection") if isinstance(platform_payload.get("collection"), dict) else None
    collection_name = str(platform_payload.get("collection_name") or "").strip()
    declaration = str(platform_payload.get("declaration") or "").strip()
    category = str(platform_payload.get("category") or "").strip()
    visibility_or_publish_mode = str(platform_payload.get("visibility_or_publish_mode") or "").strip()
    scheduled_publish_at = str(platform_payload.get("scheduled_publish_at") or "").strip()
    copy_material = platform_payload.get("copy_material") if isinstance(platform_payload.get("copy_material"), dict) else {}
    platform_specific_overrides = (
        dict(platform_payload.get("platform_specific_overrides"))
        if isinstance(platform_payload.get("platform_specific_overrides"), dict)
        else {}
    )
    material = {
        "key": platform_key,
        "label": str(rules["label"]),
        "has_title": bool(rules.get("has_title", True)),
        "title_label": "标题",
        "body_label": str(rules["body_label"]),
        "tag_label": str(rules["tag_label"]),
        "constraints": {
            "title_limit": int(rules["title_limit"]),
            "body_limit": int(rules["body_limit"]),
            "tag_limit": int(rules["tag_limit"]),
            "tag_style": str(rules["tag_style"]),
            "cover_size": {"width": int(rules["cover_size"][0]), "height": int(rules["cover_size"][1])},
            "rule_note": str(rules["rule_note"]),
        },
        "titles": titles,
        "title_goals": title_goals,
        "primary_title": titles[0] if titles else "",
        "title_copy_all": "\n".join(f"{index}. {title}" for index, title in enumerate(titles, start=1)),
        "body": body,
        "tags": tags,
        "tags_copy": tags_copy,
        "full_copy": "\n\n".join(part for part in full_copy_parts if part),
        "copy_material": copy_material,
    }
    if isinstance(collection, dict) and collection:
        material["collection"] = collection
    if collection_name:
        material["collection_name"] = collection_name
    if declaration:
        material["declaration"] = declaration
    if category:
        material["category"] = category
    if visibility_or_publish_mode:
        material["visibility_or_publish_mode"] = visibility_or_publish_mode
    if scheduled_publish_at:
        material["scheduled_publish_at"] = scheduled_publish_at
    if platform_specific_overrides:
        material["platform_specific_overrides"] = platform_specific_overrides
    return material


def _resolve_platform_cover_title(
    *,
    material: dict[str, Any],
    packaging: dict[str, Any],
    content_profile: dict[str, Any],
) -> str:
    highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
    cover_title = content_profile.get("cover_title") if isinstance(content_profile.get("cover_title"), dict) else {}
    cover_title_text = " ".join(
        str(cover_title.get(key) or "").strip()
        for key in ("top", "main", "bottom")
        if str(cover_title.get(key) or "").strip()
    ).strip()
    for candidate in (material.get("primary_title"),):
        normalized = _normalize_cover_title_candidate(candidate)
        if normalized:
            return normalized
    structured_title = _compose_compact_cover_title(
        highlights=highlights,
        content_profile=content_profile,
        cover_title_text=cover_title_text,
    )
    if structured_title:
        return structured_title
    candidates = (
        cover_title_text,
        highlights.get("strongest_selling_point"),
        highlights.get("product"),
    )
    for candidate in candidates:
        normalized = _normalize_cover_title_candidate(candidate)
        if normalized:
            return normalized
    return ""


def _resolve_cover_group_title(*, packaging: dict[str, Any], content_profile: dict[str, Any]) -> str:
    return _resolve_platform_cover_title(
        material={"primary_title": ""},
        packaging=packaging,
        content_profile=content_profile,
    )


async def _build_intelligent_cover_brief(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
    packaging: dict[str, Any],
    cover_source_manifest: dict[str, Any] | None = None,
    existing_cover_path: Path | None = None,
) -> dict[str, Any]:
    fallback = _build_fallback_cover_brief(
        packaging=packaging,
        content_profile=content_profile,
        copy_brief=copy_brief,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=existing_cover_path,
    )
    context = {
        "source_name": video_path.name,
        "content_profile": _content_profile_summary(content_profile),
        "copy_brief": copy_brief,
        "highlights": dict(packaging.get("highlights") or {}),
        "platform_titles": _collect_platform_title_samples(packaging),
        "transcript_excerpt": build_transcript_excerpt_for_cover(subtitle_items),
        "cover_source_manifest": dict(cover_source_manifest or {}),
    }
    prompt = (
        "你是短视频封面策划。请根据视频内容自己总结、提炼封面需求，不要套固定模板。"
        "你要判断视频类型，例如开箱、评测、对比、教程、种草、展示、实测等，"
        "再为图片模型准备简洁明确的封面 brief。\n"
        "封面标题要求：必须短、强识别、适合图片模型直接渲染；不要使用完整文案句子；不要超过 14 个汉字左右。"
        "如果能识别明确品牌、型号或商品名，cover_title 必须保留核心品牌/商品身份，不能只写材质、品类或卖点。"
        "background_strategy 用来决定生成阶段怎么处理背景，只能是 preserve_reference_background、enhance_reference_background、replace_background_if_needed 三选一。"
        "规则：如果参考图背景已经是刻意布置好的展示环境，优先 preserve 或 enhance；如果背景普通、杂乱、对点击率帮助不大，再用 replace_background_if_needed。"
        "critical_detail_notes 用来补充关键细节硬约束，适合描述容易被模型误读的结构语义，例如“镜面反光是实心金属不是开孔”。"
        "它应该是一个字符串数组，每条都短、明确、只描述关键细节，不要写成长段解释。"
        "不要走固定格式。你可以参考品牌/型号、商品类型、开箱/评测/对比/教程/超好玩/强烈推荐/夯爆了等信息，"
        "但必须根据真实内容自行取舍、总结和改写，不能机械拼接。"
        "EDC/工具内容要合规，不要危险导向，不要编参数。\n"
        "只输出 JSON："
        '{"cover_title":"","video_type":"","product_identity":"","selling_angle":"","visual_brief":"","background_strategy":"","critical_detail_notes":[],"avoid":""}'
        f"\n视频上下文：{json.dumps(context, ensure_ascii=False)}"
    )
    try:
        with llm_task_route("copy", search_enabled=False):
            provider = get_reasoning_provider()
            response = await asyncio.wait_for(
                provider.complete(
                    [
                        Message(role="system", content="你只输出合法 JSON，负责为图片模型提炼封面 brief。"),
                        Message(role="user", content=prompt),
                    ],
                    temperature=0.35,
                    max_tokens=900,
                    json_mode=True,
                ),
                timeout=45,
            )
        raw = response.as_json()
        payload = raw if isinstance(raw, dict) else json.loads(extract_json_text(str(raw)))
    except Exception:
        payload = {}
    return _normalize_cover_brief_payload(payload, fallback=fallback)


def _build_fallback_cover_brief(
    *,
    packaging: dict[str, Any],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
    cover_source_manifest: dict[str, Any] | None = None,
    existing_cover_path: Path | None = None,
) -> dict[str, Any]:
    title = _resolve_cover_group_title(packaging=packaging, content_profile=content_profile)
    highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
    raw_product_identity = str(
        content_profile.get("subject_model")
        or highlights.get("product")
        or copy_brief.get("topic_subject")
        or ""
    ).strip()
    product_identity = _ensure_cover_identity_keeps_compare_context(
        raw_product_identity,
        title=title,
        packaging=packaging,
        content_profile=content_profile,
        copy_brief=copy_brief,
    )
    critical_detail_notes = _default_cover_critical_detail_notes(
        packaging=packaging,
        content_profile=content_profile,
        copy_brief=copy_brief,
    )
    return {
        "cover_title": title,
        "video_type": str(highlights.get("video_type") or copy_brief.get("intent") or "").strip(),
        "product_identity": product_identity,
        "selling_angle": str(highlights.get("strongest_selling_point") or highlights.get("title_hook") or "").strip(),
        "visual_brief": "突出真实主体、产品质感和开箱/展示高光，封面标题保持大而清晰。",
        "background_strategy": _resolve_cover_background_strategy(
            cover_source_manifest=cover_source_manifest,
            existing_cover_path=existing_cover_path,
        ),
        "critical_detail_notes": critical_detail_notes,
        "avoid": "不要长句、参数、危险导向、乱码、额外文字。",
        "strategy_source": "fallback",
    }


def _normalize_cover_brief_payload(payload: dict[str, Any], *, fallback: dict[str, Any]) -> dict[str, Any]:
    product_identity = _trim_to_display_units(
        str(payload.get("product_identity") or fallback.get("product_identity") or "").strip(),
        24,
    )
    title = _normalize_llm_cover_title(payload.get("cover_title"))
    source = "llm" if title and payload else str(fallback.get("strategy_source") or "fallback")
    if not title:
        title = str(fallback.get("cover_title") or "").strip()
    title = _ensure_cover_title_keeps_identity(title, product_identity=product_identity)
    normalized = {
        "cover_title": title,
        "video_type": _trim_to_display_units(str(payload.get("video_type") or fallback.get("video_type") or "").strip(), 18),
        "product_identity": product_identity,
        "selling_angle": _trim_to_display_units(
            str(payload.get("selling_angle") or fallback.get("selling_angle") or "").strip(),
            24,
        ),
        "visual_brief": str(payload.get("visual_brief") or fallback.get("visual_brief") or "").strip()[:160],
        "background_strategy": _normalize_cover_background_strategy(
            payload.get("background_strategy") or fallback.get("background_strategy") or ""
        ),
        "critical_detail_notes": _normalize_cover_critical_detail_notes(
            payload.get("critical_detail_notes")
            if payload.get("critical_detail_notes") is not None
            else fallback.get("critical_detail_notes")
        ),
        "avoid": str(payload.get("avoid") or fallback.get("avoid") or "").strip()[:120],
        "strategy_source": source,
    }
    return normalized


def _ensure_cover_identity_keeps_compare_context(
    identity: str,
    *,
    title: str,
    packaging: dict[str, Any],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
) -> str:
    base = re.sub(r"\s+", " ", str(identity or "").strip()).strip()
    if not base:
        return ""
    context_blob = " ".join(
        part
        for part in (
            title,
            packaging.get("highlights", {}).get("title_hook") if isinstance(packaging.get("highlights"), dict) else "",
            packaging.get("highlights", {}).get("strongest_selling_point") if isinstance(packaging.get("highlights"), dict) else "",
            content_profile.get("summary"),
            content_profile.get("video_theme"),
            copy_brief.get("topic_subject"),
        )
        if str(part or "").strip()
    )
    if _cover_title_line_contains_compare_tail(context_blob) and not _cover_title_line_contains_compare_tail(base):
        return f"{base} {_resolve_compare_tail(context_blob)}".strip()
    return base


def _normalize_cover_background_strategy(value: Any) -> str:
    normalized = str(value or "").strip()
    if normalized in {
        "preserve_reference_background",
        "enhance_reference_background",
        "replace_background_if_needed",
    }:
        return normalized
    return "replace_background_if_needed"


def _normalize_cover_critical_detail_notes(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n;；]+", value)
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        return []
    notes: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = re.sub(r"\s+", " ", str(item or "").strip())
        if not text:
            continue
        text = text[:72]
        if text in seen:
            continue
        seen.add(text)
        notes.append(text)
    return notes


def _default_cover_critical_detail_notes(
    *,
    packaging: dict[str, Any],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
) -> list[str]:
    highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
    text = " ".join(
        part
        for part in (
            str(highlights.get("product") or "").strip(),
            str(highlights.get("video_type") or "").strip(),
            str(highlights.get("strongest_selling_point") or "").strip(),
            str(copy_brief.get("topic_subject") or "").strip(),
            str(copy_brief.get("intent") or "").strip(),
            str(content_profile.get("subject_model") or "").strip(),
            str(content_profile.get("subject_type") or "").strip(),
            str(content_profile.get("video_theme") or "").strip(),
            str(content_profile.get("summary") or "").strip(),
        )
        if part
    )
    lowered = text.lower()
    is_edc_blade = any(token in text for token in ("刀", "刀具", "折刀", "直跳", "MAXACE", "美杜莎")) or "edc" in lowered
    is_compare = any(token in text for token in ("双版", "双档", "两款", "顶配", "次顶配", "对比", "差别", "怎么选")) or "comparison" in lowered
    notes: list[str] = []
    if is_edc_blade:
        notes.append("保留原始刀型、开孔、转轴、柄部纹理和主要部件位置，不改款不变形。")
        notes.append("刀身镜面反光区域是实心金属高光，不是开孔、镂空、雕花或缺口。")
        notes.append("不要给刀身添加不存在的浮雕、动物纹样、刻字或装饰图案。")
    if is_edc_blade and is_compare:
        notes.insert(0, "如果参考图里有两把刀，必须保持两把都同框清晰完整，不能丢成一把。")
        notes.append("版本对比内容要保留双主体关系，让差异一眼可见，不要把第二把弱化成背景。")
    return _normalize_cover_critical_detail_notes(notes)


def _resolve_cover_background_strategy(
    *,
    cover_source_manifest: dict[str, Any] | None,
    existing_cover_path: Path | None,
) -> str:
    if existing_cover_path is not None and existing_cover_path.exists():
        return "preserve_reference_background"
    manifest = cover_source_manifest if isinstance(cover_source_manifest, dict) else {}
    source_name = str(manifest.get("source") or "").strip().lower()
    if source_name == "existing_cover_reference":
        return "preserve_reference_background"
    return "replace_background_if_needed"


def _background_strategy_prompt(strategy: str) -> str:
    normalized = _normalize_cover_background_strategy(strategy)
    if normalized == "preserve_reference_background":
        return "背景策略：优先保留参考图里已有的背景布置、场景关系和展示环境，只做质感、光影和特效增强，不要把背景整体换掉。"
    if normalized == "enhance_reference_background":
        return "背景策略：保留参考图背景的核心布置和场景关系，但允许做更强的电影化增强，让背景更酷、更有能量感。"
    return "背景策略：背景不是硬约束；如果参考图背景已经布置完整且服务主体，可以保留并增强；如果背景普通、杂乱或不利于点击率，可以替换成更酷的电影化背景。"


def _load_cover_source_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_llm_cover_title(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).strip(" -|，,。.!！?？")
    if not normalized:
        return ""
    if _display_units(normalized) > 28:
        fragments = [fragment.strip(" -|，,。.!！?？") for fragment in re.split(r"[，,。.!！?？；;]", normalized) if fragment.strip()]
        for fragment in fragments:
            if 4 <= _display_units(fragment) <= 28:
                return fragment
        return ""
    return normalized


def _ensure_cover_title_keeps_identity(title: str, *, product_identity: str) -> str:
    normalized_title = re.sub(r"\s+", " ", str(title or "").strip()).strip(" -|，,。.!！?？")
    anchor = _extract_cover_identity_anchor(product_identity)
    if not normalized_title or not anchor:
        return normalized_title
    compact_title = re.sub(r"\s+", "", normalized_title).upper()
    compact_anchor = re.sub(r"\s+", "", anchor).upper()
    if compact_anchor and compact_anchor in compact_title:
        return normalized_title
    anchor_chinese = re.sub(r"[A-Za-z0-9]+", "", anchor)
    if len(anchor_chinese) >= 2 and re.sub(r"\s+", "", anchor_chinese) in re.sub(r"\s+", "", normalized_title):
        return normalized_title
    if re.search(r"[A-Za-z0-9]{2,}", anchor) and re.search(r"[A-Za-z0-9]{2,}", normalized_title):
        return normalized_title
    repaired = f"{anchor} {normalized_title}".strip()
    if _display_units(repaired) <= 32:
        return repaired
    fragments = [fragment.strip(" -|，,。.!！?？") for fragment in re.split(r"[，,。.!！?？；;]", normalized_title) if fragment.strip()]
    for fragment in fragments:
        candidate = f"{anchor} {fragment}".strip()
        if _display_units(candidate) <= 32:
            return candidate
    return _trim_to_display_units(repaired, 32)


def _extract_cover_identity_anchor(product_identity: str) -> str:
    compact = re.sub(r"\s+", "", str(product_identity or "").strip())
    if not compact:
        return ""
    latin_match = re.search(r"[A-Za-z0-9]{2,}[\u4e00-\u9fff]{0,2}", compact)
    if latin_match:
        return latin_match.group(0)
    for suffix in ("锆合金", "音叉", "推牌", "版本", "开箱", "评测", "体验", "测评"):
        index = compact.find(suffix)
        if index > 1:
            return _trim_to_display_units(compact[:index], 8)
    return _trim_to_display_units(compact, 8)


def _collect_platform_title_samples(packaging: dict[str, Any]) -> dict[str, list[str]]:
    platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    samples: dict[str, list[str]] = {}
    for key, value in platforms.items():
        if not isinstance(value, dict):
            continue
        titles = [str(item).strip() for item in (value.get("titles") or []) if str(item).strip()]
        if titles:
            samples[str(key)] = titles[:3]
    return samples


def build_transcript_excerpt_for_cover(subtitle_items: list[dict[str, Any]], *, max_chars: int = 900) -> str:
    lines: list[str] = []
    total = 0
    for item in subtitle_items[:80]:
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        projected = total + len(text) + (1 if lines else 0)
        if projected > max_chars:
            break
        lines.append(text)
        total = projected
    return "\n".join(lines)


def _compose_compact_cover_title(
    *,
    highlights: dict[str, Any],
    content_profile: dict[str, Any],
    cover_title_text: str,
) -> str:
    subject_model = str(content_profile.get("subject_model") or "").strip()
    subject_brand = str(content_profile.get("subject_brand") or "").strip()
    subject_type = str(content_profile.get("subject_type") or "").strip()
    text_pool = " ".join(
        str(value or "").strip()
        for value in (
            subject_brand,
            subject_model,
            subject_type,
            highlights.get("product"),
            highlights.get("video_type"),
            highlights.get("strongest_selling_point"),
            highlights.get("title_hook"),
            cover_title_text,
            content_profile.get("video_theme"),
            content_profile.get("summary"),
        )
        if str(value or "").strip()
    )
    if not text_pool:
        return ""
    parts = _cover_product_title_parts(
        subject_brand=subject_brand,
        subject_model=subject_model,
        subject_type=subject_type,
        text_pool=text_pool,
    )
    keyword = _resolve_cover_action_keyword(text_pool)
    if keyword:
        parts.append(keyword)
    title = " ".join(_dedupe(parts))
    return _normalize_cover_title_candidate(title)


def _cover_product_title_parts(
    *,
    subject_brand: str,
    subject_model: str,
    subject_type: str,
    text_pool: str,
) -> list[str]:
    parts: list[str] = []
    normalized_pool = text_pool.upper()
    compact_model = re.sub(r"\s+", "", subject_model)
    compact_brand = re.sub(r"\s+", "", subject_brand)
    if compact_brand and not _is_generic_intelligent_copy_subject_identity(compact_brand):
        parts.append(compact_brand)
    elif "MOT" in normalized_pool:
        parts.append("MOT风灵" if "风灵" in text_pool else "MOT")
    elif "OLIGHT" in normalized_pool:
        parts.append("OLIGHT")
    elif "琢匠" in text_pool:
        parts.append("琢匠")
    elif "FAS" in normalized_pool:
        parts.append("FAS")

    model_tail = compact_model
    for prefix in ("MOT", "风灵", "MOT风灵", "OLIGHT", "琢匠", "FAS"):
        model_tail = model_tail.replace(prefix, "")
    model_tail = re.sub(r"(版本|版)$", "", model_tail)
    if model_tail:
        if "锆合金" in model_tail and "推牌" in model_tail:
            parts.append("锆合金推牌")
        else:
            parts.append(_trim_to_display_units(model_tail, 10))
    elif "锆合金" in text_pool and "推牌" in text_pool:
        parts.append("锆合金推牌")
    elif "音叉推牌" in text_pool:
        parts.append("音叉推牌")
    elif "推牌" in text_pool:
        parts.append("推牌")
    elif subject_type:
        parts.append(_trim_to_display_units(subject_type, 8))

    return [part for part in parts if part]


def _resolve_cover_action_keyword(text_pool: str) -> str:
    text = str(text_pool or "")
    normalized = text.lower()
    if re.search(r"对比|差异|区别|怎么选|选哪|取舍|comparison", text, re.I):
        return "对比"
    if re.search(r"教程|怎么用|使用方法|教学|tutorial", text, re.I):
        return "教程"
    if re.search(r"开箱|到手|上手|unbox|unboxing", text, re.I):
        return "开箱"
    if re.search(r"评测|测评|实测|值不值|体验|review|test", text, re.I):
        return "评测"
    if re.search(r"好玩|解压|把玩|玩具|toy|fun", normalized, re.I):
        return "超好玩"
    return "开箱"


def _normalize_cover_title_candidate(value: Any) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip()).strip(" -|，,。.!！?？")
    if not normalized:
        return ""
    fragments = [fragment.strip(" -|，,。.!！?？") for fragment in re.split(r"[，,。.!！?？；;]", normalized) if fragment.strip()]
    product_pattern = re.compile(r"MOT|风灵|锆合金|音叉|推牌|EDC|OLIGHT|司令官|琢匠|貔貅|FAS|刀帕|开箱|评测|对比|教程|超好玩|强烈推荐|夯爆", re.I)
    for fragment in fragments:
        if product_pattern.search(fragment) and _display_units(fragment) <= 22:
            return fragment
    if _display_units(normalized) > 18 and not product_pattern.search(normalized):
        return ""
    return _trim_to_display_units(normalized, 22)


def _resolve_platform_cover_group(*, platform_key: str, rules: dict[str, Any]) -> dict[str, Any]:
    width, height = int(rules["cover_size"][0]), int(rules["cover_size"][1])
    ratio = width / max(1, height)
    if abs(ratio - (16 / 9)) < 0.06:
        return dict(_cover_matrix_group_profile("landscape_16_9"))
    if abs(ratio - (4 / 3)) < 0.06:
        return dict(_cover_matrix_group_profile("landscape_4_3"))
    if abs(ratio - (3 / 4)) < 0.06:
        return dict(_cover_matrix_group_profile("portrait_3_4"))
    return dict(_cover_matrix_group_profile("portrait_9_16"))


def _cover_matrix_group_profile(group_key: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "landscape_16_9": {
            "key": "landscape_16_9",
            "label": "16:9 横版母版",
            "representative_platform": "bilibili",
            "cover_size": (1600, 900),
            "members": ["bilibili", "toutiao", "youtube", "x"],
            "visual_instruction": "16:9 横版母版，兼顾缩略图点击率与主体细节，主体完整、标题冲击强，中央安全区适合完整主副标题与吸睛文案。",
        },
        "landscape_4_3": {
            "key": "landscape_4_3",
            "label": "4:3 横版母版",
            "representative_platform": "douyin",
            "cover_size": (1440, 1080),
            "members": [],
            "visual_instruction": "4:3 横版母版，适合横向信息流与封面上传槽位，主体完整同框，左右留出戏剧化背景，中上区域适合强主标题和对比副标题。",
        },
        "portrait_3_4": {
            "key": "portrait_3_4",
            "label": "3:4 竖版母版",
            "representative_platform": "xiaohongshu",
            "cover_size": (1080, 1440),
            "members": ["xiaohongshu"],
            "visual_instruction": "3:4 竖版母版，强调质感与双主体完整展示，上半区适合品牌与主标题，下半区保留产品和手持关系，不要挤压主体。",
        },
        "portrait_9_16": {
            "key": "portrait_9_16",
            "label": "9:16 竖版母版",
            "representative_platform": "douyin",
            "cover_size": (1080, 1920),
            "members": ["douyin", "kuaishou", "wechat_channels"],
            "visual_instruction": "9:16 竖版母版，移动端第一眼冲击强，主体占比高但必须完整，上中部适合大字主标题和副标题，避免裁掉关键对比主体。",
        },
    }
    return dict(profiles.get(str(group_key or "").strip()) or profiles["landscape_16_9"])


def _resolve_standard_cover_matrix_groups() -> list[dict[str, Any]]:
    groups = [
        _cover_matrix_group_profile("landscape_16_9"),
        _cover_matrix_group_profile("landscape_4_3"),
        _cover_matrix_group_profile("portrait_3_4"),
        _cover_matrix_group_profile("portrait_9_16"),
    ]
    groups[-1]["members"] = ["kuaishou", "wechat_channels"]
    return groups


async def _prime_standard_cover_matrix_groups(
    *,
    cache: dict[str, dict[str, Any]],
    material_dir: Path,
    video_path: Path,
    source_image_path: Path | None,
    existing_cover_path: Path | None,
    title: str,
    cover_brief: dict[str, Any] | None,
    use_existing_cover: bool,
) -> dict[str, dict[str, Any]]:
    for group in _resolve_standard_cover_matrix_groups():
        group_key = str(group.get("key") or "").strip()
        if not group_key or cache.get(group_key) is not None:
            continue
        representative_platform = str(group.get("representative_platform") or "bilibili").strip()
        representative_rules = dict(PLATFORM_PUBLISH_RULES.get(representative_platform) or PLATFORM_PUBLISH_RULES["bilibili"])
        representative_rules["label"] = str(group.get("label") or representative_rules.get("label") or representative_platform)
        representative_rules["cover_size"] = tuple(group.get("cover_size") or representative_rules["cover_size"])
        representative_rules["visual_instruction"] = str(
            group.get("visual_instruction") or representative_rules.get("visual_instruction") or ""
        ).strip()
        group_output_path = material_dir / f"00-cover-{group_key}.jpg"
        if use_existing_cover:
            blocking_reasons: list[str] = []
            width, height = tuple(group.get("cover_size") or representative_rules["cover_size"])
            if existing_cover_path is not None and existing_cover_path.exists():
                _fit_image_to_canvas(
                    source_path=existing_cover_path,
                    output_path=group_output_path,
                    width=int(width),
                    height=int(height),
                    fit_mode="cover",
                )
            else:
                blocking_reasons.append("已选择使用已有封面，但目录内未找到可用封面")
            group_metadata = {
                "source": "existing_cover",
                "platform": representative_platform,
                "target_size": {"width": int(width), "height": int(height)},
                "publish_ready": group_output_path.exists() and not blocking_reasons,
                "blocking_reasons": blocking_reasons,
                "warnings": [],
                "image_generation": None,
            }
        else:
            group_metadata = await _render_platform_cover(
                output_path=group_output_path,
                video_path=video_path,
                source_image_path=source_image_path,
                existing_cover_path=None,
                title=title,
                cover_brief=cover_brief,
                platform_key=representative_platform,
                rules=representative_rules,
            )
        group_metadata["cover_group"] = {
            "key": group_key,
            "label": str(group.get("label") or "").strip(),
            "cover_path": str(group_output_path),
            "members": list(group.get("members") or []),
        }
        cache[group_key] = group_metadata
    return cache


def _serialize_cover_matrix(cache: dict[str, dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Any] = {}
    for group in _resolve_standard_cover_matrix_groups():
        group_key = str(group.get("key") or "").strip()
        node = cache.get(group_key) or {}
        cover_group = node.get("cover_group") if isinstance(node.get("cover_group"), dict) else {}
        matrix[group_key] = {
            "label": str(group.get("label") or "").strip(),
            "cover_size": list(group.get("cover_size") or []),
            "cover_path": str(cover_group.get("cover_path") or "").strip() or str(node.get("output_path") or "").strip() or None,
            "publish_ready": bool(node.get("publish_ready")),
            "blocking_reasons": [str(item).strip() for item in (node.get("blocking_reasons") or []) if str(item).strip()],
            "members": list(group.get("members") or []),
        }
    return matrix


async def _render_or_reuse_platform_cover_group(
    *,
    cache: dict[str, dict[str, Any]],
    material_dir: Path,
    output_path: Path,
    video_path: Path,
    source_image_path: Path | None,
    existing_cover_path: Path | None,
    title: str,
    platform_key: str,
    platform_rules: dict[str, Any],
    cover_group: dict[str, Any],
    cover_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    group_key = str(cover_group.get("key") or platform_key).strip()
    group_output_path = material_dir / f"00-cover-{group_key}.jpg"
    group_metadata = cache.get(group_key)
    if group_metadata is None:
        group_rules = dict(platform_rules)
        group_rules["label"] = str(cover_group.get("label") or platform_rules.get("label") or platform_key)
        group_rules["cover_size"] = tuple(cover_group.get("cover_size") or platform_rules["cover_size"])
        group_rules["visual_instruction"] = str(
            cover_group.get("visual_instruction") or platform_rules.get("visual_instruction") or ""
        ).strip()
        group_metadata = await _render_platform_cover(
            output_path=group_output_path,
            video_path=video_path,
            source_image_path=source_image_path,
            existing_cover_path=existing_cover_path,
            title=title,
            cover_brief=cover_brief,
            platform_key=str(cover_group.get("representative_platform") or platform_key),
            rules=group_rules,
        )
        group_metadata["cover_group"] = {
            "key": group_key,
            "label": str(cover_group.get("label") or ""),
            "cover_path": str(group_output_path),
            "members": list(cover_group.get("members") or []),
        }
        cache[group_key] = group_metadata

    return _materialize_platform_cover_from_group(
        group_metadata=group_metadata,
        group_output_path=group_output_path,
        output_path=output_path,
        platform_key=platform_key,
        platform_rules=platform_rules,
        cover_group=cover_group,
    )


def _render_or_reuse_existing_cover_group(
    *,
    cache: dict[str, dict[str, Any]],
    material_dir: Path,
    output_path: Path,
    existing_cover_path: Path | None,
    platform_key: str,
    platform_rules: dict[str, Any],
    cover_group: dict[str, Any],
) -> dict[str, Any]:
    group_key = str(cover_group.get("key") or platform_key).strip()
    group_output_path = material_dir / f"00-cover-{group_key}.jpg"
    group_metadata = cache.get(group_key)
    if group_metadata is None:
        target_width, target_height = tuple(cover_group.get("cover_size") or platform_rules["cover_size"])
        blocking_reasons: list[str] = []
        if existing_cover_path is not None and existing_cover_path.exists():
            fit_mode = _resolve_cover_canvas_fit_mode(
                source_path=existing_cover_path,
                width=int(target_width),
                height=int(target_height),
            )
            _fit_image_to_canvas(
                source_path=existing_cover_path,
                output_path=group_output_path,
                width=int(target_width),
                height=int(target_height),
                fit_mode=fit_mode,
            )
        else:
            blocking_reasons.append("已选择使用已有封面，但目录内未找到可用封面")
        group_metadata = {
            "source": "existing_cover",
            "platform": str(cover_group.get("representative_platform") or platform_key),
            "target_size": {"width": int(target_width), "height": int(target_height)},
            "publish_ready": group_output_path.exists() and not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "warnings": [],
            "image_generation": None,
            "cover_group": {
                "key": group_key,
                "label": str(cover_group.get("label") or ""),
                "cover_path": str(group_output_path),
                "members": list(cover_group.get("members") or []),
            },
        }
        cache[group_key] = group_metadata

    return _materialize_platform_cover_from_group(
        group_metadata=group_metadata,
        group_output_path=group_output_path,
        output_path=output_path,
        platform_key=platform_key,
        platform_rules=platform_rules,
        cover_group=cover_group,
    )


def _materialize_platform_cover_from_group(
    *,
    group_metadata: dict[str, Any],
    group_output_path: Path,
    output_path: Path,
    platform_key: str,
    platform_rules: dict[str, Any],
    cover_group: dict[str, Any],
) -> dict[str, Any]:
    target_width, target_height = int(platform_rules["cover_size"][0]), int(platform_rules["cover_size"][1])
    blocking_reasons = list(group_metadata.get("blocking_reasons") or [])
    warnings = list(group_metadata.get("warnings") or [])
    if group_output_path.exists():
        fit_mode = _resolve_cover_canvas_fit_mode(
            source_path=group_output_path,
            width=target_width,
            height=target_height,
        )
        _fit_image_to_canvas(
            source_path=group_output_path,
            output_path=output_path,
            width=target_width,
            height=target_height,
            fit_mode=fit_mode,
        )
        if bool(group_metadata.get("publish_ready")):
            # Only clear blockers when the shared group artifact itself passed the hard quality contract.
            blocking_reasons = []
    elif not blocking_reasons:
        blocking_reasons.append("通用封面尚未生成完成")
    return {
        "source": "cover_group_reuse",
        "platform": str(platform_key or "").strip(),
        "target_size": {"width": target_width, "height": target_height},
        "publish_ready": output_path.exists() and not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "cover_group": {
            "key": str(cover_group.get("key") or "").strip(),
            "label": str(cover_group.get("label") or "").strip(),
            "cover_path": str(group_output_path),
            "members": list(cover_group.get("members") or []),
        },
        "group_generation": group_metadata,
        "image_generation": group_metadata.get("image_generation"),
    }


def _build_title_goals(titles: list[str], *, platform_key: str) -> list[dict[str, str]]:
    return [
        {
            "title": title,
            "goal": _title_goal_label(title, index=index, platform_key=platform_key),
            "direction": _title_goal_direction(title, index=index, platform_key=platform_key),
        }
        for index, title in enumerate(titles, start=1)
    ]


def _title_goal_label(title: str, *, index: int, platform_key: str) -> str:
    text = str(title or "")
    if re.search(r"值不值|要不要|真香|劝退|能买吗|值吗|香不香", text):
        return "决策转化"
    if re.search(r"差异|对比|区别|怎么选|选哪|取舍", text):
        return "差异对比"
    if re.search(r"质感|细节|做工|手感|上手|实拍|近景", text):
        return "质感种草"
    if re.search(r"终于|直接|太狠|暴击|上头|居然|到手|开箱", text):
        return "流量引爆"
    if platform_key == "youtube" and re.search(r"review|hands-on|test|unboxing", text, re.I):
        return "搜索评测"
    fallback = ("流量引爆", "搜索识别", "差异对比", "质感种草", "决策转化")
    return fallback[min(index - 1, len(fallback) - 1)]


def _title_goal_direction(title: str, *, index: int, platform_key: str) -> str:
    goal = _title_goal_label(title, index=index, platform_key=platform_key)
    mapping = {
        "流量引爆": "用到手、开箱或强情绪先抓点击。",
        "搜索识别": "保留主体关键词，保证用户能搜到。",
        "差异对比": "突出版本差异、选择取舍或对比信息。",
        "质感种草": "放大细节、做工、手感和实拍感。",
        "决策转化": "用值不值、真香或劝退帮助快速判断。",
        "搜索评测": "兼顾主体关键词和评测检索表达。",
    }
    return mapping.get(goal, "明确这条标题承担的发布目标。")


def _validate_platform_material_ready(material: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if bool(material.get("has_title", True)) and not list(material.get("titles") or []):
        problems.append("缺少可发布标题")
    if not str(material.get("body") or "").strip():
        problems.append("缺少可发布正文")
    if not list(material.get("tags") or []):
        problems.append("缺少可发布标签")
    if not str(material.get("full_copy") or "").strip():
        problems.append("完整发布文案为空")
    return problems


def _collect_platform_material_blocking_reasons(material: dict[str, Any]) -> list[str]:
    problems = _validate_platform_material_ready(material)
    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else {}
    if cover_generation and not bool(cover_generation.get("publish_ready", True)):
        problems.extend(str(item).strip() for item in (cover_generation.get("blocking_reasons") or []) if str(item).strip())
    return sorted(set(reason for reason in problems if reason))


def _normalize_requested_material_platform_scope(
    requested_platforms: list[Any] | None,
) -> list[str]:
    normalized: list[str] = []
    for item in requested_platforms or []:
        raw: Any = item
        if isinstance(item, (list, tuple)) and item:
            raw = item[0]
        elif isinstance(item, dict):
            raw = item.get("platform") or item.get("key") or item.get("name")
        platform = _normalize_external_publish_platform_key(raw)
        if platform and platform not in normalized:
            normalized.append(platform)
    return normalized


def _build_material_contract(
    platform_materials: list[dict[str, Any]],
    *,
    requested_platforms: list[str] | None = None,
) -> dict[str, Any]:
    platform_contracts: dict[str, Any] = {}
    blocking_reasons: list[str] = []
    basic_publish_ready = True
    one_click_publish_ready = True
    manual_handoff_platforms: list[dict[str, Any]] = []
    requested_scope = _normalize_requested_material_platform_scope(requested_platforms)
    collection_policy_skip_values = publication_collection_policy_skip_values()
    for material in platform_materials:
        platform_key = _normalize_internal_publish_platform_key(material.get("key"))
        external_platform_key = _normalize_external_publish_platform_key(platform_key)
        label = str(material.get("label") or external_platform_key).strip()
        manual_handoff_only = platform_manual_handoff_only(external_platform_key)
        manual_publish_entry_url = platform_manual_publish_entry_url(external_platform_key)
        material_blocking_reasons = [str(item).strip() for item in (material.get("blocking_reasons") or []) if str(item).strip()]
        cover_policy_required = platform_requires_custom_cover_policy(external_platform_key)
        cover_ready = not cover_policy_required or bool(str(material.get("cover_path") or "").strip())
        metadata_fields_present = [
            field
            for field in (
                "declaration",
                "category",
                "collection_name",
                "visibility_or_publish_mode",
                "scheduled_publish_at",
            )
            if str(material.get(field) or "").strip()
        ]
        metadata_contract_present = any(
            field in material
            for field in (
                "declaration",
                "category",
                "collection_name",
                "visibility_or_publish_mode",
                "scheduled_publish_at",
            )
        )
        if isinstance(material.get("collection"), dict) and str(material.get("collection", {}).get("name") or "").strip():
            if "collection_name" not in metadata_fields_present:
                metadata_fields_present.append("collection_name")
        platform_specific_overrides = (
            dict(material.get("platform_specific_overrides"))
            if isinstance(material.get("platform_specific_overrides"), dict)
            else {}
        )
        collection_management = (
            dict(platform_specific_overrides.get("collection_management"))
            if isinstance(platform_specific_overrides.get("collection_management"), dict)
            else {}
        )
        explicit_collection_name = str(material.get("collection_name") or "").strip()
        if not explicit_collection_name and isinstance(material.get("collection"), dict):
            explicit_collection_name = str(material.get("collection", {}).get("name") or "").strip()
        if not explicit_collection_name:
            explicit_collection_name = str(
                collection_management.get("target_collection_name")
                or collection_management.get("collection_name")
                or ""
            ).strip()
        collection_policy = str(platform_specific_overrides.get("collection_policy") or "").strip().lower()
        explicit_collection_skip = bool(platform_specific_overrides.get("skip_collection_select")) or collection_policy in collection_policy_skip_values
        collection_policy_ready = (
            not platform_requires_explicit_collection_policy(external_platform_key)
            or bool(explicit_collection_name)
            or explicit_collection_skip
        )
        if platform_specific_overrides:
            metadata_fields_present.append("platform_specific_overrides")
            metadata_contract_present = True
        live_publish_preflight = (
            material.get("live_publish_preflight")
            if isinstance(material.get("live_publish_preflight"), dict)
            else platform_specific_overrides.get("live_publish_preflight")
            if isinstance(platform_specific_overrides.get("live_publish_preflight"), dict)
            else {}
        )
        live_publish_preflight_status = str(live_publish_preflight.get("status") or "").strip().lower()
        live_publish_preflight_missing = [
            str(item).strip()
            for item in (live_publish_preflight.get("missing_required_surfaces") or [])
            if str(item).strip()
        ] if isinstance(live_publish_preflight, dict) else []
        live_publish_preflight_ready = live_publish_preflight_status not in {"blocked", "missing_required_surfaces"} and not live_publish_preflight_missing
        schedule_window = evaluate_platform_schedule_window(external_platform_key, material.get("scheduled_publish_at"))
        schedule_window_ready = bool(schedule_window.get("valid"))
        publication_metadata_ready = bool(metadata_fields_present) or not metadata_contract_present
        basic_ready = not material_blocking_reasons
        one_click_ready = (
            basic_ready
            and cover_ready
            and publication_metadata_ready
            and live_publish_preflight_ready
            and collection_policy_ready
            and schedule_window_ready
        )
        if not basic_ready:
            basic_publish_ready = False
        if manual_handoff_only:
            manual_handoff_platforms.append(
                {
                    "platform": external_platform_key,
                    "label": label,
                    "login_url": manual_publish_entry_url,
                }
            )
        elif not one_click_ready:
            one_click_publish_ready = False
        platform_missing: list[str] = []
        if not cover_ready:
            platform_missing.append("cover_path")
        if not publication_metadata_ready:
            platform_missing.append("publication_metadata")
        if not live_publish_preflight_ready:
            platform_missing.append("live_publish_preflight")
        if not collection_policy_ready:
            platform_missing.append("collection_policy")
        if not schedule_window_ready:
            platform_missing.append("schedule_window")
        platform_status = "manual_handoff" if manual_handoff_only else ("passed" if one_click_ready else "failed")
        platform_contracts[external_platform_key] = {
            "status": platform_status,
            "label": label,
            "basic_publish_ready": basic_ready,
            "cover_ready": cover_ready,
            "publication_metadata_ready": publication_metadata_ready,
            "live_publish_preflight_ready": live_publish_preflight_ready,
            "collection_policy_ready": collection_policy_ready,
            "schedule_window_ready": schedule_window_ready,
            "schedule_window": schedule_window,
            "one_click_publish_ready": one_click_ready,
            "manual_handoff_only": manual_handoff_only,
            "manual_publish_entry_url": manual_publish_entry_url,
            "metadata_fields_present": sorted(set(metadata_fields_present)),
            "missing_fields": platform_missing,
            "blocking_reasons": material_blocking_reasons,
        }
        if manual_handoff_only:
            continue
        if not one_click_ready:
            if material_blocking_reasons:
                blocking_reasons.extend(f"{label}：{reason}" for reason in material_blocking_reasons)
            if not cover_ready:
                blocking_reasons.append(f"{label}：缺少平台封面 cover_path")
            if not publication_metadata_ready:
                blocking_reasons.append(f"{label}：缺少平台专属发布配置（declaration/category/collection/visibility/schedule）")
            if not live_publish_preflight_ready:
                if live_publish_preflight_missing:
                    blocking_reasons.append(
                        f"{label}：发布前置门禁未通过，缺少关键参数面 {', '.join(live_publish_preflight_missing)}"
                    )
                else:
                    blocking_reasons.append(f"{label}：发布前置门禁未通过")
            if not collection_policy_ready:
                blocking_reasons.append(f"{label}：缺少合集决策（需指定 collection_name 或显式声明跳过合集）")
            if not schedule_window_ready:
                minimum_ready_at = str(schedule_window.get("minimum_ready_at") or "").strip()
                minimum_lead_minutes = int(schedule_window.get("minimum_lead_minutes") or 0)
                if str(schedule_window.get("reason") or "").strip() == "schedule_too_soon" and minimum_ready_at:
                    blocking_reasons.append(
                        f"{label}：定时发布时间过早，至少需要提前 {minimum_lead_minutes} 分钟（当前最早可发：{minimum_ready_at}）"
                    )
                else:
                    blocking_reasons.append(f"{label}：定时发布时间无效，无法通过平台定时门禁")
    covered_platforms = sorted(platform_contracts.keys())
    missing_requested_platforms = [
        platform
        for platform in (requested_scope or [])
        if platform not in platform_contracts
    ]
    if missing_requested_platforms:
        covered_platforms_text = ", ".join(covered_platforms) if covered_platforms else "无"
        basic_publish_ready = False
        one_click_publish_ready = False
        blocking_reasons.extend(
            [
                f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {covered_platforms_text}"
                for platform in missing_requested_platforms
            ]
        )
    status = "manual_handoff" if manual_handoff_platforms and one_click_publish_ready else ("passed" if one_click_publish_ready else "failed")
    return {
        "status": status,
        "basic_publish_ready": basic_publish_ready,
        "one_click_publish_ready": one_click_publish_ready,
        "blocking_reasons": sorted(set(reason for reason in blocking_reasons if reason)),
        "manual_handoff_platforms": manual_handoff_platforms,
        "platform_scope": {
            "requested_platforms": requested_scope or covered_platforms,
            "covered_platforms": covered_platforms,
            "missing_requested_platforms": missing_requested_platforms,
        },
        "platforms": platform_contracts,
    }


def _material_contract_terminal_status(contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict):
        return "failed"
    status = str(contract.get("status") or "").strip().lower()
    if status in {"passed", "manual_handoff", "failed", "blocked"}:
        return "manual_handoff" if status == "manual_handoff" else ("passed" if status == "passed" else "failed")
    platform_contracts = contract.get("platforms") if isinstance(contract.get("platforms"), dict) else {}
    has_root_blocking_reasons = bool(
        [str(item).strip() for item in (contract.get("blocking_reasons") or []) if str(item).strip()]
    )
    has_manual_handoff_platforms = bool(contract.get("manual_handoff_platforms"))
    if platform_contracts:
        platform_statuses = {
            str(item.get("status") or "").strip().lower()
            for item in platform_contracts.values()
            if isinstance(item, dict) and str(item.get("status") or "").strip()
        }
        if "failed" in platform_statuses or "blocked" in platform_statuses:
            return "failed"
        if "manual_handoff" in platform_statuses:
            return "manual_handoff"
        if any(
            bool(item.get("manual_handoff_only"))
            for item in platform_contracts.values()
            if isinstance(item, dict)
        ):
            return "manual_handoff"
        if platform_statuses and platform_statuses <= {"passed"}:
            return "passed"
    if has_manual_handoff_platforms and bool(contract.get("one_click_publish_ready")):
        return "manual_handoff"
    if has_root_blocking_reasons:
        return "failed"
    if has_manual_handoff_platforms:
        return "manual_handoff"
    if bool(contract.get("one_click_publish_ready")):
        return "passed"
    return "failed"


def _material_contract_publish_ready(contract: dict[str, Any] | None) -> bool:
    return _material_contract_terminal_status(contract) == "passed"


def _material_contract_manual_handoff_ready(contract: dict[str, Any] | None) -> bool:
    return _material_contract_terminal_status(contract) == "manual_handoff"


def _run_material_self_healing(
    *,
    packaging: dict[str, Any],
    platform_materials: list[dict[str, Any]],
    requested_platforms: list[str] | None = None,
) -> dict[str, Any]:
    packaging_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    requested_scope = _normalize_requested_material_platform_scope(requested_platforms)
    if not requested_scope:
        requested_scope = _normalize_requested_material_platform_scope(
            [material.get("key") for material in platform_materials]
        )
    passes: list[dict[str, Any]] = []
    for attempt in range(1, MATERIAL_SELF_HEAL_MAX_PASSES + 1):
        pass_actions: list[dict[str, Any]] = []
        for material in platform_materials:
            platform_key = str(material.get("key") or "").strip()
            platform_payload = packaging_platforms.get(platform_key) if isinstance(packaging_platforms.get(platform_key), dict) else {}
            pass_actions.extend(_autofill_platform_material_metadata(material=material, platform_payload=platform_payload))
            material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
            material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        contract = _build_material_contract(
            platform_materials,
            requested_platforms=requested_scope,
        )
        passes.append(
            {
                "pass_index": attempt,
                "applied_actions": pass_actions,
                "one_click_publish_ready": _material_contract_publish_ready(contract),
                "status": _material_contract_terminal_status(contract),
                "blocking_reasons": list(contract.get("blocking_reasons") or []),
            }
        )
        contract_status = _material_contract_terminal_status(contract)
        if contract_status != "failed" or not pass_actions:
            return {
                "status": contract_status if contract_status != "failed" else "failed",
                "passes": passes,
                "final_contract": contract,
            }
    final_contract = _build_material_contract(
        platform_materials,
        requested_platforms=requested_scope,
    )
    return {
        "status": _material_contract_terminal_status(final_contract),
        "passes": passes,
        "final_contract": final_contract,
    }


def _derive_safe_platform_specific_overrides(
    *,
    platform_key: str,
    material: dict[str, Any],
    platform_payload: dict[str, Any],
) -> dict[str, Any]:
    overrides = (
        dict(material.get("platform_specific_overrides"))
        if isinstance(material.get("platform_specific_overrides"), dict)
        else {}
    )
    payload_overrides = (
        dict(platform_payload.get("platform_specific_overrides"))
        if isinstance(platform_payload.get("platform_specific_overrides"), dict)
        else {}
    )
    if payload_overrides:
        merged = dict(payload_overrides)
        merged.update(overrides)
        overrides = merged
    collection = material.get("collection") if isinstance(material.get("collection"), dict) else {}
    collection_name = str(material.get("collection_name") or collection.get("name") or "").strip()
    has_explicit_collection = (
        bool(collection_name)
        or bool(str(overrides.get("collection_policy") or "").strip())
        or bool(overrides.get("skip_collection_select"))
    )
    if platform_requires_explicit_collection_policy(platform_key) and not has_explicit_collection:
        overrides["collection_policy"] = "skip"
        overrides["skip_collection_select"] = True
    return overrides


def _autofill_platform_material_metadata(*, material: dict[str, Any], platform_payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    platform_key = str(material.get("key") or "").strip()
    copy_material = material.get("copy_material") if isinstance(material.get("copy_material"), dict) else {}
    if not copy_material:
        generated_copy_material = {
            "source": "intelligent_copy_material_self_heal",
            "primary_title": str(material.get("primary_title") or "").strip(),
            "titles": [str(item).strip() for item in (material.get("titles") or []) if str(item).strip()],
            "body": str(material.get("body") or "").strip(),
            "tags": [str(item).strip() for item in (material.get("tags") or []) if str(item).strip()],
        }
        generated_copy_material = {key: value for key, value in generated_copy_material.items() if value not in ("", [], {}, None)}
        if generated_copy_material:
            material["copy_material"] = generated_copy_material
            copy_material = generated_copy_material
            actions.append({"platform": platform_key, "field": "copy_material", "action": "derived_from_material"})
    for field in ("declaration", "category", "visibility_or_publish_mode", "scheduled_publish_at"):
        current = str(material.get(field) or "").strip()
        if current:
            continue
        candidate = str(platform_payload.get(field) or "").strip()
        if not candidate and isinstance(copy_material, dict):
            candidate = str(copy_material.get(field) or "").strip()
        if not candidate and field == "declaration":
            candidate = platform_default_declaration(platform_key)
        if candidate:
            material[field] = candidate
            actions.append({"platform": platform_key, "field": field, "action": "filled_from_safe_source"})
    schedule_window = evaluate_platform_schedule_window(platform_key, material.get("scheduled_publish_at"))
    if not schedule_window.get("valid"):
        repaired_schedule = suggest_platform_schedule_window_repair(platform_key, material.get("scheduled_publish_at"))
        repaired_value = str(repaired_schedule.get("scheduled_publish_at") or "").strip()
        if repaired_schedule.get("repaired") and repaired_value and repaired_value != str(material.get("scheduled_publish_at") or "").strip():
            material["scheduled_publish_at"] = repaired_value
            actions.append(
                {
                    "platform": platform_key,
                    "field": "scheduled_publish_at",
                    "action": "refreshed_to_next_valid_window",
                    "reason": str(repaired_schedule.get("reason") or "schedule_window_repair"),
                }
            )
    if not str(material.get("collection_name") or "").strip():
        collection = material.get("collection") if isinstance(material.get("collection"), dict) else {}
        candidate = str(collection.get("name") or "").strip()
        if not candidate:
            payload_collection = platform_payload.get("collection") if isinstance(platform_payload.get("collection"), dict) else {}
            candidate = str(platform_payload.get("collection_name") or payload_collection.get("name") or "").strip()
        if candidate:
            material["collection_name"] = candidate
            actions.append({"platform": platform_key, "field": "collection_name", "action": "filled_from_safe_source"})
    if not isinstance(material.get("collection"), dict) or not material.get("collection"):
        collection_name = str(material.get("collection_name") or "").strip()
        payload_collection = platform_payload.get("collection") if isinstance(platform_payload.get("collection"), dict) else {}
        payload_collection_name = str(platform_payload.get("collection_name") or payload_collection.get("name") or "").strip()
        selected_name = collection_name or payload_collection_name
        if selected_name:
            material["collection"] = {"name": selected_name}
            actions.append({"platform": platform_key, "field": "collection", "action": "filled_from_collection_name"})
    current_overrides = (
        dict(material.get("platform_specific_overrides"))
        if isinstance(material.get("platform_specific_overrides"), dict)
        else {}
    )
    derived_overrides = _derive_safe_platform_specific_overrides(
        platform_key=platform_key,
        material=material,
        platform_payload=platform_payload,
    )
    if derived_overrides != current_overrides:
        material["platform_specific_overrides"] = derived_overrides
        if derived_overrides.get("skip_collection_select") and not current_overrides.get("skip_collection_select"):
            actions.append(
                {
                    "platform": platform_key,
                    "field": "platform_specific_overrides.collection_policy",
                    "action": "defaulted_to_explicit_collection_skip",
                }
            )
    return actions


def _build_platform_packaging_export(
    *,
    packaging: dict[str, Any],
    platform_materials: list[dict[str, Any]],
    requested_platforms: list[str] | None = None,
    cover_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    requested_scope = _normalize_requested_material_platform_scope(requested_platforms)
    covered_scope = sorted(
        {
            str(material.get("key") or "").strip().lower().replace("_", "-")
            for material in platform_materials
            if str(material.get("key") or "").strip()
        }
    )
    export_payload: dict[str, Any] = {
        "highlights": dict(packaging.get("highlights") or {}),
        "fact_sheet": dict(packaging.get("fact_sheet") or {}) if isinstance(packaging.get("fact_sheet"), dict) else {},
        "title_audit": dict(packaging.get("title_audit") or {}) if isinstance(packaging.get("title_audit"), dict) else {},
        "platform_scope": {
            "requested_platforms": requested_scope or covered_scope,
            "covered_platforms": covered_scope,
            "missing_requested_platforms": [
                platform
                for platform in (requested_scope or [])
                if platform not in covered_scope
            ],
        },
        "cover_matrix": dict(cover_matrix or {}),
        "platforms": {},
    }
    existing_platforms = {
        _normalize_external_publish_platform_key(key): dict(value)
        for key, value in ((packaging.get("platforms") or {}) if isinstance(packaging.get("platforms"), dict) else {}).items()
        if _normalize_external_publish_platform_key(key) and isinstance(value, dict)
    }
    for material in platform_materials:
        platform_key = _normalize_external_publish_platform_key(material.get("key"))
        if not platform_key:
            continue
        entry: dict[str, Any] = dict(existing_platforms.get(platform_key) or {})
        entry.update(
            {
            "titles": list(material.get("titles") or []),
            "description": str(material.get("body") or "").strip(),
            "tags": list(material.get("tags") or []),
            "cover_path": str(material.get("cover_path") or "").strip(),
            "copy_material": dict(material.get("copy_material") or {}) if isinstance(material.get("copy_material"), dict) else {},
            }
        )
        for field in ("declaration", "category", "collection_name", "visibility_or_publish_mode", "scheduled_publish_at"):
            value = str(material.get(field) or "").strip()
            if value:
                entry[field] = value
        if isinstance(material.get("collection"), dict) and material.get("collection"):
            entry["collection"] = dict(material.get("collection") or {})
        if isinstance(material.get("live_publish_preflight"), dict) and material.get("live_publish_preflight"):
            entry["live_publish_preflight"] = dict(material.get("live_publish_preflight") or {})
        if isinstance(material.get("platform_specific_overrides"), dict) and material.get("platform_specific_overrides"):
            entry["platform_specific_overrides"] = dict(material.get("platform_specific_overrides") or {})
        export_payload["platforms"][platform_key] = entry
    return export_payload


def _write_platform_material_files(*, material_dir: Path, index: int, material: dict[str, Any]) -> None:
    platform_key = str(material.get("key") or "").strip()
    base_name = f"{index:02d}-{platform_key}"
    titles = list(material.get("titles") or [])
    if titles:
        (material_dir / f"{base_name}-titles.txt").write_text(
            str(material.get("title_copy_all") or "").strip() + "\n",
            encoding="utf-8",
        )
    (material_dir / f"{base_name}-body.txt").write_text(str(material.get("body") or "").strip() + "\n", encoding="utf-8")
    (material_dir / f"{base_name}-tags.txt").write_text(str(material.get("tags_copy") or "").strip() + "\n", encoding="utf-8")
    (material_dir / f"{base_name}.md").write_text(_render_platform_material_markdown(material), encoding="utf-8")


def _platform_material_files_exist(*, material_dir: Path, index: int, material: dict[str, Any]) -> bool:
    platform_key = str(material.get("key") or "").strip()
    base_name = f"{index:02d}-{platform_key}"
    required_paths = [
        material_dir / f"{base_name}-body.txt",
        material_dir / f"{base_name}-tags.txt",
        material_dir / f"{base_name}.md",
    ]
    if list(material.get("titles") or []):
        required_paths.append(material_dir / f"{base_name}-titles.txt")
    return all(path.exists() for path in required_paths)


def _resolve_platform_material_serial(platform_key: str) -> int:
    normalized = _normalize_internal_publish_platform_key(platform_key)
    for index, item in enumerate(PLATFORM_ORDER, start=1):
        if item[0] == normalized:
            return index
    return 1


def _merge_intelligent_copy_profile_hints(
    *,
    content_profile: dict[str, Any] | None,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    copy_style: str,
) -> dict[str, Any]:
    stem = video_path.stem.strip()
    transcript_text = " ".join(
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items[:80]
    ).strip()
    hook_line = transcript_text[:36].strip() if transcript_text else stem
    combined_text = " ".join(part for part in (stem, transcript_text) if part).strip()
    seeded = _seed_profile_from_text(combined_text)
    subject_type_candidates = [str(item).strip() for item in (seeded.get("subject_type_candidates") or []) if str(item).strip()]
    video_theme_candidates = [str(item).strip() for item in (seeded.get("video_theme_candidates") or []) if str(item).strip()]
    profile = dict(content_profile or {})
    seeded_subject_type = subject_type_candidates[0] if subject_type_candidates else ""
    keyword_subject_type = _infer_intelligent_copy_subject_type(combined_text)
    heuristic_subject_type = seeded_subject_type
    if _should_override_subject_type_with_heuristic(seeded_subject_type, keyword_subject_type):
        heuristic_subject_type = keyword_subject_type
    elif not heuristic_subject_type:
        heuristic_subject_type = keyword_subject_type

    subject_type = str(profile.get("subject_type") or "").strip()
    if not subject_type or _should_override_subject_type_with_heuristic(subject_type, heuristic_subject_type):
        subject_type = heuristic_subject_type

    subject_brand = str(profile.get("subject_brand") or "").strip() or str(seeded.get("subject_brand") or "").strip()
    if not subject_brand and re.search(r"(?<![A-Z0-9])FAS(?![A-Z0-9])", stem, re.IGNORECASE):
        subject_brand = "FAS"
    if not subject_brand and "琢匠" in combined_text:
        subject_brand = "琢匠"

    subject_model = str(profile.get("subject_model") or "").strip() or str(seeded.get("subject_model") or "").strip()
    subject_domain = str(profile.get("subject_domain") or "").strip() or _subject_domain_from_subject_type(subject_type)
    video_theme = str(profile.get("video_theme") or "").strip() or (video_theme_candidates[0] if video_theme_candidates else stem)
    search_queries = [str(item).strip() for item in (profile.get("search_queries") or seeded.get("search_queries") or []) if str(item).strip()]

    if subject_brand and subject_model:
        primary_query = f"{subject_brand} {subject_model}"
        if primary_query not in search_queries:
            search_queries.insert(0, primary_query)
    elif subject_brand and subject_type:
        primary_query = f"{subject_brand} {subject_type}"
        if primary_query not in search_queries:
            search_queries.insert(0, primary_query)

    summary = str(profile.get("summary") or "").strip()
    if not summary or "主题待进一步确认" in summary or "主体信息暂未稳定识别" in summary:
        subject_label = subject_model or subject_brand or subject_type or stem or "这条视频"
        summary = f"{subject_label}的成片素材，后续文案需要围绕画面、字幕和已核验事实重新创作。"

    resolved_hook_line = str(profile.get("hook_line") or "").strip()
    if not resolved_hook_line or resolved_hook_line == "内容待人工确认":
        resolved_hook_line = hook_line or "内容待人工确认"

    engagement_question = str(profile.get("engagement_question") or "").strip() or "这条视频你会怎么发？"
    cover_title = profile.get("cover_title") if isinstance(profile.get("cover_title"), dict) else {}
    cover_main = str(cover_title.get("main") or "").strip()
    if not cover_main or cover_main == "内容待确认":
        cover_main = subject_model or subject_brand or stem[:18] or "内容待确认"

    specialized = _specialize_intelligent_copy_profile(
        stem=stem,
        transcript_text=transcript_text,
        subject_brand=subject_brand,
        subject_model=subject_model,
        subject_type=subject_type,
        subject_domain=subject_domain,
        video_theme=video_theme,
        summary=summary,
        hook_line=resolved_hook_line,
        engagement_question=engagement_question,
        search_queries=search_queries,
        cover_title={
            "top": str(cover_title.get("top") or "").strip(),
            "main": cover_main[:18] or "内容待确认",
            "bottom": str(cover_title.get("bottom") or "").strip(),
        },
    )

    return {
        **profile,
        "subject_brand": specialized["subject_brand"],
        "subject_model": specialized["subject_model"],
        "subject_type": specialized["subject_type"],
        "subject_domain": specialized["subject_domain"],
        "video_theme": specialized["video_theme"],
        "summary": specialized["summary"],
        "hook_line": specialized["hook_line"],
        "engagement_question": specialized["engagement_question"],
        "copy_style": str(copy_style or "").strip() or "attention_grabbing",
        "search_queries": specialized["search_queries"],
        "cover_title": specialized["cover_title"],
    }


def _ensure_intelligent_copy_subject_identity(content_profile: dict[str, Any] | None, video_path: Path) -> dict[str, Any]:
    profile = dict(content_profile or {})
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    stem = video_path.stem.strip()
    normalized_brand, normalized_model = _normalize_intelligent_copy_subject_identity(
        subject_brand=brand,
        subject_model=model,
        fallback_stem=stem,
    )
    if normalized_brand:
        profile["subject_brand"] = normalized_brand
    if normalized_model:
        profile["subject_model"] = normalized_model
        if normalized_model != model:
            profile["search_queries"] = [normalized_model]
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
    if (brand and not _is_generic_intelligent_copy_subject_identity(brand)) or (
        model and not _is_generic_intelligent_copy_subject_identity(model)
    ):
        return profile
    if stem:
        profile["subject_model"] = stem
        profile.setdefault("search_queries", [stem])
        if not str(profile.get("summary") or "").strip():
            profile["summary"] = f"{stem}的成片素材，后续文案需要围绕画面、字幕和已核验事实重新创作。"
    return profile


def _is_generic_intelligent_copy_subject_identity(value: str) -> bool:
    compact = re.sub(r"[\s\-_·:：/|，,。.!！?？#【】\[\]()（）]+", "", str(value or ""))
    return compact in {
        "",
        "产品",
        "这款产品",
        "开箱产品",
        "内容",
        "内容待确认",
        "主体待确认",
        "视频",
        "这条视频",
        "物料",
    }


def _normalize_intelligent_copy_subject_identity(
    *,
    subject_brand: str,
    subject_model: str,
    fallback_stem: str,
) -> tuple[str, str]:
    brand = str(subject_brand or "").strip()
    model = str(subject_model or "").strip()
    source = model or fallback_stem
    if not source:
        return brand, model
    compact_source = re.sub(r"\s+", " ", source).strip()
    if not brand:
        split_brand, split_model = _split_cover_identity_lines(compact_source)
        if split_brand and split_model:
            brand = split_brand
            model = split_model
    elif not model:
        remainder = re.sub(rf"^{re.escape(brand)}(?:\s+|(?=[\u4e00-\u9fff]))", "", compact_source, count=1).strip()
        if remainder:
            model = remainder
    if not model:
        model = compact_source
    model = _strip_cover_compare_suffix(model)
    model = re.sub(r"\s*(两款开箱|开箱|上手|实拍|体验|评测)\s*$", "", model).strip()
    model = re.sub(r"\s*(顶配次顶配.*|顶配与次顶配.*|顶配vs次顶配.*|顶配Vs次顶配.*)$", "", model).strip()
    return brand, model or compact_source


def _should_use_intelligent_copy_fast_path(text: str) -> bool:
    return match_intelligent_copy_topic(text) is not None


def _infer_intelligent_copy_subject_type(text: str) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    if any(token in normalized for token in ("紫铜", "白铜", "摆件", "雕像", "桌搭")) and "貔貅" in normalized:
        return "铜制摆件"
    if any(token in normalized for token in ("刀帕", "伞绳", "绳扣", "弹力绳")):
        return "刀帕收纳配件"
    if any(token in normalized for token in ("机能包", "背包", "副包", "收纳")):
        return "EDC机能包"
    if any(token in normalized for token in ("工具钳", "钳", "批头", "螺丝刀")):
        return "多功能工具钳"
    if any(token in normalized for token in ("手电", "电筒", "司令官", "流明", "UV")):
        return "EDC手电"
    if any(token in normalized for token in ("折刀", "刀", "柄材", "背夹", "开刃", "钢材")):
        return "EDC折刀"
    return ""


def _should_override_subject_type_with_heuristic(current: str, heuristic: str) -> bool:
    normalized_current = str(current or "").strip()
    normalized_heuristic = str(heuristic or "").strip()
    if not normalized_heuristic:
        return False
    if not normalized_current:
        return True
    if normalized_current == normalized_heuristic:
        return False
    return normalized_current in {"AI创作工具", "AI工作流工具", "软件工具", "软件界面", "开箱产品", "产品体验"}


def _render_platform_material_markdown(material: dict[str, Any]) -> str:
    lines = [f"# {material.get('label') or ''}", ""]
    if material.get("has_title"):
        lines.extend(
            [
                "## 标题",
                str(material.get("title_copy_all") or "").strip(),
                "",
            ]
        )
    lines.extend(
        [
            f"## {material.get('body_label') or '正文'}",
            str(material.get("body") or "").strip(),
            "",
            f"## {material.get('tag_label') or '标签'}",
            str(material.get("tags_copy") or "").strip(),
            "",
        ]
    )
    return "\n".join(lines).strip() + "\n"


async def _prepare_intelligent_copy_cover_source(
    *,
    video_path: Path,
    material_dir: Path,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
    existing_verified_source_path: Path | None = None,
    existing_verified_manifest: dict[str, Any] | None = None,
) -> Path | None:
    source_path = material_dir / "00-highlight-cover-source.jpg"
    manifest_path = material_dir / "00-highlight-cover-source.json"
    settings = get_settings()
    try:
        duration = _probe_duration(video_path)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            candidates = (
                _sample_cover_candidates(
                    video_path,
                    duration=duration,
                    anchor_seek=3.0,
                    candidate_count=_resolve_cover_source_candidate_count(
                        max(6, int(settings.cover_candidate_count or 10))
                    ),
                    tmpdir=tmp,
                )
                if duration > 0
                else []
            )
            if not candidates:
                raise RuntimeError("没有可用于封面判断的候选帧")
            candidates = _annotate_cover_source_candidates(candidates)
            try:
                selected = await _select_intelligent_copy_highlight_candidate(
                    candidates,
                    content_profile=content_profile,
                    packaging=packaging,
                    contact_sheet_output_path=material_dir / "00-highlight-candidates-sheet.jpg",
                )
            except Exception as exc:
                selected = {
                    "index": 0,
                    "source": "fallback_first_candidate",
                    "score": None,
                    "reason": f"高光帧智能选择失败，已使用首个候选帧兜底：{exc}",
                }
            if _should_preserve_existing_cover_source_after_failed_refresh(
                selected=selected,
                existing_verified_source_path=existing_verified_source_path,
                existing_verified_manifest=existing_verified_manifest,
            ):
                return existing_verified_source_path
            candidate_index = max(0, min(len(candidates) - 1, int(selected.get("index", 0) or 0)))
            candidate = candidates[candidate_index]
            await _extract_frame(video_path, source_path, float(candidate.get("seek") or 3.0))
            _write_cover_source_manifest(
                manifest_path,
                {
                    "seek_sec": round(float(candidate.get("seek") or 0.0), 2),
                    "source": selected.get("source") or "highlight_rank",
                    "score": selected.get("score"),
                    "reason": selected.get("reason") or "",
                    "candidate_index": candidate_index,
                    "contact_sheet_path": selected.get("contact_sheet_path") or "",
                },
            )
            return source_path
    except Exception as exc:
        if (
            existing_verified_source_path is not None
            and existing_verified_source_path.exists()
            and _cover_source_manifest_is_verified(existing_verified_manifest)
        ):
            return existing_verified_source_path
        _write_cover_source_manifest(manifest_path, {"source": "failed", "error": str(exc)})
        return None


def _cover_source_manifest_is_verified(manifest: dict[str, Any] | None) -> bool:
    if not isinstance(manifest, dict):
        return False
    source = str(manifest.get("source") or "").strip().lower()
    return source.startswith("llm_")


async def _restore_verified_cover_source_snapshot(
    *,
    video_path: Path,
    source_path: Path | None,
    manifest_path: Path,
    manifest: dict[str, Any] | None,
) -> Path | None:
    if source_path is None or not _cover_source_manifest_is_verified(manifest):
        return source_path
    try:
        seek_sec = float((manifest or {}).get("seek_sec") or 0.0)
    except Exception:
        seek_sec = 0.0
    if seek_sec <= 0:
        return source_path
    await _extract_frame(video_path, source_path, seek_sec)
    _write_cover_source_manifest(manifest_path, dict(manifest or {}))
    return source_path


def _should_preserve_existing_cover_source_after_failed_refresh(
    *,
    selected: dict[str, Any] | None,
    existing_verified_source_path: Path | None,
    existing_verified_manifest: dict[str, Any] | None,
) -> bool:
    if existing_verified_source_path is None or not existing_verified_source_path.exists():
        return False
    if not _cover_source_manifest_is_verified(existing_verified_manifest):
        return False
    source = str((selected or {}).get("source") or "").strip().lower()
    if not source:
        return True
    return source in {"fallback_first_candidate", "heuristic_hard_contract_guard", "failed"}


async def _select_intelligent_copy_highlight_candidate(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
    contact_sheet_output_path: Path | None = None,
) -> dict[str, Any]:
    preview_paths = [candidate["preview"] for candidate in candidates if candidate.get("preview")]
    if not preview_paths:
        raise RuntimeError("没有候选帧预览图，无法选择封面高光")
    profile_text = json.dumps(
        {
            "content_profile": _content_profile_summary(content_profile),
            "highlights": dict(packaging.get("highlights") or {}),
        },
        ensure_ascii=False,
    )
    chunk_size = _resolve_cover_source_selection_chunk_size(len(candidates))
    last_error = ""
    for attempt in range(1, 4):
        try:
            selection_contract = _build_cover_source_selection_contract(
                content_profile=content_profile,
                packaging=packaging,
            )
            finalist_numbers = await _select_cover_source_finalist_numbers(
                candidates=candidates,
                preview_paths=preview_paths,
                profile_text=profile_text,
                selection_contract=selection_contract,
                content_profile=content_profile,
                packaging=packaging,
                attempt=attempt,
                chunk_size=chunk_size,
                contact_sheet_output_path=contact_sheet_output_path,
            )
            final_candidates = [candidates[number - 1] for number in finalist_numbers if 1 <= number <= len(candidates)]
            final_preview_paths = [preview_paths[number - 1] for number in finalist_numbers if 1 <= number <= len(preview_paths)]
            if len(final_candidates) == 1:
                return {
                    "index": candidates.index(final_candidates[0]),
                    "score": 1.0,
                    "reason": "唯一候选在分层筛选中直接胜出",
                    "source": "llm_contact_sheet_rank",
                    "contact_sheet_path": "",
                    "attempts": attempt,
                }
            final_sheet_path = _build_numbered_highlight_contact_sheet(
                final_preview_paths,
                output_path=contact_sheet_output_path,
            )
            final_prompt = (
                "你正在做封面底图最终定夺。"
                "这张四宫格或九宫格里只保留了前一轮胜出的候选。"
                "请从这些候选里选出唯一最优的一张，用于后续 AI 封面包装生图。"
                "优先看主角度完整展示、展开态、结构清晰、少字幕遮挡。"
                f"\n硬约束：{selection_contract}"
                f"\n当前候选对应原始序号：{finalist_numbers}"
                f"\n视频主题参考：{profile_text}"
                "\n输出 JSON："
                "{\"best_number\":2,\"ranking_numbers\":[2,4,1,3],\"score\":0.93,\"reason\":\"完整展开且主体角度最清晰\"}"
            )
            content = await asyncio.wait_for(
                complete_with_images(
                    final_prompt,
                    [final_sheet_path],
                    max_tokens=180,
                    json_mode=True,
                    preferred_provider="minimax",
                    preferred_model="minimax-m3",
                ),
                timeout=_resolve_cover_source_multimodal_timeout("final_rank"),
            )
            data = json.loads(extract_json_text(content))
            if "best_number" in data or "number" in data:
                final_index = int(data.get("best_number", data.get("number", 1)) or 1) - 1
            else:
                final_index = int(data.get("best_index", data.get("index", 0)) or 0)
            ranked_numbers = _extract_cover_source_shortlist_numbers(
                data,
                raw_text=content,
                original_numbers=finalist_numbers,
                finalist_limit=len(finalist_numbers),
            )
            full_frame_selected = await _reselect_cover_source_from_full_frame_review(
                final_candidates=final_candidates,
                finalist_numbers=finalist_numbers,
                ranked_numbers=ranked_numbers,
                final_sheet_path=final_sheet_path,
                profile_text=profile_text,
                selection_contract=selection_contract,
            )
            if full_frame_selected is not None:
                selected_candidate = final_candidates[full_frame_selected["index"]]
                selected_score = _normalize_score(full_frame_selected.get("score"), fallback=_normalize_score(data.get("score"), fallback=0.0))
                selected_reason = str(full_frame_selected.get("reason") or "").strip() or str(data.get("reason") or "").strip()
                if not _selection_result_violates_hard_contract(
                    selected_candidate,
                    content_profile=content_profile,
                    packaging=packaging,
                    score=selected_score,
                    reason=selected_reason,
                ):
                    return {
                        "index": candidates.index(selected_candidate),
                        "score": selected_score,
                        "reason": selected_reason,
                        "source": "llm_full_frame_review",
                        "contact_sheet_path": str(final_sheet_path),
                        "attempts": attempt,
                        "review_numbers": list(full_frame_selected.get("review_numbers") or []),
                    }
                full_frame_valid_backup = _select_first_valid_cover_candidate_from_ranked_numbers(
                    final_candidates=final_candidates,
                    finalist_numbers=finalist_numbers,
                    ranked_numbers=list(full_frame_selected.get("valid_numbers") or [])
                    or list(full_frame_selected.get("ranked_numbers") or []),
                    content_profile=content_profile,
                    packaging=packaging,
                )
                if full_frame_valid_backup is not None and full_frame_valid_backup["candidate"] is not selected_candidate:
                    return {
                        "index": candidates.index(full_frame_valid_backup["candidate"]),
                        "score": selected_score,
                        "reason": "原图复判首选未通过硬合同，已切换到同轮复判里满足硬合同的候选",
                        "source": "llm_full_frame_review_valid_backup",
                        "contact_sheet_path": str(final_sheet_path),
                        "attempts": attempt,
                        "review_numbers": list(full_frame_selected.get("review_numbers") or []),
                    }
            if 0 <= final_index < len(final_candidates):
                selected_candidate = final_candidates[final_index]
                selected_score = _normalize_score(data.get("score"), fallback=0.0)
                selected_reason = str(data.get("reason") or "").strip()
                if _selection_result_violates_hard_contract(
                    selected_candidate,
                    content_profile=content_profile,
                    packaging=packaging,
                    score=selected_score,
                    reason=selected_reason,
                ):
                    ranked_backup = _select_first_valid_cover_candidate_from_ranked_numbers(
                        final_candidates=final_candidates,
                        finalist_numbers=finalist_numbers,
                        ranked_numbers=ranked_numbers,
                        content_profile=content_profile,
                        packaging=packaging,
                    )
                    if ranked_backup is not None and ranked_backup["candidate"] is not selected_candidate:
                        return {
                            "index": candidates.index(ranked_backup["candidate"]),
                            "score": selected_score,
                            "reason": "模型首选未通过硬合同，已按同组排序结果切换到下一张满足硬合同的候选",
                            "source": "llm_contact_sheet_rank_backup",
                            "contact_sheet_path": str(final_sheet_path),
                            "attempts": attempt,
                        }
                    corrected = await _reselect_cover_source_after_hard_contract_violation(
                        final_candidates=final_candidates,
                        finalist_numbers=finalist_numbers,
                        final_sheet_path=final_sheet_path,
                        profile_text=profile_text,
                        selection_contract=selection_contract,
                    )
                    if corrected is not None:
                        corrected_candidate = final_candidates[corrected["index"]]
                        corrected_score = _normalize_score(corrected.get("score"), fallback=0.0)
                        corrected_reason = str(corrected.get("reason") or "").strip()
                        if not _selection_result_violates_hard_contract(
                            corrected_candidate,
                            content_profile=content_profile,
                            packaging=packaging,
                            score=corrected_score,
                            reason=corrected_reason,
                        ):
                            return {
                                "index": candidates.index(corrected_candidate),
                                "score": corrected_score,
                                "reason": corrected_reason,
                                "source": "llm_contact_sheet_rank_corrected",
                                "contact_sheet_path": str(final_sheet_path),
                                "attempts": attempt,
                            }
                        corrected_ranked_backup = _select_first_valid_cover_candidate_from_ranked_numbers(
                            final_candidates=final_candidates,
                            finalist_numbers=finalist_numbers,
                            ranked_numbers=list(corrected.get("ranked_numbers") or []),
                            content_profile=content_profile,
                            packaging=packaging,
                        )
                        if corrected_ranked_backup is not None and corrected_ranked_backup["candidate"] is not corrected_candidate:
                            return {
                                "index": candidates.index(corrected_ranked_backup["candidate"]),
                                "score": corrected_score,
                                "reason": "模型纠错首选未通过硬合同，已改用纠错排序里下一张满足硬合同的候选",
                                "source": "llm_contact_sheet_rank_corrected_backup",
                                "contact_sheet_path": str(final_sheet_path),
                                "attempts": attempt,
                            }
                    fallback_finalist_number = _fallback_hard_contract_cover_candidate_numbers(
                        final_candidates,
                        finalist_limit=1,
                        content_profile=content_profile,
                        packaging=packaging,
                    )[0]
                    fallback_candidate = final_candidates[max(0, min(len(final_candidates) - 1, fallback_finalist_number - 1))]
                    return {
                        "index": candidates.index(fallback_candidate),
                        "score": 0.0,
                        "reason": "候选结果未通过硬合同，已按字幕污染/稳定性启发式改选更稳妥底图",
                        "source": "heuristic_hard_contract_guard",
                        "contact_sheet_path": str(final_sheet_path),
                        "attempts": attempt,
                    }
                return {
                    "index": candidates.index(selected_candidate),
                    "score": selected_score,
                    "reason": selected_reason,
                    "source": "llm_contact_sheet_rank",
                    "contact_sheet_path": str(final_sheet_path),
                    "attempts": attempt,
                }
            last_error = f"模型返回序号越界：{final_index + 1}"
        except Exception as exc:
            last_error = str(exc) or exc.__class__.__name__
    raise RuntimeError(f"高光帧识别经过重试后仍失败：{last_error}")


def _annotate_cover_source_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for candidate in candidates:
        item = dict(candidate)
        preview = candidate.get("preview")
        if preview:
            item["subtitle_overlay_risk"] = _estimate_cover_subtitle_overlay_risk(Path(preview))
        annotated.append(item)
    return annotated


def _estimate_cover_subtitle_overlay_risk(path: Path) -> float:
    if not path.exists():
        return 0.0
    try:
        from PIL import Image

        with Image.open(path) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            if width <= 0 or height <= 0:
                return 0.0
            top = max(0, int(height * 0.84))
            band = rgb.crop((0, top, width, height))
            band_width, band_height = band.size
            total = max(1, band_width * band_height)
            pixels = band.load()
            mask = [0] * total
            for y in range(band_height):
                for x in range(band_width):
                    r, g, b = pixels[x, y]
                    high = max(r, g, b)
                    low = min(r, g, b)
                    saturation = (high - low) / max(1, high)
                    yellow_fill = r > 170 and g > 140 and b < 130
                    magenta_outline = r > 170 and b > 130 and g < 160
                    bright_text = high > 210 and saturation < 0.24
                    if yellow_fill or magenta_outline or bright_text:
                        mask[y * band_width + x] = 1

            seen = [False] * total
            subtitle_like_area = 0
            for start_index, active in enumerate(mask):
                if not active or seen[start_index]:
                    continue
                queue: deque[int] = deque([start_index])
                seen[start_index] = True
                xs: list[int] = []
                ys: list[int] = []
                area = 0
                while queue:
                    current = queue.popleft()
                    row, col = divmod(current, band_width)
                    xs.append(col)
                    ys.append(row)
                    area += 1
                    for next_col, next_row in ((col - 1, row), (col + 1, row), (col, row - 1), (col, row + 1)):
                        if 0 <= next_col < band_width and 0 <= next_row < band_height:
                            next_index = next_row * band_width + next_col
                            if not seen[next_index] and mask[next_index]:
                                seen[next_index] = True
                                queue.append(next_index)
                min_x, max_x = min(xs), max(xs)
                min_y, max_y = min(ys), max(ys)
                component_width = max_x - min_x + 1
                component_height = max_y - min_y + 1
                bottomness = max_y / max(1, band_height)
                if (
                    20 <= area <= total * 0.03
                    and component_height <= band_height * 0.35
                    and component_width <= band_width * 0.35
                    and bottomness >= 0.45
                ):
                    subtitle_like_area += area
            risk = subtitle_like_area / max(1.0, total * 0.08)
            return round(min(1.0, risk), 3)
    except Exception:
        return 0.0


def _selection_result_violates_hard_contract(
    candidate: dict[str, Any],
    *,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
    score: float | None,
    reason: str,
) -> bool:
    contract = _build_cover_source_selection_contract(content_profile=content_profile, packaging=packaging)
    subtitle_risk = float(candidate.get("subtitle_overlay_risk") or 0.0)
    is_compare = "同框" in contract or "版本差异" in contract
    subtitle_block_threshold = 0.45 if is_compare else 0.18
    if subtitle_risk >= subtitle_block_threshold:
        return True
    if is_compare and ((score is not None and score < 0.4) or not str(reason or "").strip()):
        return True
    return False


def _fallback_hard_contract_cover_candidate_index(
    candidates: list[dict[str, Any]],
    *,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> int:
    contract = _build_cover_source_selection_contract(content_profile=content_profile, packaging=packaging)
    is_compare = "同框" in contract or "版本差异" in contract
    midpoint = (len(candidates) - 1) / 2 if candidates else 0.0
    ranked: list[tuple[float, int]] = []
    for idx, candidate in enumerate(candidates):
        subtitle_risk = float(candidate.get("subtitle_overlay_risk") or 0.0)
        center_penalty = abs(idx - midpoint) / max(1.0, len(candidates) / 2)
        compare_bonus = -0.08 if is_compare and idx >= max(1, len(candidates) // 3) else 0.0
        ranked.append((subtitle_risk + center_penalty + compare_bonus, idx))
    ranked.sort()
    return int(ranked[0][1]) if ranked else 0


async def _select_cover_source_finalist_numbers(
    *,
    candidates: list[dict[str, Any]],
    preview_paths: list[Path],
    profile_text: str,
    selection_contract: str,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
    attempt: int,
    chunk_size: int,
    contact_sheet_output_path: Path | None,
) -> list[int]:
    shortlist_target = _resolve_cover_source_shortlist_target_count(len(candidates))
    if len(candidates) <= shortlist_target:
        return list(range(1, len(candidates) + 1))
    if len(candidates) <= chunk_size:
        sheet_path = _build_numbered_highlight_contact_sheet(
            preview_paths,
            output_path=contact_sheet_output_path,
        )
        return await _select_cover_source_shortlist_numbers_from_sheet(
            sheet_path=sheet_path,
            original_numbers=list(range(1, len(candidates) + 1)),
            profile_text=profile_text,
            selection_contract=selection_contract,
            attempt=attempt,
            chunk_index=None,
            finalist_limit=shortlist_target,
            fallback_numbers=_fallback_hard_contract_cover_candidate_numbers(
                candidates,
                finalist_limit=shortlist_target,
                content_profile=content_profile,
                packaging=packaging,
            ),
        )
    chunk_winners: list[int] = []
    for chunk_index, chunk in enumerate(_chunk_cover_source_candidates(candidates, chunk_size=chunk_size), start=1):
        if len(chunk) <= shortlist_target:
            chunk_winners.extend(candidates.index(item) + 1 for item in chunk)
            continue
        chunk_preview_paths = [Path(item["preview"]) for item in chunk if item.get("preview")]
        if not chunk_preview_paths:
            continue
        chunk_sheet_path = _build_numbered_highlight_contact_sheet(
            chunk_preview_paths,
            output_path=_resolve_cover_source_chunk_sheet_output_path(contact_sheet_output_path, chunk_index=chunk_index),
        )
        original_numbers = [candidates.index(item) + 1 for item in chunk]
        shortlist = await _select_cover_source_shortlist_numbers_from_sheet(
            sheet_path=chunk_sheet_path,
            original_numbers=original_numbers,
            profile_text=profile_text,
            selection_contract=selection_contract,
            attempt=attempt,
            chunk_index=chunk_index,
            finalist_limit=shortlist_target,
            fallback_numbers=_fallback_hard_contract_cover_candidate_numbers(
                chunk,
                finalist_limit=shortlist_target,
                content_profile=content_profile,
                packaging=packaging,
            ),
        )
        chunk_winners.extend(shortlist)
    return chunk_winners


def _chunk_cover_source_candidates(candidates: list[dict[str, Any]], *, chunk_size: int) -> list[list[dict[str, Any]]]:
    safe_chunk_size = max(4, int(chunk_size or 4))
    return [candidates[index:index + safe_chunk_size] for index in range(0, len(candidates), safe_chunk_size)]


def _resolve_cover_source_selection_chunk_size(candidate_count: int) -> int:
    if candidate_count <= 4:
        return 4
    return 9


def _resolve_cover_source_shortlist_target_count(candidate_count: int) -> int:
    if candidate_count <= 4:
        return candidate_count
    return 4


def _resolve_cover_source_multimodal_timeout(stage: str) -> int:
    normalized = str(stage or "").strip().lower()
    if normalized == "shortlist":
        return 45
    if normalized == "final_rank":
        return 45
    if normalized == "full_frame_review":
        return 60
    if normalized == "correction":
        return 45
    return 30


def _resolve_cover_source_full_frame_review_numbers(
    *,
    ranked_numbers: list[int],
    finalist_numbers: list[int],
) -> list[int]:
    ordered: list[int] = []
    for number in list(ranked_numbers or []) + list(finalist_numbers or []):
        try:
            normalized = int(number)
        except Exception:
            continue
        if normalized <= 0 or normalized in ordered:
            continue
        ordered.append(normalized)
    return ordered[: max(1, min(4, len(ordered)))]


async def _reselect_cover_source_from_full_frame_review(
    *,
    final_candidates: list[dict[str, Any]],
    finalist_numbers: list[int],
    ranked_numbers: list[int],
    final_sheet_path: Path,
    profile_text: str,
    selection_contract: str,
) -> dict[str, Any] | None:
    review_numbers = _resolve_cover_source_full_frame_review_numbers(
        ranked_numbers=ranked_numbers,
        finalist_numbers=finalist_numbers,
    )
    if len(review_numbers) <= 1:
        return None
    number_to_candidate = {
        int(number): candidate
        for number, candidate in zip(finalist_numbers, final_candidates, strict=False)
    }
    review_candidates = [
        number_to_candidate[number]
        for number in review_numbers
        if number in number_to_candidate
    ]
    review_paths = [Path(candidate["preview"]) for candidate in review_candidates if candidate.get("preview")]
    if len(review_paths) != len(review_candidates):
        return None
    review_prompt = (
        "你正在做封面底图最终终判。"
        "第 1 张图是编号总览，后面的图片是候选原图，按顺序对应这些编号："
        f"{review_numbers}。"
        "请不要只看缩略图，要结合后面的原图判断主角度是否完整、是否展开态、主体是否被遮挡、两件主体是否都清晰。"
        "优先：主体完整、展开态、结构清晰、少字幕遮挡、版本差异一眼可见。"
        "不要选：闭合态、侧边态、主体被截断、字幕污染明显、对比关系不直观的候选。"
        f"\n硬约束：{selection_contract}"
        f"\n视频主题参考：{profile_text}"
        "\n输出 JSON："
        '{"best_original_number":4,"valid_original_numbers":[4,8,9],"ranking_numbers":[4,8,9],"score":0.93,"reason":"4号原图主角度完整、展开态最清晰"}'
    )
    try:
        content = await asyncio.wait_for(
            complete_with_images(
                review_prompt,
                [final_sheet_path, *review_paths],
                max_tokens=220,
                json_mode=True,
                preferred_provider="minimax",
                preferred_model="minimax-m3",
            ),
            timeout=_resolve_cover_source_multimodal_timeout("full_frame_review"),
        )
        data = json.loads(extract_json_text(content))
    except Exception:
        return None
    selected_number = int(data.get("best_original_number", data.get("best_number", 0)) or 0)
    if selected_number not in review_numbers:
        return None
    selected_candidate = number_to_candidate.get(selected_number)
    if selected_candidate is None:
        return None
    ranked_review_numbers = _extract_cover_source_shortlist_numbers(
        data,
        raw_text=content,
        original_numbers=review_numbers,
        finalist_limit=len(review_numbers),
    )
    valid_review_numbers = _extract_cover_source_shortlist_numbers(
        {"valid_original_numbers": data.get("valid_original_numbers")},
        raw_text="",
        original_numbers=review_numbers,
        finalist_limit=len(review_numbers),
    )
    return {
        "index": final_candidates.index(selected_candidate),
        "score": data.get("score"),
        "reason": str(data.get("reason") or "").strip(),
        "review_numbers": review_numbers,
        "ranked_numbers": ranked_review_numbers,
        "valid_numbers": valid_review_numbers,
    }


async def _select_cover_source_shortlist_numbers_from_sheet(
    *,
    sheet_path: Path,
    original_numbers: list[int],
    profile_text: str,
    selection_contract: str,
    attempt: int,
    chunk_index: int | None,
    finalist_limit: int,
    fallback_numbers: list[int],
) -> list[int]:
    stage_label = f"分组 {chunk_index}" if chunk_index is not None else "全局候选"
    prompt = (
        "你正在做封面底图粗筛。"
        "这是一张四宫格或九宫格候选图，请不要只选唯一 1 张，而是保留最值得进入终选的多张候选。"
        "优先看主角度完整展示、展开态、结构清晰、少字幕遮挡、适合后续封面包装。"
        f"\n硬约束：{selection_contract}"
        f"\n当前阶段：{stage_label}"
        f"\n这一组对应原始序号：{original_numbers}"
        f"\n视频主题参考：{profile_text}"
        f"\n这是第 {attempt} 次判断。请最多保留 {max(1, finalist_limit)} 张。"
        "\n输出 JSON："
        '{"finalist_numbers":[4,8,9,10],"reason":"这些候选主体角度完整，适合进入最终四宫格/九宫格定夺"}'
    )
    content = await asyncio.wait_for(
        complete_with_images(
            prompt,
            [sheet_path],
            max_tokens=260,
            json_mode=True,
            preferred_provider="minimax",
            preferred_model="minimax-m3",
        ),
        timeout=_resolve_cover_source_multimodal_timeout("shortlist"),
    )
    data = json.loads(extract_json_text(content))
    shortlist = _extract_cover_source_shortlist_numbers(
        data,
        raw_text=content,
        original_numbers=original_numbers,
        finalist_limit=finalist_limit,
    )
    return shortlist or list(fallback_numbers[: max(1, finalist_limit)])


def _extract_cover_source_shortlist_numbers(
    payload: dict[str, Any],
    *,
    raw_text: str = "",
    original_numbers: list[int],
    finalist_limit: int,
) -> list[int]:
    valid = {int(number) for number in original_numbers if isinstance(number, int)}
    values: list[int] = []
    for key in (
        "valid_original_numbers",
        "valid_numbers",
        "ranking_numbers",
        "ordered_numbers",
        "finalist_numbers",
        "best_numbers",
        "numbers",
        "shortlist_numbers",
    ):
        raw = payload.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            try:
                value = int(item)
            except Exception:
                continue
            if value in valid and value not in values:
                values.append(value)
    if not values:
        for key in ("best_number", "number"):
            try:
                value = int(payload.get(key) or 0)
            except Exception:
                value = 0
            if value in valid and value not in values:
                values.append(value)
                break
    if not values and raw_text:
        for match in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", str(raw_text or "")):
            try:
                value = int(match)
            except Exception:
                continue
            if value in valid and value not in values:
                values.append(value)
    safe_limit = max(1, int(finalist_limit or 1))
    return values[:safe_limit]


def _select_first_valid_cover_candidate_from_ranked_numbers(
    *,
    final_candidates: list[dict[str, Any]],
    finalist_numbers: list[int],
    ranked_numbers: list[int],
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> dict[str, Any] | None:
    if not final_candidates or not finalist_numbers or not ranked_numbers:
        return None
    candidate_by_number: dict[int, dict[str, Any]] = {}
    for number, candidate in zip(finalist_numbers, final_candidates, strict=False):
        candidate_by_number[int(number)] = candidate
    for number in ranked_numbers:
        candidate = candidate_by_number.get(int(number))
        if candidate is None:
            continue
        if _selection_result_violates_hard_contract(
            candidate,
            content_profile=content_profile,
            packaging=packaging,
            score=0.95,
            reason="模型排序备选仍满足硬合同",
        ):
            continue
        return {
            "number": int(number),
            "index": final_candidates.index(candidate),
            "candidate": candidate,
        }
    return None


async def _reselect_cover_source_after_hard_contract_violation(
    *,
    final_candidates: list[dict[str, Any]],
    finalist_numbers: list[int],
    final_sheet_path: Path,
    profile_text: str,
    selection_contract: str,
) -> dict[str, Any] | None:
    if len(final_candidates) <= 1:
        return None
    correction_prompt = (
        "你刚才的封面终选结果没有通过硬合同，请在同一张终选四宫格或九宫格里重新选。"
        "这次不要再选：主体不完整、闭合态、侧边态、字幕污染明显、对比关系不清、版本差异不够直观的候选。"
        "必须优先主角度完整、展开态、结构清晰、后续适合做点击封面包装的候选。"
        f"\n硬约束：{selection_contract}"
        f"\n当前候选对应原始序号：{finalist_numbers}"
        f"\n视频主题参考：{profile_text}"
        "\n输出 JSON："
        "{\"best_number\":2,\"valid_numbers\":[2,4],\"ranking_numbers\":[2,4,1,3],\"score\":0.93,\"reason\":\"这一张主角度完整、展开态更清晰\"}"
    )
    try:
        content = await asyncio.wait_for(
            complete_with_images(
                correction_prompt,
                [final_sheet_path],
                max_tokens=180,
                json_mode=True,
                preferred_provider="minimax",
                preferred_model="minimax-m3",
            ),
            timeout=_resolve_cover_source_multimodal_timeout("correction"),
        )
        data = json.loads(extract_json_text(content))
        if "best_number" in data or "number" in data:
            final_index = int(data.get("best_number", data.get("number", 1)) or 1) - 1
        else:
            final_index = int(data.get("best_index", data.get("index", 0)) or 0)
        ranked_numbers = _extract_cover_source_shortlist_numbers(
            data,
            raw_text=content,
            original_numbers=finalist_numbers,
            finalist_limit=len(finalist_numbers),
        )
        if 0 <= final_index < len(final_candidates):
            return {
                "index": final_index,
                "score": data.get("score"),
                "reason": str(data.get("reason") or "").strip(),
                "ranked_numbers": ranked_numbers,
                "valid_numbers": _extract_cover_source_shortlist_numbers(
                    {"valid_numbers": data.get("valid_numbers")},
                    raw_text="",
                    original_numbers=finalist_numbers,
                    finalist_limit=len(finalist_numbers),
                ),
            }
    except Exception:
        return None
    return None


def _fallback_hard_contract_cover_candidate_numbers(
    candidates: list[dict[str, Any]],
    *,
    finalist_limit: int,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> list[int]:
    contract = _build_cover_source_selection_contract(content_profile=content_profile, packaging=packaging)
    is_compare = "同框" in contract or "版本差异" in contract
    ranked: list[tuple[float, int]] = []
    for idx, candidate in enumerate(candidates):
        subtitle_risk = float(candidate.get("subtitle_overlay_risk") or 0.0)
        trailing_progress = idx / max(1.0, len(candidates) - 1) if len(candidates) > 1 else 0.0
        compare_progress_bonus = (-0.18 * trailing_progress) if is_compare else 0.0
        low_subtitle_bonus = -0.12 if subtitle_risk <= 0.08 else (-0.05 if subtitle_risk <= 0.16 else 0.0)
        high_subtitle_penalty = 0.18 if subtitle_risk >= 0.35 else (0.08 if subtitle_risk >= 0.22 else 0.0)
        ranked.append((subtitle_risk + compare_progress_bonus + low_subtitle_bonus + high_subtitle_penalty, idx))
    ranked.sort()
    safe_limit = max(1, int(finalist_limit or 1))
    return [idx + 1 for _score, idx in ranked[:safe_limit]]


def _resolve_cover_source_chunk_sheet_output_path(base_output_path: Path | None, *, chunk_index: int) -> Path | None:
    if base_output_path is None:
        return None
    return base_output_path.with_name(f"{base_output_path.stem}-chunk-{chunk_index}{base_output_path.suffix}")


def _build_cover_source_selection_contract(
    *,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> str:
    highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
    subject_blob = " ".join(
        part
        for part in (
            str(highlights.get("product") or "").strip(),
            str(content_profile.get("subject_type") or "").strip(),
            str(content_profile.get("video_theme") or "").strip(),
            str(content_profile.get("summary") or "").strip(),
        )
        if part
    ).lower()
    is_edc_blade = any(token in subject_blob for token in ("刀", "刀具", "直跳", "折刀", "edc", "maxace", "美杜莎"))
    is_compare = any(token in subject_blob for token in ("对比", "差异", "区别", "怎么选", "选哪", "取舍", "双版", "顶配", "次顶配", "两款"))
    if is_edc_blade and is_compare:
        return (
            "必须优先选择两件主体同框且都完整清晰可见的帧；优先展开态、主角度完整、版本差异一眼可见、少字幕遮挡。"
            "只出现一把、闭合态、侧边态、主体被截断、底部字幕污染明显或对比关系不明确的帧一律降级。"
        )
    if is_edc_blade:
        return "必须优先选择主体完整展开、主角度清晰、刀身和柄部都完整可见且少字幕遮挡的帧；闭合态、侧边态、只有轮廓态一律降级。"
    return "必须优先选择主体主要角度完整展示、关键结构清晰可见、后续适合做点击封面的帧。"


def _build_numbered_highlight_contact_sheet(preview_paths: list[Path], *, output_path: Path | None = None) -> Path:
    valid_paths = [path for path in preview_paths if path and path.exists()]
    if not valid_paths:
        raise ValueError("No preview frames available for contact sheet")
    sheet_path = output_path or (valid_paths[0].parent / "highlight_candidates_sheet.jpg")
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    columns = _resolve_highlight_contact_sheet_columns(len(valid_paths))
    cell_width, cell_height = _resolve_highlight_contact_sheet_cell_size(len(valid_paths))
    settings = get_settings()
    fontfile = str(getattr(settings, "cover_title_font_path", "") or "").strip()
    font_clause = ""
    if fontfile and Path(fontfile).exists():
        font_clause = f":fontfile='{_escape_ffmpeg_filter_value(fontfile)}'"

    command = ["ffmpeg", "-y"]
    for path in valid_paths:
        command.extend(["-i", str(path)])

    filter_parts: list[str] = []
    labels: list[str] = []
    for index, _path in enumerate(valid_paths):
        label = f"v{index}"
        labels.append(f"[{label}]")
        filter_parts.append(
            (
                f"[{index}:v]"
                f"scale={cell_width}:{cell_height}:force_original_aspect_ratio=decrease,"
                f"pad={cell_width}:{cell_height}:(ow-iw)/2:(oh-ih)/2:color=0x111111,"
                "drawbox=x=0:y=0:w=76:h=54:color=black@0.68:t=fill,"
                f"drawtext=text='{index + 1}'{font_clause}:x=22:y=10:fontsize=34:fontcolor=white,"
                "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.24:t=2"
                f"[{label}]"
            )
        )

    layout_parts = [
        f"{(index % columns) * cell_width}_{(index // columns) * cell_height}"
        for index in range(len(valid_paths))
    ]
    filter_parts.append(
        "".join(labels)
        + f"xstack=inputs={len(valid_paths)}:layout={'|'.join(layout_parts)}:fill=0x111111"
        + ",format=yuvj420p[out]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[out]",
            "-frames:v",
            "1",
            str(sheet_path),
        ]
    )
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=settings.ffmpeg_timeout_sec,
    )
    if result.returncode != 0 or not sheet_path.exists():
        raise RuntimeError(f"候选封面接触表生成失败：{result.stderr[-400:]}")
    return sheet_path


def _resolve_highlight_contact_sheet_columns(candidate_count: int) -> int:
    safe_count = max(1, int(candidate_count or 1))
    if safe_count <= 1:
        return 1
    if safe_count <= 4:
        return 2
    return 3


def _resolve_highlight_contact_sheet_cell_size(candidate_count: int) -> tuple[int, int]:
    safe_count = max(1, int(candidate_count or 1))
    if safe_count <= 4:
        return 520, 520
    if safe_count <= 9:
        return 420, 420
    return 360, 360


def _escape_ffmpeg_filter_value(value: str) -> str:
    return str(value or "").replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def _normalize_score(value: Any, *, fallback: float) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 3)
    except Exception:
        return round(max(0.0, min(1.0, float(fallback))), 3)


def _write_cover_source_manifest(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _materialize_cover_reference_fallback(
    *,
    source_path: Path,
    output_path: Path,
    width: int,
    height: int,
) -> bool:
    try:
        fit_mode = _resolve_cover_canvas_fit_mode(
            source_path=source_path,
            width=width,
            height=height,
        )
        _fit_image_to_canvas(
            source_path=source_path,
            output_path=output_path,
            width=width,
            height=height,
            fit_mode=fit_mode,
        )
        return True
    except Exception:
        shutil.copy2(source_path, output_path)
        return False


async def _render_platform_cover(
    *,
    output_path: Path,
    video_path: Path,
    source_image_path: Path | None,
    existing_cover_path: Path | None,
    title: str,
    platform_key: str,
    rules: dict[str, Any],
    cover_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    target_width, target_height = int(rules["cover_size"][0]), int(rules["cover_size"][1])
    source_kind = "video_highlight"
    image_generation: dict[str, Any] | None = None
    cover_quality: dict[str, Any] | None = None
    blocking_reasons: list[str] = []
    request_path = output_path.with_suffix(".codex-imagegen.json")
    expected_title_lines = _build_cover_title_layout_plan(title=title, cover_brief=cover_brief)
    overlay_cover_style, overlay_title_style = _resolve_overlay_title_style(rules=rules, cover_brief=cover_brief)
    prompt_spec = _build_platform_cover_prompt_spec(
        title=title,
        platform_key=platform_key,
        rules=rules,
        width=target_width,
        height=target_height,
        cover_brief=cover_brief,
    )
    expected_prompt = _build_codex_platform_cover_image_prompt(spec=prompt_spec)
    expected_hard_contract = prompt_spec.get("hard_contract") or {}
    expected_director_policy = prompt_spec.get("director_policy") or {}
    completed_request_payload = _read_cover_request_payload(request_path)
    if (
        str(completed_request_payload.get("status") or "").strip().lower() == "completed"
        and output_path.exists()
        and _cover_request_matches_current_contract(
            completed_request_payload,
            expected_prompt=expected_prompt,
            expected_hard_contract=expected_hard_contract,
            expected_director_policy=expected_director_policy,
        )
    ):
        image_generation = dict(completed_request_payload.get("image_generation") or {})
        image_generation.update(
            {
                "status": "completed",
                "backend": str(image_generation.get("backend") or "codex_builtin"),
                "output_path": str(output_path),
                "request_path": str(request_path),
            }
        )
        if isinstance(completed_request_payload.get("codex_runner"), dict):
            image_generation["codex_runner"] = dict(completed_request_payload["codex_runner"])
        _fit_existing_image_to_canvas(
            output_path=output_path,
            width=target_width,
            height=target_height,
            fit_mode=_resolve_cover_canvas_fit_mode(
                source_path=output_path,
                width=target_width,
                height=target_height,
            ),
        )
        completed_request_payload = await _ensure_generated_cover_title_contract_ready(
            request_path=request_path,
            request_payload=completed_request_payload,
            output_path=output_path,
            title=title,
            title_lines=expected_title_lines,
            rules=rules,
            cover_brief=cover_brief,
            source_kind="image_generation",
            image_generation=image_generation,
        )
        if isinstance(completed_request_payload, dict):
            completed_request_payload["post_title_overlay_group_style"] = str(overlay_cover_style or "").strip()
            completed_request_payload["post_title_overlay_title_style"] = str(overlay_title_style or "").strip()
            if request_path.exists():
                try:
                    request_path.write_text(json.dumps(completed_request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
        cover_assessment = assess_cover_publish_readiness(
            image_generation,
            completed_request_payload,
            output_path,
        )
        return {
            "source": "image_generation",
            "platform": str(platform_key or "").strip(),
            "target_size": {"width": target_width, "height": target_height},
            "publish_ready": bool(cover_assessment.get("publish_ready")),
            "blocking_reasons": list(cover_assessment.get("blocking_reasons") or []),
            "warnings": list(cover_assessment.get("warnings") or []),
            "image_generation": image_generation,
            "cover_quality": cover_assessment,
        }
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        base_image = tmpdir_path / "base.jpg"
        if source_image_path is not None and source_image_path.exists():
            shutil.copy2(source_image_path, base_image)
        elif existing_cover_path is not None and existing_cover_path.exists():
            shutil.copy2(existing_cover_path, base_image)
            source_kind = "existing_cover_reference"
        else:
            return {
                "source": "missing_source",
                "platform": str(platform_key or "").strip(),
                "target_size": {"width": target_width, "height": target_height},
                "publish_ready": False,
                "blocking_reasons": ["封面缺少可编辑参考帧，已停止生成"],
                "image_generation": None,
            }
        generation_reference = base_image
        if bool(expected_hard_contract.get("compare_subject_pair_required")) and target_height > target_width:
            prepared_reference = tmpdir_path / "prepared-reference.jpg"
            _fit_image_to_canvas(
                source_path=base_image,
                output_path=prepared_reference,
                width=target_width,
                height=target_height,
                fit_mode="blur_fill",
            )
            generation_reference = prepared_reference
        generated_image = tmpdir_path / "generated.jpg"
        if not _should_generate_intelligent_copy_cover_image(source_kind):
            return {
                "source": source_kind,
                "platform": str(platform_key or "").strip(),
                "target_size": {"width": target_width, "height": target_height},
                "publish_ready": False,
                "blocking_reasons": ["封面图像生成未启用，正式物料不可发布"],
                "image_generation": None,
            }
        if _should_generate_intelligent_copy_cover_image(source_kind):
            last_error = ""
            fallback_warning = ""
            fallback_overlay_safe = False
            max_attempts = _resolve_intelligent_copy_cover_generation_attempts()
            for attempt in range(1, max_attempts + 1):
                try:
                    image_generation = await generate_edited_cover_image(
                        source_image_path=generation_reference,
                        output_path=generated_image,
                        request_path=request_path,
                        final_output_path=output_path,
                    prompt=expected_prompt,
                    width=target_width,
                    height=target_height,
                    hard_contract=expected_hard_contract,
                    director_policy=expected_director_policy,
                )
                    image_generation["attempts"] = attempt
                    source_kind = "image_generation"
                    break
                except CodexImageGenerationPending as exc:
                    image_generation = dict(exc.metadata)
                    image_generation["attempts"] = attempt
                    fallback_overlay_safe = _materialize_cover_reference_fallback(
                        source_path=base_image,
                        output_path=output_path,
                        width=target_width,
                        height=target_height,
                    )
                    fallback_warning = "封面等待 Codex 内置 imagegen 执行完成，已回退使用参考帧封面"
                    source_kind = "reference_cover_fallback"
                    break
                except Exception as exc:
                    last_error = str(exc)
            if source_kind != "image_generation":
                if last_error:
                    fallback_overlay_safe = _materialize_cover_reference_fallback(
                        source_path=base_image,
                        output_path=output_path,
                        width=target_width,
                        height=target_height,
                    )
                    fallback_warning = f"封面图像生成失败，已回退使用参考帧封面：{last_error}"
                    source_kind = "reference_cover_fallback"
                if source_kind != "image_generation" and not output_path.exists():
                    return {
                        "source": source_kind,
                        "platform": str(platform_key or "").strip(),
                        "target_size": {"width": target_width, "height": target_height},
                        "publish_ready": False,
                        "blocking_reasons": blocking_reasons or ["封面图像生成未完成"],
                        "image_generation": image_generation,
                    }
        if not generated_image.exists() and not output_path.exists():
            return {
                "source": source_kind,
                "platform": str(platform_key or "").strip(),
                "target_size": {"width": target_width, "height": target_height},
                "publish_ready": False,
                "blocking_reasons": ["封面图像生成没有返回图片文件"],
                "image_generation": image_generation,
            }
        if generated_image.exists():
            _fit_image_to_canvas(
                source_path=generated_image,
                output_path=output_path,
                width=target_width,
                height=target_height,
                fit_mode=_resolve_cover_canvas_fit_mode(
                    source_path=generated_image,
                    width=target_width,
                    height=target_height,
                ),
            )
            pre_overlay_output_path = output_path.with_name(f"{output_path.stem}.pre-overlay{output_path.suffix}")
            try:
                shutil.copy2(output_path, pre_overlay_output_path)
            except Exception:
                pre_overlay_output_path = None
        elif output_path.exists():
            _fit_existing_image_to_canvas(
                output_path=output_path,
                width=target_width,
                height=target_height,
                fit_mode=_resolve_cover_canvas_fit_mode(
                    source_path=output_path,
                    width=target_width,
                    height=target_height,
                ),
            )
            pre_overlay_output_path = output_path.with_name(f"{output_path.stem}.pre-overlay{output_path.suffix}")
            try:
                shutil.copy2(output_path, pre_overlay_output_path)
            except Exception:
                pre_overlay_output_path = None
        else:
            pre_overlay_output_path = None
        request_payload = _read_cover_request_payload(request_path) if request_path.exists() else {}
        if isinstance(request_payload, dict) and pre_overlay_output_path is not None:
            request_payload["pre_overlay_output_path"] = str(pre_overlay_output_path)
            if request_path.exists():
                try:
                    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
        request_payload = await _ensure_generated_cover_title_contract_ready(
            request_path=request_path,
            request_payload=request_payload,
            output_path=output_path,
            title=title,
            title_lines=expected_title_lines,
            rules=rules,
            cover_brief=cover_brief,
            source_kind=source_kind,
            image_generation=image_generation,
            allow_overlay=(source_kind != "reference_cover_fallback" or fallback_overlay_safe),
        )
        if isinstance(request_payload, dict):
            request_payload["post_title_overlay_group_style"] = str(overlay_cover_style or "").strip()
            request_payload["post_title_overlay_title_style"] = str(overlay_title_style or "").strip()
            if request_path.exists():
                try:
                    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception:
                    pass
        if isinstance(image_generation, dict) and str(image_generation.get("backend") or "") == "codex_builtin":
            cover_assessment = assess_cover_publish_readiness(
                image_generation,
                request_payload,
                output_path,
            )
            cover_quality = cover_assessment
            if not bool(cover_assessment.get("publish_ready")):
                return {
                    "source": source_kind,
                    "platform": str(platform_key or "").strip(),
                    "target_size": {"width": target_width, "height": target_height},
                    "publish_ready": False,
                    "blocking_reasons": list(cover_assessment.get("blocking_reasons") or []),
                    "warnings": list(cover_assessment.get("warnings") or []),
                    "image_generation": image_generation,
                    "cover_quality": cover_assessment,
                }
        if source_kind == "reference_cover_fallback" and fallback_warning:
            blocking_reasons = ["封面包装生图未完成，当前仅生成了参考帧占位封面"]
            warnings = [fallback_warning]
        else:
            warnings = []
    return {
        "source": source_kind,
        "platform": str(platform_key or "").strip(),
        "target_size": {"width": target_width, "height": target_height},
        "publish_ready": output_path.exists() and not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "image_generation": image_generation,
        "cover_quality": cover_quality,
    }


async def _apply_platform_cover_title_overlay(
    *,
    output_path: Path,
    title: str,
    rules: dict[str, Any],
    cover_brief: dict[str, Any] | None = None,
) -> None:
    title_lines = _build_cover_title_layout_plan(title=title, cover_brief=cover_brief)
    if not title_lines or not output_path.exists():
        return
    cover_style, title_style = _resolve_overlay_title_style(rules=rules, cover_brief=cover_brief)
    await _overlay_title_layout(
        output_path,
        title_lines,
        cover_style,
        title_style,
    )


def _should_apply_generated_cover_title_overlay(
    *,
    source_kind: str,
    image_generation: dict[str, Any] | None,
) -> bool:
    return True


def _resolve_overlay_title_style(*, rules: dict[str, Any], cover_brief: dict[str, Any] | None = None) -> tuple[str, str]:
    style_key = _resolve_cover_image_style_key(rules=rules, cover_brief=cover_brief if isinstance(cover_brief, dict) else {})
    cover_style = str(style_key or rules.get("cover_style") or "tech_showcase")
    title_style = str(rules.get("title_style") or "preset_default")
    if cover_style == OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO:
        title_style = "account_metal_cyber_stack"
    return cover_style, title_style


def _read_cover_request_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_cover_title_overlay_contract(
    *,
    title_lines: dict[str, str] | None,
    cover_style: str,
    title_style: str,
) -> dict[str, Any]:
    normalized_title_lines = {
        key: str((title_lines or {}).get(key) or "").strip()
        for key in ("brand", "top", "main", "sub", "bottom", "hook")
        if str((title_lines or {}).get(key) or "").strip()
    }
    return {
        "cover_style": str(cover_style or "").strip(),
        "title_style": str(title_style or "").strip(),
        "title_lines": normalized_title_lines,
        "style_tokens": _title_style_tokens(
            str(title_style or "").strip() or "preset_default",
            title_lines=normalized_title_lines,
            cover_style=str(cover_style or "").strip(),
        ),
    }


def _cover_request_matches_current_contract(
    request_payload: dict[str, Any],
    *,
    expected_prompt: str,
    expected_hard_contract: dict[str, Any],
    expected_director_policy: dict[str, Any] | None = None,
) -> bool:
    if not isinstance(request_payload, dict):
        return False
    if str(request_payload.get("prompt") or "") != str(expected_prompt or ""):
        return False
    recorded_hard_contract = request_payload.get("cover_hard_contract")
    if not isinstance(recorded_hard_contract, dict):
        return False
    if recorded_hard_contract != dict(expected_hard_contract or {}):
        return False
    if expected_director_policy is not None:
        recorded_director_policy = request_payload.get("cover_director_policy")
        if not isinstance(recorded_director_policy, dict):
            return False
        if recorded_director_policy != dict(expected_director_policy or {}):
            return False
    return True


def _cover_bitmap_title_contract_already_verified(
    request_payload: dict[str, Any],
    *,
    title_lines: dict[str, str] | None,
) -> bool:
    if not isinstance(request_payload, dict) or not bool(request_payload.get("bitmap_title_contract_passed")):
        return False
    expected = title_lines or {}
    actual = request_payload.get("bitmap_title_lines") if isinstance(request_payload.get("bitmap_title_lines"), dict) else {}
    for key in ("brand", "top", "main", "sub", "bottom", "hook"):
        expected_value = str(expected.get(key) or "").strip()
        actual_value = str(actual.get(key) or "").strip()
        if expected_value and actual_value != expected_value:
            return False
    return True


def _cover_title_overlay_already_applied(
    request_payload: dict[str, Any],
    *,
    title: str,
    title_lines: dict[str, str] | None,
    cover_style: str,
    title_style: str,
) -> bool:
    if not isinstance(request_payload, dict):
        return False
    if not bool(request_payload.get("post_title_overlay_applied")):
        return False
    recorded_title = str(request_payload.get("post_title_overlay_title") or "").strip()
    if recorded_title and recorded_title != str(title or "").strip():
        return False
    recorded_lines = request_payload.get("post_title_overlay_lines") if isinstance(request_payload.get("post_title_overlay_lines"), dict) else {}
    expected_lines = title_lines or {}
    for key in ("brand", "top", "main", "sub", "bottom", "hook"):
        expected = str(expected_lines.get(key) or "").strip()
        actual = str(recorded_lines.get(key) or "").strip()
        if expected and expected != actual:
            return False
    expected_contract = _build_cover_title_overlay_contract(
        title_lines=title_lines,
        cover_style=cover_style,
        title_style=title_style,
    )
    recorded_contract = request_payload.get("post_title_overlay_contract")
    if isinstance(recorded_contract, dict):
        return recorded_contract == expected_contract
    recorded_cover_style = str(request_payload.get("post_title_overlay_group_style") or "").strip()
    recorded_title_style = str(request_payload.get("post_title_overlay_title_style") or "").strip()
    if str(cover_style or "").strip() and recorded_cover_style != str(cover_style or "").strip():
        return False
    if str(title_style or "").strip() and recorded_title_style != str(title_style or "").strip():
        return False
    return False


def _mark_cover_title_overlay_applied(
    request_path: Path,
    *,
    title: str,
    title_lines: dict[str, str] | None,
    cover_style: str,
    title_style: str,
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["post_title_overlay_applied"] = True
    payload["post_title_overlay_title"] = str(title or "").strip()
    payload["post_title_overlay_lines"] = dict(title_lines or {})
    payload["post_title_overlay_group_style"] = str(cover_style or "").strip()
    payload["post_title_overlay_title_style"] = str(title_style or "").strip()
    payload["post_title_overlay_contract"] = _build_cover_title_overlay_contract(
        title_lines=title_lines,
        cover_style=cover_style,
        title_style=title_style,
    )
    payload["post_title_overlay_applied_at"] = datetime.now().isoformat()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_cover_bitmap_title_contract_verified(
    request_path: Path,
    *,
    title_lines: dict[str, str] | None,
    verification: dict[str, Any],
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["bitmap_title_contract_passed"] = bool(verification.get("bitmap_title_contract_passed"))
    payload["bitmap_title_lines"] = dict(title_lines or {})
    payload["bitmap_title_detected"] = {
        "main": str(verification.get("detected_main_title") or "").strip(),
        "bottom": str(verification.get("detected_subtitle") or "").strip(),
    }
    payload["bitmap_title_style_verified"] = bool(verification.get("style_consistent"))
    payload["bitmap_title_contract_reason"] = str(verification.get("reason") or "").strip()
    payload["bitmap_title_contract_verified_at"] = datetime.now().isoformat()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_cover_unexpected_bitmap_text_verdict(
    request_path: Path,
    *,
    verification: dict[str, Any],
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["bitmap_unexpected_text_detected"] = bool(verification.get("unexpected_bitmap_text_detected"))
    payload["bitmap_unexpected_text_detected_lines"] = list(verification.get("detected_text") or [])
    payload["bitmap_unexpected_text_reason"] = str(verification.get("reason") or "").strip()
    payload["bitmap_unexpected_text_checked_at"] = datetime.now().isoformat()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_cover_unexpected_bitmap_text_verification_unavailable(
    request_path: Path,
    *,
    reason: str,
    debug_error: str = "",
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["bitmap_unexpected_text_detected"] = None
    payload["bitmap_unexpected_text_detected_lines"] = []
    payload["bitmap_unexpected_text_reason"] = str(reason or "").strip()
    payload["bitmap_unexpected_text_checked_at"] = datetime.now().isoformat()
    payload["bitmap_unexpected_text_check_unavailable"] = True
    payload["bitmap_unexpected_text_verification_debug"] = str(debug_error or "").strip()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_cover_compare_subject_contract_verified(
    request_path: Path,
    *,
    verification: dict[str, Any],
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["compare_subject_contract_passed"] = bool(verification.get("compare_subject_contract_passed"))
    payload["compare_subject_contract_reason"] = str(verification.get("reason") or "").strip()
    payload["compare_subject_contract_checked_at"] = datetime.now().isoformat()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _mark_cover_compare_subject_contract_verification_unavailable(
    request_path: Path,
    *,
    reason: str,
    debug_error: str = "",
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    payload["compare_subject_contract_passed"] = None
    payload["compare_subject_contract_reason"] = str(reason or "").strip()
    payload["compare_subject_contract_checked_at"] = datetime.now().isoformat()
    payload["compare_subject_contract_check_unavailable"] = True
    payload["compare_subject_contract_verification_debug"] = str(debug_error or "").strip()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _resolve_cover_verification_bitmap_path(
    *,
    request_payload: dict[str, Any] | None,
    output_path: Path,
) -> Path:
    payload = request_payload if isinstance(request_payload, dict) else {}
    candidate = str(payload.get("pre_overlay_output_path") or "").strip()
    if candidate:
        candidate_path = Path(candidate).expanduser()
        try:
            if candidate_path.exists():
                return candidate_path
        except OSError:
            pass
    return output_path


async def _run_cover_visual_json_verification(
    *,
    prompt: str,
    output_path: Path,
    max_tokens: int,
    timeout_sec: float = 30.0,
    attempts: int = 2,
) -> tuple[dict[str, Any], str]:
    last_error = ""
    for _ in range(max(1, int(attempts or 1))):
        try:
            content = await asyncio.wait_for(
                complete_with_images(
                    prompt,
                    [output_path],
                    max_tokens=max_tokens,
                    json_mode=True,
                    preferred_provider="minimax",
                    preferred_model="minimax-m3",
                ),
                timeout=timeout_sec,
            )
            data = json.loads(extract_json_text(content))
            if isinstance(data, dict):
                return data, ""
            last_error = "non_dict_json_response"
        except Exception as exc:
            error_name = exc.__class__.__name__ or "Exception"
            error_message = str(exc).strip()
            last_error = error_name if not error_message else f"{error_name}: {error_message}"
    return {}, last_error


async def _verify_generated_cover_has_unexpected_bitmap_text(
    *,
    output_path: Path,
) -> dict[str, Any]:
    if not output_path.exists():
        return {}
    prompt = (
        "请判断这张视频封面位图里是否已经出现了任何不应该存在的可读文字。"
        "这里的“不应该存在”包括：标题、品牌字、型号字、配置字、字幕、水印、logo 字牌、口号、海报字效、伪文字。"
        "只判断当前位图已经画出来的内容，不要假设后期会补字。"
        "如果画面里有明显可读或半可读的大字/字牌/伪标题，就判定为 unexpected_bitmap_text_detected=true。"
        "\n输出 JSON："
        '{"unexpected_bitmap_text_detected":true,"detected_text":["巅峰之作"],"reason":"画面顶部存在额外大字字牌，不属于后期安全区预留"}'
    )
    data, error = await _run_cover_visual_json_verification(
        prompt=prompt,
        output_path=output_path,
        max_tokens=220,
    )
    if not data:
        return {}
    detected_text = data.get("detected_text")
    if not isinstance(detected_text, list):
        detected_text = []
    return {
        "unexpected_bitmap_text_detected": bool(data.get("unexpected_bitmap_text_detected")),
        "detected_text": [str(item).strip() for item in detected_text if str(item).strip()],
        "reason": str(data.get("reason") or "").strip(),
    }


async def _verify_generated_cover_compare_subject_contract(
    *,
    output_path: Path,
) -> dict[str, Any]:
    if not output_path.exists():
        return {}
    prompt = (
        "请判断这张对比类视频封面是否满足双主体完整展示硬合同。"
        "这里的主体只指两件产品本身，不要求双手完整入镜；手部可以局部出框，但产品本体必须完整可辨。"
        "要求：两件主体都要清晰同框、主角度完整、展开态清楚、不能只剩局部特写，也不能把第二件弱化到看不清。"
        "重点看产品本体是否完整：刀尖、刀身、柄部、柄尾是否都还在画面里并且可辨。"
        "如果两件主体没有同时完整可辨、被严重裁切、或对比关系不直观，就判定 compare_subject_contract_passed=false。"
        "\n输出 JSON："
        '{"compare_subject_contract_passed":false,"reason":"竖版构图过近，第二件主体只剩局部，对比关系不完整"}'
    )
    data, error = await _run_cover_visual_json_verification(
        prompt=prompt,
        output_path=output_path,
        max_tokens=180,
    )
    if not data:
        return {}
    return {
        "compare_subject_contract_passed": bool(data.get("compare_subject_contract_passed")),
        "reason": str(data.get("reason") or "").strip(),
    }


async def _verify_generated_cover_bitmap_title_contract(
    *,
    output_path: Path,
    title_lines: dict[str, str] | None,
) -> dict[str, Any]:
    lines = title_lines or {}
    required_main = str(lines.get("main") or "").strip()
    required_bottom = str(lines.get("bottom") or "").strip()
    if not output_path.exists() or (not required_main and not required_bottom):
        return {}
    prompt = (
        "请校验这张视频封面位图里已经直接渲染出来的标题是否满足硬合同。"
        f"\n要求主标题精确包含：{required_main or '无'}"
        f"\n要求副标题精确包含：{required_bottom or '无'}"
        "\n只判断画面里已经出现的位图文字，不要推测后期会再补什么。"
        "\n如果主标题和副标题都已明确、无明显错字漂移、风格统一，就判通过。"
        "\n输出 JSON："
        '{"bitmap_title_contract_passed":true,"main_title_matches":true,"subtitle_matches":true,"style_consistent":true,"detected_main_title":"MAXACE美杜莎4","detected_subtitle":"顶配vs次顶配","reason":"位图内标题完整且稳定"}'
    )
    try:
        content = await asyncio.wait_for(
            complete_with_images(
                prompt,
                [output_path],
                max_tokens=220,
                json_mode=True,
                preferred_provider="minimax",
                preferred_model="minimax-m3",
            ),
            timeout=12,
        )
        data = json.loads(extract_json_text(content))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        "bitmap_title_contract_passed": bool(data.get("bitmap_title_contract_passed")),
        "main_title_matches": bool(data.get("main_title_matches")),
        "subtitle_matches": bool(data.get("subtitle_matches")),
        "style_consistent": bool(data.get("style_consistent")),
        "detected_main_title": str(data.get("detected_main_title") or "").strip(),
        "detected_subtitle": str(data.get("detected_subtitle") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
    }


async def _ensure_generated_cover_title_contract_ready(
    *,
    request_path: Path,
    request_payload: dict[str, Any],
    output_path: Path,
    title: str,
    title_lines: dict[str, str] | None,
    rules: dict[str, Any],
    cover_brief: dict[str, Any] | None,
    source_kind: str,
    image_generation: dict[str, Any] | None,
    allow_overlay: bool = True,
) -> dict[str, Any]:
    payload = dict(request_payload or {})
    overlay_cover_style, overlay_title_style = _resolve_overlay_title_style(rules=rules, cover_brief=cover_brief)
    typography_owner = str(
        ((payload.get("cover_director_policy") or {}) if isinstance(payload.get("cover_director_policy"), dict) else {}).get("typography_owner")
        or ""
    ).strip().lower()
    local_overlay_required = typography_owner == "local_post_overlay"
    full_cover_typography_required = typography_owner in {"codex_full_cover", "bitmap_full_cover", "imagegen_full_cover"}
    verification_output_path = _resolve_cover_verification_bitmap_path(
        request_payload=payload,
        output_path=output_path,
    )
    if output_path.exists() and not local_overlay_required and _cover_bitmap_title_contract_already_verified(payload, title_lines=title_lines):
        return payload
    if output_path.exists() and isinstance(image_generation, dict) and str(image_generation.get("backend") or "").strip() == "codex_builtin":
        if local_overlay_required:
            unexpected_text_verification = await _verify_generated_cover_has_unexpected_bitmap_text(
                output_path=verification_output_path,
            )
            if unexpected_text_verification:
                if request_path.exists():
                    _mark_cover_unexpected_bitmap_text_verdict(
                        request_path,
                        verification=unexpected_text_verification,
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["bitmap_unexpected_text_detected"] = bool(
                        unexpected_text_verification.get("unexpected_bitmap_text_detected")
                    )
                    payload["bitmap_unexpected_text_detected_lines"] = list(
                        unexpected_text_verification.get("detected_text") or []
                    )
                    payload["bitmap_unexpected_text_reason"] = str(
                        unexpected_text_verification.get("reason") or ""
                    ).strip()
                if bool(unexpected_text_verification.get("unexpected_bitmap_text_detected")):
                    return payload
            else:
                reason = "unexpected_bitmap_text_verification_unavailable"
                if request_path.exists():
                    _mark_cover_unexpected_bitmap_text_verification_unavailable(
                        request_path,
                        reason=reason,
                        debug_error=str(payload.get("bitmap_unexpected_text_verification_debug") or ""),
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["bitmap_unexpected_text_detected"] = None
                    payload["bitmap_unexpected_text_detected_lines"] = []
                    payload["bitmap_unexpected_text_reason"] = reason
                    payload["bitmap_unexpected_text_checked_at"] = datetime.now().isoformat()
                    payload["bitmap_unexpected_text_check_unavailable"] = True
                    payload["bitmap_unexpected_text_verification_debug"] = ""
        hard_contract = payload.get("cover_hard_contract") if isinstance(payload.get("cover_hard_contract"), dict) else {}
        if bool(hard_contract.get("compare_subject_pair_required")):
            compare_subject_verification = await _verify_generated_cover_compare_subject_contract(
                output_path=verification_output_path,
            )
            if compare_subject_verification:
                if request_path.exists():
                    _mark_cover_compare_subject_contract_verified(
                        request_path,
                        verification=compare_subject_verification,
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["compare_subject_contract_passed"] = bool(
                        compare_subject_verification.get("compare_subject_contract_passed")
                    )
                    payload["compare_subject_contract_reason"] = str(
                        compare_subject_verification.get("reason") or ""
                    ).strip()
                if not bool(compare_subject_verification.get("compare_subject_contract_passed")):
                    return payload
            else:
                reason = "compare_subject_contract_verification_unavailable"
                if request_path.exists():
                    _mark_cover_compare_subject_contract_verification_unavailable(
                        request_path,
                        reason=reason,
                        debug_error=str(payload.get("compare_subject_contract_verification_debug") or ""),
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["compare_subject_contract_passed"] = None
                    payload["compare_subject_contract_reason"] = reason
                    payload["compare_subject_contract_checked_at"] = datetime.now().isoformat()
                    payload["compare_subject_contract_check_unavailable"] = True
                    payload["compare_subject_contract_verification_debug"] = ""
        verification = await _verify_generated_cover_bitmap_title_contract(
            output_path=output_path,
            title_lines=title_lines,
        )
        if bool(verification.get("bitmap_title_contract_passed")):
            if request_path.exists():
                _mark_cover_bitmap_title_contract_verified(
                    request_path,
                    title_lines=title_lines,
                    verification=verification,
                )
                payload = _read_cover_request_payload(request_path)
            else:
                payload["bitmap_title_contract_passed"] = True
                payload["bitmap_title_lines"] = dict(title_lines or {})
        elif full_cover_typography_required:
            return payload
    if local_overlay_required and allow_overlay and _should_apply_generated_cover_title_overlay(source_kind=source_kind, image_generation=image_generation) and not _cover_title_overlay_already_applied(
        payload,
        title=title,
        title_lines=title_lines,
        cover_style=overlay_cover_style,
        title_style=overlay_title_style,
    ):
        await _apply_platform_cover_title_overlay(
            output_path=output_path,
            title=title,
            rules=rules,
            cover_brief=cover_brief,
        )
        if request_path.exists():
            _mark_cover_title_overlay_applied(
                request_path,
                title=title,
                title_lines=title_lines,
                cover_style=overlay_cover_style,
                title_style=overlay_title_style,
            )
            return _read_cover_request_payload(request_path)
        payload["post_title_overlay_applied"] = True
        payload["post_title_overlay_lines"] = dict(title_lines or {})
        payload["post_title_overlay_group_style"] = str(overlay_cover_style or "").strip()
        payload["post_title_overlay_title_style"] = str(overlay_title_style or "").strip()
    return payload


def _should_generate_intelligent_copy_cover_image(source_kind: str) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "intelligent_copy_cover_image_generation_enabled", True)):
        return False
    return str(source_kind or "").strip() in {"video_highlight", "existing_cover_reference"}


def _resolve_intelligent_copy_cover_generation_attempts() -> int:
    settings = get_settings()
    return max(1, int(getattr(settings, "intelligent_copy_cover_codex_max_attempts", 1) or 1))


def _build_platform_cover_image_prompt(
    *,
    title: str,
    platform_key: str,
    rules: dict[str, Any],
    width: int,
    height: int,
    cover_brief: dict[str, Any] | None = None,
) -> str:
    settings = get_settings()
    backend = str(getattr(settings, "intelligent_copy_cover_image_backend", "") or "codex_builtin").strip().lower()
    spec = _build_platform_cover_prompt_spec(
        title=title,
        platform_key=platform_key,
        rules=rules,
        width=width,
        height=height,
        cover_brief=cover_brief,
    )
    if backend in {"", "codex", "codex_cli", "codex_imagegen", "codex_builtin"}:
        return _build_codex_platform_cover_image_prompt(spec=spec)
    return _build_provider_safe_cover_image_prompt(spec=spec)


def _build_codex_platform_cover_image_prompt(*, spec: dict[str, Any]) -> str:
    style_prompt = str(spec["style_prompt"] or "").strip()
    subject_identity = str(spec["product_identity"] or "").strip() or "参考图中的同一商品"
    selling_angle = str(spec.get("selling_angle") or "").strip()
    visual_brief = str(spec.get("visual_brief") or "").strip()
    video_type = str(spec.get("video_type") or "").strip()
    background_strategy_prompt = _background_strategy_prompt(spec.get("background_strategy") or "")
    critical_detail_notes = list(spec.get("critical_detail_notes") or [])
    hard_contract = spec.get("hard_contract") if isinstance(spec.get("hard_contract"), dict) else {}
    critical_detail_prompt = ""
    if critical_detail_notes:
        critical_detail_prompt = "关键细节硬约束：" + "；".join(critical_detail_notes)
    hard_contract_prompt = (
        "硬合同：必须保持参考图产品主体一致，不允许改刀型、结构、开合状态或主角度；"
        "必须直接产出完整可发布封面位图，不允许把标题留给后期再补；"
        f"同一封面组必须保持统一风格化，统一风格 key={hard_contract.get('unified_style_key') or spec.get('style_key') or ''}。"
    )
    packaging_text_exclusion_instruction = (
        "如果参考图里包含包装盒、卡片、贴纸、说明纸、印刷 logo 或任何可读包装字样，"
        "这些都不能原样保留在最终封面里；可以裁掉、弱化、虚化，或替换成无字环境纹理。"
    )
    required_title_lines = hard_contract.get("required_title_lines") if isinstance(hard_contract.get("required_title_lines"), dict) else {}
    brand_line = str(required_title_lines.get("brand") or required_title_lines.get("top") or "").strip()
    main_title_line = str(required_title_lines.get("main") or "").strip()
    subtitle_line = str(required_title_lines.get("sub") or required_title_lines.get("bottom") or "").strip()
    hook_line = str(required_title_lines.get("hook") or "").strip()
    compare_subject_pair_required = bool(hard_contract.get("compare_subject_pair_required"))
    title_zone_prompt = (
        "标题区和主体区必须明显分离：上半区用于品牌行、主标题行、副标题行和吸睛文案行，"
        "下半区或左右下方保留主体展示，不要让标题压到刀柄、刀身主体或关键对比关系。"
    )
    canvas_size = spec.get("canvas_size") if isinstance(spec.get("canvas_size"), dict) else {}
    canvas_width = int(canvas_size.get("width") or 0)
    canvas_height = int(canvas_size.get("height") or 0)
    portrait_compare_instruction = ""
    if compare_subject_pair_required and canvas_height > canvas_width:
        portrait_compare_instruction = (
            "竖版对比封面也必须保留双主体完整同框：两件主体都要看清主要轮廓、柄部和刀身，不允许只剩局部特写。"
            "不能为了冲击力把其中一件裁掉或把第二件弱化成背景。"
            "两把刀的刀尖、柄尾和主要轮廓都必须完整留在画面内，四周要保留适度安全边距。"
            "优先使用略微拉远的构图，不要做近距离怼脸式裁切。"
        )
    line_split_instruction = ""
    if brand_line and main_title_line and subtitle_line:
        line_split_instruction = (
            "标题必须按四层信息布局直接完整渲染：品牌行、主标题行、副标题行、吸睛文案行。"
            "主标题行必须最大、最有压场感；副标题行明显更小一档，品牌行独立在上方，吸睛文案行作为底部 badge。"
            "品牌行建议做成小角标或短横幅；主标题做成最醒目的厚重金属 3D 字效；副标题作为第二层信息条；吸睛文案行做成短 badge。"
        )
    required_text_prompt = (
        f"必须直接在最终位图里完整渲染这些真实文字：品牌行「{brand_line or '无'}」；"
        f"主标题「{main_title_line or '无'}」；副标题「{subtitle_line or '无'}」；"
        f"吸睛文案「{hook_line or '无'}」。"
    )
    safe_layout_prompt = (
        "构图优先做成成熟短视频爆款封面：主体聚在下半区或两侧下方，"
        "上中部留下干净但有能量感的标题舞台；不要再把标题区和主体强行堆在同一个中央区域。"
    )
    selling_line = f"封面要表达的卖点：{selling_angle}" if selling_angle else ""
    visual_line = f"画面重点：{visual_brief}" if visual_brief else ""
    video_type_line = f"视频题材：{video_type}" if video_type else ""
    return (
        "基于参考图生成一张可直接发布的完整视频封面。\n"
        f"平台：{spec['platform_label']}\n"
        f"视觉方向：{spec['visual_instruction']}\n"
        f"{video_type_line}\n"
        "主体说明：保持参考图中的同一商品主体和版本关系，不改变品牌归属、型号类别、材质关系与主角度。\n"
        f"{selling_line}\n"
        f"{visual_line}\n"
        f"{critical_detail_prompt}\n"
        f"{hard_contract_prompt}\n"
        f"{packaging_text_exclusion_instruction}\n"
        f"{background_strategy_prompt}\n"
        f"{style_prompt}\n"
        f"{title_zone_prompt}\n"
        f"{safe_layout_prompt}\n"
        f"{required_text_prompt}\n"
        "编辑策略：前景主体结构保留优先。优先保留参考图里已有的刀身、手部、相对位置和前景轮廓，"
        "重点改背景、光影、氛围特效和标题排版，不要重新设计主体几何结构。\n"
        "要求：主体必须还是参考图里的真实商品；如果参考图里是两件，就保持这两件都清晰完整。"
        "优先做强点击封面化编排：主体放大、版本差异可读、手持真实、细节锐利。"
        f"{portrait_compare_instruction}"
        f"{line_split_instruction}"
        "只允许渲染上面明确要求的品牌行、主标题、副标题和吸睛文案；不要额外添加 slogan、包装字、字幕、功能标签、按钮或任何未要求的字。"
        "标题字效必须直接在位图里完成，不要留空白牌位等后期占位方案。"
        "背景特效必须保留高能电光、金属质感、火焰能量和赛博发光史诗氛围，不要弱化成普通干净背景。"
        "标题舞台必须集中在上中部，主体展示集中在下半区或左右下方，适配常见平台居中裁切。\n"
        "禁止：任何未要求的可读文字、字幕、水印、伪 logo、乱码、错别字、改变主体身份。"
    )


def _build_provider_safe_cover_image_prompt(*, spec: dict[str, Any]) -> str:
    brief_text = "\n".join(spec["brief_lines"])
    immutable_text = "\n".join(spec["immutable_requirements"])
    background_strategy_prompt = _background_strategy_prompt(spec.get("background_strategy") or "")
    critical_detail_notes = list(spec.get("critical_detail_notes") or [])
    hard_contract = spec.get("hard_contract") if isinstance(spec.get("hard_contract"), dict) else {}
    critical_detail_prompt = ""
    if critical_detail_notes:
        critical_detail_prompt = "关键细节硬约束：\n" + "\n".join(f"- {note}" for note in critical_detail_notes)
    hard_contract_prompt = (
        "硬合同：\n"
        "- 必须保持参考图产品主体一致，不允许改刀型、结构、开合状态或主角度。\n"
        "- 必须支持明确的品牌/型号主标题和配置副标题，封面标题结构必须完整。\n"
        f"- 同一封面组必须统一风格化，统一风格 key={hard_contract.get('unified_style_key') or spec.get('style_key') or ''}。"
    )
    packaging_text_exclusion_instruction = (
        "包装盒、卡片、贴纸、说明纸、印刷 logo 或任何可读包装字样都不能原样保留在底图里；"
        "如果参考图里有这些元素，必须裁掉、弱化、虚化，或替换成无字环境纹理。"
    )
    return (
        "基于参考图生成封面底图。\n"
        f"封面主题：{spec['title']}\n"
        f"画面方向：{spec['visual_instruction']}\n"
        f"{brief_text}\n"
        f"{critical_detail_prompt}\n"
        f"{hard_contract_prompt}\n"
        f"{packaging_text_exclusion_instruction}\n"
        f"品牌/商品名必须完整保留：{spec['product_identity']}\n"
        f"{background_strategy_prompt}\n"
        f"{spec['style_prompt']}\n"
        "编辑策略：前景主体结构保留优先，尽量保留参考图里已有的主体结构、手持关系和前景轮廓；"
        "重点改背景、光影和氛围，不要重画主体几何结构。\n"
        f"{immutable_text}"
    )


def _build_platform_cover_prompt_spec(
    *,
    title: str,
    platform_key: str,
    rules: dict[str, Any],
    width: int,
    height: int,
    cover_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    title_text = re.sub(r"\s+", " ", str(title or "").strip())
    instruction = str(rules.get("visual_instruction") or "").strip() or _platform_cover_visual_instruction(platform_key)
    brief = cover_brief if isinstance(cover_brief, dict) else {}
    style_key = _resolve_cover_image_style_key(rules=rules, cover_brief=brief)
    style_prompt = _cover_image_style_prompt(style_key)
    brief_lines = []
    if brief:
        for label, key in (
            ("视频类型", "video_type"),
            ("主体识别", "product_identity"),
            ("封面卖点", "selling_angle"),
            ("画面 brief", "visual_brief"),
        ):
            value = str(brief.get(key) or "").strip()
            if value:
                brief_lines.append(f"{label}：{value}")
    product_identity = str(brief.get("product_identity") or "").strip() or "参考图中的同一商品"
    selling_angle = str(brief.get("selling_angle") or "").strip()
    visual_brief = str(brief.get("visual_brief") or "").strip()
    video_type = str(brief.get("video_type") or "").strip()
    background_strategy = _normalize_cover_background_strategy(brief.get("background_strategy") or "")
    critical_detail_notes = _normalize_cover_critical_detail_notes(brief.get("critical_detail_notes"))
    title_lines = _build_cover_title_layout_plan(title=title_text, cover_brief=brief)
    immutable_requirements = [
        "主体必须是参考图里的同一个商品；如果参考图里是两件，就保持这两件。",
        "主体一致性是最高优先级：不改商品身份，不改品牌归属，不改核心结构。",
        "优先保留参考图前景主体的原始结构和相对关系；允许重点增强的是背景、光影、氛围和标题区域。",
        "重点强调商品细节一致性：保留轮廓、比例、关键开合关系、纹理分区和主要部件位置，不改款，不变形。",
        "在主体不变的前提下，加强构图、光影、清晰度、对比和质感，突出版本差异。",
        "品牌/商品识别词不能丢，底图语义要与封面主题一致，不能换成泛称。",
        "标题结构必须准确完整：品牌行、主标题、副标题和吸睛文案都要按合同生成。",
    ]
    for note in critical_detail_notes:
        immutable_requirements.append(f"关键细节不能画错：{note}")
    hard_contract = _build_cover_hard_contract(
        title=title_text,
        cover_brief=brief,
        style_key=style_key,
        title_lines=title_lines,
    )
    director_policy = _build_cover_director_policy(
        style_key=style_key,
        title_lines=title_lines,
        hard_contract=hard_contract,
        platform_label=str(rules.get("label") or str(platform_key or "").strip() or "通用封面"),
        visual_instruction=instruction,
    )
    return {
        "title": title_text or "内容主题明确、突出主体",
        "platform_key": str(platform_key or "").strip(),
        "platform_label": str(rules.get("label") or str(platform_key or "").strip() or "通用封面"),
        "canvas_size": {"width": int(width), "height": int(height)},
        "visual_instruction": instruction,
        "style_key": style_key,
        "style_prompt": style_prompt,
        "product_identity": product_identity,
        "selling_angle": selling_angle,
        "visual_brief": visual_brief,
        "video_type": video_type,
        "background_strategy": background_strategy,
        "critical_detail_notes": critical_detail_notes,
        "brief_lines": brief_lines,
        "immutable_requirements": immutable_requirements,
        "title_lines": title_lines,
        "hard_contract": hard_contract,
        "director_policy": director_policy,
    }


def _build_cover_hard_contract(
    *,
    title: str,
    cover_brief: dict[str, Any],
    style_key: str,
    title_lines: dict[str, str] | None,
) -> dict[str, Any]:
    identity = str(cover_brief.get("product_identity") or "").strip()
    selling_angle = str(cover_brief.get("selling_angle") or "").strip()
    video_type = str(cover_brief.get("video_type") or "").strip()
    compare_text = " ".join(
        str(value or "").strip()
        for value in (title, identity, selling_angle, video_type)
        if str(value or "").strip()
    )
    compare_subject_pair_required = bool(re.search(r"\bvs\b|对比|双版本|两版本|双主体", compare_text, re.I))
    layout = dict(title_lines or {})
    return {
        "subject_identity_required": True,
        "preserve_subject_geometry": True,
        "preserve_primary_angle_if_present": True,
        "preserve_open_state_if_present": True,
        "compare_subject_pair_required": compare_subject_pair_required,
        "brand_model_title_required": bool(identity or title),
        "config_subtitle_required": bool(layout.get("bottom") or selling_angle or video_type),
        "hook_badge_required": bool(layout.get("hook")),
        "full_bitmap_cover_required": True,
        "post_title_overlay_required": False,
        "unified_style_key": str(style_key or "").strip(),
        "signature_stability_required": True,
        "required_title_lines": {
            "brand": str(layout.get("brand") or layout.get("top") or "").strip(),
            "top": str(layout.get("top") or "").strip(),
            "main": str(layout.get("main") or "").strip(),
            "sub": str(layout.get("sub") or layout.get("bottom") or "").strip(),
            "bottom": str(layout.get("bottom") or "").strip(),
            "hook": str(layout.get("hook") or "").strip(),
        },
    }


def _build_cover_director_policy(
    *,
    style_key: str,
    title_lines: dict[str, str] | None,
    hard_contract: dict[str, Any] | None,
    platform_label: str,
    visual_instruction: str = "",
) -> dict[str, Any]:
    profile = dict(COVER_DIRECTOR_STYLE_PROFILES.get(str(style_key or "").strip()) or {})
    layout = dict(title_lines or {})
    contract = dict(hard_contract or {})
    return {
        "direction_version": "full_cover_codex_v1",
        "codex_role": "render_final_cover_with_integrated_typography",
        "goal": "Let Codex image generation produce the final publishable cover with integrated typography and unified style.",
        "typography_owner": "codex_full_cover",
        "platform_label": str(platform_label or "").strip(),
        "visual_instruction": str(visual_instruction or "").strip(),
        "style_key": str(style_key or "").strip(),
        "style_profile_key": str(profile.get("style_profile_key") or "").strip(),
        "headline_effects": list(profile.get("headline_effects") or []),
        "layout_contract": list(profile.get("layout_contract") or ["brand_line", "main_title", "subtitle", "hook_badge"]),
        "composition_contract": dict(profile.get("composition_contract") or {}),
        "required_title_lines": {
            "brand": str(layout.get("brand") or layout.get("top") or "").strip(),
            "main": str(layout.get("main") or "").strip(),
            "subtitle": str(layout.get("sub") or layout.get("bottom") or "").strip(),
            "hook": str(layout.get("hook") or "").strip(),
        },
        "forbidden_extra_visual_text": [
            "subtitles",
            "watermarks",
            "pseudo logos unrelated to the requested brand",
            "Chinese or English words not explicitly requested in the prompt contract",
        ],
        "completion_requires": [
            "A real bitmap generated with Codex built-in image_gen/edit mode.",
            "The bitmap is the final cover, not a text-free base image.",
            "The bitmap already contains the requested brand line, main title, subtitle, and hook badge in a unified style.",
            "No extra unrequested typography, subtitles, watermarks, or unrelated pseudo logos appear in the bitmap.",
            "Key subject stays complete and readable after typography placement.",
            "The generated bitmap copied to output_path before marking this request completed.",
        ],
        "supports_compare_subject_pair": bool(contract.get("compare_subject_pair_required")),
    }


def _resolve_cover_image_style_key(*, rules: dict[str, Any], cover_brief: dict[str, Any]) -> str:
    explicit = str(rules.get("cover_style") or "").strip()
    brief_style_key = str(cover_brief.get("style_key") or "").strip()
    if brief_style_key in COVER_IMAGE_STYLE_SCHEMES:
        return brief_style_key
    identity_text = " ".join(
        str(cover_brief.get(key) or "").strip()
        for key in ("product_identity", "selling_angle", "visual_brief", "video_type")
        if str(cover_brief.get(key) or "").strip()
    )
    if re.search(
        r"\bEDC\b|MOT|风灵|FAS|锆合金|音叉|推牌|刀帕|伞绳|绳扣|战术|tactical|MAXACE|美杜莎|折刀|小刀|刀\b|刀具|开箱刀",
        identity_text,
        re.I,
    ):
        return OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO
    if explicit in COVER_IMAGE_STYLE_SCHEMES:
        return explicit
    return explicit


def _cover_image_style_prompt(style_key: str) -> str:
    scheme = COVER_IMAGE_STYLE_SCHEMES.get(str(style_key or "").strip())
    if not scheme:
        return "风格方案：跟随平台和内容主题，保持主体真实、标题清晰、画面专业。"
    return str(scheme.get("prompt") or "").strip()


def _cover_ratio_label(*, width: int, height: int) -> str:
    safe_width = max(1, int(width or 0))
    safe_height = max(1, int(height or 0))
    ratio = safe_width / safe_height
    if abs(ratio - (16 / 9)) < 0.03:
        return "16:9 横版"
    if abs(ratio - (9 / 16)) < 0.03:
        return "9:16 竖版"
    if abs(ratio - (3 / 4)) < 0.03:
        return "3:4 竖版"
    return f"{safe_width}:{safe_height}"


def _platform_cover_visual_instruction(platform_key: str) -> str:
    instructions = {
        "bilibili": "横版信息流封面，主体明确、细节可读、技术/开箱感强，标题和主体集中在中央安全区。",
        "xiaohongshu": "3:4 笔记封面，干净、质感、真实分享感，主体靠中上，留出醒目的标题空间。",
        "douyin": "9:16 竖版短视频封面，第一眼冲击强，主体占比大，顶部和中部要适合大字标题。",
        "kuaishou": "9:16 竖版封面，直给、真实、主体大，避免过度精修，适合手机端快速扫到重点。",
        "wechat_channels": "9:16 竖版封面，稳妥可信，画面克制，主体清楚，适合朋友圈/视频号信息流。",
        "toutiao": "横版资讯封面，结论感和主体信息清楚，背景少干扰，标题和主体集中在中央安全区。",
        "youtube": "横版 YouTube thumbnail，高对比、主体大、层次清楚，标题和主体集中在中央安全区。",
        "x": "横版社交流封面，干净、观点感强，缩略图里主体仍然清楚，标题和主体集中在中央安全区。",
    }
    return instructions.get(str(platform_key or "").strip(), "主体清楚、背景干净、预留标题安全区。")


def _fit_image_to_canvas(*, source_path: Path, output_path: Path, width: int, height: int, fit_mode: str = "contain") -> None:
    settings = get_settings()
    resolved_fit_mode = str(fit_mode or "").strip().lower()
    if resolved_fit_mode == "cover":
        video_filter = (
            "scale="
            f"w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            str(output_path),
        ]
    elif resolved_fit_mode == "blur_fill":
        filter_complex = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale=w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=24:2[bg2];"
            f"[fg]scale=w={width}:h={height}:force_original_aspect_ratio=decrease[fg2];"
            f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2"
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-filter_complex",
            filter_complex,
            "-frames:v",
            "1",
            str(output_path),
        ]
    else:
        video_filter = (
            "scale="
            f"w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x111111"
        )
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            str(output_path),
        ]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=settings.ffmpeg_timeout_sec,
    )
    if result.returncode != 0:
        raise RuntimeError(f"封面尺寸适配失败：{result.stderr[-400:]}")


def _read_image_dimensions(source_path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(source_path) as image:
            width, height = image.size
        if width > 0 and height > 0:
            return int(width), int(height)
    except Exception:
        return None
    return None


def _resolve_cover_canvas_fit_mode(
    *,
    source_path: Path,
    width: int,
    height: int,
    preserve_subject: bool = True,
) -> str:
    if not preserve_subject:
        return "cover"
    dimensions = _read_image_dimensions(source_path)
    if dimensions is None:
        return "cover"
    source_width, source_height = dimensions
    source_ratio = source_width / max(1, source_height)
    target_ratio = width / max(1, height)
    ratio_gap = abs(source_ratio - target_ratio) / max(source_ratio, target_ratio)
    if ratio_gap >= 0.16:
        return "blur_fill"
    return "cover"


def _fit_existing_image_to_canvas(*, output_path: Path, width: int, height: int, fit_mode: str = "contain") -> None:
    if not output_path.exists():
        return
    with tempfile.NamedTemporaryFile(
        suffix=output_path.suffix or ".jpg",
        prefix=f"{output_path.stem}.fit-source.",
        dir=output_path.parent,
        delete=False,
    ) as tmp_file:
        tmp_source = Path(tmp_file.name)
    try:
        shutil.copy2(output_path, tmp_source)
        _fit_image_to_canvas(
            source_path=tmp_source,
            output_path=output_path,
            width=width,
            height=height,
            fit_mode=fit_mode,
        )
    finally:
        try:
            tmp_source.unlink(missing_ok=True)
        except Exception:
            pass


def _build_cover_title_lines(title: str) -> dict[str, str] | None:
    normalized = re.sub(r"\s+", " ", str(title or "").strip()).strip(" -|")
    if not normalized:
        return None
    brand_split = re.match(r"^([A-Za-z0-9][A-Za-z0-9 ._-]{1,15})\s+(.+)$", normalized)
    if brand_split:
        brand = brand_split.group(1).strip()[:12]
        remainder = brand_split.group(2).strip()
        compare_match = re.search(r"(双版开箱对比|开箱对比|版本对比|双版对比|对比)$", remainder)
        if compare_match:
            pivot = compare_match.start()
            subject = remainder[:pivot].strip()[:12]
            bottom = compare_match.group(1).strip()[:18]
            if subject:
                return {"top": brand, "main": subject, "bottom": bottom}
    compare_match = re.search(r"(双版开箱对比|开箱对比|版本对比|双版对比|对比)$", normalized)
    if compare_match:
        pivot = compare_match.start()
        subject = normalized[:pivot].strip()[:16]
        bottom = compare_match.group(1).strip()[:18]
        if subject:
            return {"top": "", "main": subject, "bottom": bottom}
    segments = [segment.strip() for segment in re.split(r"[：:|｜\-—]", normalized) if segment.strip()]
    if len(segments) >= 3:
        return {
            "top": segments[0][:12],
            "main": segments[1][:18],
            "bottom": segments[2][:18],
        }
    if len(segments) == 2:
        return {
            "top": segments[0][:12],
            "main": segments[1][:18],
            "bottom": "",
        }
    text = segments[0]
    if len(text) <= 12:
        return {"top": "", "main": text, "bottom": ""}
    if len(text) <= 24:
        return {"top": text[:10], "main": text[10:24], "bottom": ""}
    return {"top": text[:10], "main": text[10:26], "bottom": text[26:42]}


def _build_cover_title_layout_plan(
    *,
    title: str,
    cover_brief: dict[str, Any] | None = None,
) -> dict[str, str] | None:
    base_lines = _build_cover_title_lines(title) or {"top": "", "main": "", "bottom": ""}
    brief = cover_brief if isinstance(cover_brief, dict) else {}
    identity = str(brief.get("product_identity") or "").strip()
    selling_angle = str(brief.get("selling_angle") or "").strip()
    video_type = str(brief.get("video_type") or "").strip()
    identity_lines = _build_cover_title_lines(identity) or {}
    identity_brand, identity_model = _split_cover_identity_lines(identity)
    identity_model = _strip_cover_compare_suffix(identity_model)

    top = str(base_lines.get("top") or identity_brand or identity_lines.get("top") or "").strip()
    if identity_brand and top != identity_brand:
        top = identity_brand
    main = str(base_lines.get("main") or "").strip()
    if identity_model and (not main or _cover_title_line_contains_compare_tail(main)):
        main = identity_model
    if not main:
        main = str(identity_lines.get("main") or identity_lines.get("top") or "").strip()
    bottom = str(base_lines.get("bottom") or "").strip()
    stable_compare_subtitle = _extract_stable_cover_compare_subtitle(
        title=title,
        identity=identity,
        selling_angle=selling_angle,
        video_type=video_type,
    )
    if stable_compare_subtitle:
        bottom = stable_compare_subtitle
    elif not bottom or _cover_title_line_contains_compare_tail(bottom):
        for candidate in (video_type, selling_angle, bottom):
            normalized = _normalize_cover_subtitle_line(candidate)
            if normalized:
                bottom = normalized
                break
    if not main:
        return None
    hook = _resolve_cover_hook_badge(
        title=title,
        identity=identity,
        selling_angle=selling_angle,
        video_type=video_type,
    )
    brand = top[:14]
    subtitle = bottom[:18]
    return {
        "brand": brand,
        "top": brand,
        "main": main[:18],
        "sub": subtitle,
        "bottom": subtitle,
        "hook": hook[:18],
    }


def _resolve_cover_hook_badge(
    *,
    title: str,
    identity: str,
    selling_angle: str,
    video_type: str,
) -> str:
    blob = " ".join(part for part in (title, identity, selling_angle, video_type) if str(part or "").strip())
    if _cover_title_line_contains_compare_tail(blob) and re.search(r"开箱|unbox", blob, re.I):
        return "双版本开箱"
    if _cover_title_line_contains_compare_tail(blob):
        return "双版本对比"
    if re.search(r"开箱|unbox", blob, re.I):
        return "开箱实拍"
    if re.search(r"细节|做工|手感|质感", blob, re.I):
        return "细节实拍"
    return ""


def _normalize_cover_subtitle_line(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip(" -|，,。.!！?？")
    if not text:
        return ""
    replacements = (
        ("顶配与次顶配", "顶配次顶配"),
        ("细节差异", "细节对比"),
        ("版本差异", "版本对比"),
        ("开箱对比", "双版对比"),
    )
    for source, target in replacements:
        text = text.replace(source, target)
    return _trim_to_display_units(text, 18)


def _extract_stable_cover_compare_subtitle(
    *,
    title: str,
    identity: str,
    selling_angle: str,
    video_type: str,
) -> str:
    context_blob = " ".join(
        part for part in (title, identity, selling_angle, video_type) if str(part or "").strip()
    )
    if _cover_title_line_contains_compare_tail(context_blob):
        return _resolve_compare_tail(context_blob)
    return ""


def _cover_title_line_contains_compare_tail(value: str) -> bool:
    text = str(value or "").strip()
    return any(token in text for token in ("顶配", "次顶配", "双版", "版本对比", "vs", "VS", "对比"))


def _strip_cover_compare_suffix(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip()
    if not text:
        return ""
    patterns = (
        r"\s*(顶配\s*(vs|VS|对比|与|和)\s*次顶配.*)$",
        r"\s*(顶配次顶配.*)$",
        r"\s*(顶配与次顶配.*)$",
        r"\s*(双版.*)$",
        r"\s*(双配.*)$",
        r"\s*(版本对比.*)$",
        r"\s*(开箱对比.*)$",
        r"\s*(EDC折刀.*)$",
        r"\s*(折刀.*)$",
    )
    for pattern in patterns:
        text = re.sub(pattern, "", text).strip()
    return text


def _split_cover_identity_lines(identity: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", str(identity or "").strip())
    if not normalized:
        return "", ""
    match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]{1,15})\s+(.+)$", normalized)
    if match:
        return match.group(1).strip()[:14], match.group(2).strip()[:18]
    prefix_chars: list[str] = []
    for char in normalized:
        if re.match(r"[A-Za-z0-9._-]", char):
            prefix_chars.append(char)
            continue
        break
    prefix = "".join(prefix_chars).strip()
    if 2 <= len(prefix) <= 15 and len(prefix) < len(normalized):
        remainder = normalized[len(prefix):].strip()
        if remainder:
            return prefix[:14], remainder[:18]
    return "", normalized[:18]


def _content_profile_summary(content_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject_brand": str(content_profile.get("subject_brand") or "").strip(),
        "subject_model": str(content_profile.get("subject_model") or "").strip(),
        "subject_type": str(content_profile.get("subject_type") or "").strip(),
        "subject_domain": str(content_profile.get("subject_domain") or "").strip(),
        "video_theme": str(content_profile.get("video_theme") or "").strip(),
        "summary": str(content_profile.get("summary") or "").strip(),
        "hook_line": str(content_profile.get("hook_line") or "").strip(),
        "engagement_question": str(content_profile.get("engagement_question") or "").strip(),
        "copy_style": str(content_profile.get("copy_style") or "").strip(),
        "cover_title": dict(content_profile.get("cover_title") or {}) if isinstance(content_profile.get("cover_title"), dict) else {},
    }


def _specialize_intelligent_copy_profile(
    *,
    stem: str,
    transcript_text: str,
    subject_brand: str,
    subject_model: str,
    subject_type: str,
    subject_domain: str,
    video_theme: str,
    summary: str,
    hook_line: str,
    engagement_question: str,
    search_queries: list[str],
    cover_title: dict[str, str],
) -> dict[str, Any]:
    normalized = " ".join(part for part in (stem, transcript_text) if part).strip()
    topic_spec = match_intelligent_copy_topic(normalized)
    if topic_spec is not None:
        return _build_topic_profile_overrides(
            topic_spec=topic_spec,
            subject_brand=subject_brand,
            subject_model=subject_model,
            hook_line=hook_line,
        )
    return {
        "subject_brand": subject_brand,
        "subject_model": subject_model,
        "subject_type": subject_type,
        "subject_domain": subject_domain,
        "video_theme": video_theme,
        "summary": summary,
        "hook_line": hook_line,
        "engagement_question": engagement_question,
        "search_queries": search_queries,
        "cover_title": cover_title,
    }


def _build_topic_profile_overrides(
    *,
    topic_spec: IntelligentCopyTopicSpec,
    subject_brand: str,
    subject_model: str,
    hook_line: str,
) -> dict[str, Any]:
    brand = subject_brand or topic_spec.subject_brand
    model = subject_model or topic_spec.subject_model
    cover_main = topic_spec.cover_main or f"{brand}{model}"[:18]
    return {
        "subject_brand": brand,
        "subject_model": model,
        "subject_type": topic_spec.subject_type,
        "subject_domain": topic_spec.subject_domain,
        "video_theme": topic_spec.video_theme,
        "summary": topic_spec.summary,
        "hook_line": hook_line or topic_spec.hook_line,
        "engagement_question": topic_spec.engagement_question,
        "search_queries": list(topic_spec.search_queries),
        "cover_title": {
            "top": "",
            "main": cover_main[:18],
            "bottom": "",
        },
    }


def _build_intelligent_copy_brief(
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any],
) -> dict[str, Any]:
    transcript_text = " ".join(
        str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        for item in subtitle_items[:100]
    ).strip()
    summary = str(content_profile.get("summary") or "").strip()
    question = str(content_profile.get("engagement_question") or "").strip()
    subject_brand = str(content_profile.get("subject_brand") or "").strip()
    subject_model = str(content_profile.get("subject_model") or "").strip()
    subject_type = str(content_profile.get("subject_type") or "").strip()
    subject_label = "".join(part for part in (subject_brand, subject_model) if part) or subject_brand or subject_model or video_path.stem
    normalized = " ".join(part for part in (video_path.stem, transcript_text, summary) if part)
    topic_spec = match_intelligent_copy_topic(normalized)
    if topic_spec is not None:
        return {
            "topic_key": topic_spec.key,
            "topic_subject": topic_spec.topic_subject,
            "intent": topic_spec.intent,
            "summary": summary or topic_spec.summary,
            "question": question or topic_spec.engagement_question,
            "focus_points": list(topic_spec.focus_points),
            "tags": list(topic_spec.tags),
            "anchor_terms": list(topic_spec.anchor_terms),
            "forbidden_terms": list(topic_spec.forbidden_terms),
            "title_candidates": list(topic_spec.title_candidates),
            "subject_type": subject_type,
        }
    return {
        "topic_subject": subject_label or video_path.stem,
        "intent": "generic",
        "summary": summary or f"这期主要围绕{subject_label or video_path.stem}展开。",
        "question": question or "你最想继续看哪一部分？",
        "focus_points": ["开箱过程", "细节展示", "真实体验"],
        "tags": [subject_brand, subject_model, subject_type, video_path.stem, "开箱", "上手体验"],
        "anchor_terms": [subject_brand, subject_model, subject_type, video_path.stem],
        "forbidden_terms": [],
        "subject_type": subject_type,
    }


def _build_intelligent_copy_packaging(
    *,
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
) -> dict[str, Any]:
    packaging: dict[str, Any] = {
        "highlights": {
        "product": str(copy_brief.get("topic_subject") or "").strip(),
        "video_type": str(content_profile.get("video_theme") or copy_brief.get("intent") or "").strip(),
        "strongest_selling_point": "、".join(list(copy_brief.get("focus_points") or [])[:2]),
        "strongest_emotion": "",
        "title_hook": str(content_profile.get("hook_line") or copy_brief.get("summary") or "").strip(),
        "engagement_question": str(copy_brief.get("question") or "").strip(),
        }
    }
    platforms: dict[str, Any] = {}
    for platform_key, _label, _body_label, _tag_label in PLATFORM_ORDER:
        rules = PLATFORM_PUBLISH_RULES.get(platform_key) or {}
        titles = _build_intelligent_copy_titles(platform_key=platform_key, rules=rules, copy_brief=copy_brief, content_profile=content_profile)
        description = _build_intelligent_copy_description(platform_key=platform_key, copy_brief=copy_brief)
        tags = _build_intelligent_copy_tags(copy_brief=copy_brief, rules=rules)
        platforms[platform_key] = {
            "titles": titles,
                "description": description,
                "tags": tags,
            }
    packaging["platforms"] = platforms
    return packaging


def _build_intelligent_copy_titles(
    *,
    platform_key: str,
    rules: dict[str, Any],
    copy_brief: dict[str, Any],
    content_profile: dict[str, Any],
) -> list[str]:
    if not bool(rules.get("has_title", True)):
        return []
    topic_subject = str(copy_brief.get("topic_subject") or "").strip() or str(content_profile.get("subject_model") or "").strip() or "这期内容"
    focus_points = [str(item).strip() for item in (copy_brief.get("focus_points") or []) if str(item).strip()]
    intent = str(copy_brief.get("intent") or "").strip()
    forbidden_terms = [str(item).strip() for item in (copy_brief.get("forbidden_terms") or []) if str(item).strip()]
    anchor_terms = [str(item).strip() for item in (copy_brief.get("anchor_terms") or []) if str(item).strip()]
    explicit_candidates = [str(item).strip() for item in (copy_brief.get("title_candidates") or []) if str(item).strip()]
    anchor_phrase = _resolve_title_anchor_phrase(topic_subject=topic_subject, anchor_terms=anchor_terms)
    candidate_pool: list[str] = []
    if explicit_candidates:
        candidate_pool.extend(explicit_candidates)
    candidate_pool.extend(
        _build_platform_title_boost_candidates(
            platform_key=platform_key,
            topic_subject=topic_subject,
            focus_points=focus_points,
            anchor_phrase=anchor_phrase,
        )
    )
    candidate_pool.extend(
        build_title_candidates(
            intent=intent,
            topic_subject=topic_subject,
            focus_points=focus_points,
        )
    )
    candidate_pool.extend(
        build_fallback_titles(
            label=str(rules.get("label") or "").strip(),
            content_profile=content_profile,
            copy_style="attention_grabbing",
        )
    )
    filtered = _filter_title_candidates(
        candidates=candidate_pool,
        limit=int(rules.get("title_limit") or 40),
        topic_subject=topic_subject,
        anchor_terms=anchor_terms,
        forbidden_terms=forbidden_terms,
    )
    return _ensure_title_anchor_coverage(
        titles=filtered,
        candidate_pool=candidate_pool,
        title_limit=int(rules.get("title_limit") or 40),
        topic_subject=topic_subject,
        anchor_terms=anchor_terms,
        forbidden_terms=forbidden_terms,
    )


def _ensure_title_anchor_coverage(
    *,
    titles: list[str],
    candidate_pool: list[str],
    title_limit: int,
    topic_subject: str,
    anchor_terms: list[str],
    forbidden_terms: list[str],
) -> list[str]:
    if len(_anchored_titles(titles, topic_subject=topic_subject, anchor_terms=anchor_terms)) >= 2:
        return titles
    if not anchor_phrase:
        return titles
    enriched = list(titles)
    for candidate in candidate_pool:
        if len(_anchored_titles(enriched, topic_subject=topic_subject, anchor_terms=anchor_terms)) >= 2:
            break
        for variant in _build_anchored_title_variants(candidate, anchor_phrase=anchor_phrase):
            filtered_variant = _filter_title_candidates(
                candidates=[variant],
                limit=title_limit,
                topic_subject=topic_subject,
                anchor_terms=anchor_terms,
                forbidden_terms=forbidden_terms,
            )
            for normalized in filtered_variant:
                if normalized not in enriched:
                    enriched.append(normalized)
                    if len(_anchored_titles(enriched, topic_subject=topic_subject, anchor_terms=anchor_terms)) >= 2:
                        break
            if len(_anchored_titles(enriched, topic_subject=topic_subject, anchor_terms=anchor_terms)) >= 2:
                break
    rescored = [
        (
            score_title_candidate(
                text,
                topic_subject=topic_subject,
                anchor_terms=anchor_terms,
                forbidden_terms=forbidden_terms,
            ),
            text,
        )
        for text in enriched
    ]
    rescored.sort(key=lambda item: (-item[0], item[1]))
    return _dedupe([text for _score, text in rescored])


def _anchored_titles(titles: list[str], *, topic_subject: str, anchor_terms: list[str]) -> list[str]:
    return [title for title in titles if _title_has_subject_anchor(title, topic_subject=topic_subject, anchor_terms=anchor_terms)]


def _title_has_subject_anchor(text: str, *, topic_subject: str, anchor_terms: list[str]) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if topic_subject and topic_subject.lower() in normalized:
        return True
    return any(term and term.lower() in normalized for term in anchor_terms[:3])


def _resolve_title_anchor_phrase(*, topic_subject: str, anchor_terms: list[str]) -> str:
    for candidate in anchor_terms[:3]:
        normalized = str(candidate or "").strip()
        if normalized and len(normalized) <= 24:
            return normalized
    normalized_subject = str(topic_subject or "").strip()
    if normalized_subject:
        return normalized_subject[:24]
    return ""


def _build_anchored_title_variants(title: str, *, anchor_phrase: str) -> list[str]:
    base = str(title or "").strip()
    if not base or not anchor_phrase:
        return []
    if anchor_phrase in base:
        return [base]
    return [f"{anchor_phrase}：{base}", f"{anchor_phrase}{base}"]


def _build_platform_title_boost_candidates(
    *,
    platform_key: str,
    topic_subject: str,
    focus_points: list[str],
    anchor_phrase: str,
) -> list[str]:
    subject = str(anchor_phrase or topic_subject or "这期内容").strip()
    if not subject:
        return []
    context_blob = " ".join([subject, *focus_points]).lower()
    is_compare = any(token in context_blob for token in ("对比", "区别", "差异", "顶配", "次顶配", "双版", "同款不同配", "怎么选"))
    if not is_compare:
        return []
    compare_tail = _resolve_compare_tail(context_blob)
    if platform_key == "bilibili":
        return [
            f"{subject}{compare_tail}，差在哪？",
            f"同款不同配怎么选？{subject}实拍对比",
            f"{subject}开箱对比：{compare_tail}区别在哪",
        ]
    if platform_key == "xiaohongshu":
        return [
            f"到货分享｜{subject}{compare_tail}",
            f"{subject}两个版本怎么选",
            f"{subject}{compare_tail}开箱",
        ]
    if platform_key == "douyin":
        return [
            f"{subject}{compare_tail}，差别有多大",
            f"{subject}双版开箱，先看差异",
            f"{subject}同款不同配怎么选",
        ]
    if platform_key == "toutiao":
        return [
            f"{subject}{compare_tail}实拍对比",
            f"{subject}顶配和次顶配区别在哪",
            f"{subject}两个版本怎么选更合适",
        ]
    if platform_key == "youtube":
        return [
            f"{subject}{compare_tail}开箱对比",
            f"{subject}顶配和次顶配怎么选",
            f"{subject}实拍对比：差别在哪",
        ]
    return [
        f"{subject}{compare_tail}",
        f"{subject}实拍对比",
    ]


def _resolve_compare_tail(context_blob: str) -> str:
    if "顶配" in context_blob and "次顶配" in context_blob:
        return "顶配vs次顶配"
    if "双版" in context_blob or "双配" in context_blob:
        return "双版对比"
    return "版本对比"


def _build_intelligent_copy_description(*, platform_key: str, copy_brief: dict[str, Any]) -> str:
    summary = str(copy_brief.get("summary") or "").strip()
    question = str(copy_brief.get("question") or "").strip()
    focus_points = [str(item).strip() for item in (copy_brief.get("focus_points") or []) if str(item).strip()]
    focus_line = "、".join(focus_points[:3])
    forbidden_terms = [str(item).strip() for item in (copy_brief.get("forbidden_terms") or []) if str(item).strip()]
    topic_subject = str(copy_brief.get("topic_subject") or "").strip()
    anchor_terms = [str(item).strip() for item in (copy_brief.get("anchor_terms") or []) if str(item).strip()]
    description = build_platform_description(
        platform_key,
        summary=summary,
        question=question,
        focus_line=focus_line,
    )
    sanitized = _sanitize_copy_line(description, forbidden_terms=forbidden_terms)
    if not sanitized:
        return ""
    if score_description(
        sanitized,
        topic_subject=topic_subject,
        anchor_terms=anchor_terms,
        question=question,
        forbidden_terms=forbidden_terms,
    ) < 4:
        fallback = build_fallback_description(
            label=str((PLATFORM_PUBLISH_RULES.get(platform_key) or {}).get("label") or platform_key),
            content_profile={
                "subject_brand": anchor_terms[0] if len(anchor_terms) > 0 else "",
                "subject_model": topic_subject,
                "engagement_question": question,
                "summary": summary,
            },
            copy_style="attention_grabbing",
        )
        return _sanitize_copy_line(fallback, forbidden_terms=forbidden_terms)
    return sanitized


def _build_intelligent_copy_tags(*, copy_brief: dict[str, Any], rules: dict[str, Any]) -> list[str]:
    candidates = [str(item).strip().lstrip("#") for item in (copy_brief.get("tags") or []) if str(item).strip()]
    forbidden = {str(item).strip() for item in (copy_brief.get("forbidden_terms") or []) if str(item).strip()}
    filtered = [item for item in _dedupe(candidates) if item and item not in forbidden]
    return filtered[: int(rules.get("tag_limit") or 6)]


def _filter_copy_lines(*, candidates: list[str], limit: int, forbidden_terms: list[str]) -> list[str]:
    filtered: list[str] = []
    for candidate in candidates:
        trimmed = _trim_to_display_units(candidate, limit)
        sanitized = _sanitize_copy_line(trimmed, forbidden_terms=forbidden_terms)
        if not sanitized or _display_units(sanitized) < 8:
            continue
        filtered.append(sanitized)
    return _dedupe(filtered)


def _filter_title_candidates(
    *,
    candidates: list[str],
    limit: int,
    topic_subject: str,
    anchor_terms: list[str],
    forbidden_terms: list[str],
) -> list[str]:
    scored: list[tuple[int, str]] = []
    for candidate in candidates:
        trimmed = _trim_to_display_units(candidate, limit)
        sanitized = _sanitize_copy_line(trimmed, forbidden_terms=forbidden_terms)
        if not sanitized or _display_units(sanitized) < 8:
            continue
        score = score_title_candidate(
            sanitized,
            topic_subject=topic_subject,
            anchor_terms=anchor_terms,
            forbidden_terms=forbidden_terms,
        )
        if score < 3:
            continue
        scored.append((score, sanitized))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return _dedupe([text for _score, text in scored])


def _sanitize_copy_line(text: str, *, forbidden_terms: list[str]) -> str:
    normalized = str(text or "").strip()
    if not normalized:
        return ""
    for term in forbidden_terms:
        if term and term in normalized:
            return ""
    return normalized


def _resolve_existing_folder(folder_path: str) -> Path:
    folder = Path(str(folder_path or "").strip()).expanduser()
    if not folder.exists() or not folder.is_dir():
        materialized = _materialize_host_folder(folder_path)
        if materialized is None or not materialized.exists() or not materialized.is_dir():
            raise ValueError("目录不存在，或不是可访问的文件夹。")
        return materialized.resolve()
    return folder.resolve()


def _display_folder_path_for_inspection(requested_folder_path: str, resolved_folder: Path) -> str:
    requested = str(requested_folder_path or "").strip().strip('"')
    if not requested:
        return str(resolved_folder)
    requested_path = Path(requested).expanduser()
    try:
        if requested_path.exists() and requested_path.is_dir():
            return str(resolved_folder)
    except OSError:
        pass
    if _looks_like_host_folder_path(requested):
        return requested
    return str(resolved_folder)


def _looks_like_host_folder_path(value: str) -> bool:
    normalized = str(value or "").strip()
    if normalized.startswith(("\\\\", "//")):
        return True
    return bool(re.match(r"^[A-Za-z]:[\\/]", normalized))


def _materialize_host_folder(folder_path: str) -> Path | None:
    url = _resolve_host_materialize_url()
    raw_folder_path = str(folder_path or "").strip()
    if not url or not raw_folder_path:
        return None

    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        response = httpx.post(
            url,
            json={
                "folder_path": raw_folder_path,
                "container_output_root": str(os.getenv("ROUGHCUT_OUTPUT_ROOT", "/app/data") or "/app/data"),
            },
            headers=headers,
            timeout=float(os.getenv("ROUGHCUT_HOST_MATERIALIZE_TIMEOUT_SEC", "120") or "120"),
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    materialized_path = str(payload.get("folder_path") or "").strip()
    return Path(materialized_path).expanduser() if materialized_path else None


def _resolve_host_materialize_url() -> str:
    explicit = str(os.getenv("ROUGHCUT_HOST_MATERIALIZE_DIRECTORY_URL", "") or "").strip()
    if explicit:
        return explicit
    return resolve_codex_proxy_sibling_url("/v1/host/materialize-directory")


def _pick_primary_video(*, video_files: list[Path], subtitle_files: list[Path]) -> Path | None:
    if not video_files:
        return None
    if len(video_files) == 1:
        return video_files[0]
    best_video = video_files[0]
    best_score = -1.0
    subtitle_stems = [item.stem.lower() for item in subtitle_files]
    for candidate in video_files:
        score = float(candidate.stat().st_size)
        stem = candidate.stem.lower()
        if any(stem in subtitle_stem or subtitle_stem in stem for subtitle_stem in subtitle_stems):
            score += 10_000_000_000
        if re.search(r"(final|export|成片|发布|成稿|finished)", candidate.stem, re.IGNORECASE):
            score += 5_000_000_000
        if score > best_score:
            best_score = score
            best_video = candidate
    return best_video


def _pick_primary_subtitle(*, subtitle_files: list[Path], video_file: Path | None) -> Path | None:
    if not subtitle_files:
        return None
    if len(subtitle_files) == 1 or video_file is None:
        return subtitle_files[0]
    best = subtitle_files[0]
    best_score = -1.0
    video_stem = video_file.stem.lower()
    for candidate in subtitle_files:
        score = 0.0
        stem = candidate.stem.lower()
        if stem == video_stem:
            score += 1000
        if stem in video_stem or video_stem in stem:
            score += 500
        if candidate.suffix.lower() == ".srt":
            score += 50
        if score > best_score:
            best_score = score
            best = candidate
    return best


def _pick_primary_cover(*, cover_files: list[Path], video_file: Path | None) -> Path | None:
    if not cover_files:
        return None
    if len(cover_files) == 1:
        return cover_files[0]
    best = cover_files[0]
    best_score = -1.0
    video_stem = video_file.stem.lower() if video_file is not None else ""
    for candidate in cover_files:
        score = 0.0
        stem = candidate.stem.lower()
        if re.search(r"(cover|thumbnail|poster|封面)", stem, re.IGNORECASE):
            score += 1000
        if video_stem and (stem == video_stem or stem in video_stem or video_stem in stem):
            score += 500
        if score > best_score:
            best_score = score
            best = candidate
    return best


def _load_subtitle_items(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".srt":
        return _parse_srt_items(text)
    if suffix == ".vtt":
        return _parse_vtt_items(text)
    if suffix in {".ass", ".ssa"}:
        return _parse_ass_items(text)
    return []


def _parse_srt_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n"))
    for block in blocks:
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue
        timeline_line = lines[1] if re.search(r"-->", lines[1]) else lines[0]
        match = re.match(r"(?P<start>.+?)\s*-->\s*(?P<end>.+)", timeline_line)
        if not match:
            continue
        start_sec = _parse_timestamp(match.group("start"))
        end_sec = _parse_timestamp(match.group("end"))
        if start_sec is None or end_sec is None:
            continue
        text_lines = lines[2:] if timeline_line == lines[1] else lines[1:]
        subtitle_text = re.sub(r"<[^>]+>", "", " ".join(text_lines)).strip()
        if not subtitle_text:
            continue
        items.append(
            {
                "index": len(items),
                "start_time": start_sec,
                "end_time": end_sec,
                "text_raw": subtitle_text,
                "text_norm": subtitle_text,
                "text_final": subtitle_text,
            }
        )
    return items


def _parse_vtt_items(text: str) -> list[dict[str, Any]]:
    normalized = text.replace("WEBVTT", "").strip()
    return _parse_srt_items(normalized)


def _parse_ass_items(text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in text.replace("\r\n", "\n").splitlines():
        if not line.startswith("Dialogue:"):
            continue
        parts = line.split(",", 9)
        if len(parts) < 10:
            continue
        start_sec = _parse_timestamp(parts[1])
        end_sec = _parse_timestamp(parts[2])
        if start_sec is None or end_sec is None:
            continue
        subtitle_text = re.sub(r"\{[^}]+\}", "", parts[9]).replace("\\N", " ").strip()
        if not subtitle_text:
            continue
        items.append(
            {
                "index": len(items),
                "start_time": start_sec,
                "end_time": end_sec,
                "text_raw": subtitle_text,
                "text_norm": subtitle_text,
                "text_final": subtitle_text,
            }
        )
    return items


def _parse_timestamp(value: str) -> float | None:
    text = str(value or "").strip().replace(",", ".")
    match = re.match(r"(?:(?P<h>\d+):)?(?P<m>\d{1,2}):(?P<s>\d{1,2}(?:\.\d+)?)", text)
    if not match:
        return None
    hours = int(match.group("h") or 0)
    minutes = int(match.group("m") or 0)
    seconds = float(match.group("s") or 0.0)
    return hours * 3600 + minutes * 60 + seconds


def _format_tag_copy(tags: list[str], *, style: str) -> str:
    if not tags:
        return ""
    if style == "hashtags_space":
        return " ".join(tag if tag.startswith("#") else f"#{tag}" for tag in tags)
    return ", ".join(tags)


def _trim_to_display_units(text: str, limit: int) -> str:
    trimmed = str(text or "").strip()
    if not trimmed:
        return ""
    if _display_units(trimmed) <= limit:
        return trimmed
    current = []
    for char in trimmed:
        candidate = "".join(current) + char
        if _display_units(candidate) > limit:
            break
        current.append(char)
    return "".join(current).strip(" -|")


def _display_units(text: str) -> int:
    units = 0.0
    for char in str(text or ""):
        units += 0.5 if re.match(r"[A-Za-z0-9]", char) else 1.0
    return int(units) if units.is_integer() else int(units) + 1


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _sort_by_size_desc(path: Path) -> tuple[int, str]:
    return (-int(path.stat().st_size), path.name.lower())
