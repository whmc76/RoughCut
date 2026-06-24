import json

from roughcut.media.output import get_cover_manifest_path, load_cover_selection_summary
from roughcut.production_readiness import (
    creator_refine_output_fallback_reasons,
    intelligent_copy_cover_brief_fallback_reasons,
    intelligent_copy_material_context_fallback_reasons,
    insert_plan_output_fallback_reasons,
    platform_packaging_output_fallback_reasons,
    projection_output_fallback_reasons,
    render_output_blocking_reasons,
    strategy_cut_boundary_validation,
    strategy_overlay_subtitle_occlusion_validation,
    strategy_render_validation_summary,
    strategy_storyboard_validation,
    strategy_timeline_preview_validation,
)


def test_projection_output_fallback_reasons_distinguishes_refresh_from_real_fallback() -> None:
    diagnostics = {
        "projection_refresh_required": True,
        "rebuilt_from_canonical_fallback": True,
        "source_projection_fallback_applied": False,
        "projection_validation_fallback_used": False,
    }

    assert projection_output_fallback_reasons(diagnostics) == [
        "subtitle_projection_rebuilt_from_canonical_fallback",
    ]
    assert projection_output_fallback_reasons(diagnostics, include_refresh_required=True) == [
        "subtitle_projection_rebuilt_from_canonical_fallback",
        "subtitle_projection_refresh_required",
    ]
    assert projection_output_fallback_reasons({"fallback_used": True}) == [
        "subtitle_projection_validation_fallback_used",
    ]


def test_platform_packaging_output_fallback_reasons_block_deterministic_or_renderless_outputs() -> None:
    packaging = {
        "generation_repair_trace": [{"status": "deterministic_fallback"}],
        "subtitle_projection_repair": {"projection_validation_fallback_used": True},
    }

    assert platform_packaging_output_fallback_reasons(packaging, renderless_mode=False) == [
        "platform_packaging_deterministic_fallback",
        "subtitle_projection_validation_fallback_used",
    ]
    assert platform_packaging_output_fallback_reasons({}, renderless_mode=True) == [
        "platform_packaging_renderless_only",
    ]


def test_render_output_blocking_reasons_ignore_optional_runtime_degradation() -> None:
    reasons = render_output_blocking_reasons(
        avatar_result={"status": "degraded", "reason": "missing_avatar_render"},
        subtitle_projection_repair={"projection_validation_fallback_used": True},
    )

    assert reasons == [
        "subtitle_projection_validation_fallback_used",
    ]
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
    ) == []


def test_strategy_timeline_preview_validation_blocks_missing_required_preview() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": ["timeline_preview_required"],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_timeline_preview_alignment": True,
                    }
                },
            }
        }
    }

    validation = strategy_timeline_preview_validation(strategy_review_context)

    assert validation["status"] == "blocking"
    assert validation["blocking"] is True
    assert validation["reason"] == "strategy_timeline_preview_missing"
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
    ) == ["strategy_timeline_preview_missing"]


def test_strategy_timeline_preview_validation_passes_when_required_preview_has_segments() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": ["timeline_preview_required"],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_timeline_preview_alignment": True,
                    }
                },
            }
        },
        "strategy_timeline_preview": {
            "segments": [
                {
                    "segment_id": "preview_1",
                    "timestamp": "00:00-00:04",
                }
            ]
        },
    }

    validation = strategy_timeline_preview_validation(strategy_review_context)

    assert validation["status"] == "ok"
    assert validation["blocking"] is False
    assert validation["segment_count"] == 1
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
    ) == []


def test_strategy_timeline_preview_validation_ignores_optional_strategy_without_policy() -> None:
    validation = strategy_timeline_preview_validation(
        {
            "strategy_review_gates": {
                "pipeline_plan": {
                    "strategy_type": "event_highlight",
                    "review_gates": ["manual_cut_review_optional"],
                    "strategy_policy": {"render_validation_policy": {}},
                }
            }
        }
    )

    assert validation["status"] == "not_required"
    assert validation["blocking"] is False


def test_strategy_storyboard_validation_blocks_missing_required_storyboard() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": ["storyboard_review_required"],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_storyboard_alignment": True,
                    }
                },
            }
        }
    }

    validation = strategy_storyboard_validation(strategy_review_context)

    assert validation["status"] == "blocking"
    assert validation["blocking"] is True
    assert validation["reason"] == "strategy_storyboard_review_missing"
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
    ) == ["strategy_storyboard_review_missing"]


def test_strategy_storyboard_validation_passes_when_required_storyboard_has_panels() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": ["storyboard_review_required"],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_storyboard_alignment": True,
                    }
                },
            }
        },
        "strategy_storyboard_review": {
            "panels": [
                {
                    "panel_id": "opening_hook",
                    "text": "先看关键转折",
                }
            ]
        },
    }

    validation = strategy_storyboard_validation(strategy_review_context)

    assert validation["status"] == "ok"
    assert validation["blocking"] is False
    assert validation["panel_count"] == 1
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
    ) == []


def test_strategy_render_validation_summary_collects_multiple_blocking_reasons() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": ["storyboard_review_required", "timeline_preview_required"],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_storyboard_alignment": True,
                        "check_timeline_preview_alignment": True,
                    }
                },
            }
        }
    }

    validation = strategy_render_validation_summary(strategy_review_context)

    assert validation["status"] == "blocking"
    assert validation["blocking"] is True
    assert validation["reason"] == "strategy_timeline_preview_missing"
    assert validation["blocking_reasons"] == [
        "strategy_timeline_preview_missing",
        "strategy_storyboard_review_missing",
    ]
    assert {check["check"] for check in validation["checks"]} == {
        "strategy_timeline_preview_alignment",
        "strategy_storyboard_alignment",
        "strategy_overlay_subtitle_occlusion",
        "strategy_cut_boundary_evidence",
    }
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
    ) == [
        "strategy_timeline_preview_missing",
        "strategy_storyboard_review_missing",
    ]


def test_strategy_overlay_subtitle_occlusion_validation_blocks_unsafe_overlay_evidence() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_overlay_subtitle_occlusion": True,
                    }
                },
            }
        }
    }
    render_plan = {
        "packaging_timeline": {
            "subtitles": {"style": "bold_yellow_outline"},
            "editing_accents": {
                "emphasis_overlays": [
                    {"start_time": 1.0, "end_time": 2.0, "text": "重点"}
                ]
            },
        }
    }

    validation = strategy_overlay_subtitle_occlusion_validation(
        strategy_review_context,
        render_plan=render_plan,
    )

    assert validation["status"] == "blocking"
    assert validation["blocking"] is True
    assert validation["reason"] == "strategy_overlay_subtitle_occlusion_unverified"
    assert validation["overlay_count"] == 1
    assert validation["unsafe_overlay_count"] == 1
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
        render_plan=render_plan,
    ) == ["strategy_overlay_subtitle_occlusion_unverified"]


def test_strategy_overlay_subtitle_occlusion_validation_accepts_safe_overlay_treatment() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_overlay_subtitle_occlusion": True,
                    }
                },
            }
        }
    }
    render_plan = {
        "subtitles": {"style": "bold_yellow_outline"},
        "editing_accents": {
            "emphasis_overlays": [
                {
                    "start_time": 1.0,
                    "end_time": 2.0,
                    "text": "重点",
                    "visual_treatment": "keyword_sticker",
                }
            ]
        },
    }

    validation = strategy_overlay_subtitle_occlusion_validation(
        strategy_review_context,
        render_plan=render_plan,
    )

    assert validation["status"] == "ok"
    assert validation["blocking"] is False
    assert validation["overlay_count"] == 1
    assert validation["unsafe_overlay_count"] == 0
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
        render_plan=render_plan,
    ) == []


