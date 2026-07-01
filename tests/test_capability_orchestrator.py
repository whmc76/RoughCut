from roughcut.edit.capability_orchestrator import (
    build_capability_orchestration_payload,
    normalize_local_asset_inventory,
)
from roughcut.edit.strategy_review_gates import build_strategy_review_gate_status
from roughcut.edit.strategy_review_gates import (
    build_strategy_review_gate_confirmations_payload,
    normalize_strategy_review_gate_confirmations,
)


def test_information_density_commentary_keeps_focus_disabled() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template="commentary_focus",
        content_profile={"content_kind": "commentary"},
        local_asset_inventory={
            "extra_video_files": ["clip-a.mp4"],
            "audio_files": ["bgm-a.wav"],
        },
    )

    assert payload["strategy_type"] == "information_density"
    assert payload["content_kind"] == "commentary"
    assert payload["capabilities"]["speech_density_trim"] == "auto_apply"
    assert payload["capabilities"]["screen_focus"] == "disabled"
    assert payload["capabilities"]["local_broll_insert"] == "disabled"
    assert payload["capabilities"]["local_audio_cues"] == "suggest"


def test_tutorial_defaults_to_step_demonstration_strategy() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template="tutorial_standard",
        content_profile={"content_kind": "tutorial"},
        local_asset_inventory={"extra_video_files": ["screen-cut.mp4"]},
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["content_kind"] == "tutorial"
    assert payload["capabilities"]["speech_density_trim"] == "auto_apply"
    assert payload["capabilities"]["screen_focus"] == "auto_apply"
    assert payload["capabilities"]["chapter_cards"] == "suggest"
    assert payload["capabilities"]["local_broll_insert"] == "suggest"


def test_classification_tags_can_select_step_demonstration_without_content_kind() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template=None,
        content_profile={
            "strategy_classification": {
                "primary_type": "screen_recording",
                "content_tags": ["tutorial"],
                "media_tags": ["screen_recording", "step_by_step"],
                "editing_signals": ["subtitle_important"],
                "confidence": 0.82,
            }
        },
        local_asset_inventory={"extra_video_files": ["screen-cut.mp4"]},
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["classification"]["primary_type"] == "screen_recording"
    assert {
        "chapter_cards",
        "delivery_quality_governance",
        "screen_focus",
        "source_media_inspection",
        "source_media_review",
        "speech_density_trim",
        "subtitle_timeline_projection",
    }.issubset(set(payload["pipeline_plan"]["enabled_features"]))
    assert payload["capabilities"]["screen_focus"] == "auto_apply"


def test_high_energy_signal_alone_does_not_select_event_highlight() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template=None,
        content_profile={
            "strategy_classification": {
                "primary_type": "unboxing",
                "content_tags": ["unboxing"],
                "editing_signals": ["high_energy", "subtitle_important"],
                "confidence": 0.9,
            }
        },
        local_asset_inventory={},
    )

    assert payload["strategy_type"] == "information_density"
    assert "highlight_window_selection" not in payload["pipeline_plan"]["enabled_features"]


def test_high_energy_with_event_context_selects_event_highlight() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template=None,
        content_profile={
            "strategy_classification": {
                "primary_type": "sports",
                "content_tags": ["sports"],
                "editing_signals": ["high_energy"],
                "confidence": 0.9,
            }
        },
        local_asset_inventory={},
    )

    assert payload["strategy_type"] == "event_highlight"
    assert "highlight_window_selection" in payload["pipeline_plan"]["enabled_features"]


def test_avatar_commentary_classification_selects_narrative_assembly_plan() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template="commentary_focus",
        content_profile={
            "content_kind": "commentary",
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
            },
        },
        local_asset_inventory={
            "extra_video_files": ["broll-a.mp4", "broll-b.mp4"],
            "images": ["quote.png"],
            "audio_files": ["bgm.wav"],
        },
    )

    assert payload["strategy_type"] == "narrative_assembly"
    assert payload["pipeline_plan"]["production_mode"] == "remix"
    assert "avatar_render" in payload["pipeline_plan"]["enabled_features"]
    assert "tts_generation" in payload["pipeline_plan"]["enabled_features"]
    assert "stock_footage_retrieval" in payload["pipeline_plan"]["enabled_features"]
    assert "budget_cost_estimate" in payload["pipeline_plan"]["enabled_features"]
    assert "soundtrack_audio_mix" in payload["pipeline_plan"]["enabled_features"]
    assert payload["pipeline_plan"]["strategy_policy"]["cut_policy"]["basis"] == "script_segment"
    assert payload["pipeline_plan"]["strategy_policy"]["review_policy"]["storyboard_review"] == "required"
    assert payload["pipeline_plan"]["strategy_policy"]["render_validation_policy"]["check_storyboard_alignment"] is True
    assert payload["pipeline_plan"]["strategy_policy"]["capability_defaults"]["generative_scene_plan"] == "suggest"
    assert payload["pipeline_plan"]["strategy_policy"]["capability_defaults"]["cost_budget_governance"] == "manual_required"
    assert "storyboard_review_required" in payload["pipeline_plan"]["review_gates"]
    assert "timeline_preview_required" in payload["pipeline_plan"]["review_gates"]
    assert payload["review_gate_status"]["blocking"] is True
    assert set(payload["review_gate_status"]["blocking_gate_ids"]) == {
        "strategy_confirmation",
        "storyboard_review",
        "timeline_preview",
    }
    assert payload["capabilities"]["multi_material_assembly"] == "manual_required"
    assert payload["capabilities"]["reference_style_analysis"] == "suggest"
    assert payload["capabilities"]["source_media_inspection"] == "auto_apply"
    assert payload["capabilities"]["cost_budget_governance"] == "manual_required"
    assert payload["capabilities"]["delivery_quality_governance"] == "auto_apply"


