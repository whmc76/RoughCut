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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image

from roughcut.config import get_settings, llm_task_route
from roughcut.edit.subtitle_surfaces import subtitle_semantic_item_text
from roughcut.cover_title_contract import (
    build_cover_title_semantic_plan as _shared_build_cover_title_semantic_plan,
    cover_title_has_action_signal as _shared_cover_title_has_action_signal,
    cover_title_has_evidence_signal as _shared_cover_title_has_evidence_signal,
    cover_title_has_variant_signal as _shared_cover_title_has_variant_signal,
    cover_title_semantic_core as _shared_cover_title_semantic_core,
    dedupe_cover_title_layout_lines as _shared_dedupe_cover_title_layout_lines,
    normalize_cover_title_dedupe_signature as _shared_normalize_cover_title_dedupe_signature,
    resolve_cover_title_semantic_slot as _shared_resolve_cover_title_semantic_slot,
    strip_cover_action_suffix as _shared_strip_cover_action_suffix,
    strip_cover_brand_prefix as _shared_strip_cover_brand_prefix,
)
from roughcut.host.codex_proxy import resolve_codex_proxy_sibling_url, resolve_codex_proxy_token
from roughcut.intelligent_copy_layout import (
    MATERIAL_DIR_NAME,
    resolve_smart_copy_cover_candidates_sheet_path,
    resolve_smart_copy_cover_group_output_path,
    resolve_smart_copy_cover_group_request_path,
    resolve_smart_copy_cover_reference_image_paths,
    resolve_smart_copy_cover_source_image_path,
    resolve_smart_copy_cover_source_manifest_path,
    resolve_smart_copy_material_json_path,
    resolve_smart_copy_platform_body_path,
    resolve_smart_copy_platform_packaging_json_path,
    resolve_smart_copy_platform_titles_path,
    resolve_smart_copy_platform_tags_path,
    smart_copy_copy_dir,
    smart_copy_cover_candidates_sheet_path,
    smart_copy_cover_dir,
    smart_copy_cover_group_output_path,
    smart_copy_cover_group_reference_path,
    smart_copy_cover_reference_image_path,
    smart_copy_cover_source_image_path,
    smart_copy_cover_source_manifest_path,
    smart_copy_material_json_path,
    smart_copy_meta_dir,
    smart_copy_platform_body_path,
    smart_copy_platform_cover_path,
    smart_copy_platform_markdown_path,
    smart_copy_platform_packaging_json_path,
    smart_copy_platform_packaging_markdown_path,
    smart_copy_platform_tags_path,
    smart_copy_platform_titles_path,
)
from roughcut.media.output import _extract_frame, _overlay_title_layout, _probe_duration, _sample_cover_candidates, _title_style_tokens
from roughcut.packaging.library import list_packaging_assets
from roughcut.providers.image_generation import (
    CodexImageGenerationPending,
    _attempt_codex_imagegen_auto_completion,
    _record_codex_imagegen_request_bridge_error,
    generate_edited_cover_image,
)
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.review.intelligent_copy_cover_quality import assess_cover_publish_readiness
from roughcut.review.content_profile import (
    _build_fallback_engagement_question,
    _is_generic_engagement_question,
    _seed_profile_from_text,
    _subject_domain_from_subject_type,
    infer_content_profile,
    select_workflow_template,
)
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
from roughcut.publication_packaging import (
    derive_publication_cover_slots,
    publication_packaging_entry_publish_ready,
)
from roughcut.publication_intelligence import (
    _build_collection_management_plan,
    _choose_real_collection_name,
    _publication_policy_for_creator,
    build_cached_publication_scheme,
)
from roughcut.review.platform_copy import PLATFORM_ORDER, generate_platform_packaging, save_platform_packaging_markdown
from roughcut.review.intelligent_copy_scoring import score_description, score_title_candidate
from roughcut.review.intelligent_copy_templates import (
    build_constraint_only_platform_description,
    build_constraint_only_title_candidates,
)
from roughcut.review.platform_copy import build_fallback_description
from roughcut.review.intelligent_copy_topics import IntelligentCopyTopicSpec, match_intelligent_copy_topic

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
TITLE_OPTION_LIMIT = 3
IntelligentCopyProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
MATERIAL_SELF_HEAL_MAX_PASSES = 2


def _intelligent_copy_semantic_text(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    return subtitle_semantic_item_text(
        item,
        generic_fallback_text=str(item.get("text") or item.get("raw_text") or "").strip(),
    )

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

COVER_CONTENT_STRATEGY_PROFILES: dict[str, dict[str, Any]] = {
    "unboxing_single_subject_v1": {
        "description": "开箱单主体：突出唯一主角度和上手质感。",
    },
    "tutorial_demo_v1": {
        "description": "教程演示：突出动作步骤和可读信息层级。",
    },
    "generic_showcase_v1": {
        "description": "通用展示：主体真实清晰，标题结构稳定。",
    },
}


SUBJECT_FIDELITY_SCHEME_PROFILES: dict[str, dict[str, Any]] = {
    "generic_subject_fidelity_v1": {
        "description": "通用主体保真：不改变主体身份、几何关系、主要部件布局和状态映射。",
        "edit_budget_prompt": (
            "主体编辑预算必须极小：只允许做清晰度、光影、材质质感和背景氛围增强；"
            "不允许重设计主体几何、主要部件数量、相对位置、表面分区、状态映射或版本对应关系。"
        ),
        "generic_constraints": [
            "主体一致性是最高优先级：不改商品身份、不改品牌归属、不改核心结构。",
            "保留主体主要轮廓、比例关系、主要部件数量与相对位置，不要凭空增删硬件或结构层级。",
            "保留主体表面分区、材质关系和版本差异，不要把不同版本特征互换。",
        ],
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
        "cover_size": (1080, 1440),
        "title_style": "comic_boom",
        "cover_style": "tech_showcase",
        "rule_note": "优先竖版 3:4，结果先行，避免危险动作引导。",
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
        "cover_size": (1080, 1440),
        "title_style": "comic_boom",
        "cover_style": "documentary",
        "rule_note": "按作品描述输出，优先竖版 3:4，口语直给，少一点精修腔。",
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
        "cover_size": (1080, 1440),
        "title_style": "documentary_stamp",
        "cover_style": "documentary",
        "rule_note": "按作品描述输出，偏稳妥可信，优先竖版 3:4，少用夸张网感词。",
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
        "cover_size": (1440, 1080),
        "title_style": "documentary_stamp",
        "cover_style": "documentary",
        "rule_note": "偏资讯摘要和观点导语，优先 4:3 横版，适合结论先行。",
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
        "cover_size": (1440, 1080),
        "title_style": "chrome_impact",
        "cover_style": "tech_showcase",
        "rule_note": "无独立标题，正文要在 280 字内，hashtags 建议克制；默认不强调独立 16:9 封面。",
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


async def _resolve_packaging_and_cover_context(
    *,
    video_path: Path,
    material_dir: Path,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
    existing_packaging: dict[str, Any] | None,
    selected_platform_keys: list[str],
    platforms_requiring_regeneration: list[str],
    resolved_copy_style: str,
    existing_result: dict[str, Any] | None,
    existing_cover_path: Path | None,
) -> dict[str, Any]:
    seed_generated_packaging: dict[str, Any] | None = None
    if platforms_requiring_regeneration:
        seed_generated_packaging = _filter_intelligent_copy_packaging(
            _build_intelligent_copy_packaging(
                content_profile=content_profile,
                copy_brief=copy_brief,
            ),
            platforms_requiring_regeneration,
        )
    cover_seed_packaging = _merge_resume_packaging(
        existing_packaging=existing_packaging,
        generated_packaging=seed_generated_packaging,
        platform_keys=selected_platform_keys,
    )

    cover_source_task = asyncio.create_task(
        _maybe_await(
            _prepare_intelligent_copy_cover_source(
                video_path=video_path,
                material_dir=material_dir,
                content_profile=content_profile,
                packaging=cover_seed_packaging,
            )
        )
    )
    packaging_task: asyncio.Task[dict[str, Any]] | None = None
    if platforms_requiring_regeneration:
        packaging_task = asyncio.create_task(
            _resolve_generate_platform_packaging(
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
                        "平台差异只能来自规则约束，不能主动注入不同内容角度或强制人设。",
                    ],
                },
            )
        )

    generated_packaging: dict[str, Any] | None = None
    if packaging_task is not None:
        fallback_generated_packaging = seed_generated_packaging or _filter_intelligent_copy_packaging(
            _build_intelligent_copy_packaging(
                content_profile=content_profile,
                copy_brief=copy_brief,
            ),
            platforms_requiring_regeneration,
        )
        try:
            generated_packaging = _filter_intelligent_copy_packaging(
                await asyncio.wait_for(packaging_task, timeout=210),
                platforms_requiring_regeneration,
            )
        except Exception:
            packaging_task.cancel()
            generated_packaging = fallback_generated_packaging
    packaging = _merge_resume_packaging(
        existing_packaging=existing_packaging,
        generated_packaging=generated_packaging,
        platform_keys=selected_platform_keys,
    )
    cover_source = await cover_source_task
    cover_source_manifest = _load_cover_source_manifest(smart_copy_cover_source_manifest_path(material_dir))
    cover_reference_paths = _resolve_cover_reference_paths(
        material_dir=material_dir,
        cover_source_path=cover_source,
        cover_source_manifest=cover_source_manifest,
    )
    cover_brief = await _resolve_restored_cover_brief(
        existing_result,
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=existing_cover_path,
    )
    return {
        "packaging": packaging,
        "generated_packaging": generated_packaging,
        "cover_source": cover_source,
        "cover_reference_paths": cover_reference_paths,
        "cover_source_manifest": cover_source_manifest,
        "cover_brief": cover_brief,
    }


def _prepare_structured_smart_copy_layout(material_dir: Path) -> None:
    smart_copy_meta_dir(material_dir).mkdir(parents=True, exist_ok=True)
    smart_copy_copy_dir(material_dir).mkdir(parents=True, exist_ok=True)
    smart_copy_cover_dir(material_dir).mkdir(parents=True, exist_ok=True)
    shutil.rmtree(material_dir / "_publication_runtime", ignore_errors=True)

    def move_legacy(legacy_path: Path, target_path: Path) -> None:
        if not legacy_path.exists() or not legacy_path.is_file():
            return
        if target_path.exists():
            return
        target_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(legacy_path), str(target_path))
        except OSError:
            return

    for legacy_name, target_path in (
        ("smart-copy.json", smart_copy_material_json_path(material_dir)),
        ("platform-packaging.json", smart_copy_platform_packaging_json_path(material_dir)),
        ("platform-packaging.md", smart_copy_platform_packaging_markdown_path(material_dir)),
        ("00-highlight-cover-source.jpg", smart_copy_cover_source_image_path(material_dir)),
        ("00-highlight-cover-source.json", smart_copy_cover_source_manifest_path(material_dir)),
        ("00-highlight-candidates-sheet.jpg", smart_copy_cover_candidates_sheet_path(material_dir)),
    ):
        move_legacy(material_dir / legacy_name, target_path)

    for legacy_path in sorted(material_dir.glob("00-cover-*")):
        if legacy_path.is_file():
            move_legacy(legacy_path, smart_copy_cover_dir(material_dir) / legacy_path.name)
    for suffix in ("titles", "body", "tags"):
        for legacy_path in sorted(material_dir.glob(f"*-{suffix}.txt")):
            if legacy_path.is_file():
                move_legacy(legacy_path, smart_copy_copy_dir(material_dir) / legacy_path.name)


def _prune_legacy_smart_copy_root(material_dir: Path) -> None:
    def prune_duplicate(legacy_path: Path, target_path: Path) -> None:
        if not legacy_path.exists() or not legacy_path.is_file():
            return
        if not target_path.exists() or not target_path.is_file():
            return
        try:
            legacy_path.unlink(missing_ok=True)
        except OSError:
            return

    for legacy_name, target_path in (
        ("smart-copy.json", smart_copy_material_json_path(material_dir)),
        ("platform-packaging.json", smart_copy_platform_packaging_json_path(material_dir)),
        ("platform-packaging.md", smart_copy_platform_packaging_markdown_path(material_dir)),
        ("00-highlight-cover-source.jpg", smart_copy_cover_source_image_path(material_dir)),
        ("00-highlight-cover-source.json", smart_copy_cover_source_manifest_path(material_dir)),
        ("00-highlight-candidates-sheet.jpg", smart_copy_cover_candidates_sheet_path(material_dir)),
    ):
        prune_duplicate(material_dir / legacy_name, target_path)

    for legacy_path in sorted(material_dir.glob("00-cover-*")):
        if legacy_path.is_file():
            prune_duplicate(legacy_path, smart_copy_cover_dir(material_dir) / legacy_path.name)
    for suffix in ("titles", "body", "tags"):
        for legacy_path in sorted(material_dir.glob(f"*-{suffix}.txt")):
            if legacy_path.is_file():
                prune_duplicate(legacy_path, smart_copy_copy_dir(material_dir) / legacy_path.name)


def _synchronize_publishable_root_files(*, material_dir: Path, material_entries: list[tuple[int, dict[str, Any]]]) -> None:
    expected_files: set[str] = set()
    for index, material in material_entries:
        platform_key = str(material.get("key") or "").strip()
        if not platform_key:
            continue
        expected_files.add(smart_copy_platform_markdown_path(material_dir, index, platform_key).name)
        if str(material.get("cover_path") or "").strip():
            expected_files.add(smart_copy_platform_cover_path(material_dir, index, platform_key).name)
    for candidate in material_dir.iterdir():
        if not candidate.is_file():
            continue
        name = candidate.name
        if re.fullmatch(r"\d{2}-.+-cover\.jpg", name, re.IGNORECASE) or re.fullmatch(r"\d{2}-.+\.md", name, re.IGNORECASE):
            if name not in expected_files:
                candidate.unlink(missing_ok=True)


