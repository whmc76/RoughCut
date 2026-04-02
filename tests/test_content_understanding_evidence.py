from __future__ import annotations

from roughcut.review.content_understanding_evidence import build_evidence_bundle, normalize_evidence_bundle


def test_normalize_evidence_bundle_keeps_visual_semantic_evidence_separate_from_hint_fields():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "visual_semantic_evidence": {"object_categories": ["backpack"]},
            "visual_hints": {"subject_type": "EDC机能包"},
        }
    )

    assert bundle["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert bundle["ocr_semantic_evidence"] == {}
    assert bundle["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"
    assert "visual_semantic_evidence" not in bundle["candidate_hints"]


def test_normalize_evidence_bundle_builds_primary_evidence_graph_sections():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "transcript_excerpt": "这是 HSJUN 的包",
            "visual_semantic_evidence": {"object_categories": ["backpack"]},
            "visible_text": "BOLTBOAT",
            "ocr_profile": {"visible_text": "BOLTBOAT"},
        }
    )

    assert bundle["audio_semantic_evidence"]["transcript_text"] == "这是 HSJUN 的包"
    assert bundle["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert bundle["ocr_semantic_evidence"]["visible_text"] == "BOLTBOAT"


def test_normalize_evidence_bundle_does_not_promote_visual_hint_text_into_ocr_semantic_evidence():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "visual_hints": {"visible_text": "VISUAL ONLY"},
            "ocr_profile": {},
        }
    )

    assert bundle["visible_text"] == "VISUAL ONLY"
    assert bundle["ocr_semantic_evidence"] == {}


def test_normalize_evidence_bundle_does_not_treat_standalone_visible_text_as_ocr_evidence():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "visible_text": "TOP LEVEL ONLY",
            "ocr_profile": {},
        }
    )

    assert bundle["visible_text"] == "TOP LEVEL ONLY"
    assert bundle["ocr_semantic_evidence"] == {}


def test_normalize_evidence_bundle_preserves_ocr_profile_scalar_types():
    bundle = normalize_evidence_bundle(
        {
            "source_name": "demo.mp4",
            "ocr_profile": {
                "visible_text": "BOLTBOAT",
                "available": True,
                "frame_count": 3,
                "line_count": 7,
                "confidence": 0.92,
                "timestamp": 12.5,
            },
        }
    )

    ocr_semantic_evidence = bundle["ocr_semantic_evidence"]
    assert ocr_semantic_evidence["visible_text"] == "BOLTBOAT"
    assert ocr_semantic_evidence["ocr_profile"]["available"] is True
    assert ocr_semantic_evidence["ocr_profile"]["frame_count"] == 3
    assert ocr_semantic_evidence["ocr_profile"]["line_count"] == 7
    assert ocr_semantic_evidence["ocr_profile"]["confidence"] == 0.92
    assert ocr_semantic_evidence["ocr_profile"]["timestamp"] == 12.5


