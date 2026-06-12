from roughcut.edit.rule_registry import (
    empty_rule_risk_level_counts,
    get_rule_definition,
    manual_editor_frontend_managed_auto_cut_reasons,
    manual_editor_synthetic_timeline_reasons,
    normalize_rule_risk_level,
    pause_cut_reasons,
    rule_auto_applies_in_auto_mode,
    rule_requires_llm_review,
    speech_explicit_cut_reasons,
    speech_review_cut_reasons,
    summarize_rule_risk_levels,
)


def test_rule_registry_exposes_shared_manual_editor_managed_auto_cut_reasons() -> None:
    reasons = manual_editor_frontend_managed_auto_cut_reasons()

    assert "silence" in reasons
    assert "restart_retake" in reasons
    assert "gap_fill" in reasons
    assert "catchphrase_phrase" in reasons


def test_rule_registry_exposes_shared_timeline_contract_reason_sets() -> None:
    explicit = speech_explicit_cut_reasons()
    review = speech_review_cut_reasons()
    pause = pause_cut_reasons()

    assert "filler_word" in explicit
    assert "manual_cut" in explicit
    assert "silence" in review
    assert "low_signal_subtitle" in review
    assert "rollback_instruction" in pause
    assert "manual_cut" in pause
    assert "filler_word" not in pause


def test_rule_registry_exposes_shared_manual_editor_synthetic_timeline_reasons() -> None:
    reasons = manual_editor_synthetic_timeline_reasons()

    assert reasons == {"manual_editor_keep", "manual_editor_removed"}


def test_rule_registry_reason_sets_are_derived_from_shared_metadata() -> None:
    reasons = {
        "frontend": manual_editor_frontend_managed_auto_cut_reasons(),
        "speech_explicit": speech_explicit_cut_reasons(),
        "speech_review": speech_review_cut_reasons(),
        "pause": pause_cut_reasons(),
    }

    for reason in (
        "silence",
        "rollback_instruction",
        "restart_retake",
        "low_signal_subtitle",
        "gap_fill",
    ):
        definition = get_rule_definition(reason)
        assert definition is not None
        assert (reason in reasons["frontend"]) is definition.frontend_managed_auto_cut
        assert (reason in reasons["speech_explicit"]) is definition.speech_explicit_cut
        assert (reason in reasons["speech_review"]) is definition.speech_review_cut
        assert (reason in reasons["pause"]) is definition.pause_cut

    assert "manual_cut" in reasons["speech_explicit"]
    assert "manual_cut" in reasons["pause"]


def test_rule_registry_exposes_llm_review_gate_and_risk_normalization() -> None:
    assert rule_requires_llm_review("rollback_instruction", risk_level="high") is True
    assert rule_requires_llm_review("catchphrase_phrase", risk_level="high") is True
    assert rule_requires_llm_review("catchphrase_phrase", risk_level="low") is False
    assert rule_auto_applies_in_auto_mode("catchphrase_phrase", risk_level="low") is True
    assert rule_auto_applies_in_auto_mode("catchphrase_phrase", risk_level="high") is False
    assert rule_auto_applies_in_auto_mode("noise_subtitle", risk_level="low") is False
    assert rule_auto_applies_in_auto_mode("restart_retake", risk_level="high") is False
    assert normalize_rule_risk_level("", reason="silence") == "low"
    assert normalize_rule_risk_level("weird", reason="restart_retake") == "high"


def test_rule_registry_summarizes_risk_levels() -> None:
    counts = summarize_rule_risk_levels(
        [
            {"reason": "silence"},
            {"reason": "restart_retake"},
            {"reason": "catchphrase_phrase", "risk_level": "medium"},
            {"reason": "unknown_reason", "risk_level": "high"},
        ]
    )

    assert counts == {
        **empty_rule_risk_level_counts(),
        "low": 1,
        "medium": 1,
        "high": 2,
    }
