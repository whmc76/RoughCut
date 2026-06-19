from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from roughcut import creator_asset_runtime
from roughcut.creator_asset_runtime import pick_creator_avatar_presenter_asset, resolve_creator_asset_path
from roughcut.packaging import library as packaging_library
from roughcut.pipeline import steps as pipeline_steps


def test_pick_creator_avatar_presenter_asset_prefers_closeup_video(tmp_path: Path) -> None:
    closeup = tmp_path / "closeup.mp4"
    closeup.write_bytes(b"closeup")
    full_body = tmp_path / "full.mp4"
    full_body.write_bytes(b"full")

    selected = pick_creator_avatar_presenter_asset(
        [
            {
                "id": "full",
                "asset_type": "digital_human_full_body",
                "stored_path": full_body.as_posix(),
                "metadata_json": {"content_type": "video/mp4"},
                "created_at": "2026-06-14T10:00:00+08:00",
            },
            {
                "id": "close",
                "asset_type": "digital_human_closeup",
                "stored_path": closeup.as_posix(),
                "metadata_json": {"content_type": "video/mp4"},
                "created_at": "2026-06-13T10:00:00+08:00",
            },
        ]
    )

    assert selected is not None
    assert selected["id"] == "close"


def test_resolve_creator_asset_path_repairs_container_path(tmp_path: Path, monkeypatch) -> None:
    output_dir = tmp_path / "runtime-output"
    asset_path = output_dir / "_creator_assets" / "creator-1" / "asset.mp4"
    asset_path.parent.mkdir(parents=True, exist_ok=True)
    asset_path.write_bytes(b"asset")
    monkeypatch.setattr(
        creator_asset_runtime,
        "get_settings",
        lambda: SimpleNamespace(output_dir=output_dir.as_posix()),
    )

    resolved = resolve_creator_asset_path("/app/data/output/_creator_assets/creator-1/asset.mp4")

    assert resolved == asset_path.resolve()


def test_resolve_creator_avatar_binding_prefers_creator_asset_over_legacy(monkeypatch, tmp_path: Path) -> None:
    presenter = tmp_path / "creator-closeup.mp4"
    presenter.write_bytes(b"video")
    creator = SimpleNamespace(
        id="creator-1",
        name="Creator One",
        assets=[
            SimpleNamespace(
                id="asset-1",
                asset_type="digital_human_closeup",
                stored_path=presenter.as_posix(),
                metadata_json={"content_type": "video/mp4"},
                created_at="2026-06-14T10:00:00+08:00",
            )
        ],
        preferences=[
            SimpleNamespace(
                source="legacy_avatar_profile",
                structured_payload={"legacy_profile_id": "legacy-1"},
            )
        ],
    )
    monkeypatch.setattr(pipeline_steps, "list_avatar_material_profiles", lambda: [])

    binding = pipeline_steps._resolve_creator_avatar_binding(creator)

    assert binding is not None
    assert binding["source"] == "creator_asset"
    assert binding["presenter_id"] == presenter.as_posix()
    assert binding["creator_asset_id"] == "asset-1"


def test_resolve_creator_avatar_binding_uses_legacy_profile_bound_to_creator(monkeypatch, tmp_path: Path) -> None:
    presenter = tmp_path / "legacy-presenter.mp4"
    presenter.write_bytes(b"legacy")
    creator = SimpleNamespace(
        id="creator-1",
        name="Creator One",
        assets=[],
        preferences=[
            SimpleNamespace(
                source="legacy_avatar_profile",
                structured_payload={"legacy_profile_id": "legacy-1"},
            )
        ],
    )
    monkeypatch.setattr(
        pipeline_steps,
        "list_avatar_material_profiles",
        lambda: [
            {
                "id": "legacy-1",
                "display_name": "Legacy Presenter",
                "created_at": "2026-06-14T10:00:00+08:00",
                "capability_status": {"preview": "ready", "generation": "ready"},
                "files": [
                    {
                        "role": "speaking_video",
                        "path": presenter.as_posix(),
                    }
                ],
            }
        ],
    )

    binding = pipeline_steps._resolve_creator_avatar_binding(creator)

    assert binding is not None
    assert binding["source"] == "legacy_avatar_profile"
    assert binding["avatar_profile_id"] == "legacy-1"
    assert binding["presenter_id"] == presenter.as_posix()


