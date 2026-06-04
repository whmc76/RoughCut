from __future__ import annotations

import re

HEDGE_PATTERN = re.compile(
    r"(其实|也算|算是|上是|当然|吧|一下|一点|更加|感觉|可能|好像|还是|就|都|也|会|这个|那个|的话)",
    re.UNICODE,
)
PUNCTUATION_PATTERN = re.compile(r"[，。！？!?、；;：:,.\-\s]+", re.UNICODE)
_EDC_CONFLICT_TERMS = ("摄影", "光线", "灯光", "灯具", "补光", "曝光", "色温")
_CAMERA_CONFLICT_TERMS = ("折刀", "开刃", "刀尖", "柄材", "背夹", "钢码")
_ANCHOR_KEYWORDS = (
    "开箱",
    "对比",
    "升级",
    "区别",
    "差异",
    "实测",
    "体验",
    "推荐",
    "参数",
    "尺寸",
    "重量",
    "亮度",
    "续航",
    "功率",
    "容量",
    "价格",
    "便携",
    "口感",
    "味道",
    "口气",
    "零糖",
    "益生菌",
    "含片",
    "弹射",
    "莱德曼",
)
_BRIDGE_OPENERS = (
    "你看",
    "比如",
    "比如说",
    "平时",
    "正常来说",
    "当你",
    "另外",
    "另外呢",
    "然后",
    "然后呢",
    "其实",
    "我们都知道",
)
_NUMERIC_SIGNAL_PATTERN = re.compile(r"\d", re.UNICODE)
_NON_WORD_PATTERN = re.compile(r"[，。！？!?、；;：:,.~\-—_\s\[\]【】()（）]+", re.UNICODE)
_NOISE_MARKER_TERMS = (
    "噪音",
    "杂音",
    "电流",
    "风声",
    "破音",
    "爆麦",
    "喷麦",
    "卡顿",
    "笑声",
    "掌声",
    "音乐",
    "咳嗽",
)
_NOISE_ONLY_TERMS = frozenset(_NOISE_MARKER_TERMS) | {
    "静音",
    "无语音",
    "背景音",
    "环境音",
}
_NOISE_INTERJECTION_CHARS = frozenset("啊嗯呃哦哎诶欸哈呵咳")
_VISUAL_SHOWCASE_TERMS = (
    "欣赏",
    "看一下",
    "来看",
    "看这里",
    "放一起",
    "放在一起",
    "并排",
    "同框",
    "对比看",
    "尺寸对比",
    "左边",
    "右边",
    "近看",
    "特写",
    "展示",
    "演示",
    "操作",
    "实操",
    "实测",
    "看细节",
    "细节",
    "纹理",
    "材质",
    "质感",
    "效果",
    "成品",
    "画面",
    "实拍",
    "镜头",
    "镜面",
    "雾面",
    "上手看",
    "上手",
    "开合",
    "打开",
    "合上",
    "转动",
    "滚动",
    "滑动",
    "按一下",
    "试一下",
    "听一下",
    "展开看",
    "收纳",
    "收纳看",
)
_NORMAL_LANGUAGE_SIGNAL_TERMS = (
    "可以",
    "看到",
    "看一下",
    "来看",
    "这里",
    "这个",
    "那个",
    "就是",
    "因为",
    "所以",
    "但是",
    "如果",
    "然后",
    "感觉",
    "适合",
    "支持",
    "需要",
    "打开",
    "放在",
    "拿来",
    "对比",
    "区别",
    "懒得",
    "看了",
    "不看",
    "想看",
    "想要",
)
_SHORT_NORMAL_LANGUAGE_SIGNAL_RE = re.compile(
    r"(?:我|你|他|她|它|我们|你们|他们|她们|它们|大家).{0,6}"
    r"(?:看|用|拿|放|试|讲|说|做|拆|开|关|装|换|选|买|要|想|懒得|觉得|喜欢|知道|需要|可以)",
    re.UNICODE,
)
_EMPHASIS_REPEAT_CUE_RE = re.compile(r"(?:说|讲|重复)(?:一|两|二|三|3|好多)遍")
_COUNTING_REPEAT_UNIT_RE = re.compile(r"^(?:第[\u4e00-\u9fff\d]{1,3}|[\u4e00-\u9fff\d]{1,3}个)$")


