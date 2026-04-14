from __future__ import annotations

from typing import Any

from roughcut.config import get_settings
from roughcut.providers.factory import get_reasoning_provider, get_voice_provider
from roughcut.providers.reasoning.base import Message
from roughcut.review.content_profile import apply_source_identity_constraints, extract_source_identity_constraints
from roughcut.review.content_profile_memory import merge_content_profile_creative_preferences
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
    effective_content_profile = apply_source_identity_constraints(
        content_profile or {},
        source_name=source_name,
    )
    heuristic = _build_heuristic_director_plan(
        source_name=source_name,
        subtitle_items=subtitle_items,
        content_profile=effective_content_profile,
    )
    identity_constraints = extract_source_identity_constraints(
        effective_content_profile,
        source_name=source_name,
    )

    try:
        provider = get_reasoning_provider()
        constraint_lines: list[str] = []
        if identity_constraints:
            for field_name, label in (
                ("subject_brand", "品牌"),
                ("subject_model", "型号"),
                ("subject_type", "主体类型"),
                ("video_theme", "视频主题"),
            ):
                value = str(identity_constraints.get(field_name) or "").strip()
                if value:
                    constraint_lines.append(f"{label}：{value}")
            filename_entries = list(identity_constraints.get("filename_entries") or [])
            if filename_entries:
                constraint_lines.append(f"来源文件名：{filename_entries}")
            video_description = str(identity_constraints.get("video_description") or "").strip()
            if video_description:
                constraint_lines.append(f"任务说明：{video_description}")
        constraint_section = f"\n强约束：{constraint_lines}" if constraint_lines else ""
        prompt = (
            "你是短视频 AI 导演。请根据字幕和内容画像，输出 JSON，给出："
            "opening_hook、bridge_line、science_boost、closing_prompt、rewrite_strategy、voiceover_segments。"
            "voiceover_segments 最多 4 段，每段包含 purpose/source_text/rewritten_text/suggested_start_time/target_duration_sec/reason。"
            "要求：补逻辑、补信息、补情绪，但不要编造事实；尽量保留说话人口吻。"
            "如果任务说明或文件名已经明确品牌、型号、主体类型、对比关系，这些都是强约束，不得改写成别的产品。"
            f"\n源文件：{source_name}"
            f"\n内容画像：{effective_content_profile or {}}"
            f"{constraint_section}"
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
            "subject": str((effective_content_profile or {}).get("subject_type") or ""),
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
    creative_preferences = merge_content_profile_creative_preferences(content_profile)
    preference_tags = {
        str(item.get("tag") or "").strip()
        for item in creative_preferences
        if str(item.get("tag") or "").strip()
    }
    opening_source = _subtitle_text(subtitle_items, 0)
    middle_source = _subtitle_text(subtitle_items, max(1, len(subtitle_items) // 2 - 1))
    closing_source = _subtitle_text(subtitle_items, max(0, len(subtitle_items) - 1))

    hook = _director_opening_hook(subject, preference_tags=preference_tags)
    bridge = _director_bridge_line(subject, summary=summary, preference_tags=preference_tags)
    science = _director_science_boost(subject, preference_tags=preference_tags)
    closing = question or _director_closing_prompt(subject, preference_tags=preference_tags)

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
        "rewrite_strategy": _director_rewrite_strategy(preference_tags),
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


def _director_opening_hook(subject: str, *, preference_tags: set[str]) -> str:
    if "comparison_focus" in preference_tags:
        return f"这条{subject}别从头猜，我先把最关键的差异和怎么选给你拎出来。"
    if "workflow_breakdown" in preference_tags:
        return f"这条{subject}别急着记步骤，我先把最关键的流程节点给你挑出来。"
    if "conclusion_first" in preference_tags or "fast_paced" in preference_tags:
        return f"这条{subject}先讲结论，最值回票价的重点我先替你拎出来。"
    return f"如果你只看一分钟，这条{subject}最值回票价的点我先给你挑出来。"


def _director_bridge_line(subject: str, *, summary: str, preference_tags: set[str]) -> str:
    if summary:
        if "comparison_focus" in preference_tags and "差异" not in summary and "对比" not in summary:
            return f"{summary} 接下来把关键差异、适合谁和怎么选拆开说。"
        if "workflow_breakdown" in preference_tags and "流程" not in summary and "步骤" not in summary:
            return f"{summary} 接下来把关键步骤和每一步为什么这样安排讲清楚。"
        return summary
    if "workflow_breakdown" in preference_tags:
        return f"接下来别只记{subject}表面流程，更关键的是把节点顺序和判断逻辑拆清楚。"
    if "comparison_focus" in preference_tags:
        return f"接下来别只看热闹，更关键的是把这条{subject}的差异、取舍和判断依据说透。"
    return f"接下来别只看表面流程，更关键的是它背后的逻辑为什么成立。"


def _director_science_boost(subject: str, *, preference_tags: set[str]) -> str:
    focus_parts: list[str] = []
    if "comparison_focus" in preference_tags:
        focus_parts.append("核心差异、适用人群和取舍逻辑")
    if "workflow_breakdown" in preference_tags:
        focus_parts.append("关键步骤为什么这样接、哪里最容易踩坑")
    if "detail_focus" in preference_tags or "closeup_focus" in preference_tags:
        focus_parts.append("关键细节、做工和近景特写到底该看哪里")
    if "practical_demo" in preference_tags:
        focus_parts.append("真实上手场景里最影响判断的那条标准")
    if focus_parts:
        return f"如果要把这条{subject}讲透，最好顺手补一句" + "，再讲".join(focus_parts) + "。"
    return f"如果要把这条{subject}讲透，最好顺手补一句原理、对比或使用条件。"


def _director_closing_prompt(subject: str, *, preference_tags: set[str]) -> str:
    if "comparison_focus" in preference_tags:
        return f"看到最后，你会更偏这条{subject}里讲到的哪种版本和取舍逻辑？"
    if "workflow_breakdown" in preference_tags:
        return f"看到最后，你觉得这条{subject}里哪个关键步骤最值得单独展开讲？"
    return f"看到最后，你更在意这条{subject}的结论，还是它中间给出的判断依据？"


def _director_rewrite_strategy(preference_tags: set[str]) -> list[str]:
    strategy = [
        "优先增强开头钩子，前 5 秒给出明确观看收益。",
        "中段补逻辑桥和背景解释，减少信息跳跃。",
        "结尾加入互动性收口，形成评论区问题。",
    ]
    if "conclusion_first" in preference_tags or "fast_paced" in preference_tags:
        strategy[0] = "优先把结论和观看收益前置，减少铺垫，前 5 秒直接进重点。"
    if "comparison_focus" in preference_tags:
        strategy[1] = "中段优先拆版本差异、适合人群和选择取舍，不只复述表面信息。"
    elif "workflow_breakdown" in preference_tags:
        strategy[1] = "中段优先把流程拆成关键节点，说明每一步为什么这样做。"
    if "detail_focus" in preference_tags or "closeup_focus" in preference_tags:
        strategy.insert(2, "补写关键细节、做工和近景特写的观看提示，让镜头重点更明确。")
    elif "practical_demo" in preference_tags:
        strategy.insert(2, "补写真实上手和实际使用场景，让判断依据落到体验上。")
    return strategy[:4]
