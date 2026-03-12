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
    return normalize_platform_packaging(response.as_json(), content_profile=content_profile)


def normalize_platform_packaging(
    raw: dict[str, Any],
    *,
    content_profile: dict[str, Any] | None,
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
        titles = _normalize_titles(platform_raw.get("titles"), label=label, content_profile=content_profile)
        description = str(platform_raw.get("description") or "").strip()
        if not description:
            description = build_fallback_description(label=label, content_profile=content_profile)
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


def _normalize_titles(value: Any, *, label: str, content_profile: dict[str, Any] | None) -> list[str]:
    titles = [str(item).strip() for item in (value or []) if str(item).strip()]
    if len(titles) >= 5:
        return titles[:5]

    fallback = build_fallback_titles(label=label, content_profile=content_profile)
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


def build_fallback_titles(*, label: str, content_profile: dict[str, Any] | None) -> list[str]:
    if not _has_specific_subject_identity(content_profile):
        return _build_neutral_fallback_titles(label=label)

    brand = str((content_profile or {}).get("subject_brand") or "").strip() or "这把"
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "产品"
    hook = str((content_profile or {}).get("hook_line") or "这次升级到位吗").strip()

    if label == "B站":
        return [
            f"{brand}{subject}开箱：{hook}",
            f"{brand}{subject}到底值不值",
            f"{brand}{subject}上手体验，优缺点一次说清",
            f"等了很久才到手，这把{subject}怎么样",
            f"{brand}{subject}开箱+真实体验记录",
        ]
    if label == "小红书":
        return [
            f"这把{subject}终于到手，细节真的很顶",
            f"{brand}{subject}摆上桌，质感一下就出来了",
            f"等了很久的{subject}，这次终于开箱了",
            f"玩家向{subject}开箱，细节控真的会看很久",
            f"{brand}{subject}到手分享，值不值我直说",
        ]
    if label == "抖音":
        return [
            f"{brand}{subject}终于到手",
            f"这把{subject}我等很久了",
            f"{brand}{subject}值不值",
            f"这次开箱有点上头",
            f"{subject}到手先看细节",
        ]
    if label == "快手":
        return [
            f"给你们看个真东西：{brand}{subject}",
            f"这把{subject}终于到手了",
            f"{brand}{subject}到底咋样",
            f"这次开箱我直接说结论",
            f"{subject}值不值，咱实话实说",
        ]
    return [
        f"{brand}{subject}开箱分享",
        f"{brand}{subject}到手体验",
        f"这把{subject}值不值",
        f"{brand}{subject}细节实拍",
        f"{subject}开箱与上手记录",
    ]


def build_fallback_description(*, label: str, content_profile: dict[str, Any] | None) -> str:
    question = _fallback_question(content_profile)
    if not _has_specific_subject_identity(content_profile):
        if label == "小红书":
            return f"这期先看开箱过程、外观细节和真实上手感受。不硬写产品名，只聊这次到手后最值得看的部分。{question}"
        if label == "抖音":
            return f"这次就把开箱细节和真实体验放在一条视频里，不先下死结论，先把重点看清楚。{question}"
        if label == "快手":
            return f"这期不瞎补产品信息，直接看开箱细节、做工表现和真实上手感受。{question}"
        if label == "视频号":
            return f"这次分享一条开箱上手视频，重点放在外观细节、质感和真实体验。{question}"
        return f"这期先看开箱过程、细节表现和真实上手感受，不编产品名，只说视频里能确认的内容。{question}"

    brand = str((content_profile or {}).get("subject_brand") or "").strip() or "这把"
    subject = _specific_subject_type(content_profile) or str((content_profile or {}).get("subject_type") or "").strip() or "产品"
    if label == "小红书":
        return f"{brand}{subject}终于到手，重点看外观、细节和上手感受。不是硬广，就是玩家视角的真实开箱分享。{question}"
    if label == "抖音":
        return f"这次就看{brand}{subject}到底值不值，开箱细节和真实体验都放进去了。{question}"
    if label == "快手":
        return f"给大家看个真东西，这次开箱的是{brand}{subject}，值不值、细节咋样，我直接说。{question}"
    if label == "视频号":
        return f"这次分享一条{brand}{subject}开箱视频，重点看细节、质感和真实上手体验。{question}"
    return f"这次开箱的是{brand}{subject}，视频里把到手细节、上手感受和真实想法都说清楚了。{question}"


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


def _build_neutral_fallback_titles(*, label: str) -> list[str]:
    if label == "B站":
        return [
            "这期开箱重点看哪些细节",
            "到手先别下结论，先看做工和外观",
            "这次上手体验到底怎么样",
            "不开脑补，只聊视频里能确认的内容",
            "这期开箱值不值得继续深挖",
        ]
    if label == "小红书":
        return [
            "这期开箱先看外观和细节",
            "到手第一眼先看做工表现",
            "不瞎补产品名，只聊这次上手感受",
            "这期开箱的质感和细节我先拍给你看",
            "先把细节看清，再聊值不值",
        ]
    if label == "抖音":
        return [
            "这期开箱先看细节",
            "到手先看做工表现",
            "不先下结论，先上手",
            "这次开箱重点都在这里",
            "先把外观和手感看清",
        ]
    if label == "快手":
        return [
            "这期开箱先看真细节",
            "不瞎补名字，先看上手表现",
            "到手先把做工看明白",
            "这次开箱我只说能确认的",
            "先看细节，再聊值不值",
        ]
    return [
        "这期开箱先看细节",
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
