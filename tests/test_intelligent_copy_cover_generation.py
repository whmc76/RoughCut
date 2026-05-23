from __future__ import annotations

import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from roughcut.providers import image_generation as imagegen
from roughcut.providers.image_generation import resolve_image_generation_size
from roughcut.review import intelligent_copy as ic


def test_image_generation_size_uses_closest_supported_orientation() -> None:
    assert resolve_image_generation_size(1280, 720) == "1536x1024"
    assert resolve_image_generation_size(1080, 1920) == "1024x1536"
    assert resolve_image_generation_size(1080, 1440) == "1024x1536"
    assert resolve_image_generation_size(1000, 1000) == "1024x1024"


def test_platform_cover_prompt_requires_image_model_rendered_title() -> None:
    prompt = ic._build_platform_cover_image_prompt(
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
        cover_brief={
            "video_type": "开箱把玩",
            "product_identity": "MOT 风灵音叉推牌",
            "selling_angle": "锆合金质感",
            "visual_brief": "真实手持产品，标题集中醒目。",
        },
    )

    assert "9:16 竖版" in prompt
    assert "封面标题：MOT 风灵音叉推牌 先看细节" in prompt
    assert "视频类型：开箱把玩" in prompt
    assert "主体识别：MOT 风灵音叉推牌" in prompt
    assert "基于参考图生成一张可直接发布的视频封面" in prompt
    assert "风格方案：EDC 电影英雄封面" in prompt
    assert "粗壮 3D 金属字" in prompt
    assert "标题由图片模型直接渲染" in prompt
    assert "上游 LLM 根据视频类型总结提炼" in prompt
    assert "不要改写、扩写或机械套模板" in prompt
    assert "不能散乱、太小、裁切或越界" in prompt
    assert "中央安全区" in prompt
    assert "16:9、4:3、3:4 到 9:16" in prompt
    assert "不要把文字放在左右边缘" in prompt
    assert "两侧只放可裁切的背景氛围" in prompt
    assert "禁止：额外文字、字幕、水印" in prompt
    assert "抖音" in prompt


def test_official_edc_cover_style_can_be_selected_explicitly_without_edc_keywords() -> None:
    prompt = ic._build_platform_cover_image_prompt(
        title="核心结构 看这里",
        platform_key="bilibili",
        rules={
            **ic.PLATFORM_PUBLISH_RULES["bilibili"],
            "cover_style": ic.OFFICIAL_COVER_STYLE_EDC_CINEMATIC_HERO,
        },
        width=1600,
        height=900,
        cover_brief={"product_identity": "普通工具", "visual_brief": "真实手持产品。"},
    )

    assert "风格方案：EDC 电影英雄封面" in prompt
    assert "产品是英雄物件" in prompt


def test_platform_cover_title_never_falls_back_to_body_copy() -> None:
    material = {
        "primary_title": "",
        "body": "这个版本的正文很长，适合发布描述，但绝对不能被拆成封面三行小字，否则手机端会越界也会显得很乱。",
    }
    packaging = {
        "highlights": {
            "title_hook": "先看质感",
            "strongest_selling_point": "锆合金版本",
            "product": "MOT 风灵音叉推牌",
        }
    }

    title = ic._resolve_platform_cover_title(
        material=material,
        packaging=packaging,
        content_profile={},
    )

    assert title == "MOT风灵 锆合金推牌 开箱"
    assert "正文" not in title


def test_cover_group_title_prefers_compact_product_title_over_long_copy() -> None:
    title = ic._resolve_cover_group_title(
        packaging={
            "highlights": {
                "product": "MOT 风灵音叉推牌 锆合金版本",
                "title_hook": "先被质感吸引，再看它是不是你会留下的小物",
                "strongest_selling_point": "锆合金版本",
            }
        },
        content_profile={
            "subject_model": "MOT 风灵音叉推牌 锆合金版本",
            "cover_title": {"main": "MOT 风灵音叉推牌 锆合金版本"},
        },
    )

    assert title == "MOT风灵 锆合金推牌 开箱"


def test_cover_brief_title_preserves_brand_identity_when_llm_omits_it() -> None:
    brief = ic._normalize_cover_brief_payload(
        {
            "cover_title": "锆合金推牌，手感绝了",
            "video_type": "开箱体验",
            "product_identity": "MOT风灵音叉推牌锆合金版",
            "selling_angle": "锆合金仿皮革纹理的丝滑手感",
        },
        fallback={"cover_title": "MOT风灵 锆合金推牌 开箱"},
    )

    assert brief["strategy_source"] == "llm"
    assert brief["cover_title"].startswith("MOT风灵 ")
    assert "锆合金推牌" in brief["cover_title"]


