from __future__ import annotations

import json
import mimetypes
import math
import random
import re
from collections import Counter
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from io import BytesIO

import numpy as np
from sqlalchemy import select

from roughcut.config import DEFAULT_TEST_OUTPUT_ROOT, get_settings
from roughcut.edit.presets import normalize_workflow_template_name
from roughcut.review.domain_glossaries import detect_glossary_domains, normalize_subject_domain, select_primary_subject_domain
from roughcut.state_store import PACKAGING_CONFIG_KEY, run_db_operation


PACKAGING_ROOT = DEFAULT_TEST_OUTPUT_ROOT / "packaging"
MANIFEST_PATH = PACKAGING_ROOT / "manifest.json"

ASSET_EXTENSIONS: dict[str, set[str]] = {
    "intro": {".mp4", ".mov", ".mkv", ".webm"},
    "outro": {".mp4", ".mov", ".mkv", ".webm"},
    "insert": {".mp4", ".mov", ".mkv", ".webm"},
    "music": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"},
    "watermark": {".png", ".jpg", ".jpeg", ".webp"},
}

DEFAULT_CONFIG: dict[str, Any] = {
    "intro_asset_id": None,
    "outro_asset_id": None,
    "insert_asset_id": None,
    "insert_asset_ids": [],
    "insert_selection_mode": "manual",
    "insert_position_mode": "llm",
    "watermark_asset_id": None,
    "music_asset_ids": [],
    "music_selection_mode": "random",
    "music_loop_mode": "loop_single",
    "subtitle_style": "bold_yellow_outline",
    "cover_style": "preset_default",
    "title_style": "preset_default",
    "copy_style": "attention_grabbing",
    "subtitle_motion_style": "motion_static",
    "smart_effect_style": "smart_effect_rhythm",
    "music_volume": 0.12,
    "watermark_position": "top_left",
    "watermark_opacity": 0.82,
    "watermark_scale": 0.16,
    "avatar_overlay_position": "top_right",
    "avatar_overlay_scale": 0.18,
    "avatar_overlay_corner_radius": 26,
    "avatar_overlay_border_width": 4,
    "avatar_overlay_border_color": "#F4E4B8",
    "export_resolution_mode": "source",
    "export_resolution_preset": "1080p",
    "enabled": True,
}

SUBTITLE_STYLE_OPTIONS = {
    "bold_yellow_outline",
    "white_minimal",
    "neon_green_glow",
    "cinema_blue",
    "bubble_pop",
    "keyword_highlight",
    "amber_news",
    "punch_red",
    "lime_box",
    "soft_shadow",
    "clean_box",
    "midnight_magenta",
    "mint_outline",
    "cobalt_pop",
    "rose_gold",
    "slate_caption",
    "ivory_serif",
    "cyber_orange",
    "streamer_duo",
    "doc_gray",
    "sale_banner",
    "coupon_green",
    "luxury_caps",
    "film_subtle",
    "archive_type",
    "teaser_glow",
}

SUBTITLE_MOTION_OPTIONS = {
    "motion_static",
    "motion_typewriter",
    "motion_pop",
    "motion_wave",
    "motion_slide",
    "motion_glitch",
    "motion_ripple",
    "motion_strobe",
    "motion_echo",
}

SMART_EFFECT_STYLE_OPTIONS = {
    "smart_effect_rhythm",
    "smart_effect_punch",
    "smart_effect_glitch",
    "smart_effect_cinematic",
    "smart_effect_minimal",
}

EXPORT_RESOLUTION_MODE_OPTIONS = {"source", "specified"}
EXPORT_RESOLUTION_PRESET_OPTIONS = {"1080p", "1440p", "2160p"}

COVER_STYLE_OPTIONS = {
    "preset_default",
    "tech_showcase",
    "collection_drop",
    "upgrade_spotlight",
    "tactical_neon",
    "luxury_blackgold",
    "retro_poster",
    "creator_vlog",
    "bold_review",
    "tutorial_card",
    "food_magazine",
    "street_hype",
    "minimal_white",
    "cyber_grid",
    "premium_silver",
    "comic_pop",
    "studio_red",
    "documentary_frame",
    "pastel_lifestyle",
    "industrial_orange",
    "ecommerce_sale",
    "price_strike",
    "trailer_dark",
    "festival_redgold",
    "clean_lab",
    "cinema_teaser",
}

TITLE_STYLE_OPTIONS = {
    "preset_default",
    "cyber_logo_stack",
    "chrome_impact",
    "festival_badge",
    "double_banner",
    "comic_boom",
    "luxury_gold",
    "tutorial_blueprint",
    "magazine_clean",
    "documentary_stamp",
    "neon_night",
}

COPY_STYLE_OPTIONS = {
    "attention_grabbing",
    "balanced",
    "premium_editorial",
    "trusted_expert",
    "playful_meme",
    "emotional_story",
}

MUSIC_SELECTION_MODES = {"random", "manual"}
MUSIC_LOOP_MODES = {"loop_single", "loop_all"}
INSERT_SELECTION_MODES = {"manual", "random"}
AVATAR_OVERLAY_POSITION_OPTIONS = {"top_left", "top_right", "bottom_left", "bottom_right"}

