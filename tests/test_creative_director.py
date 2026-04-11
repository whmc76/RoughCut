from __future__ import annotations

from roughcut.creative.director import _build_heuristic_director_plan


def test_heuristic_director_plan_uses_creative_preferences():
    plan = _build_heuristic_director_plan(
        source_name="demo.mp4",
        subtitle_items=[
            {"start_time": 0.0, "end_time": 1.5, "text_final": "先说开头。"},
            {"start_time": 2.0, "end_time": 4.0, "text_final": "中间讲细节。"},
            {"start_time": 8.0, "end_time": 10.0, "text_final": "最后做收口。"},
        ],
        content_profile={
            "subject_type": "EDC手电",
            "summary": "这期重点讲版本差异和怎么选。",
            "creative_preferences": [
                {"tag": "comparison_focus", "count": 3},
                {"tag": "fast_paced", "count": 2},
                {"tag": "closeup_focus", "count": 2},
            ],
        },
    )

    assert "差异" in plan["opening_hook"] or "怎么选" in plan["opening_hook"]
    assert "差异" in plan["bridge_line"] or "取舍" in plan["bridge_line"]
    assert "细节" in plan["science_boost"] or "近景" in plan["science_boost"]
    assert any("结论" in item or "重点" in item for item in plan["rewrite_strategy"])
