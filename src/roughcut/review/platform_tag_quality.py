from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from typing import Any

_GENERIC_TAGS = {
    "edc",
    "vlog",
    "分享",
    "好物",
    "种草",
    "日常",
    "生活",
    "开箱",
    "体验",
    "实测",
    "测评",
    "评测",
    "推荐",
    "数码",
    "户外",
    "装备",
    "工具",
}

_DANGEROUS_TAG_PATTERNS = (
    "毒品",
    "博彩",
    "赌博",
    "自杀",
    "自残",
    "仇恨",
    "色情",
    "裸聊",
    "枪支",
    "买枪",
    "爆炸物",
    "炸药",
    "黑产",
    "盗号",
    "外挂",
    "翻墙教程",
    "成人",
    "drug",
    "casino",
    "gambling",
    "suicide",
    "selfharm",
    "porn",
    "gun",
    "weapon",
    "explosive",
    "malware",
    "hack",
)

_PLATFORM_LIMITS: dict[str, dict[str, int]] = {
    "bilibili": {"min": 1, "max": 10},
    "xiaohongshu": {"min": 1, "max": 10},
    "douyin": {"min": 1, "max": 8},
    "kuaishou": {"min": 1, "max": 8},
    "wechat_channels": {"min": 1, "max": 6},
    "toutiao": {"min": 1, "max": 8},
    "youtube": {"min": 1, "max": 15},
    "x": {"min": 1, "max": 5},
}

_PLATFORM_LABEL_TAGS: dict[str, set[str]] = {
    "bilibili": {"小红书", "抖音", "快手", "视频号", "youtube", "twitter", "x"},
    "xiaohongshu": {"b站", "bilibili", "抖音", "快手", "视频号", "youtube", "twitter", "x"},
    "douyin": {"b站", "bilibili", "小红书", "快手", "视频号", "youtube", "twitter", "x"},
    "kuaishou": {"b站", "bilibili", "小红书", "抖音", "视频号", "youtube", "twitter", "x"},
    "wechat_channels": {"b站", "bilibili", "小红书", "抖音", "快手", "youtube", "twitter", "x"},
    "toutiao": {"b站", "bilibili", "小红书", "抖音", "快手", "视频号", "youtube", "twitter", "x"},
    "youtube": {"b站", "小红书", "抖音", "快手", "视频号", "头条"},
    "x": {"b站", "小红书", "抖音", "快手", "视频号", "头条"},
}

_ANCHOR_PROFILE_FIELDS = (
    "subject_brand",
    "subject_model",
    "subject_type",
    "subject_domain",
    "product_name",
    "scene",
    "use_scene",
    "usage_scene",
    "video_theme",
)


