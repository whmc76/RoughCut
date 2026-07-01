from __future__ import annotations

import hashlib
import re
from typing import Any

SMART_DIRECTOR_ARTIFACT_TYPES = {
    "director_brief": "smart_director_brief.v1",
    "script_plan": "smart_director_script_plan.v1",
    "storyboard_plan": "smart_director_storyboard_plan.v1",
    "asset_plan": "smart_director_asset_plan.v1",
    "asset_generation": "smart_director_asset_generation.v1",
    "voiceover_plan": "smart_director_voiceover_plan.v1",
    "music_plan": "smart_director_music_plan.v1",
    "compose_plan": "smart_director_compose_plan.v1",
    "director_review": "smart_director_review.v1",
}

SMART_DIRECTOR_DEFAULT_DURATION_SEC = 60


def build_smart_director_brief(
    *,
    job_id: str,
    source_name: str,
    source_context: dict[str, Any] | None,
    task_brief: str | None,
    video_description: str | None,
    language: str,
    platform_targets: list[str] | None = None,
) -> dict[str, Any]:
    raw_brief = _first_text(
        task_brief,
        video_description,
        _dict_text(source_context, "video_description"),
        _dict_text(source_context, "task_brief"),
        source_name,
    )
    duration_sec = _infer_duration_sec(raw_brief)
    aspect_ratio = _infer_aspect_ratio(raw_brief, platform_targets or [])
    scenes = _infer_scene_count(duration_sec)
    source_context = dict(source_context or {})
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["director_brief"],
        "job_id": job_id,
        "mode": "smart_director",
        "source_kind": "prompt_only" if source_context.get("source_kind") == "prompt_only" else "mixed_sources",
        "raw_brief": raw_brief,
        "language": language or "zh-CN",
        "target": {
            "duration_sec": duration_sec,
            "scene_count": scenes,
            "aspect_ratio": aspect_ratio,
            "platform_targets": list(platform_targets or []),
        },
        "creative_constraints": {
            "tone": _infer_tone(raw_brief),
            "audience": _infer_audience(raw_brief),
            "must_include": _infer_keywords(raw_brief, limit=8),
            "avoid": [],
        },
        "source_context": source_context,
    }


def build_smart_director_script_plan(brief: dict[str, Any]) -> dict[str, Any]:
    target = dict(brief.get("target") or {})
    duration_sec = _positive_int(target.get("duration_sec"), SMART_DIRECTOR_DEFAULT_DURATION_SEC)
    scene_count = _positive_int(target.get("scene_count"), _infer_scene_count(duration_sec))
    raw_brief = _first_text(brief.get("raw_brief"), "Smart Director video")
    beats = _split_into_beats(raw_brief, scene_count)
    scenes: list[dict[str, Any]] = []
    for index, beat in enumerate(beats):
        start_sec, end_sec = _scene_range(index, len(beats), duration_sec)
        scenes.append(
            {
                "scene_id": f"S{index + 1:02d}",
                "start_sec": start_sec,
                "end_sec": end_sec,
                "purpose": _scene_purpose(index, len(beats)),
                "narration": _narration_for_beat(beat, index, len(beats)),
                "onscreen_text": _onscreen_text_for_beat(beat, index, len(beats)),
            }
        )
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["script_plan"],
        "brief_schema": brief.get("schema"),
        "title": _title_from_brief(raw_brief),
        "logline": raw_brief[:180],
        "language": brief.get("language") or "zh-CN",
        "duration_sec": duration_sec,
        "scenes": scenes,
    }


def build_smart_director_storyboard_plan(script_plan: dict[str, Any]) -> dict[str, Any]:
    scenes = []
    for scene in list(script_plan.get("scenes") or []):
        narration = _first_text(scene.get("narration"), scene.get("onscreen_text"), script_plan.get("logline"))
        scenes.append(
            {
                "scene_id": scene.get("scene_id"),
                "time_range": [scene.get("start_sec", 0), scene.get("end_sec", 0)],
                "visual_prompt": f"High quality product/video scene, {narration}",
                "shot_type": _shot_type_for_scene(str(scene.get("purpose") or "")),
                "camera_motion": _camera_motion_for_scene(str(scene.get("purpose") or "")),
                "caption": scene.get("onscreen_text") or "",
            }
        )
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["storyboard_plan"],
        "script_schema": script_plan.get("schema"),
        "scenes": scenes,
    }


def build_smart_director_asset_plan(storyboard_plan: dict[str, Any]) -> dict[str, Any]:
    assets = []
    for scene in list(storyboard_plan.get("scenes") or []):
        scene_id = str(scene.get("scene_id") or "")
        assets.append(
            {
                "asset_id": f"{scene_id}_visual",
                "scene_id": scene_id,
                "type": "visual",
                "strategy": "generate_or_stock",
                "prompt": scene.get("visual_prompt") or "",
                "required": True,
            }
        )
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["asset_plan"],
        "storyboard_schema": storyboard_plan.get("schema"),
        "assets": assets,
        "retrieval": {
            "stock_footage_enabled": True,
            "local_material_first": True,
            "license_check_required": True,
        },
        "cost_budget": {
            "currency": "USD",
            "estimated_total": 0,
            "hard_limit_required_before_paid_generation": True,
        },
    }


