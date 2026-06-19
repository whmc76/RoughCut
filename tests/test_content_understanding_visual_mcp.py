from pathlib import Path

import pytest

from roughcut.providers.zhipu_vision_mcp import VisionMCPAnalysisResult, ZhipuVisionMCPError
from roughcut.review.content_profile import _build_asr_guided_visual_probe_windows
from roughcut.review.content_understanding_visual import _sample_frame_paths, infer_visual_semantic_evidence


def test_sample_frame_paths_keeps_video_scan_budget_bounded() -> None:
    frames = [Path(f"profile_{index:02d}_t{index:05d}p00.jpg") for index in range(24)]

    sampled = _sample_frame_paths(frames)

    assert len(sampled) == 8
    assert sampled[0] == frames[0]
    assert sampled[-1] == frames[-1]


def test_sample_frame_paths_prioritizes_asr_targeted_probe_frames() -> None:
    target_frames = [Path(f"target_asr_retake_or_accident_{index:02d}_t00100p00.jpg") for index in range(3)]
    background_frames = [Path(f"profile_{index:02d}_t{index:05d}p00.jpg") for index in range(24)]

    sampled = _sample_frame_paths([*target_frames, *background_frames], max_count=8)

    assert sampled[:3] == target_frames
    assert len(sampled) == 8
    assert any(path.name.startswith("profile_") for path in sampled)


def test_asr_guided_visual_probe_windows_find_retake_and_long_silence() -> None:
    windows = _build_asr_guided_visual_probe_windows(
        [
            {"start_time": 0.0, "end_time": 2.0, "text_final": "这里正常展示包的肩带"},
            {"start_time": 6.0, "end_time": 7.0, "text_final": "继续看这个外袋容量"},
            {"start_time": 14.5, "end_time": 15.5, "text_final": "等一下麦克风掉了我捡一下"},
        ],
        duration=20.0,
    )

    reasons = [item["reason"] for item in windows]
    assert "asr_retake_or_accident" in reasons
    assert "long_silence_gap" in reasons
    retake_window = next(item for item in windows if item["reason"] == "asr_retake_or_accident")
    assert retake_window["start"] <= 14.5
    assert retake_window["end"] >= 15.5


def test_asr_guided_visual_probe_windows_find_failed_demo_retries() -> None:
    windows = _build_asr_guided_visual_probe_windows(
        [
            {"start_time": 0.0, "end_time": 1.0, "text_final": "我试一下这个快拆扣"},
            {"start_time": 1.2, "end_time": 2.2, "text_final": "这里没扣上好像有点卡住"},
            {"start_time": 2.6, "end_time": 3.4, "text_final": "再试一下"},
            {"start_time": 3.8, "end_time": 5.4, "text_final": "这样就很轻松扣上到位了"},
        ],
        duration=8.0,
    )

    failed_demo = next(item for item in windows if item["reason"] == "asr_repeated_failed_demo")
    assert failed_demo["start"] <= 0.1
    assert failed_demo["end"] >= 5.4


def test_asr_guided_visual_probe_windows_find_progressive_line_retake() -> None:
    windows = _build_asr_guided_visual_probe_windows(
        [
            {"start_time": 0.0, "end_time": 0.8, "text_final": "这个前置快开"},
            {"start_time": 1.0, "end_time": 1.9, "text_final": "这个前置快开其实"},
            {"start_time": 2.1, "end_time": 4.0, "text_final": "这个前置快开其实是最爽的一个开法"},
        ],
        duration=6.0,
    )

    retake = next(item for item in windows if item["reason"] == "asr_progressive_line_retake")
    assert retake["start"] == 0.0
    assert retake["end"] >= 4.0


def test_asr_guided_visual_probe_windows_find_self_correction_retake() -> None:
    windows = _build_asr_guided_visual_probe_windows(
        [
            {"start_time": 719.129, "end_time": 721.408, "text_final": "拇指这还有个弹"},
            {"start_time": 721.408, "end_time": 725.508, "text_final": "开啊 就是你用这个指甲直接去"},
            {"start_time": 725.508, "end_time": 727.786, "text_final": "你用指甲卡住"},
            {"start_time": 727.786, "end_time": 730.064, "text_final": "这个大拇指的这个"},
            {"start_time": 730.064, "end_time": 733.254, "text_final": "不是 你用大拇指的指甲去卡"},
        ],
        duration=740.0,
    )

    retake = next(item for item in windows if item["reason"] == "asr_progressive_line_retake")
    assert retake["start"] <= 719.129
    assert retake["end"] >= 733.254


