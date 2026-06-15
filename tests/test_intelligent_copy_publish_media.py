from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.api import jobs as jobs_api
from roughcut.media.probe import MediaMeta
from roughcut.api import intelligent_copy as intelligent_copy_api


@pytest.mark.asyncio
async def test_job_collection_strategy_applies_one_llm_collection_to_all_target_platforms(monkeypatch) -> None:
    strategy = {
        "mode": "llm_classify",
        "default_collection_name": "EDC刀光火工具集",
        "rules": [
            {
                "collection_name": "EDC潮玩桌搭",
                "natural_language_rule": "适合潮玩、桌搭、把玩件、玩具属性或设计趣味强的 EDC 内容。",
            },
            {
                "collection_name": "EDC刀光火工具集",
                "natural_language_rule": "适合刀具、手电、工具、户外实用装备、EDC 工具属性明确的内容。",
            },
        ],
        "source": "legacy_fas_publication_policy",
    }

    async def fake_classify(collection_strategy, job):
        return "EDC潮玩桌搭", {"source": "llm", "reason": "偏潮玩桌搭内容"}

    monkeypatch.setattr(jobs_api, "_collection_name_from_llm_strategy", fake_classify)

    result = await jobs_api._platform_options_from_job_collection_strategy(
        strategy,
        SimpleNamespace(
            task_brief="MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
            source_name="",
            source_path="",
            output_dir="",
            platform_targets_json=[],
        ),
        ["bilibili", "douyin", "xiaohongshu"],
    )

    assert result["bilibili"]["collection_name"] == "EDC潮玩桌搭"
    assert result["douyin"]["collection_name"] == "EDC潮玩桌搭"
    assert result["xiaohongshu"]["platform_specific_overrides"]["collection_management"]["selected_collection_name"] == "EDC潮玩桌搭"


@pytest.mark.asyncio
async def test_job_collection_strategy_rule_based_mode_uses_formal_rule_result_without_llm(monkeypatch) -> None:
    strategy = {
        "mode": "rule_based",
        "default_collection_name": "EDC刀光火工具集",
        "rules": [
            {
                "collection_name": "EDC潮玩桌搭",
                "natural_language_rule": "适合潮玩、桌搭、把玩件、玩具属性或设计趣味强的 EDC 内容。",
            },
            {
                "collection_name": "EDC刀光火工具集",
                "natural_language_rule": "适合刀具、手电、工具、户外实用装备、EDC 工具属性明确的内容。",
            },
        ],
        "source": "legacy_fas_publication_policy",
    }

    async def fake_classify(collection_strategy, job):
        raise AssertionError("rule_based mode should not call llm classification")

    monkeypatch.setattr(jobs_api, "_collection_name_from_llm_strategy", fake_classify)

    result = await jobs_api._platform_options_from_job_collection_strategy(
        strategy,
        SimpleNamespace(
            task_brief="MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
            source_name="",
            source_path="",
            output_dir="",
            platform_targets_json=[],
        ),
        ["bilibili"],
    )

    assert result["bilibili"]["collection_name"] == "EDC潮玩桌搭"
    assert (
        result["bilibili"]["platform_specific_overrides"]["collection_strategy"]["classification"]["source"]
        == "rule_based"
    )


