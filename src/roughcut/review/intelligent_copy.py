from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Awaitable, Callable

from roughcut.config import get_settings, llm_task_route
from roughcut.media.output import _extract_frame, _overlay_title_layout, _probe_duration, _sample_cover_candidates
from roughcut.packaging.library import list_packaging_assets
from roughcut.providers.image_generation import CodexImageGenerationPending, generate_edited_cover_image
from roughcut.providers.multimodal import complete_with_images
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message, extract_json_text
from roughcut.review.intelligent_copy_cover_quality import assess_cover_publish_readiness
from roughcut.review.content_profile import _seed_profile_from_text, _subject_domain_from_subject_type, infer_content_profile
from roughcut.review.platform_copy import PLATFORM_ORDER, generate_platform_packaging, save_platform_packaging_markdown
from roughcut.review.intelligent_copy_scoring import score_description, score_title_candidate
from roughcut.review.intelligent_copy_templates import build_platform_description, build_title_candidates
from roughcut.review.intelligent_copy_topics import IntelligentCopyTopicSpec, match_intelligent_copy_topic

VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".avi", ".m4v", ".webm"}
SUBTITLE_SUFFIXES = {".srt", ".vtt", ".ass", ".ssa"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
MATERIAL_DIR_NAME = "smart-copy"
TITLE_OPTION_LIMIT = 3
IntelligentCopyProgressCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO = "edc_cinematic_hero"
COVER_IMAGE_STYLE_SCHEMES: dict[str, dict[str, str]] = {
    OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO: {
        "label": "EDC 电影英雄封面",
        "prompt": (
            "风格方案：EDC 电影英雄封面。借鉴高冲击 EDC 开箱封面，不做平铺商品图。"
            "整体要有电影级暖色冒险背景、深浅层次、金属高光、暗部对比、轻微霓虹/电光描边、"
            "速度线或能量线点缀；产品是英雄物件，质感锐利但真实；中文标题采用粗壮 3D 金属字/"
            "电竞海报字效果，主次分明，有描边、阴影和发光边缘；画面要帅、强点击、专业，"
            "不要廉价电商模板。"
        ),
    },
}

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


def inspect_intelligent_copy_folder(folder_path: str) -> dict[str, Any]:
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
    return {
        "folder_path": str(folder),
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


async def generate_intelligent_copy(
    folder_path: str,
    *,
    copy_style: str | None = None,
    platforms: list[str] | None = None,
    use_existing_cover: bool = False,
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
    if not video_path.exists():
        raise ValueError("目录内未找到可用成片视频。")
    if not subtitle_path.exists():
        raise ValueError("目录内未找到可用字幕文件。")

    subtitle_items = _load_subtitle_items(subtitle_path)
    if not subtitle_items:
        raise ValueError("字幕文件已找到，但无法解析出可用字幕内容。")
    selected_platform_keys = _resolve_intelligent_copy_platform_keys(platforms)
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
    packaging = await generate_platform_packaging(
        source_name=video_path.name,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
        copy_style=resolved_copy_style,
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
    packaging = _filter_intelligent_copy_packaging(packaging, selected_platform_keys)
    cover_brief = await _build_intelligent_cover_brief(
        video_path=video_path,
        subtitle_items=subtitle_items,
        content_profile=content_profile,
        copy_brief=copy_brief,
        packaging=packaging,
    )

    material_dir = video_path.parent / MATERIAL_DIR_NAME
    material_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = material_dir / "platform-packaging.md"
    json_path = material_dir / "smart-copy.json"
    save_platform_packaging_markdown(markdown_path, packaging)
    cover_source = await _prepare_intelligent_copy_cover_source(
        video_path=video_path,
        material_dir=material_dir,
        content_profile=content_profile,
        packaging=packaging,
    )
    base_result = {
        "folder_path": str(video_path.parent),
        "material_dir": str(material_dir),
        "markdown_path": str(markdown_path),
        "json_path": str(json_path),
        "cover_source_path": str(cover_source) if cover_source else None,
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
    }
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 56,
            "stage": "packaging",
            "message": "平台文案已生成，正在渲染各平台封面和物料文件。",
            "inspection": inspection,
            "folder_path": str(video_path.parent),
            "material_dir": str(material_dir),
            "partial_result": {**base_result, "platforms": []},
        },
    )

    platform_materials: list[dict[str, Any]] = []
    blocking_reasons: list[str] = []
    cover_group_cache: dict[str, dict[str, Any]] = {}
    publish_platforms = [item for item in PLATFORM_ORDER if item[0] in selected_platform_keys and PLATFORM_PUBLISH_RULES.get(item[0])]
    for index, (platform_key, _label, _body_label, _tag_label) in enumerate(publish_platforms, start=1):
        rules = PLATFORM_PUBLISH_RULES.get(platform_key)
        if not rules:
            continue
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
                title=str(cover_brief.get("cover_title") or "")
                or _resolve_cover_group_title(packaging=packaging, content_profile=content_profile),
                cover_brief=cover_brief,
                platform_key=platform_key,
                platform_rules=rules,
                cover_group=cover_group,
            )
        platform_blocks = _validate_platform_material_ready(material)
        if cover_generation and not bool(cover_generation.get("publish_ready", True)):
            platform_blocks.extend(str(item) for item in (cover_generation.get("blocking_reasons") or []) if str(item).strip())
        if cover_output_path.exists() and not platform_blocks:
            material["cover_path"] = str(cover_output_path)
        if cover_generation:
            material["cover_generation"] = cover_generation
        material["publish_ready"] = not platform_blocks
        material["blocking_reasons"] = platform_blocks
        blocking_reasons.extend(f"{rules['label']}：{reason}" for reason in platform_blocks)
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
                "folder_path": str(video_path.parent),
                "material_dir": str(material_dir),
                "partial_result": {**base_result, "platforms": list(platform_materials)},
            },
        )

    result = {
        **base_result,
        "copy_brief": copy_brief,
        "platforms": platform_materials,
        "publish_ready": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
    }
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    await _emit_intelligent_copy_progress(
        progress_callback,
        {
            "progress": 100,
            "stage": "completed",
            "message": "物料生成完成。",
            "inspection": inspection,
            "folder_path": str(video_path.parent),
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
        "wechat-channels": "wechat_channels",
        "wechat": "wechat_channels",
        "b站": "bilibili",
        "bilibili": "bilibili",
        "小红书": "xiaohongshu",
        "抖音": "douyin",
        "快手": "kuaishou",
        "视频号": "wechat_channels",
        "头条号": "toutiao",
        "youtube": "youtube",
        "x": "x",
    }
    selected: list[str] = []
    for platform in platforms:
        raw = str(platform or "").strip()
        normalized = aliases.get(raw.casefold(), raw)
        if normalized in available and normalized not in selected:
            selected.append(normalized)
    if not selected:
        raise ValueError("请选择至少一个可生成物料的平台。")
    return selected


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
    return {
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
    }


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
) -> dict[str, Any]:
    fallback = _build_fallback_cover_brief(
        packaging=packaging,
        content_profile=content_profile,
        copy_brief=copy_brief,
    )
    context = {
        "source_name": video_path.name,
        "content_profile": _content_profile_summary(content_profile),
        "copy_brief": copy_brief,
        "highlights": dict(packaging.get("highlights") or {}),
        "platform_titles": _collect_platform_title_samples(packaging),
        "transcript_excerpt": build_transcript_excerpt_for_cover(subtitle_items),
    }
    prompt = (
        "你是短视频封面策划。请根据视频内容自己总结、提炼封面需求，不要套固定模板。"
        "你要判断视频类型，例如开箱、评测、对比、教程、种草、展示、实测等，"
        "再为图片模型准备简洁明确的封面 brief。\n"
        "封面标题要求：必须短、强识别、适合图片模型直接渲染；不要使用完整文案句子；不要超过 14 个汉字左右。"
        "如果能识别明确品牌、型号或商品名，cover_title 必须保留核心品牌/商品身份，不能只写材质、品类或卖点。"
        "不要走固定格式。你可以参考品牌/型号、商品类型、开箱/评测/对比/教程/超好玩/强烈推荐/夯爆了等信息，"
        "但必须根据真实内容自行取舍、总结和改写，不能机械拼接。"
        "EDC/工具内容要合规，不要危险导向，不要编参数。\n"
        "只输出 JSON："
        '{"cover_title":"","video_type":"","product_identity":"","selling_angle":"","visual_brief":"","avoid":""}'
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
) -> dict[str, Any]:
    title = _resolve_cover_group_title(packaging=packaging, content_profile=content_profile)
    highlights = packaging.get("highlights") if isinstance(packaging.get("highlights"), dict) else {}
    return {
        "cover_title": title,
        "video_type": str(highlights.get("video_type") or copy_brief.get("intent") or "").strip(),
        "product_identity": str(highlights.get("product") or copy_brief.get("topic_subject") or "").strip(),
        "selling_angle": str(highlights.get("strongest_selling_point") or highlights.get("title_hook") or "").strip(),
        "visual_brief": "突出真实主体、产品质感和开箱/展示高光，封面标题保持大而清晰。",
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
        "avoid": str(payload.get("avoid") or fallback.get("avoid") or "").strip()[:120],
        "strategy_source": source,
    }
    return normalized


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
        return {
            "key": "landscape_16_9",
            "label": "横版通用封面",
            "representative_platform": "bilibili",
            "cover_size": (1600, 900),
            "members": ["bilibili", "toutiao", "youtube", "x"],
        }
    if abs(ratio - (3 / 4)) < 0.06:
        return {
            "key": "portrait_3_4",
            "label": "3:4 竖版通用封面",
            "representative_platform": "xiaohongshu",
            "cover_size": (1080, 1440),
            "members": ["xiaohongshu"],
        }
    return {
        "key": "portrait_9_16",
        "label": "9:16 竖版通用封面",
        "representative_platform": "douyin",
        "cover_size": (1080, 1920),
        "members": ["douyin", "kuaishou", "wechat_channels"],
    }


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
            _fit_image_to_canvas(
                source_path=existing_cover_path,
                output_path=group_output_path,
                width=int(target_width),
                height=int(target_height),
                fit_mode="cover",
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
    if bool(group_metadata.get("publish_ready")) and group_output_path.exists():
        _fit_image_to_canvas(
            source_path=group_output_path,
            output_path=output_path,
            width=target_width,
            height=target_height,
            fit_mode="cover",
        )
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
    if (brand and not _is_generic_intelligent_copy_subject_identity(brand)) or (
        model and not _is_generic_intelligent_copy_subject_identity(model)
    ):
        return profile
    stem = video_path.stem.strip()
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
                    candidate_count=max(6, int(settings.cover_candidate_count or 10)),
                    tmpdir=tmp,
                )
                if duration > 0
                else []
            )
            if not candidates:
                raise RuntimeError("没有可用于封面判断的候选帧")
            selected = await _select_intelligent_copy_highlight_candidate(
                candidates,
                content_profile=content_profile,
                packaging=packaging,
                contact_sheet_output_path=material_dir / "00-highlight-candidates-sheet.jpg",
            )
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
        _write_cover_source_manifest(manifest_path, {"source": "failed", "error": str(exc)})
        return None


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
    contact_sheet_path = _build_numbered_highlight_contact_sheet(
        preview_paths,
        output_path=contact_sheet_output_path,
    )
    profile_text = json.dumps(
        {
            "content_profile": _content_profile_summary(content_profile),
            "highlights": dict(packaging.get("highlights") or {}),
        },
        ensure_ascii=False,
    )
    last_error = ""
    for attempt in range(1, 4):
        try:
            prompt = (
                "你在为多平台视频发布选择封面底图。请从候选帧中选出最适合再做 AI 封面编辑的一张。"
                "优先级：1) 视频主题一眼明确，主体/产品/关键动作足够大；"
                "2) 是成片中的高光时刻，有开箱、展示、对比、细节或结果感；"
                "3) 画面清晰稳定，少字幕、少 UI 杂讯、少遮挡；"
                "4) 后续可裁成横版 16:9、竖版 9:16、3:4。"
                "不要选只有手部、主体过小、过暗、失焦、字幕占比很大的帧。"
                "候选图已经合成到一张接触表里，每个小图左上角有 1-based 序号。"
                f"\n视频主题参考：{profile_text}"
                f"\n这是第 {attempt} 次判断；如果上一轮格式失败，请修复为合法 JSON。"
                "\n输出 JSON："
                "{\"best_number\":1,\"score\":0.91,\"reason\":\"主体最大且主题最明确\"}"
            )
            content = await asyncio.wait_for(
                complete_with_images(prompt, [contact_sheet_path], max_tokens=180, json_mode=True),
                timeout=8,
            )
            data = json.loads(extract_json_text(content))
            if "best_number" in data or "number" in data:
                index = int(data.get("best_number", data.get("number", 1)) or 1) - 1
            else:
                index = int(data.get("best_index", data.get("index", 0)) or 0)
            if 0 <= index < len(candidates):
                return {
                    "index": index,
                    "score": _normalize_score(data.get("score"), fallback=0.0),
                    "reason": str(data.get("reason") or "").strip(),
                    "source": "llm_contact_sheet_rank",
                    "contact_sheet_path": str(contact_sheet_path),
                    "attempts": attempt,
                }
            last_error = f"模型返回序号越界：{index + 1}"
        except Exception as exc:
            last_error = str(exc)
    raise RuntimeError(f"高光帧识别经过重试后仍失败：{last_error}")


