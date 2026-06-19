from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from roughcut.api import intelligent_copy as ic_api
from roughcut.api import jobs as jobs_api
from roughcut import publication
from roughcut.db.models import CreatorCard, CreatorPlatformBinding, CreatorPublicationProfile, Job
from roughcut.db.session import Base
from roughcut.publication_platform_matrix import platform_skips_explicit_visibility_entry


class _FakeSession:
    async def commit(self) -> None:
        return None


@pytest.mark.asyncio
async def test_publish_intelligent_folder_skips_browser_agent_gate_for_social_auto_upload_only(monkeypatch) -> None:
    async def fake_load_inputs(**_kwargs):
        return {
            "job": SimpleNamespace(id="job-1", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"platforms": {"douyin": {}, "wechat-channels": {}}},
            "creator_profile": {"creator_profile": {"publishing": {"platform_credentials": []}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**_kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "job_id": "job-1",
            "creator_profile_id": "creator-1",
            "targets": [
                {"platform": "douyin", "adapter": "social_auto_upload"},
                {"platform": "wechat-channels", "adapter": "social_auto_upload"},
            ],
        }

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": target["platform"]} for target in plan["targets"]]}

    async def fail_agent_ready(**_kwargs):
        raise AssertionError("browser-agent gate should not run for social-auto-upload-only plans")

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda _plan: True)
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(ic_api, "check_publication_browser_agent_ready", fail_agent_ready)
    monkeypatch.setattr(ic_api, "_dispatch_publication_worker_tick", lambda _count: None)

    body = SimpleNamespace(
        folder_path="E:/materials/maxace",
        creator_profile_id="creator-1",
        platforms=["douyin", "wechat-channels"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "submitted"
    assert [item["platform"] for item in result["created_attempts"]] == ["douyin", "wechat-channels"]


@pytest.mark.asyncio
async def test_publish_intelligent_folder_auto_heals_cover_block_before_submit(monkeypatch) -> None:
    load_calls = {"count": 0}
    rerender_calls = []

    async def fake_load_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging_ready = load_calls["count"] > 1
        return {
            "job": SimpleNamespace(id="job-cover", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"ready": packaging_ready},
            "creator_profile": {"id": "creator-1", "display_name": "珍妮斯baby", "creator_profile": {"publishing": {}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        if not kwargs["platform_packaging"].get("ready"):
            return {
                "status": "blocked",
                "publish_ready": False,
                "blocked_reasons": ["平台文案未就绪：封面完整位图标题校验未完成"],
                "warnings": [],
                "targets": [],
            }
        return {
            "status": "ready",
            "publish_ready": True,
            "job_id": "job-cover",
            "creator_profile_id": "creator-1",
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    async def fake_rerender(*args, **kwargs):
        rerender_calls.append({"args": args, "kwargs": kwargs})
        return {"publish_ready": True, "material_contract": {"status": "passed"}}

    async def fake_submit_attempts(_session, plan):
        assert plan["cover_auto_heal"]["status"] == "healed"
        return {"status": "submitted", "created_attempts": [{"platform": "douyin"}]}

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(ic_api, "_dispatch_publication_worker_tick", lambda _count: None)
    monkeypatch.setattr(
        ic_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    body = SimpleNamespace(
        folder_path="E:/materials/bluey",
        creator_profile_id="creator-1",
        platforms=["douyin"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "submitted"
    assert len(rerender_calls) == 1
    assert rerender_calls[0]["kwargs"]["platforms"] == ["douyin"]


@pytest.mark.asyncio
async def test_publish_intelligent_folder_stops_when_cover_auto_heal_is_exhausted(monkeypatch) -> None:
    async def fake_load_inputs(**_kwargs):
        return {
            "job": SimpleNamespace(id="job-cover", status="done"),
            "render_output": SimpleNamespace(output_path="E:/video.mp4"),
            "packaging": {"ready": False},
            "creator_profile": {"id": "creator-1", "display_name": "珍妮斯baby", "creator_profile": {"publishing": {}}},
            "source_video_path": "E:/video.mp4",
        }

    async def fake_resolve_platform_options(**_kwargs):
        return {}

    def fake_build_plan(**_kwargs):
        return {
            "status": "blocked",
            "publish_ready": False,
            "blocked_reasons": ["平台文案未就绪：封面主体与参考图一致性不足"],
            "warnings": [],
            "targets": [],
        }

    async def fake_rerender(*_args, **_kwargs):
        return {"publish_ready": False, "material_contract": {"status": "failed"}}

    async def fail_submit_attempts(*_args, **_kwargs):
        raise AssertionError("cover-blocked plans must not be submitted after exhausted auto-heal")

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    monkeypatch.setattr(ic_api, "_load_intelligent_publish_inputs", fake_load_inputs)
    monkeypatch.setattr(ic_api, "_resolve_intelligent_publish_platform_options", fake_resolve_platform_options)
    monkeypatch.setattr(ic_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(ic_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(ic_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(ic_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(ic_api, "submit_publication_attempts", fail_submit_attempts)
    monkeypatch.setattr(
        ic_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    body = SimpleNamespace(
        folder_path="E:/materials/bluey",
        creator_profile_id="creator-1",
        platforms=["douyin"],
        platform_options=None,
    )

    result = await ic_api.publish_intelligent_folder(body, session=_FakeSession())

    assert result["status"] == "blocked"
    assert result["plan"]["cover_auto_heal"]["status"] == "needs_human"
    assert "封面自愈重试已耗尽" in "；".join(result["blocked_reasons"])


@pytest.mark.asyncio
async def test_publish_job_auto_generates_materials_before_submit(monkeypatch) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    load_calls = {"count": 0}
    generated = {"called": False}

    async def fake_load_publication_inputs(**_kwargs):
        load_calls["count"] += 1
        packaging = None if load_calls["count"] == 1 else {"platforms": {"douyin": {"titles": ["标题"]}}}
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            packaging,
            {"id": "creator-1", "display_name": "珍妮斯baby"},
        )

    async def fake_generate_intelligent_copy(folder_path, **kwargs):
        generated["called"] = True
        assert Path(folder_path) == Path("E:/rendered")
        assert kwargs["platforms"] == ["douyin"]
        return {
            "publish_ready": True,
            "material_dir": "E:/rendered/smart-copy",
            "platform_packaging_json_path": "E:/rendered/smart-copy/_meta/platform-packaging.json",
            "blocking_reasons": [],
        }

    async def fake_list_attempts(*_args, **_kwargs):
        return []

    async def fake_resolve_options(**_kwargs):
        return {}

    def fake_build_plan(**kwargs):
        assert kwargs["platform_packaging"] is not None
        return {
            "status": "ready",
            "publish_ready": True,
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    async def fake_submit_attempts(_session, plan):
        return {"status": "submitted", "created_attempts": [{"platform": plan["targets"][0]["platform"]}]}

    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "generate_intelligent_copy", fake_generate_intelligent_copy)
    monkeypatch.setattr(jobs_api, "list_publication_attempts", fake_list_attempts)
    monkeypatch.setattr(jobs_api, "_resolve_job_publication_platform_options", fake_resolve_options)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(jobs_api, "submit_publication_attempts", fake_submit_attempts)
    monkeypatch.setattr(jobs_api, "_dispatch_publication_worker_tick", lambda _count: None)

    result = await jobs_api.publish_job_to_bound_platforms(
        job_id,
        SimpleNamespace(creator_profile_id="creator-1", platforms=["douyin"], platform_options={}),
        session=_FakeSession(),
    )

    assert generated["called"] is True
    assert result["status"] == "submitted"
    assert result["material_generation"]["source"] == "job_one_click_publish"


def test_job_publication_failed_packaging_needs_regeneration() -> None:
    assert jobs_api._job_publication_packaging_needs_generation(
        {
            "status": "failed",
            "platforms": {"douyin": {"title": "标题"}},
        }
    ) is True
    assert jobs_api._job_publication_packaging_needs_generation(
        {
            "material_contract": {"status": "failed"},
            "platforms": {"douyin": {"title": "标题"}},
        }
    ) is True


@pytest.mark.asyncio
async def test_job_publish_merges_creator_card_publication_bindings() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            creator = CreatorCard(name="珍妮斯baby", status="active")
            session.add(creator)
            await session.flush()
            profile = CreatorPublicationProfile(
                creator_card_id=creator.id,
                status="draft",
                publication_payload_json={},
            )
            session.add(profile)
            await session.flush()
            binding = CreatorPlatformBinding(
                publication_profile_id=profile.id,
                platform="douyin",
                credential_ref="social-auto-upload:creator-janice-douyin:douyin",
                binding_payload_json={
                    "status": "login_confirmed",
                    "enabled": True,
                    "adapter": "social_auto_upload",
                    "account_label": "珍妮斯baby · 抖音",
                    "browser_profile_id": "browser-agent:chrome:janice:douyin",
                    "browser_binding": {"browser": "chrome", "profile_id": "browser-agent:chrome:janice:douyin"},
                },
            )
            session.add(binding)
            await session.flush()

            merged = await jobs_api._merge_job_creator_card_publication_bindings(
                session=session,
                job=Job(creator_card_id=creator.id),
                creator_profile={"id": "avatar-profile", "display_name": "珍妮斯baby", "creator_profile": {}},
            )
    finally:
        await engine.dispose()

    credentials = publication.active_publication_credentials(merged)
    assert [item["platform"] for item in credentials] == ["douyin"]
    assert credentials[0]["status"] == "logged_in"
    assert credentials[0]["adapter"] == "social_auto_upload"
    assert credentials[0]["credential_ref"] == "social-auto-upload:creator-janice-douyin:douyin"


@pytest.mark.asyncio
async def test_job_publication_auto_heals_cover_block_before_submit(monkeypatch) -> None:
    job_id = "11111111-1111-1111-1111-111111111111"
    rerender_calls = []

    async def fake_rerender(folder_path, **kwargs):
        rerender_calls.append({"folder_path": folder_path, "kwargs": kwargs})
        return {"publish_ready": True, "material_contract": {"status": "passed"}}

    async def fake_load_publication_inputs(**_kwargs):
        return (
            SimpleNamespace(id=job_id, status="done", source_path="", output_dir="E:/rendered"),
            SimpleNamespace(output_path="E:/rendered/video.mp4"),
            {"platforms": {"douyin": {"cover_path": "E:/rendered/smart-copy/03-douyin-cover.jpg"}}},
            {"id": "creator-1", "display_name": "珍妮斯baby"},
        )

    def fake_build_plan(**_kwargs):
        return {
            "status": "ready",
            "publish_ready": True,
            "targets": [{"platform": "douyin", "adapter": "social_auto_upload"}],
        }

    monkeypatch.setattr(jobs_api, "rerender_existing_intelligent_copy_cover_groups", fake_rerender)
    monkeypatch.setattr(jobs_api, "_load_publication_inputs", fake_load_publication_inputs)
    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_plan)
    monkeypatch.setattr(jobs_api, "publication_plan_is_publishable", lambda plan: bool(plan.get("publish_ready")))
    monkeypatch.setattr(
        jobs_api,
        "get_settings",
        lambda: SimpleNamespace(publication_cover_auto_heal_enabled=True, publication_cover_auto_heal_max_attempts=1),
    )

    plan, *_rest = await jobs_api._maybe_auto_heal_job_publication_cover_plan(
        plan={
            "status": "blocked",
            "publish_ready": False,
            "blocked_reasons": ["平台文案未就绪：封面当前仅为参考帧占位图，正式生图尚未完成"],
            "warnings": [],
        },
        job=SimpleNamespace(id=job_id, source_path="", output_dir="E:/rendered"),
        render_output=SimpleNamespace(output_path="E:/rendered/video.mp4"),
        packaging=None,
        creator_profile={"id": "creator-1", "display_name": "珍妮斯baby"},
        creator_profile_id="creator-1",
        requested_platforms=["douyin"],
        platform_options={},
        existing_attempts=[],
        session=_FakeSession(),
    )

    assert plan["publish_ready"] is True
    assert plan["cover_auto_heal"]["status"] == "healed"
    assert Path(rerender_calls[0]["folder_path"]) == Path("E:/rendered")
    assert rerender_calls[0]["kwargs"]["platforms"] == ["douyin"]


@pytest.mark.asyncio
async def test_intelligent_publish_merges_creator_card_publication_bindings() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            creator = CreatorCard(name="珍妮斯baby", status="active")
            session.add(creator)
            await session.flush()
            profile = CreatorPublicationProfile(
                creator_card_id=creator.id,
                status="draft",
                publication_payload_json={},
            )
            session.add(profile)
            await session.flush()
            binding = CreatorPlatformBinding(
                publication_profile_id=profile.id,
                platform="bilibili",
                credential_ref="social-auto-upload:creator-janice-bilibili:bilibili",
                binding_payload_json={
                    "status": "login_confirmed",
                    "enabled": True,
                    "adapter": "social_auto_upload",
                    "account_label": "珍妮斯baby · Chrome",
                    "browser_profile_id": "browser-agent:chrome:janice:bilibili",
                    "browser_binding": {"browser": "chrome", "profile_id": "browser-agent:chrome:janice:bilibili"},
                },
            )
            session.add(binding)
            await session.flush()

            merged = await ic_api._merge_creator_card_publication_bindings(
                session=session,
                creator_profile={"id": "avatar-profile", "display_name": "珍妮斯baby", "creator_profile": {}},
                creator_profile_id="avatar-profile",
            )
    finally:
        await engine.dispose()

    credentials = publication.active_publication_credentials(merged)
    assert [item["platform"] for item in credentials] == ["bilibili"]
    assert credentials[0]["status"] == "logged_in"
    assert credentials[0]["adapter"] == "social_auto_upload"
    assert credentials[0]["credential_ref"] == "social-auto-upload:creator-janice-bilibili:bilibili"


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_keeps_compatible_source(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "episode.mp4"
    source_path.write_bytes(b"video")

    async def fake_probe_media(path: Path):
        return SimpleNamespace(
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            pix_fmt="yuv420p",
            format_name="mp4",
        )

    monkeypatch.setattr(ic_api, "probe_media", fake_probe_media)

    resolved = await ic_api._resolve_publish_source_media_path(video_path=source_path)

    assert resolved == source_path.resolve()


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_builds_runtime_copy_for_incompatible_source(tmp_path: Path, monkeypatch) -> None:
    source_path = tmp_path / "episode.mp4"
    source_path.write_bytes(b"source-video")
    runtime_path = ic_api._publication_runtime_target_path(source_path)

    async def fake_probe_media(path: Path):
        if Path(path) == source_path:
            return SimpleNamespace(
                has_video_stream=True,
                has_audio_stream=True,
                video_codec="hevc",
                audio_codec="aac",
                pix_fmt="yuv420p10le",
                format_name="mp4",
            )
        return SimpleNamespace(
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            pix_fmt="yuv420p",
            format_name="mp4",
        )

    async def fake_transcode(**kwargs) -> None:
        target = Path(kwargs["runtime_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"runtime-video")

    monkeypatch.setattr(ic_api, "probe_media", fake_probe_media)
    monkeypatch.setattr(ic_api, "_transcode_publication_runtime_media", fake_transcode)

    resolved = await ic_api._resolve_publish_source_media_path(video_path=source_path)

    assert resolved == runtime_path.resolve()
    assert runtime_path.is_file()


def test_wechat_channels_skips_explicit_visibility_entry() -> None:
    assert platform_skips_explicit_visibility_entry("wechat-channels") is True


def test_publication_plan_option_value_preserves_explicit_blank_override() -> None:
    assert (
        publication._resolve_publication_plan_option_value(
            {"scheduled_publish_at": ""},
            {"scheduled_publish_at": "2026-06-11T20:30"},
            "scheduled_publish_at",
        )
        == ""
    )
