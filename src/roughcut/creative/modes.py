from __future__ import annotations

from copy import deepcopy
from typing import Final

DEFAULT_WORKFLOW_MODE: Final[str] = "standard_edit"
DEFAULT_LIVE_BATCH_ENHANCEMENT_MODES: Final[tuple[str, ...]] = (
    "auto_review",
    "avatar_commentary",
    "ai_effects",
)

_WORKFLOW_MODES: Final[dict[str, dict[str, object]]] = {
    "standard_edit": {
        "key": "standard_edit",
        "kind": "workflow",
        "status": "active",
        "title": "标准成片",
        "tagline": "以已有视频为源素材，完成分析、粗剪、包装和输出。",
        "summary": "适用于现有 RoughCut 主流程，先把增强能力挂到标准成片之上。",
        "suitable_for": ["已有口播视频", "录屏教程", "开箱测评", "新闻讲述"],
        "pipeline_outline": [
            "读取源视频并完成转写、字幕后处理",
            "生成内容画像、剪辑决策和包装计划",
            "根据可选增强能力叠加数字人或 AI 导演策略",
        ],
        "delivery_scope": "立即可用于任务创建",
    },
    "long_text_to_video": {
        "key": "long_text_to_video",
        "kind": "workflow",
        "status": "planned",
        "title": "长文本转视频",
        "tagline": "根据长文脚本自动拆分章节、检索素材、配音并生成长视频。",
        "summary": "这是独立流水线，不继续复用当前“已有视频粗剪”主链路，先做规划和接口占位。",
        "suitable_for": ["公众号长文", "科普脚本", "商业解读", "叙事型播客改编"],
        "pipeline_outline": [
            "长文本章节拆分、镜头脚本化和素材检索",
            "按风格路由素材库，生成长视频镜头序列",
            "结合 TTS、字幕和转场输出完整长视频",
        ],
        "delivery_scope": "规划中，暂不开放任务创建",
    },
}

_ENHANCEMENT_MODES: Final[dict[str, dict[str, object]]] = {
    "multilingual_translation": {
        "key": "multilingual_translation",
        "kind": "enhancement",
        "status": "active",
        "title": "多语言翻译",
        "tagline": "在字幕完整校对后生成多语言字幕版本，默认先产出英文译文。",
        "summary": "翻译步骤会放在字幕纠错之后，优先使用校正后的字幕文本做多语言输出，降低术语和品牌误译概率。",
        "suitable_for": ["海外分发", "双语字幕", "英文版视频包装", "后续多语言再创作"],
        "pipeline_outline": [
            "先完成字幕后处理与术语纠错，拿到较干净的中文字幕",
            "基于校正后的字幕生成英文译文，后续可扩展更多目标语言",
            "将译文作为独立 artifact 保留，供包装、出海分发和再创作使用",
        ],
        "providers": ["内置推理模型", "OpenAI 兼容推理接口", "MiniMax 兼容推理接口"],
        "default_delivery": "默认生成英文字幕版本，后续可扩展语言选择",
    },
    "auto_review": {
        "key": "auto_review",
        "kind": "enhancement",
        "status": "active",
        "title": "异常门自动放行",
        "tagline": "默认全自动跑完，只在内容、字幕或质量门发现阻塞异常时暂停。",
        "summary": "内容画像与成片核对不再作为常规人工节点；低置信度进入自动质量复跑，阻塞异常才进入人工处理。",
        "suitable_for": ["稳定栏目", "高重复结构任务", "批量值班自动剪辑", "夜间无人值守任务"],
        "pipeline_outline": [
            "完成内容画像后评估阻塞原因",
            "未命中阻塞异常时自动确认摘要并续跑后续步骤",
            "命中字幕语义污染、主体冲突或质量门阻塞时保留人工处理入口",
        ],
        "providers": ["内置摘要审核规则"],
        "default_delivery": "默认行为是异常才停；该模式用于显式展示自动放行状态",
    },
    "multi_platform_adaptation": {
        "key": "multi_platform_adaptation",
        "kind": "enhancement",
        "status": "active",
        "title": "多平台版本适配",
        "tagline": "按平台安全区、标题结构和发布文案差异，输出更适合分发的多平台版本。",
        "summary": "复用当前已有的平台包装、标题生成和画面安全区策略，把同一条内容适配成更适合 B 站、小红书、抖音等不同平台分发的版本。",
        "suitable_for": ["一稿多发", "平台矩阵运营", "同题多版本发布", "需要兼顾不同平台阅读习惯的内容"],
        "pipeline_outline": [
            "复用已有内容画像、标题和包装信息，识别平台差异点",
            "按平台安全区、标题风格和文案偏好生成适配版本",
            "输出多平台发布文案与更稳妥的成片呈现方案",
        ],
        "providers": ["平台文案生成", "包装安全区策略", "现有渲染参数适配"],
        "default_delivery": "已可接入默认配置，用于统一控制多平台适配输出",
    },
    "avatar_commentary": {
        "key": "avatar_commentary",
        "kind": "enhancement",
        "status": "active",
        "title": "数字人解说",
        "tagline": "在任意成片里合成画中画或串场解说位，补足镜头存在感和信息密度。",
        "summary": "支持用户设定数字人形象，适配 HeyGem 或其他在线数字人 API。",
        "suitable_for": ["解说补充", "知识讲解", "品牌代言口播", "无真人出镜内容"],
        "pipeline_outline": [
            "定义数字人形象、机位模板和出镜规则",
            "按时间轴生成数字人口播片段并合成画中画",
            "必要时与原字幕、包装元素重新排版避免遮挡",
        ],
        "providers": ["HeyGem", "其他数字人 API"],
        "default_delivery": "先完成配置透传、任务挂载和方案展示",
    },
    "ai_effects": {
        "key": "ai_effects",
        "kind": "enhancement",
        "status": "active",
        "title": "智能剪辑特效",
        "tagline": "基于时间线和内容节奏自动加入转场、镜头强化、强调动画和局部视觉特效。",
        "summary": "适合作为标准成片上的额外视觉增强层，优先服务节奏强化、爆点表达和镜头情绪推进。",
        "suitable_for": ["开箱测评", "高能混剪", "知识重点强化", "情绪节奏增强"],
        "pipeline_outline": [
            "识别可加特效的镜头边界、爆点词和节奏变化",
            "在不破坏主叙事的前提下补充转场、强调动画和局部视觉强化",
            "与包装、字幕和数字人口播协同，避免互相遮挡或节奏冲突",
        ],
        "providers": ["FFmpeg", "内置模板效果", "后续扩展视觉模型"],
        "default_delivery": "先完成模式挂载和审核入口，再逐步补具体特效策略",
    },
    "ai_director": {
        "key": "ai_director",
        "kind": "enhancement",
        "status": "active",
        "title": "AI 导演",
        "tagline": "基于画面、题材和原台词结构自动润色、补叙或重配音，提升逻辑与情绪。",
        "summary": "可做台词校正、桥段补强、语气优化与配音重建，强调爆款叙事方法论。",
        "suitable_for": ["知识科普", "故事化旁白", "剧情剪辑", "信息密度不足的视频"],
        "pipeline_outline": [
            "识别原台词结构、镜头节奏和视频题材",
            "生成改写建议、补充信息点和情绪桥段",
            "用 IndexTTS2、RunningHub 或其他真实语音克隆服务完成重配音并回贴时间线",
        ],
        "providers": ["IndexTTS2", "RunningHub API", "其他语音克隆 API"],
        "default_delivery": "先完成模式建模、任务挂载和后续提示词上下文注入",
    },
}


