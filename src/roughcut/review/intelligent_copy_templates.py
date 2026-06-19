from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlatformDescriptionTone:
    prefix: str
    suffix: str


PLATFORM_DESCRIPTION_TONES: dict[str, PlatformDescriptionTone] = {
    "bilibili": PlatformDescriptionTone(
        prefix="这期主要看{focus_line}。",
        suffix="",
    ),
    "xiaohongshu": PlatformDescriptionTone(
        prefix="这期我会重点看{focus_line}。",
        suffix="如果你也在看同类内容，最关心的是哪一点？",
    ),
    "douyin": PlatformDescriptionTone(
        prefix="这一条直接把{focus_line}讲明白。",
        suffix="{question}",
    ),
    "kuaishou": PlatformDescriptionTone(
        prefix="我就按实话把{focus_line}给你讲清楚。",
        suffix="{question}",
    ),
    "wechat_channels": PlatformDescriptionTone(
        prefix="重点会落在{focus_line}，方便快速判断。",
        suffix="{question}",
    ),
    "toutiao": PlatformDescriptionTone(
        prefix="这期重点就是{focus_line}，结论先行，不绕。",
        suffix="{question}",
    ),
    "youtube": PlatformDescriptionTone(
        prefix="This video focuses on {focus_line}.",
        suffix="{question}",
    ),
    "x": PlatformDescriptionTone(
        prefix="重点就是{focus_line}。",
        suffix="{question}",
    ),
    "default": PlatformDescriptionTone(
        prefix="这期重点看{focus_line}。",
        suffix="{question}",
    ),
}


INTENT_TITLE_TEMPLATES: dict[str, tuple[str, ...]] = {
    "tutorial": (
        "{topic_subject}怎么用？{focus_0}一次讲清",
        "{topic_subject}教程：{focus_1}怎么换",
        "{topic_subject}怎么包、怎么勒更顺手",
        "{topic_subject}原装弹力绳和伞绳到底怎么选",
        "{topic_subject}绳扣怎么装才顺手",
    ),
    "decor_unboxing": (
        "{topic_subject}开箱：{focus_1}到底怎么样",
        "{topic_subject}摆桌效果值不值得买单",
        "{topic_subject}体积和重量到底有多夸张",
        "{topic_subject}细节能不能撑起旗舰感",
        "{topic_subject}适不适合当桌搭摆件",
    ),
    "comparison_unboxing": (
        "{topic_subject}开箱：Pro 和 Ultra 到底怎么选",
        "{topic_subject}值不值得直接上 Ultra 版",
        "{topic_subject}和 Pro 差在哪，贵这一点值不值",
        "{topic_subject}开箱上手，先看版本取舍",
        "{topic_subject}这次买 Ultra 还是 Pro 更合理",
    ),
    "parenting_animation_explainer": (
        "{topic_subject}，先别急着纠正",
        "{topic_subject}背后藏着什么需求",
        "看懂孩子的“我也要”",
        "{topic_subject}不是坏习惯",
        "珍妮斯育儿：{focus_0}",
    ),
    "generic": (
        "{topic_subject}这期重点看什么",
        "{topic_subject}关键画面整理",
        "{topic_subject}这次讲清楚",
        "{topic_subject}重点信息记录",
        "{topic_subject}这期主要讲什么",
    ),
}


def build_platform_description(
    platform_key: str,
    *,
    summary: str,
    question: str,
    focus_line: str,
    methodology: dict[str, Any] | None = None,
    topic_subject: str = "",
) -> str:
    tone = PLATFORM_DESCRIPTION_TONES.get(platform_key) or PLATFORM_DESCRIPTION_TONES["default"]
    archetype = str((methodology or {}).get("archetype") or "").strip()
    subject = str(topic_subject or "").strip()
    summary_text = str(summary or "").strip()
    focus_text = str(focus_line or "").strip()
    if archetype == "双版本开箱对比":
        first = summary_text or (f"这期把{subject}的两个版本放在一起开箱。" if subject else "")
        second = f"先看{focus_text}。" if focus_text else ""
        return " ".join(part for part in (first, second) if part).strip()
    if archetype == "单主体开箱上手":
        first = summary_text or (f"这次到手开箱的是{subject}。" if subject else "")
        second = f"重点看{focus_text}。" if focus_text else ""
        return " ".join(part for part in (first, second) if part).strip()
    if archetype == "教程演示":
        first = summary_text or (f"这条主要讲{subject}怎么处理。" if subject else "")
        second = f"重点放在{focus_text}。" if focus_text else ""
        return " ".join(part for part in (first, second) if part).strip()
    body_parts = [
        summary_text,
        tone.prefix.format(focus_line=focus_line).strip() if focus_line else "",
        tone.suffix.format(question=question).strip() if question else "",
    ]
    return " ".join(part for part in body_parts if part).strip()


def build_constraint_only_platform_description(
    *,
    summary: str,
    question: str,
    focus_line: str,
    topic_subject: str = "",
) -> str:
    summary_text = str(summary or "").strip()
    focus_text = str(focus_line or "").strip()
    subject = str(topic_subject or "").strip()
    if summary_text:
        return " ".join(part for part in (summary_text, question) if str(part or "").strip()).strip()
    if focus_text and subject:
        return " ".join(part for part in (f"这期围绕{subject}展开，重点看{focus_text}。", question) if str(part or "").strip()).strip()
    if focus_text:
        return " ".join(part for part in (f"这期重点看{focus_text}。", question) if str(part or "").strip()).strip()
    return " ".join(part for part in (subject, question) if str(part or "").strip()).strip()


def build_title_candidates(*, intent: str, topic_subject: str, focus_points: list[str]) -> list[str]:
    templates = INTENT_TITLE_TEMPLATES.get(intent) or INTENT_TITLE_TEMPLATES["generic"]
    focus_0 = focus_points[0] if len(focus_points) > 0 else "重点"
    focus_1 = focus_points[1] if len(focus_points) > 1 else focus_0
    candidates: list[str] = []
    for template in templates:
        candidates.append(
            template.format(
                topic_subject=topic_subject,
                focus_0=focus_0,
                focus_1=focus_1,
            ).strip()
        )
    return candidates


def build_constraint_only_title_candidates(*, topic_subject: str, focus_points: list[str]) -> list[str]:
    subject = str(topic_subject or "").strip()
    if not subject:
        return []
    focus = [str(item).strip() for item in focus_points if str(item).strip()]
    candidates: list[str] = []
    if focus:
        candidates.append(f"{subject}：{focus[0]}")
    if len(focus) > 1:
        candidates.append(f"{subject}，重点看{focus[1]}")
    if len(focus) > 2:
        candidates.append(f"{subject}，先看{focus[0]}和{focus[2]}")
    if not candidates:
        candidates.append(f"{subject}重点信息记录")
    candidates.append(f"{subject}关键画面整理")
    candidates.append(f"{subject}这期重点看什么")
    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped
