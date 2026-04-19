from __future__ import annotations

from roughcut.api.config import (
    ConfigPatch,
    ConfigProfileCreate,
    ConfigProfileUpdate,
    activate_profile,
    create_profile,
    get_config,
    get_config_profiles,
    patch_config,
    patch_profile,
    remove_profile,
)
from roughcut.packaging import library


def _configure_profile_runtime(tmp_path, monkeypatch):
    import roughcut.api.config as config_api
    import roughcut.config as config_mod
    import roughcut.config_profiles as profiles_mod

    monkeypatch.setattr(config_api, "_CONFIG_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(config_mod, "_OVERRIDES_FILE", tmp_path / "roughcut_config.json")
    monkeypatch.setattr(profiles_mod, "CONFIG_PROFILES_FILE", tmp_path / "roughcut_config_profiles.json")
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path / "packaging")
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "packaging" / "manifest.json")
    config_mod._settings = None


def test_config_profile_round_trip_restores_config_and_packaging(tmp_path, monkeypatch):
    _configure_profile_runtime(tmp_path, monkeypatch)

    patch_config(
        ConfigPatch(
            transcription_provider="qwen_asr",
            transcription_model="qwen3-asr-1.7b",
            transcription_dialect="beijing",
            reasoning_provider="openai",
            reasoning_model="gpt-4.1",
            default_job_workflow_mode="standard_edit",
            default_job_enhancement_modes=["avatar_commentary", "ai_effects"],
            avatar_presenter_id="profiles/demo_presenter.mp4",
            avatar_layout_template="picture_in_picture_right",
            avatar_safe_margin=0.12,
            voice_provider="runninghub",
            voice_clone_voice_id="voice_alpha",
            director_rewrite_strength=0.74,
            auto_confirm_content_profile=True,
            content_profile_review_threshold=0.72,
            packaging_selection_min_score=0.81,
            quality_auto_rerun_enabled=False,
            quality_auto_rerun_below_score=63.5,
        )
    )
    library.update_packaging_config(
        {
            "copy_style": "trusted_expert",
            "cover_style": "tech_showcase",
            "title_style": "chrome_impact",
            "subtitle_style": "cinema_blue",
            "smart_effect_style": "smart_effect_glitch",
            "avatar_overlay_position": "bottom_left",
            "avatar_overlay_scale": 0.24,
            "enabled": True,
        }
    )

    created = create_profile(ConfigProfileCreate(name="口播测评方案", description="适合带数字人和智能特效的测评口播"))
    profile_id = created.active_profile_id

    assert profile_id
    assert created.active_profile_dirty is False
    assert created.active_profile_dirty_details == []
    assert created.profiles[0].name == "口播测评方案"
    assert created.profiles[0].description == "适合带数字人和智能特效的测评口播"
    assert created.profiles[0].workflow_mode == "standard_edit"
    assert created.profiles[0].copy_style == "trusted_expert"
    assert created.profiles[0].avatar_presenter_id == "profiles/demo_presenter.mp4"

    patch_config(
        ConfigPatch(
            transcription_provider="openai",
            transcription_model="gpt-4o-transcribe",
            transcription_dialect="mandarin",
            reasoning_provider="minimax",
            reasoning_model="MiniMax-M2.7-highspeed",
            default_job_enhancement_modes=["ai_director"],
            avatar_presenter_id="profiles/other_presenter.mp4",
            voice_provider="indextts2",
            voice_clone_voice_id="voice_beta",
            director_rewrite_strength=0.31,
            auto_confirm_content_profile=False,
            content_profile_review_threshold=0.9,
            packaging_selection_min_score=0.55,
            quality_auto_rerun_enabled=True,
            quality_auto_rerun_below_score=75.0,
        )
    )
    library.update_packaging_config(
        {
            "copy_style": "balanced",
            "cover_style": "premium_silver",
            "title_style": "magazine_clean",
            "subtitle_style": "white_minimal",
            "avatar_overlay_position": "top_right",
            "enabled": False,
        }
    )

    activate_profile(profile_id)
    config = get_config()
    packaging = library.list_packaging_assets()

    assert config.transcription_provider == "qwen3_asr"
    assert config.transcription_model == "qwen3-asr-1.7b"
    assert config.transcription_dialect == "beijing"
    assert config.reasoning_provider == "openai"
    assert config.reasoning_model == "gpt-4.1"
    assert config.default_job_enhancement_modes == ["avatar_commentary", "ai_effects"]
    assert config.avatar_presenter_id == "profiles/demo_presenter.mp4"
    assert config.voice_provider == "runninghub"
    assert config.voice_clone_voice_id == "voice_alpha"
    assert config.director_rewrite_strength == 0.74
    assert config.auto_confirm_content_profile is True
    assert config.content_profile_review_threshold == 0.72
    assert config.packaging_selection_min_score == 0.81
    assert config.quality_auto_rerun_enabled is False
    assert config.quality_auto_rerun_below_score == 63.5
    assert packaging["config"]["copy_style"] == "trusted_expert"
    assert packaging["config"]["cover_style"] == "tech_showcase"
    assert packaging["config"]["title_style"] == "chrome_impact"
    assert packaging["config"]["subtitle_style"] == "cinema_blue"
    assert packaging["config"]["avatar_overlay_position"] == "bottom_left"
    assert packaging["config"]["enabled"] is True