@pytest.mark.asyncio
async def test_intelligent_cover_brief_uses_llm_summary_instead_of_fixed_format(monkeypatch) -> None:
    calls: dict[str, object] = {}

    class FakeResponse:
        def as_json(self):
            return {
                "cover_title": "风灵推牌 太好玩",
                "video_type": "开箱把玩",
                "product_identity": "MOT 风灵音叉推牌",
                "selling_angle": "锆合金质感和把玩反馈",
                "visual_brief": "产品大、手部真实、标题集中醒目。",
                "avoid": "不要长句和额外文字。",
            }

    class FakeProvider:
        async def complete(self, messages, **kwargs):
            calls["prompt"] = messages[-1].content
            calls["json_mode"] = kwargs.get("json_mode")
            return FakeResponse()

    monkeypatch.setattr(ic, "get_reasoning_provider", lambda: FakeProvider())
    monkeypatch.setattr(ic, "llm_task_route", lambda *args, **kwargs: nullcontext())

    brief = await ic._build_intelligent_cover_brief(
        video_path=Path("MOT 风灵音叉推牌 锆合金版本.mp4"),
        subtitle_items=[{"text_final": "今天开箱这个锆合金版本，拿到手第一感觉就是质感很扎实。"}],
        content_profile={"subject_model": "MOT 风灵音叉推牌 锆合金版本"},
        copy_brief={"topic_subject": "MOT 风灵音叉推牌", "intent": "unboxing"},
        packaging={"highlights": {"product": "MOT 风灵音叉推牌", "title_hook": "先看质感"}},
    )

    assert brief["strategy_source"] == "llm"
    assert brief["cover_title"] == "风灵推牌 太好玩"
    assert brief["video_type"] == "开箱把玩"
    assert calls["json_mode"] is True
    assert "不要套固定模板" in str(calls["prompt"])


def test_intelligent_copy_subject_identity_falls_back_to_video_stem() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity({}, Path("MOT 风灵音叉推牌 锆合金版本.mp4"))

    assert profile["subject_model"] == "MOT 风灵音叉推牌 锆合金版本"
    assert profile["search_queries"] == ["MOT 风灵音叉推牌 锆合金版本"]


def test_intelligent_copy_subject_identity_replaces_generic_model() -> None:
    profile = ic._ensure_intelligent_copy_subject_identity(
        {"subject_model": "产品", "summary": "已有摘要"},
        Path("MOT 风灵音叉推牌 锆合金版本.mp4"),
    )

    assert profile["subject_model"] == "MOT 风灵音叉推牌 锆合金版本"
    assert profile["summary"] == "已有摘要"


@pytest.mark.asyncio
async def test_highlight_selection_uses_one_numbered_contact_sheet(tmp_path, monkeypatch) -> None:
    preview_paths: list[Path] = []
    for index in range(4):
        path = tmp_path / f"candidate-{index}.jpg"
        path.write_bytes(b"preview")
        preview_paths.append(path)
    candidates = [{"seek": float(index), "preview": path} for index, path in enumerate(preview_paths)]
    sheet_path = tmp_path / "sheet.jpg"
    calls: dict[str, object] = {}

    def fake_build_contact_sheet(paths, *, output_path=None):
        calls["sheet_paths"] = list(paths)
        calls["sheet_output_path"] = output_path
        sheet_path.write_bytes(b"sheet")
        return sheet_path

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        calls["prompt"] = prompt
        calls["image_paths"] = list(image_paths)
        return '{"best_number":3,"score":0.87,"reason":"主体最大"}'

    monkeypatch.setattr(ic, "_build_numbered_highlight_contact_sheet", fake_build_contact_sheet)
    monkeypatch.setattr(ic, "complete_with_images", fake_complete_with_images)

    selected = await ic._select_intelligent_copy_highlight_candidate(
        candidates,
        content_profile={"summary": "MOT 风灵音叉推牌开箱"},
        packaging={"highlights": {"title_hook": "先看细节"}},
        contact_sheet_output_path=sheet_path,
    )

    assert selected["index"] == 2
    assert selected["source"] == "llm_contact_sheet_rank"
    assert selected["contact_sheet_path"] == str(sheet_path)
    assert calls["sheet_paths"] == preview_paths
    assert calls["sheet_output_path"] == sheet_path
    assert calls["image_paths"] == [sheet_path]
    assert "1-based 序号" in calls["prompt"]