def _build_numbered_highlight_contact_sheet(preview_paths: list[Path], *, output_path: Path | None = None) -> Path:
    valid_paths = [path for path in preview_paths if path and path.exists()]
    if not valid_paths:
        raise ValueError("No preview frames available for contact sheet")
    sheet_path = output_path or (valid_paths[0].parent / "highlight_candidates_sheet.jpg")
    sheet_path.parent.mkdir(parents=True, exist_ok=True)
    columns = 3 if len(valid_paths) > 1 else 1
    cell_width = 360
    cell_height = 360
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
    blocking_reasons: list[str] = []
    request_path = output_path.with_suffix(".codex-imagegen.json")
    completed_request_payload = _read_cover_request_payload(request_path)
    if (
        str(completed_request_payload.get("status") or "").strip().lower() == "completed"
        and output_path.exists()
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
            fit_mode="cover",
        )
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
            for attempt in range(1, 4):
                try:
                    image_generation = await generate_edited_cover_image(
                        source_image_path=base_image,
                        output_path=generated_image,
                        request_path=request_path,
                        final_output_path=output_path,
                        prompt=_build_platform_cover_image_prompt(
                            title=title,
                            platform_key=platform_key,
                            rules=rules,
                            width=target_width,
                            height=target_height,
                            cover_brief=cover_brief,
                        ),
                        width=target_width,
                        height=target_height,
                    )
                    image_generation["attempts"] = attempt
                    source_kind = "image_generation"
                    break
                except CodexImageGenerationPending as exc:
                    image_generation = dict(exc.metadata)
                    image_generation["attempts"] = attempt
                    blocking_reasons.append("封面等待 Codex 内置 imagegen 执行完成")
                    break
                except Exception as exc:
                    last_error = str(exc)
            if source_kind != "image_generation":
                if last_error:
                    blocking_reasons.append(f"封面图像生成重试后仍失败：{last_error}")
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
                fit_mode="cover",
            )
        elif output_path.exists():
            _fit_existing_image_to_canvas(
                output_path=output_path,
                width=target_width,
                height=target_height,
                fit_mode="cover",
            )
        if isinstance(image_generation, dict) and str(image_generation.get("backend") or "") == "codex_builtin":
            request_payload = _read_cover_request_payload(request_path)
            cover_assessment = assess_cover_publish_readiness(
                image_generation,
                request_payload,
                output_path,
            )
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
    title_lines = _build_cover_title_lines(title)
    if title_lines and source_kind != "image_generation":
        await _overlay_title_layout(
            output_path,
            title_lines,
            str(rules.get("cover_style") or "tech_showcase"),
            str(rules.get("title_style") or "preset_default"),
        )
    return {
        "source": source_kind,
        "platform": str(platform_key or "").strip(),
        "target_size": {"width": target_width, "height": target_height},
        "publish_ready": output_path.exists() and not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "image_generation": image_generation,
    }


