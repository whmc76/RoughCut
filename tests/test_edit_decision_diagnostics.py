from roughcut.pipeline.steps import _build_variant_timeline_diagnostics
from roughcut.media.variant_timeline_bundle import (
    variant_cut_analysis_summary,
    variant_cut_evidence_summary,
    variant_high_energy_keeps,
    variant_high_risk_cuts,
    variant_llm_cut_review,
    variant_refine_decision_summary,
    variant_review_flags,
    variant_timeline_diagnostics,
)
from roughcut.review.telegram_bot import _build_final_review_diagnostics_lines


def test_variant_diagnostics_compacts_cut_evidence() -> None:
    diagnostics = _build_variant_timeline_diagnostics(
        editorial_analysis={
            "keep_energy_summary": {"count": 1},
            "cut_evidence_summary": {
                "protected_visual_cut_count": 1,
                "high_protection_evidence_count": 1,
            },
            "accepted_cuts": [
                {
                    "start": 2.0,
                    "end": 4.0,
                    "reason": "silence",
                    "boundary_keep_energy": 1.2,
                    "left_keep_role": "detail",
                    "right_keep_role": "detail",
                    "evidence": {
                        "visual_showcase_score": 0.9,
                        "language_score": 0.0,
                        "protection_score": 0.8,
                        "removal_score": 0.3,
                        "tags": ["visual_context", "scene_activity", "detail_section", "extra"],
                    },
                },
            ],
        },
        cut_analysis={},
        timeline_analysis={},
    )

    high_risk = diagnostics["high_risk_cuts"][0]
    assert high_risk["evidence"]["visual_showcase_score"] == 0.9
    assert high_risk["evidence"]["tags"][:2] == ["visual_context", "scene_activity"]
    assert diagnostics["cut_evidence_summary"]["protected_visual_cut_count"] == 1
    assert any("保护证据" in reason for reason in diagnostics["review_flags"]["review_reasons"])


def test_variant_diagnostics_include_refine_decision_summary() -> None:
    diagnostics = _build_variant_timeline_diagnostics(
        editorial_analysis={},
        cut_analysis={},
        refine_decision_plan={
            "mode": "auto_refine",
            "keep_segments": [{"start": 0.0, "end": 3.0}, {"start": 5.0, "end": 8.0}],
            "candidate_summary": {
                "total": 7,
                "auto_apply": 5,
                "manual_confirm": 2,
            },
        },
        timeline_analysis={},
    )

    assert diagnostics["refine_decision_summary"] == {
        "mode": "auto_refine",
        "keep_segment_count": 2,
        "candidate_total": 7,
        "candidate_auto_apply": 5,
        "candidate_manual_confirm": 2,
    }


def test_final_review_diagnostics_mentions_cut_evidence() -> None:
    lines = _build_final_review_diagnostics_lines(
        {
            "timeline_rules": {
                "diagnostics": {
                    "cut_evidence_summary": {
                        "protected_visual_cut_count": 1,
                        "high_protection_evidence_count": 1,
                    },
                    "high_risk_cuts": [
                        {
                            "start": 2.0,
                            "end": 4.0,
                            "boundary_keep_energy": 1.2,
                            "left_keep_role": "detail",
                            "right_keep_role": "body",
                            "evidence": {
                                "visual_showcase_score": 0.9,
                                "protection_score": 0.8,
                                "removal_score": 0.3,
                                "tags": ["visual_context", "scene_activity"],
                            },
                        },
                    ],
                    "review_flags": {"review_recommended": True, "review_reasons": ["需要复核"]},
                }
            }
        }
    )

    joined = "\n".join(lines)
    assert "证据" in joined
    assert "0.90" in joined
    assert "0.80" in joined


def test_final_review_diagnostics_mentions_refine_decision_summary() -> None:
    lines = _build_final_review_diagnostics_lines(
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "refine_decision_summary": {
                        "mode": "auto_refine",
                        "keep_segment_count": 12,
                        "candidate_total": 7,
                        "candidate_manual_confirm": 2,
                    }
                }
            }
        }
    )

    joined = "\n".join(lines)
    assert "auto_refine" in joined
    assert "12" in joined
    assert "7" in joined


def test_variant_timeline_bundle_shared_diagnostic_resolvers() -> None:
    bundle = {
        "variants": {"plain": {"segments": []}},
        "timeline_rules": {
            "diagnostics": {
                "review_flags": {"review_recommended": True, "review_reasons": ["需要复核"]},
                "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
                "high_energy_keeps": [{"start": 4.0, "end": 6.0}],
                "cut_evidence_summary": {"protected_visual_cut_count": 2},
                "cut_analysis_summary": {"accepted_cut_count": 3},
                "llm_cut_review": {"reviewed": True, "candidate_count": 3},
                "refine_decision_summary": {"mode": "manual_refine", "candidate_total": 5},
            }
        },
    }

    assert variant_timeline_diagnostics(bundle) == {
        "review_flags": {"review_recommended": True, "review_reasons": ["需要复核"]},
        "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
        "high_energy_keeps": [{"start": 4.0, "end": 6.0}],
        "cut_evidence_summary": {"protected_visual_cut_count": 2},
        "cut_analysis_summary": {"accepted_cut_count": 3},
        "llm_cut_review": {"reviewed": True, "candidate_count": 3},
        "refine_decision_summary": {"mode": "manual_refine", "candidate_total": 5},
    }
    assert variant_review_flags(bundle) == {"review_recommended": True, "review_reasons": ["需要复核"]}
    assert variant_high_risk_cuts(bundle) == [{"start": 1.0, "end": 2.0}]
    assert variant_high_energy_keeps(bundle) == [{"start": 4.0, "end": 6.0}]
    assert variant_cut_evidence_summary(bundle) == {"protected_visual_cut_count": 2}
    assert variant_cut_analysis_summary(bundle) == {"accepted_cut_count": 3}
    assert variant_llm_cut_review(bundle) == {"reviewed": True, "candidate_count": 3}
    assert variant_refine_decision_summary(bundle) == {"mode": "manual_refine", "candidate_total": 5}