@pytest.mark.asyncio
async def test_job_collection_strategy_llm_fallback_does_not_emit_platform_options(monkeypatch) -> None:
    strategy = {
        "mode": "llm_classify",
        "default_collection_name": "EDC刀光火工具集",
        "rules": [
            {
                "collection_name": "EDC潮玩桌搭",
                "natural_language_rule": "适合潮玩、桌搭、把玩件、玩具属性或设计趣味强的 EDC 内容。",
            }
        ],
        "source": "legacy_fas_publication_policy",
    }

    async def fake_classify(collection_strategy, job):
        return "EDC潮玩桌搭", {"source": "natural_rule_fallback", "error": "llm_failed"}

    monkeypatch.setattr(jobs_api, "_collection_name_from_llm_strategy", fake_classify)

    result = await jobs_api._platform_options_from_job_collection_strategy(
        strategy,
        SimpleNamespace(
            task_brief="MOT 风灵音叉推牌锆合金版 EDC玩具开箱",
            source_name="",
            source_path="",
            output_dir="",
            platform_targets_json=[],
        ),
        ["bilibili", "douyin"],
    )

    assert result == {}


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_passthrough_when_source_is_compatible(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    async def fake_probe(path: Path) -> MediaMeta:
        return MediaMeta(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="h264",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=source.stat().st_size,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            bit_rate=8_000_000,
            pix_fmt="yuv420p",
            has_video_stream=True,
            has_audio_stream=True,
        )

    monkeypatch.setattr(intelligent_copy_api, "probe_media", fake_probe)

    resolved = await intelligent_copy_api._resolve_publish_source_media_path(video_path=source)

    assert resolved == source.resolve()


@pytest.mark.asyncio
async def test_resolve_publish_source_media_path_rejects_incompatible_source(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")

    async def fake_probe(path: Path) -> MediaMeta:
        return MediaMeta(
            duration=60.0,
            width=1920,
            height=1080,
            fps=30.0,
            video_codec="hevc",
            audio_codec="aac",
            audio_sample_rate=48000,
            audio_channels=2,
            file_size=source.stat().st_size,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            bit_rate=8_000_000,
            pix_fmt="yuv420p10le",
            has_video_stream=True,
            has_audio_stream=True,
        )

    monkeypatch.setattr(intelligent_copy_api, "probe_media", fake_probe)

    with pytest.raises(RuntimeError, match="不满足发布兼容要求"):
        await intelligent_copy_api._resolve_publish_source_media_path(video_path=source)


@pytest.mark.asyncio
async def test_resolve_job_publication_platform_options_derives_scheme_from_job_source_path(monkeypatch) -> None:
    seen: dict[str, object] = {}

    def fake_build_publication_plan(**kwargs):
        seen["build_publication_plan"] = kwargs
        return {
            "targets": [
                {"platform": "douyin", "title": "测试标题"},
            ]
        }

    async def fake_generate_publication_scheme(*, plan, creator_profile, folder_path, browser, force_probe):
        seen["generate_publication_scheme"] = {
            "plan": plan,
            "creator_profile": creator_profile,
            "folder_path": folder_path,
            "browser": browser,
            "force_probe": force_probe,
        }
        return {
            "platform_options": {
                "douyin": {
                    "scheduled_publish_at": "2026-06-05T20:30",
                    "collection_name": "EDC刀光火工具集",
                    "platform_specific_overrides": {
                        "collection_management": {
                            "status": "select_existing",
                            "selected_collection_name": "EDC刀光火工具集",
                        }
                    },
                }
            }
        }

    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_publication_plan)
    monkeypatch.setattr(jobs_api, "generate_publication_scheme", fake_generate_publication_scheme)

    async def fake_empty_profile_options(session, job):
        return {}

    monkeypatch.setattr(jobs_api, "_job_agent_publication_profile_options", fake_empty_profile_options)

    result = await jobs_api._resolve_job_publication_platform_options(
        session=None,
        job=SimpleNamespace(
            source_path=r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱\MAXACE 美杜莎4 顶配次顶配开箱.mp4",
            output_dir=None,
        ),
        render_output=None,
        packaging={"platforms": {"douyin": {"primary_title": "测试标题"}}},
        creator_profile={"id": "creator-1"},
        existing_attempts=[],
        requested_platforms=["douyin"],
        requested_platform_options=None,
    )

    assert result["douyin"]["scheduled_publish_at"] == "2026-06-05T20:30"
    assert result["douyin"]["collection_name"] == "EDC刀光火工具集"
    assert seen["generate_publication_scheme"]["folder_path"] == (
        r"\\Z4pro-gwil\团队文件-媒体工作台\EDC系列\待发布\MAXACE 美杜莎4 顶配次顶配开箱"
    )


@pytest.mark.asyncio
async def test_resolve_job_publication_platform_options_prefers_explicit_options(monkeypatch) -> None:
    async def fake_generate_publication_scheme(**kwargs):
        raise AssertionError("generate_publication_scheme should not be called when explicit options are provided")

    monkeypatch.setattr(jobs_api, "generate_publication_scheme", fake_generate_publication_scheme)

    explicit = {
        "douyin": {
            "scheduled_publish_at": "2026-06-05T21:00",
        }
    }
    result = await jobs_api._resolve_job_publication_platform_options(
        session=None,
        job=SimpleNamespace(source_path="E:/videos/source.mp4", output_dir=None),
        render_output=None,
        packaging={},
        creator_profile={"id": "creator-1"},
        existing_attempts=[],
        requested_platforms=["douyin"],
        requested_platform_options=explicit,
    )

    assert result == explicit


@pytest.mark.asyncio
async def test_resolve_job_publication_platform_options_merges_creator_publication_profile_choices(monkeypatch) -> None:
    def fake_build_publication_plan(**kwargs):
        return {"targets": [{"platform": "bilibili", "title": "测试标题"}]}

    async def fake_generate_publication_scheme(**kwargs):
        return {
            "platform_options": {
                "bilibili": {
                    "scheduled_publish_at": "2026-06-05T20:30",
                    "collection_name": "EDC刀光火工具集",
                    "category": "数码",
                }
            }
        }

    async def fake_profile_options(session, job):
        return {
            "bilibili": {
                "category": "生活兴趣/户外潮流",
                "declaration": "个人观点，仅供参考",
            }
        }

    monkeypatch.setattr(jobs_api, "build_publication_plan", fake_build_publication_plan)
    monkeypatch.setattr(jobs_api, "generate_publication_scheme", fake_generate_publication_scheme)
    monkeypatch.setattr(jobs_api, "_job_agent_publication_profile_options", fake_profile_options)

    result = await jobs_api._resolve_job_publication_platform_options(
        session=None,
        job=SimpleNamespace(source_path="E:/videos/source.mp4", output_dir=None),
        render_output=None,
        packaging={"platforms": {"bilibili": {"primary_title": "测试标题"}}},
        creator_profile={"id": "creator-1"},
        existing_attempts=[],
        requested_platforms=["bilibili"],
        requested_platform_options=None,
    )

    assert result["bilibili"]["scheduled_publish_at"] == "2026-06-05T20:30"
    assert result["bilibili"]["collection_name"] == "EDC刀光火工具集"
    assert result["bilibili"]["category"] == "生活兴趣/户外潮流"
    assert result["bilibili"]["declaration"] == "个人观点，仅供参考"
