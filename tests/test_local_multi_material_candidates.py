from roughcut.edit.decisions import infer_timeline_analysis
from roughcut.edit.local_multi_material_candidates import build_local_multi_material_candidates


def test_multi_material_candidates_require_multiple_uploaded_sources() -> None:
    blocked = build_local_multi_material_candidates(
        content_profile={
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4"],
        },
        local_asset_inventory={"has_primary_video": True, "auxiliary_video_count": 0},
    )
    ready = build_local_multi_material_candidates(
        content_profile={
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4", "detail-cut.mp4", "street-broll.mp4"],
        },
        local_asset_inventory={"has_primary_video": True, "auxiliary_video_count": 2, "image_count": 1},
    )

    assert blocked == []
    assert len(ready) == 2
    assert ready[0]["suggested_operation"] in {
        "insert_into_detail_window",
        "interleave_between_body_sections",
        "interleave_after_step_boundary",
    }


def test_multi_material_candidates_infer_roles_from_source_names() -> None:
    candidates = build_local_multi_material_candidates(
        content_profile={
            "content_kind": "tutorial",
            "merged_source_names": ["lesson-main.mp4", "screen-step-demo.mp4", "macro-detail-cut.mp4"],
        },
        local_asset_inventory={"has_primary_video": True, "auxiliary_video_count": 2},
    )

    assert candidates[0]["role"] == "step_support"
    assert candidates[1]["role"] == "detail_support"


def test_infer_timeline_analysis_carries_multi_material_candidates_for_narrative_ready_profile() -> None:
    analysis = infer_timeline_analysis(
        [
            {"start_time": 0.0, "end_time": 2.2, "text_final": "先把主体讲清楚", "text_raw": "先把主体讲清楚", "text_norm": "先把主体讲清楚"},
            {"start_time": 2.5, "end_time": 5.8, "text_final": "这里补充细节展示", "text_raw": "这里补充细节展示", "text_norm": "这里补充细节展示"},
            {"start_time": 6.0, "end_time": 11.8, "text_final": "最后做一个简短结尾总结", "text_raw": "最后做一个简短结尾总结", "text_norm": "最后做一个简短结尾总结"},
        ],
        duration=11.8,
        content_profile={
            "content_kind": "commentary",
            "merged_source_names": ["main.mp4", "detail-cut.mp4", "street-broll.mp4"],
        },
    )

    assert analysis["multi_material_candidates"]
    assert analysis["multi_material_candidates"][0]["source_name"] in {"detail-cut.mp4", "street-broll.mp4"}
