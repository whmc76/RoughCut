from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any


_PLATFORM_RULES: dict[str, dict[str, Any]] = {
    "bilibili": {
        "label": "B站",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": 80,
        "recommended_min": 10,
        "recommended_max": 30,
        "preferred": ("开箱", "实测", "对比", "评测", "体验", "细节", "值不值", "怎么选", "总结"),
        "avoid": ("绝绝子", "yyds", "杀疯", "封神"),
        "tone_hint": "补一个带主体、判断或问题角度的信息型标题。",
    },
    "xiaohongshu": {
        "label": "小红书",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": 20,
        "recommended_min": 8,
        "recommended_max": 20,
        "preferred": ("到手", "分享", "开箱", "细节", "质感", "记录", "真的", "种草", "劝退"),
        "avoid": ("官方公告", "技术白皮书", "参数大全"),
        "tone_hint": "改成真实分享、到手感受或细节观察的笔记标题。",
    },
    "douyin": {
        "label": "抖音",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": 55,
        "recommended_min": 6,
        "recommended_max": 22,
        "preferred": ("直接", "到底", "值不值", "结果", "真相", "先看", "一条", "开箱", "居然"),
        "avoid": ("长文解析", "慢慢聊", "完整白皮书"),
        "tone_hint": "改成短促直给、结果先行的标题，但保留主体名。",
    },
    "kuaishou": {
        "label": "快手",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": None,
        "recommended_min": 6,
        "recommended_max": 26,
        "preferred": ("给你们看", "真东西", "实话", "直说", "值不值", "到底", "不整虚的"),
        "avoid": ("封神", "杂志感", "氛围感大片"),
        "tone_hint": "改成口语化、实话感更强的标题。",
    },
    "wechat_channels": {
        "label": "视频号",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": None,
        "recommended_min": 6,
        "recommended_max": 16,
        "preferred": ("总结", "结论", "实测", "体验", "判断", "开箱", "值不值", "重点"),
        "avoid": ("封神", "炸裂", "杀疯", "绝绝子", "离谱"),
        "tone_hint": "改成稳妥可信、结论清楚的标题。",
    },
    "toutiao": {
        "label": "头条号",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": 30,
        "recommended_min": 10,
        "recommended_max": 28,
        "preferred": ("开箱", "实测", "评测", "体验", "结论", "判断", "值不值", "对比"),
        "avoid": ("绝绝子", "封神", "杀疯"),
        "tone_hint": "改成信息摘要和判断导向的标题。",
    },
    "youtube": {
        "label": "YouTube",
        "min_titles": 3,
        "max_titles": 5,
        "hard_max": 100,
        "recommended_min": 18,
        "recommended_max": 70,
        "preferred": ("review", "unboxing", "test", "hands-on", "体验", "评测", "开箱", "实测"),
        "avoid": ("绝绝子", "杀疯", "封神"),
        "tone_hint": "补足可检索的主体、差异点和评测角度。",
    },
    "x": {
        "label": "X",
        "min_titles": 1,
        "max_titles": 3,
        "hard_max": 50,
        "recommended_min": 8,
        "recommended_max": 28,
        "preferred": ("实测", "结论", "观察", "体验", "先看", "quick take", "hands-on"),
        "avoid": ("长文解析", "绝绝子", "封神"),
        "tone_hint": "改成一句短促、可转发的明确观察。",
    },
}

_ANGLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("question", re.compile(r"[？?]|怎么|值不值|要不要|到底|买吗|如何|选哪|选谁")),
    ("emotion", re.compile(r"终于|真香|封神|上头|离谱|惊到|杀疯|爽飞|感动")),
    ("conclusion", re.compile(r"结论|建议|劝退|推荐|不推荐|可买|别买|直说|实话")),
    ("explosive", re.compile(r"直接|居然|原来|先看|一条|炸场|太狠|暴击|开箱")),
    ("informational", re.compile(r"实测|对比|体验|评测|细节|拆解|记录|总结|重点|判断|review|test|hands-on", re.I)),
)

_GENERIC_TITLE_EXACT = {
    "这条视频会怎么发",
    "先看细节",
    "真实体验",
    "真实分享",
    "值得一看",
    "看完再说",
    "这期聊聊",
    "干货满满",
    "不要错过",
    "一定要看",
    "到底怎么样",
    "效果怎么样",
}
_GENERIC_WORDS = {
    "视频",
    "这条",
    "这期",
    "今天",
    "东西",
    "产品",
    "细节",
    "体验",
    "真实",
    "分享",
    "看看",
    "先看",
    "重点",
    "感觉",
}
_AI_TEMPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^(这条|这期|今天).{0,6}(视频|内容|作品)"),
    re.compile(r"^(带你|一起来|让我们|快速了解)"),
    re.compile(r"(看完你就懂|看完再决定|答案都在视频里|建议收藏|干货满满)"),
)
_MARKETING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(全网|爆款|必看|闭眼入|天花板|颠覆|王炸|震撼|史上|超值|买它)"),
    re.compile(r"(不看后悔|错过亏大|直接封神|杀疯了|绝绝子)"),
)


