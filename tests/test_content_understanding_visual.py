from __future__ import annotations

from pathlib import Path

import pytest

from roughcut.review.content_understanding_visual import infer_visual_semantic_evidence


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_dispatches_native_multimodal_mode(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def _infer_with_native_multimodal(frame_paths, capabilities):
        calls.append("native_multimodal")
        assert frame_paths == [Path("frame_01.jpg")]
        assert capabilities["visual_understanding"]["mode"] == "native_multimodal"
        return {"route": "native_multimodal"}

    async def _infer_with_visual_mcp(*args, **kwargs):
        raise AssertionError("visual MCP route should not be used for native multimodal capability")

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual._infer_with_native_multimodal",
        _infer_with_native_multimodal,
    )
    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual._infer_with_visual_mcp",
        _infer_with_visual_mcp,
    )

    result = await infer_visual_semantic_evidence(
        frame_paths=[Path("frame_01.jpg")],
        capabilities={"visual_understanding": {"provider": "minimax", "mode": "native_multimodal"}},
    )

    assert result == {"route": "native_multimodal"}
    assert calls == ["native_multimodal"]


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_dispatches_mcp_mode(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    async def _infer_with_native_multimodal(*args, **kwargs):
        raise AssertionError("native multimodal route should not be used for MCP capability")

    async def _infer_with_visual_mcp(frame_paths, capabilities):
        calls.append("mcp")
        assert frame_paths == [Path("frame_02.jpg")]
        assert capabilities["visual_understanding"]["mode"] == "mcp"
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
        frame_paths=[Path("frame_02.jpg")],
        capabilities={"visual_understanding": {"provider": "mcp:minimax-vision", "mode": "mcp"}},
    )

    assert result == {"route": "mcp"}
    assert calls == ["mcp"]


@pytest.mark.asyncio
async def test_infer_visual_semantic_evidence_returns_empty_result_when_unavailable(monkeypatch: pytest.MonkeyPatch):
    async def _infer_with_native_multimodal(*args, **kwargs):
        raise AssertionError("native multimodal route should not be used when visual understanding is unavailable")

    async def _infer_with_visual_mcp(*args, **kwargs):
        raise AssertionError("visual MCP route should not be used when visual understanding is unavailable")

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
        capabilities={"visual_understanding": {"provider": "", "mode": "unavailable"}},
    )

    assert result == {}