def build_active_workflow_mode_options() -> list[dict[str, str]]:
    return [
        {"value": mode["key"], "label": str(mode["title"])}
        for mode in _WORKFLOW_MODES.values()
        if mode["status"] == "active"
    ]


def build_active_enhancement_mode_options() -> list[dict[str, str]]:
    return [
        {"value": mode["key"], "label": str(mode["title"])}
        for mode in _ENHANCEMENT_MODES.values()
        if mode["status"] == "active"
    ]


def build_mode_catalog() -> dict[str, list[dict[str, object]]]:
    return {
        "workflow_modes": [deepcopy(mode) for mode in _WORKFLOW_MODES.values()],
        "enhancement_modes": [deepcopy(mode) for mode in _ENHANCEMENT_MODES.values()],
    }


def normalize_workflow_mode(value: str | None, *, allow_planned: bool = False) -> str:
    normalized = str(value or DEFAULT_WORKFLOW_MODE).strip() or DEFAULT_WORKFLOW_MODE
    mode = _WORKFLOW_MODES.get(normalized)
    if mode is None:
        raise ValueError(f"Unsupported workflow_mode: {normalized}")
    if not allow_planned and mode["status"] != "active":
        raise ValueError(f"workflow_mode not available yet: {normalized}")
    return normalized


def normalize_enhancement_modes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if not values:
        return []
    normalized_items: list[str] = []
    seen: set[str] = set()
    for raw in values:
        normalized = str(raw or "").strip()
        if not normalized:
            continue
        mode = _ENHANCEMENT_MODES.get(normalized)
        if mode is None or mode["status"] != "active":
            raise ValueError(f"Unsupported enhancement_mode: {normalized}")
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_items.append(normalized)
    return normalized_items


def resolve_live_batch_enhancement_modes(values: list[str] | tuple[str, ...] | None) -> list[str]:
    if values:
        return normalize_enhancement_modes(values)
    return list(DEFAULT_LIVE_BATCH_ENHANCEMENT_MODES)


def auto_review_mode_enabled(enhancement_modes: list[str] | tuple[str, ...] | None) -> bool:
    return "auto_review" in set(enhancement_modes or [])


def multilingual_translation_mode_enabled(enhancement_modes: list[str] | tuple[str, ...] | None) -> bool:
    return "multilingual_translation" in set(enhancement_modes or [])


def build_job_creative_profile(*, workflow_mode: str, enhancement_modes: list[str]) -> dict[str, object]:
    workflow_key = normalize_workflow_mode(workflow_mode, allow_planned=True)
    enhancement_keys = normalize_enhancement_modes(enhancement_modes)
    workflow = deepcopy(_WORKFLOW_MODES[workflow_key])
    enhancements = [deepcopy(_ENHANCEMENT_MODES[key]) for key in enhancement_keys]
    execution_state = "active" if workflow.get("status") == "active" else "planned"
    return {
        "workflow_mode": workflow_key,
        "workflow": workflow,
        "enhancement_modes": enhancement_keys,
        "enhancements": enhancements,
        "execution_state": execution_state,
        "implementation_notes": [
            "长文本转视频当前只保留方案与接口占位，不进入现有已有视频主流程。",
            "异常门自动放行、多平台版本适配、数字人解说、智能剪辑特效与 AI 导演当前作为通用增强能力挂载到标准成片任务。",
            "TTS 方案优先支持 IndexTTS2 与 RunningHub 这类真实服务。",
            "素材库策略要求走较新素材，不使用老旧缓存素材。",
        ],
    }
