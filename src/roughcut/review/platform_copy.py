from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from roughcut.providers.factory import get_reasoning_provider
from roughcut.providers.reasoning.base import Message

PLATFORM_ORDER = [
    ("bilibili", "B站", "简介", "标签"),
    ("xiaohongshu", "小红书", "正文", "话题"),
    ("douyin", "抖音", "简介", "标签"),
    ("kuaishou", "快手", "简介", "标签"),
    ("wechat_channels", "视频号", "简介", "标签"),
]


def build_transcript_for_packaging(subtitle_items: list[dict[str, Any]], *, max_chars: int = 6000) -> str:
    lines: list[str] = []
    total = 0
    for item in subtitle_items:
        text = (item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        line = f"[{item.get('start_time', 0):.1f}-{item.get('end_time', 0):.1f}] {text}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


async def generate_platform_packaging(
    *,
    source_name: str,
    content_profile: dict[str, Any] | None,
    subtitle_items: list[dict[str, Any]],
    copy_style: str = "attention_grabbing",
) -> dict[str, Any]:
    provider = get_reasoning_provider()
    transcript_text = build_transcript_for_packaging(subtitle_items)
    prompt = (
        "你是多平台视频包装官，负责把字幕整理成适合不同平台发布的标题、简介和标签。"
        "内容默认按 EDC、刀具、工具、桌搭、开箱、收藏类创作者口吻处理。"
        "要求：\n"
        "1. 输出真实自然，不要像硬广，不编造事实。\n"
        "2. 刀具、EDC、工具相关内容必须保守合规，避免危险导向表述。\n"
        "3. 每个平台必须提供 5 个标题、1 段简介/正文、1 组标签。\n"
        "4. 标题要有角度差异：爆点型、稳妥型、提问型、情绪型、结论型。\n"
        "5. 标签必须贴合产品、品类、场景、风格、视频类型。\n"
        "6. 不要输出空字段。\n\n"
        f"本次统一文案风格：{_copy_style_instruction(copy_style)}\n\n"
        "默认平台偏置：\n"
        f"- B站：{_platform_bias_instruction('B站')}\n"
        f"- 小红书：{_platform_bias_instruction('小红书')}\n"
        f"- 抖音：{_platform_bias_instruction('抖音')}\n"
        f"- 快手：{_platform_bias_instruction('快手')}\n"
        f"- 视频号：{_platform_bias_instruction('视频号')}\n\n"
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
        "\"wechat_channels\":{\"titles\":[\"\"],\"description\":\"\",\"tags\":[\"\"]}"
        "}"
        "}\n\n"
        f"视频已知信息：{json.dumps(content_profile or {}, ensure_ascii=False)}\n"
        f"源文件名：{source_name}\n"
        f"字幕全文：\n{transcript_text}"
    )
    response = await provider.complete(
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
    )
    return normalize_platform_packaging(response.as_json(), content_profile=content_profile, copy_style=copy_style)


def normalize_platform_packaging(
    raw: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
    copy_style: str = "attention_grabbing",
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
        description = str(platform_raw.get("description") or "").strip()
        if not description:
            description = build_fallback_description(label=label, content_profile=content_profile, copy_style=copy_style)
        tags = _normalize_tags(platform_raw.get("tags"), content_profile=content_profile)
        normalized["platforms"][key] = {
            "titles": titles,
            "description": description,
            "tags": tags,
        }

    return normalized


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


def _normalize_titles(value: Any, *, label: str, content_profile: dict[str, Any] | None, copy_style: str) -> list[str]:
    titles = [str(item).strip() for item in (value or []) if str(item).strip()]
    if len(titles) >= 5:
        return titles[:5]

    fallback = build_fallback_titles(label=label, content_profile=content_profile, copy_style=copy_style)
    seen: set[str] = set()
    merged: list[str] = []
    for title in titles + fallback:
        if title not in seen:
            seen.add(title)
            merged.append(title)
        if len(merged) >= 5:
            break
    return merged


def _normalize_tags(value: Any, content_profile: dict[str, Any] | None) -> list[str]:
    tags = [str(item).strip().lstrip("#") for item in (value or []) if str(item).strip()]
    if tags:
        return tags

    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    subject = _specific_subject_type(content_profile)
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    fallback = [brand, subject, theme]
    if _profile_mentions_edc(content_profile):
        fallback.append("EDC")
    fallback.extend(["开箱", "上手体验", "玩家分享"])
    return _dedupe_non_empty(fallback)[:8]


def build_fallback_titles(*, label: str, content_profile: dict[str, Any] | None, copy_style: str = "attention_grabbing") -> list[str]:
    if not _has_specific_subject_identity(content_profile):
        return _build_neutral_fallback_titles(label=label, copy_style=copy_style)

    brand = str((content_profile or {}).get("subject_brand") or "").strip() or "这把"
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "产品"
    hook = str((content_profile or {}).get("hook_line") or "这次升级到位吗").strip()
    headline_hook = _copy_style_headline_hook(copy_style, hook=hook, brand=brand, subject=subject)

    if label == "B站":
        return [
            f"{brand}{subject}：{headline_hook}",
            f"{brand}{subject}{_copy_style_bilibili_angle(copy_style)}",
            f"{brand}{subject}上手体验，{_copy_style_explainer(copy_style)}",
            f"{_copy_style_waiting_angle(copy_style, subject)}",
            f"{brand}{subject}{_copy_style_record_angle(copy_style)}",
        ]
    if label == "小红书":
        return [
            _copy_style_xhs_title(copy_style, brand=brand, subject=subject),
            f"{brand}{subject}{_copy_style_texture_angle(copy_style)}",
            _copy_style_waiting_angle(copy_style, subject),
            f"玩家向{subject}开箱，{_copy_style_detail_angle(copy_style)}",
            f"{brand}{subject}到手分享，{_copy_style_judgement_angle(copy_style)}",
        ]
    if label == "抖音":
        return [
            f"{brand}{subject}{_copy_style_short_burst(copy_style)}",
            _copy_style_waiting_angle(copy_style, subject),
            f"{brand}{subject}{_copy_style_judgement_angle(copy_style)}",
            f"{_copy_style_unboxing_burst(copy_style)}",
            f"{subject}到手先看{_copy_style_detail_focus(copy_style)}",
        ]
    if label == "快手":
        return [
            f"给你们看个真东西：{brand}{subject}",
            _copy_style_waiting_angle(copy_style, subject),
            f"{brand}{subject}{_copy_style_judgement_angle(copy_style)}",
            f"这次开箱我{_copy_style_explainer(copy_style)}",
            f"{subject}{_copy_style_truth_angle(copy_style)}",
        ]
    return [
        f"{brand}{subject}{_copy_style_record_angle(copy_style)}",
        f"{brand}{subject}到手体验",
        f"这把{subject}{_copy_style_judgement_angle(copy_style)}",
        f"{brand}{subject}{_copy_style_detail_angle(copy_style)}",
        f"{subject}开箱与上手记录",
    ]


def build_fallback_description(*, label: str, content_profile: dict[str, Any] | None, copy_style: str = "attention_grabbing") -> str:
    question = _fallback_question(content_profile)
    if not _has_specific_subject_identity(content_profile):
        if label == "小红书":
            return f"{_copy_style_opening(copy_style)}这期先看开箱过程、外观细节和真实上手感受。不硬写产品名，只聊这次到手后最值得分享的那几个瞬间。{question}"
        if label == "抖音":
            return f"{_copy_style_opening(copy_style)}这条就先把重点打出来：开箱细节、真实体验、值不值得继续看，都压在这一条里。{question}"
        if label == "快手":
            return f"{_copy_style_opening(copy_style)}这期不瞎补产品信息，直接看开箱细节、做工表现和真实上手感受，能看懂的地方我都给你摆明白。{question}"
        if label == "视频号":
            return f"{_copy_style_opening(copy_style)}这次分享一条开箱上手视频，重点放在外观细节、质感和真实体验，方便你快速判断值不值得继续关注。{question}"
        return f"{_copy_style_opening(copy_style)}这期先看开箱过程、细节表现和真实上手感受，不编产品名，只说视频里能确认的内容和最值得讨论的重点。{question}"

    brand = str((content_profile or {}).get("subject_brand") or "").strip() or "这把"
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "产品"
    if label == "小红书":
        return f"{_copy_style_opening(copy_style)}{brand}{subject}终于到手，重点看外观、细节和上手感受。不是硬广，更像一次有质感的真实开箱分享。{question}"
    if label == "抖音":
        return f"{_copy_style_opening(copy_style)}这次就看{brand}{subject}到底值不值，最狠的细节和真实体验都压进这一条里了。{question}"
    if label == "快手":
        return f"{_copy_style_opening(copy_style)}给大家看个真东西，这次开箱的是{brand}{subject}，值不值、细节咋样，我就按实话给你讲。{question}"
    if label == "视频号":
        return f"{_copy_style_opening(copy_style)}这次分享一条{brand}{subject}开箱视频，重点看细节、质感和真实上手体验，方便快速做判断。{question}"
    return f"{_copy_style_opening(copy_style)}这次开箱的是{brand}{subject}，视频里把到手细节、上手感受和核心判断都说清楚了。{question}"


def _fallback_product(content_profile: dict[str, Any] | None) -> str:
    brand = str((content_profile or {}).get("subject_brand") or "").strip()
    model = str((content_profile or {}).get("subject_model") or "").strip()
    subject = _specific_subject_type(content_profile)
    return " ".join(part for part in (brand, model or subject) if part).strip()


def _normalize_highlight_product(value: Any, content_profile: dict[str, Any] | None) -> str:
    if not _has_specific_subject_identity(content_profile):
        return ""
    return str(value or _fallback_product(content_profile)).strip()


def _fallback_video_type(content_profile: dict[str, Any] | None) -> str:
    theme = str((content_profile or {}).get("video_theme") or "").strip()
    return theme or "开箱体验"


def _fallback_question(content_profile: dict[str, Any] | None) -> str:
    question = str((content_profile or {}).get("engagement_question") or "").strip()
    return question or "你觉得这次到手值不值？"


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
    }
    return mapping.get(label, "按平台用户习惯自动调整语气和信息密度。")


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
    mapping = {
        "attention_grabbing": f"{brand}{subject}终于到手，细节直接封神",
        "balanced": f"这把{subject}终于到手，细节真的很顶",
        "premium_editorial": f"{brand}{subject}到手后，气质一下就出来了",
        "trusted_expert": f"{brand}{subject}到手后，先看这几个关键点",
        "playful_meme": f"{brand}{subject}到手后真的有点离谱",
        "emotional_story": f"{brand}{subject}终于到手，这次真的等很久",
    }
    return mapping.get(copy_style, mapping["attention_grabbing"])
