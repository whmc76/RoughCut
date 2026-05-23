from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


_AI_FALLBACK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"这条视频主要围绕.+?展开"),
    re.compile(r"本视频主要(围绕|介绍|讲述|展示)"),
    re.compile(r"本文主要(围绕|介绍|讲述|展示)"),
    re.compile(r"整体来看[，,].*?(内容|视频|素材)"),
    re.compile(r"建议发布前人工核对"),
    re.compile(r"发布前.*?人工(核对|确认|复核)"),
    re.compile(r"如有(不准确|错误|遗漏)"),
    re.compile(r"根据(视频|素材|内容|字幕)(可知|来看|整理)"),
)

_GENERIC_PHRASES = (
    "内容丰富",
    "值得一看",
    "干货满满",
    "亮点很多",
    "信息量很大",
    "详细介绍",
    "全面展示",
    "深入了解",
    "帮助大家",
    "感兴趣的朋友",
    "欢迎观看",
    "不要错过",
)

_EXPERIENCE_DETAIL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(上手|到手|开箱|拆开|拿起|握持|按下|点亮|挂上|装进|塞进|掏出|拉开|合上|展开|切|削|照|扫|对比|试了|用了|戴上|闻到|尝了)"),
    re.compile(r"(手感|质感|重量|厚度|尺寸|亮度|泛光|光斑|收纳|口袋|卡扣|拉链|阻尼|声音|味道|口感|续航|发热|边缘|纹理)"),
    re.compile(r"(镜头里|画面里|实拍|近看|细看|现场|这一段|这一下|这个角度|这次)"),
    re.compile(r"\b(hands?-on|unboxing|build quality|handling|handle|texture|sound|detail|details|close[- ]?up|real use|version differences?|first impressions?)\b", re.IGNORECASE),
)

_CONCRETE_DETAIL_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?\s?(?:cm|mm|g|kg|ml|mAh|lm|流明|米|分钟|小时|档|颗|个|处|次|%))|"
    r"([A-Za-z]{2,}[- ]?\d+[A-Za-z0-9-]*)"
)

_ABSOLUTE_FACT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(唯一|首个|首次|第一(?:名|款|个|家|批|位)?|最强|最好|顶级|完全|永久|绝对|百分百|100%)"),
    re.compile(r"(官方|认证|获奖|专利|军规|医用|治疗|治愈|防过敏|无副作用)"),
)

_PARAMETER_FACT_PATTERN = re.compile(
    r"\d+(?:\.\d+)?\s?(?:流明|lm|mAh|mah|毫安|瓦|w|伏|v|克|g|kg|mm|cm|米|公里|小时|分钟|倍|档|%|IPX\d|IP\d{2})",
    re.IGNORECASE,
)

_SOFT_FACT_PATTERN = re.compile(r"(大概|差不多|估计|应该|可能|感觉|我这只|我手上|个人觉得)")

_PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "xiaohongshu": {"label": "小红书", "min_chars": 35, "max_chars": 520, "tone": "真实笔记感，保留到手感受、细节和取舍。"},
    "douyin": {"label": "抖音", "min_chars": 16, "max_chars": 160, "tone": "短促直给，先给最强记忆点或结论。"},
    "kuaishou": {"label": "快手", "min_chars": 18, "max_chars": 180, "tone": "像当面分享，少包装，多实话。"},
    "bilibili": {"label": "B站", "min_chars": 40, "max_chars": 900, "tone": "信息密度更高，适合写清主体、过程和判断。"},
    "wechat_channels": {"label": "视频号", "min_chars": 18, "max_chars": 220, "tone": "稳妥可信，减少网感夸张词。"},
    "toutiao": {"label": "头条号", "min_chars": 30, "max_chars": 500, "tone": "摘要清楚，结论和事实边界明确。"},
    "youtube": {"label": "YouTube", "min_chars": 55, "max_chars": 1800, "tone": "可检索描述，补足主体、场景和关键词。"},
    "x": {"label": "X", "min_chars": 8, "max_chars": 140, "tone": "一句观察或判断，避免长段简介腔。"},
}


