import asyncio

from roughcut.edit.local_insert_plan import normalize_local_insert_plan, plan_local_insert_slot
from roughcut.edit.packaging_timeline import packaging_timeline_insert_plan


def test_normalize_local_insert_plan_backfills_candidate_assets() -> None:
    plan = normalize_local_insert_plan(
        {
            "asset_id": "insert-a",
            "path": "insert.mp4",
            "original_name": "insert.mp4",
            "insert_target_duration_sec": 1.23456,
            "candidate_asset_ids": ["insert-a"],
        }
    )

    assert plan is not None
    assert plan["insert_target_duration_sec"] == 1.235
    assert plan["candidate_assets"][0]["asset_id"] == "insert-a"
    assert plan["candidate_assets"][0]["path"] == "insert.mp4"


def test_plan_local_insert_slot_without_subtitles_returns_start_fallback_and_strategy() -> None:
    plan = asyncio.run(
        plan_local_insert_slot(
            job_id="job-1",
            insert_plan={
                "asset_id": "insert-a",
                "path": "insert.mp4",
                "candidate_assets": [
                    {
                        "asset_id": "insert-a",
                        "path": "insert.mp4",
                        "original_name": "insert.mp4",
                        "insert_archetype": "generic_broll",
                        "insert_motion_profile": "balanced_hold",
                        "insert_transition_style": "straight_cut",
                        "insert_target_duration_sec": 1.8,
                        "selection_score": 0.3,
                        "selection_reasons": ["fallback"],
                    }
                ],
            },
            subtitle_items=[],
            content_profile={"content_kind": "commentary"},
            allow_llm=False,
        )
    )

    assert plan is not None
    assert plan["insert_after_sec"] == 0.0
    assert plan["timing_summary"]["review_recommended"] is True
    assert plan["insert_strategy_summary"]["selected_asset_id"] == "insert-a"


def test_plan_local_insert_slot_prefers_allowed_action_window_without_llm() -> None:
    plan = asyncio.run(
        plan_local_insert_slot(
            job_id="job-2",
            insert_plan={
                "candidate_assets": [
                    {
                        "asset_id": "insert-demo",
                        "path": "demo.mp4",
                        "original_name": "screen-demo.mp4",
                        "insert_archetype": "demo_step",
                        "insert_motion_profile": "guided_hold",
                        "insert_transition_style": "clean_hold",
                        "insert_target_duration_sec": 2.2,
                        "selection_score": 0.8,
                        "selection_reasons": ["demo"],
                    },
                    {
                        "asset_id": "insert-macro",
                        "path": "macro.mp4",
                        "original_name": "macro-detail.mp4",
                        "insert_archetype": "macro_detail",
                        "insert_motion_profile": "quick_punch",
                        "insert_transition_style": "punch_cut",
                        "insert_target_duration_sec": 1.4,
                        "selection_score": 0.6,
                        "selection_reasons": ["detail"],
                    },
                ]
            },
            subtitle_items=[
                {"start_time": 0.0, "end_time": 4.2, "text_final": "开场"},
                {"start_time": 9.0, "end_time": 10.5, "text_final": "先把这个操作步骤说明一下"},
                {"start_time": 10.8, "end_time": 12.6, "text_final": "然后继续下一步"},
            ],
            content_profile={"content_kind": "tutorial"},
            timeline_analysis={
                "hook_end_sec": 2.0,
                "section_actions": [
                    {
                        "index": 2,
                        "role": "detail",
                        "start_sec": 9.8,
                        "end_sec": 11.4,
                        "action_priority": 1.0,
                        "broll_anchor_sec": 10.3,
                        "packaging_intent": "detail_support",
                        "broll_allowed": True,
                    }
                ],
                "editing_skill": {"key": "tutorial_standard"},
            },
            allow_llm=False,
        )
    )

    assert plan is not None
    assert plan["insert_after_sec"] == 10.5
    assert plan["insert_section_role"] == "detail"
    assert plan["insert_packaging_intent"] == "detail_support"
    assert plan["asset_id"] == "insert-macro"
    assert plan["insert_strategy_summary"]["selected_asset_id"] == "insert-macro"
    assert plan["broll_window"]["start_sec"] == 9.8


def test_packaging_timeline_insert_plan_normalizes_nested_payload() -> None:
    plan = packaging_timeline_insert_plan(
        {
            "packaging_timeline": {
                "packaging": {
                    "insert": {
                        "asset_id": "insert-a",
                        "path": "insert.mp4",
                        "insert_target_duration_sec": 1.23456,
                    }
                }
            }
        }
    )

    assert plan is not None
    assert plan["insert_target_duration_sec"] == 1.235
    assert plan["candidate_assets"][0]["asset_id"] == "insert-a"


def test_plan_local_insert_slot_respects_main_only_material_usage() -> None:
    plan = asyncio.run(
        plan_local_insert_slot(
            job_id="job-3",
            insert_plan={
                "asset_id": "insert-a",
                "path": "insert.mp4",
                "candidate_assets": [
                    {
                        "asset_id": "insert-a",
                        "path": "insert.mp4",
                        "original_name": "insert.mp4",
                        "insert_archetype": "generic_broll",
                        "insert_motion_profile": "balanced_hold",
                        "insert_transition_style": "straight_cut",
                        "insert_target_duration_sec": 1.6,
                        "selection_score": 0.7,
                        "selection_reasons": ["fallback"],
                    }
                ],
            },
            subtitle_items=[
                {"start_time": 8.5, "end_time": 10.0, "text_final": "这里进入细节演示。"},
            ],
            content_profile={
                "content_kind": "tutorial",
                "source_context": {
                    "product_controls": {
                        "edit_mode": "tutorial",
                        "automation_level": "standard",
                        "material_usage": "main_only",
                    }
                },
            },
            timeline_analysis={"hook_end_sec": 2.0, "strategy_type": "step_demonstration"},
            allow_llm=False,
        )
    )

    assert plan is None


def test_plan_local_insert_slot_respects_selected_uploaded_no_silent_auto_apply() -> None:
    plan = asyncio.run(
        plan_local_insert_slot(
            job_id="job-4",
            insert_plan={
                "asset_id": "insert-a",
                "path": "insert.mp4",
                "candidate_assets": [
                    {
                        "asset_id": "insert-a",
                        "path": "insert.mp4",
                        "original_name": "insert.mp4",
                        "insert_archetype": "generic_broll",
                        "insert_motion_profile": "balanced_hold",
                        "insert_transition_style": "straight_cut",
                        "insert_target_duration_sec": 1.6,
                        "selection_score": 0.7,
                        "selection_reasons": ["fallback"],
                    }
                ],
            },
            subtitle_items=[
                {"start_time": 8.5, "end_time": 10.0, "text_final": "这里进入细节演示。"},
            ],
            content_profile={
                "content_kind": "tutorial",
                "source_context": {
                    "product_controls": {
                        "edit_mode": "tutorial",
                        "automation_level": "standard",
                        "material_usage": "selected_uploaded",
                    }
                },
            },
            timeline_analysis={"hook_end_sec": 2.0, "strategy_type": "step_demonstration"},
            allow_llm=False,
        )
    )

    assert plan is None
