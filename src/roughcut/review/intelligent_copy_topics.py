from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class IntelligentCopyTopicSpec:
    key: str
    match_all: tuple[str, ...]
    match_any_groups: tuple[tuple[str, ...], ...]
    subject_brand: str
    subject_model: str
    subject_type: str
    subject_domain: str
    video_theme: str
    summary: str
    hook_line: str
    engagement_question: str
    search_queries: tuple[str, ...]
    cover_main: str
    topic_subject: str
    intent: str
    focus_points: tuple[str, ...]
    tags: tuple[str, ...]
    anchor_terms: tuple[str, ...]
    forbidden_terms: tuple[str, ...]
    title_candidates: tuple[str, ...]

    def matches(self, text: str) -> bool:
        normalized = str(text or "").strip()
        if not normalized:
            return False
        if any(term not in normalized for term in self.match_all):
            return False
        for group in self.match_any_groups:
            if group and not any(term in normalized for term in group):
                return False
        return True


INTELLIGENT_COPY_TOPIC_SPECS: tuple[IntelligentCopyTopicSpec, ...] = (
    IntelligentCopyTopicSpec(
        key="olight_commander2_ultra",
        match_all=("司令官", "Ultra"),
        match_any_groups=(),
        subject_brand="OLIGHT",
        subject_model="司令官2Ultra",
        subject_type="EDC手电",
        subject_domain="flashlight",
        video_theme="OLIGHT司令官2Ultra开箱与版本取舍",
        summary="这期主要开箱OLIGHT司令官2Ultra，顺带聊 Pro 和 Ultra 版本差异、价格与配置取舍。",
        hook_line="OLIGHT司令官2Ultra到底值不值得上 Ultra 版",
        engagement_question="如果是你，会直接上 Ultra，还是选更便宜的 Pro？",
        search_queries=("OLIGHT 司令官2Ultra", "OLIGHT 司令官2Ultra Pro Ultra 对比"),
        cover_main="司令官2Ultra",
        topic_subject="OLIGHT司令官2Ultra",
        intent="comparison_unboxing",
        focus_points=("开箱上手", "Pro 和 Ultra 差异", "价格与配置取舍"),
        tags=("OLIGHT", "司令官2Ultra", "EDC手电", "开箱", "版本对比"),
        anchor_terms=("OLIGHT", "司令官2Ultra", "Pro", "Ultra"),
        forbidden_terms=("机能包", "折刀", "摆件"),
        title_candidates=(
            "OLIGHT司令官2Ultra开箱：Pro 和 Ultra 到底怎么选",
            "OLIGHT司令官2Ultra值不值得直接上 Ultra 版",
            "OLIGHT司令官2Ultra和 Pro 差在哪，贵这一点值不值",
            "OLIGHT司令官2Ultra开箱上手，先看版本取舍",
            "OLIGHT司令官2Ultra这次买 Ultra 还是 Pro 更合理",
        ),
    ),
    IntelligentCopyTopicSpec(
        key="zhuojiang_pixiu_decor",
        match_all=("貔貅",),
        match_any_groups=(("紫铜", "白铜", "摆件", "摆在家里"),),
        subject_brand="琢匠",
        subject_model="貔貅",
        subject_type="铜制摆件",
        subject_domain="decor",
        video_theme="琢匠貔貅开箱与材质细节",
        summary="这期主要开箱琢匠貔貅摆件，重点看体积重量、紫铜白铜材质和细节表现。",
        hook_line="琢匠貔貅摆桌效果到底怎么样",
        engagement_question="你更看重这种摆件的材质细节，还是整体摆桌气场？",
        search_queries=("琢匠 貔貅", "琢匠 貔貅 紫铜 白铜 摆件"),
        cover_main="琢匠貔貅",
        topic_subject="琢匠貔貅",
        intent="decor_unboxing",
        focus_points=("开箱", "紫铜白铜材质", "体积重量和摆桌效果"),
        tags=("琢匠", "貔貅", "铜制摆件", "桌搭摆件", "开箱", "材质细节"),
        anchor_terms=("琢匠", "貔貅", "摆件", "紫铜", "白铜"),
        forbidden_terms=("机能包", "折刀", "手电", "工具钳"),
        title_candidates=(
            "琢匠貔貅开箱：紫铜白铜材质到底怎么样",
            "琢匠貔貅摆桌效果值不值得买单",
            "琢匠貔貅体积和重量到底有多夸张",
            "琢匠貔貅细节能不能撑起旗舰感",
            "琢匠貔貅适不适合当桌搭摆件",
        ),
    ),
    IntelligentCopyTopicSpec(
        key="fas_knife_roll_tutorial",
        match_all=("刀帕",),
        match_any_groups=(("怎么用", "用法", "使用方法", "伞绳", "绳扣", "弹力绳"),),
        subject_brand="FAS",
        subject_model="刀帕",
        subject_type="刀帕收纳配件",
        subject_domain="accessory",
        video_theme="FAS刀帕使用与伞绳更换教程",
        summary="这期主要演示FAS刀帕怎么包裹固定，顺带讲原装弹力绳和伞绳绳扣怎么更换、怎么调松紧。",
        hook_line="FAS刀帕到底怎么包、怎么换绳",
        engagement_question="你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        search_queries=("FAS 刀帕", "FAS 刀帕 伞绳 绳扣 教程"),
        cover_main="FAS刀帕",
        topic_subject="FAS刀帕",
        intent="tutorial",
        focus_points=("使用方法", "弹力绳固定", "伞绳和绳扣更换"),
        tags=("FAS", "刀帕", "使用教程", "伞绳更换", "绳扣", "EDC收纳"),
        anchor_terms=("FAS", "刀帕", "伞绳", "绳扣"),
        forbidden_terms=("折刀", "AI创作工具", "机能包", "手电"),
        title_candidates=(
            "FAS刀帕怎么用？使用方法一次讲清",
            "FAS刀帕教程：弹力绳固定怎么换",
            "FAS刀帕怎么包、怎么勒更顺手",
            "FAS刀帕原装弹力绳和伞绳到底怎么选",
            "FAS刀帕绳扣怎么装才顺手",
        ),
    ),
)


def match_intelligent_copy_topic(text: str) -> IntelligentCopyTopicSpec | None:
    normalized = str(text or "").strip()
    if not normalized:
        return None
    for spec in INTELLIGENT_COPY_TOPIC_SPECS:
        if spec.matches(normalized):
            return spec
    return None


def build_intelligent_copy_topic_hints(text: str) -> dict[str, object]:
    topic = match_intelligent_copy_topic(text)
    if topic is None:
        return {}
    return {
        "subject_brand": topic.subject_brand,
        "subject_model": topic.subject_model,
        "subject_type": topic.subject_type,
        "video_theme": topic.video_theme,
        "summary": topic.summary,
        "hook_line": topic.hook_line,
        "engagement_question": topic.engagement_question,
        "search_queries": list(topic.search_queries),
    }