def test_missing_creator_avatar_binding_is_skipped_not_degraded() -> None:
    plan = {
        "mode": "full_track_audio_passthrough",
        "provider": "heygem",
    }

    pipeline_steps._apply_avatar_presenter_binding_to_plan(
        plan,
        binding=None,
        packaging_config={},
    )
    reason = pipeline_steps._avatar_missing_presenter_reason(plan)

    assert reason == "creator_avatar_binding_missing"
    assert pipeline_steps._avatar_missing_presenter_execution(plan, reason=reason) == {
        "provider": "heygem",
        "status": "skipped",
        "reason": "creator_avatar_binding_missing",
        "detail": "未配置可用数字人 presenter，跳过数字人渲染；普通成片不受影响。",
    }
    assert pipeline_steps._avatar_missing_presenter_runtime_result(plan, reason=reason) == {
        "enabled": True,
        "status": "skipped",
        "reason": "creator_avatar_binding_missing",
        "reason_category": "not_configured",
        "mode": "full_track_audio_passthrough",
        "integration_mode": "",
        "provider": "heygem",
        "detail": "未配置可用数字人 presenter，跳过数字人渲染；普通成片不受影响。",
    }


def test_resolve_packaging_plan_for_job_prefers_creator_assets(monkeypatch, tmp_path: Path) -> None:
    intro = tmp_path / "intro.mp4"
    intro.write_bytes(b"intro")
    outro = tmp_path / "outro.mp4"
    outro.write_bytes(b"outro")
    logo = tmp_path / "logo.png"
    logo.write_bytes(b"logo")
    music = tmp_path / "music.mp3"
    music.write_bytes(b"music")

    monkeypatch.setattr(packaging_library, "_load_state", lambda: {"config": {}, "assets": []})
    monkeypatch.setattr(packaging_library, "_load_job_packaging_snapshot", lambda _job_id: None)
    monkeypatch.setattr(packaging_library, "recommend_style_template_bundle", lambda _profile: None)

    plan = packaging_library.resolve_packaging_plan_for_job(
        "job-1",
        creator_assets=[
            {
                "id": "intro-1",
                "asset_type": "intro",
                "original_name": "intro.mp4",
                "stored_path": intro.as_posix(),
                "metadata_json": {"content_type": "video/mp4"},
                "created_at": "2026-06-14T10:00:00+08:00",
            },
            {
                "id": "outro-1",
                "asset_type": "outro",
                "original_name": "outro.mp4",
                "stored_path": outro.as_posix(),
                "metadata_json": {"content_type": "video/mp4"},
                "created_at": "2026-06-14T10:01:00+08:00",
            },
            {
                "id": "logo-1",
                "asset_type": "logo",
                "original_name": "logo.png",
                "stored_path": logo.as_posix(),
                "metadata_json": {"content_type": "image/png"},
                "created_at": "2026-06-14T10:02:00+08:00",
            },
            {
                "id": "music-1",
                "asset_type": "music_library",
                "original_name": "music.mp3",
                "stored_path": music.as_posix(),
                "metadata_json": {"content_type": "audio/mpeg"},
                "created_at": "2026-06-14T10:03:00+08:00",
            },
        ],
    )

    assert plan["intro"]["path"] == intro.as_posix()
    assert plan["outro"]["path"] == outro.as_posix()
    assert plan["watermark"]["path"] == logo.as_posix()
    assert plan["music"]["path"] == music.as_posix()


def test_packaging_creator_card_inference_requires_same_source_logo(tmp_path: Path) -> None:
    logo = tmp_path / "fas-logo.png"
    logo.write_bytes(b"logo")
    selected_assets = {
        "intro": {"开箱片头a.mp4"},
        "outro": set(),
        "watermark": set(),
        "music": {"背景音乐 cozy_cafe_in_rainy_day_serenade a.mp3"},
    }
    fas_creator = SimpleNamespace(
        assets=[
            SimpleNamespace(asset_type="intro", original_name="开箱片头A.mp4", stored_path=tmp_path / "intro.mp4"),
            SimpleNamespace(asset_type="logo", original_name="FAS.png", stored_path=logo),
        ]
    )
    unrelated_creator = SimpleNamespace(
        assets=[
            SimpleNamespace(asset_type="intro", original_name="开箱片头A.mp4", stored_path=tmp_path / "missing-logo.png"),
        ]
    )

    assert (
        pipeline_steps._score_creator_card_for_selected_packaging_assets(
            fas_creator,
            selected_assets=selected_assets,
        )
        > 0
    )
    assert (
        pipeline_steps._score_creator_card_for_selected_packaging_assets(
            unrelated_creator,
            selected_assets=selected_assets,
        )
        == 0
    )


def test_build_creator_author_profile_uses_creator_card_fields() -> None:
    creator = SimpleNamespace(
        name="FAS",
        positioning="EDC 测评",
        content_domains=["EDC", "工具装备"],
        audience="装备发烧友",
        default_platforms=["bilibili", "douyin"],
        natural_language_profile="克制、可信、结论先行。",
    )

    profile = pipeline_steps._build_creator_author_profile(creator)

    assert profile is not None
    assert profile["display_name"] == "FAS"
    assert profile["creator_profile"]["publishing"]["primary_platform"] == "bilibili"
    assert profile["creator_profile"]["positioning"]["expertise"] == ["EDC", "工具装备"]