def test_strategy_render_validation_summary_collects_overlay_blocking_reason_with_render_plan() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "narrative_assembly",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_overlay_subtitle_occlusion": True,
                    }
                },
            }
        }
    }
    render_plan = {
        "subtitles": {"style": "bold_yellow_outline"},
        "editing_accents": {
            "emphasis_overlays": [{"start_time": 1.0, "end_time": 2.0, "text": "重点"}]
        },
    }

    validation = strategy_render_validation_summary(
        strategy_review_context,
        render_plan=render_plan,
    )

    assert validation["status"] == "blocking"
    assert validation["reason"] == "strategy_overlay_subtitle_occlusion_unverified"
    assert validation["blocking_reasons"] == [
        "strategy_overlay_subtitle_occlusion_unverified",
    ]
    assert validation["overlay_count"] == 1
    assert validation["unsafe_overlay_count"] == 1
    assert {check["check"] for check in validation["checks"]} == {
        "strategy_timeline_preview_alignment",
        "strategy_storyboard_alignment",
        "strategy_overlay_subtitle_occlusion",
        "strategy_cut_boundary_evidence",
    }


def test_strategy_cut_boundary_validation_blocks_unresolved_high_risk_cuts() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "information_density",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 2},
        "blocking_high_risk_cut_count": 1,
        "high_risk_cuts": [
            {
                "start": 1.0,
                "end": 2.0,
                "boundary_keep_energy": 1.4,
                "blocking": True,
                "review_priority": "blocking",
            }
        ],
    }

    validation = strategy_cut_boundary_validation(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "blocking"
    assert validation["blocking"] is True
    assert validation["reason"] == "strategy_cut_boundary_high_risk_unresolved"
    assert validation["accepted_cut_count"] == 2
    assert validation["high_risk_cut_count"] == 1
    assert validation["blocking_high_risk_cut_count"] == 1
    assert validation["boundary_energy_evidence_count"] == 1
    assert validation["boundary_energy_evidence_count"] == 1
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    ) == ["strategy_cut_boundary_high_risk_unresolved"]


def test_strategy_cut_boundary_validation_accepts_advisory_boundary_evidence() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "information_density",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 1},
        "high_risk_cuts": [
            {
                "start": 1.0,
                "end": 2.0,
                "boundary_keep_energy": 1.2,
                "blocking": False,
                "review_priority": "advisory",
            }
        ],
    }

    validation = strategy_cut_boundary_validation(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "ok"
    assert validation["blocking"] is False
    assert validation["accepted_cut_count"] == 1
    assert validation["high_risk_cut_count"] == 1
    assert validation["blocking_high_risk_cut_count"] == 0
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    ) == []


