from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from roughcut.config import llm_task_route
from roughcut.llm_cache import digest_payload
from roughcut.providers.factory import get_reasoning_provider, get_search_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_profile_memory import merge_content_profile_creative_preferences
from roughcut.usage import track_usage_operation

_PLATFORM_FACT_SHEET_CACHE_VERSION = "2026-04-03.fact-sheet.v2"
_PLATFORM_PACKAGE_CACHE_VERSION = "2026-04-03.generate.v2"

PLATFORM_ORDER = [
    ("bilibili", "B站", "简介", "标签"),
    ("xiaohongshu", "小红书", "正文", "话题"),
    ("douyin", "抖音", "简介", "标签"),
    ("kuaishou", "快手", "简介", "标签"),
    ("wechat_channels", "视频号", "简介", "标签"),
    ("toutiao", "头条号", "简介", "标签"),
    ("youtube", "YouTube", "描述", "标签"),
    ("x", "X", "推文", "Hashtags"),
]

_TITLE_AUDIT_VERSION = "2026-04-10.title-audit.v1"
_TITLE_ANGLE_PATTERNS = (
    ("question", re.compile(r"[？?]|怎么|值不值|要不要|到底|买吗|如何|选哪|选谁")),
    ("emotion", re.compile(r"终于|真香|封神|上头|离谱|惊到|杀疯|爽飞|感动|等了很久")),
    ("conclusion", re.compile(r"结论|建议|劝退|推荐|不推荐|可买|别买|直说|实话")),
    ("explosive", re.compile(r"直接|居然|原来|先看|一条|炸场|太狠|暴击|开箱")),
    ("informational", re.compile(r"实测|对比|体验|评测|细节|拆解|记录|总结|重点|判断")),
)
_TITLE_AUDIT_RULES: dict[str, dict[str, Any]] = {
    "bilibili": {
        "label": "B站",
        "hard_max_chars": 80,
        "recommended_min_chars": 10,
        "recommended_max_chars": 30,
        "display_max_chars": 30,
        "max_emojis": 0,
        "max_exclamations": 1,
        "style_hint": "偏信息密度和搜索友好，最好带主体、判断或问题角度。",
        "audience_hint": "用户更愿意点开能快速判断主题、差异和结论的信息型标题。",
        "preferred_tokens": ("开箱", "实测", "对比", "评测", "体验", "细节", "值不值", "怎么选", "总结", "判断"),
        "avoid_tokens": ("绝绝子", "yyds", "杀疯", "封神"),
    },
    "xiaohongshu": {
        "label": "小红书",
        "hard_max_chars": 20,
        "recommended_min_chars": 8,
        "recommended_max_chars": 20,
        "display_max_chars": 20,
        "max_emojis": 2,
        "max_exclamations": 1,
        "style_hint": "偏真实分享、到手感受和审美表达，适合像笔记标题。",
        "audience_hint": "用户更吃“到手体验、细节感受、种草/劝退”这类生活化表达。",
        "preferred_tokens": ("到手", "分享", "开箱", "细节", "质感", "记录", "真的", "被", "种草", "劝退", "值不值"),
        "avoid_tokens": ("官方公告", "技术白皮书"),
    },
    "douyin": {
        "label": "抖音",
        "hard_max_chars": 55,
        "recommended_min_chars": 6,
        "recommended_max_chars": 22,
        "display_max_chars": 22,
        "max_emojis": 1,
        "max_exclamations": 1,
        "style_hint": "偏短促直给，先给结果或最强记忆点。",
        "audience_hint": "用户更容易被强钩子、结果先行、节奏快的标题带进播放。",
        "preferred_tokens": ("直接", "到底", "值不值", "结果", "真相", "先看", "一条", "开箱", "居然", "原来"),
        "avoid_tokens": ("长文解析", "慢慢聊", "完整白皮书"),
    },
    "kuaishou": {
        "label": "快手",
        "hard_max_chars": None,
        "recommended_min_chars": 6,
        "recommended_max_chars": 26,
        "display_max_chars": 26,
        "max_emojis": 1,
        "max_exclamations": 1,
        "style_hint": "偏直给、口语化、像当面把真实体验讲明白。",
        "audience_hint": "用户更偏好有实话感、少包装、能马上知道你想说什么的标题。",
        "preferred_tokens": ("给你们看", "真东西", "实话", "直说", "值不值", "到底", "不整虚的", "咱"),
        "avoid_tokens": ("封神", "杂志感", "氛围感大片"),
    },
    "wechat_channels": {
        "label": "视频号",
        "hard_max_chars": None,
        "recommended_min_chars": 6,
        "recommended_max_chars": 16,
        "display_max_chars": 20,
        "max_emojis": 0,
        "max_exclamations": 1,
        "style_hint": "偏稳妥、可信、总结式，少一点网感黑话。",
        "audience_hint": "用户更偏好结论清楚、重点明确、方便快速判断是否值得看的标题。",
        "preferred_tokens": ("总结", "结论", "实测", "体验", "判断", "开箱", "值不值", "怎么选", "重点", "记录"),
        "avoid_tokens": ("封神", "炸裂", "杀疯", "绝绝子", "离谱"),
    },
    "toutiao": {
        "label": "头条号",
        "hard_max_chars": 30,
        "recommended_min_chars": 10,
        "recommended_max_chars": 28,
        "display_max_chars": 28,
        "max_emojis": 0,
        "max_exclamations": 1,
        "style_hint": "偏信息摘要和判断导向，适合把核心结论放前面。",
        "audience_hint": "用户更关注主题是否清楚、结论是否明确、信息是否够直给。",
        "preferred_tokens": ("开箱", "实测", "评测", "体验", "结论", "判断", "值不值", "对比"),
        "avoid_tokens": ("绝绝子", "封神", "杀疯"),
    },
    "youtube": {
        "label": "YouTube",
        "hard_max_chars": 100,
        "recommended_min_chars": 18,
        "recommended_max_chars": 70,
        "display_max_chars": 70,
        "max_emojis": 0,
        "max_exclamations": 1,
        "style_hint": "更适合信息明确、可检索、带主题和结论的标题。",
        "audience_hint": "用户会先扫主体、差异、结论和关键词，过于网感的中文爆词不稳定。",
        "preferred_tokens": ("review", "unboxing", "test", "hands-on", "体验", "评测", "开箱", "实测"),
        "avoid_tokens": ("绝绝子", "杀疯", "封神"),
    },
    "x": {
        "label": "X",
        "hard_max_chars": 50,
        "recommended_min_chars": 8,
        "recommended_max_chars": 28,
        "display_max_chars": 28,
        "max_emojis": 0,
        "max_exclamations": 1,
        "style_hint": "更像贴文开头句，短促、可转发、先给信息点。",
        "audience_hint": "用户更容易接受一句判断或一个明确观察，不适合堆太多修饰。",
        "preferred_tokens": ("实测", "结论", "观察", "体验", "先看", "quick take", "hands-on"),
        "avoid_tokens": ("长文解析", "绝绝子", "封神"),
    },
}

_CN_PLATFORM_KEYS = {"bilibili", "xiaohongshu", "douyin", "kuaishou", "wechat_channels", "toutiao"}
_BRAND_CN_ALIASES = {
    "OLIGHT": "傲雷",
    "Olight": "傲雷",
    "LEATHERMAN": "莱泽曼",
    "REATE": "锐特",
}


