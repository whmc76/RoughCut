from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import re

from roughcut.review.telegram_review_parsing import NEGATED_SUBTITLE_CONTENT_PATTERN

_SUBTITLE_STYLE_KEYWORDS = ("字幕样式", "字幕风格", "字幕颜色", "字幕描边", "字幕特效")
_SUBTITLE_TEXT_KEYWORDS = ("术语", "错别字", "翻译", "字幕时间", "字幕不同步", "字幕内容", "字幕文本")
_DIAGNOSTIC_EDIT_KEYWORDS = (
    "高风险cut",
    "高风险 cut",
    "高风险边界",
    "边界不顺",
    "边界不对",
    "边界太硬",
    "衔接不顺",
    "衔接生硬",
    "开场节奏",
    "hook 节奏",
    "hook不对",
    "hook 不对",
    "开头节奏",
    "前半段节奏",
    "剪辑边界",
)


@dataclass(frozen=True)
class FinalReviewRerunPlan:
    category: str
    label: str
    trigger_step: str
    rerun_steps: tuple[str, ...]
    targets: tuple[str, ...] = ()
    focus: str = ""


def build_final_review_rerun_plan(note: str) -> FinalReviewRerunPlan | None:
    plans = build_final_review_rerun_plans(note)
    return plans[0] if plans else None


def extract_final_review_content_profile_feedback(note: str) -> dict[str, Any]:
    text = str(note or "").strip()
    if not text:
        return {}

    def _clean(value: str) -> str:
        cleaned = re.sub(r"^[\s\u3000]+|[\s\u3000]+$", "", str(value or ""))
        return cleaned.strip().strip("，,。；;：:、")

    def _extract(patterns: tuple[str, ...], limit: int) -> str:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            value = _clean(str(match.group(1) or ""))
            if value:
                return value[:limit]
        return ""

    subject_brand = _extract(
        (
            r"(?:品牌|牌子)\s*(?:改成|改为|是|为|写成|应为|应该是|[:：])\s*([A-Za-z0-9\u4e00-\u9fff·+\-/]{1,40})",
        ),
        40,
    )
    subject_model = _extract(
        (
            r"(?:型号|款式|产品名|名字|名称|系列|版本)\s*(?:改成|改为|是|为|写成|应为|应该是|[:：])\s*([A-Za-z0-9\u4e00-\u9fff·+\-/]{1,60})",
        ),
        60,
    )

    feedback: dict[str, Any] = {}
    if subject_brand:
        feedback["subject_brand"] = subject_brand
    if subject_model:
        feedback["subject_model"] = subject_model
    return feedback