def assess_platform_titles(
    platform_key: str,
    titles: Any,
    *,
    content_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assess generated title candidates for one publishing platform."""

    key = str(platform_key or "").strip()
    rule = _PLATFORM_RULES.get(key, _PLATFORM_RULES["douyin"])
    label = str(rule["label"])
    normalized_titles = _normalize_titles(titles)
    anchor_terms = _build_anchor_terms(content_profile)
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []

    min_titles = int(rule["min_titles"])
    if len(normalized_titles) < min_titles:
        blocking_reasons.append(f"{label}标题少于 {min_titles} 个，当前 {len(normalized_titles)} 个。")
        repair_hints.append(f"补足至少 {min_titles} 个标题，每个标题都要带主体锚点和不同角度。")

    max_titles = int(rule["max_titles"])
    if len(normalized_titles) > max_titles:
        warnings.append(f"{label}标题超过建议数量 {max_titles} 个，后续集成时可能只取前 {max_titles} 个。")

    if not normalized_titles:
        blocking_reasons.append(f"{label}缺少可发布标题。")
        repair_hints.append("先生成带主体名的标题，例如“主体 + 开箱/实测/结论/值不值”。")
        return _build_result(blocking_reasons, warnings, repair_hints)

    unique_titles = {_compact_for_compare(title) for title in normalized_titles}
    if len(unique_titles) < len(normalized_titles):
        blocking_reasons.append(f"{label}存在重复标题，不能直接发布。")
        repair_hints.append("删除重复标题，并分别改成结论、问题、体验或对比角度。")

    anchored_count = 0
    angles: list[str] = []
    for index, title in enumerate(normalized_titles, start=1):
        units = _display_units(title)
        hard_max = rule.get("hard_max")
        if isinstance(hard_max, int) and units > hard_max:
            blocking_reasons.append(f"{label}标题 {index} 长度 {units}，超过硬限制 {hard_max}。")
            repair_hints.append(f"压缩标题 {index}，保留主体名和一个判断点。")

        recommended_min = int(rule["recommended_min"])
        recommended_max = int(rule["recommended_max"])
        if units < recommended_min:
            warnings.append(f"{label}标题 {index} 长度 {units}，信息量偏弱。")
        elif units > recommended_max:
            warnings.append(f"{label}标题 {index} 长度 {units}，超过建议上限 {recommended_max}。")

        anchored = _has_subject_anchor(title, anchor_terms)
        if anchored:
            anchored_count += 1
        if _is_generic_unanchored_title(title, anchor_terms):
            blocking_reasons.append(f"{label}标题 {index}“{title}”没有主体锚点，属于空泛标题。")
            repair_hints.append(f"把标题 {index} 改成“具体主体 + 具体看点/结论”，不要只写体验、细节或这条视频。")
        elif not anchored:
            warnings.append(f"{label}标题 {index}缺少明显主体锚点，识别和搜索会偏弱。")

        avoid_tokens = [token for token in rule["avoid"] if _contains_token(title, token)]
        if avoid_tokens:
            warnings.append(f"{label}标题 {index}含平台不建议语气：{', '.join(avoid_tokens)}。")

        if _looks_ai_template(title):
            warnings.append(f"{label}标题 {index}有 AI 模板腔，建议改成具体对象和具体判断。")
        if _looks_marketing(title):
            warnings.append(f"{label}标题 {index}营销腔偏重，建议降低夸张承诺。")
        angles.append(_primary_angle(title))

    if anchor_terms and anchored_count == 0:
        blocking_reasons.append(f"{label}没有任何标题命中主体锚点：{', '.join(anchor_terms[:4])}。")
        repair_hints.append(f"至少 2 个标题显式写出主体锚点，例如：{anchor_terms[0]} + 实测/开箱/结论。")
    elif anchor_terms and len(normalized_titles) >= 3 and anchored_count < 2:
        blocking_reasons.append(f"{label}只有 {anchored_count} 个标题带主体锚点，低于发布前最低要求 2 个。")
        repair_hints.append("保留不同角度，但把主体品牌、型号或品类补进至少 2 个标题。")

    angle_counts = Counter(angles)
    unique_angles = len({angle for angle in angles if angle})
    if len(normalized_titles) >= 3 and unique_angles <= 1:
        warnings.append(f"{label}标题角度重复，{len(normalized_titles)} 个标题都偏“{angles[0]}”。")
        repair_hints.append("把候选标题拆成问题、结论、体验、信息点等至少 2 种角度。")
    elif len(normalized_titles) >= 4 and angle_counts:
        angle, count = angle_counts.most_common(1)[0]
        if count >= len(normalized_titles) - 1:
            warnings.append(f"{label}标题角度过于集中，{count} 个标题都偏“{angle}”。")
            repair_hints.append("增加一个明显不同的平台化角度，避免 5 个标题像同一模板改字。")

    if not any(_contains_token(title, token) for title in normalized_titles for token in rule["preferred"]):
        warnings.append(f"{label}标题缺少平台常用表达。")
        repair_hints.append(str(rule["tone_hint"]))

    return _build_result(blocking_reasons, warnings, repair_hints)


def _build_result(blocking_reasons: list[str], warnings: list[str], repair_hints: list[str]) -> dict[str, Any]:
    return {
        "publish_ready": not blocking_reasons,
        "blocking_reasons": _dedupe(blocking_reasons),
        "warnings": _dedupe(warnings),
        "repair_hints": _dedupe(repair_hints),
    }


def _normalize_titles(titles: Any) -> list[str]:
    if titles is None:
        return []
    if isinstance(titles, str):
        values = [titles]
    else:
        try:
            values = list(titles)
        except TypeError:
            values = [titles]
    return [re.sub(r"\s+", " ", str(item or "")).strip() for item in values if str(item or "").strip()]


def _build_anchor_terms(content_profile: dict[str, Any] | None) -> list[str]:
    if not isinstance(content_profile, dict):
        return []
    values: list[str] = []
    for key in (
        "subject_brand",
        "subject_model",
        "subject_type",
        "subject_domain",
        "video_theme",
        "summary",
        "hook_line",
        "visible_text",
    ):
        value = str(content_profile.get(key) or "").strip()
        if value:
            values.append(value)
    for item in content_profile.get("search_queries") or []:
        text = str(item or "").strip()
        if text:
            values.append(text)

    terms: list[str] = []
    for value in values:
        terms.append(value)
        terms.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]{1,}|[\u4e00-\u9fff]{2,}", value))

    cleaned: list[str] = []
    for term in terms:
        normalized = _clean_anchor_term(term)
        if not normalized:
            continue
        if normalized in cleaned:
            continue
        cleaned.append(normalized)
    return sorted(cleaned, key=len, reverse=True)[:12]


def _clean_anchor_term(term: str) -> str:
    value = re.sub(r"\s+", " ", str(term or "")).strip(" -_/|，。！？、:：")
    if not value:
        return ""
    compact = re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE)
    if len(compact) < 2:
        return ""
    if len(compact) > 18:
        return ""
    if compact in _GENERIC_WORDS:
        return ""
    if compact.lower() in {"review", "unboxing", "test", "hands", "video"}:
        return ""
    return value


def _has_subject_anchor(title: str, anchor_terms: list[str]) -> bool:
    normalized = title.casefold()
    if anchor_terms:
        return any(term.casefold() in normalized for term in anchor_terms)
    return bool(_specific_tokens_without_profile(title))


def _specific_tokens_without_profile(title: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9._+-]{1,}|[\u4e00-\u9fff]{2,}", title)
    specific: list[str] = []
    for token in tokens:
        compact = re.sub(r"\W+", "", token, flags=re.UNICODE)
        if compact in _GENERIC_WORDS or compact in _GENERIC_TITLE_EXACT:
            continue
        if len(compact) >= 2:
            specific.append(compact)
    return specific


def _is_generic_unanchored_title(title: str, anchor_terms: list[str]) -> bool:
    compact = _compact_for_compare(title)
    if compact in {_compact_for_compare(item) for item in _GENERIC_TITLE_EXACT}:
        return True
    if _has_subject_anchor(title, anchor_terms):
        return False
    tokens = _specific_tokens_without_profile(title)
    if not tokens:
        return True
    generic_hits = sum(1 for word in _GENERIC_WORDS if word in title)
    return generic_hits >= 2 and len(tokens) <= 1


def _primary_angle(title: str) -> str:
    for name, pattern in _ANGLE_PATTERNS:
        if pattern.search(title):
            return name
    return "generic"


def _looks_ai_template(title: str) -> bool:
    return any(pattern.search(title) for pattern in _AI_TEMPLATE_PATTERNS)


def _looks_marketing(title: str) -> bool:
    return any(pattern.search(title) for pattern in _MARKETING_PATTERNS)


def _contains_token(text: str, token: str) -> bool:
    return token.casefold() in text.casefold()


def _compact_for_compare(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or ""), flags=re.UNICODE).casefold()


def _display_units(text: str) -> int:
    units = 0.0
    for char in text:
        if unicodedata.east_asian_width(char) in {"F", "W", "A"}:
            units += 1.0
        elif char.isspace():
            units += 0.5
        else:
            units += 0.5
    return int(math.ceil(units))


def _dedupe(items: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
