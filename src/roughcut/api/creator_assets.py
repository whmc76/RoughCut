from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from roughcut.api.schemas import (
    CreatorCardIn,
    CreatorCardListOut,
    CreatorCardOut,
    CreatorCardPatch,
    CreatorCardRefineIn,
    CreatorPlatformBindingIn,
    CreatorPublicationProfileOut,
    CreatorSocialAutoUploadBindingIn,
    CreatorTaskStrategyListOut,
    CreatorTaskStrategyOut,
    CreatorVisualPlanListOut,
    CreatorVisualPlanOut,
    PlanVersionOut,
    PublicationProfilePatch,
    PublicationProfileRefineIn,
    TaskStrategyGenerateIn,
    TaskStrategyRefineIn,
    VisualPlanGenerateIn,
    VisualPlanRefineIn,
)
from roughcut.avatar import list_avatar_material_profiles
from roughcut.config import get_settings, llm_task_route
from roughcut.creator_asset_runtime import resolve_creator_asset_path
from roughcut.db.models import (
    CreatorAsset,
    CreatorCard,
    CreatorPlatformBinding,
    CreatorPreference,
    CreatorPublicationProfile,
    CreatorTaskStrategy,
    CreatorVisualPlan,
    PublicationProfileVersion,
    TaskStrategyVersion,
    VisualPlanVersion,
)
from roughcut.production_readiness import creator_refine_output_fallback_reasons
from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message
from roughcut.publication import (
    normalize_publication_browser_name,
    normalize_publication_platform,
    platform_label,
)
from roughcut.publication_social_auto_upload import SOCIAL_AUTO_UPLOAD_ADAPTER, supports_social_auto_upload_platform
from roughcut.db.session import get_session

router = APIRouter(prefix="/creator-cards", tags=["creator-assets"])
MAX_CREATOR_CARDS = 10


def _clean_list(values: Any) -> list[str]:
    if isinstance(values, str):
        return [item.strip() for item in values.replace("，", ",").split(",") if item.strip()]
    if isinstance(values, (list, tuple, set)):
        return [str(item).strip() for item in values if str(item).strip()]
    return []


def _build_legacy_creator_card_payload(profile: dict[str, Any]) -> dict[str, Any] | None:
    display_name = str(profile.get("display_name") or "").strip()
    presenter_alias = str(profile.get("presenter_alias") or "").strip()
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    archive_notes = str(creator_profile.get("archive_notes") or profile.get("notes") or "").strip()

    name = display_name or presenter_alias or str(identity.get("public_name") or "").strip()
    if not name:
        return None

    content_domains = _clean_list(positioning.get("expertise"))
    default_platforms: list[str] = []
    for raw in [publishing.get("primary_platform"), *list(publishing.get("active_platforms") or [])]:
        normalized = normalize_publication_platform(raw)
        if normalized and normalized not in default_platforms:
            default_platforms.append(normalized)

    positioning_bits = [
        str(positioning.get("creator_focus") or "").strip(),
        str(positioning.get("style") or "").strip(),
        str(identity.get("title") or "").strip(),
    ]
    positioning_text = " / ".join(item for item in positioning_bits if item)

    natural_language_bits = [
        f"公开名称：{identity.get('public_name')}" if str(identity.get("public_name") or "").strip() else "",
        f"简介：{identity.get('bio')}" if str(identity.get("bio") or "").strip() else "",
        f"受众：{positioning.get('audience')}" if str(positioning.get("audience") or "").strip() else "",
        f"语气关键词：{'、'.join(_clean_list(positioning.get('tone_keywords')))}" if _clean_list(positioning.get("tone_keywords")) else "",
        f"档案备注：{archive_notes}" if archive_notes else "",
    ]

    return {
        "legacy_profile_id": str(profile.get("id") or "").strip(),
        "name": name,
        "positioning": positioning_text or None,
        "content_domains": content_domains,
        "audience": str(positioning.get("audience") or "").strip() or None,
        "default_platforms": default_platforms,
        "natural_language_profile": "\n".join(item for item in natural_language_bits if item) or None,
        "status": "active",
    }


def _strip_public_name_lines(value: str | None) -> str | None:
    lines: list[str] = []
    for line in str(value or "").splitlines():
        text = line.strip()
        if not text:
            continue
        if re.search(r"^(公开名称|名称|名字)\s*[：:=是为]", text):
            continue
        lines.append(text)
    return "\n".join(lines) or None


def _compact_text(value: Any, *, max_len: int = 240) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None
    return text[:max_len]


def _normalize_creator_refine_patch(raw: Any) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    patch: dict[str, Any] = {}
    for key in ("name", "positioning", "audience", "natural_language_profile"):
        value = _compact_text(payload.get(key))
        if value:
            patch[key] = value
    for key in ("content_domains", "default_platforms"):
        values = _clean_list(payload.get(key))
        if key == "default_platforms":
            normalized: list[str] = []
            for item in values:
                platform = normalize_publication_platform(item)
                if platform and platform not in normalized:
                    normalized.append(platform)
            values = normalized
        if values:
            patch[key] = values[:12]
    return patch


