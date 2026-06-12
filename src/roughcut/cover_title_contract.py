from __future__ import annotations

import re
from typing import Any


def normalize_cover_title_line_contract(title_lines: dict[str, str] | None) -> dict[str, str]:
    lines = dict(title_lines or {})
    brand = str(lines.get("brand") or lines.get("top") or "").strip()
    main = str(lines.get("main") or "").strip()
    sub = str(lines.get("sub") or lines.get("bottom") or "").strip()
    hook = str(lines.get("hook") or "").strip()
    return {
        "brand": brand[:14],
        "top": brand[:14],
        "main": main[:18],
        "sub": sub[:18],
        "bottom": sub[:18],
        "hook": hook[:18],
    }


def cover_title_has_action_signal(value: str) -> bool:
    return bool(re.search(r"开箱|评测|测评|教程|体验|实拍|上手|到手|unbox|review|demo", str(value or "").strip(), re.I))


def cover_title_has_evidence_signal(value: str) -> bool:
    return bool(re.search(r"实拍|上手|到手|细节|质感|做工|proof|real", str(value or "").strip(), re.I))


def cover_title_has_variant_signal(value: str) -> bool:
    return bool(re.search(r"顶配|次顶配|双版|双版本|版本|vs|VS|对比", str(value or "").strip(), re.I))


def normalize_cover_title_dedupe_signature(value: str) -> str:
    return re.sub(r"[\s\-—_|｜:：，,。.!！?？·•]+", "", str(value or "").strip()).casefold()


