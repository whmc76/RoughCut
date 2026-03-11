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

    def to_dict(self) -> dict:
        return asdict(self)


PRESETS: dict[str, WorkflowPreset] = {
    "unboxing_default": WorkflowPreset(
        name="unboxing_default",
        label="开箱标准版",
        description="通用开箱/体验视频，强调主体识别、信息准确和节奏流畅。",
        subtitle_goal="修正品牌型号，保留口播节奏，去掉明显 ASR 错词和无意义口头禅。",
        subtitle_tone="口语化、利落、可信，不要编造参数。",
        cover_style="tech_showcase",
        cover_variant_count=5,
        cover_accent="开箱细节拉满",
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
    ),
    "vlog_daily": WorkflowPreset(
        name="vlog_daily",
        label="Vlog 日常",
        description="适合日常记录、出行、生活分享，强调情绪流动、场景切换和陪伴感。",
        subtitle_goal="保留真实口语和情绪变化，压缩重复片段，让节奏更轻快。",
        subtitle_tone="自然、有生活感，不要写成硬邦邦解说词。",
        cover_style="tech_showcase",
        cover_variant_count=5,
        cover_accent="今天发生了啥",
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
    ),
}


def get_workflow_preset(name: str | None) -> WorkflowPreset:
    if name and name in PRESETS:
        return PRESETS[name]
    return PRESETS["unboxing_default"]


def select_preset(
    *,
    channel_profile: str | None,
    subject_model: str = "",
    subject_type: str = "",
    transcript_hint: str = "",
) -> WorkflowPreset:
    if channel_profile:
        normalized = channel_profile.strip().lower()
        if normalized in PRESETS:
            return PRESETS[normalized]

    haystack = " ".join([subject_model, subject_type, transcript_hint]).lower()
    if any(keyword in haystack for keyword in ("录屏", "教程", "教学", "实操", "演示", "软件", "操作", "工作流", "screen", "obs", "剪映", "premiere", "excel", "ppt")):
        return PRESETS["screen_tutorial"]
    if any(keyword in haystack for keyword in ("vlog", "日常", "出门", "出行", "探店", "周末", "今天带你", "跟我", "生活", "一天", "citywalk")):
        return PRESETS["vlog_daily"]
    if any(keyword in haystack for keyword in ("口播", "观点", "评论", "复盘", "热点", "分析", "看法", "聊聊", "为什么", "到底")):
        return PRESETS["talking_head_commentary"]
    if any(keyword in haystack for keyword in ("游戏", "对局", "吃鸡", "王者", "lol", "fps", "团战", "击杀", "直播切片", "实况")):
        return PRESETS["gameplay_highlight"]
    if any(keyword in haystack for keyword in ("探店", "试吃", "美食", "餐厅", "咖啡", "奶茶", "火锅", "烧烤", "甜品", "口感")):
        return PRESETS["food_explore"]
    if any(keyword in haystack for keyword in ("限定", "联名", "生肖", "纪念", "lunar", "limited")):
        return PRESETS["unboxing_limited"]
    if any(keyword in haystack for keyword in ("升级", "改版", "战术", "2.0", "升级版", "新版")):
        return PRESETS["unboxing_upgrade"]
    if any(keyword in haystack for keyword in ("刀", "edc", "战术", "tactical", "钛", "柄", "锁")):
        return PRESETS["edc_tactical"]
    return PRESETS["unboxing_default"]