def build_smart_director_voiceover_plan(script_plan: dict[str, Any]) -> dict[str, Any]:
    lines = [
        {
            "scene_id": scene.get("scene_id"),
            "start_sec": scene.get("start_sec", 0),
            "end_sec": scene.get("end_sec", 0),
            "text": scene.get("narration") or "",
        }
        for scene in list(script_plan.get("scenes") or [])
    ]
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["voiceover_plan"],
        "script_schema": script_plan.get("schema"),
        "voice": {
            "language": script_plan.get("language") or "zh-CN",
            "style": "clear_director_narration",
            "pace": "medium",
        },
        "lines": lines,
    }


def build_smart_director_music_plan(script_plan: dict[str, Any]) -> dict[str, Any]:
    duration_sec = _positive_int(script_plan.get("duration_sec"), SMART_DIRECTOR_DEFAULT_DURATION_SEC)
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["music_plan"],
        "script_schema": script_plan.get("schema"),
        "duration_sec": duration_sec,
        "mood": _infer_tone(str(script_plan.get("logline") or "")),
        "cues": [
            {"start_sec": 0, "end_sec": min(duration_sec, 8), "role": "hook"},
            {"start_sec": min(duration_sec, 8), "end_sec": max(8, duration_sec - 8), "role": "body"},
            {"start_sec": max(0, duration_sec - 8), "end_sec": duration_sec, "role": "finish"},
        ],
        "mix": {"voice_ducking": True, "target_lufs": -16},
    }


def build_smart_director_compose_plan(
    *,
    script_plan: dict[str, Any],
    storyboard_plan: dict[str, Any],
    asset_plan: dict[str, Any],
    voiceover_plan: dict[str, Any],
    music_plan: dict[str, Any],
    asset_generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    storyboard_by_scene = {item.get("scene_id"): item for item in list(storyboard_plan.get("scenes") or [])}
    generated_by_asset_id = {
        item.get("asset_id"): item
        for item in list((asset_generation or {}).get("generated_assets") or [])
        if isinstance(item, dict)
    }
    timeline = []
    for scene in list(script_plan.get("scenes") or []):
        scene_id = scene.get("scene_id")
        visual_asset_id = f"{scene_id}_visual"
        board = storyboard_by_scene.get(scene_id) or {}
        generated = generated_by_asset_id.get(visual_asset_id) or {}
        image = generated.get("image") if isinstance(generated.get("image"), dict) else {}
        video = generated.get("video") if isinstance(generated.get("video"), dict) else {}
        timeline.append(
            {
                "scene_id": scene_id,
                "start_sec": scene.get("start_sec", 0),
                "end_sec": scene.get("end_sec", 0),
                "visual_asset_id": visual_asset_id,
                "generated_image_path": image.get("output_path"),
                "generated_video_path": video.get("output_path"),
                "caption": board.get("caption") or scene.get("onscreen_text") or "",
                "transition": "cut" if len(timeline) == 0 else "soft_cut",
            }
        )
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["compose_plan"],
        "script_schema": script_plan.get("schema"),
        "storyboard_schema": storyboard_plan.get("schema"),
        "asset_schema": asset_plan.get("schema"),
        "asset_generation_schema": (asset_generation or {}).get("schema"),
        "voiceover_schema": voiceover_plan.get("schema"),
        "music_schema": music_plan.get("schema"),
        "timeline": timeline,
        "delivery": {
            "renderer": "hyperframes",
            "output_profiles": ["mp4_preview", "mp4_delivery"],
            "requires_asset_materialization": True,
        },
    }


