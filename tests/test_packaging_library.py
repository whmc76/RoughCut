from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from roughcut.packaging import library


def test_packaging_library_saves_and_resolves_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    intro = library.save_packaging_asset(
        asset_type="intro",
        filename="intro.mp4",
        payload=b"intro",
    )
    music_a = library.save_packaging_asset(
        asset_type="music",
        filename="tutorial_clean_bgm.mp3",
        payload=b"a",
    )
    music_b = library.save_packaging_asset(
        asset_type="music",
        filename="battle_hype_bgm.mp3",
        payload=b"b",
    )
    insert = library.save_packaging_asset(
        asset_type="insert",
        filename="screen_step_demo_insert.mp4",
        payload=b"insert",
    )

    library.update_packaging_config(
        {
            "intro_asset_id": intro["id"],
            "insert_asset_id": insert["id"],
            "insert_asset_ids": [insert["id"]],
            "insert_selection_mode": "manual",
            "music_asset_ids": [music_a["id"], music_b["id"]],
            "music_selection_mode": "random",
            "music_loop_mode": "loop_all",
            "subtitle_style": "cinema_blue",
            "cover_style": "tactical_neon",
            "copy_style": "trusted_expert",
            "export_resolution_mode": "specified",
            "export_resolution_preset": "1080p",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "preset_name": "screen_tutorial",
            "subject_type": "剪映字幕工作流",
            "video_theme": "批量字幕样式调整步骤讲解",
        },
    )
    assert plan["intro"]["asset_id"] == intro["id"]
    assert plan["insert"]["asset_id"] == insert["id"]
    assert plan["insert"]["insert_archetype"] == "demo_step"
    assert plan["insert"]["candidate_assets"][0]["insert_motion_profile"] == "guided_hold"
    assert plan["music"]["asset_id"] == music_a["id"]
    assert plan["music"]["loop_mode"] == "loop_all"
    assert len(plan["music"]["candidate_paths"]) == 2
    assert plan["music"]["selection_strategy"] == "auto_ranked_pool"
    assert plan["music"]["selection_summary"]["review_recommended"] is False
    assert plan["subtitle_style"] == "cinema_blue"
    assert plan["cover_style"] == "tactical_neon"
    assert plan["copy_style"] == "trusted_expert"
    assert plan["export_resolution_mode"] == "specified"
    assert plan["export_resolution_preset"] == "1080p"


