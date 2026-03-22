from __future__ import annotations

from typing import Any

from roughcut.config import get_settings
from roughcut.providers.factory import get_reasoning_provider, get_voice_provider
from roughcut.providers.reasoning.base import Message
from roughcut.usage import track_usage_operation


def ai_director_mode_enabled(enhancement_modes: list[str] | tuple[str, ...] | None) -> bool:
    return "ai_director" in set(enhancement_modes or [])


async def build_ai_director_plan(
    *,
    job_id: str,
    source_name: str,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any] | None,
) -> dict[str, Any]:
    heuristic = _build_heuristic_director_plan(
        source_name=source_name,
        subtitle_items=subtitle_items,
        content_profile=content_profile or {},
    )

    try:
        provider = get_reasoning_provider()
        prompt = (
            "你是短视频 AI 导演。请根据字幕和内容画像，输出 JSON，给出："
            "opening_hook、bridge_line、science_boost、closing_prompt、rewrite_strategy、voiceover_segments。"
            "voiceover_segments 最多 4 段，每段包含 purpose/source_text/rewritten_text/suggested_start_time/target_duration_sec/reason。"
            "要求：补逻辑、补信息、补情绪，但不要编造事实；尽量保留说话人口吻。"
            f"\n源文件：{source_name}"
            f"\n内容画像：{content_profile or {}}"
            f"\n字幕：{subtitle_items[:14]}"
            f"\n当前启发式草案：{heuristic}"
        )
        with track_usage_operation("ai_director.plan"):
            response = await provider.complete(
                [
                    Message(role="system", content="你是严谨的中文短视频导演和重配音策划。"),
                    Message(role="user", content=prompt),
                ],
                temperature=0.25,
                max_tokens=1200,
                json_mode=True,
            )
        llm_payload = response.as_json()
        if isinstance(llm_payload, dict):
            heuristic.update({key: value for key, value in llm_payload.items() if value})
    except Exception:
        pass

    voice_segments = list(heuristic.get("voiceover_segments") or [])
    heuristic["voice_provider"] = get_settings().voice_provider
    heuristic["dubbing_request"] = get_voice_provider().build_dubbing_request(
        job_id=job_id,
        segments=voice_segments,
        metadata={
            "source_name": source_name,
            "rewrite_strength": get_settings().director_rewrite_strength,
            "subject": str((content_profile or {}).get("subject_type") or ""),
        },
    )
    return heuristic


def _build_heuristic_director_plan(
    *,
    source_name: str,
    subtitle_items: list[dict[str, Any]],
    content_profile: dict[str, Any],
) -> dict[str, Any]:
    subject = str(content_profile.get("subject_type") or content_profile.get("subject_model") or "这条内容").strip()
    summary = str(content_profile.get("summary") or content_profile.get("video_theme") or "").strip()
    question = str(content_profile.get("engagement_question") or "").strip()
    opening_source = _subtitle_text(subtitle_items, 0)
    middle_source = _subtitle_text(subtitle_items, max(1, len(subtitle_items) // 2 - 1))
    closing_source = _subtitle_text(subtitle_items, max(0, len(subtitle_items) - 1))

    hook = f"如果你只看一分钟，这条{subject}最值回票价的点我先给你挑出来。"
    bridge = summary or "接下来别只看表面流程，更关键的是它背后的逻辑为什么成立。"
    science = f"如果要把这条{subject}讲透，最好顺手补一句原理、对比或使用条件。"
    closing = question or f"看到最后，你更在意这条{subject}的结论，还是它中间给出的判断依据？"

    voiceover_segments = [
        {
            "segment_id": "director_hook",
            "purpose": "hook",
            "source_text": opening_source,
            "rewritten_text": hook,
            "suggested_start_time": 0.0,
            "target_duration_sec": 3.8,
            "reason": "开头钩子偏弱，需要更直接地建立观看理由。",
        },
        {
            "segment_id": "director_bridge",
            "purpose": "bridge",
            "source_text": middle_source,
            "rewritten_text": bridge,
            "suggested_start_time": round(max(_midpoint_time(subtitle_items) - 1.0, 5.0), 3),
            "target_duration_sec": 4.4,
            "reason": "中段补足逻辑桥，避免信息跳跃。",
        },
        {
            "segment_id": "director_science",
            "purpose": "science_boost",
            "source_text": middle_source,
            "rewritten_text": science,
            "suggested_start_time": round(max(_midpoint_time(subtitle_items) + 2.6, 8.0), 3),
            "target_duration_sec": 4.2,
            "reason": "补充科普或判断框架，提升信息密度。",
        },
        {
            "segment_id": "director_closing",
            "purpose": "closing",
            "source_text": closing_source,
            "rewritten_text": closing,
            "suggested_start_time": round(max(_end_time(subtitle_items) - 4.5, 10.0), 3),
            "target_duration_sec": 3.4,
            "reason": "结尾增加收口与互动，避免轻飘结束。",
        },
    ]
    return {
        "source_name": source_name,
        "opening_hook": hook,
        "bridge_line": bridge,
        "science_boost": science,
        "closing_prompt": closing,
        "rewrite_strategy": [
            "优先增强开头钩子，前 5 秒给出明确观看收益。",
            "中段补逻辑桥和背景解释，减少信息跳跃。",
            "结尾加入互动性收口，形成评论区问题。",
        ],
        "voiceover_segments": voiceover_segments,
    }


def _subtitle_text(subtitle_items: list[dict[str, Any]], index: int) -> str:
    if not subtitle_items:
        return ""
    safe_index = max(0, min(index, len(subtitle_items) - 1))
    item = subtitle_items[safe_index]
    return str(item.get("text_final") or item.get("text_norm") or item.get("text_raw") or "").strip()


def _midpoint_time(subtitle_items: list[dict[str, Any]]) -> float:
    if not subtitle_items:
        return 10.0
    safe_index = len(subtitle_items) // 2
    return float(subtitle_items[safe_index].get("start_time", 10.0) or 10.0)


def _end_time(subtitle_items: list[dict[str, Any]]) -> float:
    if not subtitle_items:
        return 20.0
    return float(subtitle_items[-1].get("end_time", 20.0) or 20.0)
