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
    if any(keyword in haystack for keyword in ("限定", "联名", "生肖", "纪念", "lunar", "limited")):
        return PRESETS["unboxing_limited"]
    if any(keyword in haystack for keyword in ("升级", "改版", "战术", "2.0", "升级版", "新版")):
        return PRESETS["unboxing_upgrade"]
    if any(keyword in haystack for keyword in ("刀", "edc", "战术", "tactical", "钛", "柄", "锁")):
        return PRESETS["edc_tactical"]
    return PRESETS["unboxing_default"]
