from roughcut.edit.capability_orchestrator import (
    build_capability_orchestration_payload,
    normalize_local_asset_inventory,
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


def test_missing_local_assets_disable_local_packaging_capabilities() -> None:
    payload = build_capability_orchestration_payload(
        strategy_profile={"strategy_type": "experience_and_mood"},
        workflow_template="vlog_daily",
        content_profile={"content_kind": "vlog"},
        local_asset_inventory={},
    )

    assert payload["capabilities"]["local_broll_insert"] == "disabled"
    assert payload["capabilities"]["local_audio_cues"] == "disabled"
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
