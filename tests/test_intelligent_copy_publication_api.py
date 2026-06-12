from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.api import intelligent_copy as ic_api
from roughcut import publication
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
