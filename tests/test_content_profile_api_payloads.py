from types import SimpleNamespace

from roughcut.api.jobs import (
    _attach_content_profile_capability_orchestration,
    _ensure_content_understanding_payload,
)
from roughcut.review.content_profile import _attach_content_understanding_timed_focus_spans


def test_attach_content_understanding_timed_focus_spans_from_evidence_bundle() -> None:
    profile = {
        "content_understanding": {
            "video_type": "unboxing",
            "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
        }
    }
    evidence_bundle = {
        "semantic_fact_inputs": {
            "timed_focus_spans": [
                {
                    "timestamp": "00:00-00:02",
                    "text": "开场先讲结论",
                    "type": "hook",
                    "start_time": 0.0,
                    "end_time": 2.0,
                },
                {
                    "timestamp": "00:02-00:05",
                    "text": "这里拿 EDC17 和 EDC37 做对比",
                    "type": "comparison",
                    "start_time": 2.0,
                    "end_time": 5.0,
                },
            ]
        }
    }

    enriched = _attach_content_understanding_timed_focus_spans(profile, evidence_bundle=evidence_bundle)

    assert len(enriched["content_understanding"]["timed_focus_spans"]) == 2
    assert enriched["content_understanding"]["timed_focus_spans"][0]["type"] == "hook"


def test_ensure_content_understanding_payload_preserves_timed_focus_spans() -> None:
    payload = _ensure_content_understanding_payload(
        {
            "subject_type": "NITECORE EDC17 手电",
            "content_understanding": {
                "video_type": "unboxing",
                "content_domain": "flashlight",
                "primary_subject": "NITECORE EDC17 手电",
                "evidence_spans": [{"timestamp": "00:02-00:05", "text": "对比片段", "type": "comparison"}],
                "timed_focus_spans": [
                    {
                        "timestamp": "00:00-00:02",
                        "text": "开场先讲结论",
                        "type": "hook",
                        "start_time": 0.0,
                        "end_time": 2.0,
                    }
                ],
                "needs_review": False,
            },
        }
    )

    assert payload is not None
    assert payload["content_understanding"]["timed_focus_spans"][0]["timestamp"] == "00:00-00:02"
    assert payload["content_understanding"]["evidence_spans"][0]["type"] == "comparison"


def test_attach_content_profile_capability_orchestration_for_tutorial_preview() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
        job_flow_mode="smart_assist",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a", "insert-b"],
            "music_asset_ids": ["music-a"],
            "intro_asset_id": "intro-a",
            "watermark_asset_id": "wm-a",
        },
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["strategy_type"] == "step_demonstration"
    assert orchestration["job_flow_mode"] == "smart_assist"
    assert orchestration["local_asset_inventory"]["auxiliary_video_count"] == 1
    assert orchestration["local_asset_inventory"]["image_count"] == 2
    assert orchestration["local_asset_inventory"]["audio_count"] == 1
    assert orchestration["capabilities"]["screen_focus"] == "suggest"
    assert orchestration["capabilities"]["local_broll_insert"] == "suggest"
    assert orchestration["capabilities"]["local_audio_cues"] == "suggest"


def test_attach_content_profile_capability_orchestration_keeps_commentary_baseline() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={},
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "subject_type": "观点口播",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["strategy_type"] == "information_density"
    assert orchestration["capabilities"]["speech_density_trim"] == "auto_apply"
    assert orchestration["capabilities"]["screen_focus"] == "disabled"
    assert orchestration["capabilities"]["local_broll_insert"] == "disabled"


def test_attach_content_profile_capability_orchestration_material_usage_main_only_disables_supporting_materials() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a", "insert-b"],
            "music_asset_ids": ["music-a"],
        },
        steps=[
            SimpleNamespace(
                step_name="content_profile",
                metadata_={
                    "source_context": {
                        "product_controls": {
                            "edit_mode": "tutorial",
                            "automation_level": "standard",
                            "material_usage": "main_only",
                        }
                    }
                },
            )
        ],
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["product_controls"]["effective"]["material_usage"] == "main_only"
    assert orchestration["capabilities"]["local_broll_insert"] == "disabled"
    assert orchestration["capabilities"]["local_audio_cues"] == "disabled"
    assert orchestration["capabilities"]["multi_material_assembly"] == "disabled"


def test_attach_content_profile_capability_orchestration_conservative_tutorial_downgrades_focus() -> None:
    job = SimpleNamespace(
        workflow_template="tutorial_standard",
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
                        "product_controls": {
                            "edit_mode": "tutorial",
                            "automation_level": "conservative",
                            "material_usage": "all_uploaded",
                        }
                    }
                },
            )
        ],
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "detail-cut.mp4"],
            "subject_type": "Premiere 教程",
        },
        job=job,
    )

    assert payload is not None
    orchestration = payload["capability_orchestration"]
    assert orchestration["product_controls"]["effective"]["automation_level"] == "conservative"
    assert orchestration["capabilities"]["screen_focus"] == "suggest"
    assert orchestration["capabilities"]["local_broll_insert"] == "suggest"


def test_attach_content_profile_capability_orchestration_recommends_multi_material_mode() -> None:
    job = SimpleNamespace(
        workflow_template="commentary_focus",
        job_flow_mode="auto",
        packaging_snapshot_json={
            "insert_asset_ids": ["insert-a"],
            "music_asset_ids": ["music-a"],
        },
    )
    payload = _attach_content_profile_capability_orchestration(
        {
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4", "cut-1.mp4", "cut-2.mp4"],
            "subject_type": "观点口播",
        },
        job=job,
    )

    assert payload is not None
    controls = payload["product_controls"]
    assert controls["requested"]["edit_mode"] == "auto"
    assert controls["recommended"]["edit_mode"] == "multi_material"
    assert payload["capability_orchestration"]["product_controls"]["effective"]["edit_mode"] == "multi_material"
