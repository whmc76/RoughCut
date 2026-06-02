from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any

from roughcut.config import DEFAULT_MINIMAX_REASONING_MODEL, get_settings

ARTIFACT_TYPE_VIDEO_UNDERSTANDING = "video_understanding"
VIDEO_UNDERSTANDING_SCHEMA_VERSION = "video_understanding_v1"

_DETAIL_SECTION_TERMS = ("展示", "细节", "上手", "对比", "实测", "演示", "开箱", "体验")
_HIGH_DENSITY_TERMS = ("教程", "步骤", "参数", "区别", "差异", "配置", "功能", "对比", "实测")
_FAST_PACE_TERMS = ("高能", "快速", "速看", "连招", "实战", "对局")
_PLATFORM_TERMS = {
    "douyin": ("短视频", "速看", "开箱", "高能"),
    "bilibili": ("评测", "对比", "教程", "实测"),
}
_SECONDARY_ROLE_MARKERS = ("comparison", "对比", "supporting", "related", "配套", "secondary", "accessory")
_SEGMENT_RANGE_RE = re.compile(
    r"(?P<start>\d+(?::\d{1,2}){0,2}(?:\.\d+)?)\s*(?:-|~|—|–|至|到)\s*(?P<end>\d+(?::\d{1,2}){0,2}(?:\.\d+)?)"
)
_SEGMENT_POINT_RE = re.compile(r"\d+(?::\d{1,2}){0,2}(?:\.\d+)?")
_SEGMENT_ROLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("hook", ("hook", "opening", "intro", "开头", "开场", "前半句", "破题")),
    ("cta", ("cta", "closing", "outro", "结尾", "收口", "互动")),
    ("comparison", ("comparison", "contrast", "对比", "差异", "区别")),
    ("detail_showcase", ("detail", "showcase", "closeup", "细节", "特写", "做工", "展示")),
    ("demo", ("demo", "hands_on", "实测", "演示", "上手", "操作")),
    ("retake", ("retake", "ng", "重来", "口误", "卡壳")),
    ("junk", ("junk", "invalid", "废片", "无效", "等待", "空镜", "静音")),
    ("transition", ("transition", "broll", "过渡", "转场")),
    ("body", ("body", "explanation", "explain", "讲解", "主体", "说明")),
)


def build_video_understanding_payload(
    profile: Mapping[str, Any] | None,
    *,
    source_name: str = "",
    transcript_excerpt: str = "",
) -> dict[str, Any]:
    candidate = dict(profile or {})
    content_understanding = _as_dict(candidate.get("content_understanding"))
    visual_semantic_evidence = _as_dict(candidate.get("visual_semantic_evidence"))
    visual_hints = _as_dict(candidate.get("visual_hints")) or _as_dict(candidate.get("visual_cluster_hints"))
    ocr_profile = _as_dict(candidate.get("ocr_profile"))
    source_context = _as_dict(candidate.get("source_context"))
    transcript_text = _text(transcript_excerpt) or _text(candidate.get("transcript_excerpt"))
    provider, model_name, mode = _resolve_model_route(
        content_understanding=content_understanding,
        visual_semantic_evidence=visual_semantic_evidence,
    )
    narrative_structure = _build_narrative_structure(candidate, content_understanding)
    primary_subject = {
        "name": _text(candidate.get("subject_type")),
        "brand": _text(candidate.get("subject_brand")),
        "model": _text(candidate.get("subject_model")),
        "type": _text(candidate.get("subject_type")),
    }

    return {
        "schema_version": VIDEO_UNDERSTANDING_SCHEMA_VERSION,
        "model": {
            "provider": provider,
            "model": model_name,
            "mode": mode,
        },
        "global_understanding": {
            "video_type": _text(content_understanding.get("video_type") or candidate.get("content_kind")),
            "content_domain": _text(content_understanding.get("content_domain") or candidate.get("subject_domain")),
            "primary_subject": primary_subject,
            "secondary_subjects": _build_secondary_subjects(content_understanding, primary_subject=primary_subject),
            "video_theme": _text(candidate.get("video_theme") or content_understanding.get("video_theme")),
            "summary": _text(candidate.get("summary") or content_understanding.get("summary")),
            "hook_hypothesis": _text(candidate.get("hook_line") or content_understanding.get("hook_line")),
            "narrative_structure": narrative_structure,
            "style_profile": _build_style_profile(
                candidate,
                transcript_excerpt=transcript_text,
                visual_semantic_evidence=visual_semantic_evidence,
            ),
        },
        "segment_understanding": _build_segment_understanding(
            candidate,
            content_understanding=content_understanding,
            visual_semantic_evidence=visual_semantic_evidence,
            narrative_structure=narrative_structure,
        ),
        "evidence": {
            "source_name": _text(source_name),
            "transcript_excerpt": transcript_text[:1600],
            "source_context": source_context,
            "ocr_evidence": _build_ocr_evidence(ocr_profile, candidate),
            "visual_semantic_evidence": visual_semantic_evidence,
            "visual_hints": visual_hints,
            "evidence_spans": _dict_list(content_understanding.get("evidence_spans"), limit=12),
            "speech_visual_alignment_issues": [],
            "uncertainties": _string_list(content_understanding.get("uncertainties"), limit=8),
            "conflicts": _string_list(content_understanding.get("conflicts"), limit=8),
        },
        "automation_hints": {
            "term_correction_bias": {
                "allowed_hotwords": _build_allowed_hotwords(candidate, content_understanding, visual_semantic_evidence),
                "blocked_hotwords": [],
            },
            "editing_bias": {
                "protect_roles": _build_protect_roles(visual_semantic_evidence),
                "drop_roles": ["retake", "junk"],
                "preferred_sections": [
                    str(section.get("label") or "").strip()
                    for section in narrative_structure
                    if str(section.get("label") or "").strip()
                ][:4],
            },
        },
        "review": {
            "needs_review": bool(content_understanding.get("needs_review", True)),
            "review_reasons": _string_list(content_understanding.get("review_reasons"), limit=12),
            "confidence": _build_review_confidence(content_understanding, visual_semantic_evidence),
        },
    }


