from __future__ import annotations

from typing import Any


DEFAULT_SMART_CUT_FILLER_ITEMS = [
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
DEFAULT_SMART_CUT_RULES: dict[str, Any] = {
    "fillerEnabled": True,
    "fillerStandaloneEnabled": True,
    "fillerContinuousEnabled": False,
    "catchphraseEnabled": True,
    "repeatedEnabled": True,
    "pauseEnabled": True,
    "smartDeleteEnabled": True,
    "pauseThresholdSec": 0.8,
    "fillers": DEFAULT_SMART_CUT_FILLERS,
    "catchphrases": DEFAULT_SMART_CUT_CATCHPHRASES,
}


def default_smart_cut_rules_payload() -> dict[str, Any]:
    return dict(DEFAULT_SMART_CUT_RULES)


def normalize_smart_cut_rules_payload(payload: Any) -> dict[str, Any]:
    value = payload if isinstance(payload, dict) else {}
    merged = {
        **DEFAULT_SMART_CUT_RULES,
        **{str(key): item for key, item in value.items() if isinstance(key, str)},
    }
    try:
        pause_threshold_sec = float(merged.get("pauseThresholdSec", DEFAULT_SMART_CUT_RULES["pauseThresholdSec"]) or DEFAULT_SMART_CUT_RULES["pauseThresholdSec"])
    except (TypeError, ValueError):
        pause_threshold_sec = float(DEFAULT_SMART_CUT_RULES["pauseThresholdSec"])
    return {
        "fillerEnabled": bool(merged.get("fillerEnabled")),
        "fillerStandaloneEnabled": bool(merged.get("fillerStandaloneEnabled")),
        "fillerContinuousEnabled": bool(merged.get("fillerContinuousEnabled")),
        "catchphraseEnabled": bool(merged.get("catchphraseEnabled")),
        "repeatedEnabled": bool(merged.get("repeatedEnabled")),
        "pauseEnabled": bool(merged.get("pauseEnabled")),
        "smartDeleteEnabled": bool(merged.get("smartDeleteEnabled")),
        "pauseThresholdSec": round(min(5.0, max(0.1, pause_threshold_sec)), 3),
        "fillers": str(merged.get("fillers") or DEFAULT_SMART_CUT_FILLERS),
        "catchphrases": str(merged.get("catchphrases") or DEFAULT_SMART_CUT_CATCHPHRASES),
    }