async def generate_intelligent_copy(
    folder_path: str,
    *,
    copy_style: str | None = None,
    platforms: list[str] | None = None,
    use_existing_cover: bool = False,
    creator_profile_id: str | None = None,
    creator_profile_name: str | None = None,
    creator_profile: dict[str, Any] | None = None,
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
    _prepare_structured_smart_copy_layout(material_dir)
    existing_result = _load_existing_intelligent_copy_result(material_dir)
    stale_existing_result_detected = bool(existing_result) and not _existing_intelligent_copy_result_matches_inputs(
        existing_result,
        video_path=video_path,
        subtitle_path=subtitle_path,
    )
    if stale_existing_result_detected:
        existing_result = None
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
    cover_context = await _resolve_packaging_and_cover_context(
        video_path=video_path,
        material_dir=material_dir,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        existing_packaging=existing_packaging,
        selected_platform_keys=selected_platform_keys,
        platforms_requiring_regeneration=platforms_requiring_regeneration,
        resolved_copy_style=resolved_copy_style,
        existing_result=existing_result,
        existing_cover_path=cover_path,
    )
    packaging = dict(cover_context["packaging"] or {})
    creator_publication_policy = _build_intelligent_copy_creator_publication_policy(
        creator_profile=creator_profile,
        creator_profile_id=creator_profile_id,
        creator_profile_name=creator_profile_name,
        packaging=packaging,
        requested_platform_keys=selected_platform_keys,
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
    markdown_path = smart_copy_platform_packaging_markdown_path(material_dir)
    platform_packaging_json_path = smart_copy_platform_packaging_json_path(material_dir)
    json_path = smart_copy_material_json_path(material_dir)
    save_platform_packaging_markdown(markdown_path, packaging)
    cover_source = cover_context["cover_source"]
    cover_reference_paths = list(cover_context.get("cover_reference_paths") or [])
    cover_source_manifest = dict(cover_context["cover_source_manifest"] or {})
    cover_brief = dict(cover_context["cover_brief"] or {})
    cover_brief = _annotate_cover_strategy_axes(
        cover_brief,
        creator_profile_name=str(creator_profile_name or "").strip(),
        copy_brief=copy_brief,
        content_profile=content_profile,
    )
    base_result = {
        "folder_path": display_folder_path,
        "material_dir": str(material_dir),
        "markdown_path": str(markdown_path),
        "platform_packaging_json_path": str(platform_packaging_json_path),
        "json_path": str(json_path),
        "source_signature": _build_intelligent_copy_source_signature(
            video_path=video_path,
            subtitle_path=subtitle_path,
        ),
        "cover_source_path": str(cover_source) if cover_source else None,
        "cover_reference_paths": [str(path) for path in cover_reference_paths],
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
        "warnings": [
            *list(inspection.get("warnings") or []),
            *(
                ["已忽略与当前视频/字幕不匹配的旧 smart-copy 结果，当前物料已按最新输入重新生成。"]
                if stale_existing_result_detected
                else []
            ),
        ],
        "creator_profile_id": str(creator_profile_id or "").strip() or None,
        "creator_profile_name": str(creator_profile_name or "").strip() or None,
        "publication_policy": creator_publication_policy,
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
        reference_image_paths=cover_reference_paths,
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
        _apply_creator_publication_policy_to_material(
            platform_key=platform_key,
            material=material,
            platform_payload=packaging.get("platforms", {}).get(platform_key) if isinstance(packaging.get("platforms"), dict) else {},
            creator_publication_policy=creator_publication_policy,
            creator_profile_name=creator_profile_name,
            rules=rules,
        )
        serial = _resolve_platform_material_serial(platform_key)
        cover_output_path = smart_copy_platform_cover_path(material_dir, serial, platform_key)
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
                reference_image_paths=cover_reference_paths,
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
        else:
            material.pop("cover_path", None)
        if cover_generation:
            material["cover_generation"] = cover_generation
        material["blocking_reasons"] = platform_blocks
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        blocking_reasons.extend(f"{rules['label']}：{reason}" for reason in platform_blocks)
        if not (reused_from_existing and _platform_material_files_exist(material_dir=material_dir, index=serial, material=material)):
            _write_platform_material_files(material_dir=material_dir, index=serial, material=material)
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

    await _settle_pending_cover_generation(
        material_dir=material_dir,
        cover_group_cache=cover_group_cache,
        platform_materials=platform_materials,
        progress_callback=progress_callback,
        inspection=inspection,
        display_folder_path=display_folder_path,
    )

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=platform_materials,
    )
    material_generation_contract = _build_material_generation_contract(
        platform_materials,
        requested_platforms=publish_platforms,
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
    result = {
        **base_result,
        "copy_brief": copy_brief,
        "platforms": platform_materials,
    }
    _apply_material_contract_export_state(result, material_contract, blocking_reasons=blocking_reasons)
    result["cover_matrix"] = _serialize_cover_matrix(cover_group_cache)
    result["material_validation"] = material_validation
    result["material_generation_contract"] = material_generation_contract
    result["material_contract"] = material_contract
    _apply_material_generation_export_state(
        result,
        material_generation_contract,
        material_contract=material_contract,
    )
    terminal_status = _material_contract_terminal_status(material_contract)
    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=publish_platforms,
        cover_matrix=result["cover_matrix"],
    )
    _synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (_resolve_platform_material_serial(material.get("key")), material)
            for material in platform_materials
        ],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_legacy_smart_copy_root(material_dir)
    _sync_materialized_smart_copy_to_host(
        requested_folder_path=str(inspection.get("folder_path") or folder_path),
        material_dir=material_dir,
    )
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
    json_path = resolve_smart_copy_material_json_path(material_dir)
    if not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _build_intelligent_copy_source_signature(*, video_path: Path, subtitle_path: Path) -> dict[str, Any]:
    return {
        "video": _build_intelligent_copy_source_file_signature(video_path),
        "subtitle": _build_intelligent_copy_source_file_signature(subtitle_path),
    }


def _build_intelligent_copy_source_file_signature(path: Path) -> dict[str, Any]:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    try:
        stat = resolved.stat()
    except OSError:
        return {
            "path": str(resolved),
            "exists": False,
        }
    return {
        "path": str(resolved),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _existing_intelligent_copy_result_matches_inputs(
    payload: dict[str, Any] | None,
    *,
    video_path: Path,
    subtitle_path: Path,
) -> bool:
    if not isinstance(payload, dict):
        return False
    recorded_signature = payload.get("source_signature")
    if not isinstance(recorded_signature, dict):
        return False
    current_signature = _build_intelligent_copy_source_signature(
        video_path=video_path,
        subtitle_path=subtitle_path,
    )
    return recorded_signature == current_signature


def _load_existing_intelligent_copy_packaging(
    *,
    material_dir: Path,
    platform_keys: list[str],
    fallback_result: dict[str, Any] | None,
) -> dict[str, Any]:
    platform_packaging_path = resolve_smart_copy_platform_packaging_json_path(material_dir)
    if platform_packaging_path.exists():
        try:
            payload = json.loads(platform_packaging_path.read_text(encoding="utf-8"))
        except Exception:
            payload = None
        normalized = _normalize_existing_platform_packaging_payload(payload, platform_keys=platform_keys)
        normalized = _supplement_existing_packaging_from_material_files(
            normalized,
            material_dir=material_dir,
            platform_keys=platform_keys,
            payload_context=payload if isinstance(payload, dict) else {},
        )
        if normalized:
            return normalized
    fallback_packaging = _packaging_from_existing_intelligent_copy_result(fallback_result, platform_keys=platform_keys)
    return _supplement_existing_packaging_from_material_files(
        fallback_packaging,
        material_dir=material_dir,
        platform_keys=platform_keys,
        payload_context=fallback_result if isinstance(fallback_result, dict) else {},
    )


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
    creator_profile_name: str | None = None,
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
    material_dir.mkdir(parents=True, exist_ok=True)
    _prepare_structured_smart_copy_layout(material_dir)
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
        fallback_cover_source = resolve_smart_copy_cover_source_image_path(material_dir)
        if fallback_cover_source.exists() and fallback_cover_source.is_file():
            existing_verified_source_path = fallback_cover_source.resolve()
    cover_source = None
    cover_reference_paths: list[Path] = []
    if not refresh_cover_source:
        cover_source = existing_verified_source_path
        if not cover_source_manifest:
            cover_source_manifest = _load_cover_source_manifest(resolve_smart_copy_cover_source_manifest_path(material_dir))
        cover_reference_paths = _resolve_cover_reference_paths(
            material_dir=material_dir,
            cover_source_path=cover_source,
            cover_source_manifest=cover_source_manifest,
        )
        if not cover_source or not cover_source.exists():
            cover_source = None
        elif _cover_source_manifest_is_verified(cover_source_manifest):
            cover_source = await _restore_verified_cover_source_snapshot(
                video_path=video_path,
                source_path=cover_source,
                manifest_path=resolve_smart_copy_cover_source_manifest_path(material_dir),
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
        cover_source_manifest = _load_cover_source_manifest(resolve_smart_copy_cover_source_manifest_path(material_dir))
        cover_reference_paths = _resolve_cover_reference_paths(
            material_dir=material_dir,
            cover_source_path=cover_source,
            cover_source_manifest=cover_source_manifest,
        )
    cover_brief = await _resolve_restored_cover_brief(
        existing_result,
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=cover_path,
    )
    existing_creator_name = str(creator_profile_name or "").strip() or (
        str(existing_result.get("creator_profile_name") or "").strip()
        or str(((existing_result.get("publication_context") or {}) if isinstance(existing_result.get("publication_context"), dict) else {}).get("creator_profile_name") or "").strip()
    )
    cover_brief = _annotate_cover_strategy_axes(
        cover_brief,
        creator_profile_name=existing_creator_name,
        copy_brief=copy_brief,
        content_profile=content_profile,
    )
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
        "cover_reference_paths": cover_reference_paths,
        "cover_source_manifest": cover_source_manifest,
        "cover_brief": cover_brief,
    }


async def rerender_existing_intelligent_copy_cover_groups(
    folder_path: str,
    *,
    platforms: list[str] | None = None,
    refresh_cover_source: bool = False,
    creator_profile_name: str | None = None,
) -> dict[str, Any]:
    context = await _restore_existing_intelligent_cover_generation_context(
        folder_path,
        platforms=platforms,
        refresh_cover_source=refresh_cover_source,
        creator_profile_name=creator_profile_name,
    )
    material_dir: Path = context["material_dir"]
    video_path: Path = context["video_path"]
    existing_result: dict[str, Any] = context["existing_result"]
    all_platform_keys: list[str] = list(context["all_platform_keys"] or [])
    selected_platform_keys: list[str] = list(context["selected_platform_keys"] or [])
    packaging: dict[str, Any] = context["packaging"]
    content_profile: dict[str, Any] = context["content_profile"]
    cover_source = context["cover_source"]
    cover_reference_paths = list(context.get("cover_reference_paths") or [])
    cover_brief: dict[str, Any] = context["cover_brief"]
    cover_source_manifest = context["cover_source_manifest"]

    platform_items = existing_result.get("platforms") if isinstance(existing_result.get("platforms"), list) else []
    existing_item_map = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in platform_items
        if isinstance(item, dict) and _normalize_internal_publish_platform_key(item.get("key"))
    }
    packaging_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    cover_group_cache: dict[str, dict[str, Any]] = {}
    cover_group_title = str(cover_brief.get("cover_title") or "") or _resolve_cover_group_title(packaging=packaging, content_profile=content_profile)
    await _prime_standard_cover_matrix_groups(
        cache=cover_group_cache,
        material_dir=material_dir,
        video_path=video_path,
        source_image_path=cover_source,
        reference_image_paths=cover_reference_paths,
        existing_cover_path=None,
        title=cover_group_title,
        cover_brief=cover_brief,
        use_existing_cover=False,
    )
    rerendered_materials: dict[str, dict[str, Any]] = {}
    publish_platforms = [item for item in PLATFORM_ORDER if item[0] in selected_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]
    for platform_key, _label, _body_label, _tag_label in publish_platforms:
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        material = _restore_or_build_platform_material(
            platform_key=platform_key,
            rules=rules,
            existing_item=existing_item_map.get(platform_key),
            packaging_platforms=packaging_platforms,
        )
        if not isinstance(material, dict):
            continue
        serial = _resolve_platform_material_serial(platform_key)
        cover_output_path = material_dir / f"{serial:02d}-{platform_key}-cover.jpg"
        cover_group = _resolve_platform_cover_group(platform_key=platform_key, rules=rules)
        cover_generation = await _render_or_reuse_platform_cover_group(
            cache=cover_group_cache,
            material_dir=material_dir,
            output_path=cover_output_path,
            video_path=video_path,
            source_image_path=cover_source,
            reference_image_paths=cover_reference_paths,
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
        else:
            material.pop("cover_path", None)
        if cover_generation:
            material["cover_generation"] = cover_generation
        material["blocking_reasons"] = platform_blocks
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)
        rerendered_materials[platform_key] = material

    await _drain_pending_cover_group_requests(cache=cover_group_cache, material_dir=material_dir)
    _refresh_cover_group_cache_status(cache=cover_group_cache, material_dir=material_dir)
    for material in rerendered_materials.values():
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        serial = _resolve_platform_material_serial(material.get("key"))
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)

    platform_materials: list[dict[str, Any]] = []
    for platform_key, _label, _body_label, _tag_label in [item for item in PLATFORM_ORDER if item[0] in all_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]:
        if platform_key in rerendered_materials:
            platform_materials.append(rerendered_materials[platform_key])
            continue
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        material = _restore_or_build_platform_material(
            platform_key=platform_key,
            rules=rules,
            existing_item=existing_item_map.get(platform_key),
            packaging_platforms=packaging_platforms,
        )
        if not isinstance(material, dict):
            continue
        _restore_platform_cover_path(material=material, material_dir=material_dir, index=_resolve_platform_material_serial(platform_key))
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        platform_materials.append(material)

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
    )
    material_generation_contract = _build_material_generation_contract(
        platform_materials,
        requested_platforms=all_platform_keys,
    )
    material_contract = _build_material_contract(
        platform_materials,
        requested_platforms=all_platform_keys,
    )
    updated_result = dict(existing_result)
    updated_result["platforms"] = [_material_to_result_payload(material) for material in platform_materials]
    updated_result["cover_source_path"] = str(cover_source) if cover_source else None
    updated_result["cover_reference_paths"] = [str(path) for path in cover_reference_paths]
    updated_result["cover_source_manifest"] = cover_source_manifest
    updated_result["cover_brief"] = cover_brief
    updated_result["creator_profile_name"] = str(creator_profile_name or context["existing_result"].get("creator_profile_name") or "").strip() or None
    publication_context = (
        dict(updated_result.get("publication_context") or {})
        if isinstance(updated_result.get("publication_context"), dict)
        else {}
    )
    updated_result["publication_context"] = {
        **publication_context,
        "creator_profile_name": updated_result["creator_profile_name"],
    }
    updated_result["cover_matrix"] = _serialize_cover_matrix(cover_group_cache)
    updated_result["material_validation"] = material_validation
    updated_result["material_generation_contract"] = material_generation_contract
    updated_result["material_contract"] = material_contract
    _apply_material_contract_export_state(
        updated_result,
        material_contract,
        blocking_reasons=list(material_contract.get("blocking_reasons") or []),
    )
    _apply_material_generation_export_state(
        updated_result,
        material_generation_contract,
        material_contract=material_contract,
    )

    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
        cover_matrix=updated_result["cover_matrix"],
    )
    platform_packaging_json_path = smart_copy_platform_packaging_json_path(material_dir)
    json_path = smart_copy_material_json_path(material_dir)
    _synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (_resolve_platform_material_serial(material.get("key")), material)
            for material in platform_materials
        ],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_legacy_smart_copy_root(material_dir)
    _sync_materialized_smart_copy_to_host(
        requested_folder_path=str(context["inspection"].get("folder_path") or folder_path),
        material_dir=material_dir,
    )
    return updated_result


async def refresh_existing_intelligent_copy_cover_current_state(
    folder_path: str,
    *,
    creator_profile_name: str | None = None,
) -> dict[str, Any]:
    context = await _restore_existing_intelligent_cover_generation_context(
        folder_path,
        platforms=None,
        refresh_cover_source=False,
        creator_profile_name=creator_profile_name,
    )
    material_dir: Path = context["material_dir"]
    existing_result: dict[str, Any] = context["existing_result"]
    all_platform_keys: list[str] = list(context["all_platform_keys"] or [])
    packaging: dict[str, Any] = context["packaging"]
    cover_source = context["cover_source"]
    cover_brief: dict[str, Any] = context["cover_brief"]
    cover_source_manifest = context["cover_source_manifest"]

    cover_group_cache = _restore_standard_cover_matrix_group_cache_from_disk(material_dir=material_dir)
    _refresh_cover_group_cache_status(cache=cover_group_cache, material_dir=material_dir)
    for group in _resolve_standard_cover_matrix_groups():
        group_key = str(group.get("key") or "").strip()
        if not group_key:
            continue
        generation = cover_group_cache.get(group_key)
        if not isinstance(generation, dict):
            continue
        cover_group = generation.get("cover_group") if isinstance(generation.get("cover_group"), dict) else {}
        group_output_path = _resolve_existing_material_cover_path(
            cover_group.get("cover_path") or generation.get("output_path"),
            material_dir=material_dir,
        )
        if group_output_path is None:
            continue
        representative_platform = str(group.get("representative_platform") or "bilibili").strip()
        group_rules = dict(PLATFORM_PUBLISH_RULES.get(representative_platform) or PLATFORM_PUBLISH_RULES["bilibili"])
        group_rules["label"] = str(group.get("label") or group_rules.get("label") or representative_platform)
        group_rules["cover_size"] = tuple(group.get("cover_size") or group_rules["cover_size"])
        group_rules["visual_instruction"] = str(
            group.get("visual_instruction") or group_rules.get("visual_instruction") or ""
        ).strip()
        refreshed_group = await _revalidate_existing_cover_generation_request(
            generation=generation,
            output_path=group_output_path,
            material_dir=material_dir,
            rules=group_rules,
            cover_brief=cover_brief,
        )
        if isinstance(refreshed_group, dict):
            refreshed_group["cover_group"] = dict(cover_group or {})
            cover_group_cache[group_key] = refreshed_group

    platform_items = existing_result.get("platforms") if isinstance(existing_result.get("platforms"), list) else []
    existing_item_map = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in platform_items
        if isinstance(item, dict) and _normalize_internal_publish_platform_key(item.get("key"))
    }
    platform_materials: list[dict[str, Any]] = []
    for platform_key, _label, _body_label, _tag_label in [item for item in PLATFORM_ORDER if item[0] in all_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]:
        item = existing_item_map.get(platform_key)
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not isinstance(item, dict) or not rules:
            continue
        material = _normalize_existing_platform_material(item, rules=rules)
        _restore_platform_cover_path(material=material, material_dir=material_dir, index=_resolve_platform_material_serial(platform_key))
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        _refresh_cover_group_reuse_platform_derivative(
            material=material,
            material_dir=material_dir,
            rules=rules,
        )
        cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else None
        cover_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
        if cover_generation is not None and cover_path is not None:
            refreshed_generation = await _revalidate_existing_cover_generation_request(
                generation=cover_generation,
                output_path=cover_path,
                material_dir=material_dir,
                rules=rules,
                cover_brief=cover_brief,
            )
            if isinstance(refreshed_generation, dict):
                material["cover_generation"] = refreshed_generation
        material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        serial = _resolve_platform_material_serial(material.get("key"))
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)
        platform_materials.append(material)

    material_validation = _run_material_self_healing(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
    )
    material_generation_contract = _build_material_generation_contract(
        platform_materials,
        requested_platforms=all_platform_keys,
    )
    material_contract = _build_material_contract(
        platform_materials,
        requested_platforms=all_platform_keys,
    )
    updated_result = dict(existing_result)
    updated_result["platforms"] = [_material_to_result_payload(material) for material in platform_materials]
    updated_result["cover_source_path"] = str(cover_source) if cover_source else None
    updated_result["cover_reference_paths"] = [str(path) for path in cover_reference_paths]
    updated_result["cover_source_manifest"] = cover_source_manifest
    updated_result["cover_brief"] = cover_brief
    updated_result["creator_profile_name"] = str(creator_profile_name or existing_result.get("creator_profile_name") or "").strip() or None
    publication_context = (
        dict(updated_result.get("publication_context") or {})
        if isinstance(updated_result.get("publication_context"), dict)
        else {}
    )
    updated_result["publication_context"] = {
        **publication_context,
        "creator_profile_name": updated_result["creator_profile_name"],
    }
    updated_result["cover_matrix"] = _serialize_cover_matrix(cover_group_cache)
    updated_result["material_validation"] = material_validation
    updated_result["material_generation_contract"] = material_generation_contract
    updated_result["material_contract"] = material_contract
    _apply_material_contract_export_state(
        updated_result,
        material_contract,
        blocking_reasons=list(material_contract.get("blocking_reasons") or []),
    )
    _apply_material_generation_export_state(
        updated_result,
        material_generation_contract,
        material_contract=material_contract,
    )

    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=platform_materials,
        requested_platforms=all_platform_keys,
        cover_matrix=updated_result["cover_matrix"],
    )
    platform_packaging_json_path = smart_copy_platform_packaging_json_path(material_dir)
    json_path = smart_copy_material_json_path(material_dir)
    _synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (_resolve_platform_material_serial(material.get("key")), material)
            for material in platform_materials
        ],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_legacy_smart_copy_root(material_dir)
    _sync_materialized_smart_copy_to_host(
        requested_folder_path=str(context["inspection"].get("folder_path") or folder_path),
        material_dir=material_dir,
    )
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
    material_dir.mkdir(parents=True, exist_ok=True)
    _prepare_structured_smart_copy_layout(material_dir)
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
    packaging_platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}

    upgraded_materials: list[dict[str, Any]] = []
    for index, platform_key in enumerate(selected_platform_keys, start=1):
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        material = _restore_or_build_platform_material(
            platform_key=platform_key,
            rules=rules,
            existing_item=existing_item_map.get(platform_key),
            packaging_platforms=packaging_platforms,
        )
        if not isinstance(material, dict):
            continue
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
    material_generation_contract = _build_material_generation_contract(
        upgraded_materials,
        requested_platforms=selected_platform_keys,
    )
    material_contract = _build_material_contract(
        upgraded_materials,
        requested_platforms=selected_platform_keys,
    )
    blocking_reasons = list(material_contract.get("blocking_reasons") or [])
    platform_packaging_json_path = smart_copy_platform_packaging_json_path(material_dir)
    json_path = smart_copy_material_json_path(material_dir)

    updated_result = dict(existing_result)
    updated_result["platforms"] = [
        _material_to_result_payload(material)
        for material in upgraded_materials
    ]
    _apply_material_contract_export_state(
        updated_result,
        material_contract,
        blocking_reasons=blocking_reasons,
    )
    updated_result["material_validation"] = material_validation
    updated_result["material_generation_contract"] = material_generation_contract
    updated_result["material_contract"] = material_contract
    _apply_material_generation_export_state(
        updated_result,
        material_generation_contract,
        material_contract=material_contract,
    )
    updated_result["platform_packaging_json_path"] = str(platform_packaging_json_path)
    updated_result["json_path"] = str(json_path)
    updated_result["creator_profile_id"] = resolved_creator_profile_id or None
    updated_result["creator_profile_name"] = resolved_creator_profile_name or None
    updated_result["publication_context"] = {
        "creator_profile_id": resolved_creator_profile_id or None,
        "creator_profile_name": resolved_creator_profile_name or None,
    }
    if isinstance(existing_result.get("cover_brief"), dict):
        updated_result["cover_brief"] = _annotate_cover_strategy_axes(
            dict(existing_result.get("cover_brief") or {}),
            creator_profile_name=resolved_creator_profile_name or str(existing_result.get("creator_profile_name") or "").strip(),
            copy_brief=None,
            content_profile=(
                dict(existing_result.get("content_profile_summary") or {})
                if isinstance(existing_result.get("content_profile_summary"), dict)
                else None
            ),
        )

    packaging_export = _build_platform_packaging_export(
        packaging=packaging,
        platform_materials=upgraded_materials,
        requested_platforms=selected_platform_keys,
        cover_matrix=dict(updated_result.get("cover_matrix") or {}),
    )
    _synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (_resolve_platform_material_serial(material.get("key")), material)
            for material in upgraded_materials
        ],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_legacy_smart_copy_root(material_dir)
    _sync_materialized_smart_copy_to_host(
        requested_folder_path=str(folder_path or ""),
        material_dir=material_dir,
    )
    return updated_result


