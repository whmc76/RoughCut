from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlatformDescriptionTone:
    prefix: str
    suffix: str


PLATFORM_DESCRIPTION_TONES: dict[str, PlatformDescriptionTone] = {
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
    "generic": (
        "{topic_subject}这期重点看什么",
        "{topic_subject}开箱先看细节",
        "{topic_subject}这次到底值不值",
        "{topic_subject}上手体验记录",
        "{topic_subject}这期主要讲什么",
    ),
}


def build_platform_description(platform_key: str, *, summary: str, question: str, focus_line: str) -> str:
    tone = PLATFORM_DESCRIPTION_TONES.get(platform_key) or PLATFORM_DESCRIPTION_TONES["default"]
    body_parts = [
        str(summary or "").strip(),
        tone.prefix.format(focus_line=focus_line).strip() if focus_line else "",
        tone.suffix.format(question=question).strip() if question else "",
    ]
    return " ".join(part for part in body_parts if part).strip()


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
