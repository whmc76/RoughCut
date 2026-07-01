from __future__ import annotations

import re
from typing import Any


def normalize_cover_title_dedupe_signature(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", str(value or "").lower())


def strip_cover_brand_prefix(value: str, brand: str) -> str:
    text = str(value or "").strip()
    prefix = str(brand or "").strip()
    if prefix and text.lower().startswith(prefix.lower()):
        return text[len(prefix):].strip(" -_|")
    return text


def strip_cover_action_suffix(value: str) -> str:
    return re.sub(r"(开箱|评测|测评|教程|体验|对比)$", "", str(value or "").strip(), flags=re.I).strip()


def cover_title_has_action_signal(value: str) -> bool:
    return bool(re.search(r"开箱|评测|测评|教程|体验|对比|unbox|review|tutorial", str(value or ""), re.I))


def cover_title_has_evidence_signal(value: str) -> bool:
    return bool(re.search(r"实拍|实测|到手|细节|做工|手感|质感", str(value or ""), re.I))


def cover_title_has_variant_signal(value: str) -> bool:
    return bool(re.search(r"vs|对比|双版|双版本|顶配|次顶配|版本", str(value or ""), re.I))


def cover_title_semantic_core(
    value: str,
    *,
    brand: str = "",
    strip_compare: bool = False,
    strip_action: bool = False,
    strip_compare_suffix=None,
) -> str:
    text = strip_cover_brand_prefix(value, brand)
    if strip_compare and strip_compare_suffix is not None:
        text = strip_compare_suffix(text)
    if strip_action:
        text = strip_cover_action_suffix(text)
    return re.sub(r"\s+", " ", text).strip()


def resolve_cover_title_semantic_slot(*, value: str, layer_role: str) -> str:
    text = str(value or "").strip()
    role = str(layer_role or "").strip().lower()
    if role in {"brand", "top"}:
        return "brand" if text else ""
    if role in {"sub", "bottom", "subtitle"}:
        return "subtitle" if text else ""
    if role == "hook":
        return "hook" if text else ""
    return "main" if text else ""


def build_cover_title_semantic_plan(*, brand: str, main: str, subtitle: str, hook: str) -> dict[str, dict[str, Any]]:
    return {
        "brand": {"text": str(brand or "").strip(), "role": "brand"},
        "main": {"text": str(main or "").strip(), "role": "main"},
        "subtitle": {"text": str(subtitle or "").strip(), "role": "subtitle"},
        "hook": {"text": str(hook or "").strip(), "role": "hook"},
    }


def dedupe_cover_title_layout_lines(
    *,
    brand: str,
    main: str,
    subtitle: str,
    hook: str,
    strip_compare_suffix=None,
) -> tuple[str, str, str, str]:
    values = [str(item or "").strip() for item in (brand, main, subtitle, hook)]
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        signature = normalize_cover_title_dedupe_signature(value)
        if value and signature in seen:
            result.append("")
        else:
            result.append(value)
            if signature:
                seen.add(signature)
    return result[0], result[1], result[2], result[3]
