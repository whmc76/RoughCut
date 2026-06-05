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
    "pauseThresholdSec": 0.8,
    "fillers": DEFAULT_SMART_CUT_FILLERS,
    "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
}
_PREVIOUS_EXPANDED_SMART_CUT_RULES: dict[str, Any] = {
    **_PREVIOUS_NARROW_SMART_CUT_RULES,
    "fillerSentenceHeadEnabled": True,
}
_PREVIOUS_EXPANDED_WITH_CATCHPHRASE_SMART_CUT_RULES: dict[str, Any] = {
    **_PREVIOUS_EXPANDED_SMART_CUT_RULES,
    "catchphraseEnabled": True,
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


def _looks_like_previous_narrow_default_rules(value: dict[str, Any]) -> bool:
    normalized_fillers = normalize_smart_cut_fillers_value(value.get("fillers"))
    normalized_catchphrases = str(value.get("catchphrases") or DEFAULT_SMART_CUT_CATCHPHRASES)
    try:
        pause_threshold_sec = round(
            min(
                5.0,
                max(
                    0.1,
                    float(
                        value.get("pauseThresholdSec", DEFAULT_SMART_CUT_RULES["pauseThresholdSec"])
                        or DEFAULT_SMART_CUT_RULES["pauseThresholdSec"]
                    ),
                ),
            ),
            3,
        )
    except (TypeError, ValueError):
        pause_threshold_sec = round(float(DEFAULT_SMART_CUT_RULES["pauseThresholdSec"]), 3)
    return {
        "fillerEnabled": bool(value.get("fillerEnabled")),
        "fillerStandaloneEnabled": bool(value.get("fillerStandaloneEnabled")),
        "fillerSentenceHeadEnabled": bool(value.get("fillerSentenceHeadEnabled")),
        "fillerSentenceTailEnabled": bool(value.get("fillerSentenceTailEnabled")),
        "catchphraseEnabled": bool(value.get("catchphraseEnabled")),
        "repeatedEnabled": bool(value.get("repeatedEnabled")),
        "pauseEnabled": bool(value.get("pauseEnabled")),
        "smartDeleteEnabled": bool(value.get("smartDeleteEnabled")),
        "pauseThresholdSec": pause_threshold_sec,
        "fillers": normalized_fillers,
        "catchphrases": normalized_catchphrases,
    } == _PREVIOUS_NARROW_SMART_CUT_RULES


def _looks_like_previous_legacy_default_rules(value: dict[str, Any]) -> bool:
    if "fillerSentenceHeadEnabled" in value or "fillerSentenceTailEnabled" in value:
        return False
    normalized_fillers = normalize_smart_cut_fillers_value(value.get("fillers"))
    normalized_catchphrases = str(value.get("catchphrases") or DEFAULT_SMART_CUT_CATCHPHRASES)
    try:
        pause_threshold_sec = round(
            min(
                5.0,
                max(
                    0.1,
                    float(
                        value.get("pauseThresholdSec", _PREVIOUS_NARROW_SMART_CUT_RULES["pauseThresholdSec"])
                        or _PREVIOUS_NARROW_SMART_CUT_RULES["pauseThresholdSec"]
                    ),
                ),
            ),
            3,
        )
    except (TypeError, ValueError):
        pause_threshold_sec = round(float(_PREVIOUS_NARROW_SMART_CUT_RULES["pauseThresholdSec"]), 3)
    return {
        "fillerEnabled": bool(value.get("fillerEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["fillerEnabled"])),
        "fillerStandaloneEnabled": bool(value.get("fillerStandaloneEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["fillerStandaloneEnabled"])),
        "catchphraseEnabled": bool(value.get("catchphraseEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["catchphraseEnabled"])),
        "repeatedEnabled": bool(value.get("repeatedEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["repeatedEnabled"])),
        "pauseEnabled": bool(value.get("pauseEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["pauseEnabled"])),
        "smartDeleteEnabled": bool(value.get("smartDeleteEnabled", _PREVIOUS_NARROW_SMART_CUT_RULES["smartDeleteEnabled"])),
        "pauseThresholdSec": pause_threshold_sec,
        "fillers": normalized_fillers,
        "catchphrases": normalized_catchphrases,
        "fillerContinuousEnabled": bool(value.get("fillerContinuousEnabled", False)),
    } == {
        "fillerEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["fillerEnabled"],
        "fillerStandaloneEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["fillerStandaloneEnabled"],
        "catchphraseEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["catchphraseEnabled"],
        "repeatedEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["repeatedEnabled"],
        "pauseEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["pauseEnabled"],
        "smartDeleteEnabled": _PREVIOUS_NARROW_SMART_CUT_RULES["smartDeleteEnabled"],
        "pauseThresholdSec": _PREVIOUS_NARROW_SMART_CUT_RULES["pauseThresholdSec"],
        "fillers": _PREVIOUS_NARROW_SMART_CUT_RULES["fillers"],
        "catchphrases": _PREVIOUS_NARROW_SMART_CUT_RULES["catchphrases"],
        "fillerContinuousEnabled": False,
    }


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
        "pauseThresholdSec": round(min(5.0, max(0.1, pause_threshold_sec)), 3),
        "fillers": normalize_smart_cut_fillers_value(merged.get("fillers") or DEFAULT_SMART_CUT_FILLERS),
        "catchphrases": str(merged.get("catchphrases") or DEFAULT_SMART_CUT_CATCHPHRASES),
    }
    if (
        normalized == _PREVIOUS_EXPANDED_SMART_CUT_RULES
        or normalized == _PREVIOUS_EXPANDED_WITH_CATCHPHRASE_SMART_CUT_RULES
    ):
        return dict(DEFAULT_SMART_CUT_RULES)
    return normalized
