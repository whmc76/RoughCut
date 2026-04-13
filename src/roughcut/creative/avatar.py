from __future__ import annotations

from typing import Any

from roughcut.config import get_settings
from roughcut.providers.factory import get_avatar_provider
from roughcut.review.content_profile import apply_source_identity_constraints, extract_source_identity_constraints


def avatar_mode_enabled(enhancement_modes: list[str] | tuple[str, ...] | None) -> bool:
    return "avatar_commentary" in set(enhancement_modes or [])


def build_avatar_commentary_plan(
    *,
    job_id: str,
    source_name: str,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
    ai_director_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    effective_content_profile = apply_source_identity_constraints(
        content_profile or {},
        source_name=source_name,
    )
    identity_constraints = extract_source_identity_constraints(
        effective_content_profile,
        source_name=source_name,
    )
    mode = "full_track_audio_passthrough"
    plan = {
        "mode": mode,
        "provider": settings.avatar_provider,
        "voice_provider": settings.voice_provider,
        "source_name": source_name,
        "presenter_id": settings.avatar_presenter_id,
        "layout_template": settings.avatar_layout_template,
        "safe_margin": settings.avatar_safe_margin,
        "overlay_scale": settings.avatar_overlay_scale,
        "segments": [],
        "design_rules": [
            "默认优先生成与成片等长的数字人口播画中画，保证讲解不断档。",
            "主画面保持原视频剪辑结果，数字人只作为辅助解说窗口存在。",
            "数字人窗口默认避开字幕安全区，具体位置以当前包装配置为准。",
            "代表性片段抽样模式仅作为可选快速模式，不再作为默认交付策略。",
        ],
        "content_identity": identity_constraints,
    }
    if identity_constraints:
        plan["design_rules"].append("文件名/任务说明提取出的品牌、型号和主题属于强约束，数字人口播不得改成其他产品。")
    plan["render_request"] = get_avatar_provider().build_render_request(job_id=job_id, plan=plan)
    return plan


def refine_avatar_commentary_segments_for_media_duration(
    segments: list[dict[str, Any]],
    subtitle_items: list[dict[str, Any]],
    *,
    media_duration_sec: float,
) -> list[dict[str, Any]]:
    max_end_time = max(0.0, float(media_duration_sec or 0.0) - 0.05)
    if max_end_time <= 0.0:
        return []

    adjusted_segments: list[dict[str, Any]] = []
    for segment in segments:
        start = max(0.0, float(segment.get("start_time") or 0.0))
        end = min(max_end_time, float(segment.get("end_time") or start))
        if end <= start:
            continue
        duration = round(end - start, 3)
        if duration < 1.05:
            continue
        adjusted_segments.append(
            {
                **segment,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "duration_sec": duration,
            }
        )

    bounded_subtitles = [
        item
        for item in _normalize_subtitle_items(subtitle_items)
        if float(item.get("start_time") or 0.0) < max_end_time
    ]
    rebuilt_candidates = _build_passthrough_avatar_segments(bounded_subtitles)
    rebuilt_segments = _select_avatar_commentary_segments(rebuilt_candidates)
    if rebuilt_segments:
        return rebuilt_segments
    return adjusted_segments


def _build_passthrough_avatar_segments(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_items = _normalize_subtitle_items(subtitle_items)
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    max_duration = 7.5
    max_chars = 52
    max_gap = 0.45

    for item in normalized_items:
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        start = float(item.get("start_time") or 0.0)
        end = float(item.get("end_time") or start)
        if end - start < 0.45:
            continue
        normalized = {
            "text": text,
            "start_time": start,
            "end_time": end,
        }
        if not current:
            current = [normalized]
            continue

        combined_start = float(current[0]["start_time"])
        combined_end = end
        combined_text = "".join(str(part["text"]) for part in current) + text
        gap = start - float(current[-1]["end_time"])
        if gap <= max_gap and (combined_end - combined_start) <= max_duration and len(combined_text) <= max_chars:
            current.append(normalized)
        else:
            groups.append(current)
            current = [normalized]

    if current:
        groups.append(current)

    segments: list[dict[str, Any]] = []
    for index, group in enumerate(groups, start=1):
        start = float(group[0]["start_time"])
        end = float(group[-1]["end_time"])
        text = "".join(str(item["text"]) for item in group)
        duration = round(max(0.6, end - start), 3)
        segments.append(
            {
                "segment_id": f"avatar_seg_{index:03d}",
                "script": text,
                "purpose": "commentary",
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "duration_sec": duration,
            }
        )
    return segments


def _normalize_subtitle_items(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized_items: list[dict[str, Any]] = []
    offset = 0.0
    last_raw_start: float | None = None
    last_normalized_end = 0.0

    for item in subtitle_items:
        text = str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()
        if not text:
            continue
        try:
            raw_start = float(item.get("start_time") or 0.0)
        except (TypeError, ValueError):
            raw_start = 0.0
        try:
            raw_end = float(item.get("end_time") or raw_start)
        except (TypeError, ValueError):
            raw_end = raw_start
        if raw_end <= 0.0 and raw_start <= 0.0:
            continue
        if last_raw_start is not None and raw_start + 0.25 < last_raw_start:
            offset = max(offset, last_normalized_end - raw_start + 0.2)
        start = raw_start + offset
        end = raw_end + offset
        if end <= start:
            end = start + 0.6
        if start + 0.15 < last_normalized_end:
            delta = last_normalized_end - start + 0.1
            start += delta
            end += delta
        normalized_items.append(
            {
                **item,
                "text_final": text,
                "start_time": round(start, 3),
                "end_time": round(end, 3),
            }
        )
        last_raw_start = raw_start
        last_normalized_end = end
    return normalized_items


def _select_avatar_commentary_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not segments:
        return []
    eligible_segments = [
        dict(segment)
        for segment in segments
        if float(segment.get("duration_sec") or 0.0) >= 1.05
    ]
    if not eligible_segments:
        return []
    timeline_end = max(float(segment.get("end_time") or 0.0) for segment in eligible_segments)
    if timeline_end <= 120.0:
        max_segments = 2
        max_total_duration = 12.0
    elif timeline_end <= 300.0:
        max_segments = 3
        max_total_duration = 16.0
    elif timeline_end <= 900.0:
        max_segments = 4
        max_total_duration = 22.0
    else:
        max_segments = 5
        max_total_duration = 28.0

    bucket_size = max(1.0, timeline_end / float(max_segments))
    selected: list[dict[str, Any]] = []
    used_ids: set[str] = set()

    for bucket_index in range(max_segments):
        bucket_start = bucket_index * bucket_size
        bucket_end = timeline_end + 0.001 if bucket_index == max_segments - 1 else (bucket_index + 1) * bucket_size
        bucket_candidates = [
            segment
            for segment in eligible_segments
            if bucket_start <= float(segment.get("start_time") or 0.0) < bucket_end
        ]
        if not bucket_candidates:
            continue
        best = max(
            bucket_candidates,
            key=lambda segment: (
                min(float(segment.get("duration_sec") or 0.0), 6.0),
                min(len(str(segment.get("script") or "")), 42),
            ),
        )
        segment_id = str(best.get("segment_id") or "")
        if segment_id and segment_id not in used_ids:
            selected.append(dict(best))
            used_ids.add(segment_id)

    if len(selected) < max_segments:
        for segment in eligible_segments:
            segment_id = str(segment.get("segment_id") or "")
            if segment_id and segment_id in used_ids:
                continue
            selected.append(dict(segment))
            if segment_id:
                used_ids.add(segment_id)
            if len(selected) >= max_segments:
                break

    selected.sort(key=lambda segment: float(segment.get("start_time") or 0.0))

    trimmed: list[dict[str, Any]] = []
    total_duration = 0.0
    for segment in selected:
        duration = float(segment.get("duration_sec") or 0.0)
        if duration <= 0.0:
            continue
        if trimmed and total_duration + duration > max_total_duration:
            break
        trimmed.append(segment)
        total_duration += duration
    return trimmed
