from roughcut.pipeline.steps import _build_variant_timeline_diagnostics
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
        timeline_analysis={},
    )

    high_risk = diagnostics["high_risk_cuts"][0]
    assert high_risk["evidence"]["visual_showcase_score"] == 0.9
    assert high_risk["evidence"]["tags"][:2] == ["visual_context", "scene_activity"]
    assert diagnostics["cut_evidence_summary"]["protected_visual_cut_count"] == 1
    assert any("保护证据" in reason for reason in diagnostics["review_flags"]["review_reasons"])


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
                    "review_flags": {"review_recommended": True, "review_reasons": ["需要检查"]},
                }
            }
        }
    )

    joined = "\n".join(lines)
    assert "剪辑证据" in joined
    assert "展示 0.90" in joined
    assert "保护 0.80" in joined
