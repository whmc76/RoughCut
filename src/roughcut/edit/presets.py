from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class WorkflowPreset:
    name: str
    label: str
    description: str
    subtitle_goal: str
    subtitle_tone: str
    cover_style: str
    cover_variant_count: int
    cover_accent: str
    content_kind: str

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS: dict[str, WorkflowPreset] = {
    "unboxing_default": WorkflowPreset(
        name="unboxing_default",
        label="开箱标准版",
        description="通用开箱/体验视频，强调主体识别、信息准确和节奏流畅。",
        subtitle_goal="修正品牌型号，保留口播节奏，去掉明显 ASR 错词和无意义口头禅，把开箱体验说清楚。",
        subtitle_tone="口语化、利落、可信，不要编造参数。",
        cover_style="tech_showcase",
        cover_variant_count=5,
        cover_accent="开箱细节拉满",
        content_kind="unboxing",
    ),
    "unboxing_limited": WorkflowPreset(
        name="unboxing_limited",
        label="限定收藏版",
        description="适合限定版、联名版、生肖款等主题，强调稀缺性和设计元素。",
        subtitle_goal="突出限定属性、工艺细节和收藏价值，品牌型号必须准确。",
        subtitle_tone="有兴奋感，但不要夸张空喊。",
        cover_style="collection_drop",
        cover_variant_count=5,
        cover_accent="限定款值不值",
        content_kind="unboxing",
    ),
    "unboxing_upgrade": WorkflowPreset(
        name="unboxing_upgrade",
        label="升级对比版",
        description="适合升级款、改版、战术版、2.0 等主题，强调变化点。",
        subtitle_goal="突出升级点、改版逻辑和体验变化，避免重复废话。",
        subtitle_tone="判断明确、信息密度高。",
        cover_style="upgrade_spotlight",
        cover_variant_count=5,
        cover_accent="这次升级到位吗",
        content_kind="unboxing",
    ),
    "edc_tactical": WorkflowPreset(
        name="edc_tactical",
        label="EDC 战术版",
        description="适合 EDC 刀具、工具、战术装备，强调做工、结构、手感和实用性。",
        subtitle_goal="把专业词、结构件和实际体验说清楚，避免口水句。",
        subtitle_tone="硬核、简洁、像老玩家解说。",
        cover_style="tactical_neon",
        cover_variant_count=5,
        cover_accent="实战向改版",
        content_kind="unboxing",
    ),
    "unboxing_standard": WorkflowPreset(
        name="unboxing_standard",
        label="潮玩EDC开箱",
        description="适合潮玩、EDC、工具和相关开箱内容，强调主体识别、信息准确和节奏流畅。",
        subtitle_goal="修正品牌型号，保留口播节奏，去掉明显 ASR 错词和无意义口头禅，把开箱体验说清楚。",
        subtitle_tone="口语化、利落、可信，不要编造参数。",
        cover_style="tech_showcase",
        cover_variant_count=5,
        cover_accent="开箱体验拉满",
        content_kind="unboxing",
    ),
    "screen_tutorial": WorkflowPreset(
        name="screen_tutorial",
        label="录屏教学",
        description="适合软件操作、工作流演示、录屏讲解，强调步骤顺序和信息清晰度。",
        subtitle_goal="保留关键操作步骤、按钮名和路径名，删掉卡壳和重复解释，让观众能跟着做。",
        subtitle_tone="清楚、直接、步骤化，像高质量教程旁白。",
        cover_style="upgrade_spotlight",
        cover_variant_count=5,
        cover_accent="这步别做错",
        content_kind="tutorial",
    ),
    "tutorial_standard": WorkflowPreset(
        name="tutorial_standard",
        label="教程演示",
        description="适合软件操作、工作流演示、录屏讲解，强调步骤顺序和信息清晰度。",
        subtitle_goal="保留关键操作步骤、按钮名和路径名，删掉卡壳和重复解释，让观众能跟着做。",
        subtitle_tone="清楚、直接、步骤化，像高质量教程旁白。",
        cover_style="upgrade_spotlight",
        cover_variant_count=5,
        cover_accent="这步别做错",
        content_kind="tutorial",
    ),
    "vlog_daily": WorkflowPreset(
        name="vlog_daily",
        label="Vlog日常",
        description="适合日常记录、出行、生活分享，强调情绪流动、场景切换和陪伴感。",
        subtitle_goal="保留真实口语和情绪变化，压缩重复片段，让节奏更轻快。",
        subtitle_tone="自然、有生活感，不要写成硬邦邦解说词。",
        cover_style="tech_showcase",
        cover_variant_count=5,
        cover_accent="今天发生了啥",
        content_kind="vlog",
    ),
    "commentary_focus": WorkflowPreset(
        name="commentary_focus",
        label="口播观点",
        description="适合对镜口播、热点评论、知识表达，强调论点、论据和转场节奏。",
        subtitle_goal="突出核心观点和结论，删除绕圈表达与重复铺垫，保留关键信息钩子。",
        subtitle_tone="有判断、节奏稳、观点明确。",
        cover_style="upgrade_spotlight",
        cover_variant_count=5,
        cover_accent="重点就这句",
        content_kind="commentary",
    ),
    "talking_head_commentary": WorkflowPreset(
        name="talking_head_commentary",
        label="口播观点",
        description="适合对镜口播、热点评论、知识表达，强调论点、论据和转场节奏。",
        subtitle_goal="突出核心观点和结论，删除绕圈表达与重复铺垫，保留关键信息钩子。",
        subtitle_tone="有判断、节奏稳、观点明确。",
        cover_style="upgrade_spotlight",
        cover_variant_count=5,
        cover_accent="重点就这句",
        content_kind="commentary",
    ),
    "gameplay_highlight": WorkflowPreset(
        name="gameplay_highlight",
        label="游戏高光",
        description="适合游戏实况、对局高光、战术复盘，强调高能时刻和结果反馈。",
        subtitle_goal="保留关键操作、局势变化和结果反馈，压缩等待时间和无效重复。",
        subtitle_tone="紧凑、带情绪、但不要过度夸张。",
        cover_style="tactical_neon",
        cover_variant_count=5,
        cover_accent="这波太关键了",
        content_kind="gameplay",
    ),
    "food_explore": WorkflowPreset(
        name="food_explore",
        label="美食探店",
        description="适合探店、试吃、餐饮推荐，强调环境、口感、流程和价格信息。",
        subtitle_goal="把店名、菜名、口感和性价比说清楚，删掉空泛赞美。",
        subtitle_tone="鲜活、具体、有画面感。",
        cover_style="collection_drop",
        cover_variant_count=5,
        cover_accent="这家到底值不值",
        content_kind="food",
    ),
}