@pytest.mark.asyncio
async def test_render_platform_cover_generates_final_titled_cover_with_image_model(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            ffmpeg_timeout_sec=1,
        ),
    )

    async def fake_generate_edited_cover_image(**kwargs):
        calls["generate"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"generated")
        return {"model": "image2", "size": "1024x1536"}

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "generate_edited_cover_image", fake_generate_edited_cover_image)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert output.exists()
    assert metadata["source"] == "image_generation"
    assert metadata["target_size"] == {"width": 1080, "height": 1920}
    assert calls["generate"]["source_image_path"].name == "base.jpg"
    assert calls["generate"]["width"] == 1080
    assert calls["generate"]["height"] == 1920
    assert calls["fit"]["fit_mode"] == "cover"
    assert "overlay" not in calls


@pytest.mark.asyncio
async def test_platform_cover_group_reuses_one_generated_cover_for_same_class(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    cache: dict[str, dict[str, object]] = {}
    render_calls: list[dict[str, object]] = []
    fit_calls: list[dict[str, object]] = []

    async def fake_render_platform_cover(**kwargs):
        render_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"group cover")
        return {
            "source": "image_generation",
            "platform": kwargs["platform_key"],
            "target_size": {"width": 1600, "height": 900},
            "publish_ready": True,
            "blocking_reasons": [],
            "image_generation": {"backend": "codex_builtin", "status": "completed"},
        }

    def fake_fit_image_to_canvas(**kwargs):
        fit_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"platform cover")

    monkeypatch.setattr(ic, "_render_platform_cover", fake_render_platform_cover)
    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)

    bilibili_group = ic._resolve_platform_cover_group(
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
    )
    youtube_group = ic._resolve_platform_cover_group(
        platform_key="youtube",
        rules=ic.PLATFORM_PUBLISH_RULES["youtube"],
    )

    bilibili = await ic._render_or_reuse_platform_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "01-bilibili-cover.jpg",
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT风灵 锆合金",
        platform_key="bilibili",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_group=bilibili_group,
    )
    youtube = await ic._render_or_reuse_platform_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "07-youtube-cover.jpg",
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT风灵 锆合金",
        platform_key="youtube",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["youtube"],
        cover_group=youtube_group,
    )

    assert len(render_calls) == 1
    assert render_calls[0]["output_path"] == tmp_path / "00-cover-landscape_16_9.jpg"
    assert bilibili["cover_group"]["key"] == "landscape_16_9"
    assert youtube["cover_group"]["key"] == "landscape_16_9"
    assert bilibili["publish_ready"] is True
    assert youtube["publish_ready"] is True
    assert len(fit_calls) == 2


def test_existing_cover_option_reuses_detected_cover_without_imagegen(tmp_path, monkeypatch) -> None:
    existing = tmp_path / "existing-cover.jpg"
    existing.write_bytes(b"existing")
    cache: dict[str, dict[str, object]] = {}
    fit_calls: list[dict[str, object]] = []

    def fake_fit_image_to_canvas(**kwargs):
        fit_calls.append(kwargs)
        Path(kwargs["output_path"]).write_bytes(b"fit")

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    cover_group = ic._resolve_platform_cover_group(
        platform_key="bilibili",
        rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
    )

    metadata = ic._render_or_reuse_existing_cover_group(
        cache=cache,
        material_dir=tmp_path,
        output_path=tmp_path / "01-bilibili-cover.jpg",
        existing_cover_path=existing,
        platform_key="bilibili",
        platform_rules=ic.PLATFORM_PUBLISH_RULES["bilibili"],
        cover_group=cover_group,
    )

    assert metadata["source"] == "cover_group_reuse"
    assert metadata["publish_ready"] is True
    assert metadata["image_generation"] is None
    assert fit_calls[0]["source_path"] == existing
    assert fit_calls[0]["output_path"] == tmp_path / "00-cover-landscape_16_9.jpg"


