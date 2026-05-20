from types import SimpleNamespace

from roughcut.pipeline.steps import (
    _attach_edit_decision_projection_gate_analysis,
    _merge_automatic_gate_with_subtitle_projection,
)


def test_subtitle_projection_gate_is_attached_to_edit_decision_analysis() -> None:
    validation = {
        "blocking": True,
        "blocking_issue_count": 2,
        "warning_issue_count": 1,
        "issue_counts": {"missing_projected_subtitle": 2},
    }
    automatic_gate = _merge_automatic_gate_with_subtitle_projection(
        {"blocking": False, "blocking_reasons": []},
        validation,
    )
    decision = SimpleNamespace(analysis={})

    _attach_edit_decision_projection_gate_analysis(
        decision,
        subtitle_source_projection_validation=validation,
        automatic_gate=automatic_gate,
    )

    assert decision.analysis["subtitle_source_projection_validation"] == validation
    assert decision.analysis["automatic_gate"]["blocking"] is True
    assert decision.analysis["automatic_gate"]["blocking_reasons"] == [
        "subtitle_source_projection_validation_blocking"
    ]