def strip_cover_brand_prefix(value: str, brand: str) -> str:
    text = str(value or "").strip()
    brand_text = str(brand or "").strip()
    if not text or not brand_text:
        return text
    stripped = re.sub(
        rf"^{re.escape(brand_text)}(?:\s+|(?=[A-Za-z0-9\u4e00-\u9fff]))?",
        "",
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip(" -|：:")
    return stripped or text


def strip_cover_action_suffix(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip()).strip()
    if not text:
        return ""
    stripped = re.sub(r"\s*(开箱实拍|开箱|评测|测评|教程|体验|实拍|上手|到手)$", "", text, flags=re.IGNORECASE).strip(" -|：:")
    if stripped and stripped != text:
        return stripped
    return text


def cover_title_semantic_core(
    value: str,
    *,
    brand: str = "",
    strip_compare: bool = False,
    strip_action: bool = False,
    strip_compare_suffix: Any = None,
) -> str:
    text = strip_cover_brand_prefix(value, brand)
    if strip_compare and callable(strip_compare_suffix):
        text = str(strip_compare_suffix(text) or "").strip()
    if strip_action:
        text = strip_cover_action_suffix(text)
    return normalize_cover_title_dedupe_signature(text)


def resolve_cover_title_semantic_slot(*, value: str, layer_role: str) -> str:
    text = str(value or "").strip()
    role = str(layer_role or "").strip().lower()
    if not text:
        return ""
    if role == "brand":
        return "brand"
    if role == "main":
        return "identity"
    has_variant_signal = cover_title_has_variant_signal(text)
    has_action_signal = cover_title_has_action_signal(text)
    has_evidence_signal = cover_title_has_evidence_signal(text)
    if role == "hook":
        if has_action_signal or has_evidence_signal:
            return "action_evidence"
        if has_variant_signal:
            return "variant_compare"
        return "generic_secondary"
    if has_variant_signal:
        return "variant_compare"
    if has_action_signal or has_evidence_signal:
        return "action_evidence"
    return "generic_secondary"


def build_cover_title_semantic_plan(
    *,
    brand: str,
    main: str,
    subtitle: str,
    hook: str,
    strip_compare_suffix: Any = None,
) -> dict[str, dict[str, Any]]:
    normalized = normalize_cover_title_line_contract(
        {
            "brand": brand,
            "main": main,
            "sub": subtitle,
            "hook": hook,
        }
    )
    brand_text = normalized["brand"]
    main_text = normalized["main"]
    subtitle_text = normalized["sub"]
    hook_text = normalized["hook"]
    return {
        "brand": {
            "text": brand_text,
            "signature": normalize_cover_title_dedupe_signature(brand_text),
            "role": "brand",
            "slot": resolve_cover_title_semantic_slot(value=brand_text, layer_role="brand"),
        },
        "main": {
            "text": main_text,
            "signature": cover_title_semantic_core(
                main_text,
                brand=brand_text,
                strip_compare=True,
                strip_action=True,
                strip_compare_suffix=strip_compare_suffix,
            ),
            "has_compare_signal": False,
            "has_action_signal": cover_title_has_action_signal(main_text),
            "role": "identity",
            "slot": resolve_cover_title_semantic_slot(value=main_text, layer_role="main"),
        },
        "subtitle": {
            "text": subtitle_text,
            "signature": cover_title_semantic_core(subtitle_text, brand=brand_text),
            "has_action_signal": cover_title_has_action_signal(subtitle_text),
            "has_evidence_signal": cover_title_has_evidence_signal(subtitle_text),
            "role": "secondary",
            "slot": resolve_cover_title_semantic_slot(value=subtitle_text, layer_role="subtitle"),
        },
        "hook": {
            "text": hook_text,
            "signature": cover_title_semantic_core(hook_text, brand=brand_text),
            "has_action_signal": cover_title_has_action_signal(hook_text),
            "has_evidence_signal": cover_title_has_evidence_signal(hook_text),
            "role": "hook",
            "slot": resolve_cover_title_semantic_slot(value=hook_text, layer_role="hook"),
        },
    }


def dedupe_cover_title_layout_lines(
    *,
    brand: str,
    main: str,
    subtitle: str,
    hook: str,
    strip_compare_suffix: Any = None,
) -> tuple[str, str, str, str]:
    normalized = normalize_cover_title_line_contract(
        {
            "brand": brand,
            "main": main,
            "sub": subtitle,
            "hook": hook,
        }
    )
    brand_text = normalized["brand"]
    raw_main = normalized["main"]
    main_without_brand = strip_cover_brand_prefix(raw_main, brand_text)
    cleaned_main = strip_cover_action_suffix(main_without_brand)
    main_text = cleaned_main or main_without_brand or raw_main
    semantic_plan = build_cover_title_semantic_plan(
        brand=brand_text,
        main=main_text,
        subtitle=normalized["sub"],
        hook=normalized["hook"],
        strip_compare_suffix=strip_compare_suffix,
    )
    subtitle_text = str(semantic_plan["subtitle"]["text"] or "").strip()
    hook_text = str(semantic_plan["hook"]["text"] or "").strip()
    main_sig = str(semantic_plan["main"]["signature"] or "").strip()
    subtitle_sig = str(semantic_plan["subtitle"]["signature"] or "").strip()
    hook_sig = str(semantic_plan["hook"]["signature"] or "").strip()
    subtitle_slot = str(semantic_plan["subtitle"].get("slot") or "").strip()
    hook_slot = str(semantic_plan["hook"].get("slot") or "").strip()

    if subtitle_sig and main_sig and (
        subtitle_sig == main_sig or main_sig.endswith(subtitle_sig) or subtitle_sig in main_sig
    ):
        subtitle_text = ""
        subtitle_sig = ""
        subtitle_slot = ""

    if hook_sig and main_sig and hook_sig == main_sig:
        hook_text = ""
        hook_sig = ""
        hook_slot = ""
    if subtitle_sig and hook_sig:
        same_semantic_text = subtitle_sig == hook_sig or subtitle_sig in hook_sig or hook_sig in subtitle_sig
        same_slot = subtitle_slot and subtitle_slot == hook_slot
        if same_semantic_text or same_slot:
            if hook_slot == "action_evidence":
                subtitle_text = ""
            else:
                hook_text = ""
        elif subtitle_slot == "action_evidence" and hook_slot == "action_evidence":
            subtitle_text = ""

    return brand_text, main_text[:18], subtitle_text[:18], hook_text[:18]
