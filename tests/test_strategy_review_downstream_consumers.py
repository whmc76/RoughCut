from roughcut.edit.decisions import build_edit_decision
from roughcut.edit.render_plan import build_render_plan, render_plan_manual_editor, render_plan_strategy_review_context


def _strategy_review_profile() -> dict:
    return {
        "strategy_review_context": {
            "strategy_review_gates": {
                "artifact_type": "strategy_review_gates",
                "strategy_type": "narrative_assembly",
                "pipeline_plan": {
                    "strategy_type": "narrative_assembly",
                    "production_mode": "remix",
                    "review_gates": ["storyboard_review_required", "timeline_preview_required"],
                },
                "review_gate_status": {
                    "blocking": False,
                    "blocking_gate_ids": [],
                },
            },
            "strategy_storyboard_review": {
                "artifact_type": "strategy_storyboard_review",
                "panels": [{"panel_id": "opening_hook", "text": "先看关键转折"}],
            },
            "strategy_timeline_preview": {
                "artifact_type": "strategy_timeline_preview",
                "segments": [{"segment_id": "preview_1", "text": "插入原始素材"}],
            },
        }
    }


def test_edit_decision_analysis_carries_strategy_review_context() -> None:
    decision = build_edit_decision(
        source_path="source.mp4",
        duration=12.0,
        silence_segments=[],
        subtitle_items=[],
        content_profile=_strategy_review_profile(),
    )

    strategy_context = decision.analysis["strategy_review_context"]

    assert strategy_context["schema"] == "strategy_review_context.v1"
    assert strategy_context["strategy_review_gates"]["pipeline_plan"]["strategy_type"] == "narrative_assembly"
    assert strategy_context["strategy_storyboard_review"]["panels"][0]["panel_id"] == "opening_hook"
    assert strategy_context["strategy_timeline_preview"]["segments"][0]["segment_id"] == "preview_1"


def test_render_plan_exposes_strategy_review_context_to_manual_editor_and_packaging() -> None:
    plan = build_render_plan(
        "00000000-0000-0000-0000-000000000000",
        content_profile=_strategy_review_profile(),
    )

    strategy_context = render_plan_strategy_review_context(plan)
    manual_editor = render_plan_manual_editor(plan)

    assert strategy_context["strategy_review_gates"]["review_gate_status"]["blocking"] is False
    assert manual_editor["strategy_review_context"]["strategy_storyboard_review"]["panels"][0]["text"] == "先看关键转折"
    assert plan["packaging_timeline"]["strategy_review_context"]["strategy_timeline_preview"]["segments"][0][
        "segment_id"
    ] == "preview_1"