@pytest.mark.asyncio
async def test_render_platform_cover_writes_codex_imagegen_request_when_builtin_backend_pending(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        ic,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_generation_enabled=True,
            intelligent_copy_cover_image_backend="codex_builtin",
            ffmpeg_timeout_sec=1,
        ),
    )

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs
        Path(kwargs["output_path"]).write_bytes(b"fit")

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=source,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    image_generation = metadata["image_generation"]
    request_path = Path(image_generation["request_path"])
    request = json.loads(request_path.read_text(encoding="utf-8"))

    assert metadata["source"] == "video_highlight"
    assert metadata["publish_ready"] is False
    assert image_generation["status"] == "pending_codex_imagegen"
    assert image_generation["backend"] == "codex_builtin"
    assert request_path.exists()
    assert Path(image_generation["source_image_path"]).exists()
    assert Path(request["output_path"]) == output
    assert image_generation["image_model"] == "codex_builtin_image_generation"
    assert request["image_generation"]["image_model"] == "codex_builtin_image_generation"
    assert request["codex_runner"]["role"] == "codex_exec_agent"
    assert request["codex_runner"]["model"] == "gpt-5.4-mini"
    assert request["codex_runner"]["reasoning_effort"] == "low"
    assert "Codex built-in image_gen" in request["instructions"]
    assert "not as the underlying image model" in request["instructions"]
    assert "concise image-generation brief" in request["instructions"]
    assert request["cover_director_policy"]["codex_role"] == "write_clear_image_generation_brief"
    assert request["cover_director_policy"]["typography_owner"] == "image_model"
    assert any(
        "center safe area" in item
        for item in request["cover_director_policy"]["completion_requires"]
    )
    assert "fit" not in calls
    assert not output.exists()


@pytest.mark.asyncio
async def test_render_platform_cover_preserves_completed_codex_output(tmp_path, monkeypatch) -> None:
    source = tmp_path / "highlight.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "douyin-cover.jpg"
    output.write_bytes(b"completed cover")
    request_path = tmp_path / "douyin-cover.codex-imagegen.json"
    request_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "backend": "codex_builtin",
                "created_at": "2026-05-20T00:00:00+00:00",
                "source_image_path": str(source),
                "output_path": str(output),
                "target_size": {"width": 1080, "height": 1920},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: dict[str, object] = {}
    settings = SimpleNamespace(
        intelligent_copy_cover_image_generation_enabled=True,
        intelligent_copy_cover_image_backend="codex_builtin",
        ffmpeg_timeout_sec=1,
    )

    monkeypatch.setattr(ic, "get_settings", lambda: settings)
    monkeypatch.setattr(imagegen, "get_settings", lambda: settings)
    monkeypatch.setattr(
        ic,
        "assess_cover_publish_readiness",
        lambda metadata, request, path: {
            "publish_ready": True,
            "blocking_reasons": [],
            "warnings": [],
            "output_path": str(path),
        },
    )

    def fake_fit_image_to_canvas(**kwargs):
        calls["fit"] = kwargs

    async def fake_overlay_title_layout(*args):
        calls["overlay"] = args

    monkeypatch.setattr(ic, "_fit_image_to_canvas", fake_fit_image_to_canvas)
    monkeypatch.setattr(ic, "_overlay_title_layout", fake_overlay_title_layout)

    metadata = await ic._render_platform_cover(
        output_path=output,
        video_path=tmp_path / "video.mp4",
        source_image_path=None,
        existing_cover_path=None,
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
    )

    assert output.exists()
    assert output.read_bytes() == b"completed cover"
    assert metadata["source"] == "image_generation"
    assert metadata["publish_ready"] is True
    assert metadata["image_generation"]["status"] == "completed"
    assert "fit" in calls
    assert calls["fit"]["output_path"] == output
    assert calls["fit"]["fit_mode"] == "cover"
    assert "overlay" not in calls


@pytest.mark.asyncio
async def test_codex_imagegen_requires_completion_marker_before_publishable_result(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(
            intelligent_copy_cover_image_backend="codex_builtin",
            intelligent_copy_cover_codex_runner_model="gpt-5.4-mini",
            intelligent_copy_cover_codex_runner_effort="low",
        ),
    )

    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    output.write_bytes(b"generated")
    with pytest.raises(imagegen.CodexImageGenerationPending):
        await imagegen.generate_edited_cover_image(
            source_image_path=source,
            output_path=output,
            final_output_path=output,
            request_path=request_path,
            prompt="生成封面",
            width=1280,
            height=720,
        )

    imagegen.mark_codex_imagegen_request_completed(request_path=request_path, output_path=output)
    metadata = await imagegen.generate_edited_cover_image(
        source_image_path=source,
        output_path=output,
        final_output_path=output,
        request_path=request_path,
        prompt="生成封面",
        width=1280,
        height=720,
    )

    assert metadata["status"] == "completed"
    assert metadata["backend"] == "codex_builtin"
    assert metadata["image_model"] == "codex_builtin_image_generation"
    assert metadata["codex_runner"]["model"] == "gpt-5.4-mini"
    assert metadata["codex_runner"]["reasoning_effort"] == "low"