LEGACY_PRESET_ALIASES = {
    "talking_head_commentary_v2": "commentary_focus",
}

VISIBLE_TEMPLATE_ORDER = (
    "unboxing_standard",
    "tutorial_standard",
    "vlog_daily",
    "commentary_focus",
    "gameplay_highlight",
    "food_explore",
)

CONTENT_KIND_TO_TEMPLATE = {
    "tutorial": "tutorial_standard",
    "vlog": "vlog_daily",
    "commentary": "commentary_focus",
    "gameplay": "gameplay_highlight",
    "food": "food_explore",
}


def normalize_workflow_template_name(name: str | None) -> str:
    normalized = str(name or "").strip().lower()
    if normalized in LEGACY_PRESET_ALIASES:
        return LEGACY_PRESET_ALIASES[normalized]
    return normalized


def get_workflow_preset(name: str | None) -> WorkflowPreset:
    raw = str(name or "").strip().lower()
    if raw and raw in PRESETS:
        return PRESETS[raw]
    normalized = normalize_workflow_template_name(name)
    if normalized in PRESETS:
        return PRESETS[normalized]
    return PRESETS["unboxing_standard"]


def list_workflow_template_options() -> list[dict[str, str]]:
    return [
        {"value": "", "label": "自动选择模板"},
        *[
            {
                "value": name,
                "label": PRESETS[name].label,
            }
            for name in VISIBLE_TEMPLATE_ORDER
        ],
    ]