def _fallback_creator_refine_patch(prompt: str) -> dict[str, Any]:
    text = str(prompt or "").strip()
    patch: dict[str, Any] = {}
    patterns = {
        "name": r"(?:公开名称|名称|名字)\s*(?:是|为|改成|改为|叫)\s*([^，。；;\n]+)",
        "positioning": r"(?:定位)\s*(?:是|为|改成|改为)\s*([^，。；;\n]+)",
        "audience": r"(?:受众|目标受众)\s*(?:是|为|改成|改为)\s*([^，。；;\n]+)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            value = _compact_text(match.group(1), max_len=120)
            if value:
                patch[key] = value
    domain_match = re.search(r"(?:内容领域|领域)\s*(?:是|为|改成|改为)\s*([^。；;\n]+)", text)
    if domain_match:
        domains = _clean_list(domain_match.group(1))
        if domains:
            patch["content_domains"] = domains[:12]
    platform_match = re.search(r"(?:默认平台|平台)\s*(?:是|为|改成|改为)\s*([^。；;\n]+)", text)
    if platform_match:
        platforms = [
            platform
            for platform in (normalize_publication_platform(item) for item in _clean_list(platform_match.group(1)))
            if platform
        ]
        if platforms:
            patch["default_platforms"] = list(dict.fromkeys(platforms))[:12]
    return patch


async def _build_creator_refine_patch(creator: CreatorCard, prompt: str) -> tuple[dict[str, Any], dict[str, Any]]:
    request_prompt = f"""
你是 RoughCut 的创作者卡片维护 Agent。根据用户的自然语言修改需求，返回要更新到创作者卡片的结构化 JSON。

当前创作者：
- name: {creator.name}
- positioning: {creator.positioning or ""}
- audience: {creator.audience or ""}
- content_domains: {json.dumps(list(creator.content_domains or []), ensure_ascii=False)}
- default_platforms: {json.dumps(list(creator.default_platforms or []), ensure_ascii=False)}
- natural_language_profile: {creator.natural_language_profile or ""}

用户修改需求：
{prompt}

只返回 JSON。允许字段：
{{
  "name": "公开名称，只有用户明确要求改公开名称/名称时才填写",
  "positioning": "创作者定位",
  "audience": "受众",
  "content_domains": ["内容领域"],
  "default_platforms": ["bilibili", "douyin"],
  "natural_language_profile": "无法归入以上字段但应该长期保存的自然语言偏好"
}}
不要把“公开名称是...”整句写入 name 或 natural_language_profile；name 只能是最终名称本身。
只处理创作者卡片档案字段。字幕、标题、封面、视觉包装、任务剪辑策略、发布物料等需求不属于本接口；如果用户只提出这些需求，返回 {{}}。
没有需要更新的字段就返回 {{}}。
""".strip()
    try:
        with llm_task_route("content_profile", search_enabled=False, settings=get_settings()):
            response = await get_reasoning_provider().complete(
                [Message(role="user", content=request_prompt)],
                temperature=0.1,
                max_tokens=800,
                json_mode=True,
            )
        patch = _normalize_creator_refine_patch(response.as_json())
        if patch:
            return patch, {"source": "llm", "model": response.model, "usage": response.usage}
    except Exception as exc:
        fallback = _fallback_creator_refine_patch(prompt)
        return fallback, {"source": "rule_fallback", "error": f"{type(exc).__name__}: {exc}"}
    return _fallback_creator_refine_patch(prompt), {"source": "rule_fallback", "error": "llm_returned_empty_patch"}


async def _sync_legacy_avatar_profiles(session: AsyncSession) -> None:
    legacy_profiles = list_avatar_material_profiles()
    if not legacy_profiles:
        return

    result = await session.execute(
        select(CreatorCard)
        .options(selectinload(CreatorCard.preferences))
    )
    existing_cards = list(result.scalars().unique())
    existing_by_name = {card.name.strip().lower(): card for card in existing_cards if card.name.strip()}
    existing_by_legacy_id: dict[str, CreatorCard] = {}
    existing_bindings_by_card_id: dict[uuid.UUID, set[str]] = {}
    for card in existing_cards:
        existing_bindings_by_card_id[card.id] = set()
        for preference in card.preferences:
            if preference.source != "legacy_avatar_profile":
                continue
            legacy_id = str((preference.structured_payload or {}).get("legacy_profile_id") or "").strip()
            if legacy_id:
                existing_by_legacy_id[legacy_id] = card
                existing_bindings_by_card_id[card.id].add(legacy_id)

    changed = False
    for profile in legacy_profiles:
        if len(existing_by_name) >= MAX_CREATOR_CARDS:
            break
        payload = _build_legacy_creator_card_payload(profile)
        if payload is None:
            continue
        legacy_id = payload.pop("legacy_profile_id")
        card = existing_by_legacy_id.get(legacy_id)
        if card is None:
            card = existing_by_name.get(payload["name"].strip().lower())

        if card is None:
            card = CreatorCard(**payload)
            session.add(card)
            await session.flush()
            existing_by_name[card.name.strip().lower()] = card
            existing_bindings_by_card_id[card.id] = set()
            changed = True
        else:
            for field in ("positioning", "audience", "natural_language_profile"):
                if not getattr(card, field) and payload.get(field):
                    setattr(card, field, payload[field])
                    changed = True
            if not list(card.content_domains or []) and payload["content_domains"]:
                card.content_domains = payload["content_domains"]
                changed = True
            if not list(card.default_platforms or []) and payload["default_platforms"]:
                card.default_platforms = payload["default_platforms"]
                changed = True
            if str(card.status or "").strip() == "draft":
                card.status = "active"
                changed = True

        has_legacy_binding = legacy_id in existing_bindings_by_card_id.get(card.id, set())
        if not has_legacy_binding:
            session.add(
                CreatorPreference(
                    creator_card_id=card.id,
                    preference_type="legacy_profile_binding",
                    natural_language_rule=f"从旧创作者档案导入：{payload['name']}",
                    structured_payload={"legacy_profile_id": legacy_id} if legacy_id else {"legacy_name": payload["name"]},
                    source="legacy_avatar_profile",
                )
            )
            if legacy_id:
                existing_bindings_by_card_id.setdefault(card.id, set()).add(legacy_id)
            changed = True

    if changed:
        await session.commit()


def _creator_asset_dir(creator_id: uuid.UUID) -> Path:
    base = Path(get_settings().output_dir).expanduser().resolve() / "_creator_assets" / str(creator_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _repair_creator_asset_storage_path(asset: CreatorAsset) -> bool:
    resolved = resolve_creator_asset_path(asset.stored_path)
    if not resolved.exists() or not resolved.is_file():
        return False
    normalized = resolved.as_posix()
    if normalized == str(asset.stored_path or ""):
        return False
    asset.stored_path = normalized
    return True


def _repair_creator_assets_storage_paths(assets: list[CreatorAsset]) -> bool:
    changed = False
    for asset in assets:
        changed = _repair_creator_asset_storage_path(asset) or changed
    return changed


def _sanitize_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in (name or "asset.bin"))
    return cleaned[:180] or "asset.bin"


def _strategy_payload(prompt: str, creator: CreatorCard, index: int, strategy_type: str) -> dict[str, Any]:
    creator_name = creator.name.strip()
    positioning = (creator.positioning or creator.natural_language_profile or "").strip()
    intent = prompt.strip() or "基于创作者卡片直接生成默认剪辑策略"
    variants = [
        {
            "style_name": "紧凑密集型",
            "strategy_type": "creator_compact_dense_policy",
            "policy_scope": "覆盖评测、教程、对比、高光等任务，由素材内容自动路由",
            "priority_bias": "高信息密度和快节奏优先，压缩停顿和铺垫",
            "strategy_goal": "把说话节奏剪快、镜头变短，让信息连续输出",
            "opening_policy": "开头 3-8 秒直接给结果、冲突或最强信息点",
            "structure_policy": "钩子 -> 高频信息点 -> 短证据 -> 快速收束",
            "editing_playbook": "压短句间停顿，减少长镜头停留，用短段落连续推进",
            "speech_rhythm_policy": "压缩停顿和重复语气词，让口播更利落",
            "shot_length_policy": "多数镜头控制在 1.5-3 秒，证据镜头按理解需要稍作停留",
            "keep_policy": "保留结果镜头、强变化、核心结论和最短必要证据",
            "cut_policy": "删除长铺垫、弱信息解释、重复论证、等待和节奏低谷",
            "pacing_policy": "整体偏快，连续弱信息段压缩，关键结论短暂停留",
            "packaging_strategy": "高密度包装，用字幕、强调条和节奏点维持注意力",
            "transition_policy": "段落切换和信息峰值处允许快转场，但不能遮挡主体",
            "effect_insert_policy": "在开头钩子、结果揭示、反差点和强信息点插入动态强调",
            "effect_frequency": "中到高，每 8-15 秒允许 1 次明显包装或强调",
            "effect_logic": "包装跟随信息峰值，不给低信息片段加装饰",
            "effect_style": "快闪、速度线、弹出标题、节奏型音效点",
            "evidence_policy": "判断必须有画面、参数、步骤结果或上下文支撑",
            "manual_review_boundary": "删除步骤、改变结论或涉及强判断时人工确认",
            "applicable_scenes": ["产品评测", "教程演示", "新旧对比", "长视频切片"],
            "routing_matrix": {
                "product_review": "先结论后证据",
                "tutorial": "步骤保真，压缩等待",
                "comparison": "按差异维度重排",
                "highlight": "提炼高光但保留必要上下文",
            },
            "success_metric": "弱信息段明显减少，前 8 秒有明确钩子",
            "expected_effect": "成片更短、更利落，适合信息流和高密度内容",
            "automation_level": "balanced",
            "material_usage": "selected_uploaded",
            "risk_gate": "manual_confirm_for_context_loss",
            "rules": [
                "优先压缩停顿、重复和弱信息段",
                "短镜头连续推进，但不得剪掉改变理解的上下文",
                "包装只跟随信息峰值和段落切换",
            ],
            "sample_case": "同样能处理评测、教程、对比、高光；区别是整体更快、更短、更密集",
        },
        {
            "style_name": "自然松弛型",
            "strategy_type": "creator_relaxed_natural_policy",
            "policy_scope": "覆盖所有任务，但默认把证据链和信息密度放在第一位",
            "priority_bias": "自然表达和观看舒适度优先，保留必要停顿和现场感",
            "strategy_goal": "让成片像真实讲述，不把口播剪得过碎",
            "opening_policy": "开头先自然进入主题，可以保留一句铺垫或现场语气",
            "structure_policy": "自然引入 -> 重点段落 -> 解释/演示 -> 温和收束",
            "editing_playbook": "保留自然呼吸、反应和现场过渡，只清掉明显冗余",
            "speech_rhythm_policy": "保留短暂停顿、语气和转折，不追求每句话都顶满",
            "shot_length_policy": "多数镜头 3-6 秒，操作、表情和展示镜头允许更长",
            "keep_policy": "保留自然反应、现场解释、完整展示和能建立信任的上下文",
            "cut_policy": "删除明显重复、长等待、跑题闲聊和技术性错误段",
            "pacing_policy": "中低速，段落之间留呼吸，重点画面给观众看清",
            "packaging_strategy": "低干扰包装，少特效，主要用字幕和轻提示辅助理解",
            "transition_policy": "以硬切和自然过渡为主，少用明显转场",
            "effect_insert_policy": "只在重点名词、步骤提醒和必要对比处插入轻标注",
            "effect_frequency": "低，每 30-45 秒最多 1 次明显强调",
            "effect_logic": "包装只解决理解问题，不为了热闹插入",
            "effect_style": "轻字幕、淡入提示、少量局部放大，避免快闪和强音效",
            "evidence_policy": "结论没有证据时降级为疑问或保留人工确认",
            "manual_review_boundary": "涉及购买建议、效果宣称、步骤删除时人工确认",
            "applicable_scenes": ["深度测评", "教程演示", "横向对比", "复盘讲解"],
            "routing_matrix": {
                "product_review": "结论后必须接实测证据",
                "tutorial": "步骤和验证镜头不可自动删除",
                "comparison": "同类证据集中展示",
                "highlight": "高光前后保留必要因果",
            },
            "success_metric": "观众感到顺畅可信，内容不显得被剪得过急",
            "expected_effect": "更像真人自然表达，适合建立信任和长观看",
            "automation_level": "balanced",
            "material_usage": "all_uploaded",
            "risk_gate": "manual_confirm_for_high_risk",
            "rules": [
                "保留自然停顿和关键反应",
                "只删除明确冗余，不强行压成快节奏",
                "包装不得打断主体表达",
            ],
            "sample_case": "同样能处理评测、教程、对比、高光；区别是更慢、更顺、更像真实讲述",
        },
        {
            "style_name": "专业克制型",
            "strategy_type": "creator_professional_controlled_policy",
            "policy_scope": "覆盖所有任务，但默认把开头效率和节奏峰值放在第一位",
            "priority_bias": "结构清晰、证据可信和品牌质感优先",
            "strategy_goal": "在信息密度和可信度之间取中间值，成片干净有秩序",
            "opening_policy": "开头先给明确主题或判断，但不使用夸张钩子",
            "structure_policy": "主题 -> 依据 -> 对比/步骤 -> 结论，段落边界清楚",
            "editing_playbook": "按信息层级剪辑，避免碎切和过度包装",
            "speech_rhythm_policy": "去掉明显废话，但保留判断前后的解释空间",
            "shot_length_policy": "多数镜头 2.5-5 秒，证据和细节镜头稳定停留",
            "keep_policy": "保留证据、参数、关键步骤、对比依据和完整结论",
            "cut_policy": "删除跑题、重复铺垫、无证据夸张表达和影响专业感的片段",
            "pacing_policy": "中速，信息段紧凑，证据段稳定",
            "packaging_strategy": "专业包装，用参数卡、对比框和小标题建立秩序",
            "transition_policy": "段落间用干净短转场或标题卡，不使用花哨动效",
            "effect_insert_policy": "在参数、对比结论、风险提醒处插入克制强调",
            "effect_frequency": "中低，每个核心段落 1 次重点包装",
            "effect_logic": "包装必须帮助建立信息层级或证据关系",
            "effect_style": "低饱和、几何线框、参数卡、局部放大，偏专业感",
            "evidence_policy": "证据保留到足够可信即可，不展开完整论证链",
            "manual_review_boundary": "压缩上下文可能改变原意或误导结论时人工确认",
            "applicable_scenes": ["短视频切片", "新品开箱", "亮点回顾", "信息流首发"],
            "routing_matrix": {
                "product_review": "先结果后压缩证据",
                "tutorial": "先展示最终效果再保留关键步骤",
                "comparison": "先放最大差异",
                "highlight": "高光密集排列",
            },
            "success_metric": "观众能快速理解结构，同时觉得内容可信不浮夸",
            "expected_effect": "适合专业测评、教程和品牌型内容，质感更稳",
            "automation_level": "balanced",
            "material_usage": "all_uploaded",
            "risk_gate": "manual_confirm_for_high_risk",
            "rules": [
                "优先保持信息层级清楚",
                "证据和细节镜头不能过度碎切",
                "包装风格必须克制统一",
            ],
            "sample_case": "同样能处理评测、教程、对比、高光；区别是更干净、更克制、更专业",
        },
    ]
    variant = variants[index % len(variants)]
    return {
        "name": f"{creator_name} · {variant['style_name']}",
        "strategy_type": variant["strategy_type"] if strategy_type == "creator_bound" else strategy_type,
        "intent": intent,
        "policy_scope": variant["policy_scope"],
        "priority_bias": variant["priority_bias"],
        "strategy_goal": variant["strategy_goal"],
        "opening_policy": variant["opening_policy"],
        "structure_policy": variant["structure_policy"],
        "editing_playbook": variant["editing_playbook"],
        "speech_rhythm_policy": variant["speech_rhythm_policy"],
        "shot_length_policy": variant["shot_length_policy"],
        "keep_policy": variant["keep_policy"],
        "cut_policy": variant["cut_policy"],
        "pacing_policy": variant["pacing_policy"],
        "packaging_strategy": variant["packaging_strategy"],
        "transition_policy": variant["transition_policy"],
        "effect_insert_policy": variant["effect_insert_policy"],
        "effect_frequency": variant["effect_frequency"],
        "effect_logic": variant["effect_logic"],
        "effect_style": variant["effect_style"],
        "evidence_policy": variant["evidence_policy"],
        "manual_review_boundary": variant["manual_review_boundary"],
        "applicable_scenes": variant["applicable_scenes"],
        "routing_matrix": variant["routing_matrix"],
        "success_metric": variant["success_metric"],
        "expected_effect": variant["expected_effect"],
        "automation_level": variant["automation_level"],
        "material_usage": variant["material_usage"],
        "risk_gate": variant["risk_gate"],
        "rules": [f"开场先对齐 {creator_name} 的表达定位", *variant["rules"]],
        "sample_case": variant["sample_case"],
        "why": [
            f"基于创作者定位：{positioning}" if positioning else f"基于创作者 {creator_name} 的长期风格",
            "基于本次自然语言任务想法提炼主线",
            f"候选策略侧重：{variant['strategy_goal']}",
        ],
        "fallback_mapping": {
            "workflow_mode": "standard_edit",
            "job_flow_mode": "auto",
            "enhancement_modes": ["auto_review"],
        },
    }


def _visual_payload(prompt: str, creator: CreatorCard, index: int) -> dict[str, Any]:
    creator_name = creator.name.strip()
    direction = prompt.strip() or "基于创作者卡片直接生成默认视觉方向"
    variants = [
        {
            "style_name": "结论特写型",
            "cover_direction": "产品主体特写 + 右侧结论式短标题",
            "subtitle_direction": "中等密度，型号、参数和结论词高亮",
            "title_tone": "直接判断，先给值不值得的结论",
            "color_direction": "低饱和青绿 + 冷灰底，可信、克制",
            "copy_tone": "事实判断优先，少形容词",
            "sample_case": {
                "scene": "新品开箱对比首屏",
                "cover_text": "升级点值不值",
                "title_sample": "新款到底值不值得换？先看这 3 点",
                "subtitle_sample": "关键参数：响应更快，噪声更低",
                "layout": "左侧主体特写，右侧两行短结论，下方参数标签",
            },
        },
        {
            "style_name": "同框对比型",
            "cover_direction": "新旧产品同框 + 三个差异标签",
            "subtitle_direction": "低密度，只高亮对比结论和风险点",
            "title_tone": "对比复盘，先说取舍，不制造悬念",
            "color_direction": "冷白背景 + 深蓝信息条，清楚、理性",
            "copy_tone": "对照项清晰，强调证据链",
            "sample_case": {
                "scene": "老款和新款横向对比段落",
                "cover_text": "差价买到了什么",
                "title_sample": "同价位对比：这次升级主要在这两处",
                "subtitle_sample": "老款：稳定 / 新款：响应更快",
                "layout": "左右分屏，同一角度同框，对比标签贴近主体",
            },
        },
        {
            "style_name": "场景验证型",
            "cover_direction": "真实使用场景 + 结果数据卡片",
            "subtitle_direction": "操作短句 + 结果数字突出，少用满屏字幕",
            "title_tone": "场景化判断，强调测试结果",
            "color_direction": "暖白 + 深墨绿强调色，生活感但不营销",
            "copy_tone": "像现场记录，结论来自测试过程",
            "sample_case": {
                "scene": "实际安装或上手测试片段",
                "cover_text": "实测后再下结论",
                "title_sample": "装上实测一圈，问题和优点都很明显",
                "subtitle_sample": "实测结果：稳定，但安装门槛更高",
                "layout": "大画面保留真实环境，右下角放结果数据卡",
            },
        },
        {
            "style_name": "步骤讲解型",
            "cover_direction": "关键步骤定格 + 操作编号",
            "subtitle_direction": "步骤字幕短句，风险提醒单独高亮",
            "title_tone": "教程式说明，直接告诉观众能不能照做",
            "color_direction": "米白底 + 黑色主字 + 琥珀提醒色",
            "copy_tone": "说明清楚，避免夸张承诺",
            "sample_case": {
                "scene": "安装步骤或参数设置教程",
                "cover_text": "照做前先看这步",
                "title_sample": "这一步别跳过，否则后面会返工",
                "subtitle_sample": "第 2 步：先确认接口方向",
                "layout": "主体操作画面占 70%，左上角步骤编号，底部提醒条",
            },
        },
    ]
    variant = variants[index % len(variants)]
    return {
        "name": f"{creator_name} · {variant['style_name']}",
        "cover_direction": variant["cover_direction"],
        "subtitle_direction": variant["subtitle_direction"],
        "title_tone": variant["title_tone"],
        "color_direction": variant["color_direction"],
        "copy_tone": f"{variant['copy_tone']}；本次方向：{direction}",
        "sample_case": variant["sample_case"],
        "platform_variants": {
            "bilibili": "信息更完整，保留型号与依据",
            "douyin": "前三秒更直接，保留一句核心判断",
        },
        "agent_reason": f"根据 {creator_name} 的定位和任务想法生成「{variant['style_name']}」候选视觉方向。",
    }


def _publication_payload(creator: CreatorCard, prompt: str | None = None) -> dict[str, Any]:
    collection_strategy = _default_collection_strategy_for_creator(creator)
    return _normalize_publication_profile_payload({
        "default_platforms": list(creator.default_platforms or []),
        "publication_mode": "material_only",
        "collection_strategy": collection_strategy,
        "platform_options": {},
        "platform_rules": {
            platform: {
                "title_rule": "标题保留结论与关键实体",
                "intro_rule": "前三秒突出本条内容最重要的信息",
            }
            for platform in list(creator.default_platforms or [])
        },
        "agent_reason": prompt.strip() if prompt else "根据创作者卡片默认平台和定位生成。",
    })


def _default_collection_strategy_for_creator(creator: CreatorCard) -> dict[str, Any]:
    creator_blob = " ".join(
        str(item or "")
        for item in (
            creator.name,
            creator.positioning,
            creator.natural_language_profile,
            " ".join(str(item) for item in (creator.content_domains or [])),
        )
    ).lower()
    if "fas" not in creator_blob:
        return {"mode": "auto"}
    default_collection_name = "EDC刀光火工具集"
    return {
        "mode": "llm_classify",
        "default_collection_name": default_collection_name,
        "candidate_collections": ["EDC潮玩桌搭", "EDC刀光火工具集", "FAS新品", "机能户外装备"],
        "rules": [
            {
                "collection_name": "EDC潮玩桌搭",
                "natural_language_rule": "适合潮玩、桌搭、把玩件、玩具属性或设计趣味强的 EDC 内容。重点判断内容主体是不是偏玩具感、收藏感、桌面摆件感，而不是实用工具测评。",
                "examples": ["MOT 风灵音叉推牌", "锆合金把玩件", "潮玩桌搭开箱"],
            },
            {
                "collection_name": "EDC刀光火工具集",
                "natural_language_rule": "适合刀具、手电、工具、户外实用装备、EDC 工具属性明确的内容。重点判断内容主体是否在讲功能、材质、做工、使用场景或工具价值。",
                "examples": ["MAXACE 美杜莎", "折刀开箱", "手电工具类 EDC 介绍"],
            },
            {
                "collection_name": "FAS新品",
                "natural_language_rule": "适合新品首发、新款上架、首次到货、开售预告等以新品信息为核心的内容。若同时属于工具或潮玩，但重点是新品发布，优先进入新品合集。",
                "examples": ["新品首发", "新款到货", "开售预告"],
            },
            {
                "collection_name": "机能户外装备",
                "natural_language_rule": "适合机能穿搭、户外装备、背包、收纳、露营或通勤装备系统类内容。重点判断是否围绕户外/通勤/机能场景建立装备方案。",
                "examples": ["机能户外装备", "通勤装备系统", "露营收纳"],
            },
        ],
        "classifier": "llm",
        "classification_basis": "根据任务想法、素材文件名、发布标题、简介、标签和内容摘要理解视频主题，选择一个最合适的合集。",
        "source": "legacy_fas_publication_policy",
    }


def _normalize_collection_strategy_payload(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    default_collection_name = str(raw.get("default_collection_name") or "").strip()
    mode = str(raw.get("mode") or ("select_existing" if default_collection_name else "auto")).strip() or "auto"
    candidate_collections = [
        str(item).strip()
        for item in (raw.get("candidate_collections") or [])
        if str(item).strip()
    ]
    rules = [dict(item) for item in (raw.get("rules") or []) if isinstance(item, dict)]
    platforms_raw = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else {}
    platforms: dict[str, dict[str, Any]] = {}
    for raw_platform, raw_config in platforms_raw.items():
        platform = normalize_publication_platform(raw_platform)
        if not platform or not isinstance(raw_config, dict):
            continue
        collection_name = str(raw_config.get("collection_name") or (default_collection_name if mode != "rule_based" else "") or "").strip()
        enabled = bool(raw_config.get("enabled", True))
        collection_management = (
            dict(raw_config.get("collection_management"))
            if isinstance(raw_config.get("collection_management"), dict)
            else {}
        )
        if collection_name:
            collection_management.setdefault("status", "select_existing")
            collection_management.setdefault("target_collection_name", collection_name)
            collection_management.setdefault("selected_collection_name", collection_name)
        platforms[platform] = {
            "enabled": enabled,
            "collection_name": collection_name,
            "collection_management": collection_management,
        }
    return {
        "mode": mode,
        "default_collection_name": default_collection_name,
        "candidate_collections": candidate_collections,
        "rules": rules,
        "classifier": str(raw.get("classifier") or ("llm" if mode == "llm_classify" else "")).strip(),
        "classification_basis": str(raw.get("classification_basis") or "").strip(),
        "platforms": platforms,
        "source": str(raw.get("source") or "").strip() or "publication_management",
    }


def _platform_options_from_collection_strategy(
    collection_strategy: dict[str, Any],
    default_platforms: Any = None,
) -> dict[str, dict[str, Any]]:
    strategy = _normalize_collection_strategy_payload(collection_strategy)
    if str(strategy.get("mode") or "").strip() in {"rule_based", "llm_classify"}:
        return {}
    options: dict[str, dict[str, Any]] = {}
    platforms = [
        platform
        for platform in (normalize_publication_platform(item) for item in (default_platforms or []))
        if platform
    ]
    if not platforms:
        platforms = list((strategy.get("platforms") or {}).keys())
    for platform in platforms:
        config = (strategy.get("platforms") or {}).get(platform) or {}
        collection_name = str(config.get("collection_name") or strategy.get("default_collection_name") or "").strip()
        if not collection_name:
            continue
        options[platform] = {
            "collection_name": collection_name,
            "platform_specific_overrides": {
                "collection_management": dict(config.get("collection_management") or {
                    "status": "select_existing",
                    "target_collection_name": collection_name,
                    "selected_collection_name": collection_name,
                }),
            },
        }
    return options


def _merge_publication_platform_options(
    base: dict[str, dict[str, Any]],
    override: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    merged = {platform: dict(options) for platform, options in base.items()}
    for platform, options in override.items():
        current = dict(merged.get(platform) or {})
        for key, value in options.items():
            if key == "platform_specific_overrides" and isinstance(value, dict):
                nested = (
                    dict(current.get("platform_specific_overrides"))
                    if isinstance(current.get("platform_specific_overrides"), dict)
                    else {}
                )
                nested.update(value)
                current["platform_specific_overrides"] = nested
            else:
                current[key] = value
        merged[platform] = current
    return merged


def _normalize_publication_profile_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload or {})
    collection_strategy = _normalize_collection_strategy_payload(normalized.get("collection_strategy"))
    normalized["collection_strategy"] = collection_strategy
    collection_options = _platform_options_from_collection_strategy(collection_strategy, normalized.get("default_platforms"))
    platform_options = normalized.get("platform_options")
    cleaned_options: dict[str, dict[str, Any]] = {}
    if isinstance(platform_options, dict):
        for raw_platform, raw_options in platform_options.items():
            platform = normalize_publication_platform(raw_platform)
            if not platform or not isinstance(raw_options, dict):
                continue
            option = {str(key): value for key, value in raw_options.items() if value not in ("", None, [], {})}
            nested_overrides = option.get("platform_specific_overrides")
            if isinstance(nested_overrides, dict):
                option["platform_specific_overrides"] = {
                    str(key): value for key, value in nested_overrides.items() if value not in ("", None, [], {})
                }
                if not option["platform_specific_overrides"]:
                    option.pop("platform_specific_overrides", None)
            if option:
                cleaned_options[platform] = option
    normalized["platform_options"] = _merge_publication_platform_options(collection_options, cleaned_options)
    return normalized


def _merge_fas_collection_strategy_defaults(
    existing: Any,
    default_strategy: dict[str, Any],
) -> dict[str, Any]:
    current = existing if isinstance(existing, dict) else {}
    current_platforms = current.get("platforms") if isinstance(current.get("platforms"), dict) else {}
    default_platforms = default_strategy.get("platforms") if isinstance(default_strategy.get("platforms"), dict) else {}
    current_rules = current.get("rules") if isinstance(current.get("rules"), list) else []
    has_natural_language_rules = any(
        isinstance(rule, dict) and str(rule.get("natural_language_rule") or "").strip()
        for rule in current_rules
    )
    mode = str(
        current.get("mode") if has_natural_language_rules else default_strategy.get("mode")
        or current.get("mode")
        or "llm_classify"
    )
    return {
        **default_strategy,
        **current,
        "mode": mode,
        "default_collection_name": str(
            current.get("default_collection_name") or default_strategy.get("default_collection_name") or ""
        ).strip(),
        "candidate_collections": current.get("candidate_collections") or default_strategy.get("candidate_collections") or [],
        "rules": current_rules if has_natural_language_rules else default_strategy.get("rules") or [],
        "platforms": {} if mode == "llm_classify" else {**default_platforms, **current_platforms},
        "source": current.get("source") or default_strategy.get("source") or "legacy_fas_publication_policy",
    }


def _normalize_creator_platform_or_400(platform: str) -> str:
    normalized = normalize_publication_platform(platform)
    if not normalized:
        raise HTTPException(status_code=400, detail="不支持的发布平台。")
    return normalized


def _normalize_publication_browser_or_400(browser: str | None) -> str:
    normalized = normalize_publication_browser_name(browser or "chrome")
    if not normalized:
        raise HTTPException(status_code=400, detail="不支持的浏览器选项。")
    return normalized


def _social_auto_upload_account_name(creator: CreatorCard, browser: str, explicit: str | None = None) -> str:
    value = str(explicit or "").strip()
    if value:
        return value
    browser_label = {
        "chrome": "Chrome",
        "edge": "Edge",
        "browser-agent": "Browser Agent",
    }.get(browser, browser)
    return f"{creator.name.strip() or '发布账号'} · {browser_label}"


def _social_auto_upload_binding_payload(
    *,
    creator: CreatorCard,
    platform: str,
    browser: str,
    account_name: str,
) -> dict[str, Any]:
    browser_profile_id = f"browser-agent:{browser}:{creator.id}:{platform}"
    return {
        "adapter": SOCIAL_AUTO_UPLOAD_ADAPTER,
        "account_name": account_name,
        "account_label": account_name,
        "platform_label": platform_label(platform),
        "browser": browser,
        "browser_profile_id": browser_profile_id,
        "browser_binding": {
            "browser": browser,
            "profile_id": browser_profile_id,
            "source": "creator_publication_management",
        },
        "enabled": True,
        "status": "login_reference_bound",
        "binding_source": "social_auto_upload_login_binding",
        "notes": "绑定 social-auto-upload 登录账号名；不保存平台密码、Cookie 或浏览器凭证。",
    }


async def _get_creator_or_404(session: AsyncSession, creator_id: uuid.UUID) -> CreatorCard:
    result = await session.execute(
        select(CreatorCard)
        .where(CreatorCard.id == creator_id)
        .options(
            selectinload(CreatorCard.assets),
            selectinload(CreatorCard.preferences),
        )
        .execution_options(populate_existing=True)
    )
    creator = result.scalar_one_or_none()
    if creator is None:
        raise HTTPException(status_code=404, detail="Creator card not found")
    return creator


async def _get_task_strategy_or_404(session: AsyncSession, strategy_id: uuid.UUID) -> CreatorTaskStrategy:
    result = await session.execute(
        select(CreatorTaskStrategy)
        .where(CreatorTaskStrategy.id == strategy_id)
        .options(selectinload(CreatorTaskStrategy.versions))
        .execution_options(populate_existing=True)
    )
    strategy = result.scalar_one_or_none()
    if strategy is None:
        raise HTTPException(status_code=404, detail="Task strategy not found")
    return strategy


async def _get_visual_plan_or_404(session: AsyncSession, visual_plan_id: uuid.UUID) -> CreatorVisualPlan:
    result = await session.execute(
        select(CreatorVisualPlan)
        .where(CreatorVisualPlan.id == visual_plan_id)
        .options(selectinload(CreatorVisualPlan.versions))
        .execution_options(populate_existing=True)
    )
    visual_plan = result.scalar_one_or_none()
    if visual_plan is None:
        raise HTTPException(status_code=404, detail="Visual plan not found")
    return visual_plan


async def _get_or_create_publication_profile(
    session: AsyncSession,
    creator: CreatorCard,
) -> CreatorPublicationProfile:
    async def _load() -> CreatorPublicationProfile | None:
        result = await session.execute(
            select(CreatorPublicationProfile)
            .where(CreatorPublicationProfile.creator_card_id == creator.id)
            .options(
                selectinload(CreatorPublicationProfile.bindings),
                selectinload(CreatorPublicationProfile.versions),
            )
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    profile = await _load()
    if profile is not None:
        normalized_payload = _normalize_publication_profile_payload(profile.publication_payload_json or {})
        collection_strategy = normalized_payload.get("collection_strategy")
        collection_rules = (
            collection_strategy.get("rules")
            if isinstance(collection_strategy, dict) and isinstance(collection_strategy.get("rules"), list)
            else []
        )
        has_natural_language_rules = any(
            isinstance(rule, dict) and str(rule.get("natural_language_rule") or "").strip()
            for rule in collection_rules
        )
        if "fas" in str(creator.name or "").strip().lower() and (
            "collection_strategy" not in (profile.publication_payload_json or {}) or not has_natural_language_rules
        ):
            default_strategy = _default_collection_strategy_for_creator(creator)
            normalized_payload = _normalize_publication_profile_payload(
                {
                    **normalized_payload,
                    "collection_strategy": _merge_fas_collection_strategy_defaults(
                        normalized_payload.get("collection_strategy"),
                        default_strategy,
                    ),
                }
            )
        if normalized_payload != (profile.publication_payload_json or {}):
            profile.publication_payload_json = normalized_payload
            await session.commit()
            loaded = await _load()
            assert loaded is not None
            return loaded
        return profile
    profile = CreatorPublicationProfile(
        creator_card_id=creator.id,
        publication_payload_json=_publication_payload(creator),
        status="draft",
    )
    session.add(profile)
    await session.flush()
    version = PublicationProfileVersion(
        publication_profile_id=profile.id,
        version=1,
        operation="generate",
        payload_json=profile.publication_payload_json,
    )
    session.add(version)
    await session.commit()
    loaded = await _load()
    assert loaded is not None
    return loaded


async def _next_version(
    session: AsyncSession,
    model: type[TaskStrategyVersion] | type[VisualPlanVersion] | type[PublicationProfileVersion],
    foreign_key_field: Any,
    foreign_key_value: uuid.UUID,
) -> int:
    result = await session.execute(
        select(func.max(model.version)).where(foreign_key_field == foreign_key_value)
    )
    return int(result.scalar() or 0) + 1


@router.get("", response_model=CreatorCardListOut)
async def list_creator_cards(session: AsyncSession = Depends(get_session)) -> CreatorCardListOut:
    await _sync_legacy_avatar_profiles(session)
    result = await session.execute(
        select(CreatorCard)
        .options(
            selectinload(CreatorCard.assets),
            selectinload(CreatorCard.preferences),
        )
        .order_by(CreatorCard.updated_at.desc())
    )
    creators = list(result.scalars().unique())
    if _repair_creator_assets_storage_paths([asset for creator in creators for asset in creator.assets]):
        await session.commit()
    return CreatorCardListOut(items=creators)


@router.post("", response_model=CreatorCardOut, status_code=status.HTTP_201_CREATED)
async def create_creator_card(body: CreatorCardIn, session: AsyncSession = Depends(get_session)) -> CreatorCard:
    await _sync_legacy_avatar_profiles(session)
    total = (
        await session.execute(select(func.count()).select_from(CreatorCard))
    ).scalar_one()
    if int(total or 0) >= MAX_CREATOR_CARDS:
        raise HTTPException(status_code=400, detail=f"最多只能保存 {MAX_CREATOR_CARDS} 个创作者卡片")
    creator = CreatorCard(**body.model_dump())
    session.add(creator)
    await session.commit()
    return await _get_creator_or_404(session, creator.id)


@router.get("/{creator_id}", response_model=CreatorCardOut)
async def get_creator_card(creator_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> CreatorCard:
    creator = await _get_creator_or_404(session, creator_id)
    if _repair_creator_assets_storage_paths(list(creator.assets)):
        await session.commit()
        creator = await _get_creator_or_404(session, creator_id)
    return creator


@router.patch("/{creator_id}", response_model=CreatorCardOut)
async def patch_creator_card(
    creator_id: uuid.UUID,
    body: CreatorCardPatch,
    session: AsyncSession = Depends(get_session),
) -> CreatorCard:
    creator = await _get_creator_or_404(session, creator_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(creator, key, value)
    await session.commit()
    return await _get_creator_or_404(session, creator_id)


@router.delete("/{creator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_creator_card(creator_id: uuid.UUID, session: AsyncSession = Depends(get_session)) -> None:
    creator = await _get_creator_or_404(session, creator_id)
    await session.delete(creator)
    await session.commit()


@router.post("/{creator_id}/assets", response_model=CreatorCardOut, status_code=status.HTTP_201_CREATED)
async def upload_creator_asset(
    creator_id: uuid.UUID,
    file: UploadFile = File(...),
    asset_type: str | None = Form(default=None),
    session: AsyncSession = Depends(get_session),
) -> CreatorCard:
    creator = await _get_creator_or_404(session, creator_id)
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    asset_id = uuid.uuid4()
    target_dir = _creator_asset_dir(creator.id)
    target_path = target_dir / f"{asset_id}-{_sanitize_filename(file.filename or 'asset.bin')}"
    target_path.write_bytes(payload)
    normalized_asset_type = (asset_type or "").strip() or (file.content_type or "application/octet-stream").split("/")[0]
    asset = CreatorAsset(
        id=asset_id,
        creator_card_id=creator.id,
        asset_type=normalized_asset_type,
        original_name=file.filename or "asset.bin",
        stored_path=target_path.as_posix(),
        metadata_json={
            "content_type": file.content_type,
            "size_bytes": len(payload),
            "asset_type_source": "user_selected" if asset_type else "content_type",
        },
    )
    session.add(asset)
    await session.commit()
    return await _get_creator_or_404(session, creator.id)


@router.delete("/{creator_id}/assets/{asset_id}", response_model=CreatorCardOut)
async def delete_creator_asset(
    creator_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorCard:
    await _get_creator_or_404(session, creator_id)
    asset = await session.get(CreatorAsset, asset_id)
    if asset is None or asset.creator_card_id != creator_id:
        raise HTTPException(status_code=404, detail="Creator asset not found")
    try:
        resolve_creator_asset_path(asset.stored_path).unlink(missing_ok=True)
    except OSError:
        pass
    await session.delete(asset)
    await session.commit()
    return await _get_creator_or_404(session, creator_id)


@router.get("/{creator_id}/assets/{asset_id}/file")
async def get_creator_asset_file(
    creator_id: uuid.UUID,
    asset_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    await _get_creator_or_404(session, creator_id)
    asset = await session.get(CreatorAsset, asset_id)
    if asset is None or asset.creator_card_id != creator_id:
        raise HTTPException(status_code=404, detail="Creator asset not found")
    path = resolve_creator_asset_path(asset.stored_path)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Creator asset file not found")
    if _repair_creator_asset_storage_path(asset):
        await session.commit()
    content_type = str((asset.metadata_json or {}).get("content_type") or "application/octet-stream")
    return FileResponse(path, media_type=content_type, filename=asset.original_name)


@router.post("/{creator_id}/refine", response_model=CreatorCardOut)
async def refine_creator_card(
    creator_id: uuid.UUID,
    body: CreatorCardRefineIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorCard:
    creator = await _get_creator_or_404(session, creator_id)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    patch, refine_meta = await _build_creator_refine_patch(creator, prompt)
    blocking_reasons = creator_refine_output_fallback_reasons(refine_meta)
    if blocking_reasons:
        raise HTTPException(
            status_code=503,
            detail=(
                "creator refine produced a fallback result and was blocked from mutating the production card: "
                + ", ".join(blocking_reasons)
            ),
        )
    if "name" in patch:
        creator.name = patch["name"]
        creator.natural_language_profile = _strip_public_name_lines(creator.natural_language_profile)
    if "positioning" in patch:
        creator.positioning = patch["positioning"]
    if "audience" in patch:
        creator.audience = patch["audience"]
    if "content_domains" in patch:
        creator.content_domains = patch["content_domains"]
    if "default_platforms" in patch:
        creator.default_platforms = patch["default_platforms"]
    if "natural_language_profile" in patch:
        existing = _strip_public_name_lines(creator.natural_language_profile)
        incoming = _strip_public_name_lines(patch["natural_language_profile"])
        creator.natural_language_profile = "\n\n".join(
            part for part in [existing, incoming] if part
        ) or None
    preference_version = (
        len(creator.preferences) + 1
        if creator.preferences
        else 1
    )
    session.add(
        CreatorPreference(
            creator_card_id=creator.id,
            preference_type=body.preference_type,
            natural_language_rule=prompt,
            structured_payload={"applied_patch": patch, "agent": refine_meta},
            source="agent_refine",
            version=preference_version,
        )
    )
    await session.commit()
    return await _get_creator_or_404(session, creator_id)


@router.get("/{creator_id}/task-strategies", response_model=CreatorTaskStrategyListOut)
async def list_task_strategies(
    creator_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorTaskStrategyListOut:
    await _get_creator_or_404(session, creator_id)
    result = await session.execute(
        select(CreatorTaskStrategy)
        .where(CreatorTaskStrategy.creator_card_id == creator_id)
        .options(selectinload(CreatorTaskStrategy.versions))
        .order_by(CreatorTaskStrategy.updated_at.desc())
    )
    return CreatorTaskStrategyListOut(items=list(result.scalars().unique()))


@router.post("/{creator_id}/task-strategies/generate", response_model=CreatorTaskStrategyListOut)
async def generate_task_strategies(
    creator_id: uuid.UUID,
    body: TaskStrategyGenerateIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorTaskStrategyListOut:
    creator = await _get_creator_or_404(session, creator_id)
    count = min(max(body.candidate_count, 1), 4)
    prompt = body.prompt.strip()
    summary = f"根据「{prompt}」生成的候选任务策略。" if prompt else "基于创作者卡片直接生成的候选任务策略。"
    existing_result = await session.execute(
        select(CreatorTaskStrategy)
        .where(CreatorTaskStrategy.creator_card_id == creator.id)
        .options(selectinload(CreatorTaskStrategy.versions))
    )
    for existing in existing_result.scalars().unique():
        await session.delete(existing)
    await session.flush()
    for index in range(count):
        payload = _strategy_payload(prompt, creator, index, body.strategy_type)
        strategy = CreatorTaskStrategy(
            creator_card_id=creator.id,
            name=str(payload["name"]),
            strategy_type=body.strategy_type,
            summary=summary,
            strategy_payload_json=payload,
            status="candidate",
            is_active=index == 0,
        )
        session.add(strategy)
        await session.flush()
        session.add(
            TaskStrategyVersion(
                strategy_id=strategy.id,
                version=1,
                operation="generate",
                prompt=prompt,
                payload_json=payload,
            )
        )
    await session.commit()
    return await list_task_strategies(creator_id, session)


@router.post("/task-strategies/{strategy_id}/refine", response_model=CreatorTaskStrategyOut)
async def refine_task_strategy(
    strategy_id: uuid.UUID,
    body: TaskStrategyRefineIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorTaskStrategy:
    strategy = await _get_task_strategy_or_404(session, strategy_id)
    payload = dict(strategy.strategy_payload_json or {})
    payload["refine_prompt"] = body.prompt.strip()
    payload.setdefault("rules", [])
    payload["rules"] = [*payload["rules"], f"调整要求：{body.prompt.strip()}"]
    strategy.strategy_payload_json = payload
    strategy.summary = f"{strategy.summary or strategy.name}\n调整：{body.prompt.strip()}".strip()
    strategy.status = "refined"
    next_version = await _next_version(session, TaskStrategyVersion, TaskStrategyVersion.strategy_id, strategy.id)
    session.add(
        TaskStrategyVersion(
            strategy_id=strategy.id,
            version=next_version,
            operation="refine",
            prompt=body.prompt.strip(),
            payload_json=payload,
        )
    )
    await session.commit()
    return await _get_task_strategy_or_404(session, strategy_id)


@router.post("/task-strategies/{strategy_id}/activate", response_model=CreatorTaskStrategyOut)
async def activate_task_strategy(
    strategy_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorTaskStrategy:
    strategy = await _get_task_strategy_or_404(session, strategy_id)
    result = await session.execute(
        select(CreatorTaskStrategy).where(CreatorTaskStrategy.creator_card_id == strategy.creator_card_id)
    )
    for item in result.scalars():
        item.is_active = item.id == strategy.id
    strategy.status = "active"
    await session.commit()
    return await _get_task_strategy_or_404(session, strategy_id)


@router.get("/task-strategies/{strategy_id}/versions", response_model=list[PlanVersionOut])
async def list_task_strategy_versions(
    strategy_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[TaskStrategyVersion]:
    strategy = await _get_task_strategy_or_404(session, strategy_id)
    return list(strategy.versions)


@router.get("/{creator_id}/visual-plans", response_model=CreatorVisualPlanListOut)
async def list_visual_plans(
    creator_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorVisualPlanListOut:
    await _get_creator_or_404(session, creator_id)
    result = await session.execute(
        select(CreatorVisualPlan)
        .where(CreatorVisualPlan.creator_card_id == creator_id)
        .options(selectinload(CreatorVisualPlan.versions))
        .order_by(CreatorVisualPlan.updated_at.desc())
    )
    return CreatorVisualPlanListOut(items=list(result.scalars().unique()))


@router.post("/{creator_id}/visual-plans/generate", response_model=CreatorVisualPlanListOut)
async def generate_visual_plans(
    creator_id: uuid.UUID,
    body: VisualPlanGenerateIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorVisualPlanListOut:
    creator = await _get_creator_or_404(session, creator_id)
    count = min(max(body.candidate_count, 1), 4)
    prompt = body.prompt.strip()
    summary = f"根据「{prompt}」生成的候选视觉方向。" if prompt else "基于创作者卡片直接生成的候选视觉方向。"
    existing_result = await session.execute(
        select(CreatorVisualPlan)
        .where(CreatorVisualPlan.creator_card_id == creator.id)
        .options(selectinload(CreatorVisualPlan.versions))
    )
    for existing in existing_result.scalars().unique():
        await session.delete(existing)
    await session.flush()
    for index in range(count):
        payload = _visual_payload(prompt, creator, index)
        visual_plan = CreatorVisualPlan(
            creator_card_id=creator.id,
            name=str(payload["name"]),
            summary=summary,
            visual_payload_json=payload,
            status="candidate",
            is_active=index == 0,
        )
        session.add(visual_plan)
        await session.flush()
        session.add(
            VisualPlanVersion(
                visual_plan_id=visual_plan.id,
                version=1,
                operation="generate",
                prompt=prompt,
                payload_json=payload,
            )
        )
    await session.commit()
    return await list_visual_plans(creator_id, session)


@router.post("/visual-plans/{visual_plan_id}/refine", response_model=CreatorVisualPlanOut)
async def refine_visual_plan(
    visual_plan_id: uuid.UUID,
    body: VisualPlanRefineIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorVisualPlan:
    visual_plan = await _get_visual_plan_or_404(session, visual_plan_id)
    payload = dict(visual_plan.visual_payload_json or {})
    payload["agent_reason"] = body.prompt.strip()
    payload["copy_tone"] = body.prompt.strip()
    visual_plan.visual_payload_json = payload
    visual_plan.summary = f"{visual_plan.summary or visual_plan.name}\n调整：{body.prompt.strip()}".strip()
    visual_plan.status = "refined"
    next_version = await _next_version(session, VisualPlanVersion, VisualPlanVersion.visual_plan_id, visual_plan.id)
    session.add(
        VisualPlanVersion(
            visual_plan_id=visual_plan.id,
            version=next_version,
            operation="refine",
            prompt=body.prompt.strip(),
            payload_json=payload,
        )
    )
    await session.commit()
    return await _get_visual_plan_or_404(session, visual_plan_id)


@router.post("/visual-plans/{visual_plan_id}/activate", response_model=CreatorVisualPlanOut)
async def activate_visual_plan(
    visual_plan_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorVisualPlan:
    visual_plan = await _get_visual_plan_or_404(session, visual_plan_id)
    result = await session.execute(
        select(CreatorVisualPlan).where(CreatorVisualPlan.creator_card_id == visual_plan.creator_card_id)
    )
    for item in result.scalars():
        item.is_active = item.id == visual_plan.id
    visual_plan.status = "active"
    await session.commit()
    return await _get_visual_plan_or_404(session, visual_plan_id)


@router.get("/visual-plans/{visual_plan_id}/versions", response_model=list[PlanVersionOut])
async def list_visual_plan_versions(
    visual_plan_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[VisualPlanVersion]:
    visual_plan = await _get_visual_plan_or_404(session, visual_plan_id)
    return list(visual_plan.versions)


@router.get("/{creator_id}/publication-profile", response_model=CreatorPublicationProfileOut)
async def get_publication_profile(
    creator_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    return await _get_or_create_publication_profile(session, creator)


@router.patch("/{creator_id}/publication-profile", response_model=CreatorPublicationProfileOut)
async def patch_publication_profile(
    creator_id: uuid.UUID,
    body: PublicationProfilePatch,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    profile = await _get_or_create_publication_profile(session, creator)
    if body.status is not None:
        profile.status = body.status
    if body.publication_payload_json is not None:
        merged_payload = {
            **(profile.publication_payload_json or {}),
            **body.publication_payload_json,
        }
        profile.publication_payload_json = _normalize_publication_profile_payload(merged_payload)
        next_version = await _next_version(
            session,
            PublicationProfileVersion,
            PublicationProfileVersion.publication_profile_id,
            profile.id,
        )
        session.add(
            PublicationProfileVersion(
                publication_profile_id=profile.id,
                version=next_version,
                operation="patch",
                payload_json=profile.publication_payload_json,
            )
        )
    await session.commit()
    return await _get_or_create_publication_profile(session, creator)


@router.post("/{creator_id}/publication-profile/refine", response_model=CreatorPublicationProfileOut)
async def refine_publication_profile(
    creator_id: uuid.UUID,
    body: PublicationProfileRefineIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    profile = await _get_or_create_publication_profile(session, creator)
    payload = dict(profile.publication_payload_json or {})
    payload["agent_reason"] = body.prompt.strip()
    profile.publication_payload_json = payload
    profile.status = "refined"
    next_version = await _next_version(
        session,
        PublicationProfileVersion,
        PublicationProfileVersion.publication_profile_id,
        profile.id,
    )
    session.add(
        PublicationProfileVersion(
            publication_profile_id=profile.id,
            version=next_version,
            operation="refine",
            prompt=body.prompt.strip(),
            payload_json=payload,
        )
    )
    await session.commit()
    return await _get_or_create_publication_profile(session, creator)


@router.post("/{creator_id}/platform-bindings", response_model=CreatorPublicationProfileOut)
async def add_platform_binding(
    creator_id: uuid.UUID,
    body: CreatorPlatformBindingIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    profile = await _get_or_create_publication_profile(session, creator)
    platform = _normalize_creator_platform_or_400(body.platform)
    result = await session.execute(
        select(CreatorPlatformBinding).where(
            CreatorPlatformBinding.publication_profile_id == profile.id,
            CreatorPlatformBinding.platform == platform,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        binding = CreatorPlatformBinding(
            publication_profile_id=profile.id,
            platform=platform,
        )
        session.add(binding)
    binding.credential_ref = body.credential_ref
    binding.binding_payload_json = body.binding_payload_json
    await session.commit()
    return await _get_or_create_publication_profile(session, creator)


@router.post("/{creator_id}/platform-bindings/social-auto-upload", response_model=CreatorPublicationProfileOut)
async def bind_social_auto_upload_login(
    creator_id: uuid.UUID,
    body: CreatorSocialAutoUploadBindingIn,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    platform = _normalize_creator_platform_or_400(body.platform)
    if not supports_social_auto_upload_platform(platform):
        raise HTTPException(status_code=400, detail=f"{platform_label(platform)} 暂不支持 social-auto-upload 登录绑定。")
    browser = _normalize_publication_browser_or_400(body.browser)
    account_name = _social_auto_upload_account_name(creator, browser, body.account_name)
    profile = await _get_or_create_publication_profile(session, creator)
    result = await session.execute(
        select(CreatorPlatformBinding).where(
            CreatorPlatformBinding.publication_profile_id == profile.id,
            CreatorPlatformBinding.platform == platform,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        binding = CreatorPlatformBinding(
            publication_profile_id=profile.id,
            platform=platform,
        )
        session.add(binding)
    binding.credential_ref = f"social-auto-upload:{account_name}:{platform}"
    binding.binding_payload_json = _social_auto_upload_binding_payload(
        creator=creator,
        platform=platform,
        browser=browser,
        account_name=account_name,
    )
    await session.commit()
    return await _get_or_create_publication_profile(session, creator)


@router.delete("/{creator_id}/platform-bindings/{platform}", response_model=CreatorPublicationProfileOut)
async def delete_platform_binding(
    creator_id: uuid.UUID,
    platform: str,
    session: AsyncSession = Depends(get_session),
) -> CreatorPublicationProfile:
    creator = await _get_creator_or_404(session, creator_id)
    profile = await _get_or_create_publication_profile(session, creator)
    normalized_platform = _normalize_creator_platform_or_400(platform)
    result = await session.execute(
        select(CreatorPlatformBinding).where(
            CreatorPlatformBinding.publication_profile_id == profile.id,
            CreatorPlatformBinding.platform == normalized_platform,
        )
    )
    binding = result.scalar_one_or_none()
    if binding is None:
        raise HTTPException(status_code=404, detail="Platform binding not found")
    await session.delete(binding)
    await session.commit()
    return await _get_or_create_publication_profile(session, creator)