def compact_subtitle_text(text: str) -> str:
    return _NON_WORD_PATTERN.sub("", str(text or "").strip()).upper()


def subtitle_signal_score(text: str, *, content_profile: dict | None) -> float:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return 0.0
    score = 0.0
    if _NUMERIC_SIGNAL_PATTERN.search(compact):
        score += 1.0
    if any(keyword in compact for keyword in _ANCHOR_KEYWORDS):
        score += 1.5
    if has_visual_showcase_signal(compact, content_profile=content_profile):
        score += 1.1
    for token in extract_subject_tokens(content_profile or {}):
        if token and token in compact.upper():
            score += 2.5
            break
    if len(compact) >= 10:
        score += 0.5
    if any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS):
        score -= 1.0
    if is_low_signal_subtitle_text(compact, content_profile=content_profile):
        score -= 1.5
    return score


def is_low_signal_subtitle_text(text: str, *, content_profile: dict | None = None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not compact:
        return True
    if "�" in compact:
        return True
    if looks_like_noise_subtitle(compact):
        return True
    if is_exact_natural_emphasis_repetition(compact):
        return False
    if len(compact) <= 2:
        return True
    if has_normal_language_signal(compact, content_profile=content_profile):
        return False
    if (
        len(compact) <= 8
        and any(compact.startswith(prefix) for prefix in _BRIDGE_OPENERS)
        and not has_anchor_signal(compact, content_profile=content_profile)
        and not has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    repeated_chunk = re.search(r"(.{2,8})\1{1,}", compact)
    if (
        repeated_chunk
        and len(repeated_chunk.group(0)) >= max(4, int(len(compact) * 0.55))
        and not looks_like_natural_emphasis_repetition(
            repeated_chunk.group(1),
            repeat_count=max(2, len(repeated_chunk.group(0)) // max(len(repeated_chunk.group(1)), 1)),
            full_text=compact,
        )
        and not has_anchor_signal(compact, content_profile=content_profile)
        and not has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    unique_chars = len(set(compact))
    if len(compact) >= 8 and unique_chars <= max(2, len(compact) // 5):
        return True
    repeated_token_match = re.fullmatch(r"(.{1,6})", compact)
    if (
        repeated_token_match
        and compact.count(repeated_token_match.group(1)) >= 3
        and not looks_like_natural_emphasis_repetition(
            repeated_token_match.group(1),
            repeat_count=compact.count(repeated_token_match.group(1)),
            full_text=compact,
        )
    ):
        return True
    stripped_hedge = HEDGE_PATTERN.sub("", compact)
    if (
        len(compact) <= 12
        and len(stripped_hedge) <= 4
        and not re.search(r"[A-Za-z0-9]", stripped_hedge)
        and not has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if (
        len(compact) <= 18
        and len(stripped_hedge) <= max(4, int(len(compact) * 0.38))
        and not has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if (
        len(compact) <= 14
        and len(stripped_hedge) <= 5
        and not has_anchor_signal(compact, content_profile=content_profile)
        and not has_visual_showcase_signal(compact, content_profile=content_profile)
    ):
        return True
    if looks_like_subject_conflict_subtitle(compact, content_profile=content_profile):
        return True
    return False


def looks_like_natural_emphasis_repetition(unit: str, *, repeat_count: int, full_text: str = "") -> bool:
    phrase = str(unit or "").strip()
    candidate = str(full_text or "").strip()
    if not phrase or repeat_count < 2:
        return False
    combined = candidate or phrase
    if _EMPHASIS_REPEAT_CUE_RE.search(combined):
        return True
    if repeat_count > 3:
        return False
    if candidate != phrase * repeat_count:
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]{2,4}", phrase):
        return False
    if _COUNTING_REPEAT_UNIT_RE.fullmatch(phrase):
        return False
    return True


def is_nonsemantic_repetition_text(text: str, *, content_profile: dict | None) -> bool:
    compact = compact_subtitle_text(text)
    if len(compact) < 4:
        return False
    repeated_chunk = re.search(r"(.{1,8})\1{1,}", compact)
    if not repeated_chunk:
        return False
    repeated_text = repeated_chunk.group(0)
    unit = repeated_chunk.group(1)
    repeat_count = max(2, len(repeated_text) // max(len(unit), 1))
    if len(repeated_text) < max(4, int(len(compact) * 0.55)):
        return False
    if looks_like_natural_emphasis_repetition(unit, repeat_count=repeat_count, full_text=compact):
        return False
    return not (
        has_anchor_signal(compact, content_profile=content_profile)
        or has_visual_showcase_signal(compact, content_profile=content_profile)
    )


def is_exact_natural_emphasis_repetition(text: str) -> bool:
    candidate = str(text or "").strip()
    if len(candidate) < 4:
        return False
    for unit_len in range(2, len(candidate) // 2 + 1):
        if len(candidate) % unit_len != 0:
            continue
        repeat_count = len(candidate) // unit_len
        unit = candidate[:unit_len]
        if unit * repeat_count != candidate:
            continue
        if looks_like_natural_emphasis_repetition(unit, repeat_count=repeat_count, full_text=candidate):
            return True
    return False


def has_visual_showcase_signal(text: str, *, content_profile: dict | None) -> bool:
    normalized = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if not normalized:
        return False
    return any(term in normalized for term in _VISUAL_SHOWCASE_TERMS)


def has_normal_language_signal(text: str, *, content_profile: dict | None) -> bool:
    compact = PUNCTUATION_PATTERN.sub("", str(text or "").strip())
    if len(compact) < 4:
        return False
    if len(compact) <= 12 and _SHORT_NORMAL_LANGUAGE_SIGNAL_RE.search(compact):
        return True
    if has_anchor_signal(compact, content_profile=content_profile):
        return True
    if has_visual_showcase_signal(compact, content_profile=content_profile):
        return True
    if re.search(r"[A-Za-z0-9]", compact):
        return True
    if (
        len(compact) >= 6
        and len(set(compact)) >= 3
        and any(term in compact for term in _NORMAL_LANGUAGE_SIGNAL_TERMS)
    ):
        return True
    return len(compact) >= 10 and len(set(compact)) >= max(4, len(compact) // 4)


def looks_like_noise_subtitle(text: str) -> bool:
    compact = compact_subtitle_text(text)
    if not compact:
        return False
    if compact in _NOISE_ONLY_TERMS:
        return True
    if any(marker in compact for marker in _NOISE_MARKER_TERMS):
        return True
    if len(compact) <= 6 and set(compact) <= _NOISE_INTERJECTION_CHARS and len(compact) >= 3:
        return True
    if len(compact) <= 8 and re.fullmatch(r"([啊嗯呃哦哎诶欸哈呵咳])\1{2,}", compact):
        return True
    return False


def has_anchor_signal(text: str, *, content_profile: dict | None) -> bool:
    normalized = str(text or "")
    if _NUMERIC_SIGNAL_PATTERN.search(normalized):
        return True
    if any(keyword in normalized for keyword in _ANCHOR_KEYWORDS):
        return True
    subject_tokens = extract_subject_tokens(content_profile or {})
    return any(token in normalized.upper() for token in subject_tokens)


def looks_like_subject_conflict_subtitle(text: str, *, content_profile: dict | None) -> bool:
    profile = content_profile or {}
    family = subject_family(str(profile.get("subject_type") or ""))
    if not family:
        return False
    conflict_terms: tuple[str, ...] = ()
    if family == "edc":
        conflict_terms = _EDC_CONFLICT_TERMS
    elif family == "camera":
        conflict_terms = _CAMERA_CONFLICT_TERMS
    if not conflict_terms:
        return False
    normalized = str(text or "")
    if not any(term in normalized for term in conflict_terms):
        return False
    subject_tokens = extract_subject_tokens(profile)
    if subject_tokens and not any(token in normalized.upper() for token in subject_tokens):
        return False
    return len(normalized) <= 18


def extract_subject_tokens(profile: dict) -> set[str]:
    tokens: set[str] = set()
    for key in ("subject_brand", "subject_model", "visible_text"):
        raw = str(profile.get(key) or "")
        for token in re.findall(r"[A-Za-z0-9-]{2,}", raw.upper()):
            tokens.add(token)
            tokens.add(token.replace("-", ""))
    return {token for token in tokens if token}


def subject_family(subject_type: str) -> str:
    normalized = str(subject_type or "").strip()
    if not normalized:
        return ""
    if any(token in normalized for token in ("折刀", "工具钳", "战术", "EDC", "刀", "背夹", "柄材")):
        return "edc"
    if any(token in normalized for token in ("相机", "镜头", "摄影", "灯", "补光")):
        return "camera"
    return ""
