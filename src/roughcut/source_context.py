from __future__ import annotations

import re
from typing import Any

from roughcut.review.content_profile_keywords import _is_informative_source_hint, _normalize_profile_value

_FILENAME_DESCRIPTION_PREFIX = "任务说明依据文件名："
_FILENAME_MODEL_SIGNAL_RE = re.compile(r"[A-Za-z]{1,12}\d{1,8}[A-Za-z0-9\u4e00-\u9fff-]{0,12}", re.IGNORECASE)
_FILENAME_TOKEN_RE = re.compile(r"[A-Za-z0-9+#-]{2,}|[\u4e00-\u9fff]{2,}", re.IGNORECASE)
_FILENAME_EDITORIAL_TERM_RE = re.compile(
    r"(开箱|测评|评测|对比|上手|体验|讲解|演示|教程|拆箱|预告|review|unbox|unboxing|compare|vs|workflow|tutorial|demo)",
    re.IGNORECASE,
)
_FILENAME_TRAILING_PUNCTUATION_RE = re.compile(r"[。！？!?]$")
_GENERIC_FILENAME_HINTS = {
    "demo",
    "source",
    "video",
    "clip",
    "test",
    "sample",
    "final",
    "avatar",
    "thumb",
    "thumbnail",
    "merged",
    "watchmerge",
    "taskonly",
    "quality",
    "bundle",
    "render",
    "output",
    "draft",
    "intro",
}


def normalize_filename_hint(value: Any) -> str:
    from pathlib import Path

    stem = Path(str(value or "").strip()).stem
    if not stem:
        return ""
    stem = re.sub(r"^(?:IMG|VID|DSC|PXL|CIMG|MVIMG)[-_]?\d+(?:[_-]\d+)*", "", stem, flags=re.IGNORECASE)
    stem = re.sub(r"^\d{8}(?:[-_]\d{6,})?", "", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    stem = re.sub(r"^[\s._-]+", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" _-")
    if not _is_informative_source_hint(stem):
        return ""
    return stem


def _is_descriptive_filename_hint(text: str) -> bool:
    candidate = str(text or "").strip()
    if not candidate:
        return False
    compact = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", candidate.lower())
    if not compact or compact in _GENERIC_FILENAME_HINTS:
        return False
    tokens = _FILENAME_TOKEN_RE.findall(candidate)
    has_editorial_term = bool(_FILENAME_EDITORIAL_TERM_RE.search(candidate))
    has_model_signal = bool(_FILENAME_MODEL_SIGNAL_RE.search(candidate))
    has_chinese = bool(re.search(r"[\u4e00-\u9fff]", candidate))
    if has_editorial_term:
        return True
    if has_model_signal and len(tokens) >= 2:
        return True
    if has_chinese and len(tokens) >= 2:
        return True
    return len(tokens) >= 3 and any(len(token) >= 4 for token in tokens)


def extract_descriptive_filename_entries(
    *,
    source_name: str | None = None,
    merged_source_names: list[str] | None = None,
) -> list[str]:
    entries: list[str] = []
    seen: set[str] = set()

    def append(value: Any) -> None:
        text = normalize_filename_hint(value)
        normalized = _normalize_profile_value(text)
        if not text or not normalized or normalized in seen or not _is_descriptive_filename_hint(text):
            return
        seen.add(normalized)
        entries.append(text)

    for item in merged_source_names or []:
        append(item)
    if not entries:
        append(source_name)
    return entries[:3]


def build_filename_video_description(
    *,
    source_name: str | None = None,
    merged_source_names: list[str] | None = None,
) -> str | None:
    entries = extract_descriptive_filename_entries(source_name=source_name, merged_source_names=merged_source_names)
    if not entries:
        return None
    text = f"{_FILENAME_DESCRIPTION_PREFIX}{'；'.join(entries)}"
    if not _FILENAME_TRAILING_PUNCTUATION_RE.search(text):
        text = f"{text}。"
    return text


def merge_video_description_with_filename_hints(
    video_description: str | None,
    *,
    source_name: str | None = None,
    merged_source_names: list[str] | None = None,
) -> str | None:
    explicit = str(video_description or "").strip()
    filename_entries = extract_descriptive_filename_entries(
        source_name=source_name,
        merged_source_names=merged_source_names,
    )
    if not filename_entries:
        return explicit[:4000] or None

    filename_brief = "；".join(filename_entries)
    filename_norm = _normalize_profile_value(filename_brief)
    explicit_norm = _normalize_profile_value(explicit)
    if explicit and filename_norm and filename_norm in explicit_norm:
        return explicit[:4000]

    filename_description = build_filename_video_description(
        source_name=source_name,
        merged_source_names=merged_source_names,
    )
    if explicit and filename_description:
        return f"{filename_description}\n{explicit}"[:4000]
    return (filename_description or explicit or "")[:4000] or None


def enrich_source_context_with_filename_hints(
    source_context: dict[str, Any] | None,
    *,
    source_name: str | None = None,
    merged_source_names: list[str] | None = None,
) -> dict[str, Any] | None:
    payload = dict(source_context or {})
    resolved_merged_source_names = [
        str(item).strip()
        for item in (merged_source_names if merged_source_names is not None else payload.get("merged_source_names") or [])
        if str(item).strip()
    ]
    if resolved_merged_source_names:
        payload["merged_source_names"] = resolved_merged_source_names

    merged_description = merge_video_description_with_filename_hints(
        payload.get("video_description"),
        source_name=source_name,
        merged_source_names=resolved_merged_source_names,
    )
    if merged_description:
        payload["video_description"] = merged_description
    else:
        payload.pop("video_description", None)
    return payload or None