def build_final_review_rerun_plans(note: str) -> list[FinalReviewRerunPlan]:
    normalized = str(note or "").strip().lower()
    if not normalized:
        return []

    has_subtitle_style_request = any(keyword in normalized for keyword in _SUBTITLE_STYLE_KEYWORDS)
    has_subtitle_text_request = any(keyword in normalized for keyword in _SUBTITLE_TEXT_KEYWORDS) and not bool(
        NEGATED_SUBTITLE_CONTENT_PATTERN.search(normalized)
    )
    has_diagnostic_edit_request = any(keyword in normalized for keyword in _DIAGNOSTIC_EDIT_KEYWORDS)
    edit_focus = _final_review_edit_focus(normalized)

    plans: list[FinalReviewRerunPlan] = []
    for category, label, trigger_step, keywords, targets in (
        ("subtitle", "字幕与术语修订", "subtitle_postprocess", ("字幕", "术语", "错别字", "翻译", "字幕时间", "字幕不同步", "字幕内容", "字幕文本"), ("subtitle_text", "subtitle_timing")),
        ("subtitle_style", "字幕样式重出", "render", _SUBTITLE_STYLE_KEYWORDS, ("subtitle_style",)),
        ("content_profile", "内容摘要与文案定位调整", "content_profile", ("摘要", "主题", "关键词", "文案方向", "内容定位", "主体识别", "标题钩子"), ("summary", "keywords", "content_profile")),
        ("ai_director", "AI 导演文案与配音重做", "ai_director", ("旁白", "解说词", "口播文案", "ai导演", "ai 导演", "重配音", "配音文案"), ("voiceover", "director_script")),
        ("avatar_commentary", "数字人解说重做", "avatar_commentary", ("数字人", "口播人", "虚拟人", "画中画", "主播形象", "讲解人"), ("avatar",)),
        ("edit_plan", "剪辑结构重做", "edit_plan", ("节奏", "结构", "镜头", "重剪", "重新剪", "剪辑", "删掉", "前面太长", "后面太长", "卡点", *_DIAGNOSTIC_EDIT_KEYWORDS), ("timeline", "pacing", "cut_boundary")),
        ("cover_render", "封面重出", "render", ("封面", "缩略图", "标题图", "封面字", "封面标题"), ("cover",)),
        ("packaging_render", "包装素材重出", "render", ("片头", "片尾", "转场", "水印", "包装"), ("intro", "outro", "transition", "watermark")),
        ("music_render", "背景音乐重出", "render", ("bgm", "背景音乐", "音乐"), ("music",)),
        ("platform_package", "平台文案与发布文案重出", "platform_package", ("平台文案", "发布文案", "发布标题", "简介", "话题", "标签", "hashtags", "hashtag"), ("publish_copy", "hashtags", "platform_copy")),
    ):
        if category == "subtitle":
            if "字幕" not in normalized and not has_subtitle_text_request:
                continue
            if has_subtitle_style_request and not has_subtitle_text_request:
                continue
            if has_diagnostic_edit_request:
                continue
        elif not any(keyword in normalized for keyword in keywords):
            continue
        resolved_label = label
        resolved_targets = targets
        resolved_focus = ""
        if category == "edit_plan":
            resolved_focus = edit_focus
            if edit_focus == "hook_boundary":
                resolved_label = "Hook 边界重剪"
                resolved_targets = ("timeline", "pacing", "cut_boundary", "hook_boundary")
            elif edit_focus == "cta_transition":
                resolved_label = "CTA 衔接重剪"
                resolved_targets = ("timeline", "pacing", "cut_boundary", "cta_transition")
            elif edit_focus == "mid_transition":
                resolved_label = "中段衔接重剪"
                resolved_targets = ("timeline", "pacing", "cut_boundary", "mid_transition")
        plans.append(
            FinalReviewRerunPlan(
                category=category,
                label=resolved_label,
                trigger_step=trigger_step,
                rerun_steps=_rerun_chain_from_step(trigger_step),
                targets=resolved_targets,
                focus=resolved_focus,
            )
        )
    if extract_final_review_content_profile_feedback(note) and not any(plan.category == "content_profile" for plan in plans):
        plans.append(
            FinalReviewRerunPlan(
                category="content_profile",
                label="内容摘要与文案定位调整",
                trigger_step="content_profile",
                rerun_steps=_rerun_chain_from_step("content_profile"),
                targets=("summary", "keywords", "content_profile"),
            )
        )
    return plans


def combine_final_review_rerun_plans(plans: list[FinalReviewRerunPlan]) -> FinalReviewRerunPlan | None:
    if not plans:
        return None
    from roughcut.pipeline.orchestrator import PIPELINE_STEPS

    indexed: list[tuple[int, FinalReviewRerunPlan]] = []
    for plan in plans:
        if plan.trigger_step not in PIPELINE_STEPS:
            continue
        indexed.append((PIPELINE_STEPS.index(plan.trigger_step), plan))
    if not indexed:
        return None
    indexed.sort(key=lambda item: item[0])
    _, earliest = indexed[0]
    labels: list[str] = []
    categories: list[str] = []
    targets: list[str] = []
    focuses: list[str] = []
    for _, plan in indexed:
        if plan.label not in labels:
            labels.append(plan.label)
        if plan.category not in categories:
            categories.append(plan.category)
        if plan.focus and plan.focus not in focuses:
            focuses.append(plan.focus)
        for target in plan.targets:
            if target not in targets:
                targets.append(target)
    return FinalReviewRerunPlan(
        category="+".join(categories),
        label=" + ".join(labels),
        trigger_step=earliest.trigger_step,
        rerun_steps=earliest.rerun_steps,
        targets=tuple(targets),
        focus=focuses[0] if len(focuses) == 1 else "+".join(focuses),
    )


def _final_review_edit_focus(normalized_note: str) -> str:
    text = str(normalized_note or "").strip().lower()
    if not text:
        return ""
    if "hook" in text or "开场节奏" in text or "开头节奏" in text:
        return "hook_boundary"
    if "cta" in text or "收尾衔接" in text or "结尾衔接" in text:
        return "cta_transition"
    if any(token in text for token in ("中段衔接", "边界不顺", "边界不对", "边界太硬", "衔接不顺", "衔接生硬", "高风险边界", "高风险 cut", "高风险cut", "剪辑边界")):
        return "mid_transition"
    return ""


def _rerun_chain_from_step(step_name: str) -> tuple[str, ...]:
    from roughcut.pipeline.orchestrator import PIPELINE_STEPS

    if step_name not in PIPELINE_STEPS:
        return ()
    start_index = PIPELINE_STEPS.index(step_name)
    return tuple(PIPELINE_STEPS[start_index:])
