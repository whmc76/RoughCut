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
    "visible_text：只保留画面里稳定可见且可复核的文字，不是摘要改写，不要塞入内容推断。\n"
    "可见文本提取规则：\n"
    "1) 优先使用 OCR 多帧稳定复现文本；\n"
    "2) 严禁文件名、时间戳、标题模板、截图水印、字幕原句、口号化文案进入 visible_text；\n"
    "3) 同一文本需跨帧复现（建议 >=2 帧）或有高置信单帧信号；\n"
    "4) 没有可信可见文字时返回空并由人工补充，不可回退到文件名。\n"
    "summary：中文一句话归纳视频主轴与结果。\n"
    "engagement_question：1 条可用于评论区的互动问题。\n"
    "keywords（或 search_queries）：用于检索核验的高价值关键词。\n"
    "keywords：优先输出 4-10 个单独 token（高优先级：subject_brand > subject_model > subject_type > 高频主题词）。\n"
    "禁止把“品牌+型号+类型”拼成长句；每条关键词只保留一个核心词或短词。\n"
    "示例："
    "“赫斯俊, 船长, 机能包, 开箱”。\n"
    "search_queries：可保留自然短语，默认给出 1-6 条，用于后续检索。\n"
    "无稳定信号时不得回退文件名或时间码，必须回退到默认候选词。\n"
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