def assess_platform_body(
    platform_key: str,
    body: str,
    *,
    content_profile: Mapping[str, Any] | None = None,
    fact_sheet: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    text = _normalize_body(body)
    rules = _PLATFORM_RULES.get(platform_key, {"label": platform_key or "未知平台", "min_chars": 20, "max_chars": 500, "tone": "按平台语气重写。"})

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []

    if not text:
        blocking_reasons.append("正文为空")
        repair_hints.append("补一段像创作者本人发布的正文：主体 + 一个画面动作 + 一个真实感受。")
        return _result(blocking_reasons, warnings, repair_hints)

    fallback_hits = _ai_fallback_hits(text)
    if fallback_hits:
        blocking_reasons.append(f"正文像 AI 兜底/审核提示文案：{fallback_hits[0]}")
        repair_hints.append("删除“主要围绕/人工核对/根据素材”等兜底句，改成第一人称或现场观察。")

    generic_score = _generic_score(text)
    if generic_score >= 2 and not _has_experience_detail(text):
        blocking_reasons.append("正文空泛，缺少视频里的具体动作或体验细节")
        repair_hints.append("至少补一个镜头动作或体验词，例如上手、开箱、点亮、装入口袋、手感、光斑、收纳变化。")

    subject_anchors = _subject_anchors(content_profile, fact_sheet)
    if subject_anchors:
        if not _contains_any_anchor(text, subject_anchors):
            blocking_reasons.append("正文缺少主体锚点")
            repair_hints.append(f"把主体写进正文，优先使用：{_join_preview(subject_anchors)}。")
    elif len(text) < 80 and not _CONCRETE_DETAIL_PATTERN.search(text):
        warnings.append("未提供主体资料，且正文里没有明显品牌/型号/对象锚点")
        repair_hints.append("集成时传入 content_profile 或 fact_sheet，便于校验正文是否写到正确主体。")

    if not _has_experience_detail(text):
        blocking_reasons.append("正文缺少视频动作/体验细节")
        repair_hints.append("补充一个可从画面或体验中验证的细节，避免只写主题和评价。")

    _apply_platform_tone_checks(platform_key, rules, text, warnings, repair_hints)
    _apply_fact_risk_checks(text, fact_sheet, blocking_reasons, warnings, repair_hints)

    blocking_reasons = _dedupe(blocking_reasons)
    warnings = _dedupe(warnings)
    repair_hints = _dedupe(repair_hints)
    return _result(blocking_reasons, warnings, repair_hints)


def _result(blocking_reasons: list[str], warnings: list[str], repair_hints: list[str]) -> dict[str, Any]:
    return {
        "publish_ready": not blocking_reasons,
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
        "repair_hints": repair_hints,
    }


def _normalize_body(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _ai_fallback_hits(text: str) -> list[str]:
    hits: list[str] = []
    for pattern in _AI_FALLBACK_PATTERNS:
        match = pattern.search(text)
        if match:
            hits.append(match.group(0))
    return _dedupe(hits)


def _generic_score(text: str) -> int:
    return sum(1 for phrase in _GENERIC_PHRASES if phrase in text)


def _has_experience_detail(text: str) -> bool:
    if any(pattern.search(text) for pattern in _EXPERIENCE_DETAIL_PATTERNS):
        return True
    return bool(_CONCRETE_DETAIL_PATTERN.search(text))


def _subject_anchors(content_profile: Mapping[str, Any] | None, fact_sheet: Mapping[str, Any] | None) -> list[str]:
    anchors: list[str] = []
    for source in (content_profile, fact_sheet):
        if not isinstance(source, Mapping):
            continue
        for key in (
            "subject_brand",
            "subject_model",
            "subject_type",
            "video_theme",
            "primary_subject",
            "brand",
            "model",
            "type",
            "theme",
            "subject",
        ):
            anchors.extend(_flatten_text_values(source.get(key)))
        for key in ("subject_entities", "entities", "verified_entities"):
            anchors.extend(_flatten_text_values(source.get(key)))
    return _dedupe([anchor for anchor in anchors if _usable_anchor(anchor)])


def _flatten_text_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, Mapping):
        values: list[str] = []
        for key in ("name", "canonical", "canonical_name", "value", "text", "label"):
            values.extend(_flatten_text_values(value.get(key)))
        return values
    if isinstance(value, (list, tuple, set)):
        values: list[str] = []
        for item in value:
            values.extend(_flatten_text_values(item))
        return values
    return [str(value).strip()]


def _usable_anchor(value: str) -> bool:
    if re.search(r"(人工核对|保守策略|发布素材|老本行|今天|我们|建议|具体型号|参数)", str(value or "")):
        return False
    compact = _compact(value)
    if len(compact) < 2:
        return False
    if len(compact) > 24:
        return False
    return compact not in {"内容待确认", "待确认", "未知", "开箱", "展示", "体验", "视频", "内容"}


def _contains_any_anchor(text: str, anchors: list[str]) -> bool:
    compact_text = _compact(text).lower()
    token_text = _anchor_token_text(text)
    for anchor in anchors:
        compact_anchor = _compact(anchor).lower()
        if compact_anchor and compact_anchor in compact_text:
            return True
        tokens = _anchor_tokens(anchor)
        if tokens and any(token in token_text for token in tokens):
            return True
    return False


def _compact(value: str) -> str:
    return re.sub(r"[\s\-_·:：/|，,。.!！?？#【】\[\]()（）]+", "", value or "")


def _anchor_token_text(value: str) -> str:
    return " ".join(_anchor_tokens(value))


def _anchor_tokens(value: str) -> list[str]:
    text = str(value or "").lower()
    tokens = re.findall(r"[a-z0-9]{2,}", text)
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for chunk in chinese_chunks:
        if len(chunk) <= 4:
            tokens.append(chunk)
        else:
            tokens.extend(chunk[index : index + 2] for index in range(0, len(chunk) - 1))
    return _dedupe(token for token in tokens if token not in {"the", "and", "with", "version", "开箱", "上手", "体验", "版本"})


def _apply_platform_tone_checks(
    platform_key: str,
    rules: Mapping[str, Any],
    text: str,
    warnings: list[str],
    repair_hints: list[str],
) -> None:
    min_chars = int(rules.get("min_chars") or 0)
    max_chars = int(rules.get("max_chars") or 0)
    length = len(text)
    if length < min_chars:
        warnings.append(f"{rules.get('label')}正文偏短，平台语气可能不够完整")
        repair_hints.append(str(rules.get("tone") or "按平台语气补充。"))
    if max_chars and length > max_chars:
        warnings.append(f"{rules.get('label')}正文偏长，可能不适合当前平台")
        repair_hints.append(str(rules.get("tone") or "按平台语气压缩。"))
    if platform_key in {"wechat_channels", "toutiao"} and re.search(r"(绝绝子|杀疯了|封神|炸裂|离谱到家)", text):
        warnings.append(f"{rules.get('label')}正文网感夸张词偏多")
        repair_hints.append("视频号/头条正文改成更稳的观察和结论，少用爆词。")
    if platform_key == "xiaohongshu" and not re.search(r"(我|到手|实拍|上手|分享|这次|个人|姐妹|家人们)", text):
        warnings.append("小红书正文缺少笔记式亲历感")
        repair_hints.append("小红书建议用到手/实拍/上手后的个人感受开头。")


def _apply_fact_risk_checks(
    text: str,
    fact_sheet: Mapping[str, Any] | None,
    blocking_reasons: list[str],
    warnings: list[str],
    repair_hints: list[str],
) -> None:
    parameter_hits = _dedupe(match.group(0) for match in _PARAMETER_FACT_PATTERN.finditer(text))
    absolute_hits = _dedupe(
        match.group(0)
        for pattern in _ABSOLUTE_FACT_PATTERNS
        for match in pattern.finditer(text)
        if not _is_benign_absolute_context(text, match)
    )
    if not parameter_hits and not absolute_hits:
        return

    verified = _fact_sheet_verified(fact_sheet)
    has_soft_boundary = bool(_SOFT_FACT_PATTERN.search(text))

    if parameter_hits and not verified and not has_soft_boundary:
        blocking_reasons.append(f"正文包含未核验参数：{_join_preview(parameter_hits)}")
        repair_hints.append("未核验参数不要写死；改成画面可见体验，或在 fact_sheet 标记 verified 后再发布。")
    elif parameter_hits and not verified:
        warnings.append(f"正文包含带主观边界的参数表述：{_join_preview(parameter_hits)}")
        repair_hints.append("保留参数时建议加来源或改成“我手上这只/体感”。")

    if absolute_hits and not verified:
        blocking_reasons.append(f"正文包含高风险事实/绝对化词：{_join_preview(absolute_hits)}")
        repair_hints.append("删除唯一、最强、官方认证、治疗等未经核验的绝对化事实。")


def _is_benign_absolute_context(text: str, match: re.Match[str]) -> bool:
    value = match.group(0)
    start = match.start()
    end = match.end()
    window = text[max(0, start - 4) : min(len(text), end + 4)]
    if value == "第一" and re.search(r"第一(眼|次|时间|反应|感觉|印象|视角)", window):
        return True
    return False


def _fact_sheet_verified(fact_sheet: Mapping[str, Any] | None) -> bool:
    if not isinstance(fact_sheet, Mapping):
        return False
    if fact_sheet.get("verified") is True or fact_sheet.get("fact_checked") is True:
        return True
    status = str(fact_sheet.get("status") or fact_sheet.get("verification_status") or "").strip().lower()
    if status in {"verified", "confirmed", "fact_checked", "passed"}:
        return True
    verified_claims = fact_sheet.get("verified_claims")
    return isinstance(verified_claims, (list, tuple, set)) and bool(verified_claims)


def _join_preview(items: list[str], limit: int = 3) -> str:
    preview = [str(item).strip() for item in items if str(item).strip()]
    return "、".join(preview[:limit])


def _dedupe(items: Any) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return values