def test_build_evidence_bundle_keeps_evidence_only_fields():
    bundle = build_evidence_bundle(
        source_name="IMG_1234.mp4",
        subtitle_items=[
            {
                "text_final": "今天看下这个包的分仓和挂点",
                "start_time": 0.0,
                "end_time": 2.0,
            }
        ],
        transcript_excerpt="[0.0-2.0] 今天看下这个包的分仓和挂点",
        visible_text="FXX1",
        ocr_profile={"visible_text": "FXX1"},
        visual_hints={"subject_type": "EDC机能包", "visible_text": "FXX1"},
    )

    assert bundle["transcript_excerpt"] == "[0.0-2.0] 今天看下这个包的分仓和挂点"
    assert bundle["visible_text"] == "FXX1"
    assert "subject_type" not in bundle
    assert bundle["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"


def test_build_evidence_bundle_collects_generic_semantic_fact_inputs():
    bundle = build_evidence_bundle(
        source_name="HSJUN_BOLTBOAT_review.mp4",
        subtitle_items=[
            {
                "text_final": "这是 hsjun 和 boltboat 联名的包",
                "start_time": 0.0,
                "end_time": 2.0,
            },
            {
                "text_final": "它叫游刃，今天主要看结构和背负",
                "start_time": 2.0,
                "end_time": 4.0,
            },
        ],
        transcript_excerpt="[0.0-2.0] 这是 hsjun 和 boltboat 联名的包 [2.0-4.0] 它叫游刃",
        visible_text="BOLTBOAT HSJUN",
        ocr_profile={"visible_text": "BOLTBOAT HSJUN"},
        visual_hints={"subject_brand": "HSJUN", "subject_model": "游刃"},
    )

    semantic_inputs = bundle["semantic_fact_inputs"]

    assert "HSJUN_BOLTBOAT_review.mp4" in semantic_inputs["source_name"]
    assert "这是 hsjun 和 boltboat 联名的包" in semantic_inputs["subtitle_lines"]
    assert "它叫游刃，今天主要看结构和背负" in semantic_inputs["subtitle_lines"]
    assert semantic_inputs["transcript_text"].startswith("[0.0-2.0]")
    assert semantic_inputs["visible_text"] == "BOLTBOAT HSJUN"
    assert "HSJUN" in semantic_inputs["hint_candidates"]
    assert "游刃" in semantic_inputs["hint_candidates"]


def test_build_evidence_bundle_prioritizes_relation_rich_cue_lines_and_entity_tokens():
    bundle = build_evidence_bundle(
        source_name="collab_backpack_review.mp4",
        subtitle_items=[
            {"text_final": "今天主要聊一下上身感受", "start_time": 0.0, "end_time": 1.0},
            {"text_final": "这是 hsjun 和 boltboat 联名的包", "start_time": 1.0, "end_time": 2.0},
            {"text_final": "这个系列叫 游刃", "start_time": 2.0, "end_time": 3.0},
            {"text_final": "它的面料和容量我后面再说", "start_time": 3.0, "end_time": 4.0},
            {"text_final": "型号其实就是这次联名双肩包", "start_time": 4.0, "end_time": 5.0},
        ],
        transcript_excerpt="这是 hsjun 和 boltboat 联名的包，这个系列叫 游刃",
        visible_text="HSJUN BOLTBOAT",
    )

    semantic_inputs = bundle["semantic_fact_inputs"]

    assert "这是 hsjun 和 boltboat 联名的包" in semantic_inputs["cue_lines"]
    assert "这个系列叫 游刃" in semantic_inputs["cue_lines"]
    assert "HSJUN" in semantic_inputs["entity_like_tokens"]
    assert "BOLTBOAT" in semantic_inputs["entity_like_tokens"]
    assert any(item["relation"] == "naming" and item.get("value") == "游刃" for item in semantic_inputs["relation_hints"])
    assert "游刃" in semantic_inputs["entity_like_tokens"]
    assert len(semantic_inputs["cue_lines"]) <= 8
    assert "COLLAB_BACKPACK_REVIEW" not in semantic_inputs["entity_like_tokens"]


def test_build_evidence_bundle_collects_relation_hints_and_skips_placeholder_hint_values():
    bundle = build_evidence_bundle(
        source_name="brand_collab_review.mp4",
        subtitle_items=[
            {"text_final": "这是 hsjun 和 boltboat 联名的包", "start_time": 0.0, "end_time": 1.0},
            {"text_final": "这个系列叫 游刃", "start_time": 1.0, "end_time": 2.0},
            {"text_final": "这是 hsjun 家的轻量化双肩包", "start_time": 2.0, "end_time": 3.0},
        ],
        transcript_excerpt="这是 hsjun 和 boltboat 联名的包，这个系列叫 游刃",
        visible_text="",
        ocr_profile={"visible_text": ""},
        visual_hints={"subject_brand": "HSJUN", "nested": {"subject_model": "游刃"}},
    )

    semantic_inputs = bundle["semantic_fact_inputs"]

    assert "{}" not in semantic_inputs["hint_candidates"]
    assert "HSJUN" in semantic_inputs["hint_candidates"]
    assert "游刃" in semantic_inputs["hint_candidates"]
    assert any(item["relation"] == "collaboration" for item in semantic_inputs["relation_hints"])
    assert any(item["relation"] == "naming" for item in semantic_inputs["relation_hints"])
    assert any(item["relation"] == "ownership" for item in semantic_inputs["relation_hints"])


def test_build_content_understanding_orchestration_context_rejects_invalid_or_nested_context_input():
    from roughcut.review.content_understanding_orchestrator import build_content_understanding_orchestration_context

    try:
        build_content_understanding_orchestration_context(None)
    except TypeError as exc:
        assert "dict evidence bundle" in str(exc)
    else:
        raise AssertionError("expected TypeError for non-dict input")

    try:
        build_content_understanding_orchestration_context({"evidence_bundle": {}})
    except ValueError as exc:
        assert "already-orchestrated context" in str(exc)
    else:
        raise AssertionError("expected ValueError for nested orchestrator context")


def test_build_content_understanding_orchestration_context_uses_new_mainline_and_preserves_visual_semantic_evidence():
    from roughcut.review.content_understanding_orchestrator import build_content_understanding_orchestration_context

    context = build_content_understanding_orchestration_context(
        {
            "source_name": "demo.mp4",
            "visual_semantic_evidence": {"object_categories": ["backpack"]},
            "visual_hints": {"subject_type": "EDC机能包"},
        }
    )

    assert context["mainline"] == "content_understanding"
    assert context["evidence_bundle"]["visual_semantic_evidence"]["object_categories"] == ["backpack"]
    assert context["evidence_bundle"]["candidate_hints"]["visual_hints"]["subject_type"] == "EDC机能包"
    assert "content_profile" not in context
