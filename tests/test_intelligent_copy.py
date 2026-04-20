from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from roughcut.review import intelligent_copy as smart_copy_mod
from roughcut.review.intelligent_copy_scoring import score_description, score_title_candidate
from roughcut.review.intelligent_copy_templates import build_platform_description, build_title_candidates


def test_inspect_intelligent_copy_folder_prefers_matching_video_and_cover(tmp_path: Path):
    video = tmp_path / "demo_final.mp4"
    subtitle = tmp_path / "demo_final.srt"
    cover = tmp_path / "demo_final_cover.jpg"
    alt_video = tmp_path / "raw_clip.mp4"
    video.write_bytes(b"x" * 200)
    alt_video.write_bytes(b"x" * 20)
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")
    cover.write_bytes(b"jpg")

    inspected = smart_copy_mod.inspect_intelligent_copy_folder(str(tmp_path))

    assert inspected["video_file"] == str(video.resolve())
    assert inspected["subtitle_file"] == str(subtitle.resolve())
    assert inspected["cover_file"] == str(cover.resolve())
    assert str(alt_video.resolve()) in inspected["extra_video_files"]


@pytest.mark.asyncio
async def test_generate_intelligent_copy_writes_platform_materials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    video = tmp_path / "demo.mp4"
    subtitle = tmp_path / "demo.srt"
    video.write_bytes(b"x" * 200)
    subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n这是一条测试字幕\n", encoding="utf-8")

    async def fake_infer_content_profile(**kwargs):
        return {
            "subject_brand": "RoughCut",
            "subject_model": "Demo",
            "subject_type": "AI 剪辑工具",
            "subject_domain": "ai",
            "video_theme": "智能文案演示",
            "summary": "测试摘要",
            "hook_line": "先看结果",
            "engagement_question": "你会怎么发？",
            "copy_style": kwargs.get("copy_style") or "balanced",
            "cover_title": {"top": "RoughCut", "main": "Demo", "bottom": "先看结果"},
        }

    async def fake_render_platform_cover(**kwargs):
        output_path = kwargs["output_path"]
        output_path.write_bytes(b"cover")

    monkeypatch.setattr(smart_copy_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(smart_copy_mod, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(smart_copy_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    result = await smart_copy_mod.generate_intelligent_copy(str(tmp_path), copy_style="balanced")

    material_dir = tmp_path / smart_copy_mod.MATERIAL_DIR_NAME
    assert result["copy_style"] == "balanced"
    assert Path(result["markdown_path"]).exists()
    assert Path(result["json_path"]).exists()
    assert material_dir.exists()
    assert (material_dir / "01-bilibili-titles.txt").exists()
    assert (material_dir / "01-bilibili-body.txt").exists()
    assert (material_dir / "01-bilibili-tags.txt").exists()
    assert any(item["key"] == "x" and item["has_title"] is False for item in result["platforms"])
    assert any(item["key"] == "kuaishou" and item["has_title"] is False for item in result["platforms"])
    assert any(item["key"] == "wechat_channels" and item["has_title"] is False for item in result["platforms"])
    assert next(item for item in result["platforms"] if item["key"] == "xiaohongshu")["constraints"]["tag_limit"] == 8
    assert next(item for item in result["platforms"] if item["key"] == "kuaishou")["constraints"]["tag_limit"] == 4


@pytest.mark.asyncio
async def test_generate_intelligent_copy_falls_back_when_content_profile_times_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    video = tmp_path / "fallback-demo.mp4"
    subtitle = tmp_path / "fallback-demo.srt"
    video.write_bytes(b"x" * 200)
    subtitle.write_text("1\n00:00:00,000 --> 00:00:02,000\n这是一条回退测试字幕\n", encoding="utf-8")

    async def fake_infer_content_profile(**kwargs):
        raise TimeoutError("content profile timeout")

    async def fake_render_platform_cover(**kwargs):
        kwargs["output_path"].write_bytes(b"cover")

    monkeypatch.setattr(smart_copy_mod, "infer_content_profile", fake_infer_content_profile)
    monkeypatch.setattr(smart_copy_mod, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(smart_copy_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    result = await smart_copy_mod.generate_intelligent_copy(str(tmp_path), copy_style="balanced")

    assert result["content_profile_summary"]["summary"].startswith("这条视频主要围绕")
    assert result["content_profile_summary"]["video_theme"] == "fallback-demo"


@pytest.mark.asyncio
async def test_generate_intelligent_copy_uses_fast_path_for_special_topics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    video = tmp_path / "FAS刀帕伞绳更换和用法.mp4"
    subtitle = tmp_path / "FAS刀帕伞绳更换和用法.srt"
    video.write_bytes(b"x" * 200)
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\n今天给大家简单说一下这个\n\n"
        "2\n00:00:02,000 --> 00:00:04,000\n我们FAS的刀帕是怎么用的\n",
        encoding="utf-8",
    )

    async def fail_infer_content_profile(**kwargs):
        raise AssertionError("fast path should skip infer_content_profile")

    async def fake_render_platform_cover(**kwargs):
        kwargs["output_path"].write_bytes(b"cover")

    monkeypatch.setattr(smart_copy_mod, "infer_content_profile", fail_infer_content_profile)
    monkeypatch.setattr(smart_copy_mod, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(smart_copy_mod, "list_packaging_assets", lambda: {"config": {"copy_style": "attention_grabbing"}})

    result = await smart_copy_mod.generate_intelligent_copy(str(tmp_path), copy_style="balanced")

    assert result["content_profile_summary"]["subject_brand"] == "FAS"
    assert result["content_profile_summary"]["subject_model"] == "刀帕"
    assert result["content_profile_summary"]["subject_type"] == "刀帕收纳配件"


def test_merge_intelligent_copy_profile_hints_detects_decor_subject_from_filename_and_transcript(tmp_path: Path):
    video = tmp_path / "琢匠貔貅.mp4"
    video.write_bytes(b"x")

    profile = smart_copy_mod._merge_intelligent_copy_profile_hints(
        content_profile={},
        video_path=video,
        subtitle_items=[
            {"text_final": "今天来一个重磅开箱"},
            {"text_final": "这次是琢匠的貔貅摆件，紫铜白铜细节我觉得挺有意思"},
        ],
        copy_style="attention_grabbing",
    )

    assert profile["subject_brand"] == "琢匠"
    assert profile["subject_model"] == "貔貅"
    assert profile["subject_type"] == "铜制摆件"
    assert profile["subject_domain"] == "decor"
    assert profile["search_queries"] == ["琢匠 貔貅", "琢匠 貔貅 紫铜 白铜 摆件"]


def test_merge_intelligent_copy_profile_hints_detects_fas_edc_subject_from_filename(tmp_path: Path):
    video = tmp_path / "FAS刀帕伞绳更换和用法.mp4"
    video.write_bytes(b"x")

    profile = smart_copy_mod._merge_intelligent_copy_profile_hints(
        content_profile={"subject_type": "AI创作工具", "cover_title": {"main": "内容待确认"}},
        video_path=video,
        subtitle_items=[
            {"text_final": "今天给大家简单说一下这个"},
            {"text_final": "我们FAS的刀帕是怎么用的"},
        ],
        copy_style="attention_grabbing",
    )

    assert profile["subject_brand"] == "FAS"
    assert profile["subject_model"] == "刀帕"
    assert profile["subject_type"] == "刀帕收纳配件"
    assert profile["subject_domain"] == "accessory"
    assert profile["cover_title"]["main"] == "FAS刀帕"


def test_fast_path_topic_matcher_uses_registry():
    topic = smart_copy_mod.match_intelligent_copy_topic("今天看看琢匠貔貅，紫铜白铜摆件细节到底怎么样")

    assert topic is not None
    assert topic.key == "zhuojiang_pixiu_decor"
    assert topic.subject_type == "铜制摆件"


def test_title_candidates_come_from_template_registry():
    titles = build_title_candidates(
        intent="tutorial",
        topic_subject="FAS刀帕",
        focus_points=["使用方法", "弹力绳固定"],
    )

    assert titles[0] == "FAS刀帕怎么用？使用方法一次讲清"
    assert any("弹力绳固定" in item for item in titles)


def test_platform_description_comes_from_tone_template():
    description = build_platform_description(
        "kuaishou",
        summary="这期主要演示 FAS刀帕怎么包裹固定。",
        question="你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        focus_line="使用方法、弹力绳固定、伞绳和绳扣更换",
    )

    assert description.startswith("这期主要演示 FAS刀帕怎么包裹固定。")
    assert "我就按实话把使用方法、弹力绳固定、伞绳和绳扣更换给你讲清楚。" in description
    assert description.endswith("你会继续用原装弹力绳，还是直接换成伞绳和绳扣？")


def test_title_scoring_prefers_subject_clear_candidates():
    strong = score_title_candidate(
        "FAS刀帕怎么用？使用方法一次讲清",
        topic_subject="FAS刀帕",
        anchor_terms=["FAS", "刀帕", "伞绳"],
        forbidden_terms=["折刀"],
    )
    weak = score_title_candidate(
        "这期重点看什么",
        topic_subject="FAS刀帕",
        anchor_terms=["FAS", "刀帕", "伞绳"],
        forbidden_terms=["折刀"],
    )

    assert strong > weak


def test_description_scoring_penalizes_empty_generic_copy():
    strong = score_description(
        "这期主要演示 FAS刀帕怎么包裹固定。 我就按实话把使用方法、弹力绳固定、伞绳和绳扣更换给你讲清楚。 你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        topic_subject="FAS刀帕",
        anchor_terms=["FAS", "刀帕", "伞绳", "绳扣"],
        question="你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        forbidden_terms=["折刀"],
    )
    weak = score_description(
        "这期重点看一下。欢迎讨论。",
        topic_subject="FAS刀帕",
        anchor_terms=["FAS", "刀帕", "伞绳", "绳扣"],
        question="你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        forbidden_terms=["折刀"],
    )

    assert strong > weak


def test_build_intelligent_copy_packaging_overrides_wrong_theme_terms():
    content_profile = {
        "video_theme": "FAS刀帕使用与伞绳更换教程",
        "hook_line": "FAS刀帕到底怎么包、怎么换绳",
    }
    copy_brief = {
        "topic_subject": "FAS刀帕",
        "intent": "tutorial",
        "summary": "这期主要演示 FAS刀帕怎么包裹固定，顺带讲原装弹力绳和伞绳绳扣怎么更换。",
        "question": "你会继续用原装弹力绳，还是直接换成伞绳和绳扣？",
        "focus_points": ["使用方法", "弹力绳固定", "伞绳和绳扣更换"],
        "tags": ["FAS", "刀帕", "使用教程", "伞绳更换", "绳扣", "EDC收纳"],
        "forbidden_terms": ["折刀", "AI创作工具", "机能包", "手电"],
    }

    refined = smart_copy_mod._build_intelligent_copy_packaging(
        content_profile=content_profile,
        copy_brief=copy_brief,
    )

    xiaohongshu = refined["platforms"]["xiaohongshu"]
    assert xiaohongshu["titles"]
    assert xiaohongshu["titles"][0].startswith("FAS刀帕")
    assert all("折刀" not in item for item in xiaohongshu["titles"])
    assert any("刀帕" in item for item in xiaohongshu["titles"])
    assert "伞绳" in xiaohongshu["description"]
    assert "绳扣" in xiaohongshu["description"]
    assert "折刀" not in xiaohongshu["description"]
    assert "刀帕" in xiaohongshu["tags"]


@pytest.mark.asyncio
async def test_render_platform_cover_skips_overlay_when_existing_cover_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    output_path = tmp_path / "output.jpg"
    video_path = tmp_path / "demo.mp4"
    cover_path = tmp_path / "cover.jpg"
    video_path.write_bytes(b"video")
    cover_path.write_bytes(b"cover")
    overlay_calls: list[tuple] = []
    extract_calls: list[tuple] = []

    def fake_fit_image_to_canvas(**kwargs):
        kwargs["output_path"].write_bytes(b"fitted")

    async def fake_extract_frame(*args, **kwargs):
        extract_calls.append((args, kwargs))

    async def fake_overlay_title_layout(*args, **kwargs):
        overlay_calls.append((args, kwargs))

    monkeypatch.setattr(smart_copy_mod, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(smart_copy_mod, "_extract_frame", fake_extract_frame)
    monkeypatch.setattr(smart_copy_mod, "_overlay_title_layout", fake_overlay_title_layout)

    await smart_copy_mod._render_platform_cover(
        output_path=output_path,
        video_path=video_path,
        existing_cover_path=cover_path,
        title="不应该再叠字",
        rules=smart_copy_mod.PLATFORM_PUBLISH_RULES["xiaohongshu"],
    )

    assert output_path.exists()
    assert overlay_calls == []
    assert extract_calls == []


@pytest.mark.asyncio
async def test_open_folder_reports_file_targets_as_files(client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "cover.jpg"
    target.write_bytes(b"cover")
    calls: list[tuple[str, ...]] = []

    def fake_popen(args):
        calls.append(tuple(args))

    monkeypatch.setattr("roughcut.api.intelligent_copy.subprocess.Popen", fake_popen)

    response = await client.post("/api/v1/intelligent-copy/open-folder", json={"folder_path": str(target)})

    assert response.status_code == 200
    assert response.json()["kind"] == "file"
    assert response.json()["path"] == str(target.resolve())
    assert calls == [("explorer", "/select,", str(target.resolve()))]