def promote_platform_preview_to_intelligent_copy_result(
    folder_path: str,
    *,
    preview_payload: dict[str, Any] | None = None,
    preview_path: str | None = None,
    platforms: list[str] | None = None,
    creator_profile_id: str | None = None,
    creator_profile_name: str | None = None,
    browser: str = "chrome",
) -> dict[str, Any]:
    material_dir = _resolve_existing_material_dir(folder_path)
    material_dir.mkdir(parents=True, exist_ok=True)
    _prepare_structured_smart_copy_layout(material_dir)

    payload: dict[str, Any] | None = preview_payload if isinstance(preview_payload, dict) else None
    if payload is None:
        preview_file = Path(str(preview_path or "").strip().strip('"')).expanduser()
        if not preview_file.exists():
            raise ValueError("待提升的 preview JSON 不存在。")
        try:
            loaded = json.loads(preview_file.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError("待提升的 preview JSON 无法读取。") from exc
        if not isinstance(loaded, dict):
            raise ValueError("待提升的 preview JSON 结构无效。")
        payload = loaded

    preview_platforms = payload.get("platforms") if isinstance(payload.get("platforms"), dict) else {}
    if not isinstance(preview_platforms, dict) or not preview_platforms:
        raise ValueError("preview JSON 未包含可提升的平台文案。")

    selected_platform_keys = _resolve_intelligent_copy_platform_keys(platforms) if platforms else [
        key
        for key in (_normalize_internal_publish_platform_key(item) for item in preview_platforms.keys())
        if key and PLATFORM_PUBLISH_RULES.get(key)
    ]
    if not selected_platform_keys:
        raise ValueError("preview JSON 中没有可提升的平台文案。")

    existing_result = _load_existing_intelligent_copy_result(material_dir)
    if not isinstance(existing_result, dict):
        raise ValueError("未找到可写回的 smart-copy.json。")
    resolved_creator_profile_id, resolved_creator_profile_name = _resolve_upgrade_creator_context(
        existing_result=existing_result,
        creator_profile_id=creator_profile_id,
        creator_profile_name=creator_profile_name,
    )
    all_platform_keys = _resolve_upgrade_platform_keys(existing_result, platforms=None)
    for key in selected_platform_keys:
        if key not in all_platform_keys:
            all_platform_keys.append(key)

    existing_packaging = _load_existing_intelligent_copy_packaging(
        material_dir=material_dir,
        platform_keys=all_platform_keys,
        fallback_result=existing_result,
    )
    resolved_platform_options = _resolve_upgrade_platform_options(
        packaging=existing_packaging,
        existing_result=existing_result,
        material_dir=material_dir,
        platform_keys=all_platform_keys,
        platform_options=None,
        publication_scheme=None,
        publication_scheme_path=None,
        creator_profile_id=resolved_creator_profile_id,
        creator_profile_name=resolved_creator_profile_name,
        browser=browser,
    )
    existing_platform_items = existing_result.get("platforms") if isinstance(existing_result.get("platforms"), list) else []
    existing_item_map = {
        _normalize_internal_publish_platform_key(item.get("key")): item
        for item in existing_platform_items
        if isinstance(item, dict) and _normalize_internal_publish_platform_key(item.get("key"))
    }
    existing_packaging_map = existing_packaging.get("platforms") if isinstance(existing_packaging.get("platforms"), dict) else {}

    promoted_materials: list[dict[str, Any]] = []
    for platform_key in all_platform_keys:
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        preview_entry = preview_platforms.get(platform_key)
        if isinstance(preview_entry, dict) and platform_key in selected_platform_keys:
            material = _build_platform_material(platform_key=platform_key, platform_payload=preview_entry, rules=rules)
            existing_source = existing_packaging_map.get(platform_key) if isinstance(existing_packaging_map.get(platform_key), dict) else {}
            existing_item = existing_item_map.get(platform_key) if isinstance(existing_item_map.get(platform_key), dict) else {}
            for source in (existing_source, existing_item):
                _merge_non_empty_publication_metadata_fields(material, source)
                if isinstance(source.get("collection"), dict) and source.get("collection"):
                    material["collection"] = dict(source.get("collection") or {})
                if isinstance(source.get("platform_specific_overrides"), dict) and source.get("platform_specific_overrides"):
                    material["platform_specific_overrides"] = dict(source.get("platform_specific_overrides") or {})
                if isinstance(source.get("cover_generation"), dict) and source.get("cover_generation"):
                    material["cover_generation"] = dict(source.get("cover_generation") or {})
                if isinstance(source.get("live_publish_preflight"), dict) and source.get("live_publish_preflight"):
                    material["live_publish_preflight"] = dict(source.get("live_publish_preflight") or {})
                if str(source.get("cover_path") or "").strip():
                    material["cover_path"] = str(source.get("cover_path") or "").strip()
            existing_copy_material = (
                dict(existing_source.get("copy_material") or {})
                if isinstance(existing_source, dict) and isinstance(existing_source.get("copy_material"), dict)
                else (
                    dict(existing_item.get("copy_material") or {})
                    if isinstance(existing_item, dict) and isinstance(existing_item.get("copy_material"), dict)
                    else {}
                )
            )
            copy_material = dict(existing_copy_material)
            copy_material.update(
                {
                    "primary_title": str(material.get("primary_title") or "").strip(),
                    "titles": list(material.get("titles") or []),
                    "body": str(material.get("body") or "").strip(),
                    "tags": list(material.get("tags") or []),
                    "full_copy": str(material.get("full_copy") or "").strip(),
                }
            )
            material["copy_material"] = copy_material
            option = (
                resolved_platform_options.get(platform_key)
                if isinstance(resolved_platform_options, dict)
                and isinstance(resolved_platform_options.get(platform_key), dict)
                else {}
            )
            if isinstance(option, dict) and option:
                _apply_platform_option_metadata(material=material, option=option)
            material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
            material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        else:
            existing_item = existing_item_map.get(platform_key)
            if not isinstance(existing_item, dict):
                continue
            material = _normalize_existing_platform_material(existing_item, rules=rules)
            serial = _resolve_platform_material_serial(platform_key)
            _restore_platform_cover_path(material=material, material_dir=material_dir, index=serial)
            _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
            material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
            material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        serial = _resolve_platform_material_serial(platform_key)
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)
        promoted_materials.append(material)

    updated_result = dict(existing_result)
    updated_result["platforms"] = [_material_to_result_payload(material) for material in promoted_materials]
    updated_result["creator_profile_id"] = resolved_creator_profile_id or None
    updated_result["creator_profile_name"] = resolved_creator_profile_name or None
    updated_result["publication_context"] = {
        "creator_profile_id": resolved_creator_profile_id or None,
        "creator_profile_name": resolved_creator_profile_name or None,
    }
    updated_result["promotion_context"] = {
        "source": "preview_json",
        "preview_path": str(preview_path or "").strip() or None,
        "platforms": list(selected_platform_keys),
        "browser": str(browser or "chrome").strip() or "chrome",
    }
    packaging_export = _build_platform_packaging_export(
        packaging=existing_packaging,
        platform_materials=promoted_materials,
        requested_platforms=all_platform_keys,
        cover_matrix=dict(updated_result.get("cover_matrix") or existing_packaging.get("cover_matrix") or {}),
    )
    platform_packaging_json_path = smart_copy_platform_packaging_json_path(material_dir)
    json_path = smart_copy_material_json_path(material_dir)
    _synchronize_publishable_root_files(
        material_dir=material_dir,
        material_entries=[
            (_resolve_platform_material_serial(material.get("key")), material)
            for material in promoted_materials
        ],
    )
    platform_packaging_json_path.write_text(json.dumps(packaging_export, ensure_ascii=False, indent=2), encoding="utf-8")
    json_path.write_text(json.dumps(updated_result, ensure_ascii=False, indent=2), encoding="utf-8")
    _prune_legacy_smart_copy_root(material_dir)
    _sync_materialized_smart_copy_to_host(
        requested_folder_path=str(folder_path or ""),
        material_dir=material_dir,
    )
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
    for field in (
        "scheduled_publish_slot",
        "scheduled_publish_at",
        "scheduled_publish_rationale",
        "visibility_or_publish_mode",
        "collection_name",
        "category",
    ):
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
        titles = [str(item).strip() for item in (payload.get("titles") or existing_item.get("titles") or []) if str(item).strip()]
        title = str(
            payload.get("primary_title")
            or payload.get("title")
            or existing_item.get("primary_title")
            or existing_item.get("title")
            or (titles[0] if titles else "")
            or ""
        ).strip()
        body = str(payload.get("body") or payload.get("description") or existing_item.get("body") or "").strip()
        tags = [str(item).strip().lstrip("#") for item in (payload.get("tags") or existing_item.get("tags") or []) if str(item).strip()]
        cover_path = str(existing_item.get("cover_path") or payload.get("cover_path") or "").strip()
        if not cover_path:
            cover_candidate = material_dir / f"{len(targets) + 1:02d}-{platform_key}-cover.jpg"
            if cover_candidate.exists():
                cover_path = str(cover_candidate)
        target = {
            "platform": _normalize_external_publish_platform_key(platform_key),
            "title": title,
            "titles": titles,
            "body": body,
            "tags": tags,
            "cover_path": cover_path,
            "full_copy": str(existing_item.get("full_copy") or "").strip(),
            "copy_material": dict(existing_item.get("copy_material") or {}) if isinstance(existing_item.get("copy_material"), dict) else {},
        }
        _copy_material_contract_publication_context(source=existing_item, destination=target)
        _copy_material_contract_publication_context(source=payload, destination=target)
        targets.append(target)
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
    for field in (
        "declaration",
        "category",
        "collection_name",
        "visibility_or_publish_mode",
        "scheduled_publish_slot",
        "scheduled_publish_rationale",
        "scheduled_publish_at",
    ):
        value = str(source.get(field) or "").strip()
        if value:
            target[field] = value


def _material_cover_slots(material: dict[str, Any]) -> list[dict[str, Any]]:
    slots = derive_publication_cover_slots(material)
    return [dict(item) for item in slots if isinstance(item, dict)]