def _read_cover_request_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _should_generate_intelligent_copy_cover_image(source_kind: str) -> bool:
    settings = get_settings()
    if not bool(getattr(settings, "intelligent_copy_cover_image_generation_enabled", True)):
        return False
    return str(source_kind or "").strip() in {"video_highlight", "existing_cover_reference"}


def _build_platform_cover_image_prompt(
    *,
    title: str,
    platform_key: str,
    rules: dict[str, Any],
    width: int,
    height: int,
    cover_brief: dict[str, Any] | None = None,
) -> str:
    title_text = re.sub(r"\s+", " ", str(title or "").strip())
    platform_label = str(rules.get("label") or platform_key or "").strip()
    ratio_label = _cover_ratio_label(width=width, height=height)
    instruction = _platform_cover_visual_instruction(platform_key)
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
    brief_text = ("\n" + "\n".join(brief_lines)) if brief_lines else ""
    return (
        "基于参考图生成一张可直接发布的视频封面。\n"
        f"平台：{platform_label}\n"
        f"比例/尺寸：{ratio_label}，最终 {width}x{height}\n"
        f"封面标题：{title_text or '内容主题明确、突出主体'}\n"
        f"视觉方向：{instruction}\n"
        f"{brief_text}\n"
        f"{style_prompt}\n"
        "要求：保留真实主体和产品形态；智能优化构图、主体占比、光影、清晰度、对比、质感和背景整洁度；"
        "封面标题已经由上游 LLM 根据视频类型总结提炼，请严格使用给定标题，不要改写、扩写或机械套模板；"
        "标题由图片模型直接渲染，必须准确完整、大而清晰、层级分明，不能散乱、太小、裁切或越界；"
        "标题和关键主体必须放在画面中央安全区，适配平台从 16:9、4:3、3:4 到 9:16 的居中裁切，"
        "不要把文字放在左右边缘，两侧只放可裁切的背景氛围。\n"
        "禁止：额外文字、字幕、水印、伪 logo、乱码、错别字、伪造参数、改变主体身份。"
    )