def test_config_profile_marks_active_profile_dirty_until_recaptured(tmp_path, monkeypatch):
    _configure_profile_runtime(tmp_path, monkeypatch)

    patch_config(
        ConfigPatch(
            default_job_enhancement_modes=["avatar_commentary"],
            avatar_presenter_id="profiles/demo_presenter.mp4",
        )
    )
    library.update_packaging_config(
        {
            "copy_style": "attention_grabbing",
            "cover_style": "preset_default",
        }
    )

    created = create_profile(ConfigProfileCreate(name="默认方案", description="默认审核基线"))
    profile_id = created.active_profile_id

    patch_config(
        ConfigPatch(
            default_job_enhancement_modes=["avatar_commentary", "ai_director"],
            avatar_presenter_id="profiles/demo_presenter_b.mp4",
        )
    )
    library.update_packaging_config(
        {
            "copy_style": "premium_editorial",
            "cover_style": "luxury_blackgold",
        }
    )

    profiles = get_config_profiles()
    active_profile = next(profile for profile in profiles.profiles if profile.id == profile_id)

    assert profiles.active_profile_dirty is True
    assert set(profiles.active_profile_dirty_keys) == {
        "avatar_presenter_id",
        "default_job_enhancement_modes",
        "packaging.copy_style",
        "packaging.cover_style",
    }
    dirty_details = {item["key"]: item for item in profiles.active_profile_dirty_details}
    assert dirty_details["avatar_presenter_id"] == {
        "key": "avatar_presenter_id",
        "saved_value": "profiles/demo_presenter.mp4",
        "current_value": "profiles/demo_presenter_b.mp4",
    }
    assert dirty_details["default_job_enhancement_modes"] == {
        "key": "default_job_enhancement_modes",
        "saved_value": ["avatar_commentary"],
        "current_value": ["avatar_commentary", "ai_director"],
    }
    assert active_profile.is_active is True
    assert active_profile.is_dirty is True
    assert set(active_profile.dirty_keys) == set(profiles.active_profile_dirty_keys)
    assert active_profile.dirty_details == profiles.active_profile_dirty_details

    updated = patch_profile(
        profile_id,
        ConfigProfileUpdate(name="导演增强方案", description="导演增强和复跑优先", capture_current=True),
    )
    refreshed_profile = next(profile for profile in updated.profiles if profile.id == profile_id)

    assert updated.active_profile_dirty is False
    assert updated.active_profile_dirty_keys == []
    assert updated.active_profile_dirty_details == []
    assert refreshed_profile.name == "导演增强方案"
    assert refreshed_profile.description == "导演增强和复跑优先"
    assert refreshed_profile.is_dirty is False
    assert refreshed_profile.dirty_keys == []
    assert refreshed_profile.dirty_details == []
    assert refreshed_profile.copy_style == "premium_editorial"
    assert refreshed_profile.cover_style == "luxury_blackgold"
    assert refreshed_profile.enhancement_modes == ["avatar_commentary", "ai_director"]


def test_delete_active_config_profile_clears_active_pointer(tmp_path, monkeypatch):
    _configure_profile_runtime(tmp_path, monkeypatch)

    created = create_profile(ConfigProfileCreate(name="待删除方案"))
    profile_id = created.active_profile_id

    deleted = remove_profile(profile_id)

    assert deleted.active_profile_id is None
    assert deleted.active_profile_dirty is False
    assert deleted.profiles == []
