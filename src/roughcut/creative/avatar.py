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
    plan = {
        "mode": "full_track_audio_passthrough",
        "provider": settings.avatar_provider,
        "source_name": source_name,
        "presenter_id": settings.avatar_presenter_id,
        "layout_template": settings.avatar_layout_template,
        "safe_margin": settings.avatar_safe_margin,
        "overlay_scale": settings.avatar_overlay_scale,
        "segments": [],
        "design_rules": [
            "默认使用粗剪后的整轨原声驱动数字人，全程生成画中画口播。",
            "主画面保持原视频剪辑结果，数字人只作为辅助解说窗口存在。",
            "数字人窗口默认避开字幕安全区，优先落在右下角。",
        ],
    }
    plan["render_request"] = get_avatar_provider().build_render_request(job_id=job_id, plan=plan)
    return plan
