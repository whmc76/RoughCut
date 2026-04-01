from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

from roughcut.providers.ocr.base import OCRFrameResult


def build_content_profile_ocr(
    frames: Sequence[OCRFrameResult],
    *,
    source_name: str = "",
) -> dict[str, Any]:
    raw_snippets: list[dict[str, Any]] = []
    candidate_map: dict[str, dict[str, Any]] = {}
    visible_parts: list[str] = []

    for frame in frames:
        for line in frame.lines:
            text = str(line.text or "").strip()
            if not text:
                continue
            raw_snippets.append(
                {
                    "frame_index": frame.frame_index,
                    "timestamp": float(frame.timestamp),
                    "text": text,
                    "confidence": round(float(line.confidence), 4),
                    "box": list(line.box) if line.box is not None else None,
                    "frame_path": frame.frame_path or "",
                }
            )
            visible_parts.append(text)

            normalized_text = _normalize_candidate_text(text)
            if not normalized_text:
                continue

            candidate = candidate_map.setdefault(
                normalized_text,
                {
                    "normalized_text": normalized_text,
                    "display_text": text,
                    "raw_texts": [],
                    "frame_indexes": [],
                    "support_count": 0,
                    "confidence": 0.0,
                },
            )
            candidate["support_count"] += 1
            candidate["frame_indexes"].append(frame.frame_index)
            candidate["confidence"] = max(float(candidate["confidence"]), float(line.confidence))
            if text not in candidate["raw_texts"]:
                candidate["raw_texts"].append(text)
            if len(text) > len(str(candidate["display_text"])):
                candidate["display_text"] = text

    normalized_subject_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (-int(item["support_count"]), -float(item["confidence"]), -len(str(item["normalized_text"]))),
    )

    visible_text = _compact_visible_text(visible_parts)
    line_count = len(raw_snippets)
    return {
        "source_name": str(source_name or "").strip(),
        "frame_count": len(frames),
        "line_count": line_count,
        "available": bool(line_count),
        "status": "ok" if line_count else "empty",
        "visible_text": visible_text,
        "raw_snippets": raw_snippets,
        "normalized_subject_candidates": normalized_subject_candidates,
        "subject_brand": "",
        "subject_model": "",
        "subject_type": "",
    }


def _normalize_candidate_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = normalized.lower()
    normalized = normalized.replace("／", "/")
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _compact_visible_text(parts: Sequence[str]) -> str:
    compacted: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = str(part or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        compacted.append(text)
        if len(" ".join(compacted)) >= 120:
            break
    return " ".join(compacted)[:120]