def test_strategy_cut_boundary_validation_respects_explicit_zero_blocking_count() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "information_density",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 1},
        "blocking_high_risk_cut_count": 0,
        "high_risk_cuts": [
            {
                "start": 1.0,
                "end": 2.0,
                "boundary_keep_energy": 1.2,
                "blocking": True,
                "review_priority": "blocking",
            }
        ],
    }

    validation = strategy_cut_boundary_validation(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "ok"
    assert validation["blocking"] is False
    assert validation["blocking_high_risk_cut_count"] == 0
    assert validation["high_risk_cut_count"] == 1


def test_strategy_render_validation_summary_collects_cut_boundary_blocking_reason() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "information_density",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 2},
        "blocking_high_risk_cut_count": 1,
        "high_risk_cuts": [
            {
                "start": 1.0,
                "end": 2.0,
                "boundary_keep_energy": 1.4,
                "blocking": True,
            }
        ],
    }

    validation = strategy_render_validation_summary(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "blocking"
    assert validation["reason"] == "strategy_cut_boundary_high_risk_unresolved"
    assert validation["blocking_reasons"] == [
        "strategy_cut_boundary_high_risk_unresolved",
    ]
    assert validation["accepted_cut_count"] == 2
    assert validation["high_risk_cut_count"] == 1
    assert validation["blocking_high_risk_cut_count"] == 1


def test_strategy_cut_boundary_validation_requires_highlight_frame_samples() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "event_highlight",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                        "check_highlight_boundary_frames": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 1},
        "blocking_high_risk_cut_count": 0,
        "high_risk_cuts": [],
    }

    validation = strategy_cut_boundary_validation(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "blocking"
    assert validation["reason"] == "strategy_cut_boundary_frame_samples_missing"
    assert validation["boundary_frame_sample_count"] == 0
    assert render_output_blocking_reasons(
        avatar_result=None,
        subtitle_projection_repair=None,
        strategy_review_context=strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    ) == ["strategy_cut_boundary_frame_samples_missing"]


def test_strategy_cut_boundary_validation_accepts_highlight_sample_manifest() -> None:
    strategy_review_context = {
        "strategy_review_gates": {
            "pipeline_plan": {
                "strategy_type": "event_highlight",
                "review_gates": [],
                "strategy_policy": {
                    "render_validation_policy": {
                        "check_cut_boundaries": True,
                        "check_highlight_boundary_frames": True,
                    }
                },
            }
        }
    }
    cut_boundary_evidence = {
        "cut_analysis_summary": {"accepted_cut_count": 1},
        "blocking_high_risk_cut_count": 0,
        "cut_boundary_sample_manifest": {
            "schema": "strategy_cut_boundary_samples.v1",
            "boundary_samples": [
                {
                    "cut_id": "highlight_1",
                    "frame_paths": ["frames/highlight_1_before.jpg", "frames/highlight_1_after.jpg"],
                    "waveform_path": "waveforms/highlight_1.json",
                }
            ],
        },
    }

    validation = strategy_render_validation_summary(
        strategy_review_context,
        cut_boundary_evidence=cut_boundary_evidence,
    )

    assert validation["status"] == "ok"
    assert validation["boundary_frame_sample_count"] == 2
    assert validation["boundary_waveform_sample_count"] == 1


def test_creator_refine_and_insert_plan_fallbacks_are_blocking() -> None:
    assert creator_refine_output_fallback_reasons({"source": "rule_fallback"}) == [
        "creator_refine_rule_fallback",
    ]
    assert insert_plan_output_fallback_reasons({"selection_source": "deterministic_fallback"}) == [
        "insert_slot_deterministic_fallback",
    ]
    assert intelligent_copy_cover_brief_fallback_reasons({"strategy_source": "fallback"}) == [
        "intelligent_copy_cover_brief_fallback",
    ]
    assert intelligent_copy_material_context_fallback_reasons(
        packaging={"generation_repair_trace": [{"status": "deterministic_fallback"}]},
        cover_brief={"strategy_source": "fallback"},
    ) == [
        "platform_packaging_deterministic_fallback",
        "intelligent_copy_cover_brief_fallback",
    ]


def test_cover_selection_summary_marks_primary_fallback_output(tmp_path) -> None:
    output_path = tmp_path / "cover.png"
    output_path.write_bytes(b"cover")
    manifest_path = get_cover_manifest_path(output_path)
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "index": 1,
                    "path": str(output_path),
                    "seek_sec": 0.0,
                    "strategy_key": "fallback",
                    "strategy_label": "基础兜底",
                    "reason": "cover_generation_fallback",
                    "title_style": "preset_default",
                    "title": {"line1": "标题"},
                    "score": 0.0,
                    "ranking_source": "fallback",
                    "rank": 1,
                    "is_primary": True,
                    "review_recommended": False,
                    "score_gap_to_next": None,
                    "review_reason": "",
                }
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    summary = load_cover_selection_summary(output_path)

    assert summary is not None
    assert summary["fallback_generated"] is True
    assert summary["fallback_reason"] == "cover_generation_fallback"
    assert summary["ranking_source"] == "fallback"
