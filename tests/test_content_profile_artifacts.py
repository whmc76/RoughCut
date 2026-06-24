from types import SimpleNamespace

from roughcut.review.content_profile_artifacts import (
    ARTIFACT_TYPE_STRATEGY_REVIEW_GATES,
    ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW,
    ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW,
    build_content_profile_artifact_payloads,
    build_strategy_review_gates_artifact_payload,
    build_strategy_storyboard_review_artifact_payload,
    build_strategy_timeline_preview_artifact_payload,
)
from roughcut.review.content_profile_strategy import attach_content_profile_capability_orchestration
from roughcut.edit.strategy_review_gates import build_strategy_review_gate_confirmations_payload


def test_content_profile_artifact_payloads_include_video_understanding() -> None:
    payloads = build_content_profile_artifact_payloads(
        draft_profile={
            "summary": "这期围绕 NITECORE EDC17 展开。",
            "video_understanding": {
                "schema_version": "video_understanding_v1",
                "global_understanding": {"video_theme": "NITECORE EDC17 开箱"},
            },
        },
        final_profile=None,
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
    )

    assert payloads.video_understanding == {
        "schema_version": "video_understanding_v1",
        "global_understanding": {"video_theme": "NITECORE EDC17 开箱"},
    }


def test_strategy_review_gates_artifact_payload_uses_capability_orchestration() -> None:
    profile = {
        "capability_orchestration": {
            "strategy_type": "narrative_assembly",
            "classification": {
                "primary_type": "avatar_commentary_remix",
                "production_mode": "remix",
            },
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "production_mode": "remix",
                "primary_type": "avatar_commentary_remix",
                "review_gates": [
                    "strategy_confirmation_required",
                    "storyboard_review_required",
                    "timeline_preview_required",
                ],
            },
        }
    }

    artifact = build_strategy_review_gates_artifact_payload(profile)

    assert artifact is not None
    assert artifact["artifact_type"] == ARTIFACT_TYPE_STRATEGY_REVIEW_GATES
    assert artifact["strategy_type"] == "narrative_assembly"
    assert artifact["classification"]["primary_type"] == "avatar_commentary_remix"
    assert artifact["review_gate_status"]["blocking"] is True
    assert set(artifact["review_gate_status"]["blocking_gate_ids"]) == {
        "strategy_confirmation",
        "storyboard_review",
        "timeline_preview",
    }


def test_content_profile_artifact_payloads_include_strategy_review_gates_from_final_profile() -> None:
    payloads = build_content_profile_artifact_payloads(
        draft_profile={"summary": "draft"},
        final_profile={
            "summary": "final",
            "capability_orchestration": {
                "strategy_type": "narrative_assembly",
                "pipeline_plan": {
                    "strategy_type": "narrative_assembly",
                    "review_gates": ["storyboard_review_required"],
                },
                "review_gate_status": {
                    "schema": "strategy_review_gates.v1",
                    "strategy_type": "narrative_assembly",
                    "gates": [
                        {
                            "gate_id": "storyboard_review",
                            "source_key": "storyboard_review_required",
                            "requirement": "required",
                            "status": "pending",
                            "blocking": True,
                        }
                    ],
                    "blocking": True,
                    "blocking_gate_ids": ["storyboard_review"],
                },
            },
        },
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
    )

    assert payloads.strategy_review_gates is not None
    assert payloads.strategy_review_gates["strategy_type"] == "narrative_assembly"
    assert payloads.strategy_review_gates["review_gate_status"]["blocking_gate_ids"] == ["storyboard_review"]


def test_strategy_storyboard_and_timeline_preview_artifacts_follow_required_gates() -> None:
    profile = {
        "video_theme": "数字人讲解热点事件",
        "hook_line": "先看这段争议的关键转折",
        "content_understanding": {
            "timed_focus_spans": [
                {
                    "timestamp": "00:00-00:04",
                    "text": "开场抛出核心冲突",
                    "type": "hook",
                    "start_time": 0.0,
                    "end_time": 4.0,
                },
                {
                    "timestamp": "00:04-00:12",
                    "text": "插入原始素材解释背景",
                    "type": "material_insert",
                    "start_time": 4.0,
                    "end_time": 12.0,
                },
            ]
        },
        "capability_orchestration": {
            "strategy_type": "narrative_assembly",
            "classification": {
                "primary_type": "avatar_commentary_remix",
                "production_mode": "remix",
            },
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "production_mode": "remix",
                "primary_type": "avatar_commentary_remix",
                "enabled_features": ["storyboard_review", "timeline_preview", "material_insert_plan"],
                "review_gates": [
                    "storyboard_review_required",
                    "timeline_preview_required",
                ],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_storyboard_alignment": True,
                        "check_timeline_preview_alignment": True,
                    }
                },
            },
        },
    }

    gates = build_strategy_review_gates_artifact_payload(profile)
    storyboard = build_strategy_storyboard_review_artifact_payload(profile)
    timeline = build_strategy_timeline_preview_artifact_payload(profile)
    payloads = build_content_profile_artifact_payloads(
        draft_profile={"summary": "draft"},
        final_profile=profile,
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
    )

    assert gates is not None
    assert gates["gate_artifacts"]["storyboard_review"]["artifact_type"] == ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW
    assert gates["gate_artifacts"]["timeline_preview"]["artifact_type"] == ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW
    assert storyboard is not None
    assert storyboard["artifact_type"] == ARTIFACT_TYPE_STRATEGY_STORYBOARD_REVIEW
    assert storyboard["panels"][0]["panel_id"] == "opening_hook"
    assert timeline is not None
    assert timeline["artifact_type"] == ARTIFACT_TYPE_STRATEGY_TIMELINE_PREVIEW
    assert timeline["segments"][0]["timestamp"] == "00:00-00:04"
    assert payloads.strategy_storyboard_review is not None
    assert payloads.strategy_timeline_preview is not None
    strategy_context = payloads.downstream_context["resolved_profile"]["strategy_review_context"]
    assert strategy_context["strategy_storyboard_review"]["panels"][0]["panel_id"] == "opening_hook"
    assert strategy_context["strategy_timeline_preview"]["segments"][0]["timestamp"] == "00:00-00:04"


