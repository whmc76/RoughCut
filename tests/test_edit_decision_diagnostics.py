from roughcut.edit.decisions import EditDecision, EditSegment
from roughcut.pipeline.steps import _apply_llm_cut_review_to_decision, _build_variant_timeline_diagnostics
from roughcut.pipeline.steps import _should_review_cut_with_llm
from roughcut.review.telegram_bot import _coerce_subtitle_event_to_item, _extract_subtitle_items_from_report, _load_full_subtitle_review_lines
from roughcut.media.variant_timeline_bundle import (
    variant_cut_analysis_summary,
    variant_cut_evidence_summary,
    variant_high_energy_keeps,
    variant_high_risk_cuts,
    variant_llm_cut_review,
    variant_multimodal_trim_review_summary,
    variant_packaging_timeline,
    variant_refine_decision_summary,
    variant_review_flags,
    variant_timeline_diagnostics,
)
from roughcut.review.telegram_bot import _build_final_review_diagnostics_lines
import pytest


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


def test_variant_diagnostics_excludes_edge_silence_from_high_risk_cuts() -> None:
    diagnostics = _build_variant_timeline_diagnostics(
        editorial_analysis={
            "accepted_cuts": [
                {
                    "start": 0.0,
                    "end": 1.56,
                    "reason": "silence",
                    "boundary_keep_energy": 1.75,
                    "left_keep_role": "",
                    "right_keep_role": "body",
                },
                {
                    "start": 950.85,
                    "end": 952.62,
                    "reason": "silence",
                    "boundary_keep_energy": 2.23,
                    "left_keep_role": "body",
                    "right_keep_role": "",
                },
                {
                    "start": 150.03,
                    "end": 150.63,
                    "reason": "silence",
                    "boundary_keep_energy": 2.23,
                    "left_keep_role": "body",
                    "right_keep_role": "body",
                },
            ],
        },
        cut_analysis={},
        timeline_analysis={},
    )

    assert diagnostics["high_risk_cuts"] == [
        {
            "start": 150.03,
            "end": 150.63,
            "reason": "silence",
            "source_text": "",
            "match_surface": "",
            "match_surface_layer": "",
            "risk_level": "",
            "rule_id": "",
            "boundary_keep_energy": 2.23,
            "left_keep_role": "body",
            "right_keep_role": "body",
            "evidence": {},
        }
    ]


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
                "rule_auto_apply": 1,
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
        "rule_auto_apply_cut_count": 1,
        "multimodal_auto_apply_cut_count": 0,
        "risk_levels": {},
    }


def test_llm_review_gate_uses_rule_registry_risk_contract() -> None:
    assert _should_review_cut_with_llm({"reason": "catchphrase_phrase", "risk_level": "high"}) is True
    assert _should_review_cut_with_llm({"reason": "catchphrase_phrase", "risk_level": "low"}) is False


def test_apply_llm_cut_review_demotes_unsure_cut_to_manual_candidate() -> None:
    decision = EditDecision(
        source="demo.mp4",
        segments=[
            EditSegment(start=0.0, end=1.56, type="remove", reason="silence"),
            EditSegment(start=1.56, end=4.0, type="keep"),
        ],
        analysis={
            "accepted_cuts": [
                {
                    "start": 0.0,
                    "end": 1.56,
                    "reason": "silence",
                    "rule_id": "silence:0.000:1.560:silence",
                    "risk_level": "low",
                    "source_text": "silence",
                    "match_surface": "silence",
                    "match_surface_layer": "raw",
                    "boundary_keep_energy": 1.75,
                }
            ]
        },
    )

    reviewed = _apply_llm_cut_review_to_decision(
        decision=decision,
        review_result={
            "min_confidence": 0.72,
            "decisions": [
                {
                    "candidate_id": "silence:0.000:1.560",
                    "verdict": "unsure",
                    "confidence": 0.62,
                    "reason": "hook opening may contain useful product reveal",
                    "evidence": ["hook_guard", "scene boundary"],
                }
            ],
        },
        subtitle_items=[],
        content_profile=None,
    )

    assert [(segment.type, segment.start, segment.end) for segment in reviewed.segments] == [
        ("keep", 0.0, 4.0),
    ]
    assert reviewed.analysis["accepted_cuts"] == []
    assert reviewed.analysis["manual_editor_rule_candidates"] == [
        {
            "start": 0.0,
            "end": 1.56,
            "reason": "silence",
            "rule_id": "silence:0.000:1.560:silence",
            "risk_level": "low",
            "source_text": "silence",
            "match_surface": "silence",
            "match_surface_layer": "raw",
            "boundary_keep_energy": 1.75,
            "auto_applied": False,
            "llm_review": {
                "candidate_id": "silence:0.000:1.560",
                "verdict": "unsure",
                "confidence": 0.62,
                "reason": "hook opening may contain useful product reveal",
                "evidence": ["hook_guard", "scene boundary"],
            },
        }
    ]
    assert reviewed.analysis["llm_cut_review"]["demoted_cut_count"] == 1
    assert reviewed.analysis["llm_cut_review"]["restored_cut_count"] == 0