def build_transcript_for_packaging(subtitle_items: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    for item in subtitle_items:
        text = (item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        lines.append(f"[{item.get('start_time', 0):.1f}-{item.get('end_time', 0):.1f}] {text}")
    if not lines:
        return ""

    full_text = "\n".join(lines)
    if len(full_text) <= max_chars:
        return full_text

    section_size = max(1, len(lines) // 3)
    sections = [
        lines[:section_size],
        lines[max(0, len(lines) // 2 - section_size // 2): len(lines) // 2 + (section_size + 1) // 2],
        list(reversed(lines[-section_size:])),
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    total = 0
    max_section_len = max(len(section) for section in sections)
    for index in range(max_section_len):
        for section in sections:
            if index >= len(section):
                continue
            line = section[index]
            if line in seen:
                continue
            projected = total + len(line) + (1 if deduped else 0)
            if projected > max_chars:
                return "\n".join(deduped)
            seen.add(line)
            deduped.append(line)
            total = projected
    return "\n".join(deduped)


def build_packaging_prompt_brief(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    max_transcript_chars: int = 2200,
) -> dict[str, Any]:
    profile = content_profile or {}
    cover_title = profile.get("cover_title") if isinstance(profile.get("cover_title"), dict) else {}
    resolved_feedback = _resolved_review_feedback_payload(profile)
    creative_preferences = merge_content_profile_creative_preferences(profile)
    return {
        "source_name": source_name,
        "subject_brand": str(profile.get("subject_brand") or "").strip(),
        "subject_model": str(profile.get("subject_model") or "").strip(),
        "subject_type": str(profile.get("subject_type") or "").strip(),
        "subject_domain": str(profile.get("subject_domain") or "").strip(),
        "video_theme": str(profile.get("video_theme") or "").strip(),
        "summary": str(profile.get("summary") or "").strip(),
        "hook_line": str(profile.get("hook_line") or "").strip(),
        "visible_text": str(profile.get("visible_text") or "").strip(),
        "engagement_question": str(profile.get("engagement_question") or "").strip(),
        "correction_notes": str(profile.get("correction_notes") or "").strip(),
        "supplemental_context": str(profile.get("supplemental_context") or "").strip(),
        "copy_style": str(profile.get("copy_style") or "").strip(),
        "workflow_template": str(profile.get("workflow_template") or profile.get("preset_name") or "").strip(),
        "search_queries": [str(item).strip() for item in (profile.get("search_queries") or []) if str(item).strip()][:3],
        "creative_preferences": [
            {
                "tag": str(item.get("tag") or "").strip(),
                "label": str(item.get("label") or item.get("tag") or "").strip(),
                "guidance": str(item.get("guidance") or "").strip(),
            }
            for item in creative_preferences[:6]
            if str(item.get("tag") or "").strip()
        ],
        "cover_title": {
            "top": str(cover_title.get("top") or "").strip(),
            "main": str(cover_title.get("main") or "").strip(),
            "bottom": str(cover_title.get("bottom") or "").strip(),
        },
        "manual_review_applied": bool(str(profile.get("review_mode") or "").strip() == "manual_confirmed" or resolved_feedback),
        "resolved_review_user_feedback": resolved_feedback,
        "transcript_excerpt": build_transcript_for_packaging(subtitle_items, max_chars=max_transcript_chars),
    }


def build_packaging_fact_sheet_cache_fingerprint(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = content_profile or {}
    resolved_feedback = _resolved_review_feedback_payload(profile)
    evidence = [
        {
            "title": str(item.get("title") or "").strip(),
            "url": str(item.get("url") or "").strip(),
            "snippet": str(item.get("snippet") or "").strip(),
        }
        for item in (profile.get("evidence") or [])
        if isinstance(item, dict) and (item.get("url") or item.get("title") or item.get("snippet"))
    ]
    return {
        "version": _PLATFORM_FACT_SHEET_CACHE_VERSION,
        "source_name": str(source_name or "").strip(),
        "subject_brand": str(profile.get("subject_brand") or "").strip(),
        "subject_model": str(profile.get("subject_model") or "").strip(),
        "subject_type": str(profile.get("subject_type") or "").strip(),
        "search_queries": [str(item).strip() for item in (profile.get("search_queries") or []) if str(item).strip()][:4],
        "resolved_review_feedback_sha256": digest_payload(resolved_feedback),
        "transcript_excerpt_sha256": digest_payload(build_transcript_for_packaging(subtitle_items, max_chars=1400)),
        "evidence_sha256": digest_payload(evidence),
        "evidence_count": len(evidence),
    }


def packaging_fact_sheet_cache_allowed(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile or {}
    if not _has_specific_subject_identity(profile):
        return True
    evidence = [
        item
        for item in (profile.get("evidence") or [])
        if isinstance(item, dict) and (item.get("url") or item.get("title") or item.get("snippet"))
    ]
    return len(evidence) >= 2


def build_platform_packaging_cache_fingerprint(
    *,
    source_name: str,
    prompt_brief: dict[str, Any],
    fact_sheet: dict[str, Any],
    copy_style: str,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "version": _PLATFORM_PACKAGE_CACHE_VERSION,
        "source_name": str(source_name or "").strip(),
        "copy_style": str(copy_style or "").strip(),
        "prompt_brief_sha256": digest_payload(prompt_brief or {}),
        "fact_sheet_sha256": digest_payload(fact_sheet or {}),
        "author_profile_sha256": digest_payload(author_profile or {}),
    }


async def build_packaging_fact_sheet(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
) -> dict[str, Any]:
    profile = content_profile or {}
    if not _has_specific_subject_identity(profile):
        return {
            "status": "skipped",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "主体信息不明确，禁止写任何具体参数、升级倍率、发布时间或价格差异。",
        }

    evidence = [
        item for item in (profile.get("evidence") or [])
        if isinstance(item, dict) and (item.get("url") or item.get("title") or item.get("snippet"))
    ]
    if len(evidence) < 2:
        evidence.extend(
            await _search_packaging_evidence(
                source_name=source_name,
                content_profile=profile,
                subtitle_items=subtitle_items,
            )
        )
    evidence = _dedupe_evidence(evidence)
    if not evidence:
        return {
            "status": "unverified",
            "verified_facts": [],
            "official_sources": [],
            "guardrail_summary": "未找到可核验来源，禁止写流明、毫瓦、射程、容量、功率、价格、发布时间和升级倍率。",
        }

    preferred_evidence = _prefer_official_evidence(
        evidence,
        brand=str(profile.get("subject_brand") or ""),
        model=str(profile.get("subject_model") or ""),
    )
    try:
        with llm_task_route("copy", search_enabled=False):
            provider = get_reasoning_provider()
            subject_identity = _packaging_subject_identity(profile)
            resolved_feedback = _resolved_review_feedback_payload(profile)
            prompt = (
                "你在做短视频发布前的参数核验。"
                "只能根据下面给出的搜索证据，提炼已经被证据直接支持的事实。"
                "不要补全、不要猜测、不要根据常识扩写。"
                "数字参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率只有在证据里明确出现时才能写。"
                "如果证据不足，就返回空 verified_facts。"
                "输出 JSON："
                '{"verified_facts":[{"fact":"","source_url":"","source_title":""}],"official_sources":[{"title":"","url":""}],"guardrail_summary":""}'
                f"\n视频主体：{json.dumps(subject_identity, ensure_ascii=False)}"
                f"\n审核确认修正：{json.dumps(resolved_feedback, ensure_ascii=False)}"
                f"\n搜索证据：{json.dumps(preferred_evidence[:8], ensure_ascii=False)}"
            )
            with track_usage_operation("platform_package.fact_sheet"):
                response = await asyncio.wait_for(
                    provider.complete(
                        [
                            Message(role="system", content="你是严格的事实核验助手，只输出 JSON。"),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.0,
                        max_tokens=900,
                        json_mode=True,
                    ),
                    timeout=75,
                )
        raw = response.as_json()
    except Exception:
        raw = {}

    fact_sheet = _normalize_fact_sheet(
        raw,
        fallback_evidence=preferred_evidence,
    )
    if not fact_sheet["verified_facts"]:
        fact_sheet["status"] = "unverified"
        fact_sheet["guardrail_summary"] = (
            fact_sheet.get("guardrail_summary")
            or "证据里没有足够明确的参数支持，禁止写参数、倍率和上市状态。"
        )
    else:
        fact_sheet["status"] = "verified"
    return fact_sheet


async def generate_platform_packaging(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    copy_style: str = "attention_grabbing",
    author_profile: dict[str, Any] | None = None,
    prompt_brief: dict[str, Any] | None = None,
    fact_sheet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    prompt_brief = prompt_brief or build_packaging_prompt_brief(
        source_name=source_name,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
    )
    fact_sheet = fact_sheet or await build_packaging_fact_sheet(
        source_name=source_name,
        content_profile=content_profile,
        subtitle_items=subtitle_items,
    )
    fact_guardrail_text = _build_fact_guardrail_text(fact_sheet)
    author_prompt_text = _build_author_prompt_text(author_profile)
    creative_guidance_text = _build_packaging_creative_guidance_text(content_profile)
    prompt = (
        "你是多平台视频包装官，负责把字幕整理成适合不同平台发布的标题、简介和标签。"
        f"{_domain_prompt_voice_instruction(content_profile)}"
        "要求：\n"
        "1. 输出真实自然，不要像硬广，不编造事实。\n"
        "2. 刀具、EDC、工具相关内容必须保守合规，避免危险导向表述。\n"
        "3. 每个平台必须提供 5 个标题、1 段简介/正文、1 组标签，且五个平台的简介/正文不能只是轻微同义改写。\n"
        "4. 标题要有角度差异：爆点型、稳妥型、提问型、情绪型、结论型。\n"
        "5. 标签必须贴合产品、品类、场景、风格、视频类型。\n"
        "6. 不要输出空字段。\n"
        "7. 参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率，只能写在“已核验事实”里出现过的信息。\n"
        "8. 如果没有核验证据，改写成保守表达，只写到手体验、外观、做工、上手感受，不写具体参数。\n\n"
        "9. 如果给了作者信息，只能按平台策略选择最合适的 0 到 3 个字段自然带出，不要所有平台重复同一段自我介绍。\n"
        "10. 平台简介策略必须明显区分：\n"
        "- B站：先给核心判断，再说这期重点拆什么，可自然带作者专业身份或长期关注方向。\n"
        "- 小红书：像真实分享笔记，带一点作者人设、审美/使用偏好、到手感受。\n"
        "- 抖音：一句结果 + 一句记忆点，可带极短作者身份锚点，节奏要快。\n"
        "- 快手：像当面讲实话，直给、不绕，可带接地气的人设表达。\n"
        "- 视频号：稳妥可信，偏总结式，可带作者职业/内容定位增强可信度。\n"
        "- 头条号：偏资讯/观点摘要，标题和正文要先把判断讲明白。\n"
        "- YouTube：描述可更完整，适合补充结构、关键看点和检索关键词。\n"
        "- X：没有独立视频标题，推文正文要短，像可直接发出的贴文。\n\n"
        f"本次统一文案风格：{_copy_style_instruction(copy_style)}\n\n"
        f"{fact_guardrail_text}\n\n"
        f"{author_prompt_text}\n\n"
        f"{creative_guidance_text}\n\n"
        "默认平台偏置：\n"
        f"- B站：{_platform_bias_instruction('B站')}\n"
        f"- 小红书：{_platform_bias_instruction('小红书')}\n"
        f"- 抖音：{_platform_bias_instruction('抖音')}\n"
        f"- 快手：{_platform_bias_instruction('快手')}\n"
        f"- 视频号：{_platform_bias_instruction('视频号')}\n"
        f"- 头条号：{_platform_bias_instruction('头条号')}\n"
        f"- YouTube：{_platform_bias_instruction('YouTube')}\n"
        f"- X：{_platform_bias_instruction('X')}\n\n"
        "请输出 JSON，格式如下：\n"
        "{"
        "\"highlights\":{"
        "\"product\":\"\",\"video_type\":\"\",\"strongest_selling_point\":\"\","
        "\"strongest_emotion\":\"\",\"title_hook\":\"\",\"engagement_question\":\"\""
        "},"
        "\"platforms\":{"
        "\"bilibili\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"xiaohongshu\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"douyin\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"kuaishou\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"wechat_channels\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"toutiao\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"youtube\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]},"
        "\"x\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]}"
        "}"
        "}\n\n"
        f"视频摘要上下文：{json.dumps(prompt_brief, ensure_ascii=False)}"
    )
    try:
        with llm_task_route("copy", search_enabled=False):
            provider = get_reasoning_provider()
            with track_usage_operation("platform_package.generate_packaging"):
                response = await asyncio.wait_for(
                    provider.complete(
                        [
                            Message(
                                role="system",
                                content=(
                                    "你是严谨的中文多平台视频包装策划。"
                                    "优先输出真实玩家口吻、平台化表达、自然互动问题和合规标签。"
                                ),
                            ),
                            Message(role="user", content=prompt),
                        ],
                        temperature=0.35,
                        max_tokens=3200,
                        json_mode=True,
                    ),
                    timeout=90,
                )
        raw_response = response.as_json()
    except Exception:
        raw_response = {}
    packaging = normalize_platform_packaging(
        raw_response,
        content_profile=content_profile,
        copy_style=copy_style,
        fact_sheet=fact_sheet,
        author_profile=author_profile,
    )
    packaging["fact_sheet"] = fact_sheet
    return packaging


def normalize_platform_packaging(
    raw: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str = "attention_grabbing",
    fact_sheet: dict[str, Any] | None = None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    highlights = raw.get("highlights") if isinstance(raw.get("highlights"), dict) else {}
    normalized: dict[str, Any] = {
        "highlights": {
            "product": _normalize_highlight_product(highlights.get("product"), content_profile),
            "video_type": str(highlights.get("video_type") or _fallback_video_type(content_profile)).strip(),
            "strongest_selling_point": str(highlights.get("strongest_selling_point") or "").strip(),
            "strongest_emotion": str(highlights.get("strongest_emotion") or "").strip(),
            "title_hook": str(highlights.get("title_hook") or "").strip(),
            "engagement_question": str(highlights.get("engagement_question") or _fallback_question(content_profile)).strip(),
        },
        "platforms": {},
    }

    raw_platforms = raw.get("platforms") if isinstance(raw.get("platforms"), dict) else {}
    for key, label, _, _ in PLATFORM_ORDER:
        platform_raw = raw_platforms.get(key) if isinstance(raw_platforms.get(key), dict) else {}
        titles = _normalize_titles(platform_raw.get("titles"), label=label, content_profile=content_profile, copy_style=copy_style)
        description = _normalize_platform_description(
            platform_raw.get("description"),
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
            author_profile=author_profile,
        )
        tags = _normalize_tags(platform_raw.get("tags"), content_profile=content_profile)
        normalized["platforms"][key] = {
            "titles": titles,
            "description": description,
            "tags": tags,
        }

    guarded = _enforce_packaging_fact_guardrails(
        normalized,
        content_profile=content_profile,
        copy_style=copy_style,
        fact_sheet=fact_sheet,
        author_profile=author_profile,
    )
    varied = _enforce_platform_description_variation(
        guarded,
        content_profile=content_profile,
        copy_style=copy_style,
        author_profile=author_profile,
    )
    varied["title_audit"] = audit_platform_packaging_titles(
        varied,
        content_profile=content_profile,
    )
    return varied


def render_platform_packaging_markdown(packaging: dict[str, Any]) -> str:
    highlights = packaging.get("highlights") or {}
    lines = [
        "# 视频爆点提炼",
        f"- 产品：{highlights.get('product', '')}",
        f"- 视频类型：{highlights.get('video_type', '')}",
        f"- 最强卖点：{highlights.get('strongest_selling_point', '')}",
        f"- 最强情绪点：{highlights.get('strongest_emotion', '')}",
        f"- 最适合标题的钩子：{highlights.get('title_hook', '')}",
        f"- 最适合评论区的问题：{highlights.get('engagement_question', '')}",
        "",
    ]

    title_audit = packaging.get("title_audit") if isinstance(packaging.get("title_audit"), dict) else {}
    audit_platforms = title_audit.get("platforms") if isinstance(title_audit.get("platforms"), dict) else {}
    if audit_platforms:
        summary = title_audit.get("summary") if isinstance(title_audit.get("summary"), dict) else {}
        lines.extend(
            [
                "# 标题审核",
                (
                    f"- 总体：{str(summary.get('status') or 'unknown')}，"
                    f"{int(summary.get('platforms_with_errors') or 0)} 个平台报错，"
                    f"{int(summary.get('platforms_with_warnings') or 0)} 个平台预警"
                ),
                f"- 审计版本：{title_audit.get('version') or _TITLE_AUDIT_VERSION}",
                "- 计数方式：中文/全角按 1，英文数字半角按 0.5，长度判断向上取整",
                "",
            ]
        )
        for key, label, _, _ in PLATFORM_ORDER:
            platform_audit = audit_platforms.get(key)
            if not isinstance(platform_audit, dict):
                continue
            lines.append(f"## {label}")
            lines.append(f"- 结果：{_render_title_audit_platform_summary(platform_audit)}")
            for issue in (platform_audit.get("issues") or [])[:3]:
                if not isinstance(issue, dict):
                    continue
                lines.append(
                    f"- {str(issue.get('severity') or 'warning').upper()}: {str(issue.get('message') or '').strip()}"
                )
            lines.append("")

    platforms = packaging.get("platforms") or {}
    for key, label, body_label, tag_label in PLATFORM_ORDER:
        platform = platforms.get(key) or {}
        lines.append(f"# {label}")
        lines.append("## 标题")
        for idx, title in enumerate(platform.get("titles") or [], start=1):
            lines.append(f"{idx}. {title}")
        lines.append("")
        lines.append(f"## {body_label}")
        lines.append(platform.get("description") or "")
        lines.append("")
        lines.append(f"## {tag_label}")
        lines.append(" ".join(_hashify_tags(platform.get("tags") or [])))
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def save_platform_packaging_markdown(output_path: Path, packaging: dict[str, Any]) -> Path:
    output_path.write_text(render_platform_packaging_markdown(packaging), encoding="utf-8")
    return output_path


async def _search_packaging_evidence(
    *,
    source_name: str,
    content_profile: dict[str, Any],
    subtitle_items: list[dict[str, Any]],
) -> list[dict[str, str]]:
    try:
        provider = get_search_provider()
    except Exception:
        return []

    transcript_text = build_transcript_for_packaging(subtitle_items, max_chars=1400)
    queries = _build_packaging_fact_queries(
        source_name=source_name,
        content_profile=content_profile,
        transcript_text=transcript_text,
    )
    results: list[dict[str, str]] = []
    for query in queries[:4]:
        try:
            items = await provider.search(query, max_results=4)
        except Exception:
            continue
        for item in items:
            results.append(
                {
                    "query": query,
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                }
            )
    return results


def _build_packaging_fact_queries(
    *,
    source_name: str,
    content_profile: dict[str, Any],
    transcript_text: str,
) -> list[str]:
    identity = _packaging_subject_identity(content_profile)
    brand = str(identity.get("brand") or "").strip()
    model = str(identity.get("model") or "").strip()
    subject_type = str(identity.get("subject_type") or "").strip()
    queries: list[str] = []
    resolved_feedback = _resolved_review_feedback_payload(content_profile)
    preferred_search_queries = resolved_feedback.get("search_queries") or content_profile.get("search_queries") or []
    for item in preferred_search_queries:
        text = str(item).strip()
        if text:
            queries.append(text)
    if brand and model:
        queries.extend(
            [
                f"{brand} {model} 官方 参数",
                f"{brand} {model} 官网",
                f"{brand} {model} official specs",
            ]
        )
    if brand and model and subject_type:
        queries.append(f"{brand} {model} {subject_type} 官方")
    if not queries:
        stem = Path(source_name).stem
        if stem:
            queries.append(stem)
    if transcript_text and brand and model:
        queries.append(f"{brand} {model} 开箱")
    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        text = item.strip()
        if text and text not in seen:
            seen.add(text)
            deduped.append(text)
    return deduped


def _resolved_review_feedback_payload(content_profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = content_profile or {}
    payload = profile.get("resolved_review_user_feedback")
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "video_theme",
        "hook_line",
        "visible_text",
        "summary",
        "engagement_question",
        "correction_notes",
        "supplemental_context",
    ):
        value = str(payload.get(key) or "").strip()
        if value:
            normalized[key] = value
    queries = [str(item).strip() for item in (payload.get("search_queries") or []) if str(item).strip()]
    if queries:
        normalized["search_queries"] = queries[:6]
    return normalized


def _packaging_subject_identity(content_profile: dict[str, Any] | None) -> dict[str, str]:
    profile = content_profile or {}
    resolved_feedback = _resolved_review_feedback_payload(profile)
    return {
        "brand": str(resolved_feedback.get("subject_brand") or profile.get("subject_brand") or "").strip(),
        "model": str(resolved_feedback.get("subject_model") or profile.get("subject_model") or "").strip(),
        "subject_type": str(resolved_feedback.get("subject_type") or profile.get("subject_type") or "").strip(),
    }


def _dedupe_evidence(evidence: list[dict[str, Any]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in evidence:
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        snippet = str(item.get("snippet") or "").strip()
        key = url or f"{title}|{snippet}"
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(
            {
                "query": str(item.get("query") or "").strip(),
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )
    return deduped


def _prefer_official_evidence(
    evidence: list[dict[str, str]],
    *,
    brand: str,
    model: str,
) -> list[dict[str, str]]:
    official = [item for item in evidence if _looks_officialish_source(item, brand=brand, model=model)]
    return official or evidence


def _looks_officialish_source(item: dict[str, str], *, brand: str, model: str) -> bool:
    url = str(item.get("url") or "")
    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    host = (urlparse(url).netloc or "").lower()
    merged = f"{title} {snippet} {host}".lower()
    if any(token in merged for token in (" official", "官网", "官方", "spec", "参数")):
        return True
    tokens = []
    for raw in (brand, model):
        normalized = re.sub(r"[^a-z0-9]+", "", str(raw or "").lower())
        if len(normalized) >= 4:
            tokens.append(normalized)
    host_compact = re.sub(r"[^a-z0-9]+", "", host)
    return any(token in host_compact for token in tokens)


def _normalize_fact_sheet(raw: dict[str, Any], *, fallback_evidence: list[dict[str, str]]) -> dict[str, Any]:
    verified_facts: list[dict[str, str]] = []
    for item in raw.get("verified_facts") or []:
        if not isinstance(item, dict):
            continue
        fact = str(item.get("fact") or "").strip()
        source_url = str(item.get("source_url") or "").strip()
        source_title = str(item.get("source_title") or "").strip()
        if not fact:
            continue
        verified_facts.append(
            {
                "fact": fact,
                "source_url": source_url,
                "source_title": source_title,
            }
        )
    official_sources: list[dict[str, str]] = []
    for item in raw.get("official_sources") or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if title or url:
            official_sources.append({"title": title, "url": url})
    if not official_sources:
        for item in fallback_evidence[:4]:
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            if title or url:
                official_sources.append({"title": title, "url": url})
    return {
        "status": "verified" if verified_facts else "unverified",
        "verified_facts": verified_facts,
        "official_sources": official_sources,
        "guardrail_summary": str(raw.get("guardrail_summary") or "").strip(),
    }


def _build_fact_guardrail_text(fact_sheet: dict[str, Any] | None) -> str:
    sheet = fact_sheet or {}
    facts = [str(item.get("fact") or "").strip() for item in sheet.get("verified_facts") or [] if str(item.get("fact") or "").strip()]
    sources = [str(item.get("url") or "").strip() for item in sheet.get("official_sources") or [] if str(item.get("url") or "").strip()]
    if not facts:
        return (
            "已核验事实：无。\n"
            "写作约束：禁止写具体参数、功率、流明、毫瓦、射程、容量、价格、发布时间、升级倍率；"
            "只能写到手体验、外观、做工、手感、使用场景。"
        )
    source_text = "\n".join(f"- {item}" for item in sources[:4]) or "- 无"
    fact_text = "\n".join(f"- {item}" for item in facts[:8])
    return (
        "已核验事实（只能使用以下已核验信息）：\n"
        f"{fact_text}\n"
        "优先来源：\n"
        f"{source_text}"
    )


def _enforce_packaging_fact_guardrails(
    packaging: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    fact_sheet: dict[str, Any] | None,
    author_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sheet = fact_sheet or {}
    verified_blob = "\n".join(str(item.get("fact") or "") for item in sheet.get("verified_facts") or [])
    guarded = {
        "highlights": dict(packaging.get("highlights") or {}),
        "platforms": {key: dict(value or {}) for key, value in (packaging.get("platforms") or {}).items()},
    }
    if sheet:
        guarded["fact_sheet"] = sheet

    highlights = guarded["highlights"]
    if _contains_unverified_claim(str(highlights.get("strongest_selling_point") or ""), verified_blob):
        highlights["strongest_selling_point"] = ""
    if _contains_unverified_claim(str(highlights.get("title_hook") or ""), verified_blob):
        highlights["title_hook"] = str((content_profile or {}).get("hook_line") or "").strip()
    if not _contains_confirmed_product_anchor(str(highlights.get("title_hook") or ""), content_profile):
        highlights["title_hook"] = _build_confirmed_title_hook(content_profile)

    for key, label, _, _ in PLATFORM_ORDER:
        platform = guarded["platforms"].get(key) or {}
        fallback_titles = _fit_titles_to_platform(
            build_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style),
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
        )
        titles = list(platform.get("titles") or [])
        guarded_titles: list[str] = []
        for idx, title in enumerate(titles[:5]):
            replacement = fallback_titles[min(idx, len(fallback_titles) - 1)] if fallback_titles else _sanitize_title_text(title)
            if _contains_unverified_claim(title, verified_blob) or not _contains_confirmed_product_anchor(title, content_profile):
                guarded_titles.append(replacement)
            else:
                guarded_titles.append(title)
        platform["titles"] = _fit_titles_to_platform(
            guarded_titles + fallback_titles[len(guarded_titles):5],
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
        )
        description = str(platform.get("description") or "").strip()
        if _contains_unverified_claim(description, verified_blob):
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
        guarded["platforms"][key] = platform
    return guarded


def _contains_unverified_claim(text: str, verified_blob: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if not _looks_like_fact_sensitive_claim(normalized):
        return False
    if not verified_blob.strip():
        return True
    normalized_blob = verified_blob.lower()
    lower_text = normalized.lower()
    numeric_tokens = re.findall(r"\d+(?:\.\d+)?", normalized)
    if numeric_tokens and any(token not in normalized_blob for token in numeric_tokens):
        return True
    risk_terms = [
        "翻倍",
        "提升",
        "增加",
        "发布",
        "首发",
        "闲鱼",
        "价格",
        "贵",
        "便宜",
        "一代",
        "二代",
    ]
    for term in risk_terms:
        if term in lower_text and term not in normalized_blob:
            return True
    return False


def _looks_like_fact_sensitive_claim(text: str) -> bool:
    lower_text = str(text or "").lower()
    if re.search(r"\d", lower_text):
        return True
    keywords = (
        "流明",
        "lm",
        "毫瓦",
        "mw",
        "mwh",
        "mah",
        "功率",
        "射程",
        "续航",
        "容量",
        "价格",
        "未发布",
        "发布",
        "闲鱼",
        "翻倍",
        "升级",
        "提升",
        "增加",
        "一代",
        "二代",
        "对比",
        "比一代",
        "比上一代",
        "多花",
    )
    return any(token in lower_text for token in keywords)


def _normalize_titles(value: Any, *, label: str, content_profile: dict[str, Any] | None, copy_style: str) -> list[str]:
    titles = [str(item).strip() for item in (value or []) if str(item).strip()]
    if len(titles) >= 5:
        return _fit_titles_to_platform(titles[:5], label=label, content_profile=content_profile, copy_style=copy_style)

    fallback = build_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style)
    seen: set[str] = set()
    merged: list[str] = []
    for title in titles + fallback:
        if title not in seen:
            seen.add(title)
            merged.append(title)
        if len(merged) >= 5:
            break
    return _fit_titles_to_platform(merged, label=label, content_profile=content_profile, copy_style=copy_style)


def _fit_titles_to_platform(
    titles: list[str],
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str,
) -> list[str]:
    key = _platform_key_from_label(label)
    rule = _TITLE_AUDIT_RULES.get(key) or {}
    max_chars = (
        rule.get("hard_max_chars")
        or rule.get("recommended_max_chars")
        or rule.get("display_max_chars")
    )
    compact_fallbacks = _build_compact_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style)
    seen: set[str] = set()
    fitted: list[str] = []
    fallback_cursor = 0
    for raw_title in titles:
        title = _sanitize_title_text(raw_title)
        if isinstance(max_chars, int) and _text_display_units_ceiling(title) > max_chars:
            replacement = ""
            while fallback_cursor < len(compact_fallbacks):
                candidate = _sanitize_title_text(compact_fallbacks[fallback_cursor])
                fallback_cursor += 1
                if candidate and _text_display_units_ceiling(candidate) <= max_chars and candidate not in seen:
                    replacement = candidate
                    break
            title = replacement or _truncate_title(title, max_chars)
        if not title or title in seen:
            continue
        seen.add(title)
        fitted.append(title)
        if len(fitted) >= 5:
            return fitted

    for candidate in compact_fallbacks:
        title = _sanitize_title_text(candidate)
        if not title or title in seen:
            continue
        if isinstance(max_chars, int) and _text_display_units_ceiling(title) > max_chars:
            title = _truncate_title(title, max_chars)
        if not title or title in seen:
            continue
        seen.add(title)
        fitted.append(title)
        if len(fitted) >= 5:
            break
    return fitted


def _build_compact_fallback_titles(
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str,
) -> list[str]:
    del copy_style
    if not _has_specific_subject_identity(content_profile):
        if label == "小红书":
            return ["终于到手了", "先看开箱细节", "这次质感真不错", "细节先看清", "值不值先聊聊"]
        if label == "抖音":
            return ["先看这次开箱", "这次值不值", "重点直接看", "细节先看", "上手先说结论"]
        if label == "快手":
            return ["给你们看个真东西", "这次我说实话", "值不值我直说", "先看细节", "到底咋样"]
        if label == "视频号":
            return ["开箱重点记录", "到手体验总结", "值不值先看", "细节重点", "上手记录"]
        if label == "头条号":
            return ["开箱重点总结", "先看核心结论", "这次体验怎么说", "值不值先讲明白", "开箱观察记录"]
        if label == "YouTube":
            return ["Hands-on quick take", "Unboxing first look", "What stands out first", "Worth it or not", "Key details first"]
        if label == "X":
            return ["Quick take first", "First look in one post", "Worth it at first glance?", "Key detail first", "Hands-on note"]
        return ["开箱重点先看", "值不值一次说清", "这次先看细节", "上手体验记录", "开箱真实判断"]

    product = _compact_product_label(content_profile, label=label)
    subject = _compact_subject_label(content_profile, label=label)
    if label == "小红书":
        return [
            f"{product}终于到手",
            f"{product}细节先看",
            f"{subject}开箱看细节",
            f"{product}值不值",
            "等很久才到手",
        ]
    if label == "抖音":
        return [
            f"{product}先看重点",
            f"{product}值不值",
            f"{product}终于到手",
            "这次开箱先看细节",
            f"{subject}先看细节",
        ]
    if label == "快手":
        return [
            "给你们看个真东西",
            f"{product}值不值我直说",
            f"{product}到底咋样",
            "这次开箱我说实话",
            f"{subject}先看细节",
        ]
    if label == "视频号":
        return [
            f"{product}开箱记录",
            f"{product}到手体验",
            f"{product}值不值",
            f"{subject}开箱重点",
            f"{product}细节总结",
        ]
    if label == "头条号":
        return [
            f"{product}开箱结论",
            f"{product}值不值先说",
            f"{product}体验重点",
            f"{subject}实测判断",
            f"{product}这次怎么看",
        ]
    if label == "YouTube":
        return [
            f"{product} review",
            f"{product} hands-on",
            f"{product} first look",
            f"{subject} quick review",
            f"{product} worth it?",
        ]
    if label == "X":
        return [
            f"{product} quick take",
            f"{product} first look",
            f"{product} one-line verdict",
            f"{subject} first impression",
            f"{product} key detail",
        ]
    return [
        f"{product}开箱实测",
        f"{product}值不值",
        f"{product}上手体验",
        f"{subject}重点细节",
        f"{product}真实判断",
    ]


def _compact_product_label(content_profile: dict[str, Any] | None, *, label: str) -> str:
    brand = _localized_brand_label(
        str((content_profile or {}).get("subject_brand") or "").strip(),
        label=label,
        content_profile=content_profile,
    )
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "这款产品"
    max_chars = 12 if label in {"小红书", "视频号"} else 14
    for candidate in (
        " ".join(part for part in (brand, model) if part).strip(),
        model,
        brand,
        subject,
        "这款产品",
    ):
        text = _sanitize_title_text(candidate)
        if text and _text_display_units_ceiling(text) <= max_chars:
            return text
    return _truncate_title(_sanitize_title_text(model or brand or subject or "这款产品"), max_chars)


def _compact_subject_label(content_profile: dict[str, Any] | None, *, label: str) -> str:
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "这次开箱"
    max_chars = 8 if label == "视频号" else 10
    return _truncate_title(_sanitize_title_text(subject), max_chars) or "这次开箱"


def _sanitize_title_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", text)
    text = text.replace("#", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ，。；：!！?？")


def _truncate_title(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    sanitized = _sanitize_title_text(text)
    if _text_display_units_ceiling(sanitized) <= max_chars:
        return sanitized
    current_units = 0.0
    truncated_chars: list[str] = []
    for char in sanitized:
        char_units = _char_display_units(char)
        if math.ceil(current_units + char_units) > max_chars:
            break
        truncated_chars.append(char)
        current_units += char_units
    return "".join(truncated_chars).rstrip(" ，。；：!！?？")


def _text_length_metrics(text: str) -> dict[str, Any]:
    ascii_count = 0
    cjk_count = 0
    fullwidth_count = 0
    emoji_count = 0
    other_count = 0
    display_units_raw = 0.0
    for char in str(text or ""):
        if _is_emoji_char(char):
            emoji_count += 1
            display_units_raw += 1.0
            continue
        east_asian_width = unicodedata.east_asian_width(char)
        if east_asian_width in {"W", "F"}:
            fullwidth_count += 1
            if _is_cjk_char(char):
                cjk_count += 1
            display_units_raw += 1.0
        elif ord(char) < 128:
            ascii_count += 1
            display_units_raw += 0.5
        else:
            other_count += 1
            display_units_raw += 1.0
    return {
        "char_count": len(text),
        "ascii_count": ascii_count,
        "cjk_count": cjk_count,
        "fullwidth_count": fullwidth_count,
        "emoji_count": emoji_count,
        "other_count": other_count,
        "display_units_raw": round(display_units_raw, 2),
        "display_units": math.ceil(display_units_raw),
    }


def _text_display_units_ceiling(text: str) -> int:
    return int(_text_length_metrics(text).get("display_units") or 0)


def _char_display_units(char: str) -> float:
    if _is_emoji_char(char):
        return 1.0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 1.0
    if ord(char) < 128:
        return 0.5
    return 1.0


def _is_cjk_char(char: str) -> bool:
    return bool(re.match(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", char))


def _is_emoji_char(char: str) -> bool:
    return bool(re.match(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", char))


def _platform_key_from_label(label: str) -> str:
    for key, current_label, _, _ in PLATFORM_ORDER:
        if current_label == label:
            return key
    return ""


def _is_cn_platform(label: str) -> bool:
    return _platform_key_from_label(label) in _CN_PLATFORM_KEYS


def _contains_cjk_text(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(text or "")))


def _looks_ascii_brand(text: str) -> bool:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", str(text or ""))
    return bool(normalized) and normalized == re.sub(r"\s+", "", str(text or ""))


def _brand_cn_alias(brand: str, content_profile: dict[str, Any] | None = None) -> str:
    profile = content_profile or {}
    preferred = str(profile.get("subject_brand_cn") or "").strip()
    if preferred:
        return preferred
    return str(_BRAND_CN_ALIASES.get(str(brand or "").strip()) or "").strip()


def _brand_bilingual_alias(brand: str, content_profile: dict[str, Any] | None = None) -> str:
    profile = content_profile or {}
    preferred = str(profile.get("subject_brand_bilingual") or "").strip()
    if preferred:
        return preferred
    alias = _brand_cn_alias(brand, content_profile)
    normalized_brand = str(brand or "").strip()
    if alias and normalized_brand and alias != normalized_brand:
        return f"{alias}{normalized_brand}"
    return normalized_brand


def _localized_brand_label(brand: str, *, label: str, content_profile: dict[str, Any] | None = None) -> str:
    normalized_brand = str(brand or "").strip()
    if not normalized_brand:
        return ""
    if not _is_cn_platform(label):
        return normalized_brand
    if _contains_cjk_text(normalized_brand):
        return normalized_brand
    alias = _brand_cn_alias(normalized_brand, content_profile)
    if not alias:
        return normalized_brand
    if label == "B站":
        return _brand_bilingual_alias(normalized_brand, content_profile)
    return alias


def _localized_product_label(content_profile: dict[str, Any] | None, *, label: str) -> str:
    brand = _localized_brand_label(
        str((content_profile or {}).get("subject_brand") or "").strip(),
        label=label,
        content_profile=content_profile,
    )
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject = _specific_subject_type(content_profile)
    return " ".join(part for part in (brand, model or subject) if part).strip()


def _localized_brand_tag_candidates(content_profile: dict[str, Any] | None) -> list[str]:
    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    if not brand:
        return []
    if _contains_cjk_text(brand):
        return [brand]
    alias = _brand_cn_alias(brand, content_profile)
    if alias:
        return [alias, brand]
    return [brand]


def _normalize_tags(value: Any, content_profile: dict[str, Any] | None) -> list[str]:
    tags = [str(item).strip().lstrip("#") for item in (value or []) if str(item).strip()]
    brand_candidates = _localized_brand_tag_candidates(content_profile)
    if tags:
        enriched = list(tags)
        raw_brand = str((content_profile or {}).get("subject_brand") or "").strip()
        alias = _brand_cn_alias(raw_brand, content_profile)
        if raw_brand and alias and raw_brand in tags and alias not in tags:
            enriched.insert(0, alias)
        return _dedupe_non_empty(enriched)[:8]

    subject = _specific_subject_type(content_profile)
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    fallback = [*brand_candidates, subject, theme]
    if _profile_mentions_edc(content_profile):
        fallback.append("EDC")
    fallback.extend(["开箱", "上手体验", "玩家分享"])
    return _dedupe_non_empty(fallback)[:8]


def _normalize_platform_description(
    value: Any,
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    author_profile: dict[str, Any] | None,
) -> str:
    description = str(value or "").strip()
    if not description:
        return build_fallback_description(
            label=label,
            content_profile=content_profile,
            copy_style=copy_style,
            author_profile=author_profile,
        )
    return _inject_author_context_into_description(label, description, author_profile)


def _enforce_platform_description_variation(
    packaging: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str,
    author_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    platforms = packaging.get("platforms")
    if not isinstance(platforms, dict):
        return packaging

    seen_descriptions: list[str] = []
    for key, label, _, _ in PLATFORM_ORDER:
        platform = platforms.get(key)
        if not isinstance(platform, dict):
            continue
        description = str(platform.get("description") or "").strip()
        if not description:
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
            description = str(platform.get("description") or "").strip()
        if any(_description_similarity(description, item) >= 0.82 for item in seen_descriptions):
            platform["description"] = build_fallback_description(
                label=label,
                content_profile=content_profile,
                copy_style=copy_style,
                author_profile=author_profile,
            )
            description = str(platform.get("description") or "").strip()
        seen_descriptions.append(description)
    return packaging


def audit_platform_packaging_titles(
    packaging: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    platforms = packaging.get("platforms") if isinstance(packaging.get("platforms"), dict) else {}
    audit_platforms: dict[str, Any] = {}
    platforms_with_errors = 0
    platforms_with_warnings = 0
    total_errors = 0
    total_warnings = 0
    for key, label, _, _ in PLATFORM_ORDER:
        platform = platforms.get(key) if isinstance(platforms.get(key), dict) else {}
        platform_audit = _audit_platform_titles(
            key=key,
            label=label,
            titles=platform.get("titles") if isinstance(platform, dict) else [],
            content_profile=content_profile,
        )
        audit_platforms[key] = platform_audit
        summary = platform_audit.get("summary") if isinstance(platform_audit.get("summary"), dict) else {}
        total_errors += int(summary.get("error_count") or 0)
        total_warnings += int(summary.get("warning_count") or 0)
        if int(summary.get("error_count") or 0) > 0:
            platforms_with_errors += 1
        elif int(summary.get("warning_count") or 0) > 0:
            platforms_with_warnings += 1

    overall_status = "pass"
    if platforms_with_errors:
        overall_status = "error"
    elif platforms_with_warnings or total_warnings:
        overall_status = "warning"
    return {
        "version": _TITLE_AUDIT_VERSION,
        "summary": {
            "status": overall_status,
            "platform_count": len(PLATFORM_ORDER),
            "platforms_with_errors": platforms_with_errors,
            "platforms_with_warnings": platforms_with_warnings,
            "error_count": total_errors,
            "warning_count": total_warnings,
        },
        "platforms": audit_platforms,
    }


def _audit_platform_titles(
    *,
    key: str,
    label: str,
    titles: Any,
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    rule = dict(_TITLE_AUDIT_RULES.get(key) or {})
    normalized_titles = [str(item).strip() for item in (titles or []) if str(item).strip()]
    title_results: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    error_count = 0
    warning_count = 0
    primary_angles: list[str] = []
    anchored_titles = 0
    for index, title in enumerate(normalized_titles, start=1):
        title_result = _audit_single_title(
            key=key,
            label=label,
            title=title,
            index=index,
            rule=rule,
            content_profile=content_profile,
        )
        title_results.append(title_result)
        primary_angles.append(str(title_result.get("primary_angle") or "generic"))
        if _contains_confirmed_product_anchor(title, content_profile):
            anchored_titles += 1
        for issue in title_result.get("issues") or []:
            if not isinstance(issue, dict):
                continue
            issues.append(issue)
            if issue.get("severity") == "error":
                error_count += 1
            else:
                warning_count += 1

    diversity = _audit_title_diversity(
        key=key,
        label=label,
        primary_angles=primary_angles,
        title_count=len(normalized_titles),
    )
    if diversity:
        issues.append(diversity)
        if diversity.get("severity") == "error":
            error_count += 1
        else:
            warning_count += 1

    if _has_specific_subject_identity(content_profile) and normalized_titles and anchored_titles < 2:
        issue = _build_audit_issue(
            severity="warning",
            code="identity_anchor_weak",
            message=f"{label} 5 个标题里只有 {anchored_titles} 个带明显主体锚点，搜索和识别会偏弱。",
        )
        issues.append(issue)
        warning_count += 1

    status = "pass"
    if error_count:
        status = "error"
    elif warning_count:
        status = "warning"
    return {
        "label": label,
        "rules": {
            "hard_max_chars": rule.get("hard_max_chars"),
            "recommended_min_chars": rule.get("recommended_min_chars"),
            "recommended_max_chars": rule.get("recommended_max_chars"),
            "display_max_chars": rule.get("display_max_chars"),
            "encoding": "utf-8 single-line",
            "counting_mode": "中文/全角=1，英文数字半角=0.5，向上取整",
            "style_hint": rule.get("style_hint") or "",
            "audience_hint": rule.get("audience_hint") or "",
        },
        "summary": {
            "status": status,
            "title_count": len(normalized_titles),
            "error_count": error_count,
            "warning_count": warning_count,
            "anchored_title_count": anchored_titles,
            "unique_primary_angles": len({item for item in primary_angles if item}),
        },
        "titles": title_results,
        "issues": issues,
    }


def _audit_single_title(
    *,
    key: str,
    label: str,
    title: str,
    index: int,
    rule: dict[str, Any],
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    metrics = _text_length_metrics(title)
    char_count = int(metrics.get("char_count") or 0)
    display_units = int(metrics.get("display_units") or 0)
    display_units_raw = float(metrics.get("display_units_raw") or 0.0)
    utf8_bytes = 0
    try:
        utf8_bytes = len(title.encode("utf-8"))
    except UnicodeEncodeError:
        issues.append(
            _build_audit_issue(
                severity="error",
                code="invalid_utf8",
                message=f"{label} 标题 {index} 不能稳定编码为 UTF-8。",
                title_index=index,
            )
        )
    if any(0xD800 <= ord(char) <= 0xDFFF for char in title):
        issues.append(
            _build_audit_issue(
                severity="error",
                code="surrogate_char",
                message=f"{label} 标题 {index} 含有非法代理字符。",
                title_index=index,
            )
        )
    if re.search(r"[\r\n\t]", title) or re.search(r"[\x00-\x1f\x7f]", title):
        issues.append(
            _build_audit_issue(
                severity="error",
                code="control_char",
                message=f"{label} 标题 {index} 含换行、Tab 或控制字符，不适合直接发布。",
                title_index=index,
            )
        )
    if re.search(r"[\u200b-\u200f\u2060\ufeff]", title):
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="invisible_char",
                message=f"{label} 标题 {index} 含零宽或不可见字符，建议清理。",
                title_index=index,
            )
        )
    if "�" in title:
        issues.append(
            _build_audit_issue(
                severity="error",
                code="replacement_char",
                message=f"{label} 标题 {index} 出现替换字符，说明原始文本可能有编码损坏。",
                title_index=index,
            )
        )

    hard_max_chars = rule.get("hard_max_chars")
    if isinstance(hard_max_chars, int) and display_units > hard_max_chars:
        issues.append(
            _build_audit_issue(
                severity="error",
                code="hard_length_overflow",
                message=f"{label} 标题 {index} 加权长度 {display_units}，超过硬限制 {hard_max_chars}。",
                title_index=index,
            )
        )
    recommended_min_chars = rule.get("recommended_min_chars")
    if isinstance(recommended_min_chars, int) and display_units < recommended_min_chars:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="too_short",
                message=f"{label} 标题 {index} 加权长度只有 {display_units}，信息量偏弱。",
                title_index=index,
            )
        )
    recommended_max_chars = rule.get("recommended_max_chars")
    if isinstance(recommended_max_chars, int) and display_units > recommended_max_chars:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="recommended_length_overflow",
                message=f"{label} 标题 {index} 加权长度 {display_units}，超过建议上限 {recommended_max_chars}。",
                title_index=index,
            )
        )
    display_max_chars = rule.get("display_max_chars")
    if isinstance(display_max_chars, int) and display_units > display_max_chars:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="display_length_overflow",
                message=f"{label} 标题 {index} 加权长度 {display_units}，超出常见展示舒适区 {display_max_chars}。",
                title_index=index,
            )
        )

    emoji_count = int(metrics.get("emoji_count") or 0)
    max_emojis = int(rule.get("max_emojis") or 0)
    if emoji_count > max_emojis:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="emoji_overuse",
                message=f"{label} 标题 {index} 含 {emoji_count} 个 emoji，超出建议值 {max_emojis}。",
                title_index=index,
            )
        )
    exclamation_count = len(re.findall(r"[!！]", title))
    max_exclamations = int(rule.get("max_exclamations") or 0)
    if exclamation_count > max_exclamations:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="punctuation_overuse",
                message=f"{label} 标题 {index} 感叹号偏多，当前 {exclamation_count} 个。",
                title_index=index,
            )
        )
    if re.search(r"[!！?？]{2,}", title):
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="repeated_punctuation",
                message=f"{label} 标题 {index} 有连续标点，平台感不稳。",
                title_index=index,
            )
        )
    if "#" in title:
        issues.append(
            _build_audit_issue(
                severity="warning",
                code="title_has_hashtag",
                message=f"{label} 标题 {index} 把 hashtag 写进了标题，建议留给标签区。",
                title_index=index,
            )
        )

    style_issue = _audit_platform_style(title=title, key=key, label=label, index=index, rule=rule)
    if style_issue:
        issues.append(style_issue)
    audience_issue = _audit_platform_audience_fit(
        title=title,
        key=key,
        label=label,
        index=index,
        rule=rule,
        content_profile=content_profile,
    )
    if audience_issue:
        issues.append(audience_issue)

    primary_angle = _title_primary_angle(title)
    status = "pass"
    if any(issue.get("severity") == "error" for issue in issues):
        status = "error"
    elif issues:
        status = "warning"
    return {
        "index": index,
        "title": title,
        "char_count": char_count,
        "display_units": display_units,
        "display_units_raw": display_units_raw,
        "ascii_count": int(metrics.get("ascii_count") or 0),
        "cjk_count": int(metrics.get("cjk_count") or 0),
        "utf8_bytes": utf8_bytes,
        "status": status,
        "primary_angle": primary_angle,
        "angles": _title_angles(title),
        "issues": issues,
    }


def _audit_platform_style(
    *,
    title: str,
    key: str,
    label: str,
    index: int,
    rule: dict[str, Any],
) -> dict[str, Any] | None:
    preferred_tokens = tuple(rule.get("preferred_tokens") or ())
    if preferred_tokens and not any(token in title for token in preferred_tokens):
        return _build_audit_issue(
            severity="warning",
            code="style_mismatch",
            message=f"{label} 标题 {index} 缺少平台常见表达信号，当前更像通用标题。",
            title_index=index,
        )
    if key == "douyin" and len(title) > 24:
        return _build_audit_issue(
            severity="warning",
            code="pace_too_slow",
            message=f"{label} 标题 {index} 偏长，短视频首屏节奏会慢。",
            title_index=index,
        )
    if key == "wechat_channels" and re.search(r"封神|炸裂|杀疯|绝绝子|离谱", title):
        return _build_audit_issue(
            severity="warning",
            code="tone_too_hyped",
            message=f"{label} 标题 {index} 网感词偏重，不够稳妥可信。",
            title_index=index,
        )
    if key == "youtube" and re.search(r"封神|绝绝子|杀疯|离谱", title):
        return _build_audit_issue(
            severity="warning",
            code="tone_too_localized",
            message=f"{label} 标题 {index} 网感词过重，国际平台检索和点击稳定性会下降。",
            title_index=index,
        )
    if key == "x" and len(title) > 32:
        return _build_audit_issue(
            severity="warning",
            code="hook_too_long",
            message=f"{label} 标题 {index} 作为贴文开头偏长，转发传播不够利落。",
            title_index=index,
        )
    if key == "kuaishou" and re.search(r"杂志感|氛围感|高级感", title):
        return _build_audit_issue(
            severity="warning",
            code="tone_too_polished",
            message=f"{label} 标题 {index} 太像精修种草文，不够直给。",
            title_index=index,
        )
    return None


def _audit_platform_audience_fit(
    *,
    title: str,
    key: str,
    label: str,
    index: int,
    rule: dict[str, Any],
    content_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    avoid_tokens = tuple(rule.get("avoid_tokens") or ())
    if avoid_tokens and any(token in title for token in avoid_tokens):
        return _build_audit_issue(
            severity="warning",
            code="audience_mismatch",
            message=f"{label} 标题 {index} 含 {', '.join(token for token in avoid_tokens if token in title)}，和平台主流受众预期不太一致。",
            title_index=index,
        )
    if key == "bilibili" and not re.search(r"开箱|实测|对比|评测|值不值|体验|怎么选|总结|判断|细节", title):
        return _build_audit_issue(
            severity="warning",
            code="search_signal_weak",
            message=f"{label} 标题 {index} 缺少主题或判断词，搜索可见性偏弱。",
            title_index=index,
        )
    if key == "xiaohongshu" and not re.search(r"到手|分享|细节|质感|记录|真的|种草|劝退|喜欢|被", title):
        return _build_audit_issue(
            severity="warning",
            code="share_feel_weak",
            message=f"{label} 标题 {index} 分享感偏弱，更像通用分发标题。",
            title_index=index,
        )
    if key == "kuaishou" and not re.search(r"给你们看|真东西|实话|直说|值不值|到底|咱", title):
        return _build_audit_issue(
            severity="warning",
            code="plainspoken_weak",
            message=f"{label} 标题 {index} 少了点“当面讲实话”的口语感。",
            title_index=index,
        )
    if key == "youtube" and not re.search(r"review|unboxing|hands-on|first look|体验|评测|开箱|实测", title, re.IGNORECASE):
        return _build_audit_issue(
            severity="warning",
            code="search_signal_weak",
            message=f"{label} 标题 {index} 缺少 review / unboxing / hands-on 一类可检索信号。",
            title_index=index,
        )
    if key == "x" and not re.search(r"结论|观察|体验|先看|quick|take|first look|hands-on", title, re.IGNORECASE):
        return _build_audit_issue(
            severity="warning",
            code="hook_signal_weak",
            message=f"{label} 标题 {index} 缺少贴文开头常见的判断或观察信号。",
            title_index=index,
        )
    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    brand_alias = _brand_cn_alias(brand, content_profile)
    if key in _CN_PLATFORM_KEYS and brand_alias and brand in title and brand_alias not in title:
        return _build_audit_issue(
            severity="warning",
            code="brand_localization_weak",
            message=f"{label} 标题 {index} 直接用了英文品牌 {brand}，更建议写成中文或中英双语，例如 {brand_alias}。",
            title_index=index,
        )
    return None


def _audit_title_diversity(
    *,
    key: str,
    label: str,
    primary_angles: list[str],
    title_count: int,
) -> dict[str, Any] | None:
    if title_count < 5:
        return _build_audit_issue(
            severity="error",
            code="title_count_missing",
            message=f"{label} 只有 {title_count} 个标题，没满足 5 个版本输出要求。",
        )
    unique_angles = {item for item in primary_angles if item and item != "generic"}
    if len(unique_angles) >= 4:
        return None
    return _build_audit_issue(
        severity="warning",
        code="angle_diversity_low",
        message=f"{label} 5 个标题只有 {len(unique_angles)} 种明显角度，版本差异不够开。",
    )


def _title_angles(title: str) -> list[str]:
    return [name for name, pattern in _TITLE_ANGLE_PATTERNS if pattern.search(title)]


def _title_primary_angle(title: str) -> str:
    matches = _title_angles(title)
    return matches[0] if matches else "generic"


def _build_audit_issue(
    *,
    severity: str,
    code: str,
    message: str,
    title_index: int | None = None,
) -> dict[str, Any]:
    issue = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if title_index is not None:
        issue["title_index"] = title_index
    return issue


def _render_title_audit_platform_summary(platform_audit: dict[str, Any]) -> str:
    summary = platform_audit.get("summary") if isinstance(platform_audit.get("summary"), dict) else {}
    rules = platform_audit.get("rules") if isinstance(platform_audit.get("rules"), dict) else {}
    limit_fragments = []
    if isinstance(rules.get("hard_max_chars"), int):
        limit_fragments.append(f"硬上限 {rules['hard_max_chars']} 字")
    if isinstance(rules.get("recommended_max_chars"), int):
        limit_fragments.append(f"建议不超过 {rules['recommended_max_chars']} 字")
    if isinstance(rules.get("display_max_chars"), int):
        limit_fragments.append(f"常见展示舒适区 {rules['display_max_chars']} 字")
    limit_text = "；".join(limit_fragments) or "长度按平台风格检查"
    return (
        f"{summary.get('status') or 'unknown'}，"
        f"{int(summary.get('error_count') or 0)} 个错误，"
        f"{int(summary.get('warning_count') or 0)} 个预警，"
        f"{limit_text}（混合中英文加权）"
        f"，"
        f"角度数 {int(summary.get('unique_primary_angles') or 0)}"
    )


def _description_similarity(left: str, right: str) -> float:
    left_normalized = re.sub(r"[\W_]+", "", str(left or "").lower())
    right_normalized = re.sub(r"[\W_]+", "", str(right or "").lower())
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(a=left_normalized, b=right_normalized).ratio()


def _inject_author_context_into_description(
    label: str,
    description: str,
    author_profile: dict[str, Any] | None,
) -> str:
    text = str(description or "").strip()
    if not text:
        return text
    author_sentence = _build_author_sentence(label, author_profile)
    if not author_sentence:
        return text
    if _description_has_author_anchor(text, author_profile):
        return text
    return _insert_sentence_before_question(text, author_sentence)


def _description_has_author_anchor(text: str, author_profile: dict[str, Any] | None) -> bool:
    normalized = _normalize_anchor_text(text)
    anchors = [
        _normalize_anchor_text(_author_public_name(author_profile)),
        _normalize_anchor_text(_author_identity(author_profile)),
        _normalize_anchor_text(_author_focus(author_profile)),
    ]
    return any(anchor and anchor in normalized for anchor in anchors)


def _insert_sentence_before_question(text: str, sentence: str) -> str:
    base = str(text or "").strip()
    author_sentence = str(sentence or "").strip().rstrip("。！？!?")
    if not base or not author_sentence:
        return base
    match = re.search(r"[^。！？!?]*[？?]\s*$", base)
    if not match:
        return f"{base.rstrip('。！？!?')}。{author_sentence}。"
    question = base[match.start():]
    leading = base[:match.start()].rstrip("。！？!? ")
    return f"{leading}。{author_sentence}{question}"


def _build_author_prompt_text(author_profile: dict[str, Any] | None) -> str:
    author_context = _author_context(author_profile)
    if not author_context:
        return "可用作者信息：无。"
    strategy = _author_description_strategy(author_profile)
    return (
        "可用作者信息（按平台策略择优引用，不要堆砌，不要所有平台重复同一段）：\n"
        f"{json.dumps(author_context, ensure_ascii=False)}"
        + (f"\n作者补充策略：{strategy}" if strategy else "")
    )


def _author_context(author_profile: dict[str, Any] | None) -> dict[str, Any]:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    business = creator_profile.get("business") if isinstance(creator_profile.get("business"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    expertise = positioning.get("expertise") if isinstance(positioning.get("expertise"), list) else personal.get("expertise") if isinstance(personal.get("expertise"), list) else []
    context = {
        "display_name": str(profile.get("display_name") or "").strip() or None,
        "presenter_alias": str(profile.get("presenter_alias") or "").strip() or None,
        "public_name": str(identity.get("public_name") or personal.get("public_name") or "").strip() or None,
        "real_name": str(identity.get("real_name") or personal.get("real_name") or "").strip() or None,
        "title": str(identity.get("title") or personal.get("title") or "").strip() or None,
        "organization": str(identity.get("organization") or personal.get("organization") or "").strip() or None,
        "location": str(identity.get("location") or personal.get("location") or "").strip() or None,
        "bio": str(identity.get("bio") or personal.get("bio") or "").strip() or None,
        "expertise": [str(item).strip() for item in expertise if str(item).strip()][:6],
        "experience": str(personal.get("experience") or "").strip() or None,
        "achievements": str(personal.get("achievements") or "").strip() or None,
        "creator_focus": str(positioning.get("creator_focus") or personal.get("creator_focus") or "").strip() or None,
        "audience": str(positioning.get("audience") or personal.get("audience") or "").strip() or None,
        "style": str(positioning.get("style") or personal.get("style") or "").strip() or None,
        "primary_platform": str(publishing.get("primary_platform") or "").strip() or None,
        "active_platforms": [str(item).strip() for item in (publishing.get("active_platforms") or []) if str(item).strip()][:6],
        "signature": str(publishing.get("signature") or "").strip() or None,
        "contact": str(business.get("contact") or personal.get("contact") or "").strip() or None,
        "collaboration_notes": str(business.get("collaboration_notes") or "").strip() or None,
        "availability": str(business.get("availability") or "").strip() or None,
        "extra_notes": str(creator_profile.get("archive_notes") or personal.get("extra_notes") or "").strip() or None,
    }
    return {key: value for key, value in context.items() if value not in (None, "", [])}


def _build_author_sentence(label: str, author_profile: dict[str, Any] | None) -> str:
    name = _author_public_name(author_profile)
    if not name:
        return ""
    identity = _author_identity(author_profile)
    focus = _author_focus(author_profile)
    style = _author_style(author_profile)
    primary_platform = _author_primary_platform(author_profile)
    if label == "B站":
        if identity and focus:
            return f"我是{name}，{identity}，长期关注{focus}"
        if focus:
            return f"我是{name}，长期关注{focus}"
        if identity:
            return f"我是{name}，{identity}"
        return f"我是{name}"
    if label == "小红书":
        if focus and style:
            return f"我是{name}，平时主要分享{focus}，会更在意{style}"
        if focus:
            return f"我是{name}，平时主要分享{focus}"
        if style:
            return f"我是{name}，这次会更在意{style}"
        return f"我是{name}"
    if label == "抖音":
        if focus:
            return f"我是{name}，平时就盯{focus}"
        return f"我是{name}"
    if label == "快手":
        if focus:
            return f"我是{name}，平时就爱折腾{focus}"
        return f"我是{name}"
    if label == "视频号":
        if identity and primary_platform:
            return f"我是{name}，{identity}，主内容阵地在{primary_platform}"
        if identity and focus:
            return f"我是{name}，{identity}，长期关注{focus}"
        if primary_platform:
            return f"我是{name}，主内容阵地在{primary_platform}"
        return f"我是{name}"
    if identity and focus:
        return f"我是{name}，{identity}，长期关注{focus}"
    if identity:
        return f"我是{name}，{identity}"
    if focus:
        return f"我是{name}，长期关注{focus}"
    return f"我是{name}"


def _author_public_name(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    return (
        str(identity.get("public_name") or "").strip()
        or str(personal.get("public_name") or "").strip()
        or str(profile.get("presenter_alias") or "").strip()
        or str(profile.get("display_name") or "").strip()
    )


def _author_identity(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    identity_profile = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    title = str(identity_profile.get("title") or personal.get("title") or "").strip()
    organization = str(identity_profile.get("organization") or personal.get("organization") or "").strip()
    experience = str(personal.get("experience") or "").strip()
    achievements = str(personal.get("achievements") or "").strip()
    if organization and title:
        return f"{organization}{title}"
    if title:
        return title
    if organization:
        return organization
    if experience:
        return experience
    if achievements and len(achievements) <= 20:
        return achievements
    return ""


def _author_focus(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    identity = creator_profile.get("identity") if isinstance(creator_profile.get("identity"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    creator_focus = str(positioning.get("creator_focus") or personal.get("creator_focus") or "").strip()
    if creator_focus:
        return creator_focus
    expertise = positioning.get("expertise") if isinstance(positioning.get("expertise"), list) else personal.get("expertise")
    if isinstance(expertise, list):
        topics = [str(item).strip() for item in expertise if str(item).strip()]
        if topics:
            return "、".join(topics[:3])
    bio = str(identity.get("bio") or personal.get("bio") or "").strip()
    if bio and len(bio) <= 24:
        return bio
    return ""


def _author_style(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    positioning = creator_profile.get("positioning") if isinstance(creator_profile.get("positioning"), dict) else {}
    personal = profile.get("personal_info") if isinstance(profile.get("personal_info"), dict) else {}
    return (
        str(positioning.get("style") or personal.get("style") or "").strip()
        or str(positioning.get("audience") or personal.get("audience") or "").strip()
        or str(creator_profile.get("archive_notes") or personal.get("extra_notes") or "").strip()
    )


def _author_primary_platform(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("primary_platform") or "").strip()


def _author_default_call_to_action(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("default_call_to_action") or "").strip()


def _author_description_strategy(author_profile: dict[str, Any] | None) -> str:
    profile = author_profile if isinstance(author_profile, dict) else {}
    creator_profile = profile.get("creator_profile") if isinstance(profile.get("creator_profile"), dict) else {}
    publishing = creator_profile.get("publishing") if isinstance(creator_profile.get("publishing"), dict) else {}
    return str(publishing.get("description_strategy") or "").strip()


def _build_packaging_creative_guidance_text(content_profile: dict[str, Any] | None) -> str:
    preferences = merge_content_profile_creative_preferences(content_profile)
    if not preferences:
        return "已学习创作偏好：无。"
    lines = ["已学习创作偏好（优先体现在标题角度、简介重点和表达节奏上）："]
    for item in preferences[:6]:
        label = str(item.get("label") or item.get("tag") or "").strip()
        guidance = str(item.get("guidance") or "").strip()
        if label and guidance:
            lines.append(f"- {label}：{guidance}")
        elif label:
            lines.append(f"- {label}")
    return "\n".join(lines)


def _creative_preference_tags(content_profile: dict[str, Any] | None) -> set[str]:
    return {
        str(item.get("tag") or "").strip()
        for item in merge_content_profile_creative_preferences(content_profile)
        if str(item.get("tag") or "").strip()
    }


def _creative_preference_title_angle(content_profile: dict[str, Any] | None, *, label: str) -> str:
    tags = _creative_preference_tags(content_profile)
    if "workflow_breakdown" in tags:
        mapping = {
            "B站": "关键步骤拆开讲",
            "小红书": "流程重点先看",
            "抖音": "步骤先拆给你看",
            "快手": "流程我给你讲明白",
            "视频号": "流程重点总结",
        }
        return mapping.get(label, "")
    if "comparison_focus" in tags:
        mapping = {
            "B站": "版本差异一次说清",
            "小红书": "版本差异先看",
            "抖音": "差异直接看",
            "快手": "差异我直说",
            "视频号": "版本差异总结",
        }
        return mapping.get(label, "")
    if "closeup_focus" in tags:
        mapping = {
            "B站": "近景细节一次看清",
            "小红书": "近景细节先看",
            "抖音": "近景细节直接看",
            "快手": "细节我拉近给你看",
            "视频号": "近景细节记录",
        }
        return mapping.get(label, "")
    if "practical_demo" in tags:
        mapping = {
            "B站": "上手实测重点看",
            "小红书": "上手实测先看",
            "抖音": "实测结果先看",
            "快手": "上手实测我直说",
            "视频号": "上手实测总结",
        }
        return mapping.get(label, "")
    return ""


def _creative_preference_description_focus(content_profile: dict[str, Any] | None) -> str:
    tags = _creative_preference_tags(content_profile)
    if not tags:
        return ""
    if "workflow_breakdown" in tags:
        return "流程步骤、节点逻辑和关键判断"
    parts: list[str] = []
    if "comparison_focus" in tags:
        parts.append("版本差异和选择取舍")
    if "closeup_focus" in tags:
        parts.append("近景细节和做工特写")
    elif "detail_focus" in tags:
        parts.append("细节、做工和结构")
    if "practical_demo" in tags:
        parts.append("上手实测和实际使用场景")
    if "conclusion_first" in tags and not parts:
        parts.append("核心判断和关键依据")
    return "、".join(parts[:3])


def build_fallback_titles(*, label: str, content_profile: dict[str, Any] | None, copy_style: str = "attention_grabbing") -> list[str]:
    if not _has_specific_subject_identity(content_profile):
        return _build_neutral_fallback_titles(label=label, copy_style=copy_style)

    product = _preferred_product_label(content_profile, label=label) or "这款产品"
    subject = _preferred_subject_label(content_profile) or "产品"
    hook = _build_confirmed_title_hook(content_profile)
    headline_hook = _copy_style_headline_hook(copy_style, hook=hook, brand=product, subject=subject)
    creative_title_angle = _creative_preference_title_angle(content_profile, label=label)

    if label == "B站":
        return [
            f"{product}：{headline_hook}",
            f"{product}{creative_title_angle or _copy_style_bilibili_angle(copy_style)}",
            f"{product}上手体验，{_copy_style_explainer(copy_style)}",
            f"{_copy_style_waiting_angle(copy_style, subject)}",
            f"{product}{_copy_style_record_angle(copy_style)}",
        ]
    if label == "小红书":
        return [
            _copy_style_xhs_title(copy_style, brand=product, subject=subject),
            f"{product}{_copy_style_texture_angle(copy_style)}",
            creative_title_angle or _copy_style_waiting_angle(copy_style, subject),
            f"玩家向{subject}开箱，{_copy_style_detail_angle(copy_style)}",
            f"{product}到手分享，{_copy_style_judgement_angle(copy_style)}",
        ]
    if label == "抖音":
        return [
            f"{product}{_copy_style_short_burst(copy_style)}",
            creative_title_angle or _copy_style_waiting_angle(copy_style, subject),
            f"{product}{_copy_style_judgement_angle(copy_style)}",
            f"{_copy_style_unboxing_burst(copy_style)}",
            f"{subject}到手先看{_copy_style_detail_focus(copy_style)}",
        ]
    if label == "快手":
        return [
            f"给你们看个真东西：{product}",
            creative_title_angle or _copy_style_waiting_angle(copy_style, subject),
            f"{product}{_copy_style_judgement_angle(copy_style)}",
            f"这次开箱我{_copy_style_explainer(copy_style)}",
            f"{subject}{_copy_style_truth_angle(copy_style)}",
        ]
    return [
        f"{product}{_copy_style_record_angle(copy_style)}",
        f"{product}到手体验",
        f"这把{subject}{_copy_style_judgement_angle(copy_style)}",
        f"{product}{_copy_style_detail_angle(copy_style)}",
        f"{subject}开箱与上手记录",
    ]


def build_fallback_description(
    *,
    label: str,
    content_profile: dict[str, Any] | None,
    copy_style: str = "attention_grabbing",
    author_profile: dict[str, Any] | None = None,
) -> str:
    question = _fallback_question_with_author(content_profile, author_profile)
    creative_focus = _creative_preference_description_focus(content_profile)
    if not _has_specific_subject_identity(content_profile):
        if creative_focus:
            if label == "小红书":
                description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、{creative_focus}。不硬写产品名，只聊这次最值得分享的几个重点。{question}"
                return _inject_author_context_into_description(label, description, author_profile)
            if label == "抖音":
                description = f"{_copy_style_opening(copy_style)}这条直接看{creative_focus}，最值得继续看的重点都压在这一条里。{question}"
                return _inject_author_context_into_description(label, description, author_profile)
            if label == "快手":
                description = f"{_copy_style_opening(copy_style)}这期不瞎补产品信息，直接看{creative_focus}，能看懂的地方我都给你摆明白。{question}"
                return _inject_author_context_into_description(label, description, author_profile)
            if label == "视频号":
                description = f"{_copy_style_opening(copy_style)}这次分享一条开箱上手视频，重点看{creative_focus}，方便你快速做判断。{question}"
                return _inject_author_context_into_description(label, description, author_profile)
            description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、{creative_focus}，只说视频里能确认的内容和最值得讨论的重点。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "小红书":
            description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、外观细节和真实上手感受。不硬写产品名，只聊这次到手后最值得分享的那几个瞬间。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "抖音":
            description = f"{_copy_style_opening(copy_style)}这条就先把重点打出来：开箱细节、真实体验、值不值得继续看，都压在这一条里。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "快手":
            description = f"{_copy_style_opening(copy_style)}这期不瞎补产品信息，直接看开箱细节、做工表现和真实上手感受，能看懂的地方我都给你摆明白。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "视频号":
            description = f"{_copy_style_opening(copy_style)}这次分享一条开箱上手视频，重点放在外观细节、质感和真实体验，方便你快速判断值不值得继续关注。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        description = f"{_copy_style_opening(copy_style)}这期先看开箱过程、细节表现和真实上手感受，不编产品名，只说视频里能确认的内容和最值得讨论的重点。{question}"
        return _inject_author_context_into_description(label, description, author_profile)

    product = _preferred_product_label(content_profile, label=label) or "这款产品"
    if creative_focus:
        if label == "小红书":
            description = f"{_copy_style_opening(copy_style)}{product}终于到手，重点看{creative_focus}。不是硬广，更像一次有质感的真实开箱分享。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "抖音":
            description = f"{_copy_style_opening(copy_style)}这次就看{product}到底值不值，重点看{creative_focus}，最狠的内容都压进这一条里了。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "快手":
            description = f"{_copy_style_opening(copy_style)}给大家看个真东西，这次开箱的是{product}，重点就聊{creative_focus}，我按实话给你讲。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        if label == "视频号":
            description = f"{_copy_style_opening(copy_style)}这次分享一条{product}开箱视频，重点看{creative_focus}，方便快速做判断。{question}"
            return _inject_author_context_into_description(label, description, author_profile)
        description = f"{_copy_style_opening(copy_style)}这次开箱的是{product}，视频里重点看{creative_focus}和核心判断。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "小红书":
        description = f"{_copy_style_opening(copy_style)}{product}终于到手，重点看外观、细节和上手感受。不是硬广，更像一次有质感的真实开箱分享。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "抖音":
        description = f"{_copy_style_opening(copy_style)}这次就看{product}到底值不值，最狠的细节和真实体验都压进这一条里了。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "快手":
        description = f"{_copy_style_opening(copy_style)}给大家看个真东西，这次开箱的是{product}，值不值、细节咋样，我就按实话给你讲。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    if label == "视频号":
        description = f"{_copy_style_opening(copy_style)}这次分享一条{product}开箱视频，重点看细节、质感和真实上手体验，方便快速做判断。{question}"
        return _inject_author_context_into_description(label, description, author_profile)
    description = f"{_copy_style_opening(copy_style)}这次开箱的是{product}，视频里把到手细节、上手感受和核心判断都说清楚了。{question}"
    return _inject_author_context_into_description(label, description, author_profile)


def _fallback_product(content_profile: dict[str, Any] | None, *, label: str | None = None) -> str:
    brand_raw = str((content_profile or {}).get("subject_brand") or "").strip()
    brand = _localized_brand_label(brand_raw, label=label or "", content_profile=content_profile) if label else brand_raw
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject = _specific_subject_type(content_profile)
    return " ".join(part for part in (brand, model or subject) if part).strip()


def _preferred_product_label(content_profile: dict[str, Any] | None, label: str | None = None) -> str:
    return _fallback_product(content_profile, label=label)


def _preferred_subject_label(content_profile: dict[str, Any] | None) -> str:
    profile = content_profile or {}
    return (
        str(profile.get("subject_model") or "").strip()
        or _specific_subject_type(profile)
        or str(profile.get("subject_type") or "").strip()
        or "产品"
    )


def _normalize_highlight_product(value: Any, content_profile: dict[str, Any] | None) -> str:
    if not _has_specific_subject_identity(content_profile):
        return ""
    return str(value or _fallback_product(content_profile, label="B站")).strip()


def _fallback_video_type(content_profile: dict[str, Any] | None) -> str:
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    return theme or "开箱体验"


def _fallback_question(content_profile: dict[str, Any] | None) -> str:
    question = str((content_profile or {}).get("engagement_question") or "").strip()
    return question or "你觉得这次到手值不值？"


def _fallback_question_with_author(
    content_profile: dict[str, Any] | None,
    author_profile: dict[str, Any] | None,
) -> str:
    return _author_default_call_to_action(author_profile) or _fallback_question(content_profile)


def _has_specific_subject_identity(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile or {}
    if str(profile.get("subject_brand") or "").strip():
        return True
    if str(profile.get("subject_model") or "").strip():
        return True
    return bool(_specific_subject_type(profile))


def _specific_subject_type(content_profile: dict[str, Any] | None) -> str:
    subject = str((content_profile or {}).get("subject_type") or "").strip()
    if not subject:
        return ""
    generic_subjects = {
        "开箱",
        "开箱产品",
        "产品",
        "工具",
        "东西",
        "玩意",
        "单品",
        "EDC",
        "刀具",
        "装备",
        "物件",
    }
    normalized = subject.replace(" ", "")
    if normalized in generic_subjects or normalized.startswith("开箱"):
        return ""
    return subject


def _profile_mentions_edc(content_profile: dict[str, Any] | None) -> bool:
    profile = content_profile or {}
    fields = (
        profile.get("subject_type"),
        profile.get("video_theme"),
        profile.get("summary"),
    )
    return any("EDC" in str(value or "").upper() for value in fields)


def _build_neutral_fallback_titles(*, label: str, copy_style: str = "attention_grabbing") -> list[str]:
    if label == "B站":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱重点看哪些细节",
            "到手先别下结论，先看做工和外观",
            "这次上手体验到底怎么样",
            "不开脑补，只聊视频里能确认的内容",
            "这期开箱值不值得继续深挖",
        ]
    if label == "小红书":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看外观和细节",
            "到手第一眼先看做工表现",
            "不瞎补产品名，只聊这次上手感受",
            "这期开箱的质感和细节我先拍给你看",
            "先把细节看清，再聊值不值",
        ]
    if label == "抖音":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看细节",
            "到手先看做工表现",
            "不先下结论，先上手",
            "这次开箱重点都在这里",
            "先把外观和手感看清",
        ]
    if label == "快手":
        return [
            f"{_copy_style_neutral_hook(copy_style)}这期开箱先看真细节",
            "不瞎补名字，先看上手表现",
            "到手先把做工看明白",
            "这次开箱我只说能确认的",
            "先看细节，再聊值不值",
        ]
    return [
        f"{_copy_style_neutral_hook(copy_style)}这期开箱先看细节",
        "到手先看外观和做工",
        "这次上手体验到底怎么样",
        "不编产品名，只聊真实表现",
        "先把重点细节看清楚",
    ]


def _dedupe_non_empty(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _build_confirmed_title_hook(content_profile: dict[str, Any] | None) -> str:
    hook = str((content_profile or {}).get("hook_line") or "").strip()
    if hook and _contains_confirmed_product_anchor(hook, content_profile):
        return hook
    return "这次重点看哪些细节"


def _contains_confirmed_product_anchor(text: str, content_profile: dict[str, Any] | None) -> bool:
    anchors = _build_confirmed_identity_anchors(content_profile)
    required = [anchor for anchor in (anchors.get("model"), anchors.get("brand")) if anchor]
    if not required:
        return True
    normalized = _normalize_anchor_text(text)
    return required[0] in normalized


def _build_confirmed_identity_anchors(content_profile: dict[str, Any] | None) -> dict[str, str]:
    profile = content_profile or {}
    return {
        "brand": _primary_anchor_token(str(profile.get("subject_brand") or "")),
        "model": _primary_anchor_token(str(profile.get("subject_model") or "")),
    }


def _primary_anchor_token(text: str) -> str:
    normalized = _normalize_anchor_text(text)
    if not normalized:
        return ""
    alpha_numeric = re.findall(r"[a-z0-9]+", normalized)
    for token in alpha_numeric:
        if len(token) >= 3 and not token.isdigit():
            return token
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", normalized)
    if cjk_runs:
        return max(cjk_runs, key=len)
    return normalized if len(normalized) >= 2 else ""


def _normalize_anchor_text(text: str) -> str:
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", str(text or "").lower())


def _hashify_tags(tags: list[str]) -> list[str]:
    return [item if item.startswith("#") else f"#{item}" for item in tags if item]


def _copy_style_instruction(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "吸引眼球：允许强爆点、强情绪、强反差，但不编造事实。",
        "balanced": "平衡稳妥：有吸引力，但不过度浮夸，优先清晰和自然。",
        "premium_editorial": "高级编辑感：克制、干净、像杂志编辑或品牌文案。",
        "trusted_expert": "专业可信：更像经验分享和专家拆解，少营销腔。",
        "playful_meme": "轻松玩梗：允许更口语、更俏皮、更有网感。",
        "emotional_story": "情绪叙事：更强调经历、等待、惊喜、落差和感受。",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _platform_bias_instruction(label: str) -> str:
    mapping = {
        "B站": "信息密度更高，强调拆解、讲清逻辑、适合教程和深度说明。",
        "小红书": "更重质感、分享感和情绪共鸣，像真体验笔记。",
        "抖音": "更短更快更有爆点，先给结果和记忆点。",
        "快手": "更接地气、更直给，像当面把真实体验讲明白。",
        "视频号": "更稳妥可信，适合快速概括重点和结论。",
        "头条号": "更像资讯摘要或观点导语，适合先抛判断、再补重点。",
        "YouTube": "更强调主题明确、可检索、结构完整，适合 review / hands-on / first look 语气。",
        "X": "更像可直接转发的贴文，先给一个观察或结论，尽量短促。",
    }
    return mapping.get(label, "按平台用户习惯自动调整语气和信息密度。")


def _domain_prompt_voice_instruction(content_profile: dict[str, Any] | None) -> str:
    domain = str((content_profile or {}).get("subject_domain") or "").strip().lower()
    mapping = {
        "edc": "内容按 EDC/装备体验类创作者口吻处理，强调上手体验、细节和真实判断。",
        "outdoor": "内容按户外装备体验类创作者口吻处理，强调场景、耐用性和实际使用感受。",
        "tech": "内容按数码科技内容口吻处理，强调设备体验、关键差异、参数判断和真实感受。",
        "ai": "内容按 AI领域内容口吻处理，强调工作流、模型能力、使用门槛、实际效果和结论。",
        "functional": "内容按机能/包袋/穿搭体验口吻处理，强调收纳、搭配、做工和使用场景。",
        "tools": "内容按工具实测内容口吻处理，强调结构、手感、功能点和真实上手体验。",
        "food": "内容按美食体验口吻处理，强调口感、环境、流程和真实评价。",
        "travel": "内容按旅行/生活记录口吻处理，强调行程体验、信息效率和实用建议。",
        "finance": "内容按财经解读口吻处理，强调结论、逻辑和信息边界。",
        "news": "内容按新闻速览口吻处理，强调信息密度、事实边界和结论摘要。",
        "sports": "内容按体育内容口吻处理，强调关键回合、结果和观感。",
    }
    return mapping.get(domain, "内容按当前视频所属领域的真实创作者口吻处理，强调信息准确、自然表达和平台适配。")


def _copy_style_headline_hook(copy_style: str, *, hook: str, brand: str, subject: str) -> str:
    if copy_style == "balanced":
        return hook or f"{subject}这次重点说清楚"
    if copy_style == "premium_editorial":
        return f"{subject}这次很值得看"
    if copy_style == "trusted_expert":
        return f"{subject}关键差异讲明白"
    if copy_style == "playful_meme":
        return f"{subject}这次真有点狠"
    if copy_style == "emotional_story":
        return f"{subject}这次真的等很久"
    return hook or f"{brand}{subject}这次太狠了"


def _copy_style_bilibili_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "到底强得有多离谱",
        "balanced": "到底值不值得看",
        "premium_editorial": "这次有哪些细节变化",
        "trusted_expert": "核心差异一次讲清",
        "playful_meme": "这次是不是有点太猛",
        "emotional_story": "等了这么久到底值不值",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_explainer(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "优缺点一次说透",
        "balanced": "优缺点一次说清",
        "premium_editorial": "细节变化慢慢拆开",
        "trusted_expert": "核心逻辑讲明白",
        "playful_meme": "爽点和坑点都掰开说",
        "emotional_story": "我为什么会被它打动都说清楚",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_waiting_angle(copy_style: str, subject: str) -> str:
    mapping = {
        "attention_grabbing": f"等了很久才到手，这把{subject}太狠了",
        "balanced": f"等了很久才到手，这把{subject}怎么样",
        "premium_editorial": f"这把{subject}到手后，第一眼细节很加分",
        "trusted_expert": f"这把{subject}到手后，先看几个关键点",
        "playful_meme": f"这把{subject}我真等麻了",
        "emotional_story": f"等了很久，这把{subject}终于到手了",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_record_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "开箱+真实暴击体验",
        "balanced": "开箱+真实体验记录",
        "premium_editorial": "到手观察与细节记录",
        "trusted_expert": "实测记录与判断",
        "playful_meme": "开箱实录，真的有点顶",
        "emotional_story": "到手后的第一天记录",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_texture_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "摆上桌直接杀疯了",
        "balanced": "摆上桌，质感一下就出来了",
        "premium_editorial": "摆上桌，整体气质立刻出来了",
        "trusted_expert": "摆上桌，几个关键细节很清楚",
        "playful_meme": "摆上桌真的太会了",
        "emotional_story": "摆上桌那一刻真的有点感动",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_detail_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "细节党真的会看上头",
        "balanced": "细节控真的会看很久",
        "premium_editorial": "细节质感会让人慢慢看很久",
        "trusted_expert": "几个细节位都值得放大看",
        "playful_meme": "细节党直接爽飞",
        "emotional_story": "细节越看越容易上头",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_judgement_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "到底香不香",
        "balanced": "值不值我直说",
        "premium_editorial": "到底值不值得收藏",
        "trusted_expert": "到底值不值得入手",
        "playful_meme": "到底顶不顶",
        "emotional_story": "到底值不值我这段等待",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_short_burst(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "直接炸场",
        "balanced": "终于到手",
        "premium_editorial": "很值得看",
        "trusted_expert": "先看关键差异",
        "playful_meme": "真的有点狠",
        "emotional_story": "终于轮到我了",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_unboxing_burst(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "这次开箱直接上头",
        "balanced": "这次开箱有点上头",
        "premium_editorial": "这次开箱的质感很在线",
        "trusted_expert": "这次开箱先看几个重点",
        "playful_meme": "这次开箱真的有梗",
        "emotional_story": "这次开箱真有点感慨",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_detail_focus(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "最狠细节",
        "balanced": "细节",
        "premium_editorial": "关键细节",
        "trusted_expert": "核心细节",
        "playful_meme": "爽点细节",
        "emotional_story": "最打动人的细节",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_truth_angle(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "值不值我直接摊牌",
        "balanced": "值不值，咱实话实说",
        "premium_editorial": "到底值不值得慢慢看",
        "trusted_expert": "到底值不值得入手",
        "playful_meme": "到底顶不顶，咱不装了",
        "emotional_story": "值不值，这次我想认真聊聊",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])


def _copy_style_opening(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "先说结论，",
        "balanced": "",
        "premium_editorial": "如果只看重点，",
        "trusted_expert": "先把核心判断放前面，",
        "playful_meme": "先别急着划走，",
        "emotional_story": "说实话，",
    }
    return mapping.get(copy_style, "")


def _copy_style_neutral_hook(copy_style: str) -> str:
    mapping = {
        "attention_grabbing": "先说重点，",
        "balanced": "",
        "premium_editorial": "如果只看重点，",
        "trusted_expert": "先看核心信息，",
        "playful_meme": "先别滑走，",
        "emotional_story": "先从感受说起，",
    }
    return mapping.get(copy_style, "")


def _copy_style_xhs_title(copy_style: str, *, brand: str, subject: str) -> str:
    merged = brand
    normalized_brand = _normalize_anchor_text(brand)
    normalized_subject = _normalize_anchor_text(subject)
    if subject and normalized_subject and normalized_subject not in normalized_brand:
        merged = f"{brand}{subject}"
    mapping = {
        "attention_grabbing": f"{merged}终于到手，细节直接封神",
        "balanced": f"这把{subject}终于到手，细节真的很顶",
        "premium_editorial": f"{merged}到手后，气质一下就出来了",
        "trusted_expert": f"{merged}到手后，先看这几个关键点",
        "playful_meme": f"{merged}到手后真的有点离谱",
        "emotional_story": f"{merged}终于到手，这次真的等很久",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])