PRESET_HINT_KEYWORDS: dict[str, set[str]] = {
    "unboxing_standard": {"UNBOX", "BOX", "PACKAGE", "PRODUCT", "DETAIL", "MACRO", "SHOWCASE", "开箱", "包装", "细节"},
    "edc_tactical": {"EDC", "TACTICAL", "KNIFE", "TOOL", "GEAR", "MACRO", "战术", "工具", "钳", "刀"},
    "tutorial_standard": {"SCREEN", "UI", "FLOW", "STEP", "GUIDE", "TUTORIAL", "教程", "录屏", "步骤", "操作"},
    "vlog_daily": {"VLOG", "DAILY", "CITY", "TRAVEL", "LIFESTYLE", "日常", "出行", "生活"},
    "commentary_focus": {"COMMENTARY", "TALK", "ANALYSIS", "观点", "口播", "分析"},
    "gameplay_highlight": {"GAME", "GAMEPLAY", "HIGHLIGHT", "ACE", "CLUTCH", "REPLAY", "游戏", "高光", "对局"},
    "food_explore": {"FOOD", "DISH", "STORE", "MENU", "CAFE", "RESTAURANT", "探店", "试吃", "美食", "菜"},
}

MUSIC_MOOD_KEYWORDS: dict[str, set[str]] = {
    "tutorial_standard": {"CALM", "CLEAN", "LIGHT", "AMBIENT", "FOCUS", "LOFI", "PIANO", "教程", "轻松"},
    "vlog_daily": {"CHILL", "LOFI", "SUNNY", "SOFT", "WARM", "TRAVEL", "VLOG", "日常", "轻快"},
    "commentary_focus": {"CLEAN", "MINIMAL", "DOCUMENTARY", "AMBIENT", "NEWS", "分析", "简洁"},
    "gameplay_highlight": {"HYPE", "EPIC", "BATTLE", "ENERGY", "BASS", "TRAP", "高能", "热血"},
    "food_explore": {"COZY", "JAZZ", "FUNK", "WARM", "CAFE", "LIFESTYLE", "美食", "轻松"},
    "edc_tactical": {"TACTICAL", "DARK", "INDUSTRIAL", "METAL", "BASS", "战术", "硬核"},
    "unboxing_standard": {"TECH", "UPBEAT", "CLEAN", "SHOWCASE", "科技", "展示"},
}

DOMAIN_HINT_KEYWORDS: dict[str, set[str]] = {
    "edc": {"EDC", "TACTICAL", "KNIFE", "TOOL", "GEAR", "MACRO", "战术", "工具", "钳", "刀"},
    "outdoor": {"OUTDOOR", "CAMP", "HIKE", "GEAR", "户外", "露营", "徒步"},
    "tech": {"TECH", "PHONE", "CHIP", "SCREEN", "CAMERA", "PHONE", "LAPTOP", "EARBUD", "手机", "芯片", "屏幕", "相机", "耳机"},
    "ai": {"AI", "WORKFLOW", "NODE", "MODEL", "AGENT", "COMFYUI", "RUNNINGHUB", "工作流", "节点", "模型", "智能体"},
    "functional": {"FUNCTIONAL", "BAG", "SLING", "UTILITY", "机能", "通勤", "穿搭", "包"},
    "tools": {"TOOLS", "TOOL", "PLIER", "BIT", "SCREWDRIVER", "工具", "钳", "批头", "螺丝刀"},
    "food": {"FOOD", "DISH", "CAFE", "RESTAURANT", "美食", "探店", "试吃"},
    "travel": {"TRAVEL", "CITY", "TRIP", "VLOG", "出行", "旅行"},
    "finance": {"FINANCE", "MARKET", "ECON", "财经", "金融"},
    "news": {"NEWS", "REPORT", "BRIEF", "新闻", "快讯"},
    "sports": {"SPORT", "GAME", "MATCH", "赛事", "比赛"},
}

DOMAIN_MOOD_KEYWORDS: dict[str, set[str]] = {
    "edc": {"TACTICAL", "DARK", "INDUSTRIAL", "METAL", "BASS", "战术", "硬核"},
    "outdoor": {"OPEN", "EPIC", "NATURE", "TRAVEL", "WIDE", "户外", "自然"},
    "tech": {"TECH", "CLEAN", "SHOWCASE", "UPBEAT", "科技", "展示"},
    "ai": {"AI", "WORKFLOW", "NODE", "AMBIENT", "FOCUS", "DIGITAL", "工作流", "节点"},
    "functional": {"UTILITY", "STREET", "URBAN", "工业", "机能"},
    "tools": {"INDUSTRIAL", "METAL", "TOOL", "硬核", "工业"},
    "food": {"COZY", "JAZZ", "FUNK", "WARM", "美食", "轻松"},
    "travel": {"CHILL", "SUNNY", "WARM", "TRAVEL", "日常", "轻快"},
    "finance": {"CLEAN", "MINIMAL", "NEWS", "简洁", "分析"},
    "news": {"DOCUMENTARY", "CLEAN", "NEWS", "稳重", "简洁"},
    "sports": {"HYPE", "EPIC", "BATTLE", "ENERGY", "高能", "热血"},
}