def test_variant_diagnostics_include_multimodal_trim_review_summary() -> None:
    diagnostics = _build_variant_timeline_diagnostics(
        editorial_analysis={},
        cut_analysis={
            "multimodal_trim_review_summary": {
                "reviewed": True,
                "candidate_count": 4,
                "accepted_count": 2,
                "rejected_count": 1,
                "pending_count": 1,
            }
        },
        refine_decision_plan={
            "candidate_summary": {
                "multimodal_auto_apply": 2,
            }
        },
        timeline_analysis={},
    )

    assert diagnostics["multimodal_trim_review_summary"] == {
        "reviewed": True,
        "candidate_count": 4,
        "accepted_count": 2,
        "rejected_count": 1,
        "pending_count": 1,
        "auto_apply_cut_count": 2,
    }


def test_variant_packaging_timeline_reads_nested_payload_and_legacy_flat_fields() -> None:
    nested = variant_packaging_timeline(
        {
            "timeline_rules": {
                "packaging_timeline": {
                    "timeline_analysis": {"hook_end_sec": 2.5},
                    "editing_skill": {"key": "unboxing_standard"},
                    "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 5.0}]},
                    "subtitles": {"style": "bold_yellow_outline"},
                    "packaging": {"intro": {"path": "intro.mp4"}, "music": {"path": "music.mp3"}},
                    "editing_accents": {"style": "smart_effect_commercial"},
                }
            }
        }
    )
    assert nested == {
        "timeline_analysis": {"hook_end_sec": 2.5},
        "editing_skill": {"key": "unboxing_standard"},
        "section_choreography": {"sections": [{"start_sec": 0.0, "end_sec": 5.0}]},
        "subtitles": {"style": "bold_yellow_outline"},
        "packaging": {
            "intro": {"path": "intro.mp4"},
            "outro": None,
            "insert": None,
            "watermark": None,
            "music": {"path": "music.mp3"},
        },
        "editing_accents": {"style": "smart_effect_commercial"},
    }

    legacy = variant_packaging_timeline(
        {
            "timeline_rules": {
                "timeline_analysis": {"hook_end_sec": 1.2},
                "editing_skill": {"key": "legacy"},
                "section_choreography": {"sections": []},
                "subtitles": {"style": "legacy"},
                "intro": {"path": "legacy-intro.mp4"},
                "editing_accents": {"style": "legacy-style"},
            }
        }
    )
    assert legacy["timeline_analysis"] == {"hook_end_sec": 1.2}
    assert legacy["editing_skill"] == {"key": "legacy"}
    assert legacy["subtitles"] == {"style": "legacy"}
    assert legacy["packaging"]["intro"] == {"path": "legacy-intro.mp4"}
    assert legacy["editing_accents"] == {"style": "legacy-style"}


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


def test_final_review_diagnostics_mentions_multimodal_trim_review_summary() -> None:
    lines = _build_final_review_diagnostics_lines(
        {
            "variants": {"plain": {"segments": []}},
            "timeline_rules": {
                "diagnostics": {
                    "multimodal_trim_review_summary": {
                        "candidate_count": 3,
                        "accepted_count": 1,
                        "rejected_count": 1,
                        "pending_count": 1,
                        "auto_apply_cut_count": 1,
                    }
                }
            }
        }
    )

    joined = "\n".join(lines)
    assert "多模态复核" in joined
    assert "候选 3 个" in joined
    assert "自动并入全自动精修 1 个" in joined