def test_packaging_library_describes_insert_candidate_archetypes(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    macro = library.save_packaging_asset(
        asset_type="insert",
        filename="product_macro_detail_insert.mp4",
        payload=b"macro",
    )
    lifestyle = library.save_packaging_asset(
        asset_type="insert",
        filename="city_lifestyle_cutaway_insert.mp4",
        payload=b"lifestyle",
    )

    library.update_packaging_config(
        {
            "insert_asset_id": macro["id"],
            "insert_asset_ids": [macro["id"], lifestyle["id"]],
            "insert_selection_mode": "random",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={"preset_name": "daily_vlog", "video_theme": "城市通勤日常"},
    )

    candidate_archetypes = {item["asset_id"]: item["insert_archetype"] for item in plan["insert"]["candidate_assets"]}
    assert candidate_archetypes[macro["id"]] == "macro_detail"
    assert candidate_archetypes[lifestyle["id"]] == "lifestyle_context"


def test_packaging_library_resolves_insert_prepare_and_runtime_duration():
    plan = {
        "insert_target_duration_sec": 1.2,
        "insert_motion_profile": "quick_punch",
    }

    assert library.resolve_insert_prepare_duration(plan, source_duration=3.4) == 1.296
    assert library.resolve_insert_effective_duration(plan, source_duration=3.4) == 1.2


def test_packaging_library_delete_clears_selected_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    watermark = library.save_packaging_asset(
        asset_type="watermark",
        filename="mark.png",
        payload=b"watermark",
    )
    state = library.list_packaging_assets()
    assert state["config"]["watermark_asset_id"] == watermark["id"]

    library.delete_packaging_asset(watermark["id"])
    state = library.list_packaging_assets()
    assert state["config"]["watermark_asset_id"] is None


def test_packaging_library_migrates_legacy_none_loop_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "manifest.json").write_text(
        json.dumps({"assets": [], "config": {"music_loop_mode": "none"}}, ensure_ascii=False),
        encoding="utf-8",
    )

    payload = library.list_packaging_assets()

    assert payload["config"]["music_loop_mode"] == "loop_all"


def test_packaging_library_flags_review_for_low_confidence_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    music_a = library.save_packaging_asset(
        asset_type="music",
        filename="track_alpha.mp3",
        payload=b"a",
    )
    music_b = library.save_packaging_asset(
        asset_type="music",
        filename="track_beta.mp3",
        payload=b"b",
    )

    library.update_packaging_config(
        {
            "music_asset_ids": [music_a["id"], music_b["id"]],
            "music_selection_mode": "random",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={"preset_name": "screen_tutorial"},
    )

    assert plan["music"]["asset_id"] in {music_a["id"], music_b["id"]}
    assert plan["music"]["selection_summary"]["review_recommended"] is True
    assert plan["music"]["selection_summary"]["review_reason"]


def test_packaging_library_defaults_match_new_overlay_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    payload = library.list_packaging_assets()

    assert payload["config"]["music_volume"] == 0.12
    assert payload["config"]["watermark_position"] == "top_left"
    assert payload["config"]["avatar_overlay_position"] == "top_right"
    assert payload["config"]["avatar_overlay_scale"] == 0.18


def test_packaging_library_reset_restores_defaults_but_keeps_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    intro = library.save_packaging_asset(
        asset_type="intro",
        filename="intro.mp4",
        payload=b"intro",
    )
    library.update_packaging_config(
        {
            "intro_asset_id": intro["id"],
            "avatar_overlay_position": "bottom_left",
            "avatar_overlay_scale": 0.26,
            "avatar_overlay_corner_radius": 32,
            "avatar_overlay_border_width": 6,
            "avatar_overlay_border_color": "#FFFFFF",
        }
    )

    config = library.reset_packaging_config()
    state = library.list_packaging_assets()

    assert config["intro_asset_id"] is None
    assert config["avatar_overlay_position"] == "top_right"
    assert config["avatar_overlay_scale"] == 0.18
    assert config["avatar_overlay_corner_radius"] == 26
    assert config["avatar_overlay_border_width"] == 4
    assert config["avatar_overlay_border_color"] == "#F4E4B8"
    assert len(state["assets"]["intro"]) == 1


def test_packaging_library_music_selection_prefers_ai_domain_over_template_name(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    ai_music = library.save_packaging_asset(
        asset_type="music",
        filename="workflow_nodes_ai_bgm.mp3",
        payload=b"ai",
    )
    tech_music = library.save_packaging_asset(
        asset_type="music",
        filename="phone_chip_review_bgm.mp3",
        payload=b"tech",
    )

    library.update_packaging_config(
        {
            "music_asset_ids": [ai_music["id"], tech_music["id"]],
            "music_selection_mode": "random",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "workflow_template": "tutorial_standard",
            "subject_domain": "ai",
            "video_theme": "ComfyUI 工作流与模型推理讲解",
        },
    )

    assert plan["music"]["asset_id"] == ai_music["id"]


def test_packaging_library_auto_applies_commerce_bundle_for_default_style_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "subject_domain": "edc",
            "video_theme": "新品开箱升级 限时优惠提醒",
            "summary": "这波升级值不值",
        },
    )

    assert plan["subtitle_style"] == "sale_banner"
    assert plan["subtitle_motion_style"] == "motion_strobe"
    assert plan["smart_effect_style"] == "smart_effect_punch"
    assert plan["style_template_bundle_key"] == "impact_commerce"
    assert plan["style_template_bundle_recommended_key"] == "impact_commerce"
    assert plan["style_template_bundle_auto_applied"] is True


def test_packaging_library_recommends_explainer_bundle_for_workflow_content_without_overriding_custom_choice(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    library.update_packaging_config(
        {
            "subtitle_style": "keyword_highlight",
            "subtitle_motion_style": "motion_glitch",
            "smart_effect_style": "smart_effect_glitch",
            "cover_style": "clean_lab",
            "title_style": "tutorial_blueprint",
            "copy_style": "trusted_expert",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "subject_domain": "ai",
            "workflow_template": "tutorial_standard",
            "video_theme": "AI 工作流搭建教程",
            "summary": "把步骤和配置先讲清楚",
        },
    )

    assert plan["subtitle_style"] == "keyword_highlight"
    assert plan["style_template_bundle_key"] == "hardcore_specs"
    assert plan["style_template_bundle_recommended_key"] == "restrained_explainer"
    assert plan["style_template_bundle_auto_applied"] is False


def test_packaging_library_recommends_suspense_bundle_for_teaser_language(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "video_theme": "真正的大招还在后面",
            "summary": "先别划走 最后的反转更狠",
        },
    )

    assert plan["subtitle_style"] == "teaser_glow"
    assert plan["style_template_bundle_key"] == "suspense_teaser"
    assert plan["style_template_bundle_recommended_key"] == "suspense_teaser"
    assert plan["style_template_bundle_auto_applied"] is True


def test_packaging_library_music_selection_prefers_tech_domain_over_template_name(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    ai_music = library.save_packaging_asset(
        asset_type="music",
        filename="workflow_nodes_ai_bgm.mp3",
        payload=b"ai",
    )
    tech_music = library.save_packaging_asset(
        asset_type="music",
        filename="phone_chip_review_bgm.mp3",
        payload=b"tech",
    )

    library.update_packaging_config(
        {
            "music_asset_ids": [ai_music["id"], tech_music["id"]],
            "music_selection_mode": "random",
        }
    )

    plan = library.resolve_packaging_plan_for_job(
        str(uuid.uuid4()),
        content_profile={
            "workflow_template": "tutorial_standard",
            "subject_domain": "tech",
            "video_theme": "手机芯片与续航实测",
        },
    )

    assert plan["music"]["asset_id"] == tech_music["id"]


@pytest.mark.asyncio
async def test_packaging_library_uses_job_packaging_snapshot_when_present(db_engine, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from roughcut.db.models import Job
    from roughcut.db.session import get_session_factory

    monkeypatch.setattr(library, "PACKAGING_ROOT", tmp_path)
    monkeypatch.setattr(library, "MANIFEST_PATH", tmp_path / "manifest.json")

    library.update_packaging_config(
        {
            "copy_style": "trusted_expert",
            "subtitle_style": "cinema_blue",
            "cover_style": "tactical_neon",
        }
    )

    job_id = uuid.uuid4()
    async with get_session_factory()() as session:
        session.add(
            Job(
                id=job_id,
                source_path="jobs/demo/packaging-profile.mp4",
                source_name="packaging-profile.mp4",
                status="pending",
                language="zh-CN",
                packaging_snapshot_json={
                    "copy_style": "attention_grabbing",
                    "subtitle_style": "bold_yellow_outline",
                    "cover_style": "preset_default",
                    "title_style": "preset_default",
                    "subtitle_motion_style": "motion_static",
                    "smart_effect_style": "smart_effect_rhythm",
                    "export_resolution_mode": "source",
                    "export_resolution_preset": "1080p",
                    "enabled": True,
                },
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    plan = library.resolve_packaging_plan_for_job(str(job_id), content_profile={"workflow_template": "tutorial_standard"})

    assert plan["copy_style"] == "attention_grabbing"
    assert plan["subtitle_style"] == "bold_yellow_outline"
    assert plan["cover_style"] == "preset_default"
    assert plan["smart_effect_style"] == "smart_effect_commercial"


@pytest.mark.asyncio
async def test_packaging_library_migrates_legacy_container_asset_paths_to_shared_root(db_engine, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from roughcut.db.models import AppSetting, PackagingAsset
    from roughcut.db.session import get_session_factory

    shared_root = tmp_path / "shared-packaging"
    monkeypatch.setattr(library, "PACKAGING_ROOT", shared_root)
    monkeypatch.setattr(library, "MANIFEST_PATH", shared_root / "manifest.json")

    legacy_file = tmp_path / "legacy-private" / "outro" / "legacy-outro.mp4"
    legacy_file.parent.mkdir(parents=True, exist_ok=True)
    legacy_file.write_bytes(b"legacy-outro")

    asset_id = "legacy-outro-asset"
    stored_name = "legacy-outro.mp4"
    async with get_session_factory()() as session:
        session.add(
            PackagingAsset(
                id=asset_id,
                asset_type="outro",
                original_name="legacy-outro.mp4",
                stored_name=stored_name,
                path=f"/app/{legacy_file.as_posix()}",
                size_bytes=len(b"legacy-outro"),
                content_type="video/mp4",
                watermark_preprocessed=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AppSetting(
                key="packaging_config",
                value_json={
                    "enabled": True,
                    "outro_asset_id": asset_id,
                },
            )
        )
        await session.commit()

    plan = library.resolve_packaging_plan_for_job(str(uuid.uuid4()), content_profile={"workflow_template": "tutorial_standard"})

    assert plan["outro"] is not None
    resolved_path = Path(plan["outro"]["path"])
    assert resolved_path == shared_root / "outro" / stored_name
    assert resolved_path.exists()
    assert resolved_path.read_bytes() == b"legacy-outro"


@pytest.mark.asyncio
async def test_packaging_library_hides_missing_assets_from_config_and_listing(db_engine, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from roughcut.db.models import AppSetting, PackagingAsset
    from roughcut.db.session import get_session_factory

    shared_root = tmp_path / "shared-packaging"
    monkeypatch.setattr(library, "PACKAGING_ROOT", shared_root)
    monkeypatch.setattr(library, "MANIFEST_PATH", shared_root / "manifest.json")

    asset_id = "missing-watermark-asset"
    async with get_session_factory()() as session:
        session.add(
            PackagingAsset(
                id=asset_id,
                asset_type="watermark",
                original_name="missing-logo.png",
                stored_name="missing-logo.png",
                path=str(tmp_path / "missing" / "missing-logo.png"),
                size_bytes=12,
                content_type="image/png",
                watermark_preprocessed=None,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            AppSetting(
                key="packaging_config",
                value_json={
                    "enabled": True,
                    "watermark_asset_id": asset_id,
                },
            )
        )
        await session.commit()

    payload = library.list_packaging_assets()

    assert payload["assets"]["watermark"] == []
    assert payload["config"]["watermark_asset_id"] is None