def test_explicit_strategy_profile_wins_over_classification_tags() -> None:
    payload = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "event_highlight"},
        workflow_template="tutorial_standard",
        content_profile={
            "strategy_classification": {
                "primary_type": "screen_recording",
                "content_tags": ["tutorial"],
                "media_tags": ["screen_recording"],
                "confidence": 0.91,
            }
        },
        local_asset_inventory={},
    )

    assert payload["strategy_type"] == "event_highlight"
    assert "highlight_window_selection" in payload["pipeline_plan"]["enabled_features"]
    assert payload["pipeline_plan"]["strategy_policy"]["cut_policy"]["basis"] == "highlight_window"


def test_pipeline_plan_uses_strategy_registry_for_information_density_policy() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template="commentary_focus",
        content_profile={
            "strategy_classification": {
                "primary_type": "talking_head",
                "media_tags": ["single_speaker", "speech_dominant"],
                "editing_signals": ["retake_likely", "silence_trim_useful"],
                "confidence": 0.92,
            }
        },
        local_asset_inventory={},
    )

    plan = payload["pipeline_plan"]
    assert payload["strategy_type"] == "information_density"
    assert plan["strategy_policy"]["cut_policy"]["snap_to_word_boundary"] is True
    assert plan["strategy_policy"]["cut_policy"]["edge_padding_ms"] == [50, 120]
    assert plan["strategy_policy"]["render_validation_policy"]["check_cut_boundaries"] is True
    assert "retake_and_silence_review" in plan["enabled_features"]
    assert "source_media_review" in plan["enabled_features"]
    assert "post_render_self_review" in plan["enabled_features"]
    assert "manual_cut_review_recommended" in plan["review_gates"]
    assert payload["review_gate_status"]["blocking"] is False
    assert payload["review_gate_status"]["recommended_gate_count"] == 1


def test_product_controls_and_inventory_feed_classification_snapshot() -> None:
    payload = build_capability_orchestration_payload(
        workflow_template="commentary_focus",
        content_profile={
            "content_kind": "commentary",
            "source_context": {
                "product_controls": {
                    "edit_mode": "tutorial",
                    "automation_level": "standard",
                    "material_usage": "all_uploaded",
                }
            },
        },
        local_asset_inventory={
            "extra_video_files": ["screen-a.mp4", "screen-b.mp4"],
            "images": ["step.png"],
            "audio_files": ["bgm.wav"],
        },
    )

    classification = payload["classification"]
    assert payload["strategy_type"] == "step_demonstration"
    assert classification["production_mode"] == "tutorial"
    assert "tutorial" in classification["content_tags"]
    assert "step_by_step" in classification["editing_signals"]
    assert "multi_material_ready" in classification["asset_tags"]
    assert "visual_inserts_available" in classification["asset_tags"]
    assert "audio_support_available" in classification["asset_tags"]


def test_strategy_review_gate_status_accepts_confirmations_for_required_gates() -> None:
    plan = {
        "strategy_type": "narrative_assembly",
        "review_gates": [
            "strategy_confirmation_required",
            "storyboard_review_required",
            "timeline_preview_required",
        ],
    }

    pending = build_strategy_review_gate_status(plan)
    approved = build_strategy_review_gate_status(
        plan,
        confirmations={
            "strategy_confirmation": {"status": "approved"},
            "storyboard_review": "confirmed",
            "timeline_preview": "satisfied",
        },
    )

    assert pending["blocking"] is True
    assert pending["required_gate_count"] == 3
    assert approved["blocking"] is False
    assert approved["blocking_gate_ids"] == []
    assert [item["status"] for item in approved["gates"]] == ["approved", "confirmed", "satisfied"]


