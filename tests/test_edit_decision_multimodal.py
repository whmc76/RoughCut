from roughcut.edit.decisions import _build_range_evidence, build_edit_decision, infer_timeline_analysis


def _subtitle(text: str, *, start: float, end: float) -> dict:
    return {
        "start_time": start,
        "end_time": end,
        "text_raw": text,
        "text_norm": text,
        "text_final": text,
    }


def _subtitle_timeline() -> list[dict]:
    return [
        _subtitle("先讲结论这个 EDC17 到底值不值", start=0.0, end=1.8),
        _subtitle("这里看细节对比和上手展示", start=2.0, end=5.6),
        _subtitle("你会怎么选欢迎留言", start=5.8, end=7.4),
    ]


def test_multimodal_segment_hints_flow_into_section_actions() -> None:
    subtitle_items = _subtitle_timeline()
    baseline = infer_timeline_analysis(subtitle_items, duration=7.5, content_profile=None)
    guided = infer_timeline_analysis(
        subtitle_items,
        duration=7.5,
        content_profile={
            "video_understanding": {
                "segment_understanding": [
                    {
                        "start": 2.0,
                        "end": 5.6,
                        "role": "detail_showcase",
                        "keep_priority": "high",
                        "confidence": 0.82,
                    }
                ]
            }
        },
    )

    baseline_action = next(action for action in baseline["section_actions"] if float(action["start_sec"]) <= 3.5 <= float(action["end_sec"]))
    guided_action = next(action for action in guided["section_actions"] if float(action["start_sec"]) <= 3.5 <= float(action["end_sec"]))

    assert guided_action["action_priority"] > baseline_action["action_priority"]
    assert guided_action["transition_boost"] > baseline_action["transition_boost"]
    assert "detail_showcase" in guided_action["multimodal_roles"]
    assert guided_action["multimodal_keep_priority"] == "high"


def test_multimodal_keep_hint_protects_range_evidence() -> None:
    subtitle_items = _subtitle_timeline()
    baseline = infer_timeline_analysis(subtitle_items, duration=7.5, content_profile=None)
    guided_profile = {
        "video_understanding": {
            "segment_understanding": [
                {
                    "start": 2.0,
                    "end": 5.6,
                    "role": "comparison",
                    "keep_priority": "high",
                    "confidence": 0.86,
                }
            ]
        }
    }
    guided = infer_timeline_analysis(subtitle_items, duration=7.5, content_profile=guided_profile)

    baseline_evidence = _build_range_evidence(
        2.3,
        4.9,
        subtitle_items=subtitle_items,
        transcript_segments=[],
        content_profile=None,
        timeline_analysis=baseline,
        scene_points=[],
    )
    guided_evidence = _build_range_evidence(
        2.3,
        4.9,
        subtitle_items=subtitle_items,
        transcript_segments=[],
        content_profile=guided_profile,
        timeline_analysis=guided,
        scene_points=[],
    )

    assert guided_evidence.protection_score > baseline_evidence.protection_score
    assert guided_evidence.visual_showcase_score > baseline_evidence.visual_showcase_score
    assert guided_evidence.multimodal_score > 0
    assert guided_evidence.multimodal_keep_priority == "high"
    assert "multimodal_keep_high" in guided_evidence.tags


def test_multimodal_drop_hint_raises_removal_signal() -> None:
    subtitle_items = _subtitle_timeline()
    baseline = infer_timeline_analysis(subtitle_items, duration=7.5, content_profile=None)
    guided_profile = {
        "video_understanding": {
            "segment_understanding": [
                {
                    "start": 2.0,
                    "end": 4.6,
                    "role": "junk",
                    "keep_priority": "drop",
                    "confidence": 0.9,
                }
            ]
        }
    }
    guided = infer_timeline_analysis(subtitle_items, duration=7.5, content_profile=guided_profile)

    baseline_evidence = _build_range_evidence(
        2.1,
        4.2,
        subtitle_items=subtitle_items,
        transcript_segments=[],
        content_profile=None,
        timeline_analysis=baseline,
        scene_points=[],
    )
    guided_evidence = _build_range_evidence(
        2.1,
        4.2,
        subtitle_items=subtitle_items,
        transcript_segments=[],
        content_profile=guided_profile,
        timeline_analysis=guided,
        scene_points=[],
    )

    assert guided_evidence.removal_score > baseline_evidence.removal_score
    assert guided_evidence.retake_score > baseline_evidence.retake_score
    assert guided_evidence.multimodal_keep_priority == "drop"
    assert "multimodal_drop_signal" in guided_evidence.tags


def test_tutorial_timeline_analysis_infers_step_demonstration_strategy() -> None:
    analysis = infer_timeline_analysis(
        [
            _subtitle("先把素材拖进时间线。", start=0.0, end=2.0),
            _subtitle("然后检查每一步操作。", start=2.0, end=5.0),
        ],
        duration=5.0,
        content_profile={
            "workflow_template": "tutorial_standard",
            "content_kind": "tutorial",
            "subject_type": "Premiere 教程",
        },
    )

    assert analysis["strategy_type"] == "step_demonstration"
    assert analysis["strategy_profile"]["strategy_type"] == "step_demonstration"


def test_build_edit_decision_keeps_tutorial_strategy_metadata_for_downstream_steps() -> None:
    decision = build_edit_decision(
        source_path="demo.mp4",
        duration=5.0,
        silence_segments=[],
        subtitle_items=[
            _subtitle("先把素材拖进时间线。", start=0.0, end=2.0),
            _subtitle("然后检查每一步操作。", start=2.0, end=5.0),
        ],
        content_profile={
            "workflow_template": "tutorial_standard",
            "content_kind": "tutorial",
            "subject_type": "Premiere 教程",
        },
    )

    assert decision.analysis["strategy_type"] == "step_demonstration"
    assert decision.analysis["strategy_profile"]["strategy_type"] == "step_demonstration"


def test_build_edit_decision_prefers_confirmed_gameplay_profile_over_stale_content_understanding() -> None:
    decision = build_edit_decision(
        source_path="demo.mp4",
        duration=13.8,
        silence_segments=[],
        subtitle_items=[
            _subtitle("先看这一波关键操作。", start=0.0, end=3.0),
            _subtitle("这里是最值得保留的高光片段。", start=3.1, end=8.2),
            _subtitle("最后再看结尾处理。", start=8.4, end=13.8),
        ],
        content_profile={
            "workflow_template": "gameplay_highlight",
            "content_kind": "gameplay",
            "content_understanding": {"video_type": "unboxing"},
            "product_controls": {
                "effective": {
                    "edit_mode": "highlight",
                    "automation_level": "standard",
                    "material_usage": "all_uploaded",
                }
            },
        },
    )

    assert decision.analysis["strategy_type"] == "event_highlight"
    assert decision.analysis["strategy_profile"]["strategy_type"] == "event_highlight"