def _restore_platform_cover_path(*, material: dict[str, Any], material_dir: Path, index: int) -> None:
    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else {}
    platform_key = str(material.get("key") or "").strip()
    target_cover_path = material_dir / f"{index:02d}-{platform_key}-cover.jpg"
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
        existing_cover_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
        if existing_cover_path is not None and not (cover_generation and not bool(cover_generation.get("publish_ready", True))):
            material["cover_path"] = str(existing_cover_path)
            return
        if cover_generation and not bool(cover_generation.get("publish_ready", True)):
            target_cover_path.unlink(missing_ok=True)
            material.pop("cover_path", None)
        return

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
    source_kind = str(cover_generation.get("source") or "").strip().lower()
    if source_kind == "cover_group_reuse":
        group_generation = cover_generation.get("group_generation") if isinstance(cover_generation.get("group_generation"), dict) else None
        group_cover_path = _resolve_cover_generation_output_path(group_generation, material_dir=material_dir) if isinstance(group_generation, dict) else None
        if group_cover_path is None:
            return
        refreshed_group = _refresh_existing_cover_generation_node(
            generation=group_generation,
            output_path=group_cover_path,
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
    cover_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
    if cover_path is None:
        return
    refreshed = _refresh_existing_cover_generation_node(
        generation=cover_generation,
        output_path=cover_path,
        material_dir=material_dir,
    )
    if refreshed is not None:
        material["cover_generation"] = refreshed


def _refresh_cover_group_reuse_platform_derivative(
    *,
    material: dict[str, Any],
    material_dir: Path,
    rules: dict[str, Any],
) -> None:
    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else None
    if not isinstance(cover_generation, dict):
        return
    if str(cover_generation.get("source") or "").strip().lower() != "cover_group_reuse":
        return
    cover_group = cover_generation.get("cover_group") if isinstance(cover_generation.get("cover_group"), dict) else {}
    group_generation = cover_generation.get("group_generation") if isinstance(cover_generation.get("group_generation"), dict) else {}
    group_output_path = _resolve_cover_generation_output_path(group_generation, material_dir=material_dir)
    output_path = _resolve_existing_material_cover_path(material.get("cover_path"), material_dir=material_dir)
    if output_path is None:
        platform_key = _normalize_internal_publish_platform_key(material.get("key"))
        if platform_key:
            output_path = smart_copy_platform_cover_path(
                material_dir,
                _resolve_platform_material_serial(platform_key),
                platform_key,
            )
    if group_output_path is None or output_path is None or not group_output_path.exists():
        return
    should_refresh = not output_path.exists()
    if not should_refresh:
        try:
            should_refresh = output_path.stat().st_mtime + 1 < group_output_path.stat().st_mtime
        except Exception:
            should_refresh = True
    if not should_refresh:
        return
    refreshed_generation = _materialize_platform_cover_from_group(
        group_metadata=group_generation,
        group_output_path=group_output_path,
        output_path=output_path,
        platform_key=_normalize_internal_publish_platform_key(material.get("key")),
        platform_rules=rules,
        cover_group=cover_group,
    )
    material["cover_generation"] = refreshed_generation
    if bool(refreshed_generation.get("publish_ready")) and output_path.exists():
        material["cover_path"] = str(output_path)
    else:
        material.pop("cover_path", None)


def _refresh_cover_group_cache_status(*, cache: dict[str, dict[str, Any]], material_dir: Path) -> None:
    for group_key, generation in list(cache.items()):
        if not isinstance(generation, dict):
            continue
        cover_group = generation.get("cover_group") if isinstance(generation.get("cover_group"), dict) else {}
        group_cover_path = _resolve_existing_material_cover_path(
            cover_group.get("cover_path") or generation.get("output_path"),
            material_dir=material_dir,
        )
        if group_cover_path is None:
            continue
        refreshed = _refresh_existing_cover_generation_node(
            generation=generation,
            output_path=group_cover_path,
            material_dir=material_dir,
        )
        if refreshed is None:
            continue
        refreshed["cover_group"] = dict(cover_group or {})
        cache[group_key] = refreshed


async def _settle_pending_cover_generation(
    *,
    material_dir: Path,
    cover_group_cache: dict[str, dict[str, Any]],
    platform_materials: list[dict[str, Any]],
    progress_callback: IntelligentCopyProgressCallback | None,
    inspection: dict[str, Any],
    display_folder_path: str,
) -> None:
    await _drain_pending_cover_group_requests(cache=cover_group_cache, material_dir=material_dir)
    _refresh_cover_group_cache_status(cache=cover_group_cache, material_dir=material_dir)
    _refresh_platform_material_cover_generation_status(material_dir=material_dir, platform_materials=platform_materials)
    if not _has_pending_cover_generation(platform_materials=platform_materials, cover_group_cache=cover_group_cache):
        return
    settings = get_settings()
    wait_budget_sec = max(
        20.0,
        min(180.0, float(int(getattr(settings, "intelligent_copy_cover_image_timeout_sec", 240) or 240)) * 0.75),
    )
    deadline = asyncio.get_running_loop().time() + wait_budget_sec
    while _has_pending_cover_generation(platform_materials=platform_materials, cover_group_cache=cover_group_cache):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            break
        await _emit_intelligent_copy_progress(
            progress_callback,
            {
                "progress": 94,
                "stage": "cover_wait",
                "message": "封面仍在收敛，正在等待图片生成状态落盘。",
                "inspection": inspection,
                "folder_path": display_folder_path,
                "material_dir": str(material_dir),
            },
        )
        await asyncio.sleep(min(2.0, remaining))
        await _drain_pending_cover_group_requests(cache=cover_group_cache, material_dir=material_dir)
        _refresh_cover_group_cache_status(cache=cover_group_cache, material_dir=material_dir)
        _refresh_platform_material_cover_generation_status(material_dir=material_dir, platform_materials=platform_materials)


def _refresh_platform_material_cover_generation_status(*, material_dir: Path, platform_materials: list[dict[str, Any]]) -> None:
    for material in platform_materials:
        _refresh_restored_cover_generation_status(material=material, material_dir=material_dir)
        platform_key = _normalize_internal_publish_platform_key(material.get("key"))
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if rules:
            _refresh_cover_group_reuse_platform_derivative(
                material=material,
                material_dir=material_dir,
                rules=rules,
            )
        material["blocking_reasons"] = _collect_platform_material_blocking_reasons(material)
        material["publish_ready"] = publication_packaging_entry_publish_ready(material, trust_explicit_flag=False)
        serial = _resolve_platform_material_serial(material.get("key"))
        _write_platform_material_files(material_dir=material_dir, index=serial, material=material)


def _has_pending_cover_generation(
    *,
    platform_materials: list[dict[str, Any]],
    cover_group_cache: dict[str, dict[str, Any]],
) -> bool:
    pending_statuses = {"pending", "pending_codex_imagegen", "queued", "running", "in_progress"}
    for generation in list(cover_group_cache.values()):
        image_generation = generation.get("image_generation") if isinstance(generation, dict) else {}
        status = str((image_generation or {}).get("status") or "").strip().lower()
        if status in pending_statuses:
            return True
    for material in platform_materials:
        cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else {}
        image_generation = cover_generation.get("image_generation") if isinstance(cover_generation.get("image_generation"), dict) else {}
        status = str((image_generation or {}).get("status") or "").strip().lower()
        if status in pending_statuses:
            return True
    return False


def _restore_standard_cover_matrix_group_cache_from_disk(*, material_dir: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    for group in _resolve_standard_cover_matrix_groups():
        group_key = str(group.get("key") or "").strip()
        if not group_key:
            continue
        group_output_path = resolve_smart_copy_cover_group_output_path(material_dir, group_key)
        request_path = resolve_smart_copy_cover_group_request_path(material_dir, group_key)
        request_payload = _read_cover_request_payload(request_path)
        image_generation: dict[str, Any] | None = None
        if request_payload:
            image_generation = {
                "backend": str(request_payload.get("backend") or "codex_builtin").strip() or "codex_builtin",
                "status": str(request_payload.get("status") or "").strip(),
                "output_path": str(request_payload.get("output_path") or group_output_path),
                "request_path": str(request_path),
            }
            codex_runner = request_payload.get("codex_runner")
            if isinstance(codex_runner, dict) and codex_runner:
                image_generation["codex_runner"] = dict(codex_runner)
        cache[group_key] = {
            "source": "cover_group_reuse",
            "platform": str(group.get("representative_platform") or "bilibili").strip(),
            "target_size": {
                "width": int((group.get("cover_size") or [0, 0])[0] or 0),
                "height": int((group.get("cover_size") or [0, 0])[1] or 0),
            },
            "publish_ready": False,
            "blocking_reasons": [],
            "warnings": [],
            "image_generation": image_generation,
            "cover_group": {
                "key": group_key,
                "label": str(group.get("label") or "").strip(),
                "cover_path": str(group_output_path),
                "members": list(group.get("members") or []),
            },
        }
    return cache


async def _drain_pending_cover_group_requests(*, cache: dict[str, dict[str, Any]], material_dir: Path) -> None:
    settings = get_settings()
    for generation in list(cache.values()):
        if not isinstance(generation, dict):
            continue
        image_generation = generation.get("image_generation") if isinstance(generation.get("image_generation"), dict) else {}
        request_path = _resolve_existing_material_cover_path(image_generation.get("request_path"), material_dir=material_dir)
        output_path = _resolve_cover_generation_output_path(generation, material_dir=material_dir)
        if request_path is None or output_path is None:
            continue
        payload = _read_cover_request_payload(request_path)
        if str(payload.get("status") or "").strip().lower() != "pending_codex_imagegen":
            continue
        try:
            await _attempt_codex_imagegen_auto_completion(
                request_path=request_path,
                output_path=output_path,
                settings=settings,
            )
        except Exception as exc:
            _record_codex_imagegen_request_bridge_error(
                request_path=request_path,
                error=str(exc) or exc.__class__.__name__,
            )
            continue


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
    if request_path is None:
        inferred_request_path = output_path.with_suffix(".codex-imagegen.json")
        if inferred_request_path.exists():
            request_path = inferred_request_path
    request_payload = _read_cover_request_payload(request_path) if request_path is not None else {}
    if request_path is not None and request_payload:
        original_status = str(request_payload.get("status") or "").strip()
        _finalize_cover_request_generation_status(request_path=request_path, payload=request_payload)
        if str(request_payload.get("status") or "").strip() != original_status:
            try:
                request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass
    if request_payload or image_generation:
        cover_assessment = assess_cover_publish_readiness(
            refreshed,
            request_payload,
            output_path,
        )
        image_generation = dict(image_generation)
        if request_path is not None:
            image_generation["request_path"] = str(request_path)
        if request_payload:
            for field in (
                "status",
                "backend",
                "result_path",
                "completed_at",
                "last_attempted_at",
                "timed_out",
                "auto_completion_error",
                "codex_runner",
            ):
                if field in request_payload:
                    image_generation[field] = request_payload.get(field)
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


def _extract_required_cover_title_lines_from_request_payload(request_payload: dict[str, Any] | None) -> dict[str, str]:
    payload = request_payload if isinstance(request_payload, dict) else {}
    required_lines = (
        payload.get("cover_hard_contract", {}).get("required_title_lines")
        if isinstance(payload.get("cover_hard_contract"), dict)
        else {}
    )
    if not isinstance(required_lines, dict) or not required_lines:
        required_lines = (
            payload.get("cover_director_policy", {}).get("required_title_lines")
            if isinstance(payload.get("cover_director_policy"), dict)
            else {}
        )
    if not isinstance(required_lines, dict):
        return {}
    return {
        key: str(required_lines.get(key) or "").strip()
        for key in ("brand", "top", "main", "sub", "bottom", "hook")
        if str(required_lines.get(key) or "").strip()
    }


async def _revalidate_existing_cover_generation_request(
    *,
    generation: dict[str, Any] | None,
    output_path: Path,
    material_dir: Path,
    rules: dict[str, Any],
    cover_brief: dict[str, Any] | None,
) -> dict[str, Any] | None:
    refreshed = _refresh_existing_cover_generation_node(
        generation=generation,
        output_path=output_path,
        material_dir=material_dir,
    )
    if not isinstance(refreshed, dict):
        return refreshed
    image_generation = refreshed.get("image_generation") if isinstance(refreshed.get("image_generation"), dict) else {}
    request_path = _resolve_existing_material_cover_path(image_generation.get("request_path"), material_dir=material_dir)
    if request_path is None or not request_path.exists() or not output_path.exists():
        return refreshed
    request_payload = _read_cover_request_payload(request_path)
    if not isinstance(request_payload, dict) or str(request_payload.get("status") or "").strip().lower() != "completed":
        return refreshed
    if str(request_payload.get("backend") or image_generation.get("backend") or "").strip().lower() != "codex_builtin":
        return refreshed
    title_lines = _extract_required_cover_title_lines_from_request_payload(request_payload)
    verification_payload = await _ensure_generated_cover_title_contract_ready(
        request_path=request_path,
        request_payload=request_payload,
        output_path=output_path,
        title=str((cover_brief or {}).get("cover_title") or "").strip(),
        title_lines=title_lines,
        rules=rules,
        cover_brief=cover_brief,
        source_kind="image_generation",
        image_generation=image_generation,
        allow_overlay=False,
    )
    if isinstance(verification_payload, dict):
        request_payload = verification_payload
    refreshed = _refresh_existing_cover_generation_node(
        generation=refreshed,
        output_path=output_path,
        material_dir=material_dir,
    )
    return refreshed


def _extract_cover_generation_timing_summary(generation: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(generation, dict):
        return {}
    image_generation = generation.get("image_generation") if isinstance(generation.get("image_generation"), dict) else {}
    request_path_text = str(image_generation.get("request_path") or "").strip()
    if not request_path_text:
        return {}
    request_path = Path(request_path_text).expanduser()
    if not request_path.exists():
        return {}
    payload = _read_cover_request_payload(request_path)
    if not isinstance(payload, dict) or not payload:
        return {}
    created_at_text = str(payload.get("created_at") or "").strip()
    completed_at_text = str(payload.get("completed_at") or "").strip()
    started = _parse_datetime_with_fallback(created_at_text)
    completed = _parse_datetime_with_fallback(completed_at_text)
    duration_sec: float | None = None
    elapsed_sec: float | None = None
    if started is not None and completed is not None:
        duration_sec = round((completed - started).total_seconds(), 2)
    elif started is not None:
        elapsed_sec = round((datetime.now(started.tzinfo) - started).total_seconds(), 2)
    return {
        "status": str(payload.get("status") or "").strip(),
        "created_at": created_at_text or None,
        "completed_at": completed_at_text or None,
        "duration_sec": duration_sec,
        "elapsed_sec": elapsed_sec,
        "result_path": str(payload.get("result_path") or "").strip() or None,
    }


def _parse_datetime_with_fallback(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _apply_platform_option_metadata(*, material: dict[str, Any], option: dict[str, Any]) -> None:
    for field in ("scheduled_publish_at", "visibility_or_publish_mode", "collection_name", "category"):
        value = str(option.get(field) or "").strip()
        if value:
            material[field] = value
    for field in ("scheduled_publish_slot", "scheduled_publish_rationale"):
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
    collection_management = (
        dict(option.get("collection_management"))
        if isinstance(option.get("collection_management"), dict)
        else dict(option_overrides.get("collection_management"))
        if isinstance(option_overrides.get("collection_management"), dict)
        else {}
    )
    if collection_management:
        material["collection_management"] = collection_management
    available_collections = [str(item).strip() for item in (option.get("available_collections") or []) if str(item).strip()]
    if available_collections:
        material["available_collections"] = available_collections
    collection_catalog = [dict(item) for item in (option.get("collection_catalog") or []) if isinstance(item, dict)]
    if collection_catalog:
        material["collection_catalog"] = collection_catalog


def _copy_material_contract_publication_context(*, source: dict[str, Any], destination: dict[str, Any]) -> dict[str, Any]:
    for field in (
        "scheduled_publish_at",
        "scheduled_publish_slot",
        "scheduled_publish_rationale",
        "visibility_or_publish_mode",
        "collection_name",
        "category",
        "declaration",
    ):
        value = str(source.get(field) or "").strip()
        if value:
            destination[field] = value
    collection_management = source.get("collection_management") if isinstance(source.get("collection_management"), dict) else None
    if collection_management:
        destination["collection_management"] = dict(collection_management)
    available_collections = [str(item).strip() for item in (source.get("available_collections") or []) if str(item).strip()]
    if available_collections:
        destination["available_collections"] = available_collections
    collection_catalog = [dict(item) for item in (source.get("collection_catalog") or []) if isinstance(item, dict)]
    if collection_catalog:
        destination["collection_catalog"] = collection_catalog
    return destination


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
        "cover_slots": _material_cover_slots(material),
        "publish_ready": publication_packaging_entry_publish_ready(material),
        "blocking_reasons": [str(item).strip() for item in (material.get("blocking_reasons") or []) if str(item).strip()],
    }
    _copy_material_contract_publication_context(source=material, destination=payload)
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
            "cover_slots": _material_cover_slots(item),
            "copy_material": dict(item.get("copy_material") or {}) if isinstance(item.get("copy_material"), dict) else {},
            "publish_ready": publication_packaging_entry_publish_ready(item),
            "blocking_reasons": [str(reason).strip() for reason in (item.get("blocking_reasons") or []) if str(reason).strip()],
        }
        _copy_material_contract_publication_context(source=item, destination=platforms[key])
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


def _parse_existing_platform_title_lines(text: str) -> list[str]:
    titles: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue
        line = re.sub(r"^\d+\.\s*", "", line).strip()
        if line and line not in titles:
            titles.append(line)
    return titles


def _parse_existing_platform_tag_lines(text: str) -> list[str]:
    normalized = re.sub(r"[\r\n]+", ",", str(text or ""))
    parts = re.split(r"[,\uff0c\u3001]+", normalized)
    return _dedupe([str(part).strip().lstrip("#") for part in parts if str(part).strip().lstrip("#")])


def _build_existing_cover_slots_from_cover_matrix(
    *,
    payload_context: dict[str, Any] | None,
    platform_key: str,
) -> list[dict[str, Any]]:
    cover_matrix = (
        payload_context.get("cover_matrix")
        if isinstance(payload_context, dict) and isinstance(payload_context.get("cover_matrix"), dict)
        else {}
    )
    slots: list[dict[str, Any]] = []
    for matrix_key, entry in cover_matrix.items():
        if not isinstance(entry, dict):
            continue
        members = [
            _normalize_external_publish_platform_key(item)
            for item in (entry.get("members") or [])
            if _normalize_external_publish_platform_key(item)
        ]
        if platform_key not in members:
            continue
        cover_path = str(entry.get("cover_path") or "").strip()
        if not cover_path:
            continue
        cover_size = entry.get("cover_size")
        target_size = None
        if isinstance(cover_size, (list, tuple)) and len(cover_size) >= 2:
            try:
                target_size = {"width": int(cover_size[0]), "height": int(cover_size[1])}
            except Exception:
                target_size = None
        slot_entry: dict[str, Any] = {
            "slot": str(matrix_key or "").strip() or "primary",
            "cover_path": cover_path,
            "matrix_key": str(matrix_key or "").strip() or "primary",
            "members": members,
        }
        if target_size:
            slot_entry["target_size"] = target_size
        label = str(entry.get("label") or "").strip()
        if label:
            slot_entry["label"] = label
        slots.append(slot_entry)
    return slots


def _load_existing_platform_packaging_from_material_files(
    *,
    material_dir: Path,
    platform_key: str,
    payload_context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    serial = _resolve_platform_material_serial(platform_key)
    body_path = resolve_smart_copy_platform_body_path(material_dir, serial, platform_key)
    tags_path = resolve_smart_copy_platform_tags_path(material_dir, serial, platform_key)
    titles_path = resolve_smart_copy_platform_titles_path(material_dir, serial, platform_key)
    if not body_path.exists() and not tags_path.exists() and not titles_path.exists():
        return None
    body = body_path.read_text(encoding="utf-8", errors="replace").strip() if body_path.exists() else ""
    tags = _parse_existing_platform_tag_lines(
        tags_path.read_text(encoding="utf-8", errors="replace") if tags_path.exists() else ""
    )
    titles = _parse_existing_platform_title_lines(
        titles_path.read_text(encoding="utf-8", errors="replace") if titles_path.exists() else ""
    )
    if not (body or tags or titles):
        return None
    cover_slots = _build_existing_cover_slots_from_cover_matrix(
        payload_context=payload_context,
        platform_key=platform_key,
    )
    cover_path = str(cover_slots[0].get("cover_path") or "").strip() if cover_slots else ""
    copy_material = {
        "source": "materialized_copy_files_restore",
        "primary_title": titles[0] if titles else "",
        "titles": list(titles),
        "body": body,
        "tags": list(tags),
    }
    entry: dict[str, Any] = {
        "titles": titles,
        "primary_title": titles[0] if titles else "",
        "description": body,
        "body": body,
        "tags": tags,
        "copy_material": copy_material,
    }
    if cover_path:
        entry["cover_path"] = cover_path
    if cover_slots:
        entry["cover_slots"] = cover_slots
    return entry


def _supplement_existing_packaging_from_material_files(
    packaging: dict[str, Any] | None,
    *,
    material_dir: Path,
    platform_keys: list[str],
    payload_context: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = dict(packaging or {})
    platforms = (
        {
            _normalize_internal_publish_platform_key(key): dict(value)
            for key, value in (normalized.get("platforms") or {}).items()
            if _normalize_internal_publish_platform_key(key) and isinstance(value, dict)
        }
        if isinstance(normalized.get("platforms"), dict)
        else {}
    )
    changed = False
    for platform_key in platform_keys:
        if platforms.get(platform_key):
            continue
        synthesized = _load_existing_platform_packaging_from_material_files(
            material_dir=material_dir,
            platform_key=platform_key,
            payload_context=payload_context,
        )
        if not isinstance(synthesized, dict):
            continue
        platforms[platform_key] = synthesized
        changed = True
    if not platforms and not changed:
        return normalized
    normalized["platforms"] = platforms
    return normalized


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
        "cover_slots": _material_cover_slots(item),
        "copy_material": dict(item.get("copy_material") or {}) if isinstance(item.get("copy_material"), dict) else {},
        "cover_generation": dict(item.get("cover_generation") or {}) if isinstance(item.get("cover_generation"), dict) else None,
        "publish_ready": publication_packaging_entry_publish_ready(item),
        "blocking_reasons": [str(reason).strip() for reason in (item.get("blocking_reasons") or []) if str(reason).strip()],
    }
    _merge_non_empty_publication_metadata_fields(payload, item)
    return payload


def _restore_or_build_platform_material(
    *,
    platform_key: str,
    rules: dict[str, Any],
    existing_item: dict[str, Any] | None,
    packaging_platforms: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if isinstance(existing_item, dict):
        return _normalize_existing_platform_material(existing_item, rules=rules)
    platform_payload = (
        packaging_platforms.get(platform_key)
        if isinstance(packaging_platforms, dict) and isinstance(packaging_platforms.get(platform_key), dict)
        else None
    )
    if not isinstance(platform_payload, dict):
        return None
    material = _build_platform_material(
        platform_key=platform_key,
        platform_payload=platform_payload,
        rules=rules,
    )
    _copy_material_contract_publication_context(source=platform_payload, destination=material)
    return material


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
        _intelligent_copy_semantic_text(item)
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


def _build_intelligent_copy_creator_publication_policy(
    *,
    creator_profile: dict[str, Any] | None,
    creator_profile_id: str | None,
    creator_profile_name: str | None,
    packaging: dict[str, Any],
    requested_platform_keys: list[str],
) -> dict[str, Any]:
    profile = creator_profile if isinstance(creator_profile, dict) else {}
    if not profile and not str(creator_profile_id or "").strip() and not str(creator_profile_name or "").strip():
        return {}
    targets: list[dict[str, Any]] = []
    platforms_payload = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    for platform_key in requested_platform_keys:
        platform_payload = platforms_payload.get(platform_key) if isinstance(platforms_payload.get(platform_key), dict) else {}
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
        targets.append(
            _build_intelligent_copy_publication_target(
                platform_key=platform_key,
                material={},
                platform_payload=platform_payload,
                creator_profile_name=creator_profile_name,
                rules=rules,
            )
        )
    policy = _publication_policy_for_creator(
        profile,
        {
            "creator_profile_id": str(creator_profile_id or "").strip() or None,
            "creator_profile_name": str(creator_profile_name or "").strip() or None,
            "targets": targets,
        },
    )
    return policy if isinstance(policy, dict) and list(policy.get("rules") or []) else {}


def _build_intelligent_copy_publication_target(
    *,
    platform_key: str,
    material: dict[str, Any],
    platform_payload: dict[str, Any],
    creator_profile_name: str | None,
    rules: dict[str, Any],
) -> dict[str, Any]:
    payload = platform_payload if isinstance(platform_payload, dict) else {}
    material_payload = material if isinstance(material, dict) else {}
    titles = [
        str(item).strip()
        for item in (
            material_payload.get("titles")
            or payload.get("titles")
            or [material_payload.get("primary_title") or payload.get("title") or ""]
        )
        if str(item).strip()
    ][:TITLE_OPTION_LIMIT]
    body = str(material_payload.get("body") or payload.get("description") or payload.get("body") or "").strip()
    tags = [
        str(item).strip().lstrip("#")
        for item in (material_payload.get("tags") or payload.get("tags") or [])
        if str(item).strip()
    ]
    collection_name = str(
        material_payload.get("collection_name")
        or payload.get("collection_name")
        or ((material_payload.get("collection") or {}) if isinstance(material_payload.get("collection"), dict) else {}).get("name")
        or ""
    ).strip()
    platform_specific_overrides = (
        dict(material_payload.get("platform_specific_overrides"))
        if isinstance(material_payload.get("platform_specific_overrides"), dict)
        else dict(payload.get("platform_specific_overrides"))
        if isinstance(payload.get("platform_specific_overrides"), dict)
        else {}
    )
    return {
        "platform": platform_key,
        "platform_label": str(rules.get("label") or platform_key),
        "creator_profile_name": str(creator_profile_name or "").strip(),
        "title": titles[0] if titles else "",
        "titles": titles,
        "body": body,
        "description": body,
        "tags": tags,
        "collection_name": collection_name,
        "platform_specific_overrides": platform_specific_overrides,
    } | {
        key: value
        for key, value in {
            "declaration": str(material_payload.get("declaration") or payload.get("declaration") or "").strip(),
            "category": str(material_payload.get("category") or payload.get("category") or "").strip(),
            "visibility_or_publish_mode": str(material_payload.get("visibility_or_publish_mode") or payload.get("visibility_or_publish_mode") or "").strip(),
            "scheduled_publish_slot": str(material_payload.get("scheduled_publish_slot") or payload.get("scheduled_publish_slot") or "").strip(),
            "scheduled_publish_rationale": str(material_payload.get("scheduled_publish_rationale") or payload.get("scheduled_publish_rationale") or "").strip(),
            "scheduled_publish_at": str(material_payload.get("scheduled_publish_at") or payload.get("scheduled_publish_at") or "").strip(),
        }.items()
        if value
    }


def _apply_creator_publication_policy_to_material(
    *,
    platform_key: str,
    material: dict[str, Any],
    platform_payload: dict[str, Any],
    creator_publication_policy: dict[str, Any] | None,
    creator_profile_name: str | None,
    rules: dict[str, Any],
) -> None:
    policy = creator_publication_policy if isinstance(creator_publication_policy, dict) else {}
    if not list(policy.get("rules") or []):
        return
    target = _build_intelligent_copy_publication_target(
        platform_key=platform_key,
        material=material,
        platform_payload=platform_payload,
        creator_profile_name=creator_profile_name,
        rules=rules,
    )
    current_overrides = (
        dict(material.get("platform_specific_overrides"))
        if isinstance(material.get("platform_specific_overrides"), dict)
        else {}
    )
    collection_management = (
        dict(current_overrides.get("collection_management"))
        if isinstance(current_overrides.get("collection_management"), dict)
        else {}
    )
    if not collection_management:
        collection_management = _build_collection_management_plan(
            {},
            target,
            publication_policy=policy,
        )
        if collection_management.get("status") not in {"", "not_supported", "not_configured"}:
            current_overrides["collection_management"] = collection_management
    current_collection_name = str(material.get("collection_name") or "").strip()
    if not current_collection_name:
        current_collection_name = _choose_real_collection_name(
            {},
            target,
            publication_policy=policy,
        )
        if current_collection_name:
            material["collection_name"] = current_collection_name
    if current_overrides:
        material["platform_specific_overrides"] = current_overrides


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


async def _resolve_restored_cover_brief(
    existing_result: dict[str, Any] | None,
    *,
    video_path: Path,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any],
    copy_brief: dict[str, Any],
    packaging: dict[str, Any],
    cover_source_manifest: dict[str, Any] | None = None,
    existing_cover_path: Path | None = None,
) -> dict[str, Any]:
    existing_payload = existing_result if isinstance(existing_result, dict) else {}
    fallback = _build_fallback_cover_brief(
        packaging=packaging,
        content_profile=content_profile,
        copy_brief=copy_brief,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=existing_cover_path,
    )
    persisted = (
        dict(existing_payload.get("cover_brief") or {})
        if isinstance(existing_payload.get("cover_brief"), dict)
        else {}
    )
    if any(str(persisted.get(key) or "").strip() for key in ("cover_title", "product_identity", "selling_angle", "visual_brief")):
        return _normalize_cover_brief_payload(persisted, fallback=fallback)
    return await _maybe_await(_build_intelligent_cover_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
        cover_source_manifest=cover_source_manifest,
        existing_cover_path=existing_cover_path,
    ))


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


def _resolve_subject_fidelity_scheme_key(
    *,
    content_strategy_key: str,
    cover_brief: dict[str, Any],
    copy_brief: dict[str, Any] | None = None,
) -> str:
    return "generic_subject_fidelity_v1"


def _resolve_subject_fidelity_scheme_profile(scheme_key: str) -> dict[str, Any]:
    return dict(SUBJECT_FIDELITY_SCHEME_PROFILES.get(str(scheme_key or "").strip()) or SUBJECT_FIDELITY_SCHEME_PROFILES["generic_subject_fidelity_v1"])


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
    is_compare = _has_explicit_cover_compare_signal(text) or "comparison" in lowered
    notes: list[str] = []
    if is_edc_blade:
        notes.append("保留原始刀型、开孔、转轴、柄部纹理和主要部件位置，不改款不变形。")
        notes.append("保留螺丝数量、位置、开槽方向、边角切面和金属分区，不要凭空增删五金细节。")
        notes.append("刀身镜面反光区域是实心金属高光，不是开孔、镂空、雕花或缺口。")
        notes.append("不要给刀身添加不存在的浮雕、动物纹样、刻字或装饰图案。")
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


def _cover_reference_pack_prompt(
    *,
    reference_count: int,
) -> str:
    if int(reference_count or 0) <= 1:
        return "参考图语义：这是一张单参考图，直接保持这张图里的真实商品主体、主角度和结构关系。"
    return (
        "参考图语义：这是一组同一真实商品或同一对比商品组的多角度参考图，不是不同商品。"
        "第 1 张是主参考角度，其余图片只是补充角度与细节校正。"
        "必须综合全部参考图保持同一主体身份、结构和版本关系，但最终构图要优先服从多数参考共同指向的主角度。"
        "少数侧边态、边缘角度或局部细节图只能用来补足结构细节，不能反过来把最终封面主构图改成侧视图。"
        "如果大多数参考图展示的是更完整的正面、三分之四正面或展开英雄角度，就必须延续这种主视角。"
    )


def _load_cover_source_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resolve_cover_reference_paths(
    *,
    material_dir: Path,
    cover_source_path: Path | None,
    cover_source_manifest: dict[str, Any] | None,
) -> list[Path]:
    manifest = cover_source_manifest if isinstance(cover_source_manifest, dict) else {}
    resolved: list[Path] = []
    for raw_path in manifest.get("reference_image_paths") or []:
        try:
            path = Path(str(raw_path or "")).expanduser()
        except Exception:
            continue
        if path.exists() and path.is_file() and path not in resolved:
            resolved.append(path.resolve())
    if resolved:
        return resolved
    for path in resolve_smart_copy_cover_reference_image_paths(material_dir):
        if path.exists() and path.is_file():
            resolved_path = path.resolve()
            if resolved_path not in resolved:
                resolved.append(resolved_path)
    if resolved:
        return resolved
    if cover_source_path is not None and cover_source_path.exists() and cover_source_path.is_file():
        return [cover_source_path.resolve()]
    return []


def _prune_stale_cover_reference_images(material_dir: Path, *, keep_count: int) -> None:
    for stale_path in resolve_smart_copy_cover_reference_image_paths(material_dir)[max(0, int(keep_count or 0)):]:
        try:
            stale_path.unlink(missing_ok=True)
        except OSError:
            continue


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
        text = _intelligent_copy_semantic_text(item)
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
    normalized_platform = str(platform_key or "").strip().lower().replace("_", "-")
    if normalized_platform == "toutiao":
        return dict(_cover_matrix_group_profile("landscape_16_9"))
    width, height = int(rules["cover_size"][0]), int(rules["cover_size"][1])
    return dict(_cover_matrix_group_profile(_resolve_cover_matrix_group_key(width=width, height=height)))


def _resolve_cover_matrix_group_key(*, width: int, height: int) -> str:
    ratio = float(width) / max(1.0, float(height))
    if abs(ratio - (16 / 9)) < 0.06:
        return "landscape_16_9"
    if abs(ratio - (4 / 3)) < 0.06:
        return "landscape_4_3"
    if abs(ratio - (3 / 4)) < 0.06:
        return "portrait_3_4"
    return "portrait_3_4"


def _build_cover_matrix_layout_prompt(layout_constraints: dict[str, Any] | None) -> str:
    constraints = dict(layout_constraints or {})
    if not constraints:
        return ""
    lines: list[str] = []
    if str(constraints.get("title_density") or "").strip() == "compact_upper_stack":
        lines.append("标题堆叠必须更紧凑地上收，品牌行、主标题、副标题和吸睛文案尽量压缩在上半区，不要把副标题和 badge 压到画面中部。")
    if str(constraints.get("subject_clearance_zone") or "").strip() == "middle_center":
        lines.append("画面中部要保留主主体展示通道，不要让标题条、badge 或特效横切关键结构。")
    return "".join(lines)


def _cover_matrix_group_profile(group_key: str) -> dict[str, Any]:
    profiles: dict[str, dict[str, Any]] = {
        "landscape_16_9": {
            "key": "landscape_16_9",
            "label": "16:9 横版母版",
            "representative_platform": "bilibili",
            "cover_size": (1600, 900),
            "members": ["bilibili", "toutiao", "youtube"],
            "visual_instruction": "16:9 横版母版，兼顾缩略图点击率与主体细节，主体完整、标题冲击强，中央安全区适合完整主副标题与吸睛文案。",
            "layout_constraints": {},
        },
        "landscape_4_3": {
            "key": "landscape_4_3",
            "label": "4:3 横版母版",
            "representative_platform": "bilibili",
            "cover_size": (1440, 1080),
            "members": ["bilibili", "wechat_channels", "x"],
            "visual_instruction": "4:3 横版母版，适合横向信息流与封面上传槽位，主体完整同框，左右留出戏剧化背景，中上区域适合强主标题和对比副标题。",
            "layout_constraints": {},
        },
        "portrait_3_4": {
            "key": "portrait_3_4",
            "label": "3:4 竖版母版",
            "representative_platform": "xiaohongshu",
            "cover_size": (1080, 1440),
            "members": ["xiaohongshu", "douyin", "kuaishou", "wechat_channels"],
            "visual_instruction": "3:4 竖版母版，强调质感与主体完整展示，上半区适合品牌与主标题，下半区保留产品和手持关系，不要挤压主体。",
            "layout_constraints": {
                "title_density": "compact_upper_stack",
                "subject_clearance_zone": "middle_center",
            },
        },
    }
    return dict(profiles.get(str(group_key or "").strip()) or profiles["landscape_16_9"])


def _resolve_standard_cover_matrix_groups() -> list[dict[str, Any]]:
    return [
        _cover_matrix_group_profile("landscape_16_9"),
        _cover_matrix_group_profile("landscape_4_3"),
        _cover_matrix_group_profile("portrait_3_4"),
    ]


async def _prime_standard_cover_matrix_groups(
    *,
    cache: dict[str, dict[str, Any]],
    material_dir: Path,
    video_path: Path,
    source_image_path: Path | None,
    reference_image_paths: list[Path] | None = None,
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
        group_output_path = smart_copy_cover_group_output_path(material_dir, group_key)
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
                reference_image_paths=reference_image_paths,
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
            "generation_timing": _extract_cover_generation_timing_summary(node),
        }
    return matrix


async def _render_or_reuse_platform_cover_group(
    *,
    cache: dict[str, dict[str, Any]],
    material_dir: Path,
    output_path: Path,
    video_path: Path,
    source_image_path: Path | None,
    reference_image_paths: list[Path] | None = None,
    existing_cover_path: Path | None,
    title: str,
    platform_key: str,
    platform_rules: dict[str, Any],
    cover_group: dict[str, Any],
    cover_brief: dict[str, Any] | None = None,
) -> dict[str, Any]:
    group_key = str(cover_group.get("key") or platform_key).strip()
    group_output_path = smart_copy_cover_group_output_path(material_dir, group_key)
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
            reference_image_paths=reference_image_paths,
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
    group_output_path = smart_copy_cover_group_output_path(material_dir, group_key)
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
    if group_output_path.exists() and bool(group_metadata.get("publish_ready")):
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
        blocking_reasons = []
    elif group_output_path.exists():
        output_path.unlink(missing_ok=True)
    elif not blocking_reasons:
        blocking_reasons.append("通用封面尚未生成完成")
    else:
        output_path.unlink(missing_ok=True)
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


def _collect_platform_material_generation_blocking_reasons(material: dict[str, Any]) -> list[str]:
    problems = _validate_platform_material_ready(material)
    platform_key = _normalize_external_publish_platform_key(material.get("key"))
    cover_policy_required = platform_requires_custom_cover_policy(platform_key)
    cover_path_text = str(material.get("cover_path") or "").strip()
    if cover_policy_required and not cover_path_text:
        problems.append("缺少平台封面 cover_path")
    cover_generation = material.get("cover_generation") if isinstance(material.get("cover_generation"), dict) else {}
    image_generation = cover_generation.get("image_generation") if isinstance(cover_generation.get("image_generation"), dict) else {}
    generation_status = str(image_generation.get("status") or "").strip().lower()
    if cover_policy_required and image_generation:
        if generation_status in {"pending", "pending_codex_imagegen", "queued", "running", "in_progress"}:
            problems.append("封面生成未完成")
        elif generation_status in {"failed", "error", "cancelled", "canceled"}:
            problems.append(f"封面生成失败：status={generation_status}")
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
        if not explicit_collection_name:
            explicit_collection_skip = True
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


def _build_material_generation_contract(
    platform_materials: list[dict[str, Any]],
    *,
    requested_platforms: list[str] | None = None,
) -> dict[str, Any]:
    platform_contracts: dict[str, Any] = {}
    blocking_reasons: list[str] = []
    requested_scope = _normalize_requested_material_platform_scope(requested_platforms)
    for material in platform_materials:
        platform_key = _normalize_internal_publish_platform_key(material.get("key"))
        external_platform_key = _normalize_external_publish_platform_key(platform_key)
        label = str(material.get("label") or external_platform_key).strip()
        material_blocking_reasons = _collect_platform_material_generation_blocking_reasons(material)
        generation_ready = not material_blocking_reasons
        platform_contracts[external_platform_key] = {
            "status": "passed" if generation_ready else "failed",
            "label": label,
            "generation_ready": generation_ready,
            "blocking_reasons": material_blocking_reasons,
        }
        if material_blocking_reasons:
            blocking_reasons.extend(f"{label}：{reason}" for reason in material_blocking_reasons)
    covered_platforms = sorted(platform_contracts.keys())
    missing_requested_platforms = [
        platform
        for platform in (requested_scope or [])
        if platform not in platform_contracts
    ]
    if missing_requested_platforms:
        covered_platforms_text = ", ".join(covered_platforms) if covered_platforms else "无"
        blocking_reasons.extend(
            [
                f"发布范围不匹配：{platform} 不在本期物料生成范围内。当前仅覆盖平台 -> {covered_platforms_text}"
                for platform in missing_requested_platforms
            ]
        )
    return {
        "status": "passed" if not blocking_reasons else "failed",
        "generation_ready": not blocking_reasons,
        "blocking_reasons": sorted(set(reason for reason in blocking_reasons if reason)),
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


def _apply_material_contract_export_state(
    target: dict[str, Any],
    contract: dict[str, Any] | None,
    *,
    blocking_reasons: Sequence[str] | None = None,
) -> dict[str, Any]:
    terminal_status = _material_contract_terminal_status(contract)
    target["status"] = terminal_status
    target["publish_ready"] = _material_contract_publish_ready(contract)
    target["one_click_publish_ready"] = bool((contract or {}).get("one_click_publish_ready"))
    target["manual_handoff_ready"] = _material_contract_manual_handoff_ready(contract)
    target["manual_handoff_targets"] = list((contract or {}).get("manual_handoff_platforms") or [])
    if blocking_reasons is not None:
        target["blocking_reasons"] = list(blocking_reasons)
    return target


def _apply_material_generation_export_state(
    target: dict[str, Any],
    generation_contract: dict[str, Any] | None,
    *,
    material_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generation_ready = bool((generation_contract or {}).get("generation_ready"))
    target["material_generation_status"] = str((generation_contract or {}).get("status") or "failed").strip() or "failed"
    target["material_generation_ready"] = generation_ready
    target["status"] = "passed" if generation_ready else _material_contract_terminal_status(material_contract)
    return target


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
    collection_management = (
        dict(overrides.get("collection_management"))
        if isinstance(overrides.get("collection_management"), dict)
        else {}
    )
    collection_management_target = str(
        collection_management.get("selected_collection_name")
        or collection_management.get("target_collection_name")
        or collection_management.get("collection_name")
        or ""
    ).strip()
    collection_policy = str(overrides.get("collection_policy") or "").strip().lower()
    explicit_collection_skip = bool(overrides.get("skip_collection_select")) or collection_policy in publication_collection_policy_skip_values()
    if (
        platform_requires_explicit_collection_policy(platform_key)
        and not collection_name
        and not collection_management_target
        and not explicit_collection_skip
    ):
        overrides["skip_collection_select"] = True
        overrides["collection_policy"] = "skip"
        explicit_collection_skip = True
    if (collection_name or collection_management_target) and explicit_collection_skip:
        overrides.pop("skip_collection_select", None)
        if collection_policy in publication_collection_policy_skip_values():
            overrides.pop("collection_policy", None)
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
    material_generation_contract = _build_material_generation_contract(
        platform_materials,
        requested_platforms=requested_platforms,
    )
    material_contract = _build_material_contract(
        platform_materials,
        requested_platforms=requested_platforms,
    )
    material_generation_ready = bool(material_generation_contract.get("generation_ready"))
    export_status = "passed" if material_generation_ready else _material_contract_terminal_status(material_contract)
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
        "material_generation_contract": material_generation_contract,
        "material_generation_status": str(material_generation_contract.get("status") or "failed").strip() or "failed",
        "material_generation_ready": material_generation_ready,
        "material_contract": material_contract,
        "status": export_status,
        "publish_ready": _material_contract_publish_ready(material_contract),
        "one_click_publish_ready": bool(material_contract.get("one_click_publish_ready")),
        "manual_handoff_ready": _material_contract_manual_handoff_ready(material_contract),
        "platforms": {},
    }
    material_contract_platforms = (
        material_contract.get("platforms")
        if isinstance(material_contract.get("platforms"), dict)
        else {}
    )
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
        contract_entry = material_contract_platforms.get(platform_key) if isinstance(material_contract_platforms.get(platform_key), dict) else {}
        entry.update(
            {
            "titles": list(material.get("titles") or []),
            "description": str(material.get("body") or "").strip(),
            "tags": list(material.get("tags") or []),
            "cover_path": str(material.get("cover_path") or "").strip(),
            "cover_slots": _material_cover_slots(material),
            "copy_material": dict(material.get("copy_material") or {}) if isinstance(material.get("copy_material"), dict) else {},
            "publish_ready": bool(
                contract_entry.get("one_click_publish_ready")
                if "one_click_publish_ready" in contract_entry
                else publication_packaging_entry_publish_ready(material)
            ),
            "one_click_publish_ready": bool(contract_entry.get("one_click_publish_ready")),
            "blocking_reasons": [str(item).strip() for item in (contract_entry.get("blocking_reasons") or []) if str(item).strip()],
            "manual_handoff_only": bool(contract_entry.get("manual_handoff_only")),
            }
        )
        _copy_material_contract_publication_context(source=material, destination=entry)
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
    titles = list(material.get("titles") or [])
    if titles:
        smart_copy_platform_titles_path(material_dir, index, platform_key).write_text(
            str(material.get("title_copy_all") or "").strip() + "\n",
            encoding="utf-8",
        )
    smart_copy_platform_body_path(material_dir, index, platform_key).write_text(
        str(material.get("body") or "").strip() + "\n",
        encoding="utf-8",
    )
    smart_copy_platform_tags_path(material_dir, index, platform_key).write_text(
        str(material.get("tags_copy") or "").strip() + "\n",
        encoding="utf-8",
    )
    smart_copy_platform_markdown_path(material_dir, index, platform_key).write_text(
        _render_platform_material_markdown(material),
        encoding="utf-8",
    )


def _platform_material_files_exist(*, material_dir: Path, index: int, material: dict[str, Any]) -> bool:
    platform_key = str(material.get("key") or "").strip()
    required_paths = [
        resolve_smart_copy_platform_body_path(material_dir, index, platform_key),
        resolve_smart_copy_platform_tags_path(material_dir, index, platform_key),
        smart_copy_platform_markdown_path(material_dir, index, platform_key),
    ]
    if list(material.get("titles") or []):
        required_paths.append(resolve_smart_copy_platform_titles_path(material_dir, index, platform_key))
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
        _intelligent_copy_semantic_text(item)
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
    if (
        not summary
        or "主题待进一步确认" in summary
        or "主体信息暂未稳定识别" in summary
        or "后续文案需要围绕画面、字幕和已核验事实重新创作" in summary
    ):
        subject_label = subject_model or subject_brand or subject_type or stem or "这条视频"
        summary = _build_publish_safe_copy_summary(subject_label=subject_label, context_text=" ".join(part for part in (stem, transcript_text) if part))

    resolved_hook_line = str(profile.get("hook_line") or "").strip()
    if not resolved_hook_line or resolved_hook_line == "内容待人工确认":
        resolved_hook_line = hook_line or "内容待人工确认"

    engagement_question = _resolve_intelligent_copy_question(
        content_profile=profile,
        context_text=" ".join(part for part in (stem, transcript_text, summary) if str(part or "").strip()),
    )
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
    stem = video_path.stem.strip()
    brand = str(profile.get("subject_brand") or "").strip()
    model = str(profile.get("subject_model") or "").strip()
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
    subject_label = model or brand or stem or "这期内容"
    summary = str(profile.get("summary") or "").strip()
    if (
        not summary
        or "主题待进一步确认" in summary
        or "主体信息暂未稳定识别" in summary
        or "后续文案需要围绕画面、字幕和已核验事实重新创作" in summary
    ):
        profile["summary"] = _build_publish_safe_copy_summary(subject_label=subject_label, context_text=stem)
    profile["engagement_question"] = _resolve_intelligent_copy_question(content_profile=profile, context_text=stem)
    if (brand and not _is_generic_intelligent_copy_subject_identity(brand)) or (
        model and not _is_generic_intelligent_copy_subject_identity(model)
    ):
        return profile
    if stem:
        profile["subject_model"] = stem
        profile.setdefault("search_queries", [stem])
        profile["summary"] = _build_publish_safe_copy_summary(subject_label=stem, context_text=stem)
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
    if any(token in normalized.lower() for token in ("直跳", "跳刀", "otf", "双动")):
        return "EDC跳刀"
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
    _prepare_structured_smart_copy_layout(material_dir)
    source_path = smart_copy_cover_source_image_path(material_dir)
    manifest_path = smart_copy_cover_source_manifest_path(material_dir)
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
                        max(4, int(settings.cover_candidate_count or 4))
                    ),
                    tmpdir=tmp,
                )
                if duration > 0
                else []
            )
            if not candidates:
                raise RuntimeError("没有可用于封面判断的候选帧")
            candidates = _annotate_cover_source_candidates(candidates)
            reference_candidates = candidates[: min(4, len(candidates))]
            ranking = await _rank_cover_reference_candidates_for_generation(
                candidates=reference_candidates,
                content_profile=content_profile,
                packaging=packaging,
            )
            ordered_candidates: list[dict[str, Any]] = []
            for number in ranking.get("ranking_numbers") or []:
                try:
                    ordered_candidates.append(reference_candidates[int(number) - 1])
                except Exception:
                    continue
            if ordered_candidates:
                reference_candidates = ordered_candidates[: len(reference_candidates)]
            reference_paths: list[Path] = []
            reference_seek_secs: list[float] = []
            for index, candidate in enumerate(reference_candidates, start=1):
                reference_path = smart_copy_cover_reference_image_path(material_dir, index)
                seek_sec = float(candidate.get("seek") or 3.0)
                await _extract_frame(video_path, reference_path, seek_sec)
                reference_paths.append(reference_path)
                reference_seek_secs.append(round(seek_sec, 2))
            if not reference_paths:
                raise RuntimeError("没有成功提取可用于封面生成的参考帧")
            shutil.copy2(reference_paths[0], source_path)
            _prune_stale_cover_reference_images(material_dir, keep_count=len(reference_paths))
            try:
                resolve_smart_copy_cover_candidates_sheet_path(material_dir).unlink(missing_ok=True)
            except OSError:
                pass
            _write_cover_source_manifest(
                manifest_path,
                {
                    "seek_sec": reference_seek_secs[0],
                    "source": "sampled_reference_pack",
                    "score": None,
                    "reason": "已直接保留四张候选帧作为 Codex 封面参考图组，不再生成 contact sheet 或四选一高光帧。",
                    "candidate_index": 0,
                    "candidate_indices": list(range(len(reference_paths))),
                    "reference_image_paths": [str(path) for path in reference_paths],
                    "reference_seek_secs": reference_seek_secs,
                    "reference_count": len(reference_paths),
                    "reference_primary_number": int(ranking.get("primary_number") or 1),
                    "reference_ranking_numbers": [int(value) for value in (ranking.get("ranking_numbers") or []) if str(value).strip()],
                    "reference_order_reason": str(ranking.get("reason") or "").strip(),
                    "contact_sheet_path": "",
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
    reference_paths = _resolve_cover_reference_paths(
        material_dir=source_path.parent.parent,
        cover_source_path=source_path,
        cover_source_manifest=manifest,
    )
    reference_seek_secs = [
        float(value)
        for value in ((manifest or {}).get("reference_seek_secs") or [])
        if str(value or "").strip()
    ]
    if reference_paths and reference_seek_secs:
        for reference_path, seek_sec in zip(reference_paths, reference_seek_secs, strict=False):
            if seek_sec <= 0:
                continue
            await _extract_frame(video_path, reference_path, seek_sec)
        if reference_paths[0].exists():
            shutil.copy2(reference_paths[0], source_path)
        _write_cover_source_manifest(manifest_path, dict(manifest or {}))
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
    profile_text = _build_cover_source_profile_text(
        content_profile=content_profile,
        packaging=packaging,
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


def _fallback_cover_reference_candidate_order(
    candidates: list[dict[str, Any]],
) -> list[int]:
    ranked: list[tuple[float, int]] = []
    for index, candidate in enumerate(candidates, start=1):
        subtitle_risk = float(candidate.get("subtitle_overlay_risk") or 0.0)
        ranked.append((subtitle_risk, index))
    ranked.sort()
    return [index for _score, index in ranked]


def _build_cover_source_profile_text(
    *,
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> str:
    return json.dumps(
        {
            "content_profile": _content_profile_summary(content_profile),
            "highlights": dict(packaging.get("highlights") or {}),
        },
        ensure_ascii=False,
    )


async def _rank_cover_reference_candidates_for_generation(
    *,
    candidates: list[dict[str, Any]],
    content_profile: dict[str, Any],
    packaging: dict[str, Any],
) -> dict[str, Any]:
    fallback_ranking = _fallback_cover_reference_candidate_order(candidates)
    if len(candidates) <= 1:
        return {
            "primary_number": 1 if candidates else 0,
            "ranking_numbers": fallback_ranking,
            "reason": "候选不足，直接沿用现有顺序",
            "used_fallback": True,
        }
    review_paths = [Path(candidate["preview"]) for candidate in candidates if candidate.get("preview")]
    if len(review_paths) != len(candidates):
        return {
            "primary_number": fallback_ranking[0] if fallback_ranking else 0,
            "ranking_numbers": fallback_ranking,
            "reason": "参考预览不完整，按低字幕风险顺序回退",
            "used_fallback": True,
        }
    profile_text = _build_cover_source_profile_text(
        content_profile=content_profile,
        packaging=packaging,
    )
    selection_contract = _build_cover_source_selection_contract(
        content_profile=content_profile,
        packaging=packaging,
    )
    prompt = (
        "你正在给 Codex 封面生成挑选同一商品的主参考图顺序。"
        "这几张图都来自同一个真实商品或同一对比商品组的不同拍摄角度，不是不同商品。"
        "你的任务不是淘汰到只剩一张，而是先确定谁应该做 1 号主参考，其余图片继续作为补充角度一起保留。"
        "如果多数图片展示的是正面、三分之四正面、展开态或更完整的英雄角度，就必须让这类多数主角度排在前面。"
        "少数侧边态、边缘角度、局部特写、补充细节图只能放后面做结构补充，不能反过来决定最终主构图。"
        "优先：主体完整、主角度清晰、展开态或更利于识别整体结构、版本差异直观、少字幕遮挡。"
        "降级：侧边态、闭合态、局部特写、主体被截断、字幕污染明显、对比关系不直观。"
        f"\n硬约束：{selection_contract}"
        f"\n视频主题参考：{profile_text}"
        "\n输出 JSON："
        '{"primary_number":2,"ranking_numbers":[2,4,1,3],"reason":"2号是更完整的主角度；1号侧边态只适合作辅助细节参考"}'
    )
    try:
        content = await asyncio.wait_for(
            complete_with_images(
                prompt,
                review_paths,
                max_tokens=220,
                json_mode=True,
            ),
            timeout=_resolve_cover_source_multimodal_timeout("full_frame_review"),
        )
        data = json.loads(extract_json_text(content))
    except Exception:
        return {
            "primary_number": fallback_ranking[0] if fallback_ranking else 0,
            "ranking_numbers": fallback_ranking,
            "reason": "主参考排序识别失败，按低字幕风险顺序回退",
            "used_fallback": True,
        }
    ranking_numbers = _extract_cover_source_shortlist_numbers(
        {"ranking_numbers": data.get("ranking_numbers")},
        raw_text=content,
        original_numbers=list(range(1, len(candidates) + 1)),
        finalist_limit=len(candidates),
    )
    if not ranking_numbers:
        ranking_numbers = fallback_ranking
    primary_number = int(data.get("primary_number", ranking_numbers[0] if ranking_numbers else 0) or 0)
    if primary_number not in range(1, len(candidates) + 1):
        primary_number = ranking_numbers[0] if ranking_numbers else 0
    ordered = [primary_number]
    for number in ranking_numbers:
        if number not in ordered:
            ordered.append(number)
    for number in fallback_ranking:
        if number not in ordered:
            ordered.append(number)
    return {
        "primary_number": primary_number,
        "ranking_numbers": ordered,
        "reason": str(data.get("reason") or "").strip(),
        "used_fallback": False,
    }


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
        "请不要只看缩略图，要结合后面的原图判断主角度是否完整、是否展开态、主体是否被遮挡、关键结构是否清晰。"
        "优先：主体完整、展开态、结构清晰、少字幕遮挡、适合后续封面包装。"
        "不要选：闭合态、侧边态、主体被截断、字幕污染明显或主体关系混乱的候选。"
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
        "这次不要再选：主体不完整、闭合态、侧边态、字幕污染明显、主体关系混乱或关键信息不清的候选。"
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
    reference_image_paths: list[Path] | None = None,
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
    reference_count_hint = max(
        1,
        len([path for path in (reference_image_paths or []) if path is not None]) or (1 if source_image_path is not None else 0),
    )
    prompt_spec = _build_platform_cover_prompt_spec(
        title=title,
        platform_key=platform_key,
        rules=rules,
        width=target_width,
        height=target_height,
        cover_brief=cover_brief,
        reference_count=reference_count_hint,
    )
    expected_prompt = _build_platform_cover_image_prompt(
        title=title,
        platform_key=platform_key,
        rules=rules,
        width=target_width,
        height=target_height,
        cover_brief=cover_brief,
        reference_count=reference_count_hint,
    )
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
        generation_reference_paths: list[Path] = []
        if reference_image_paths:
            for index, reference_path in enumerate(reference_image_paths, start=1):
                candidate = Path(reference_path)
                if not candidate.exists():
                    continue
                generation_reference_paths.append(candidate)
            if generation_reference_paths:
                shutil.copy2(generation_reference_paths[0], base_image)
        elif source_image_path is not None and source_image_path.exists():
            shutil.copy2(source_image_path, base_image)
            generation_reference_paths = [base_image]
        elif existing_cover_path is not None and existing_cover_path.exists():
            shutil.copy2(existing_cover_path, base_image)
            generation_reference_paths = [base_image]
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
                        source_image_path=generation_reference_paths[0],
                        reference_image_paths=generation_reference_paths,
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
        if (
            isinstance(image_generation, dict)
            and output_path.exists()
            and not _cover_request_matches_current_contract(
                request_payload,
                expected_prompt=expected_prompt,
                expected_hard_contract=expected_hard_contract,
                expected_director_policy=expected_director_policy,
            )
        ):
            request_payload = _write_cover_request_payload_snapshot(
                request_path=request_path,
                image_generation=image_generation,
                output_path=output_path,
                prompt=expected_prompt,
                hard_contract=expected_hard_contract,
                director_policy=expected_director_policy,
                width=target_width,
                height=target_height,
            )
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


def _write_cover_request_payload_snapshot(
    *,
    request_path: Path,
    image_generation: dict[str, Any] | None,
    output_path: Path,
    prompt: str,
    hard_contract: dict[str, Any] | None,
    director_policy: dict[str, Any] | None,
    width: int,
    height: int,
) -> dict[str, Any]:
    payload = {
        "status": str((image_generation or {}).get("status") or "completed").strip() or "completed",
        "backend": str((image_generation or {}).get("backend") or "").strip(),
        "created_at": datetime.now().isoformat(),
        "output_path": str(output_path),
        "prompt": str(prompt or ""),
        "cover_hard_contract": dict(hard_contract or {}),
        "cover_director_policy": dict(director_policy or {}),
        "target_size": {"width": int(width or 0), "height": int(height or 0)},
        "image_generation": dict(image_generation or {}),
    }
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


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
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
    payload["bitmap_title_contract_passed"] = bool(verification.get("bitmap_title_contract_passed"))
    payload["bitmap_title_lines"] = dict(title_lines or {})
    payload["bitmap_title_detected"] = {
        "main": str(verification.get("detected_main_title") or "").strip(),
        "bottom": str(verification.get("detected_subtitle") or "").strip(),
    }
    payload["bitmap_title_main_title_matches"] = bool(verification.get("main_title_matches"))
    payload["bitmap_title_subtitle_matches"] = bool(verification.get("subtitle_matches"))
    payload["bitmap_title_style_verified"] = bool(verification.get("style_consistent"))
    payload["bitmap_title_contract_reason"] = str(verification.get("reason") or "").strip()
    payload["bitmap_title_contract_verified_at"] = datetime.now().isoformat()
    payload.pop("bitmap_title_contract_check_unavailable", None)
    payload.pop("bitmap_title_contract_debug", None)
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
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
    payload["bitmap_unexpected_text_detected"] = bool(verification.get("unexpected_bitmap_text_detected"))
    payload["bitmap_unexpected_text_detected_lines"] = list(verification.get("detected_text") or [])
    payload["bitmap_unexpected_text_reason"] = str(verification.get("reason") or "").strip()
    payload["bitmap_unexpected_text_checked_at"] = datetime.now().isoformat()
    payload.pop("bitmap_unexpected_text_check_unavailable", None)
    payload.pop("bitmap_unexpected_text_verification_debug", None)
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
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
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
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
    payload["compare_subject_contract_passed"] = bool(verification.get("compare_subject_contract_passed"))
    payload["compare_subject_contract_reason"] = str(verification.get("reason") or "").strip()
    payload["compare_subject_contract_checked_at"] = datetime.now().isoformat()
    payload.pop("compare_subject_contract_check_unavailable", None)
    payload.pop("compare_subject_contract_verification_debug", None)
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
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
    payload["compare_subject_contract_passed"] = None
    payload["compare_subject_contract_reason"] = str(reason or "").strip()
    payload["compare_subject_contract_checked_at"] = datetime.now().isoformat()
    payload["compare_subject_contract_check_unavailable"] = True
    payload["compare_subject_contract_verification_debug"] = str(debug_error or "").strip()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _director_policy_prefers_compare_subject_pair(director_policy: dict[str, Any] | None) -> bool:
    return False


def _mark_cover_bitmap_title_contract_verification_unavailable(
    request_path: Path,
    *,
    reason: str,
    debug_error: str = "",
) -> None:
    payload = _read_cover_request_payload(request_path)
    if not payload:
        return
    _finalize_cover_request_generation_status(request_path=request_path, payload=payload)
    payload["bitmap_title_contract_passed"] = None
    payload["bitmap_title_main_title_matches"] = None
    payload["bitmap_title_subtitle_matches"] = None
    payload["bitmap_title_style_verified"] = None
    payload["bitmap_title_contract_reason"] = str(reason or "").strip()
    payload["bitmap_title_contract_verified_at"] = datetime.now().isoformat()
    payload["bitmap_title_contract_check_unavailable"] = True
    payload["bitmap_title_contract_debug"] = str(debug_error or "").strip()
    try:
        request_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _finalize_cover_request_generation_status(*, request_path: Path, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        return
    status = str(payload.get("status") or "").strip().lower()
    if status == "completed":
        return
    backend = str(payload.get("backend") or "").strip().lower()
    if backend == "codex_builtin" and not (
        bool(payload.get("generated_by_codex_bridge"))
        or _cover_request_has_post_generation_evidence(payload)
    ):
        return
    output_path = _resolve_cover_request_status_output_path(request_path=request_path, payload=payload)
    if output_path is None:
        return
    try:
        if not output_path.exists() or not output_path.is_file():
            return
    except OSError:
        return
    completed_at = datetime.now().isoformat()
    payload["status"] = "completed"
    payload["completed_at"] = str(payload.get("completed_at") or "").strip() or completed_at
    payload["last_attempted_at"] = completed_at
    payload["result_path"] = str(payload.get("result_path") or output_path)
    if payload.get("auto_completion_error") is None:
        payload["auto_completion_error"] = ""


def _cover_request_has_post_generation_evidence(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if bool(payload.get("post_title_overlay_applied")):
        return True
    for field in (
        "bitmap_title_contract_verified_at",
        "bitmap_unexpected_text_checked_at",
        "compare_subject_contract_checked_at",
        "completed_at",
        "result_path",
    ):
        if str(payload.get(field) or "").strip():
            return True
    return False


def _resolve_cover_request_status_output_path(*, request_path: Path, payload: dict[str, Any]) -> Path | None:
    raw_output_path = str(payload.get("output_path") or "").strip()
    if not raw_output_path:
        return None
    normalized_output_path = raw_output_path.replace("\\", "/")
    container_prefix = "/app/data/"
    if normalized_output_path.startswith(container_prefix):
        repo_root = Path(__file__).resolve().parents[3]
        host_output_root = Path(
            os.getenv("ROUGHCUT_OUTPUT_HOST_ROOT", "") or (repo_root / "data" / "runtime")
        ).expanduser()
        relative = normalized_output_path[len(container_prefix):].lstrip("/")
        return (host_output_root / Path(relative)).resolve()
    output_path = Path(raw_output_path).expanduser()
    if not output_path.is_absolute():
        return (request_path.parent / output_path).resolve()
    try:
        if output_path.exists():
            return output_path
    except OSError:
        return None
    return output_path


def _resolve_cover_verification_bitmap_path(
    *,
    request_payload: dict[str, Any] | None,
    output_path: Path,
) -> Path:
    payload = request_payload if isinstance(request_payload, dict) else {}
    typography_owner = str(
        ((payload.get("cover_director_policy") or {}) if isinstance(payload.get("cover_director_policy"), dict) else {}).get("typography_owner")
        or ""
    ).strip().lower()
    if typography_owner not in {"local_post_overlay", "post_title_overlay"}:
        return output_path
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
    request_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not output_path.exists():
        return {}
    payload = request_payload if isinstance(request_payload, dict) else {}
    director_policy = payload.get("cover_director_policy") if isinstance(payload.get("cover_director_policy"), dict) else {}
    content_scheme = director_policy.get("content_scheme") if isinstance(director_policy.get("content_scheme"), dict) else {}
    verification_prompt = str(content_scheme.get("compare_subject_verification_prompt") or "").strip()
    if not verification_prompt:
        verification_prompt = (
            "请判断这张封面是否把主要商品主体表达清楚。"
            "这里的主体只指真实主商品本身，不把包装盒、托盘、卡片、贴纸、说明纸、配件、景物和装饰元素算作主体。"
            "要求：主角度完整、关键结构清楚、不能只剩局部特写，也不能被背景物喧宾夺主。"
            "如果主体不完整、被严重裁切、被错误弱化成背景，或画面凭空增加误导性的第二主体，就判定 compare_subject_contract_passed=false。"
        )
    prompt = verification_prompt + "\n输出 JSON：" + '{"compare_subject_contract_passed":false,"reason":"竖版构图过近，主主体只剩局部，关键结构不完整"}'
    data, error = await _run_cover_visual_json_verification(
        prompt=prompt,
        output_path=output_path,
        max_tokens=180,
        timeout_sec=45.0,
        attempts=3,
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
    data, error = await _run_cover_visual_json_verification(
        prompt=prompt,
        output_path=output_path,
        max_tokens=220,
        timeout_sec=30.0,
        attempts=2,
    )
    if not data:
        return {}
    return {
        "bitmap_title_contract_passed": bool(data.get("bitmap_title_contract_passed")),
        "main_title_matches": bool(data.get("main_title_matches")),
        "subtitle_matches": bool(data.get("subtitle_matches")),
        "style_consistent": bool(data.get("style_consistent")),
        "detected_main_title": str(data.get("detected_main_title") or "").strip(),
        "detected_subtitle": str(data.get("detected_subtitle") or "").strip(),
        "reason": str(data.get("reason") or "").strip(),
        "debug_error": str(error or "").strip(),
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
    backend = str((image_generation or {}).get("backend") or payload.get("backend") or "").strip().lower()
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
    if output_path.exists() and isinstance(image_generation, dict):
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
        if full_cover_typography_required and backend == "codex_builtin":
            verification = await _verify_generated_cover_bitmap_title_contract(
                output_path=output_path,
                title_lines=title_lines,
            )
            if verification:
                if request_path.exists():
                    _mark_cover_bitmap_title_contract_verified(
                        request_path,
                        title_lines=title_lines,
                        verification=verification,
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["bitmap_title_contract_passed"] = bool(verification.get("bitmap_title_contract_passed"))
                    payload["bitmap_title_main_title_matches"] = bool(verification.get("main_title_matches"))
                    payload["bitmap_title_subtitle_matches"] = bool(verification.get("subtitle_matches"))
                    payload["bitmap_title_style_verified"] = bool(verification.get("style_consistent"))
                    payload["bitmap_title_contract_reason"] = str(verification.get("reason") or "").strip()
                    payload["bitmap_title_contract_verified_at"] = datetime.now().isoformat()
                    if bool(verification.get("bitmap_title_contract_passed")):
                        payload["bitmap_title_lines"] = dict(title_lines or {})
                if not bool(verification.get("bitmap_title_contract_passed")):
                    return payload
            elif full_cover_typography_required:
                reason = "bitmap_title_contract_verification_unavailable"
                if request_path.exists():
                    _mark_cover_bitmap_title_contract_verification_unavailable(
                        request_path,
                        reason=reason,
                        debug_error=str(payload.get("bitmap_title_contract_debug") or ""),
                    )
                    payload = _read_cover_request_payload(request_path)
                else:
                    payload["bitmap_title_contract_passed"] = None
                    payload["bitmap_title_main_title_matches"] = None
                    payload["bitmap_title_subtitle_matches"] = None
                    payload["bitmap_title_style_verified"] = None
                    payload["bitmap_title_contract_reason"] = reason
                    payload["bitmap_title_contract_verified_at"] = datetime.now().isoformat()
                    payload["bitmap_title_contract_check_unavailable"] = True
                    payload["bitmap_title_contract_debug"] = ""
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
    reference_count: int = 1,
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
        reference_count=reference_count,
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
    subject_fidelity_scheme = (
        spec.get("director_policy", {}).get("subject_fidelity_scheme")
        if isinstance(spec.get("director_policy"), dict)
        else {}
    )
    subject_fidelity_constraints = list(
        (
            subject_fidelity_scheme.get("generic_constraints")
            if isinstance(subject_fidelity_scheme, dict)
            else []
        )
        or []
    )
    subject_fidelity_constraints_prompt = ""
    if subject_fidelity_constraints:
        subject_fidelity_constraints_prompt = "主体保真通用约束：" + "；".join(
            str(item or "").strip() for item in subject_fidelity_constraints if str(item or "").strip()
        )
    subject_edit_budget_prompt = str(
        subject_fidelity_scheme.get("edit_budget_prompt")
        if isinstance(subject_fidelity_scheme, dict)
        else ""
    ).strip() or (
        "主体编辑预算必须极小：只允许做清晰度、光影、材质质感和背景氛围增强；"
        "不允许重设计主体几何、主要部件数量、相对位置、表面分区、状态映射或版本对应关系。"
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
    active_title_layers = [
        ("品牌行", brand_line),
        ("主标题", main_title_line),
        ("副标题", subtitle_line),
        ("吸睛文案", hook_line),
    ]
    active_title_layers = [(label, text) for label, text in active_title_layers if text]
    active_title_layer_count = len(active_title_layers)
    director_policy = spec.get("director_policy") if isinstance(spec.get("director_policy"), dict) else {}
    compare_subject_pair_preferred = _director_policy_prefers_compare_subject_pair(director_policy)
    knife_subject = _cover_prompt_targets_knife_subject(spec)
    subject_structure_label = "刀型、结构、开合状态" if knife_subject else "主体结构、主要部件布局、展示状态"
    subject_overlap_label = "刀柄、刀身主体或关键对比关系" if knife_subject else "主体关键结构、主体识别区域或关键对比关系"
    foreground_subject_label = "刀身、手部、相对位置和前景轮廓" if knife_subject else "主体、手持/摆放关系、相对位置和前景轮廓"
    hard_contract_prompt = (
        "硬合同：必须保持参考图产品主体一致，"
        f"不允许改{subject_structure_label}或主角度；"
        "必须直接产出完整可发布封面位图，不允许把标题留给后期再补；"
        f"同一封面组必须保持统一风格化，统一风格 key={hard_contract.get('unified_style_key') or spec.get('style_key') or ''}。"
    )
    title_zone_prompt = (
        "标题区和主体区必须明显分离：上半区用于品牌行、主标题行、副标题行和吸睛文案行，"
        f"下半区或左右下方保留主体展示，不要让标题压到{subject_overlap_label}。"
    )
    canvas_size = spec.get("canvas_size") if isinstance(spec.get("canvas_size"), dict) else {}
    canvas_width = int(canvas_size.get("width") or 0)
    canvas_height = int(canvas_size.get("height") or 0)
    portrait_compare_instruction = ""
    if compare_subject_pair_preferred and canvas_height > canvas_width:
        content_scheme = director_policy.get("content_scheme") if isinstance(director_policy.get("content_scheme"), dict) else {}
        portrait_compare_instruction = str(
            content_scheme.get("portrait_compare_instruction") if isinstance(content_scheme, dict) else ""
        ).strip()
        if not portrait_compare_instruction:
            portrait_compare_instruction = (
                "即使标题里在讲版本差异，封面也不要凭空扩展成双主体设定。"
                "优先把真实主主体放大、看清主要轮廓和关键结构，四周保留适度安全边距。"
                "不要为了制造对比感硬塞第二个主体，也不要做近距离怼脸式裁切。"
            )
    matrix_scheme = (
        spec.get("director_policy", {}).get("matrix_scheme")
        if isinstance(spec.get("director_policy"), dict)
        else {}
    )
    matrix_layout_instruction = _build_cover_matrix_layout_prompt(
        matrix_scheme.get("layout_constraints") if isinstance(matrix_scheme, dict) else {}
    )
    line_split_instruction = ""
    if active_title_layer_count >= 3:
        layer_names = "、".join(label for label, _text in active_title_layers)
        line_split_instruction = (
            f"标题必须按 {active_title_layer_count} 层信息布局直接完整渲染：{layer_names}。"
            "主标题必须最大、最有压场感；品牌行独立在上方；"
            + (
                "副标题作为第二层信息条；" if subtitle_line else ""
            )
            + (
                "吸睛文案做成短 badge。"
                if hook_line
                else "其余辅助信息层级必须明显弱于主标题。"
            )
        )
    elif active_title_layer_count == 2:
        layer_names = "、".join(label for label, _text in active_title_layers)
        line_split_instruction = (
            f"标题必须按 2 层信息布局直接完整渲染：{layer_names}。"
            "主标题必须最大；另一层作为辅助信息，明显更小，不要重复主标题语义。"
        )
    required_text_prompt = (
        "必须直接在最终位图里完整渲染这些真实文字："
        + "；".join(f"{label}「{text}」" for label, text in active_title_layers)
        + "。"
        if active_title_layers
        else "如果画面里出现文字，只允许使用提示词里明确要求的标题内容。"
    )
    allowed_text_layer_prompt = (
        "只允许渲染上面明确要求的这些文字层；不要额外添加 slogan、包装字、字幕、功能标签、按钮或任何未要求的字。"
        if active_title_layers
        else "不要额外添加 slogan、包装字、字幕、功能标签、按钮或任何未要求的字。"
    )
    safe_layout_prompt = (
        "构图优先做成成熟短视频爆款封面：主体聚在下半区或两侧下方，"
        "上中部留下干净但有能量感的标题舞台；不要再把标题区和主体强行堆在同一个中央区域。"
    )
    reference_pack_prompt = _cover_reference_pack_prompt(
        reference_count=int(spec.get("reference_count") or 1),
    )
    selling_line = f"封面要表达的卖点：{selling_angle}" if selling_angle else ""
    visual_line = f"画面重点：{visual_brief}" if visual_brief else ""
    video_type_line = f"视频题材：{video_type}" if video_type else ""
    subject_identity_line = (
        "主体说明：保持参考图中的同一商品主体和版本关系，不改变品牌归属、型号类别、材质关系与主角度。"
        if compare_subject_pair_preferred
        else "主体说明：保持参考图中的同一商品主体，不改变品牌归属、型号类别、材质关系与主角度，也不要凭空增加第二主体。"
    )
    subject_requirement_line = (
        "要求：主体必须还是参考图里的真实商品；如果参考图里明确是两件主要对比主体，就保持这两件都清晰完整。"
        "优先做强点击封面化编排：主体放大、版本差异可读、手持真实、细节锐利。"
        if compare_subject_pair_preferred
        else "要求：主体必须还是参考图里的真实商品；优先做强点击封面化编排：主体放大、细节清楚、手持真实、质感锐利，不要把背景物件误生成第二主体。"
    )
    return (
        "基于参考图生成一张可直接发布的完整视频封面。\n"
        f"平台：{spec['platform_label']}\n"
        f"视觉方向：{spec['visual_instruction']}\n"
        f"{video_type_line}\n"
        f"{reference_pack_prompt}\n"
        f"{subject_identity_line}\n"
        f"{selling_line}\n"
        f"{visual_line}\n"
        f"{subject_fidelity_constraints_prompt}\n"
        f"{critical_detail_prompt}\n"
        f"{hard_contract_prompt}\n"
        f"{packaging_text_exclusion_instruction}\n"
        f"{background_strategy_prompt}\n"
        f"{style_prompt}\n"
        f"{title_zone_prompt}\n"
        f"{safe_layout_prompt}\n"
        f"{required_text_prompt}\n"
        "编辑策略：前景主体结构保留优先。优先保留参考图里已有的"
        f"{foreground_subject_label}，"
        "重点改背景、光影、氛围特效和标题排版，不要重新设计主体几何结构。\n"
        f"{subject_edit_budget_prompt}\n"
        f"{subject_requirement_line}"
        f"{portrait_compare_instruction}"
        f"{matrix_layout_instruction}"
        f"{line_split_instruction}"
        f"{allowed_text_layer_prompt}"
        "标题字效必须直接在位图里完成，不要留空白牌位等后期占位方案。"
        "背景特效必须保留高能电光、金属质感、火焰能量和赛博发光史诗氛围，不要弱化成普通干净背景。"
        "标题舞台必须集中在上中部，主体展示集中在下半区或左右下方，适配常见平台居中裁切。\n"
        "禁止：任何未要求的可读文字、字幕、水印、伪 logo、乱码、错别字、改变主体身份。"
    )


def _build_provider_safe_cover_image_prompt(*, spec: dict[str, Any]) -> str:
    brief_text = "\n".join(spec["brief_lines"])
    immutable_text = "\n".join(spec["immutable_requirements"])
    background_strategy_prompt = _background_strategy_prompt(spec.get("background_strategy") or "")
    reference_pack_prompt = _cover_reference_pack_prompt(
        reference_count=int(spec.get("reference_count") or 1),
    )
    critical_detail_notes = list(spec.get("critical_detail_notes") or [])
    hard_contract = spec.get("hard_contract") if isinstance(spec.get("hard_contract"), dict) else {}
    critical_detail_prompt = ""
    if critical_detail_notes:
        critical_detail_prompt = "关键细节硬约束：\n" + "\n".join(f"- {note}" for note in critical_detail_notes)
    subject_fidelity_scheme = (
        spec.get("director_policy", {}).get("subject_fidelity_scheme")
        if isinstance(spec.get("director_policy"), dict)
        else {}
    )
    subject_fidelity_constraints = list(
        (
            subject_fidelity_scheme.get("generic_constraints")
            if isinstance(subject_fidelity_scheme, dict)
            else []
        )
        or []
    )
    subject_fidelity_constraints_prompt = ""
    if subject_fidelity_constraints:
        subject_fidelity_constraints_prompt = "主体保真通用约束：\n" + "\n".join(
            f"- {str(item or '').strip()}" for item in subject_fidelity_constraints if str(item or "").strip()
        )
    compare_subject_pair_preferred = _director_policy_prefers_compare_subject_pair(
        spec.get("director_policy") if isinstance(spec.get("director_policy"), dict) else {}
    )
    knife_subject = _cover_prompt_targets_knife_subject(spec)
    subject_structure_label = "刀型、结构、开合状态" if knife_subject else "主体结构、主要部件布局、展示状态"
    foreground_subject_label = "刀身、手持关系和前景轮廓" if knife_subject else "主体结构、摆放/手持关系和前景轮廓"
    hard_contract_prompt = (
        "硬合同：\n"
        f"- 必须保持参考图产品主体一致，不允许改{subject_structure_label}或主角度。\n"
        "- 必须为后期统一叠加品牌/型号主标题和配置副标题预留清晰标题安全区，但底图里不能直接画任何标题字。\n"
        f"- 同一封面组必须统一风格化，统一风格 key={hard_contract.get('unified_style_key') or spec.get('style_key') or ''}。"
    )
    packaging_text_exclusion_instruction = (
        "包装盒、卡片、贴纸、说明纸、印刷 logo 或任何可读包装字样都不能原样保留在底图里；"
        "如果参考图里有这些元素，必须裁掉、弱化、虚化，或替换成无字环境纹理。"
    )
    no_text_bitmap_instruction = (
        "底图里禁止出现任何可读或半可读的中文、英文、数字、logo 字牌、产品本体铭文、品牌章、字幕、水印、海报字效或伪文字；"
        "如果产品本体或包装上原本有品牌字样，只保留对应位置的材质/刻印关系，不要让任何字母数字保持可读。"
    )
    return (
        "基于参考图生成封面底图。\n"
        f"封面主题：{spec['title']}\n"
        f"画面方向：{spec['visual_instruction']}\n"
        f"{reference_pack_prompt}\n"
        f"{brief_text}\n"
        f"{subject_fidelity_constraints_prompt}\n"
        f"{critical_detail_prompt}\n"
        f"{hard_contract_prompt}\n"
        f"{packaging_text_exclusion_instruction}\n"
        f"{no_text_bitmap_instruction}\n"
        f"品牌/商品身份必须通过外形、结构、材质关系和{'版本差异' if compare_subject_pair_preferred else '主体细节'}稳定表达：{spec['product_identity']}\n"
        f"{background_strategy_prompt}\n"
        f"{spec['style_prompt']}\n"
        "编辑策略：前景主体结构保留优先，尽量保留参考图里已有的"
        f"{foreground_subject_label}；"
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
    reference_count: int = 1,
) -> dict[str, Any]:
    cover_backend = _resolve_active_cover_image_backend()
    typography_owner = _resolve_cover_typography_owner_for_backend(cover_backend)
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
    compare_subject_pair_preferred = _has_explicit_cover_compare_signal(
        " ".join(
            part
            for part in (
                title_text,
                product_identity,
                selling_angle,
                video_type,
                *list((title_lines or {}).values()),
            )
            if str(part or "").strip()
        )
    )
    immutable_requirements = [
        (
            "主体必须是参考图里的同一个商品；如果内容明确是双版本/双主体对比，就保持这两个主要主体都稳定可辨。"
            if compare_subject_pair_preferred
            else "主体必须是参考图里的同一个商品，不要凭空增加第二主体或额外版本。"
        ),
        "主体一致性是最高优先级：不改商品身份，不改品牌归属，不改核心结构。",
        "优先保留参考图前景主体的原始结构和相对关系；允许重点增强的是背景、光影、氛围和标题区域。",
        "重点强调商品细节一致性：保留轮廓、比例、关键开合关系、纹理分区和主要部件位置，不改款，不变形。",
        (
            "在主体不变的前提下，加强构图、光影、清晰度、对比和质感，突出版本差异。"
            if compare_subject_pair_preferred
            else "在主体不变的前提下，加强构图、光影、清晰度、对比和质感，突出真实细节与材质表现。"
        ),
    ]
    if typography_owner == "local_post_overlay":
        immutable_requirements.extend(
            [
                "底图语义要和封面主题一致，但不能依赖任何可读文字来表达品牌或型号。",
                "必须预留清晰标题安全区，后期统一叠加品牌行、主标题、副标题和吸睛文案。",
                "底图里不能直接画任何可读或半可读文字；如果主体或包装上有品牌刻字、logo 字牌或型号铭文，只保留位置关系和材质质感，不要让字母数字保持可读。",
            ]
        )
    else:
        immutable_requirements.extend(
            [
                "品牌/商品识别词不能丢，底图语义要与封面主题一致，不能换成泛称。",
                "标题结构必须准确完整：品牌行、主标题、副标题和吸睛文案都要按合同生成。",
            ]
        )
    for note in critical_detail_notes:
        immutable_requirements.append(f"关键细节不能画错：{note}")
    hard_contract = _build_cover_hard_contract(
        title=title_text,
        cover_brief=brief,
        style_key=style_key,
        title_lines=title_lines,
        typography_owner=typography_owner,
    )
    director_policy = _build_cover_director_policy(
        style_key=style_key,
        title_lines=title_lines,
        hard_contract=hard_contract,
        typography_owner=typography_owner,
        platform_label=str(rules.get("label") or str(platform_key or "").strip() or "通用封面"),
        visual_instruction=instruction,
        strategy_axes=dict(brief.get("strategy_axes") or {}) if isinstance(brief.get("strategy_axes"), dict) else None,
        canvas_size=(int(width), int(height)),
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
        "reference_count": max(1, int(reference_count or 1)),
        "critical_detail_notes": critical_detail_notes,
        "brief_lines": brief_lines,
        "immutable_requirements": immutable_requirements,
        "title_lines": title_lines,
        "hard_contract": hard_contract,
        "director_policy": director_policy,
        "cover_backend": cover_backend,
        "typography_owner": typography_owner,
    }


def _build_cover_hard_contract(
    *,
    title: str,
    cover_brief: dict[str, Any],
    style_key: str,
    title_lines: dict[str, str] | None,
    typography_owner: str,
) -> dict[str, Any]:
    identity = str(cover_brief.get("product_identity") or "").strip()
    selling_angle = str(cover_brief.get("selling_angle") or "").strip()
    video_type = str(cover_brief.get("video_type") or "").strip()
    layout = dict(title_lines or {})
    local_overlay_required = str(typography_owner or "").strip().lower() == "local_post_overlay"
    return {
        "subject_identity_required": True,
        "preserve_subject_geometry": True,
        "preserve_primary_angle_if_present": True,
        "preserve_open_state_if_present": True,
        "compare_subject_pair_required": False,
        "brand_model_title_required": bool(identity or title),
        "config_subtitle_required": bool(layout.get("bottom") or selling_angle or video_type),
        "hook_badge_required": bool(layout.get("hook")),
        "full_bitmap_cover_required": not local_overlay_required,
        "post_title_overlay_required": local_overlay_required,
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
    typography_owner: str,
    platform_label: str,
    visual_instruction: str = "",
    strategy_axes: dict[str, Any] | None = None,
    canvas_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    profile = dict(COVER_DIRECTOR_STYLE_PROFILES.get(str(style_key or "").strip()) or {})
    layout = dict(title_lines or {})
    contract = dict(hard_contract or {})
    axes = dict(strategy_axes or {})
    width, height = tuple(canvas_size or (0, 0))
    matrix_key = _resolve_cover_matrix_group_key(width=int(width or 0), height=int(height or 0)) if width and height else ""
    matrix_profile = _cover_matrix_group_profile(matrix_key) if matrix_key else {}
    matrix_scheme = dict(axes.get("matrix_scheme") or {})
    matrix_scheme.update(
        {
            "key": matrix_key,
            "canvas_size": [int(width), int(height)] if width and height else [],
            "layout_constraints": dict(matrix_profile.get("layout_constraints") or {}),
        }
    )
    creator_style_scheme = dict(axes.get("creator_style_scheme") or {})
    creator_style_scheme.setdefault("style_profile_key", str(profile.get("style_profile_key") or "").strip())
    subject_fidelity_scheme = dict(axes.get("subject_fidelity_scheme") or {})
    content_scheme = dict(axes.get("content_scheme") or {})
    effective_style_profile_key = str(creator_style_scheme.get("style_profile_key") or profile.get("style_profile_key") or "").strip()
    owner = str(typography_owner or "").strip().lower() or "codex_full_cover"
    local_overlay_required = owner == "local_post_overlay"
    return {
        "direction_version": "local_overlay_required_v1" if local_overlay_required else "full_cover_codex_v1",
        "codex_role": "render_cover_base_for_local_overlay" if local_overlay_required else "render_final_cover_with_integrated_typography",
        "goal": (
            "Let the image backend produce a clean cover base that is safe for local title overlay."
            if local_overlay_required
            else "Let Codex image generation produce the final publishable cover with integrated typography and unified style."
        ),
        "typography_owner": owner,
        "platform_label": str(platform_label or "").strip(),
        "visual_instruction": str(visual_instruction or "").strip(),
        "style_key": str(style_key or "").strip(),
        "style_profile_key": effective_style_profile_key,
        "base_style_profile_key": str(profile.get("style_profile_key") or "").strip(),
        "headline_effects": list(profile.get("headline_effects") or []),
        "layout_contract": list(profile.get("layout_contract") or ["brand_line", "main_title", "subtitle", "hook_badge"]),
        "composition_contract": dict(profile.get("composition_contract") or {}),
        "matrix_scheme": matrix_scheme,
        "content_scheme": content_scheme,
        "creator_style_scheme": creator_style_scheme,
        "subject_fidelity_scheme": subject_fidelity_scheme,
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
            *(
                [
                    "A real bitmap generated by the selected image backend.",
                    "The bitmap is a clean cover base for local typography overlay, not the final text-integrated cover.",
                    "No extra unrequested typography, subtitles, watermarks, or unrelated pseudo logos appear in the bitmap.",
                    "Key subject stays complete and readable after later typography placement.",
                    "The generated bitmap copied to output_path before marking this request completed.",
                ]
                if local_overlay_required
                else [
                    "A real bitmap generated with Codex built-in image_gen/edit mode.",
                    "The bitmap is the final cover, not a text-free base image.",
                    "The bitmap already contains the requested brand line, main title, subtitle, and hook badge in a unified style.",
                    "No extra unrequested typography, subtitles, watermarks, or unrelated pseudo logos appear in the bitmap.",
                    "Key subject stays complete and readable after typography placement.",
                    "The generated bitmap copied to output_path before marking this request completed.",
                ]
            ),
        ],
        "supports_compare_subject_pair": False,
    }


def _resolve_active_cover_image_backend() -> str:
    settings = get_settings()
    backend = str(getattr(settings, "intelligent_copy_cover_image_backend", "") or "codex_builtin").strip().lower()
    if backend in {"", "codex", "codex_cli", "codex_imagegen"}:
        return "codex_builtin"
    if backend == "openai_api":
        return "openai_images_api"
    if backend in {"minimax", "minimax_api"}:
        return "minimax_images_api"
    if backend in {"dreamina", "dreamina_cdp", "dreamina_web_cdp"}:
        return "dreamina_web"
    if backend in {"openai_images_api", "minimax_images_api", "dreamina_web"}:
        return backend
    return "codex_builtin"


def _resolve_cover_typography_owner_for_backend(backend: str) -> str:
    return "codex_full_cover" if str(backend or "").strip().lower() == "codex_builtin" else "local_post_overlay"


def _cover_prompt_targets_knife_subject(spec: dict[str, Any] | None) -> bool:
    payload = spec if isinstance(spec, dict) else {}
    blob = " ".join(
        str(payload.get(key) or "").strip()
        for key in ("product_identity", "selling_angle", "visual_brief", "video_type", "title")
        if str(payload.get(key) or "").strip()
    )
    return bool(re.search(r"折刀|跳刀|刀具|刀身|刀柄|开刃|背夹|刃面|刀尖|直跳|otf", blob, re.I))


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
    action_tail_pattern = r"(双版本开箱|双版开箱|双版本对比|双版对比|开箱|评测|测评|教程|体验)$"
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
        action_match = re.search(action_tail_pattern, remainder)
        if action_match:
            pivot = action_match.start()
            subject = remainder[:pivot].strip()
            bottom = action_match.group(1).strip()[:18]
            if subject and re.search(r"[\u4e00-\u9fff]", subject):
                return {"top": brand, "main": subject[:18], "bottom": bottom}
    compare_match = re.search(r"(双版开箱对比|开箱对比|版本对比|双版对比|对比)$", normalized)
    if compare_match:
        pivot = compare_match.start()
        subject = normalized[:pivot].strip()[:16]
        bottom = compare_match.group(1).strip()[:18]
        if subject:
            return {"top": "", "main": subject, "bottom": bottom}
    action_match = re.search(action_tail_pattern, normalized)
    if action_match:
        pivot = action_match.start()
        subject = normalized[:pivot].strip()
        bottom = action_match.group(1).strip()[:18]
        if subject and re.search(r"[\u4e00-\u9fff]", subject):
            return {"top": "", "main": subject[:18], "bottom": bottom}
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
    brand, main, subtitle, hook = _dedupe_cover_title_layout_lines(
        brand=top[:14],
        main=main[:18],
        subtitle=bottom[:18],
        hook=hook[:18],
    )
    if not main:
        return None
    return {
        "brand": brand,
        "top": brand,
        "main": main,
        "sub": subtitle,
        "bottom": subtitle,
        "hook": hook,
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


def _cover_title_has_action_signal(value: str) -> bool:
    return _shared_cover_title_has_action_signal(value)


def _cover_title_has_evidence_signal(value: str) -> bool:
    return _shared_cover_title_has_evidence_signal(value)


def _cover_title_has_variant_signal(value: str) -> bool:
    return _shared_cover_title_has_variant_signal(value)


def _normalize_cover_title_dedupe_signature(value: str) -> str:
    return _shared_normalize_cover_title_dedupe_signature(value)


def _strip_cover_brand_prefix(value: str, brand: str) -> str:
    return _shared_strip_cover_brand_prefix(value, brand)


def _strip_cover_action_suffix(value: str) -> str:
    return _shared_strip_cover_action_suffix(value)


def _cover_title_semantic_core(
    value: str,
    *,
    brand: str = "",
    strip_compare: bool = False,
    strip_action: bool = False,
) -> str:
    return _shared_cover_title_semantic_core(
        value,
        brand=brand,
        strip_compare=strip_compare,
        strip_action=strip_action,
        strip_compare_suffix=_strip_cover_compare_suffix,
    )


def _resolve_cover_title_semantic_slot(*, value: str, layer_role: str) -> str:
    return _shared_resolve_cover_title_semantic_slot(value=value, layer_role=layer_role)


def _build_cover_title_semantic_plan(*, brand: str, main: str, subtitle: str, hook: str) -> dict[str, dict[str, Any]]:
    semantic_plan = _shared_build_cover_title_semantic_plan(
        brand=brand,
        main=main,
        subtitle=subtitle,
        hook=hook,
        strip_compare_suffix=_strip_cover_compare_suffix,
    )
    semantic_plan["main"]["has_compare_signal"] = _cover_title_line_contains_compare_tail(str(semantic_plan["main"].get("text") or ""))
    semantic_plan["subtitle"]["has_compare_signal"] = _cover_title_line_contains_compare_tail(str(semantic_plan["subtitle"].get("text") or ""))
    semantic_plan["hook"]["has_compare_signal"] = _cover_title_line_contains_compare_tail(str(semantic_plan["hook"].get("text") or ""))
    return semantic_plan


def _dedupe_cover_title_layout_lines(*, brand: str, main: str, subtitle: str, hook: str) -> tuple[str, str, str, str]:
    return _shared_dedupe_cover_title_layout_lines(
        brand=brand,
        main=main,
        subtitle=subtitle,
        hook=hook,
        strip_compare_suffix=_strip_cover_compare_suffix,
    )


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


def _has_explicit_cover_compare_signal(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return False
    explicit_phrases = (
        "顶配和次顶配",
        "顶配/次顶配",
        "顶配vs次顶配",
        "顶配 vs 次顶配",
        "顶配与次顶配",
        "顶配次顶配",
        "双版对比",
        "双版本对比",
        "双版本开箱",
        "双版开箱",
        "同款不同配",
        "两个版本",
        "两款对比",
        "两款开箱",
        "版本取舍",
    )
    if any(phrase in normalized for phrase in explicit_phrases):
        return True
    has_config_pair = "顶配" in normalized and "次顶配" in normalized
    has_multi_variant = has_config_pair or any(token in normalized for token in ("双版", "双版本", "两款", "两个版本"))
    has_compare_action = any(token in normalized for token in ("对比", "区别", "差异", "差别", "怎么选", "选哪", "取舍"))
    has_unboxing = any(token in normalized for token in ("开箱", "到手", "上手", "unbox"))
    return has_multi_variant and (has_compare_action or has_unboxing)


def _cover_title_line_contains_compare_tail(value: str) -> bool:
    return _has_explicit_cover_compare_signal(value)


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


def _resolve_cover_creator_style_profile_key(*, creator_profile_name: str, style_key: str) -> str:
    creator_name = str(creator_profile_name or "").strip()
    normalized = creator_name.casefold()
    if "fas" in normalized and str(style_key or "").strip() == "edc_cinematic_hero":
        return "fas_edc_signature_full_cover_v1"
    return f"{str(style_key or '').strip() or 'default'}_generic_full_cover_v1"


def _resolve_cover_content_strategy_key(*, cover_brief: dict[str, Any], title_lines: dict[str, str] | None = None) -> str:
    brief = dict(cover_brief or {})
    title_blob = " ".join(
        part
        for part in (
            brief.get("video_type"),
            brief.get("selling_angle"),
            brief.get("product_identity"),
            *list((title_lines or {}).values()),
        )
        if str(part or "").strip()
    )
    if re.search(r"开箱|unbox", title_blob, re.I):
        return "unboxing_single_subject_v1"
    if re.search(r"教程|教学|怎么用|tutorial", title_blob, re.I):
        return "tutorial_demo_v1"
    return "generic_showcase_v1"


def _resolve_cover_content_strategy_profile(strategy_key: str) -> dict[str, Any]:
    return dict(COVER_CONTENT_STRATEGY_PROFILES.get(str(strategy_key or "").strip()) or {})


def _annotate_cover_strategy_axes(
    cover_brief: dict[str, Any],
    *,
    creator_profile_name: str = "",
    copy_brief: dict[str, Any] | None = None,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    brief = dict(cover_brief or {})
    if not brief:
        return brief
    title_lines = _build_cover_title_layout_plan(title=str(brief.get("cover_title") or "").strip(), cover_brief=brief)
    style_key = str(brief.get("style_key") or "").strip() or _resolve_cover_image_style_key(rules={}, cover_brief=brief)
    creator_name = str(creator_profile_name or brief.get("creator_profile_name") or "").strip()
    content_strategy_key = _resolve_cover_content_strategy_key(cover_brief=brief, title_lines=title_lines)
    content_strategy_profile = _resolve_cover_content_strategy_profile(content_strategy_key)
    subject_fidelity_scheme_key = _resolve_subject_fidelity_scheme_key(
        content_strategy_key=content_strategy_key,
        cover_brief=brief,
        copy_brief=copy_brief,
    )
    subject_fidelity_scheme_profile = _resolve_subject_fidelity_scheme_profile(subject_fidelity_scheme_key)
    creator_style_profile_key = _resolve_cover_creator_style_profile_key(
        creator_profile_name=creator_name,
        style_key=style_key,
    )
    instance_observations = _normalize_cover_critical_detail_notes(brief.get("critical_detail_notes"))
    if not instance_observations:
        instance_observations = _default_cover_critical_detail_notes(
            packaging={
                "highlights": {
                    "product": str(brief.get("product_identity") or "").strip(),
                    "video_type": str(brief.get("video_type") or "").strip(),
                    "strongest_selling_point": str(brief.get("selling_angle") or "").strip(),
                }
            },
            content_profile=dict(content_profile or {}),
            copy_brief=dict(copy_brief or {}),
        )
    strategy_axes = {
        "matrix_scheme": {
            "scope": "cross_platform_cover_matrix",
            "description": "比例母版与跨平台封面矩阵方案。",
        },
        "content_scheme": {
            "key": content_strategy_key,
            "scope": "vertical_program_cover_logic",
            "video_type": str(brief.get("video_type") or "").strip() or str((copy_brief or {}).get("intent") or "").strip(),
            "description": str(content_strategy_profile.get("description") or "节目垂直选帧、标题结构与构图策略。").strip(),
            "compare_subject_policy": str(content_strategy_profile.get("compare_subject_policy") or "").strip(),
            "allow_mixed_open_closed_states": bool(content_strategy_profile.get("allow_mixed_open_closed_states")),
            "portrait_compare_instruction": str(content_strategy_profile.get("portrait_compare_instruction") or "").strip(),
            "compare_subject_verification_prompt": str(content_strategy_profile.get("compare_subject_verification_prompt") or "").strip(),
        },
        "creator_style_scheme": {
            "creator_profile_name": creator_name or str((content_profile or {}).get("subject_brand") or "").strip(),
            "style_key": style_key,
            "style_profile_key": creator_style_profile_key,
            "scope": "creator_signature_art_direction",
            "description": "创作者专属封面艺术风格方案。",
        },
        "subject_fidelity_scheme": {
            "key": subject_fidelity_scheme_key,
            "scope": "subject_fidelity_contract",
            "description": str(subject_fidelity_scheme_profile.get("description") or "主体保真与实例细节约束。").strip(),
            "edit_budget_prompt": str(subject_fidelity_scheme_profile.get("edit_budget_prompt") or "").strip(),
            "generic_constraints": list(subject_fidelity_scheme_profile.get("generic_constraints") or []),
            "instance_observations": instance_observations,
        },
    }
    brief["style_key"] = style_key
    brief["creator_profile_name"] = creator_name or None
    brief["strategy_axes"] = strategy_axes
    return brief


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
        _intelligent_copy_semantic_text(item)
        for item in subtitle_items[:100]
    ).strip()
    summary = str(content_profile.get("summary") or "").strip()
    subject_brand = str(content_profile.get("subject_brand") or "").strip()
    subject_model = str(content_profile.get("subject_model") or "").strip()
    subject_type = str(content_profile.get("subject_type") or "").strip()
    subject_label = "".join(part for part in (subject_brand, subject_model) if part) or subject_brand or subject_model or video_path.stem
    evidence_context = " ".join(part for part in (video_path.stem, transcript_text) if part)
    question_context = " ".join(part for part in (video_path.stem, transcript_text, summary) if part)
    question = _resolve_intelligent_copy_question(content_profile=content_profile, context_text=question_context)
    topic_spec = match_intelligent_copy_topic(evidence_context)
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
    derived_intent = _derive_generic_intelligent_copy_intent(evidence_context)
    derived_focus_points = _derive_generic_intelligent_copy_focus_points(evidence_context)
    return {
        "topic_subject": subject_label or video_path.stem,
        "intent": derived_intent,
        "summary": summary or f"这期主要围绕{subject_label or video_path.stem}展开。",
        "question": question,
        "focus_points": derived_focus_points,
        "tags": [
            subject_brand,
            subject_model,
            subject_type,
            video_path.stem,
            *(["顶配", "次顶配", "对比"] if derived_intent == "comparison_unboxing" else []),
            "开箱",
            "上手体验",
        ],
        "anchor_terms": [subject_brand, subject_model, subject_type, video_path.stem],
        "forbidden_terms": [],
        "title_candidates": _build_generic_intelligent_copy_title_candidates(
            topic_subject=subject_label or video_path.stem,
            normalized_context=evidence_context,
        ),
        "subject_type": subject_type,
    }


def _resolve_intelligent_copy_question(*, content_profile: dict[str, Any], context_text: str) -> str:
    question = str(content_profile.get("engagement_question") or "").strip()
    if question and not _is_generic_engagement_question(question):
        return question
    preset = select_workflow_template(
        workflow_template=str(content_profile.get("workflow_template") or "").strip() or None,
        transcript_hint=str(context_text or "").strip(),
    )
    repaired_profile = {
        **dict(content_profile or {}),
        "engagement_question": question,
    }
    return _build_fallback_engagement_question(repaired_profile, preset)


def _build_publish_safe_copy_summary(*, subject_label: str, context_text: str) -> str:
    subject = str(subject_label or "这期内容").strip()
    normalized = str(context_text or "").strip()
    if _has_explicit_compare_unboxing_signal(normalized):
        return f"{subject}双版本开箱，重点看版本差异、细节展示和上手体验。"
    if "开箱" in normalized or "到手" in normalized or "上手" in normalized:
        return f"这期围绕{subject}展开，重点看开箱过程、细节展示和上手体验。"
    if "对比" in normalized or "区别" in normalized or "差异" in normalized:
        return f"这期围绕{subject}展开，重点看版本差异和细节表现。"
    return f"这期围绕{subject}展开，重点看画面里能确认的细节和实际观感。"


def _derive_generic_intelligent_copy_intent(context_text: str) -> str:
    normalized = str(context_text or "").strip().lower()
    if not normalized:
        return "generic"
    has_compare = _has_explicit_compare_signal(normalized)
    has_unboxing = any(token in normalized for token in ("开箱", "到手", "上手"))
    if has_compare and has_unboxing:
        return "comparison_unboxing"
    if has_unboxing:
        return "decor_unboxing"
    return "generic"


def _derive_generic_intelligent_copy_focus_points(context_text: str) -> list[str]:
    normalized = str(context_text or "").strip()
    if _has_explicit_compare_signal(normalized):
        return ["顶配", "次顶配", "细节差异"]
    if "对比" in normalized or "区别" in normalized or "差异" in normalized:
        return ["版本差异", "细节展示", "上手体验"]
    if "开箱" in normalized or "上手" in normalized:
        return ["开箱过程", "细节展示", "上手体验"]
    return ["细节展示", "真实体验", "重点信息"]


def _build_generic_intelligent_copy_title_candidates(*, topic_subject: str, normalized_context: str) -> list[str]:
    subject = str(topic_subject or "").strip()
    normalized = str(normalized_context or "").strip().lower()
    if not subject:
        return []
    if _has_explicit_compare_signal(normalized):
        return [
            f"{subject}顶配和次顶配到底差在哪",
            f"{subject}双版本开箱，先看差别",
            f"{subject}顶配/次顶配实拍对比",
        ]
    if "对比" in normalized or "区别" in normalized or "差异" in normalized:
        return [
            f"{subject}实拍对比，差别在哪",
            f"{subject}这次重点看版本差异",
        ]
    return []


def _has_explicit_compare_unboxing_signal(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    has_unboxing = any(token in normalized for token in ("开箱", "到手", "上手"))
    return has_unboxing and _has_explicit_compare_signal(normalized)


def _has_explicit_compare_signal(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    explicit_phrases = (
        "顶配和次顶配",
        "顶配/次顶配",
        "顶配vs次顶配",
        "顶配 vs 次顶配",
        "顶配与次顶配",
        "顶配次顶配",
        "双版对比",
        "双版本对比",
        "同款不同配",
        "两个版本",
        "两款对比",
        "版本取舍",
    )
    if any(phrase in normalized for phrase in explicit_phrases):
        return True
    has_config_pair = "顶配" in normalized and "次顶配" in normalized
    has_multi_variant = has_config_pair or any(token in normalized for token in ("双版", "双版本", "两款", "两个版本"))
    has_compare_action = any(token in normalized for token in ("对比", "区别", "差异", "差别", "怎么选", "选哪", "取舍"))
    return has_multi_variant and has_compare_action


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
        platform_copy_brief = _copy_brief_for_platform(copy_brief=copy_brief, platform_key=platform_key)
        titles = _build_intelligent_copy_titles(platform_key=platform_key, rules=rules, copy_brief=platform_copy_brief, content_profile=content_profile)
        description = _build_intelligent_copy_description(platform_key=platform_key, copy_brief=platform_copy_brief)
        tags = _build_intelligent_copy_tags(copy_brief=platform_copy_brief, rules=rules)
        platforms[platform_key] = {
            "titles": titles,
            "description": description,
            "tags": tags,
        }
    packaging["platforms"] = platforms
    return packaging


def _copy_brief_for_platform(*, copy_brief: dict[str, Any], platform_key: str) -> dict[str, Any]:
    del platform_key
    return dict(copy_brief or {})


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
    forbidden_terms = [str(item).strip() for item in (copy_brief.get("forbidden_terms") or []) if str(item).strip()]
    anchor_terms = [str(item).strip() for item in (copy_brief.get("anchor_terms") or []) if str(item).strip()]
    explicit_candidates = [str(item).strip() for item in (copy_brief.get("title_candidates") or []) if str(item).strip()]
    candidate_pool: list[str] = []
    if explicit_candidates:
        candidate_pool.extend(explicit_candidates)
    candidate_pool.extend(
        build_constraint_only_title_candidates(
            topic_subject=topic_subject,
            focus_points=focus_points,
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
            f"{subject}双版本开箱，先看差别",
            f"{subject}{_humanize_compare_tail(compare_tail)}到底差在哪",
            f"{subject}实拍对比，{_humanize_compare_tail(compare_tail)}怎么选",
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


def _humanize_compare_tail(compare_tail: str) -> str:
    normalized = str(compare_tail or "").strip()
    if normalized == "顶配vs次顶配":
        return "顶配和次顶配"
    if normalized == "双版对比":
        return "双版本"
    if normalized == "版本对比":
        return "不同版本"
    return normalized


def _build_intelligent_copy_description(*, platform_key: str, copy_brief: dict[str, Any]) -> str:
    summary = str(copy_brief.get("summary") or "").strip()
    question = str(copy_brief.get("question") or "").strip()
    focus_points = [str(item).strip() for item in (copy_brief.get("focus_points") or []) if str(item).strip()]
    focus_line = "、".join(focus_points[:3])
    forbidden_terms = [str(item).strip() for item in (copy_brief.get("forbidden_terms") or []) if str(item).strip()]
    topic_subject = str(copy_brief.get("topic_subject") or "").strip()
    anchor_terms = [str(item).strip() for item in (copy_brief.get("anchor_terms") or []) if str(item).strip()]
    description = build_constraint_only_platform_description(
        summary=summary,
        question=question,
        focus_line=focus_line,
        topic_subject=topic_subject,
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
        return _sanitize_copy_line(
            build_constraint_only_platform_description(
                summary=summary,
                question=question,
                focus_line=focus_line,
                topic_subject=topic_subject,
            )
            or fallback,
            forbidden_terms=forbidden_terms,
        )
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


def _resolve_host_sync_smart_copy_url() -> str:
    explicit = str(os.getenv("ROUGHCUT_HOST_SYNC_SMART_COPY_URL", "") or "").strip()
    if explicit:
        return explicit
    return resolve_codex_proxy_sibling_url("/v1/host/sync-smart-copy")


def _is_materialized_host_smart_copy_dir(material_dir: Path) -> bool:
    normalized = str(material_dir).replace("\\", "/").lower()
    return "/host-intelligent-copy/" in normalized


def _sync_materialized_smart_copy_to_host(*, requested_folder_path: str, material_dir: Path) -> None:
    raw_requested = str(requested_folder_path or "").strip().strip('"')
    if not raw_requested or not _looks_like_host_folder_path(raw_requested):
        return
    if not material_dir.exists() or not material_dir.is_dir():
        return
    if not _is_materialized_host_smart_copy_dir(material_dir):
        return
    url = _resolve_host_sync_smart_copy_url()
    if not url:
        raise RuntimeError("未配置宿主机 smart-copy 回写地址。")

    headers = {"Content-Type": "application/json"}
    token = resolve_codex_proxy_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.post(
        url,
        json={
            "source_material_dir": str(material_dir),
            "target_folder_path": raw_requested,
        },
        headers=headers,
        timeout=float(os.getenv("ROUGHCUT_HOST_MATERIALIZE_TIMEOUT_SEC", "120") or "120"),
    )
    response.raise_for_status()


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