def test_strategy_review_gate_confirmations_are_bound_to_evidence_fingerprint() -> None:
    plan = {
        "strategy_type": "narrative_assembly",
        "production_mode": "remix",
        "primary_type": "avatar_commentary_remix",
        "review_gates": ["storyboard_review_required"],
    }
    classification = {
        "primary_type": "avatar_commentary_remix",
        "production_mode": "remix",
        "media_tags": ["digital_human"],
        "confidence": 0.78,
    }

    confirmation = build_strategy_review_gate_confirmations_payload(
        gate_ids=["storyboard_review"],
        pipeline_plan=plan,
        classification=classification,
        status="approved",
        note="storyboard checked",
    )
    matching = normalize_strategy_review_gate_confirmations(
        confirmation,
        pipeline_plan=plan,
        classification=classification,
    )
    stale = normalize_strategy_review_gate_confirmations(
        confirmation,
        pipeline_plan={**plan, "production_mode": "source_cut"},
        classification=classification,
    )

    assert matching["storyboard_review"]["status"] == "approved"
    assert matching["storyboard_review"]["note"] == "storyboard checked"
    assert stale == {}


def test_step_demonstration_auto_applies_focus_and_downgrades_in_assist_mode() -> None:
    payload = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "step_demonstration"},
        workflow_template="tutorial_standard",
        content_profile={"content_kind": "tutorial"},
        local_asset_inventory={
            "extra_video_files": ["screen-cut.mp4"],
            "images": ["frame.png"],
            "audio_files": ["bgm-a.wav"],
        },
        job_flow_mode="smart_assist",
    )

    assert payload["strategy_type"] == "step_demonstration"
    assert payload["capabilities"]["speech_density_trim"] == "suggest"
    assert payload["capabilities"]["screen_focus"] == "suggest"
    assert payload["capabilities"]["chapter_cards"] == "suggest"
    assert payload["capabilities"]["local_broll_insert"] == "suggest"
    assert payload["capabilities"]["local_audio_cues"] == "suggest"
    assert payload["capabilities"]["source_media_inspection"] == "suggest"
    assert payload["capabilities"]["delivery_quality_governance"] == "suggest"


def test_missing_local_assets_disable_local_packaging_capabilities() -> None:
    payload = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "experience_and_mood"},
        workflow_template="vlog_daily",
        content_profile={"content_kind": "vlog"},
        local_asset_inventory={},
    )

    assert payload["capabilities"]["local_broll_insert"] == "disabled"
    assert payload["capabilities"]["local_audio_cues"] == "disabled"
    assert payload["capabilities"]["stock_footage_retrieval"] == "disabled"
    assert payload["capabilities"]["soundtrack_audio_mix"] == "suggest"
    assert payload["capabilities"]["speech_density_trim"] == "suggest"


def test_narrative_assembly_requires_multiple_uploaded_materials() -> None:
    blocked = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "narrative_assembly"},
        workflow_template="vlog_daily",
        content_profile={"content_kind": "vlog"},
        local_asset_inventory={"extra_video_files": ["shot-a.mp4"]},
    )
    ready = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "narrative_assembly"},
        workflow_template="vlog_daily",
        content_profile={"content_kind": "vlog"},
        local_asset_inventory={
            "extra_video_files": ["shot-a.mp4", "shot-b.mp4"],
            "images": ["still-a.png"],
        },
    )

    assert blocked["capabilities"]["multi_material_assembly"] == "disabled"
    assert ready["capabilities"]["multi_material_assembly"] == "manual_required"


def test_explicit_capability_overrides_win_after_policy_resolution() -> None:
    payload = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "event_highlight"},
        workflow_template="gameplay_highlight",
        content_profile={"content_kind": "gameplay"},
        local_asset_inventory={"audio_files": ["bgm-a.wav"]},
        capability_overrides={
            "highlight_window_selection": "manual_required",
            "local_audio_cues": "disabled",
        },
    )

    assert payload["capabilities"]["highlight_window_selection"] == "manual_required"
    assert payload["capabilities"]["local_audio_cues"] == "disabled"


def test_normalize_local_asset_inventory_accepts_count_and_list_shapes() -> None:
    inventory = normalize_local_asset_inventory(
        {
            "has_primary_video": True,
            "extra_video_file_count": 2,
            "still_images": ["frame-a.png"],
            "music_assets": ["bgm-a.wav", "bgm-b.wav"],
            "watermark_assets": ["wm.png"],
        }
    )

    assert inventory["primary_video_count"] == 1
    assert inventory["auxiliary_video_count"] == 2
    assert inventory["image_count"] == 1
    assert inventory["audio_count"] == 2
    assert inventory["watermark_count"] == 1
    assert inventory["has_visual_inserts"] is True
    assert inventory["multi_material_ready"] is True