def build_smart_director_review(
    compose_plan: dict[str, Any],
    asset_plan: dict[str, Any],
    asset_generation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    timeline = list(compose_plan.get("timeline") or [])
    assets = list(asset_plan.get("assets") or [])
    missing_assets = [item for item in assets if not str(item.get("asset_id") or "").strip()]
    generation_status = str((asset_generation or {}).get("status") or "").strip()
    materialized_count = sum(
        1
        for item in list((asset_generation or {}).get("generated_assets") or [])
        if isinstance(item, dict) and str(item.get("status") or "") in {"completed", "partial"}
    )
    ready_for_materialization = bool(timeline and assets and not missing_assets)
    ready_for_render = ready_for_materialization and generation_status in {"completed", "partial"} and materialized_count > 0
    status = "render_ready" if ready_for_render else "plan_ready" if ready_for_materialization else "blocked"
    return {
        "schema": SMART_DIRECTOR_ARTIFACT_TYPES["director_review"],
        "compose_schema": compose_plan.get("schema"),
        "asset_generation_schema": (asset_generation or {}).get("schema"),
        "status": status,
        "checks": {
            "has_timeline": bool(timeline),
            "has_assets": bool(assets),
            "missing_asset_count": len(missing_assets),
            "ready_for_materialization": ready_for_materialization,
            "asset_generation_status": generation_status,
            "materialized_asset_count": materialized_count,
            "ready_for_render": ready_for_render,
        },
        "next_stage": "asset_materialization_and_render",
    }


def smart_director_artifact_fingerprint(payload: dict[str, Any]) -> str:
    text = repr(_stable_object(payload)).encode("utf-8", errors="ignore")
    return hashlib.sha256(text).hexdigest()


def _stable_object(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable_object(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_stable_object(item) for item in value]
    return value


def _dict_text(payload: dict[str, Any] | None, key: str) -> str:
    if not isinstance(payload, dict):
        return ""
    value = payload.get(key)
    return str(value or "").strip()


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return "Smart Director video"


def _positive_int(value: Any, fallback: int) -> int:
    try:
        parsed = int(float(str(value)))
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _infer_duration_sec(text: str) -> int:
    normalized = str(text or "")
    match = re.search(r"(\d{1,3})\s*(?:s|sec|second|seconds|秒)", normalized, flags=re.IGNORECASE)
    if match:
        return min(600, max(10, int(match.group(1))))
    match = re.search(r"(\d{1,2})\s*(?:min|minute|minutes|分钟)", normalized, flags=re.IGNORECASE)
    if match:
        return min(600, max(10, int(match.group(1)) * 60))
    return SMART_DIRECTOR_DEFAULT_DURATION_SEC


def _infer_scene_count(duration_sec: int) -> int:
    return min(8, max(3, round(duration_sec / 15)))


def _infer_aspect_ratio(text: str, platform_targets: list[str]) -> str:
    normalized = f"{text} {' '.join(platform_targets)}".lower()
    if any(token in normalized for token in ("9:16", "竖屏", "vertical", "tiktok", "douyin", "shorts")):
        return "9:16"
    if any(token in normalized for token in ("1:1", "square", "方形")):
        return "1:1"
    return "16:9"


def _infer_tone(text: str) -> str:
    normalized = str(text or "").lower()
    if any(token in normalized for token in ("科技", "tech", "future", "ai")):
        return "modern_tech"
    if any(token in normalized for token in ("温暖", "warm", "family")):
        return "warm"
    if any(token in normalized for token in ("高端", "premium", "luxury")):
        return "premium"
    return "clear_commercial"


def _infer_audience(text: str) -> str:
    normalized = str(text or "").lower()
    if any(token in normalized for token in ("开发者", "developer", "engineer")):
        return "technical_audience"
    if any(token in normalized for token in ("家长", "parent", "家庭")):
        return "family_audience"
    if any(token in normalized for token in ("老板", "企业", "business", "b2b")):
        return "business_audience"
    return "general_audience"


def _infer_keywords(text: str, *, limit: int) -> list[str]:
    tokens = re.findall(r"[\w\u4e00-\u9fff]{2,}", str(text or ""))
    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        normalized = token.strip()
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _split_into_beats(text: str, scene_count: int) -> list[str]:
    parts = [part.strip() for part in re.split(r"[。！？!?\n；;]+", str(text or "")) if part.strip()]
    if not parts:
        parts = [str(text or "Smart Director video").strip()]
    while len(parts) < scene_count:
        parts.append(parts[-1])
    return parts[:scene_count]


def _scene_range(index: int, count: int, duration_sec: int) -> tuple[int, int]:
    start = round(index * duration_sec / max(1, count))
    end = round((index + 1) * duration_sec / max(1, count))
    return start, max(start + 1, end)


def _scene_purpose(index: int, count: int) -> str:
    if index == 0:
        return "hook"
    if index == count - 1:
        return "call_to_action"
    return "proof_point"


def _narration_for_beat(beat: str, index: int, count: int) -> str:
    beat = beat.strip()
    if index == 0:
        return f"Start with the core hook: {beat}"
    if index == count - 1:
        return f"Close with a clear reason to act: {beat}"
    return f"Develop the proof point: {beat}"


def _onscreen_text_for_beat(beat: str, index: int, count: int) -> str:
    keywords = _infer_keywords(beat, limit=4)
    if keywords:
        return " / ".join(keywords)
    if index == 0:
        return "Key hook"
    if index == count - 1:
        return "Take action"
    return "Proof point"


def _title_from_brief(text: str) -> str:
    clean = re.sub(r"\s+", " ", str(text or "")).strip()
    return clean[:36] or "Smart Director Video"


def _shot_type_for_scene(purpose: str) -> str:
    if purpose == "hook":
        return "hero_closeup"
    if purpose == "call_to_action":
        return "clean_packshot"
    return "contextual_medium_shot"


def _camera_motion_for_scene(purpose: str) -> str:
    if purpose == "hook":
        return "slow_push_in"
    if purpose == "call_to_action":
        return "stable_hold"
    return "gentle_parallax"
