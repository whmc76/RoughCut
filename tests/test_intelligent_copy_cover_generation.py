from __future__ import annotations

import json
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


def test_platform_cover_prompt_keeps_title_as_guidance_not_rendered_text() -> None:
    prompt = ic._build_platform_cover_image_prompt(
        title="MOT 风灵音叉推牌 先看细节",
        platform_key="douyin",
        rules=ic.PLATFORM_PUBLISH_RULES["douyin"],
        width=1080,
        height=1920,
    )

    assert "9:16 竖版" in prompt
    assert "标题参考：MOT 风灵音叉推牌 先看细节" in prompt
    assert "不要把标题文字直接画进图片里" in prompt
    assert "抖音" in prompt


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
async def test_render_platform_cover_generates_from_highlight_then_overlays_title(tmp_path, monkeypatch) -> None:
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
    assert calls["overlay"][2] == "tech_showcase"


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
    assert "Codex built-in image_gen" in request["instructions"]
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
        source_image_path=source,
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
    assert "fit" not in calls
    assert "overlay" in calls


@pytest.mark.asyncio
async def test_codex_imagegen_requires_completion_marker_before_publishable_result(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source")
    output = tmp_path / "cover.jpg"
    request_path = tmp_path / "cover.codex-imagegen.json"

    monkeypatch.setattr(
        imagegen,
        "get_settings",
        lambda: SimpleNamespace(intelligent_copy_cover_image_backend="codex_builtin"),
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