@pytest.mark.asyncio
async def test_llm_mcp_vision_uses_mcp_results_and_merges_frame_evidence(monkeypatch) -> None:
    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        assert prompt
        assert [Path(path) for path in image_paths] == [Path("frame-1.png"), Path("frame-2.png"), Path("frame-3.png"), Path("frame-4.png")]
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
async def test_llm_mcp_vision_turns_accidental_mic_drop_into_timed_drop_event(monkeypatch) -> None:
    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        assert "麦克风" in prompt
        return [
            VisionMCPAnalysisResult(
                image_path="profile_04_t00123p40.jpg",
                content=(
                    '{"object_categories":["shoulder_bag"],"visible_brands":["BOLTBOAT"],'
                    '"visible_models":[],"subject_candidates":["edc_shoulder_bag"],'
                    '"interaction_type":"人物弯腰捡起掉落的麦克风","scene_context":"户外口播展示",'
                    '"evidence_notes":["麦克风从衣领处脱落，人物暂停展示去捡起"],'
                    '"frame_level_findings":[{"finding":"麦克风掉落后弯腰捡起","evidence":"手离开包去处理收音设备"}],'
                    '"timeline_events":[{"role":"junk","keep_priority":"drop","summary":"麦克风掉落并捡起","start_sec":123.4,"end_sec":128.0}]}'
                ),
                raw={},
            )
        ]

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual.analyze_images_with_mcp",
        fake_analyze_images_with_mcp,
    )

    result = await infer_visual_semantic_evidence(
        [Path("profile_04_t00123p40.jpg")],
        {
            "visual_understanding": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
            }
        },
    )

    assert result["timeline_events"]
    event = result["timeline_events"][0]
    assert event["role"] == "junk"
    assert event["keep_priority"] == "drop"
    assert event["start"] <= 123.4
    assert event["end"] >= 128.0


@pytest.mark.asyncio
async def test_llm_mcp_vision_prefers_video_timeline_events_when_source_is_available(monkeypatch) -> None:
    async def fake_analyze_video_with_mcp(video_path, *, prompt, timeout_sec=180):
        assert Path(video_path) == Path("boltboat.mov")
        assert "时间轴事件" in prompt
        return VisionMCPAnalysisResult(
            image_path=str(video_path),
            content=(
                '{"object_categories":["shoulder_bag"],"visible_brands":["BOLTBOAT"],'
                '"visible_models":[],"subject_candidates":["edc_shoulder_bag"],'
                '"interaction_type":"上身展示","scene_context":"户外口播",'
                '"evidence_notes":["中段出现收音设备事故"],'
                '"frame_level_findings":[],'
                '"timeline_events":[{"role":"junk","keep_priority":"drop","summary":"麦克风脱落，人物暂停捡起",'
                '"start_sec":302.0,"end_sec":309.5,"confidence":0.86}]}'
            ),
            raw={},
        )

    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        raise AssertionError("image fallback should not be used when video analysis returns a payload")

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual.analyze_video_with_mcp",
        fake_analyze_video_with_mcp,
    )
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
        source_path=Path("boltboat.mov"),
    )

    assert result["timeline_events"][0]["role"] == "junk"
    assert result["timeline_events"][0]["keep_priority"] == "drop"
    assert result["timeline_events"][0]["start"] <= 302.0


@pytest.mark.asyncio
async def test_llm_mcp_vision_rejects_unsupported_visual_drop_labels(monkeypatch) -> None:
    async def fake_analyze_images_with_mcp(image_paths, *, prompt, timeout_sec=90):
        return [
            VisionMCPAnalysisResult(
                image_path="profile_03_t00291p77.jpg",
                content=(
                    '{"object_categories":["shoulder_bag"],"visible_brands":["BOLTBOAT"],'
                    '"visible_models":[],"subject_candidates":["edc_shoulder_bag"],'
                    '"interaction_type":"正常上身展示","scene_context":"户外口播",'
                    '"evidence_notes":["人物正常站立展示包"],'
                    '"frame_level_findings":[],'
                    '"timeline_events":[{"role":"junk","keep_priority":"drop","summary":"person is standing upright",'
                    '"evidence":"no bending or exiting the frame","start_sec":291.0,"end_sec":297.0}]}'
                ),
                raw={},
            )
        ]

    monkeypatch.setattr(
        "roughcut.review.content_understanding_visual.analyze_images_with_mcp",
        fake_analyze_images_with_mcp,
    )

    result = await infer_visual_semantic_evidence(
        [Path("profile_03_t00291p77.jpg")],
        {
            "visual_understanding": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
            }
        },
    )

    event = result["timeline_events"][0]
    assert event["role"] == "body"
    assert event["keep_priority"] == "medium"


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