def select_workflow_template(
    *,
    workflow_template: str | None,
    content_kind: str = "",
    subject_domain: str = "",
    subject_model: str = "",
    subject_type: str = "",
    transcript_hint: str = "",
) -> WorkflowPreset:
    raw_override = str(workflow_template or "").strip().lower()
    if raw_override in PRESETS:
        return PRESETS[raw_override]
    normalized_override = normalize_workflow_template_name(workflow_template)
    if normalized_override in PRESETS:
        return PRESETS[normalized_override]

    normalized_kind = str(content_kind or "").strip().lower()
    normalized_domain = str(subject_domain or "").strip().lower()
    haystack = " ".join([subject_model, subject_type, transcript_hint]).lower()

    if normalized_kind in CONTENT_KIND_TO_TEMPLATE:
        template_name = CONTENT_KIND_TO_TEMPLATE[normalized_kind]
        if normalized_kind == "tutorial":
            return PRESETS[template_name]
        if normalized_kind == "commentary":
            return PRESETS[template_name]
        if normalized_kind == "vlog":
            return PRESETS[template_name]
        if normalized_kind == "gameplay":
            return PRESETS[template_name]
        if normalized_kind == "food":
            return PRESETS[template_name]

    if normalized_kind == "unboxing":
        if any(keyword in haystack for keyword in ("限定", "联名", "生肖", "纪念", "lunar", "limited")):
            return PRESETS["unboxing_limited"]
        if any(keyword in haystack for keyword in ("升级", "改版", "2.0", "升级版", "新版")):
            return PRESETS["unboxing_upgrade"]
        if any(keyword in haystack for keyword in ("刀", "edc", "战术", "tactical", "钛", "柄", "锁")):
            return PRESETS["edc_tactical"]
        return PRESETS["unboxing_standard"]

    if any(keyword in haystack for keyword in ("录屏", "教程", "教学", "实操", "演示", "软件", "操作", "工作流", "screen", "obs", "剪映", "premiere", "excel", "ppt")):
        return PRESETS["tutorial_standard"]
    if any(keyword in haystack for keyword in ("vlog", "日常", "出门", "出行", "探店", "周末", "今天带你", "跟我", "生活", "一天", "citywalk")):
        return PRESETS["vlog_daily"]
    if any(keyword in haystack for keyword in ("口播", "观点", "评论", "复盘", "热点", "分析", "看法", "聊聊", "为什么", "到底")):
        return PRESETS["commentary_focus"]
    if any(keyword in haystack for keyword in ("游戏", "对局", "吃鸡", "王者", "lol", "fps", "团战", "击杀", "直播切片", "实况")):
        return PRESETS["gameplay_highlight"]
    if any(keyword in haystack for keyword in ("探店", "试吃", "美食", "餐厅", "咖啡", "奶茶", "火锅", "烧烤", "甜品", "口感")):
        return PRESETS["food_explore"]
    if any(keyword in haystack for keyword in ("限定", "联名", "生肖", "纪念", "lunar", "limited")):
        return PRESETS["unboxing_limited"]
    if any(keyword in haystack for keyword in ("升级", "改版", "2.0", "升级版", "新版")):
        return PRESETS["unboxing_upgrade"]
    if any(keyword in haystack for keyword in ("刀", "edc", "战术", "tactical", "钛", "柄", "锁")):
        return PRESETS["edc_tactical"]
    return PRESETS["unboxing_standard"]


def select_preset(
    *,
    channel_profile: str | None,
    subject_model: str = "",
    subject_type: str = "",
    transcript_hint: str = "",
) -> WorkflowPreset:
    return select_workflow_template(
        workflow_template=channel_profile,
        subject_model=subject_model,
        subject_type=subject_type,
        transcript_hint=transcript_hint,
    )
