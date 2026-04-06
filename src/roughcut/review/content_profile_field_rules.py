from __future__ import annotations


SUPPORTED_VIDEO_TYPES = ("tutorial", "vlog", "commentary", "gameplay", "food", "unboxing")
_SUPPORTED_VIDEO_TYPE_LABELS = (
    "教程(tutorial)",
    "Vlog(vlog)",
    "观点(commentary)",
    "游戏(gameplay)",
    "探店(food)",
    "开箱(unboxing)",
)
_SUPPORTED_VIDEO_TYPES_DISPLAY = "、".join(_SUPPORTED_VIDEO_TYPE_LABELS)
_SUPPORTED_VIDEO_TYPES_DISPLAY_EN = "/".join(SUPPORTED_VIDEO_TYPES)

_CONTENT_FIELD_RULES_COMMON = (
    "字段规则（通用）：\n"
    f"subject_type：必须从 {_SUPPORTED_VIDEO_TYPES_DISPLAY} 中选一个主类型，不允许并列多个；无明显特征可回退为 unboxing。\n"
    "video_theme：一句话点出核心主题，不要写泛化词；不要把它写成标题口号。\n"
    "hook_line：中文，尽量短、具体，可直接作为标题钩子；避免与 video_theme 内容重复。\n"
    "visible_text：只保留视频里真实出现的可见文字关键词，不要扩写。\n"
    "summary：中文一句话归纳视频主轴与结果。\n"
    "engagement_question：1 条可用于评论区的互动问题。\n"
    "keywords（或 search_queries）：用于检索核验的高价值关键词，严格给出 1-4 条，不允许留空；无稳定信号时必须回退到默认候选词。\n"
    "correction_notes：补充人工判定、风险说明、是否有错误拆解点，便于复核。\n"
    "示例：\n"
    "- 与字幕一致：此条确认与字幕/画面一致。\n"
    "- 风险提示：该条有模型误读“...”，建议后续以原字幕为准。\n"
    "supplemental_context：补充拍摄背景、素材问题、后续处理上下文或额外说明，建议在此写“补拍需求/素材异常/风格约束”等，不要复写 summary。\n"
    "示例：\n"
    "- 补充：镜头抖动明显，建议字幕优先纠错。\n"
    "- 后续：本条偏口播节奏，标题需更偏向通勤场景。\n"
)


CONTENT_UNDERSTANDING_FIELD_GUIDELINES = (
    f"{_CONTENT_FIELD_RULES_COMMON}"
    f"video_type：同 subject_type 规则，返回 {_SUPPORTED_VIDEO_TYPES_DISPLAY} 之一。\n"
)


CONTENT_PROFILE_FIELD_GUIDELINES = _CONTENT_FIELD_RULES_COMMON