def _resolve_cover_image_style_key(*, rules: dict[str, Any], cover_brief: dict[str, Any]) -> str:
    explicit = str(rules.get("cover_style") or "").strip()
    if explicit in COVER_IMAGE_STYLE_SCHEMES:
        return explicit
    identity_text = " ".join(
        str(cover_brief.get(key) or "").strip()
        for key in ("product_identity", "selling_angle", "visual_brief", "video_type")
        if str(cover_brief.get(key) or "").strip()
    )
    if re.search(r"\bEDC\b|MOT|风灵|FAS|锆合金|音叉|推牌|刀帕|伞绳|绳扣|战术|tactical", identity_text, re.I):
        return OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO
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
    if str(fit_mode or "").strip().lower() == "cover":
        video_filter = (
            "scale="
            f"w={width}:h={height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
    else:
        video_filter = (
            "scale="
            f"w={width}:h={height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x111111"
        )
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vf",
            video_filter,
            "-frames:v",
            "1",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=settings.ffmpeg_timeout_sec,
    )
    if result.returncode != 0:
        raise RuntimeError(f"封面尺寸适配失败：{result.stderr[-400:]}")


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

    if explicit_candidates:
        return _filter_title_candidates(
            candidates=explicit_candidates,
            limit=int(rules.get("title_limit") or 40),
            topic_subject=topic_subject,
            anchor_terms=anchor_terms,
            forbidden_terms=forbidden_terms,
        )

    candidates = build_title_candidates(
        intent=intent,
        topic_subject=topic_subject,
        focus_points=focus_points,
    )
    return _filter_title_candidates(
        candidates=candidates,
        limit=int(rules.get("title_limit") or 40),
        topic_subject=topic_subject,
        anchor_terms=anchor_terms,
        forbidden_terms=forbidden_terms,
    )


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
        fallback = " ".join(part for part in (summary, question) if part).strip()
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
        raise ValueError("目录不存在，或不是可访问的文件夹。")
    return folder.resolve()


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
