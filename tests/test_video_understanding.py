from roughcut.review.video_understanding import build_video_understanding_payload


def test_build_video_understanding_payload_fuses_profile_and_visual_evidence() -> None:
    payload = build_video_understanding_payload(
        {
            "content_kind": "unboxing",
            "subject_domain": "flashlight",
            "subject_brand": "NITECORE",
            "subject_model": "EDC17",
            "subject_type": "NITECORE EDC17 手电",
            "video_theme": "NITECORE EDC17 开箱与 EDC37 对比",
            "summary": "这期围绕 NITECORE EDC17 的外观、功能和对比体验展开。",
            "hook_line": "EDC17 到底值不值得买？",
            "engagement_question": "你更在意 EDC17 的哪一项体验？",
            "search_queries": ["NITECORE EDC17 EDC37"],
            "visual_semantic_evidence": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
                "visible_brands": ["NITECORE"],
                "visible_models": ["EDC17"],
                "subject_candidates": ["flashlight"],
                "interaction_type": "手持对比展示",
                "scene_context": "室内桌面开箱",
            },
            "content_understanding": {
                "video_type": "unboxing",
                "content_domain": "flashlight",
                "primary_subject": "NITECORE EDC17 手电",
                "evidence_spans": [
                    {"timestamp": "00:00-00:04", "text": "先看 EDC17 到底值不值得买", "type": "hook"},
                    {"timestamp": "00:05-00:11", "text": "这里拿 EDC17 和 EDC37 做对比", "type": "comparison"},
                ],
                "subject_entities": [
                    {"kind": "product", "name": "NITECORE EDC17 手电", "brand": "NITECORE", "model": "EDC17"},
                    {"kind": "comparison_product", "name": "NITECORE EDC37", "brand": "NITECORE", "model": "EDC37"},
                ],
                "confidence": {"overall": 0.83},
                "review_reasons": [],
                "needs_review": False,
            },
        },
        source_name="20260228-152013 奈特科尔 nitecore EDC17开箱以及和edc37的对比.mp4",
        transcript_excerpt="今天看一下 NITECORE EDC17，顺便和 EDC37 做个对比。",
    )

    assert payload["schema_version"] == "video_understanding_v1"
    assert payload["model"]["provider"] == "zhipu"
    assert payload["model"]["model"] == "zai-mcp-server"
    assert payload["model"]["mode"] == "llm_mcp_vision"
    assert payload["global_understanding"]["primary_subject"]["brand"] == "NITECORE"
    assert payload["global_understanding"]["secondary_subjects"][0]["model"] == "EDC37"
    assert payload["automation_hints"]["term_correction_bias"]["allowed_hotwords"][0] == "NITECORE"
    assert payload["segment_understanding"][0]["role"] == "hook"
    assert payload["segment_understanding"][0]["start"] == 0.0
    assert payload["segment_understanding"][1]["role"] == "comparison"
    assert payload["segment_understanding"][1]["keep_priority"] == "high"
    assert "comparison" in payload["automation_hints"]["editing_bias"]["protect_roles"]
    assert payload["review"]["needs_review"] is False


def test_build_video_understanding_payload_promotes_visual_drop_events_to_junk_segments() -> None:
    payload = build_video_understanding_payload(
        {
            "content_kind": "unboxing",
            "subject_domain": "bag",
            "subject_brand": "BOLTBOAT",
            "subject_type": "机能单肩包",
            "visual_semantic_evidence": {
                "provider": "zhipu",
                "model": "zai-mcp-server",
                "mode": "llm_mcp_vision",
                "status": "ready",
                "subject_candidates": ["edc_shoulder_bag"],
                "interaction_type": "上身展示",
                "timeline_events": [
                    {
                        "start": 123.0,
                        "end": 129.0,
                        "role": "junk",
                        "keep_priority": "drop",
                        "summary": "麦克风掉落后弯腰捡起",
                        "reason_tags": ["visual_drop_candidate"],
                        "confidence": 0.82,
                    }
                ],
            },
        },
        source_name="IMG_0185 HSJUN BOLTBOAT 影蚀.MOV",
        transcript_excerpt="我们来看这个包的上身效果。",
    )

    junk_segments = [item for item in payload["segment_understanding"] if item["role"] == "junk"]
    assert junk_segments
    assert junk_segments[0]["keep_priority"] == "drop"
    assert junk_segments[0]["start"] == 123.0
    assert "visual_drop_candidate" in junk_segments[0]["reason_tags"]
