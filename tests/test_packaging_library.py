from __future__ import annotations

import json
import uuid

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
