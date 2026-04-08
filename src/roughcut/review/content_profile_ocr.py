from __future__ import annotations

import re
import unicodedata
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

    for frame in frames:
        for line in frame.lines:
            text = str(line.text or "").strip()
            if not text:
                continue
            try:
                confidence = float(line.confidence)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < 0.42:
                continue
            if _is_ocr_filename_like(text):
                continue
            if _is_ocr_timestamp_like(text):
                continue
            raw_snippets.append(
                {
                    "frame_index": frame.frame_index,
                    "timestamp": float(frame.timestamp),
                    "text": text,
                    "confidence": round(confidence, 4),
                    "box": list(line.box) if line.box is not None else None,
                    "frame_path": frame.frame_path or "",
                }
            )

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
            candidate["confidence"] = max(float(candidate["confidence"]), confidence)
            if text not in candidate["raw_texts"]:
                candidate["raw_texts"].append(text)
            if len(text) > len(str(candidate["display_text"])):
                candidate["display_text"] = text

    normalized_subject_candidates = sorted(
        candidate_map.values(),
        key=lambda item: (
            -int(item["support_count"]),
            -float(item["confidence"]),
            -len(str(item["normalized_text"])),
        ),
    )
    visible_text_candidates = _select_stable_visible_text(
        normalized_subject_candidates,
        frame_count=len(frames),
    )

    visible_text = _compact_visible_text(visible_text_candidates)
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


def _is_ocr_filename_like(text: str) -> bool:
    raw = str(text or "").strip().lower()
    if not raw:
        return False
    if re.fullmatch(r"(img|dsc|mvimg|pxl|cimg|vid|screenshot)[-_]?\d+", raw):
        return True
    if re.fullmatch(r"\d{8}[_-].+", raw):
        return True
    if re.fullmatch(r"[\w\-_]+\.(mov|mp4|avi|mkv|jpg|jpeg|png|webp|heic)$", raw):
        return True
    if raw.replace("-", "").replace("_", "").replace(".", "").isdigit():
        return True
    return False


def _is_ocr_timestamp_like(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw:
        return False
    if re.fullmatch(r"\[\s*\d{1,4}(?:\.\d+)?\s*[-–—]\s*\d{1,4}(?:\.\d+)?\s*\].*", raw):
        return True
    if re.fullmatch(r"\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*[-–—]\s*\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*\].*", raw):
        return True
    if re.fullmatch(r"\[\s*\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\s*\].*", raw):
        return True
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?", raw):
        return True
    return False


def _is_ocr_noise_candidate(item: dict[str, Any]) -> bool:
    normalized = str(item.get("normalized_text") or "").strip()
    display = str(item.get("display_text") or "").strip()
    if not normalized and not display:
        return False
    noise_chunks = {"开箱", "评测", "实测", "介绍", "对比", "上手", "内容", "产品", "视频", "主题"}
    if normalized in noise_chunks or display in noise_chunks:
        return True
    combined = normalized or display
    if not re.search(r"[A-Za-z0-9]", combined) and any(chunk in combined for chunk in noise_chunks):
        return True
    return False


def _score_ocr_candidate(item: dict[str, Any]) -> tuple[int, int, float, int]:
    display = str(item.get("display_text") or "").strip()
    normalized = str(item.get("normalized_text") or "").strip()
    score = 0
    if _is_ocr_noise_candidate(item):
        score -= 8
    if re.search(r"[A-Za-z]", display):
        score += 2
    if re.search(r"\d", display):
        score += 2
    if re.search(r"[\u4e00-\u9fff]", display):
        score += 1
    if re.search(r"[A-Za-z]", display) and re.search(r"\d", display):
        score += 1
    if re.search(r"[A-Za-z]", display) and re.search(r"[\u4e00-\u9fff]", display):
        score += 2
    if len(normalized) >= 8:
        score += 1
    return (score, int(item.get("support_count", 0)), float(item.get("confidence", 0.0)), len(display))


def _select_stable_visible_text(
    candidates: list[dict[str, Any]],
    *,
    frame_count: int,
) -> list[str]:
    if not candidates:
        return []
    preferred = candidates
    if frame_count > 1:
        stable = [item for item in candidates if len(set(item.get("frame_indexes") or [])) >= 2]
        informative_stable = [item for item in stable if not _is_ocr_noise_candidate(item)]
        if informative_stable:
            preferred = informative_stable
        elif stable:
            preferred = candidates
    ordered = sorted(
        preferred,
        key=lambda item: _score_ocr_candidate(item),
        reverse=True,
    )
    visible_candidates = [item for item in ordered if not _is_ocr_noise_candidate(item)]
    if not visible_candidates:
        visible_candidates = ordered
    return [str(item.get("display_text") or "").strip() for item in visible_candidates if str(item.get("display_text") or "").strip()]


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