def normalize_video_understanding_segment_hints(
    video_understanding: Mapping[str, Any] | None,
    *,
    duration: float | None = None,
) -> list[dict[str, Any]]:
    payload = dict(video_understanding or {})
    segments = payload.get("segment_understanding")
    if not isinstance(segments, list):
        return []
    review = _as_dict(payload.get("review"))
    confidence = _as_dict(review.get("confidence"))
    fallback_confidence = _float_value(confidence.get("segment_roles") or confidence.get("overall"))
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(segments):
        normalized_item = _normalize_segment_hint_item(
            item,
            index=index,
            duration=duration,
            fallback_confidence=fallback_confidence,
        )
        if normalized_item and normalized_item not in normalized:
            normalized.append(normalized_item)
    normalized.sort(key=lambda item: (float(item.get("start", 0.0) or 0.0), float(item.get("end", 0.0) or 0.0)))
    return normalized[:12]


def _resolve_model_route(
    *,
    content_understanding: dict[str, Any],
    visual_semantic_evidence: dict[str, Any],
) -> tuple[str, str, str]:
    settings = get_settings()
    capability_matrix = _as_dict(content_understanding.get("capability_matrix"))
    visual_capability = _as_dict(capability_matrix.get("visual_understanding"))
    provider = (
        _text(visual_semantic_evidence.get("provider"))
        or _text(visual_capability.get("provider"))
        or _text(getattr(settings, "active_reasoning_provider", ""))
        or _text(getattr(settings, "reasoning_provider", ""))
    )
    mode = (
        _text(visual_semantic_evidence.get("mode"))
        or _text(visual_capability.get("mode"))
        or "hybrid_profile_fusion"
    )
    model_name = _text(getattr(settings, "active_reasoning_model", "")) or _text(getattr(settings, "reasoning_model", ""))
    if provider.lower() == "minimax" and mode == "native_multimodal":
        model_name = "MiniMax-M3"
    if not model_name and provider.lower() == "minimax":
        model_name = DEFAULT_MINIMAX_REASONING_MODEL
    return provider, model_name, mode


def _build_secondary_subjects(
    content_understanding: dict[str, Any],
    *,
    primary_subject: dict[str, str],
) -> list[dict[str, str]]:
    secondary: list[dict[str, str]] = []
    primary_norm = _normalize_text(primary_subject.get("name"))
    for item in list(content_understanding.get("subject_entities") or []):
        entity = _as_dict(item)
        name = _text(entity.get("name"))
        if not name or _normalize_text(name) == primary_norm:
            continue
        kind = _text(entity.get("kind")).lower()
        if not any(marker in kind for marker in _SECONDARY_ROLE_MARKERS):
            continue
        payload = {
            "kind": kind,
            "name": name,
            "brand": _text(entity.get("brand")),
            "model": _text(entity.get("model")),
        }
        if payload not in secondary:
            secondary.append(payload)
    return secondary[:8]