def assess_platform_tags(
    platform_key: str,
    tags: Iterable[Any] | None,
    *,
    content_profile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_tags, duplicate_tags = _normalize_tags(tags)
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    repair_hints: list[str] = []

    limits = _PLATFORM_LIMITS.get(str(platform_key or "").strip(), {"min": 1, "max": 10})
    if len(normalized_tags) < limits["min"]:
        blocking_reasons.append("标签为空，无法发布。")
        repair_hints.append("补充 3-6 个标签，至少包含 1 个主体/品类/品牌/场景锚点。")
    if len(normalized_tags) > limits["max"]:
        blocking_reasons.append(f"标签数量超过平台建议上限 {limits['max']} 个。")
        repair_hints.append(f"保留最相关的主体、品类、场景标签，删除到 {limits['max']} 个以内。")
    if duplicate_tags:
        warnings.append(f"已去重重复标签：{', '.join(duplicate_tags)}。")

    dangerous_tags = [tag for tag in normalized_tags if _contains_any(tag, _DANGEROUS_TAG_PATTERNS)]
    if dangerous_tags:
        blocking_reasons.append(f"包含违禁或危险导向标签：{', '.join(dangerous_tags)}。")
        repair_hints.append("移除危险、违法、成人、黑产或自伤导向标签，改为中性内容标签。")

    mismatched_tags = _platform_mismatched_tags(platform_key, normalized_tags)
    if mismatched_tags:
        warnings.append(f"疑似混入其他平台标签：{', '.join(mismatched_tags)}。")
        repair_hints.append("删除其他平台名称类标签，换成内容主体或使用场景标签。")

    generic_tags = [tag for tag in normalized_tags if _is_generic_tag(tag)]
    anchor_tags = [tag for tag in normalized_tags if _is_anchor_tag(tag, content_profile)]
    if normalized_tags and not anchor_tags:
        blocking_reasons.append("标签缺少主体/品类/品牌/场景锚点。")
        repair_hints.append("至少加入 1 个能指向内容主体的标签，例如品牌、型号、品类或具体使用场景。")
    elif len(generic_tags) >= max(2, len(normalized_tags) // 2 + 1):
        warnings.append("泛标签占比偏高，搜索和推荐识别度不足。")
        repair_hints.append("减少 EDC/开箱/体验 等泛标签，增加主体、品类、品牌或场景标签。")

    if generic_tags and len(generic_tags) == len(normalized_tags):
        reason = "只有泛标签组合，必须补充主体/品类/品牌/场景锚点。"
        if reason not in blocking_reasons:
            blocking_reasons.append(reason)
        repair_hints.append("减少 EDC/开箱/体验 等泛标签，增加主体、品类、品牌或场景标签。")

    return {
        "publish_ready": not blocking_reasons,
        "blocking_reasons": _dedupe_messages(blocking_reasons),
        "warnings": _dedupe_messages(warnings),
        "repair_hints": _dedupe_messages(repair_hints),
        "normalized_tags": normalized_tags,
    }


def _normalize_tags(tags: Iterable[Any] | None) -> tuple[list[str], list[str]]:
    normalized: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    for raw in tags or []:
        tag = _normalize_tag(raw)
        if not tag:
            continue
        key = _tag_key(tag)
        if key in seen:
            duplicates.append(tag)
            continue
        seen.add(key)
        normalized.append(tag)
    return normalized, duplicates


def _normalize_tag(raw: Any) -> str:
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    text = text.strip("#＃")
    text = re.sub(r"\s+", " ", text)
    text = text.strip(" \t\r\n,，;；、。")
    return text


def _tag_key(tag: str) -> str:
    return re.sub(r"[\s_\-#＃]+", "", tag).casefold()


def _is_generic_tag(tag: str) -> bool:
    key = _tag_key(tag)
    return key in {_tag_key(item) for item in _GENERIC_TAGS}


def _is_anchor_tag(tag: str, content_profile: Mapping[str, Any] | None) -> bool:
    if not tag or _is_generic_tag(tag) or _contains_any(tag, _DANGEROUS_TAG_PATTERNS):
        return False

    key = _tag_key(tag)
    profile_terms = _profile_anchor_terms(content_profile)
    if profile_terms and any(term in key or key in term for term in profile_terms):
        return True

    return _looks_specific(tag)


def _looks_specific(tag: str) -> bool:
    key = _tag_key(tag)
    if len(key) < 3:
        return False
    if re.search(r"[a-zA-Z]+\d|\d+[a-zA-Z]|[A-Z]{2,}", tag):
        return True
    return len(tag) >= 4


def _profile_anchor_terms(content_profile: Mapping[str, Any] | None) -> set[str]:
    if not content_profile:
        return set()

    terms: set[str] = set()
    for field in _ANCHOR_PROFILE_FIELDS:
        value = content_profile.get(field)
        if isinstance(value, str):
            terms.update(_split_anchor_text(value))
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            for item in value:
                if isinstance(item, str):
                    terms.update(_split_anchor_text(item))

    keywords = content_profile.get("keywords")
    if isinstance(keywords, Iterable) and not isinstance(keywords, (str, bytes, Mapping)):
        for keyword in keywords:
            if isinstance(keyword, str):
                terms.update(_split_anchor_text(keyword))

    return {term for term in terms if len(term) >= 2}


def _split_anchor_text(text: str) -> set[str]:
    normalized = _normalize_tag(text)
    pieces = re.split(r"[\s,，/／|、;；()（）\[\]【】]+", normalized)
    return {_tag_key(piece) for piece in pieces if piece.strip()}


def _platform_mismatched_tags(platform_key: str, normalized_tags: list[str]) -> list[str]:
    blocked_labels = _PLATFORM_LABEL_TAGS.get(str(platform_key or "").strip(), set())
    return [tag for tag in normalized_tags if _tag_key(tag) in {_tag_key(label) for label in blocked_labels}]


def _contains_any(text: str, patterns: Iterable[str]) -> bool:
    key = _tag_key(text)
    return any(_tag_key(pattern) in key for pattern in patterns)


def _dedupe_messages(messages: Iterable[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if message in seen:
            continue
        seen.add(message)
        deduped.append(message)
    return deduped
