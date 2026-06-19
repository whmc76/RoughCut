from __future__ import annotations

import re
from typing import Any


LEGACY_DEFAULT_SMART_CUT_FILLER_ITEMS = [
    "嗯",
    "呃",
    "额",
    "呃呃",
    "嗯嗯",
]
EXPANDED_DEFAULT_SMART_CUT_FILLER_ITEMS = [
    "嗯",
    "呃",
    "额",
    "啊",
    "呀",
    "呢",
    "吧",
    "嘛",
    "哦",
    "喔",
    "哎",
    "唉",
    "诶",
    "欸",
    "呃呃",
    "嗯嗯",
]
DEFAULT_SMART_CUT_FILLER_ITEMS = list(EXPANDED_DEFAULT_SMART_CUT_FILLER_ITEMS)
DEFAULT_SMART_CUT_CATCHPHRASE_ITEMS = [
    "就是",
    "然后",
    "其实",
    "你知道",
    "我觉得",
    "怎么说呢",
    "就是说",
]
DEFAULT_SMART_CUT_FILLERS = "，".join(DEFAULT_SMART_CUT_FILLER_ITEMS)
DEFAULT_SMART_CUT_CATCHPHRASES = "，".join(DEFAULT_SMART_CUT_CATCHPHRASE_ITEMS)
SMART_DELETE_AUTO_EDIT_REASONS = [
    "rollback_instruction",
    "restart_retake",
    "restart_cue",
    "failed_attempt",
    "off_topic_interruption",
    "noise_subtitle",
    "low_signal_subtitle",
    "long_non_dialogue",
    "timing_trim",
    "micro_keep",
    "micro_keep_bridge",
    "gap_fill",
]
SMART_DELETE_AUTO_EDIT_REASON_SET = set(SMART_DELETE_AUTO_EDIT_REASONS)
_TERM_SPLIT_PATTERN = re.compile(r"[,，、;；\s]+")
_PREVIOUS_NARROW_SMART_CUT_RULES: dict[str, Any] = {
    "fillerEnabled": True,
    "fillerStandaloneEnabled": True,
    "fillerSentenceHeadEnabled": False,
    "fillerSentenceTailEnabled": False,
    "catchphraseEnabled": False,
    "repeatedEnabled": True,
    "pauseEnabled": True,
    "smartDeleteEnabled": True,
    "disabledSmartDeleteReasons": [],
    "pauseThresholdSec": 0.8,
    "fillers": DEFAULT_SMART_CUT_FILLERS,
    "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
}
DEFAULT_SMART_CUT_RULES: dict[str, Any] = {
    **_PREVIOUS_NARROW_SMART_CUT_RULES,
}


def default_smart_cut_rules_payload() -> dict[str, Any]:
    return dict(DEFAULT_SMART_CUT_RULES)


def _normalize_term_items(value: Any) -> list[str]:
    return [
        item.strip()
        for item in _TERM_SPLIT_PATTERN.split(str(value or ""))
        if item.strip()
    ]


def _items_key(items: list[str]) -> tuple[str, ...]:
    return tuple(sorted(dict.fromkeys(items)))


def normalize_smart_cut_fillers_value(value: Any) -> str:
    items = _normalize_term_items(value)
    if not items:
        return DEFAULT_SMART_CUT_FILLERS
    if _items_key(items) in {
        _items_key(LEGACY_DEFAULT_SMART_CUT_FILLER_ITEMS),
        _items_key(EXPANDED_DEFAULT_SMART_CUT_FILLER_ITEMS),
    }:
        return DEFAULT_SMART_CUT_FILLERS
    return "，".join(dict.fromkeys(items))


def normalize_smart_cut_rules_payload(payload: Any) -> dict[str, Any]:
    value = payload if isinstance(payload, dict) else {}
    merged = {
        **DEFAULT_SMART_CUT_RULES,
        **{str(key): item for key, item in value.items() if isinstance(key, str)},
    }
    legacy_continuous_enabled = bool(merged.get("fillerContinuousEnabled"))
    try:
        pause_threshold_sec = float(merged.get("pauseThresholdSec", DEFAULT_SMART_CUT_RULES["pauseThresholdSec"]) or DEFAULT_SMART_CUT_RULES["pauseThresholdSec"])
    except (TypeError, ValueError):
        pause_threshold_sec = float(DEFAULT_SMART_CUT_RULES["pauseThresholdSec"])
    raw_disabled_reasons = merged.get("disabledSmartDeleteReasons")
    disabled_reason_set = {
        str(reason or "").strip()
        for reason in (raw_disabled_reasons if isinstance(raw_disabled_reasons, list) else [])
        if str(reason or "").strip() in SMART_DELETE_AUTO_EDIT_REASON_SET
    }
    normalized = {
        "fillerEnabled": bool(merged.get("fillerEnabled")),
        "fillerStandaloneEnabled": bool(merged.get("fillerStandaloneEnabled")),
        "fillerSentenceHeadEnabled": bool(
            merged.get("fillerSentenceHeadEnabled")
            if "fillerSentenceHeadEnabled" in merged
            else legacy_continuous_enabled
        ),
        "fillerSentenceTailEnabled": bool(
            merged.get("fillerSentenceTailEnabled")
            if "fillerSentenceTailEnabled" in merged
            else legacy_continuous_enabled
        ),
        "catchphraseEnabled": bool(merged.get("catchphraseEnabled")),
        "repeatedEnabled": bool(merged.get("repeatedEnabled")),
        "pauseEnabled": bool(merged.get("pauseEnabled")),
        "smartDeleteEnabled": bool(merged.get("smartDeleteEnabled")),
        "disabledSmartDeleteReasons": [
            reason for reason in SMART_DELETE_AUTO_EDIT_REASONS if reason in disabled_reason_set
        ],
        "pauseThresholdSec": round(min(5.0, max(0.1, pause_threshold_sec)), 3),
        "fillers": normalize_smart_cut_fillers_value(merged.get("fillers") or DEFAULT_SMART_CUT_FILLERS),
        "catchphrases": str(merged.get("catchphrases") or DEFAULT_SMART_CUT_CATCHPHRASES),
    }
    return normalized
