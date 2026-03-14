from __future__ import annotations

from typing import Any

from roughcut.config import get_settings
from roughcut.providers.factory import get_avatar_provider


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
    segments: list[dict[str, Any]] = []
    mode = "full_track_audio_passthrough"
    plan = {
        "mode": mode,
        "provider": settings.avatar_provider,
        "source_name": source_name,
        "presenter_id": settings.avatar_presenter_id,
        "layout_template": settings.avatar_layout_template,
        "safe_margin": settings.avatar_safe_margin,
        "overlay_scale": settings.avatar_overlay_scale,
        "segments": segments,
        "design_rules": [
            "默认优先使用完整原声驱动数字人，保证口播画面连续，不在主路径拆成碎片段。",
            "主画面保持原视频剪辑结果，数字人只作为辅助解说窗口存在。",
            "数字人窗口默认避开字幕安全区，具体位置以当前包装配置为准。",
        ],
    }
    plan["render_request"] = get_avatar_provider().build_render_request(job_id=job_id, plan=plan)
    return plan


def _build_passthrough_avatar_segments(subtitle_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    max_duration = 10.5
    max_chars = 34
    max_gap = 0.35

    for item in subtitle_items:
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
