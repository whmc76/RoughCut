from __future__ import annotations

import json
from pathlib import Path

import pytest

from roughcut.review.content_understanding_capabilities import resolve_content_understanding_capabilities
from roughcut.review.content_understanding_visual import infer_visual_semantic_evidence


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_native_route_uses_multimodal_completion_and_parses_json(
    monkeypatch: pytest.MonkeyPatch,
):
    calls: list[str] = []

    async def fake_complete_with_images(prompt, image_paths, **kwargs):
        calls.append("complete_with_images")
        assert image_paths == [Path("frame_01.jpg")]
        assert kwargs["json_mode"] is True
        assert kwargs["max_tokens"] >= 200
        assert "主体物体" in prompt
        assert "操作行为" in prompt
        assert "品牌" in prompt
        assert "型号" in prompt
        assert "背景" in prompt
        assert "EDC" not in prompt
        return json.dumps(
            {
                "provider": "minimax",
                "mode": "native_multimodal",
                "frame_paths": ["frame_01.jpg"],
                "object_categories": ["tool"],
                "visible_brands": ["RoughCut"],
                "visible_models": ["RC-1"],
                "subject_candidates": ["knife"],
                "interaction_type": "handheld",
                "scene_context": "桌面展示",
                "evidence_notes": ["frame 1 shows a branded tool"],
                "frame_level_findings": [{"frame": "frame_01.jpg", "finding": "主体清晰可见"}],
            }
        )

    monkeypatch.setattr("roughcut.review.content_understanding_visual.complete_with_images", fake_complete_with_images)

    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_01.jpg")],
        capabilities={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
    )

    assert calls == ["complete_with_images"]
    assert result["provider"] == "minimax"
    assert result["mode"] == "native_multimodal"
    assert result["status"] == "ready"
    assert result["failure_reason"] == ""
    assert result["frame_paths"] == ["frame_01.jpg"]
    assert result["object_categories"] == ["tool"]
    assert result["visible_brands"] == ["RoughCut"]
    assert result["visible_models"] == ["RC-1"]
    assert result["subject_candidates"] == ["knife"]
    assert result["interaction_type"] == "handheld"
    assert result["scene_context"] == "桌面展示"
    assert result["evidence_notes"] == ["frame 1 shows a branded tool"]
    assert result["frame_level_findings"] == [{"frame": "frame_01.jpg", "finding": "主体清晰可见"}]


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_native_route_degrades_on_malformed_or_empty_json(
    monkeypatch: pytest.MonkeyPatch,
):
    async def fake_complete_with_images(*args, **kwargs):
        return "not json"

    monkeypatch.setattr("roughcut.review.content_understanding_visual.complete_with_images", fake_complete_with_images)

    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_02.jpg")],
        capabilities={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
    )

    assert result["provider"] == "minimax"
    assert result["mode"] == "native_multimodal"
    assert result["status"] == "degraded"
    assert result["failure_reason"] == "visual_parse_failed"
    assert result["frame_paths"] == ["frame_02.jpg"]
    assert result["object_categories"] == []
    assert result["visible_brands"] == []
    assert result["visible_models"] == []
    assert result["subject_candidates"] == []
    assert result["interaction_type"] == ""
    assert result["scene_context"] == ""
    assert result["evidence_notes"] == []


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_dispatches_mcp_mode(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def _infer_with_native_multimodal(*args, **kwargs):
        raise AssertionError("native multimodal route should not be used for MCP capability")

    async def _infer_with_visual_mcp(frame_paths, capabilities):
        calls.append("mcp")
        assert frame_paths == [Path("frame_03.jpg")]
        assert capabilities["visual_understanding"]["mode"] == "visual_mcp"
        return {"route": "mcp"}

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual._infer_with_native_multimodal",
        _infer_with_native_multimodal,
    )
    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual._infer_with_visual_mcp",
        _infer_with_visual_mcp,
    )

    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_03.jpg")],
        capabilities={"visual_understanding": {"provider": "mcp:minimax-vision", "mode": "visual_mcp"}},
    )

    assert result == {"route": "mcp"}
    assert calls == ["mcp"]


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_returns_semantic_shape_for_mcp_route():
    capabilities = resolve_content_understanding_capabilities(
        reasoning_provider="minimax",
        visual_provider="",
        visual_mcp_provider="mcp:minimax-vision",
    )

    assert capabilities["visual_understanding"]["mode"] == "visual_mcp"

    result = await infer_visual_semantic_evidence(frame_paths=[Path("frame_04.jpg")], capabilities=capabilities)

    assert result["mode"] == "mcp"
    assert result["provider"] == "mcp:minimax-vision"
    assert result["frame_paths"] == ["frame_04.jpg"]
    assert result["status"] == "stubbed"
    assert result["failure_reason"] == "visual_mcp_not_implemented"
    assert isinstance(result["object_categories"], list)
    assert isinstance(result["visible_brands"], list)
    assert isinstance(result["visible_models"], list)
    assert isinstance(result["subject_candidates"], list)
    assert isinstance(result["evidence_notes"], list)


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_returns_unavailable_shape_when_capability_missing():
    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_05.jpg")],
        capabilities={"visual_understanding": {"provider": "", "mode": "unavailable"}},
    )

    assert result["mode"] == "unavailable"
    assert result["provider"] == ""
    assert result["status"] == "unavailable"
    assert result["failure_reason"] == "visual_capability_unavailable"
    assert result["frame_paths"] == ["frame_05.jpg"]