def test_content_profile_artifact_payloads_apply_strategy_gate_confirmations() -> None:
    final_profile = {
        "summary": "final",
        "capability_orchestration": {
            "strategy_type": "narrative_assembly",
            "classification": {
                "primary_type": "avatar_commentary_remix",
                "production_mode": "remix",
            },
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "production_mode": "remix",
                "primary_type": "avatar_commentary_remix",
                "review_gates": [
                    "strategy_confirmation_required",
                    "storyboard_review_required",
                    "timeline_preview_required",
                ],
            },
        },
    }
    confirmations = build_strategy_review_gate_confirmations_payload(
        gate_ids=["strategy_confirmation", "storyboard_review", "timeline_preview"],
        pipeline_plan=final_profile["capability_orchestration"]["pipeline_plan"],
        classification=final_profile["capability_orchestration"]["classification"],
        status="approved",
    )

    payloads = build_content_profile_artifact_payloads(
        draft_profile={"summary": "draft"},
        final_profile=final_profile,
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
        strategy_review_gate_confirmations=confirmations,
    )

    assert payloads.strategy_review_gates is not None
    assert payloads.strategy_review_gates["confirmations"]["strategy_confirmation"]["status"] == "approved"
    assert payloads.strategy_review_gates["review_gate_status"]["blocking"] is False
    assert payloads.strategy_review_gates["review_gate_status"]["blocking_gate_ids"] == []


def test_content_profile_strategy_helper_feeds_strategy_review_gate_artifact() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a"],
            "music_asset_ids": ["music-a"],
        },
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "strategy_classification": {
                            "primary_type": "avatar_commentary_remix",
                            "production_mode": "remix",
                            "content_tags": ["news_commentary"],
                            "media_tags": ["script_driven", "digital_human"],
                            "editing_signals": ["storyboard_required", "material_insert_required"],
                            "asset_tags": ["creator_avatar", "tts_voice"],
                            "confidence": 0.78,
                        }
                    }
                },
            )
        ],
    )

    profile = attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4", "broll-a.mp4"],
            "subject_type": "数字人解说",
        },
        job=job,
    )
    payloads = build_content_profile_artifact_payloads(
        draft_profile={"summary": "draft"},
        final_profile=profile,
        downstream_profile={"summary": "downstream"},
        subtitle_quality_report={"score": 96.0},
    )

    assert profile is not None
    assert profile["source_context"]["strategy_classification"]["primary_type"] == "avatar_commentary_remix"
    assert profile["capability_orchestration"]["strategy_type"] == "narrative_assembly"
    assert profile["capability_orchestration"]["review_gate_status"]["blocking"] is True
    assert payloads.strategy_review_gates is not None
    assert payloads.strategy_review_gates["pipeline_plan"]["production_mode"] == "remix"
    assert set(payloads.strategy_review_gates["review_gate_status"]["blocking_gate_ids"]) == {
        "strategy_confirmation",
        "storyboard_review",
        "timeline_preview",
    }


def test_content_profile_strategy_helper_uses_job_product_controls_before_strategy_inference() -> None:
    job = SimpleNamespace(
        workflow_template=None,
        job_flow_mode="auto",
        packaging_snapshot_json={},
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "product_controls": {
                            "edit_mode": "tutorial",
                            "automation_level": "standard",
                            "material_usage": "all_uploaded",
                        }
                    }
                },
            )
        ],
    )

    profile = attach_content_profile_capability_orchestration(
        {
            "merged_source_names": ["lesson-main.mp4", "screen-detail.mp4"],
            "subject_type": "屏幕操作教程",
        },
        job=job,
    )

    assert profile is not None
    orchestration = profile["capability_orchestration"]
    assert profile["source_context"]["product_controls"]["edit_mode"] == "tutorial"
    assert orchestration["strategy_type"] == "step_demonstration"
    assert orchestration["classification"]["production_mode"] == "tutorial"
    assert "step_by_step" in orchestration["classification"]["editing_signals"]