GENERIC_MUSIC_TOKENS = {"BGM", "MUSIC", "LOOP", "TRACK", "BEAT", "INSTRUMENTAL", "AMBIENT"}
GENERIC_INSERT_TOKENS = {"BROLL", "DETAIL", "MACRO", "CLOSEUP", "BOX", "PACKAGE", "PRODUCT", "SHOT", "INSERT", "CUTAWAY", "细节", "特写", "包装"}


def list_packaging_assets() -> dict[str, Any]:
    state = _load_state()
    assets_by_id = {item["id"]: item for item in state["assets"]}
    state["config"] = _normalize_config(dict(state["config"]), assets_by_id)
    assets = sorted(state["assets"], key=lambda item: item.get("created_at", ""), reverse=True)
    by_type = {
        asset_type: [item for item in assets if item.get("asset_type") == asset_type]
        for asset_type in ASSET_EXTENSIONS
    }
    return {
        "assets": by_type,
        "config": state["config"],
    }


def save_packaging_asset(*, asset_type: str, filename: str, payload: bytes) -> dict[str, Any]:
    asset_type = _normalize_asset_type(asset_type)
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ASSET_EXTENSIONS[asset_type]:
        raise ValueError(f"Unsupported {asset_type} file type: {suffix or 'unknown'}")

    watermark_preprocessed = False
    if asset_type == "watermark":
        payload, suffix, content_type, watermark_preprocessed = _maybe_remove_watermark_solid_background(
            payload=payload,
            source_suffix=suffix,
        )
    else:
        content_type = mimetypes.guess_type(f"dummy{suffix}")[0] or "application/octet-stream"

    PACKAGING_ROOT.mkdir(parents=True, exist_ok=True)
    asset_id = uuid.uuid4().hex
    stored_name = f"{asset_id}{suffix}"
    asset_dir = PACKAGING_ROOT / asset_type
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / stored_name
    target.write_bytes(payload)

    item = {
        "id": asset_id,
        "asset_type": asset_type,
        "original_name": Path(filename or stored_name).name,
        "stored_name": stored_name,
        "path": str(target.resolve()),
        "size_bytes": len(payload),
        "content_type": content_type,
        "watermark_preprocessed": watermark_preprocessed if asset_type == "watermark" else None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    state = _load_state()
    state["assets"] = [existing for existing in state["assets"] if existing.get("id") != asset_id]
    state["assets"].append(item)

    if asset_type in {"intro", "outro", "watermark"}:
        config_key = f"{asset_type}_asset_id"
        if not state["config"].get(config_key):
            state["config"][config_key] = asset_id
    if asset_type == "insert":
        if not state["config"].get("insert_asset_id"):
            state["config"]["insert_asset_id"] = asset_id
        insert_ids = list(state["config"].get("insert_asset_ids") or [])
        if asset_id not in insert_ids:
            insert_ids.append(asset_id)
        state["config"]["insert_asset_ids"] = insert_ids
    if asset_type == "music":
        music_ids = list(state["config"].get("music_asset_ids") or [])
        if asset_id not in music_ids:
            music_ids.append(asset_id)
        state["config"]["music_asset_ids"] = music_ids

    _save_state(state)
    return item


def _maybe_remove_watermark_solid_background(payload: bytes, source_suffix: str) -> tuple[bytes, str, str, bool]:
    source_content_type = mimetypes.guess_type(f"dummy{source_suffix}")[0] or "application/octet-stream"

    try:
        from PIL import Image
    except Exception:  # pragma: no cover
        return payload, source_suffix, source_content_type, False

    try:
        image = Image.open(BytesIO(payload))
        if image.mode in {"RGBA", "LA"}:
            alpha_channel = np.array(image.getchannel("A"), dtype=np.uint8) if image.mode == "RGBA" else np.array(image.getchannel("A"), dtype=np.uint8)
            if alpha_channel.mean() < 250:
                return payload, source_suffix, source_content_type, False
        if image.mode not in {"RGB", "RGBA", "LA", "P", "CMYK", "L"}:
            image = image.convert("RGB")
    except Exception:
        return payload, source_suffix, source_content_type, False

    if image.width == 0 or image.height == 0:
        return payload, source_suffix, source_content_type, False

    detected = _detect_pure_background_color(image)
    if detected is None:
        return payload, source_suffix, source_content_type, False

    rgb = np.array(image.convert("RGB"), dtype=np.int16)
    bg = np.array(detected, dtype=np.int16)
    diff = np.abs(rgb - bg).max(axis=2)
    alpha = np.where(diff <= 22, 0, 255).astype(np.uint8)
    if alpha.mean() > 252:
        return payload, source_suffix, source_content_type, False

    out = np.concatenate([rgb.astype(np.uint8), alpha[:, :, None]], axis=2)
    out_image = Image.fromarray(out, mode="RGBA")
    out_bytes = BytesIO()
    out_image.save(out_bytes, format="PNG", optimize=True)
    output = out_bytes.getvalue()
    return output, ".png", "image/png", True


def _detect_pure_background_color(image: Any) -> tuple[int, int, int] | None:
    from PIL import Image

    preview = image.convert("RGB")
    target_width = max(1, min(128, int(preview.width)))
    scale = max(1, math.ceil(preview.width / 128))
    target_height = max(1, min(128, int(preview.height / scale)))
    small = preview.resize((target_width, target_height), Image.Resampling.BILINEAR)
    arr = np.array(small, dtype=np.uint8)
    if arr.shape[0] == 0 or arr.shape[1] == 0:
        return None
    edges = np.concatenate(
        [
            arr[0, :, :],
            arr[-1, :, :],
            arr[:, 0, :],
            arr[:, -1, :],
        ],
        axis=0,
    )
    if edges.shape[0] == 0:
        return None

    quantized = (edges // 16) * 16
    quantized_tuples = [tuple(pixel) for pixel in quantized.reshape(-1, 3)]
    bg_candidate, count = Counter(quantized_tuples).most_common(1)[0]
    ratio = count / max(1, len(quantized_tuples))
    if ratio < 0.78:
        return None

    mask = np.abs(arr.astype(np.int16) - np.array(bg_candidate, dtype=np.int16)).max(axis=2) <= 28
    bg_area_ratio = mask.mean()
    if bg_area_ratio < 0.42:
        return None
    if bg_area_ratio > 0.97:
        return None
    return bg_candidate


def delete_packaging_asset(asset_id: str) -> None:
    state = _load_state()
    asset = next((item for item in state["assets"] if item.get("id") == asset_id), None)
    if not asset:
        raise KeyError(asset_id)

    path = Path(asset["path"])
    path.unlink(missing_ok=True)

    state["assets"] = [item for item in state["assets"] if item.get("id") != asset_id]
    config = state["config"]
    for key in ("intro_asset_id", "outro_asset_id", "insert_asset_id", "watermark_asset_id"):
        if config.get(key) == asset_id:
            config[key] = None
    config["insert_asset_ids"] = [item for item in config.get("insert_asset_ids", []) if item != asset_id]
    config["music_asset_ids"] = [item for item in config.get("music_asset_ids", []) if item != asset_id]
    _save_state(state)


def update_packaging_config(patch: dict[str, Any]) -> dict[str, Any]:
    state = _load_state()
    config = state["config"]
    assets_by_id = {item["id"]: item for item in state["assets"]}

    for key, value in patch.items():
        if key not in DEFAULT_CONFIG:
            continue
        config[key] = value

    for asset_key, asset_type in (
        ("intro_asset_id", "intro"),
        ("outro_asset_id", "outro"),
        ("insert_asset_id", "insert"),
        ("watermark_asset_id", "watermark"),
    ):
        asset_id = config.get(asset_key)
        if asset_id and assets_by_id.get(asset_id, {}).get("asset_type") != asset_type:
            raise ValueError(f"{asset_key} does not reference a valid {asset_type} asset")

    state["config"] = _normalize_config(dict(config), assets_by_id)

    _save_state(state)
    return state["config"]


def resolve_packaging_plan_for_job(job_id: str, *, content_profile: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _load_state()
    config = dict(DEFAULT_CONFIG)
    config.update(state["config"])
    if not config.get("enabled"):
        return {
            "intro": None,
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": None,
            "subtitle_style": DEFAULT_CONFIG["subtitle_style"],
            "cover_style": DEFAULT_CONFIG["cover_style"],
            "title_style": DEFAULT_CONFIG["title_style"],
            "copy_style": DEFAULT_CONFIG["copy_style"],
            "subtitle_motion_style": DEFAULT_CONFIG["subtitle_motion_style"],
            "smart_effect_style": DEFAULT_CONFIG["smart_effect_style"],
            "export_resolution_mode": DEFAULT_CONFIG["export_resolution_mode"],
            "export_resolution_preset": DEFAULT_CONFIG["export_resolution_preset"],
        }

    assets_by_id = {
        item["id"]: item for item in state["assets"]
        if Path(item.get("path") or "").exists()
    }
    config = _normalize_config(config, assets_by_id)

    intro = _resolve_single_asset(assets_by_id, config.get("intro_asset_id"), expected_type="intro")
    outro = _resolve_single_asset(assets_by_id, config.get("outro_asset_id"), expected_type="outro")
    insert = _resolve_insert_asset(assets_by_id, config, job_id, content_profile=content_profile)
    watermark = _resolve_single_asset(assets_by_id, config.get("watermark_asset_id"), expected_type="watermark")
    music = _resolve_music_asset(assets_by_id, config, job_id, content_profile=content_profile)

    if watermark:
        watermark.update(
            {
                "position": config["watermark_position"],
                "opacity": config["watermark_opacity"],
                "scale": config["watermark_scale"],
            }
        )
    if music:
        music.update(
            {
                "selection_mode": config["music_selection_mode"],
                "loop_mode": config["music_loop_mode"],
                "volume": config["music_volume"],
                "candidate_paths": [assets_by_id[item]["path"] for item in music.get("candidate_asset_ids", []) if item in assets_by_id],
            }
        )

    return {
        "intro": intro,
        "outro": outro,
        "insert": insert,
        "watermark": watermark,
        "music": music,
        "subtitle_style": config["subtitle_style"],
        "subtitle_motion_style": config["subtitle_motion_style"],
        "smart_effect_style": config["smart_effect_style"],
        "cover_style": config["cover_style"],
        "title_style": config["title_style"],
        "copy_style": config["copy_style"],
        "avatar_overlay_position": config["avatar_overlay_position"],
        "avatar_overlay_scale": config["avatar_overlay_scale"],
        "avatar_overlay_corner_radius": config["avatar_overlay_corner_radius"],
        "avatar_overlay_border_width": config["avatar_overlay_border_width"],
        "avatar_overlay_border_color": config["avatar_overlay_border_color"],
        "export_resolution_mode": config["export_resolution_mode"],
        "export_resolution_preset": config["export_resolution_preset"],
    }


def get_packaging_asset(asset_id: str) -> dict[str, Any]:
    state = _load_state()
    asset = next((item for item in state["assets"] if item.get("id") == asset_id), None)
    if not asset:
        raise KeyError(asset_id)
    return asset


def _resolve_single_asset(
    assets_by_id: dict[str, dict[str, Any]],
    asset_id: str | None,
    *,
    expected_type: str,
) -> dict[str, Any] | None:
    if not asset_id:
        return None
    asset = assets_by_id.get(asset_id)
    if not asset or asset.get("asset_type") != expected_type:
        return None
    return {
        "asset_id": asset["id"],
        "asset_type": expected_type,
        "path": asset["path"],
        "original_name": asset["original_name"],
    }


def _resolve_music_asset(
    assets_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    job_id: str,
    *,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    music_ids = [item for item in config.get("music_asset_ids") or [] if item in assets_by_id]
    if not music_ids:
        return None
    ordered_ids = list(music_ids)
    if config.get("music_selection_mode") == "manual":
        rankings = _rank_packaging_assets(
            [assets_by_id[item] for item in ordered_ids],
            asset_type="music",
            content_profile=content_profile,
        )
        selected_id = ordered_ids[0]
        if selected_id not in ordered_ids:
            selected_id = rankings[0]["asset_id"] if rankings else None
        selection_summary = None
    else:
        rankings = _rank_packaging_assets(
            [assets_by_id[item] for item in ordered_ids],
            asset_type="music",
            content_profile=content_profile,
            random_seed=f"music:{job_id}",
        )
        ordered_ids = [item["asset_id"] for item in rankings]
        selected_id = ordered_ids[0] if ordered_ids else None
        selection_summary = _build_packaging_selection_summary(rankings)
    if not selected_id:
        return None
    asset = assets_by_id[selected_id]
    return {
        "asset_id": asset["id"],
        "asset_type": "music",
        "path": asset["path"],
        "original_name": asset["original_name"],
        "candidate_asset_ids": ordered_ids,
        "selection_strategy": "manual_override" if config.get("music_selection_mode") == "manual" else "auto_ranked_pool",
        "selection_summary": selection_summary,
    }


def _resolve_insert_asset(
    assets_by_id: dict[str, dict[str, Any]],
    config: dict[str, Any],
    job_id: str,
    *,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    insert_ids = [item for item in config.get("insert_asset_ids") or [] if item in assets_by_id]
    if config.get("insert_selection_mode") == "manual":
        selected_id = config.get("insert_asset_id")
        if selected_id not in insert_ids and selected_id in assets_by_id:
            insert_ids = [selected_id]
        if not selected_id:
            selected_id = insert_ids[0] if insert_ids else None
        selection_summary = None
    else:
        rankings = _rank_packaging_assets(
            [assets_by_id[item] for item in insert_ids],
            asset_type="insert",
            content_profile=content_profile,
            random_seed=f"insert:{job_id}",
        )
        insert_ids = [item["asset_id"] for item in rankings]
        selected_id = insert_ids[0] if insert_ids else None
        selection_summary = _build_packaging_selection_summary(rankings)
    if not selected_id:
        return None
    asset = assets_by_id[selected_id]
    return {
        "asset_id": asset["id"],
        "asset_type": "insert",
        "path": asset["path"],
        "original_name": asset["original_name"],
        "candidate_asset_ids": insert_ids,
        "selection_mode": config.get("insert_selection_mode") or "manual",
        "position_mode": config.get("insert_position_mode") or "llm",
        "selection_strategy": "manual_override" if config.get("insert_selection_mode") == "manual" else "auto_ranked_pool",
        "selection_summary": selection_summary,
    }


def _normalize_asset_type(asset_type: str) -> str:
    value = str(asset_type or "").strip().lower()
    if value not in ASSET_EXTENSIONS:
        raise ValueError(f"Unsupported asset type: {asset_type}")
    return value


def _load_state() -> dict[str, Any]:
    default_state = {
        "assets": [],
        "config": dict(DEFAULT_CONFIG),
    }
    try:
        state, has_data = _load_state_from_db()
        if has_data:
            return state
    except Exception:
        state = default_state

    legacy_state = _load_legacy_state()
    if legacy_state["assets"] or legacy_state["config"] != dict(DEFAULT_CONFIG):
        try:
            _save_state_to_db(legacy_state)
        except Exception:
            pass
        return legacy_state
    return state


def _normalize_config(config: dict[str, Any], assets_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    normalized = dict(DEFAULT_CONFIG)
    normalized.update(config or {})

    insert_ids = [
        item for item in (normalized.get("insert_asset_ids") or [])
        if assets_by_id.get(item, {}).get("asset_type") == "insert"
    ]
    normalized["insert_asset_ids"] = insert_ids
    normalized["insert_selection_mode"] = str(normalized.get("insert_selection_mode") or "manual").strip() or "manual"
    if normalized["insert_selection_mode"] not in INSERT_SELECTION_MODES:
        normalized["insert_selection_mode"] = "manual"
    normalized["insert_position_mode"] = str(normalized.get("insert_position_mode") or "llm").strip() or "llm"

    music_ids = [
        item for item in (normalized.get("music_asset_ids") or [])
        if assets_by_id.get(item, {}).get("asset_type") == "music"
    ]
    normalized["music_asset_ids"] = music_ids
    normalized["music_selection_mode"] = str(normalized.get("music_selection_mode") or "random").strip() or "random"
    if normalized["music_selection_mode"] not in MUSIC_SELECTION_MODES:
        normalized["music_selection_mode"] = DEFAULT_CONFIG["music_selection_mode"]

    loop_mode = str(normalized.get("music_loop_mode") or "loop_single").strip() or "loop_single"
    if loop_mode == "none":
        loop_mode = "loop_all"
    if loop_mode not in MUSIC_LOOP_MODES:
        loop_mode = DEFAULT_CONFIG["music_loop_mode"]
    normalized["music_loop_mode"] = loop_mode

    subtitle_style = str(normalized.get("subtitle_style") or DEFAULT_CONFIG["subtitle_style"]).strip() or DEFAULT_CONFIG["subtitle_style"]
    if subtitle_style not in SUBTITLE_STYLE_OPTIONS:
        subtitle_style = DEFAULT_CONFIG["subtitle_style"]
    normalized["subtitle_style"] = subtitle_style

    cover_style = str(normalized.get("cover_style") or DEFAULT_CONFIG["cover_style"]).strip() or DEFAULT_CONFIG["cover_style"]
    if cover_style not in COVER_STYLE_OPTIONS:
        cover_style = DEFAULT_CONFIG["cover_style"]
    normalized["cover_style"] = cover_style

    title_style = str(normalized.get("title_style") or DEFAULT_CONFIG["title_style"]).strip() or DEFAULT_CONFIG["title_style"]
    if title_style not in TITLE_STYLE_OPTIONS:
        title_style = DEFAULT_CONFIG["title_style"]
    normalized["title_style"] = title_style

    copy_style = str(normalized.get("copy_style") or DEFAULT_CONFIG["copy_style"]).strip() or DEFAULT_CONFIG["copy_style"]
    if copy_style not in COPY_STYLE_OPTIONS:
        copy_style = DEFAULT_CONFIG["copy_style"]
    normalized["copy_style"] = copy_style

    subtitle_motion_style = str(
        normalized.get("subtitle_motion_style") or DEFAULT_CONFIG["subtitle_motion_style"]
    ).strip() or DEFAULT_CONFIG["subtitle_motion_style"]
    if subtitle_motion_style not in SUBTITLE_MOTION_OPTIONS:
        subtitle_motion_style = DEFAULT_CONFIG["subtitle_motion_style"]
    normalized["subtitle_motion_style"] = subtitle_motion_style

    smart_effect_style = str(
        normalized.get("smart_effect_style") or DEFAULT_CONFIG["smart_effect_style"]
    ).strip() or DEFAULT_CONFIG["smart_effect_style"]
    if smart_effect_style not in SMART_EFFECT_STYLE_OPTIONS:
        smart_effect_style = DEFAULT_CONFIG["smart_effect_style"]
    normalized["smart_effect_style"] = smart_effect_style

    avatar_overlay_position = str(
        normalized.get("avatar_overlay_position") or DEFAULT_CONFIG["avatar_overlay_position"]
    ).strip() or DEFAULT_CONFIG["avatar_overlay_position"]
    if avatar_overlay_position not in AVATAR_OVERLAY_POSITION_OPTIONS:
        avatar_overlay_position = DEFAULT_CONFIG["avatar_overlay_position"]
    normalized["avatar_overlay_position"] = avatar_overlay_position

    try:
        avatar_overlay_scale = float(normalized.get("avatar_overlay_scale") or DEFAULT_CONFIG["avatar_overlay_scale"])
    except Exception:
        avatar_overlay_scale = float(DEFAULT_CONFIG["avatar_overlay_scale"])
    normalized["avatar_overlay_scale"] = round(max(0.16, min(0.32, avatar_overlay_scale)), 3)

    try:
        avatar_overlay_corner_radius = int(
            normalized.get("avatar_overlay_corner_radius") or DEFAULT_CONFIG["avatar_overlay_corner_radius"]
        )
    except Exception:
        avatar_overlay_corner_radius = int(DEFAULT_CONFIG["avatar_overlay_corner_radius"])
    normalized["avatar_overlay_corner_radius"] = max(0, min(64, avatar_overlay_corner_radius))

    try:
        avatar_overlay_border_width = int(
            normalized.get("avatar_overlay_border_width") or DEFAULT_CONFIG["avatar_overlay_border_width"]
        )
    except Exception:
        avatar_overlay_border_width = int(DEFAULT_CONFIG["avatar_overlay_border_width"])
    normalized["avatar_overlay_border_width"] = max(0, min(12, avatar_overlay_border_width))

    avatar_overlay_border_color = str(
        normalized.get("avatar_overlay_border_color") or DEFAULT_CONFIG["avatar_overlay_border_color"]
    ).strip().upper()
    if not re.fullmatch(r"#[0-9A-F]{6}", avatar_overlay_border_color):
        avatar_overlay_border_color = str(DEFAULT_CONFIG["avatar_overlay_border_color"])
    normalized["avatar_overlay_border_color"] = avatar_overlay_border_color

    export_resolution_mode = str(
        normalized.get("export_resolution_mode") or DEFAULT_CONFIG["export_resolution_mode"]
    ).strip() or DEFAULT_CONFIG["export_resolution_mode"]
    if export_resolution_mode not in EXPORT_RESOLUTION_MODE_OPTIONS:
        export_resolution_mode = DEFAULT_CONFIG["export_resolution_mode"]
    normalized["export_resolution_mode"] = export_resolution_mode

    export_resolution_preset = str(
        normalized.get("export_resolution_preset") or DEFAULT_CONFIG["export_resolution_preset"]
    ).strip() or DEFAULT_CONFIG["export_resolution_preset"]
    if export_resolution_preset not in EXPORT_RESOLUTION_PRESET_OPTIONS:
        export_resolution_preset = DEFAULT_CONFIG["export_resolution_preset"]
    normalized["export_resolution_preset"] = export_resolution_preset

    normalized["music_volume"] = float(normalized.get("music_volume") or DEFAULT_CONFIG["music_volume"])
    normalized["watermark_opacity"] = float(normalized.get("watermark_opacity") or DEFAULT_CONFIG["watermark_opacity"])
    normalized["watermark_scale"] = float(normalized.get("watermark_scale") or DEFAULT_CONFIG["watermark_scale"])
    normalized["watermark_position"] = (
        str(normalized.get("watermark_position") or DEFAULT_CONFIG["watermark_position"]).strip()
        or DEFAULT_CONFIG["watermark_position"]
    )
    normalized["enabled"] = bool(normalized.get("enabled"))
    return normalized


def _save_state(state: dict[str, Any]) -> None:
    try:
        _save_state_to_db(state)
    except Exception:
        PACKAGING_ROOT.mkdir(parents=True, exist_ok=True)
        MANIFEST_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_state_from_db() -> tuple[dict[str, Any], bool]:
    async def _operation(session: Any) -> tuple[dict[str, Any], bool]:
        from roughcut.db.models import AppSetting, PackagingAsset

        asset_rows = (await session.execute(select(PackagingAsset))).scalars().all()
        config_row = await session.get(AppSetting, PACKAGING_CONFIG_KEY)
        state = {
            "assets": [_serialize_asset_row(row) for row in asset_rows],
            "config": dict(DEFAULT_CONFIG),
        }
        if config_row is not None and isinstance(config_row.value_json, dict):
            state["config"].update(config_row.value_json)
        has_data = bool(asset_rows) or config_row is not None
        return state, has_data

    return run_db_operation(_operation)


def _save_state_to_db(state: dict[str, Any]) -> None:
    assets = [dict(item or {}) for item in (state.get("assets") or [])]
    config = dict(state.get("config") or {})

    async def _operation(session: Any) -> None:
        from roughcut.db.models import AppSetting, PackagingAsset

        existing_assets = (await session.execute(select(PackagingAsset))).scalars().all()
        for row in existing_assets:
            await session.delete(row)

        for item in assets:
            session.add(
                PackagingAsset(
                    id=str(item.get("id") or uuid.uuid4().hex),
                    asset_type=str(item.get("asset_type") or ""),
                    original_name=str(item.get("original_name") or ""),
                    stored_name=str(item.get("stored_name") or ""),
                    path=str(item.get("path") or ""),
                    size_bytes=int(item.get("size_bytes") or 0),
                    content_type=str(item.get("content_type") or "application/octet-stream"),
                    watermark_preprocessed=item.get("watermark_preprocessed"),
                    created_at=_parse_asset_timestamp(item.get("created_at")),
                )
            )

        config_row = await session.get(AppSetting, PACKAGING_CONFIG_KEY)
        if config_row is None:
            config_row = AppSetting(key=PACKAGING_CONFIG_KEY, value_json=config)
            session.add(config_row)
        else:
            config_row.value_json = config

        await session.commit()

    run_db_operation(_operation)


def _load_legacy_state() -> dict[str, Any]:
    state = {
        "assets": [],
        "config": dict(DEFAULT_CONFIG),
    }
    if not MANIFEST_PATH.exists():
        return state
    try:
        raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return state
    state["assets"] = list(raw.get("assets") or [])
    state["config"].update(raw.get("config") or {})
    return state


def _serialize_asset_row(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "asset_type": row.asset_type,
        "original_name": row.original_name,
        "stored_name": row.stored_name,
        "path": row.path,
        "size_bytes": row.size_bytes,
        "content_type": row.content_type,
        "watermark_preprocessed": row.watermark_preprocessed,
        "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else str(row.created_at),
    }


def _parse_asset_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value or datetime.now(timezone.utc).isoformat()))


def _rank_packaging_assets(
    assets: list[dict[str, Any]],
    *,
    asset_type: str,
    content_profile: dict[str, Any] | None,
    random_seed: str | None = None,
) -> list[dict[str, Any]]:
    scored = [
        _score_packaging_asset(asset, asset_type=asset_type, content_profile=content_profile)
        for asset in assets
    ]
    if random_seed:
        random.Random(random_seed).shuffle(scored)
    scored.sort(
        key=lambda item: (
            -float(item["score"]),
            str(item["asset"].get("created_at") or ""),
            str(item["asset"].get("original_name") or ""),
        ),
        reverse=False,
    )
    return [
        {
            "asset_id": item["asset"]["id"],
            "score": item["score"],
            "reasons": item["reasons"],
        }
        for item in scored
    ]


def _score_packaging_asset(
    asset: dict[str, Any],
    *,
    asset_type: str,
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    profile = content_profile or {}
    preset_name = normalize_workflow_template_name(
        str(profile.get("workflow_template") or profile.get("preset_name") or "").strip()
    )
    subject_domain = _resolve_packaging_subject_domain(profile)
    asset_tokens = _tokenize_packaging_text(
        " ".join(
            [
                str(asset.get("original_name") or ""),
                str(Path(str(asset.get("original_name") or "")).stem),
            ]
        )
    )
    profile_tokens = _tokenize_packaging_text(
        " ".join(
            str(profile.get(key) or "")
            for key in ("subject_brand", "subject_model", "subject_type", "video_theme", "summary")
        )
    )
    preset_tokens = PRESET_HINT_KEYWORDS.get(preset_name, set())
    domain_tokens = DOMAIN_HINT_KEYWORDS.get(subject_domain, set())
    reasons: list[str] = []
    score = 0.28

    if asset_type == "music":
        mood_tokens = MUSIC_MOOD_KEYWORDS.get(preset_name, set())
        domain_mood_tokens = DOMAIN_MOOD_KEYWORDS.get(subject_domain, set())
        mood_matches = asset_tokens & mood_tokens
        domain_mood_matches = asset_tokens & domain_mood_tokens
        preset_matches = asset_tokens & preset_tokens
        domain_matches = asset_tokens & domain_tokens
        if domain_mood_matches:
            score += min(0.34, 0.12 * len(domain_mood_matches))
            reasons.append("BGM 气质匹配内容领域")
        if mood_matches:
            score += min(0.3, 0.1 * len(mood_matches))
            reasons.append("BGM 气质匹配视频风格")
        if asset_tokens & GENERIC_MUSIC_TOKENS:
            score += 0.08
            reasons.append("文件命名明确为背景音乐")
        if domain_matches:
            score += min(0.18, 0.09 * len(domain_matches))
            reasons.append("文件命名直接命中内容领域")
        if preset_matches:
            score += 0.12
            reasons.append("文件命名直接命中内容预设")
        if domain_matches and domain_mood_matches:
            score += 0.08
            reasons.append("内容领域和气质同时命中")
        if mood_matches and preset_matches:
            score += 0.08
            reasons.append("风格和内容类型同时命中")
    else:
        subject_matches = asset_tokens & profile_tokens
        domain_matches = asset_tokens & domain_tokens
        if subject_matches:
            score += min(0.34, 0.12 * len(subject_matches))
            reasons.append("插入素材命中视频主体信息")
        if domain_matches:
            score += min(0.18, 0.09 * len(domain_matches))
            reasons.append("文件命名贴合当前内容领域")
        if asset_tokens & GENERIC_INSERT_TOKENS:
            score += 0.12
            reasons.append("文件命名表明是可插入 B-roll")
        if asset_tokens & preset_tokens:
            score += 0.08
            reasons.append("文件命名贴合当前内容类型")

    if not reasons and asset_tokens:
        score += 0.04
        reasons.append("候选文件名包含可用线索")

    score = round(min(score, 0.99), 3)
    return {"asset": asset, "score": score, "reasons": reasons}


def _build_packaging_selection_summary(rankings: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rankings:
        return None
    settings = get_settings()
    primary = rankings[0]
    runner_up = rankings[1] if len(rankings) > 1 else None
    primary_score = float(primary.get("score") or 0.0)
    runner_up_score = float(runner_up.get("score") or 0.0) if runner_up else 0.0
    score_gap = round(max(0.0, primary_score - runner_up_score), 3)
    review_recommended = bool(
        primary_score < float(settings.packaging_selection_min_score)
        or (runner_up is not None and score_gap <= float(settings.packaging_selection_review_gap))
    )
    return {
        "selected_asset_id": primary.get("asset_id"),
        "selected_score": round(primary_score, 3),
        "runner_up_asset_id": runner_up.get("asset_id") if runner_up else None,
        "runner_up_score": round(runner_up_score, 3),
        "score_gap": score_gap,
        "review_recommended": review_recommended,
        "review_reason": (
            "候选分差过小或匹配信号不足，建议确认首选素材。"
            if review_recommended
            else ""
        ),
    }


def _resolve_packaging_subject_domain(profile: dict[str, Any] | None) -> str:
    candidate = normalize_subject_domain(str((profile or {}).get("subject_domain") or "").strip())
    if candidate:
        return candidate
    detected = detect_glossary_domains(
        workflow_template=None,
        content_profile=profile or {},
        subtitle_items=None,
        source_name=None,
    )
    return str(select_primary_subject_domain(detected) or "")


def _tokenize_packaging_text(text: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9]+|[\u3400-\u9fff]{2,}", str(text or "")):
        token = str(raw).strip().upper()
        if len(token) >= 2:
            tokens.add(token)
    return tokens