def test_variant_timeline_bundle_shared_diagnostic_resolvers() -> None:
    bundle = {
        "variants": {"plain": {"segments": []}},
        "timeline_rules": {
            "diagnostics": {
                "review_flags": {"review_recommended": True, "review_reasons": ["需要复核"]},
                "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
                "high_energy_keeps": [{"start": 4.0, "end": 6.0}],
                "cut_evidence_summary": {"protected_visual_cut_count": 2},
                "cut_analysis_summary": {"accepted_cut_count": 3, "auto_apply_candidate_count": 1},
                "llm_cut_review": {"reviewed": True, "candidate_count": 3},
                "multimodal_trim_review_summary": {"candidate_count": 2, "accepted_count": 1},
                "refine_decision_summary": {"mode": "manual_refine", "candidate_total": 5},
            }
        },
    }

    assert variant_timeline_diagnostics(bundle) == {
        "review_flags": {"review_recommended": True, "review_reasons": ["需要复核"]},
        "high_risk_cuts": [{"start": 1.0, "end": 2.0}],
        "high_energy_keeps": [{"start": 4.0, "end": 6.0}],
        "cut_evidence_summary": {"protected_visual_cut_count": 2},
        "cut_analysis_summary": {"accepted_cut_count": 3, "auto_apply_candidate_count": 1},
        "llm_cut_review": {"reviewed": True, "candidate_count": 3},
        "multimodal_trim_review_summary": {"candidate_count": 2, "accepted_count": 1},
        "refine_decision_summary": {"mode": "manual_refine", "candidate_total": 5},
    }
    assert variant_review_flags(bundle) == {"review_recommended": True, "review_reasons": ["需要复核"]}
    assert variant_high_risk_cuts(bundle) == [{"start": 1.0, "end": 2.0}]
    assert variant_high_energy_keeps(bundle) == [{"start": 4.0, "end": 6.0}]
    assert variant_cut_evidence_summary(bundle) == {"protected_visual_cut_count": 2}
    assert variant_cut_analysis_summary(bundle) == {"accepted_cut_count": 3, "auto_apply_candidate_count": 1}
    assert variant_llm_cut_review(bundle) == {"reviewed": True, "candidate_count": 3}
    assert variant_multimodal_trim_review_summary(bundle) == {"candidate_count": 2, "accepted_count": 1}
    assert variant_refine_decision_summary(bundle) == {"mode": "manual_refine", "candidate_total": 5}


@pytest.mark.asyncio
async def test_load_full_subtitle_review_lines_respects_display_surface_contract() -> None:
    class _ScalarResult:
        def __init__(self, items):
            self._items = items

        def all(self):
            return self._items

    class _ExecuteResult:
        def __init__(self, items):
            self._items = items

        def scalars(self):
            return _ScalarResult(self._items)

    class _Session:
        def __init__(self, items):
            self._items = items

        async def execute(self, _query):
            return _ExecuteResult(self._items)

    suppressed = type(
        "SubtitleRow",
        (),
        {
            "id": "s1",
            "item_index": 0,
            "text_raw": "那个",
            "text_norm": "这是 NITECORE EDC17 手电",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
            "start_time": 0.0,
            "end_time": 1.0,
        },
    )()
    visible = type(
        "SubtitleRow",
        (),
        {
            "id": "s2",
            "item_index": 1,
            "text_raw": "顺便和 EDC37 做个对比",
            "text_norm": "顺便和 EDC37 做个对比",
            "text_final": "顺便和 EDC37 做个对比",
            "start_time": 1.0,
            "end_time": 2.0,
        },
    )()

    lines = await _load_full_subtitle_review_lines("00000000-0000-0000-0000-000000000000", _Session([suppressed, visible]))

    assert [(line.slot, line.text, line.subtitle_index) for line in lines] == [
        ("L1", "顺便和 EDC37 做个对比", 1),
    ]


def test_extract_subtitle_items_from_report_respects_display_surface_contract() -> None:
    report = type(
        "SubtitleReport",
        (),
        {
            "items": [
                {
                    "index": 0,
                    "start": 0.0,
                    "end": 1.0,
                    "text_raw": "那个 EDC 折刀",
                    "text_norm": "这是 MAXACE 美杜莎4",
                    "text_final": "",
                    "display_suppressed_reason": "standalone_filler",
                },
                {
                    "index": 1,
                    "start": 1.0,
                    "end": 2.0,
                    "text_raw": "看一下细节",
                    "text_norm": "看一下细节",
                    "text_final": "看一下细节",
                },
            ]
        },
    )()

    items = _extract_subtitle_items_from_report(report)

    assert items == [
        {"index": 0, "start": 0.0, "end": 1.0, "text": ""},
        {"index": 1, "start": 1.0, "end": 2.0, "text": "看一下细节"},
    ]


def test_coerce_subtitle_event_to_item_prefers_display_surface_contract() -> None:
    item = _coerce_subtitle_event_to_item(
        {
            "index": 1,
            "start": 0.0,
            "end": 1.0,
            "text": "那个 EDC 折刀",
            "text_raw": "那个 EDC 折刀",
            "text_norm": "这是 MAXACE 美杜莎4",
            "text_final": "",
            "display_suppressed_reason": "standalone_filler",
        },
        index=1,
    )

    assert item == {"index": 1, "start": 0.0, "end": 1.0, "text": "那个 EDC 折刀"}