def _build_narrative_structure(
    profile: Mapping[str, Any],
    content_understanding: Mapping[str, Any],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    hook_line = _text(profile.get("hook_line") or content_understanding.get("hook_line"))
    video_theme = _text(profile.get("video_theme") or content_understanding.get("video_theme"))
    summary = _text(profile.get("summary") or content_understanding.get("summary"))
    engagement_question = _text(profile.get("engagement_question") or content_understanding.get("engagement_question"))
    if hook_line:
        sections.append(
            {
                "section_id": "hook_1",
                "label": "hook",
                "summary": hook_line,
                "evidence": [hook_line],
            }
        )
    if video_theme:
        label = "demo" if any(term in video_theme for term in _DETAIL_SECTION_TERMS) else "body"
        sections.append(
            {
                "section_id": "body_1",
                "label": label,
                "summary": video_theme,
                "evidence": [video_theme],
            }
        )
    if summary and _normalize_text(summary) not in {_normalize_text(hook_line), _normalize_text(video_theme)}:
        sections.append(
            {
                "section_id": "body_2",
                "label": "body",
                "summary": summary,
                "evidence": [summary],
            }
        )
    if engagement_question:
        sections.append(
            {
                "section_id": "cta_1",
                "label": "cta",
                "summary": engagement_question,
                "evidence": [engagement_question],
            }
        )
    return sections[:4]


def _build_style_profile(
    profile: Mapping[str, Any],
    *,
    transcript_excerpt: str,
    visual_semantic_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    theme_blob = " ".join(
        part
        for part in (
            _text(profile.get("video_theme")),
            _text(profile.get("summary")),
            _text(profile.get("hook_line")),
            transcript_excerpt[:600],
        )
        if part
    )
    info_density = "high" if any(term in theme_blob for term in _HIGH_DENSITY_TERMS) or len(theme_blob) >= 220 else "medium"
    pace = "fast" if any(term in theme_blob for term in _FAST_PACE_TERMS) else "medium"
    emotion_intensity = "medium" if _text(profile.get("hook_line")) else "low"
    platform_bias: list[str] = []
    for platform, cues in _PLATFORM_TERMS.items():
        if any(cue in theme_blob for cue in cues):
            platform_bias.append(platform)
    if _string_list(visual_semantic_evidence.get("visible_models"), limit=8):
        info_density = "high"
    return {
        "pace": pace,
        "information_density": info_density,
        "emotion_intensity": emotion_intensity,
        "platform_bias": platform_bias[:3],
    }


def _build_ocr_evidence(ocr_profile: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    visible_text = _text(profile.get("visible_text") or ocr_profile.get("visible_text"))
    return {
        "visible_text": visible_text,
        "lines": _string_list(ocr_profile.get("text_lines"), limit=12),
    }


def _build_allowed_hotwords(
    profile: Mapping[str, Any],
    content_understanding: Mapping[str, Any],
    visual_semantic_evidence: Mapping[str, Any],
) -> list[str]:
    hotwords: list[str] = []

    def add(value: Any) -> None:
        text = _text(value)
        if text and text not in hotwords:
            hotwords.append(text)

    for key in ("subject_brand", "subject_model", "subject_type", "video_theme"):
        add(profile.get(key))
    for key in ("visible_brands", "visible_models", "subject_candidates"):
        for item in list(visual_semantic_evidence.get(key) or []):
            add(item)
    semantic_facts = _as_dict(content_understanding.get("semantic_facts"))
    for key in ("brand_candidates", "model_candidates", "product_name_candidates", "product_type_candidates"):
        for item in list(semantic_facts.get(key) or []):
            add(item)
    for item in list(profile.get("search_queries") or [])[:4]:
        add(item)
    return hotwords[:16]


def _build_protect_roles(visual_semantic_evidence: Mapping[str, Any]) -> list[str]:
    roles = ["detail_showcase"]
    interaction_type = _text(visual_semantic_evidence.get("interaction_type"))
    if "对比" in interaction_type or "comparison" in interaction_type.lower():
        roles.append("comparison")
    if "展示" in interaction_type or "演示" in interaction_type or "demo" in interaction_type.lower():
        roles.append("demo")
    return roles


def _build_segment_understanding(
    profile: Mapping[str, Any],
    *,
    content_understanding: Mapping[str, Any],
    visual_semantic_evidence: Mapping[str, Any],
    narrative_structure: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    confidence = _as_dict(content_understanding.get("confidence"))
    fallback_confidence = _float_value(confidence.get("overall"))
    if fallback_confidence <= 0.0 and visual_semantic_evidence:
        fallback_confidence = 0.35
    raw_segments: list[dict[str, Any]] = []
    for index, span in enumerate(list(content_understanding.get("evidence_spans") or [])[:8]):
        if not isinstance(span, Mapping):
            continue
        raw_segments.append(
            {
                "segment_id": str(span.get("segment_id") or f"vu_span_{index + 1}"),
                "timestamp": span.get("timestamp"),
                "text": _text(span.get("text")),
                "role": _resolve_segment_role(span.get("type"), text=span.get("text")),
                "keep_priority": _resolve_segment_keep_priority(
                    role=_resolve_segment_role(span.get("type"), text=span.get("text")),
                    text=span.get("text"),
                ),
                "reason_tags": _segment_reason_tags(
                    role=_resolve_segment_role(span.get("type"), text=span.get("text")),
                    raw_type=span.get("type"),
                ),
                "confidence": max(0.28, fallback_confidence or 0.0),
            }
        )
    if not raw_segments and narrative_structure:
        for index, section in enumerate(narrative_structure[:4]):
            role = _resolve_segment_role(section.get("label"), text=section.get("summary"))
            raw_segments.append(
                {
                    "segment_id": str(section.get("section_id") or f"vu_section_{index + 1}"),
                    "timestamp": section.get("timestamp"),
                    "text": _text(section.get("summary")),
                    "role": role,
                    "keep_priority": _resolve_segment_keep_priority(role=role, text=section.get("summary")),
                    "reason_tags": _segment_reason_tags(role=role, raw_type=section.get("label")),
                    "confidence": max(0.24, fallback_confidence or 0.0),
                }
            )
    return normalize_video_understanding_segment_hints(
        {
            "segment_understanding": raw_segments,
            "review": {"confidence": {"segment_roles": fallback_confidence}},
        }
    )


def _build_review_confidence(
    content_understanding: Mapping[str, Any],
    visual_semantic_evidence: Mapping[str, Any],
) -> dict[str, float]:
    confidence = _as_dict(content_understanding.get("confidence"))
    overall = _float_value(confidence.get("overall"))
    if overall <= 0.0 and visual_semantic_evidence:
        overall = 0.35
    topic_confidence = _float_value(confidence.get("topic") or overall)
    structure_confidence = _float_value(confidence.get("structure") or overall)
    segment_role_confidence = 0.0
    if visual_semantic_evidence and str(visual_semantic_evidence.get("status") or "").strip().lower() == "ready":
        segment_role_confidence = max(0.28, overall or 0.0)
    return {
        "overall": round(overall, 3),
        "topic": round(topic_confidence, 3),
        "structure": round(structure_confidence, 3),
        "segment_roles": round(segment_role_confidence, 3),
    }


def _normalize_segment_hint_item(
    item: Any,
    *,
    index: int,
    duration: float | None,
    fallback_confidence: float,
) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    role = _resolve_segment_role(item.get("role") or item.get("type") or item.get("label"), text=item.get("summary") or item.get("text"))
    if not role:
        return None
    start, end = _resolve_segment_bounds(item, role=role, duration=duration)
    if end <= start:
        return None
    keep_priority = _resolve_segment_keep_priority(
        role=role,
        explicit=item.get("keep_priority"),
        text=item.get("summary") or item.get("text"),
    )
    confidence = _float_value(item.get("confidence"))
    if confidence <= 0.0:
        confidence = fallback_confidence
    if confidence <= 0.0:
        confidence = 0.32 if keep_priority == "drop" else 0.38
    reason_tags = _string_list(item.get("reason_tags"), limit=8) or _segment_reason_tags(role=role, raw_type=item.get("type"))
    summary = _text(item.get("summary") or item.get("text"))
    normalized = {
        "segment_id": _text(item.get("segment_id") or item.get("section_id") or f"vu_segment_{index + 1}"),
        "start": round(start, 3),
        "end": round(end, 3),
        "duration_sec": round(max(0.0, end - start), 3),
        "role": role,
        "keep_priority": keep_priority,
        "reason_tags": reason_tags,
        "confidence": round(confidence, 3),
    }
    if summary:
        normalized["summary"] = summary[:120]
    return normalized


def _resolve_segment_bounds(
    item: Mapping[str, Any],
    *,
    role: str,
    duration: float | None,
) -> tuple[float, float]:
    start = _coerce_float(item.get("start"))
    if start is None:
        start = _coerce_float(item.get("start_sec"))
    if start is None:
        start = _coerce_float(item.get("start_time"))
    end = _coerce_float(item.get("end"))
    if end is None:
        end = _coerce_float(item.get("end_sec"))
    if end is None:
        end = _coerce_float(item.get("end_time"))
    if start is not None and end is not None:
        return _clamp_segment_bounds(start, end, duration=duration)
    timestamp_range = _parse_segment_timestamp_range(item.get("timestamp"))
    if timestamp_range is not None:
        return _clamp_segment_bounds(timestamp_range[0], timestamp_range[1], duration=duration)
    if start is not None:
        return _clamp_segment_bounds(start, start + _default_segment_duration(role), duration=duration)
    return 0.0, 0.0


def _parse_segment_timestamp_range(value: Any) -> tuple[float, float] | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        start = max(0.0, float(value))
        return start, start + 2.8
    text = _text(value)
    if not text:
        return None
    range_match = _SEGMENT_RANGE_RE.search(text)
    if range_match:
        start = _parse_time_token(range_match.group("start"))
        end = _parse_time_token(range_match.group("end"))
        if start is not None and end is not None:
            return start, end
    point_match = _SEGMENT_POINT_RE.search(text)
    if not point_match:
        return None
    point = _parse_time_token(point_match.group(0))
    if point is None:
        return None
    return point, point + 2.8


def _parse_time_token(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return max(0.0, float(text))
    parts = text.split(":")
    if not 1 <= len(parts) <= 3:
        return None
    try:
        numbers = [float(part) for part in parts]
    except ValueError:
        return None
    seconds = 0.0
    for number in numbers:
        seconds = seconds * 60 + number
    return max(0.0, seconds)


def _resolve_segment_role(value: Any, *, text: Any = None) -> str:
    tokens = " ".join(part for part in (_text(value).lower(), _text(text).lower()) if part)
    if not tokens:
        return ""
    for role, cues in _SEGMENT_ROLE_KEYWORDS:
        if any(cue in tokens for cue in cues):
            return role
    return "body"


def _resolve_segment_keep_priority(
    *,
    role: str,
    explicit: Any = None,
    text: Any = None,
) -> str:
    normalized = _text(explicit).strip().lower()
    if normalized in {"high", "medium", "low", "drop"}:
        return normalized
    text_blob = _text(text).lower()
    if role in {"retake", "junk"} or any(token in text_blob for token in ("废片", "无效", "删掉", "重来", "口误")):
        return "drop"
    if role in {"hook", "cta", "comparison", "detail_showcase", "demo"}:
        return "high"
    if role == "transition":
        return "low"
    return "medium"


def _segment_reason_tags(*, role: str, raw_type: Any) -> list[str]:
    tags = [role]
    raw_text = _text(raw_type).strip().lower()
    if raw_text and raw_text not in tags:
        tags.append(raw_text)
    if role in {"comparison", "detail_showcase", "demo"}:
        tags.append("visual_priority")
    elif role in {"retake", "junk"}:
        tags.append("drop_candidate")
    return tags[:8]


def _default_segment_duration(role: str) -> float:
    return {
        "hook": 3.2,
        "cta": 2.8,
        "comparison": 4.0,
        "detail_showcase": 3.8,
        "demo": 4.2,
        "transition": 2.0,
        "retake": 2.4,
        "junk": 2.4,
        "body": 4.5,
    }.get(role, 3.4)


def _clamp_segment_bounds(start: float, end: float, *, duration: float | None) -> tuple[float, float]:
    normalized_start = max(0.0, float(start or 0.0))
    normalized_end = max(normalized_start, float(end or normalized_start))
    if duration is not None and duration > 0.0:
        normalized_start = min(normalized_start, float(duration))
        normalized_end = min(max(normalized_start, normalized_end), float(duration))
    return round(normalized_start, 3), round(normalized_end, 3)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_text(value: Any) -> str:
    return _text(value).lower().replace(" ", "")


def _string_list(value: Any, *, limit: int) -> list[str]:
    if isinstance(value, list):
        items = [_text(item) for item in value]
    else:
        text = _text(value)
        items = [text] if text else []
    deduped: list[str] = []
    for item in items:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:limit]


def _dict_list(value: Any, *, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, Mapping):
            items.append(dict(item))
        if len(items) >= limit:
            break
    return items


def _float_value(value: Any) -> float:
    try:
        parsed = float(value or 0.0)
    except (TypeError, ValueError):
        parsed = 0.0
    return max(0.0, min(parsed, 1.0))


def _coerce_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
