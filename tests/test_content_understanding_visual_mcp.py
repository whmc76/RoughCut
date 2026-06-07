from pathlib import Path

import pytest

from roughcut.providers.zhipu_vision_mcp import VisionMCPAnalysisResult, ZhipuVisionMCPError
from roughcut.review.content_understanding_visual import infer_visual_semantic_evidence


@pytest.mark.asyncio
async def test_llm_mcp_vision_uses_mcp_results_and_merges_frame_evidence(monkeypatch) -> None:
    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        assert prompt
        assert [Path(path) for path in image_paths] == [Path("frame-1.png"), Path("frame-3.png"), Path("frame-4.png")]
        return [
            VisionMCPAnalysisResult(
                image_path="frame-1.png",
                content=(
                    '{"object_categories":["flashlight"],"visible_brands":["NITECORE"],'
                    '"visible_models":["EDC17"],"subject_candidates":["edc_flashlight"],'
                    '"interaction_type":"手持展示","scene_context":"室内桌面",'
                    '"evidence_notes":["主体为小型手电"],'
                    '"frame_level_findings":[{"finding":"主体正面展示","evidence":"logo可见"}]}'
                ),
                raw={},
            ),
            VisionMCPAnalysisResult(
                image_path="frame-2.png",
                content=(
                    '{"object_categories":["flashlight"],"visible_brands":["NITECORE"],'
                    '"visible_models":["EDC17"],"subject_candidates":["flashlight"],'
                    '"interaction_type":"近景对比","scene_context":"室内桌面",'
                    '"evidence_notes":["出现型号字样"],'
                    '"frame_level_findings":[{"finding":"近景细节","evidence":"型号清晰"}]}'
                ),
                raw={},
            ),
        ]

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual.analyze_images_with_mcp",
        fake_analyze_images_with_mcp,
    )

    result = await infer_visual_semantic_evidence(
        [Path("frame-1.png"), Path("frame-2.png"), Path("frame-3.png"), Path("frame-4.png")],
        {
            "visual_understanding": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
            }
        },
    )

    assert result["provider"] == "zhipu"
    assert result["model"] == "zai-mcp-server"
    assert result["mode"] == "llm_mcp_vision"
    assert result["status"] == "ready"
    assert result["object_categories"] == ["flashlight"]
    assert result["visible_brands"] == ["NITECORE"]
    assert result["visible_models"] == ["EDC17"]
    assert result["subject_candidates"] == ["edc_flashlight", "flashlight"]
    assert result["interaction_type"] == "手持展示"
    assert result["scene_context"] == "室内桌面"
    assert len(result["frame_level_findings"]) == 2


@pytest.mark.asyncio
async def test_llm_mcp_vision_degrades_when_mcp_is_unavailable(monkeypatch) -> None:
    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        raise ZhipuVisionMCPError("npx not found")

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual.analyze_images_with_mcp",
        fake_analyze_images_with_mcp,
    )

    result = await infer_visual_semantic_evidence(
        [Path("frame-1.png")],
        {
            "visual_understanding": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
            }
        },
    )

    assert result["status"] == "degraded"
    assert result["failure_reason"] == "vision_mcp_unavailable"
