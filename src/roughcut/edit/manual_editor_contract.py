from __future__ import annotations

from typing import Any


def manual_editor_change_contract(change_plan: dict[str, Any] | None) -> dict[str, Any]:
    plan = change_plan if isinstance(change_plan, dict) else {}
    return {
        "change_scope": str(plan.get("change_scope") or "timeline"),
        "render_strategy": str(plan.get("render_strategy") or "full_timeline_render"),
        "timeline_changed": bool(plan.get("timeline_changed")),
        "subtitle_changed": bool(plan.get("subtitle_changed")),
        "video_transform_changed": bool(plan.get("video_transform_changed")),
        "rotation_changed": bool(plan.get("rotation_changed")),
    }


def manual_editor_is_subtitle_only_render(change_contract: dict[str, Any] | None) -> bool:
    contract = manual_editor_change_contract(change_contract)
    return (
        contract["change_scope"] == "subtitle_only"
        and contract["render_strategy"] == "reuse_timeline_effect_plan"
    )


def manual_editor_change_contract_is_consistent(change_contract: dict[str, Any] | None) -> bool:
    contract = manual_editor_change_contract(change_contract)
    change_scope = contract["change_scope"]
    timeline_changed = bool(contract["timeline_changed"])
    subtitle_changed = bool(contract["subtitle_changed"])
    video_transform_changed = bool(contract["video_transform_changed"])
    render_strategy = contract["render_strategy"]

    if change_scope == "timeline":
        return timeline_changed and render_strategy == "full_timeline_render"
    if change_scope == "video_transform":
        return (
            not timeline_changed
            and video_transform_changed
            and render_strategy == "source_orientation_render"
        )
    if change_scope == "subtitle_only":
        return (
            not timeline_changed
            and subtitle_changed
            and not video_transform_changed
            and render_strategy == "reuse_timeline_effect_plan"
        )
    if change_scope == "no_material_change":
        return (
            not timeline_changed
            and not subtitle_changed
            and not video_transform_changed
            and render_strategy == "metadata_refresh_render"
        )
    return False


def manual_editor_rerun_issue_code(change_contract: dict[str, Any] | None) -> str:
    contract = manual_editor_change_contract(change_contract)
    if contract["timeline_changed"]:
        return "manual_timeline_edit"
    if contract["video_transform_changed"]:
        return "manual_video_transform_edit"
    if contract["subtitle_changed"]:
        return "manual_subtitle_edit"
    return "manual_editor_no_material_change"


def manual_editor_rerun_plan(change_contract: dict[str, Any] | None) -> dict[str, Any]:
    contract = manual_editor_change_contract(change_contract)
    if contract["render_strategy"] == "metadata_refresh_render":
        return {
            "rerun_start_step": "platform_package",
            "rerun_steps": ["platform_package"],
        }
    return {
        "rerun_start_step": "render",
        "rerun_steps": ["render", "final_review", "platform_package"],
    }


def manual_editor_apply_detail(change_scope: str) -> str:
    if str(change_scope or "") == "subtitle_only":
        return "手动字幕已保存，已复用原剪辑/特效计划并从 render 重新烧录字幕、生成成片和平台包。"
    if str(change_scope or "") == "no_material_change":
        return "未检测到时间线/字幕/画面方向变化，已保存编辑元数据并仅刷新平台文案。"
    if str(change_scope or "") == "video_transform":
        return "画面方向已保存，已从 render 开始重新生成成片、特效和数字人口播链路。"
    return "手动时间线已保存，已从 render 开始重新生成成片、特效和数字人口播链路。"
